"""Honest engine comparison: the hourly error-rate mart computed by PySpark vs DuckDB.

Both read the same sanitized JSON Lines file and produce the same table. Spark's NER step is
excluded so only the engines are compared. Prints wall-clock seconds for each.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.getenv("NEXUS_DATA_DIR", ROOT / "data"))


def spark_run(path: str) -> tuple[float, int]:
    from etl_spark_job import build_spark  # noqa: I001 - sibling script
    from pyspark.sql import functions as F

    spark = build_spark()
    spark.sparkContext.setLogLevel("ERROR")
    started = time.perf_counter()
    df = (spark.read.schema("ts string, level string, component string, message string").json(path)
          .withColumn("ts", F.to_timestamp("ts", "yyyy-MM-dd HH:mm:ss"))
          .groupBy(F.date_trunc("hour", "ts").alias("hour"), "component")
          .agg(F.count("*").alias("events"), F.sum((F.col("level") == "ERROR").cast("int")).alias("errors")))
    rows = df.count()
    elapsed = time.perf_counter() - started
    spark.stop()
    return elapsed, rows


def duckdb_run(path: str) -> tuple[float, int]:
    import duckdb

    started = time.perf_counter()
    rows = duckdb.execute("""
        SELECT date_trunc('hour', strptime(ts, '%Y-%m-%d %H:%M:%S')) AS hour, component,
               count(*) AS events, sum(CASE WHEN level = 'ERROR' THEN 1 ELSE 0 END) AS errors
        FROM read_json(?, format='newline_delimited',
                       columns={ts: 'VARCHAR', level: 'VARCHAR', component: 'VARCHAR', message: 'VARCHAR'})
        GROUP BY ALL""", [path]).fetchall()
    return time.perf_counter() - started, len(rows)


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DATA / "sanitized" / "logs.jsonl"))
    args = parser.parse_args()
    lines = sum(1 for _ in open(args.input, encoding="utf-8"))
    spark_s, spark_rows = spark_run(args.input)
    duck_s, duck_rows = duckdb_run(args.input)
    print(json.dumps({"input_rows": lines, "spark_seconds": round(spark_s, 2), "duckdb_seconds": round(duck_s, 3),
                      "result_rows": {"spark": spark_rows, "duckdb": duck_rows}}, indent=2))
