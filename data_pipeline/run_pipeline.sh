#!/usr/bin/env bash
# Batch log pipeline: (generate sample logs) -> Perl parse/redact -> Spark NER + lake + marts + DQ
# -> DuckDB warehouse -> PII recall report. Exits non-zero if any stage or data-quality check fails.
#   LINES=200000 bash data_pipeline/run_pipeline.sh
set -euo pipefail
cd "$(dirname "$0")/.."
DATA="${NEXUS_DATA_DIR:-data}"
mkdir -p "$DATA/sanitized"

if [[ ! -f "$DATA/raw_logs/app.log" || "${REGENERATE:-0}" == "1" ]]; then
  echo "== generating ${LINES:-50000} synthetic log lines"
  python data_pipeline/scripts/generate_logs.py --lines "${LINES:-50000}" --out "$DATA/raw_logs"
fi

echo "== stage 1: parser.pl"
perl data_pipeline/scripts/parser.pl --out "$DATA/sanitized/logs.jsonl" --rejects "$DATA/sanitized/rejects.log" \
  --stats "$DATA/sanitized/stats.json" "$DATA/raw_logs/app.log"

echo "== stage 2: Spark (NER, lake, marts, data quality)"
python data_pipeline/scripts/etl_spark_job.py --data-dir "$DATA"

echo "== stage 3: DuckDB warehouse"
python data_pipeline/scripts/load_warehouse.py --data-dir "$DATA"

if [[ -f "$DATA/raw_logs/pii_truth.jsonl" ]]; then
  echo "== PII redaction recall"
  python data_pipeline/scripts/pii_recall.py --data-dir "$DATA"
fi
