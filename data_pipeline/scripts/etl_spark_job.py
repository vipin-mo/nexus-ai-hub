"""Stage 2 of the log pipeline (PySpark): NER redaction, Parquet data lake, marts, data-quality gates.

Inputs
  data/sanitized/logs.jsonl      parser.pl output (structured PII already redacted)
  data/sanitized/stats.json      parser.pl counts, used to reconcile row totals
  data/events/*.jsonl            per-request events written by the orchestrator

Outputs (data/lake, Parquet)
  logs/            partitioned by date, person names redacted with spaCy NER
  agent_events/    partitioned by date
  marts/           log_errors_hourly, incident_hours, agent_daily, agent_blocks, pii_summary
  _dq/latest.json  data-quality results; the job exits 1 if any check fails

Spark runs single-node (local[*]) here. At this data size DuckDB alone is faster - see
data_pipeline/scripts/benchmark_etl.py - Spark is used so the same job scales out unchanged.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.getenv("NEXUS_DATA_DIR", ROOT / "data"))

LEAK_PATTERNS = {
    "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "ssn": r"(^|[^0-9])[0-9]{3}-[0-9]{2}-[0-9]{4}([^0-9]|$)",
    "anthropic_key": r"sk-ant-[A-Za-z0-9_-]{10,}",
}


def ner_redact_batches(batches):
    """mapInArrow worker: load spaCy once per partition, redact PERSON entities."""
    import re

    import pyarrow as pa
    import spacy

    nlp = spacy.load("en_core_web_sm", disable=["parser", "lemmatizer", "attribute_ruler", "tagger"])
    candidate = re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b")  # only lines with two capitalised words go to NER
    identifier = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")  # CONSTANT_CASE names are never people
    for batch in batches:
        messages = batch.column("message").to_pylist()
        idx = [i for i, m in enumerate(messages) if m and candidate.search(m)]
        persons = [0] * len(messages)
        for i, doc in zip(idx, nlp.pipe([messages[i] for i in idx], batch_size=256), strict=True):
            ents = [e for e in doc.ents if e.label_ == "PERSON" and not identifier.search(e.text)]
            text = messages[i]
            for ent in reversed(ents):
                text = text[:ent.start_char] + "<PERSON>" + text[ent.end_char:]
            messages[i], persons[i] = text, len(ents)
        yield pa.RecordBatch.from_arrays(
            [batch.column("ts"), batch.column("level"), batch.column("component"),
             pa.array(messages, pa.string()), pa.array(persons, pa.int32())],
            names=["ts", "level", "component", "message", "persons_redacted"])


def build_spark():
    from pyspark.sql import SparkSession

    return (SparkSession.builder.appName("nexus-log-etl")
            .master(os.getenv("SPARK_MASTER", "local[*]"))
            .config("spark.sql.session.timeZone", "UTC")
            .config("spark.sql.shuffle.partitions", os.getenv("SPARK_SHUFFLE_PARTITIONS", "8"))
            .config("spark.ui.enabled", "false")
            .config("spark.driver.memory", os.getenv("SPARK_DRIVER_MEMORY", "2g"))
            .getOrCreate())


def run(data: Path) -> dict:
    from pyspark.sql import functions as F
    from pyspark.sql import types as T

    sanitized, lake = data / "sanitized", data / "lake"
    stats = json.loads((sanitized / "stats.json").read_text())
    spark = build_spark()
    spark.sparkContext.setLogLevel("WARN")
    timings, checks = {}, {}
    try:
        # ---- logs: parse, NER-redact, write to the lake
        t = time.perf_counter()
        log_schema = T.StructType([T.StructField(n, T.StringType()) for n in ("ts", "level", "component", "message")])
        raw = spark.read.schema(log_schema).json(str(sanitized / "logs.jsonl"))
        out_schema = "ts string, level string, component string, message string, persons_redacted int"
        logs = (raw.mapInArrow(ner_redact_batches, out_schema)
                .withColumn("ts", F.to_timestamp("ts", "yyyy-MM-dd HH:mm:ss"))
                .withColumn("date", F.to_date("ts")))
        logs.write.mode("overwrite").partitionBy("date").parquet(str(lake / "logs"))
        logs = spark.read.parquet(str(lake / "logs"))
        timings["logs_to_lake_s"] = round(time.perf_counter() - t, 2)

        # ---- data-quality gates
        lake_rows = logs.count()
        checks["rows_reconcile"] = {"lake_rows": lake_rows, "parser_parsed": stats["parsed"],
                                    "parser_lines": stats["lines"], "parser_rejected": stats["rejected"],
                                    "ok": lake_rows == stats["parsed"] == stats["lines"] - stats["rejected"]}
        null_ts = logs.filter(F.col("ts").isNull()).count()
        checks["timestamps_valid"] = {"null_ts": null_ts, "ok": null_ts == 0}
        leaks = {name: logs.filter(F.col("message").rlike(rx)).count() for name, rx in LEAK_PATTERNS.items()}
        checks["no_pii_leaks"] = {**leaks, "ok": sum(leaks.values()) == 0}
        reject_rate = stats["rejected"] / max(stats["lines"], 1)
        checks["reject_rate_below_2pct"] = {"reject_rate": round(reject_rate, 5), "ok": reject_rate < 0.02}

        # ---- log marts
        t = time.perf_counter()
        marts = lake / "marts"
        hourly = (logs.groupBy(F.date_trunc("hour", "ts").alias("hour"), "component")
                  .agg(F.count("*").alias("events"),
                       F.sum((F.col("level") == "ERROR").cast("int")).alias("errors"),
                       F.sum((F.col("level") == "WARN").cast("int")).alias("warnings"))
                  .withColumn("error_rate", F.round(F.col("errors") / F.col("events"), 4)))
        hourly.coalesce(1).write.mode("overwrite").parquet(str(marts / "log_errors_hourly"))
        baseline = hourly.groupBy("component").agg(F.expr("percentile_approx(error_rate, 0.5)").alias("baseline"))
        spike = F.col("error_rate") >= F.greatest(F.lit(0.15), F.col("baseline") * 4)  # >= 4x the component median
        incidents = (hourly.join(baseline, "component")
                     .filter((F.col("events") >= 10) & spike)
                     .select("hour", "component", "events", "errors", "error_rate",
                             F.round("baseline", 4).alias("baseline")))
        incidents.coalesce(1).write.mode("overwrite").parquet(str(marts / "incident_hours"))
        persons = logs.agg(F.sum("persons_redacted")).first()[0] or 0
        pii = spark.createDataFrame([(k, int(v), "parser.pl regex") for k, v in stats["redacted"].items()]
                                    + [("PERSON", int(persons), "spaCy NER (Spark)")],
                                    "pii_type string, redactions long, stage string")
        pii.coalesce(1).write.mode("overwrite").parquet(str(marts / "pii_summary"))

        # ---- agent request events
        events_rows = 0
        event_files = sorted((data / "events").glob("*.jsonl")) if (data / "events").exists() else []
        if event_files:
            events = (spark.read.json([str(p) for p in event_files])
                      .withColumn("ts", F.to_timestamp("ts")).withColumn("date", F.to_date("ts")))
            events.write.mode("overwrite").partitionBy("date").parquet(str(lake / "agent_events"))
            events = spark.read.parquet(str(lake / "agent_events"))
            events_rows = events.count()
            daily = (events.groupBy("date", F.coalesce("route", F.lit("BLOCKED")).alias("route"),
                                    F.coalesce("llm_provider", F.lit("none")).alias("provider"))
                     .agg(F.count("*").alias("requests"),
                          F.sum((F.col("status") == "BLOCKED").cast("int")).alias("blocked"),
                          F.sum(F.col("degraded").cast("int")).alias("degraded"),
                          F.expr("percentile_approx(latency_ms, 0.5)").alias("latency_p50_ms"),
                          F.expr("percentile_approx(latency_ms, 0.95)").alias("latency_p95_ms"),
                          F.sum("llm_input_tokens").alias("input_tokens"),
                          F.sum("llm_output_tokens").alias("output_tokens"),
                          F.round(F.sum("llm_cost_usd"), 6).alias("cost_usd")))
            daily.coalesce(1).write.mode("overwrite").parquet(str(marts / "agent_daily"))
            blocks = (events.filter(F.col("status") == "BLOCKED")
                      .groupBy("date", "source", "security_category").count().withColumnRenamed("count", "blocked"))
            blocks.coalesce(1).write.mode("overwrite").parquet(str(marts / "agent_blocks"))
        timings["marts_s"] = round(time.perf_counter() - t, 2)
    finally:
        spark.stop()

    result = {"log_rows": lake_rows, "event_rows": events_rows, "persons_redacted": int(persons),
              "timings": timings, "checks": checks, "ok": all(c["ok"] for c in checks.values())}
    (lake / "_dq").mkdir(parents=True, exist_ok=True)
    (lake / "_dq" / "latest.json").write_text(json.dumps(result, indent=2, default=str))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=DATA)
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        result = run(args.data_dir)
    except FileNotFoundError as exc:
        print(f"ETL input missing: {exc}. Run parser.pl first.", file=sys.stderr)
        return 2
    result["total_s"] = round(time.perf_counter() - started, 2)
    print(json.dumps(result, indent=2, default=str))
    if not result["ok"]:
        failed = [name for name, c in result["checks"].items() if not c["ok"]]
        print(f"DATA QUALITY FAILED: {failed}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
