"""Measure PII redaction recall: how many inserted PII values survive the whole pipeline.

Uses the ground truth written by generate_logs.py and the redacted logs in the lake.
A value counts as leaked if its exact text appears in the redacted message of the same line.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.getenv("NEXUS_DATA_DIR", ROOT / "data"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA)
    args = parser.parse_args()
    # The lake is partitioned and unordered, so lines are matched on (timestamp, level, component).
    raw_lines = (args.data_dir / "raw_logs" / "app.log").read_text(encoding="utf-8").splitlines()
    redacted = duckdb.execute(
        "SELECT strftime(ts, '%Y-%m-%d %H:%M:%S') AS ts, level, component, message FROM read_parquet(?)",
        [f"{args.data_dir}/lake/logs/*/*.parquet"]).fetchall()
    by_key: dict[tuple, list[str]] = {}
    for ts, level, component, message in redacted:
        by_key.setdefault((ts, level, component), []).append(message)

    inserted, leaked = Counter(), Counter()
    for row in map(json.loads, (args.data_dir / "raw_logs" / "pii_truth.jsonl").read_text().splitlines()):
        line = raw_lines[row["line"] - 1]
        key = (line[1:20], line.split()[2], line.split()[3])
        candidates = by_key.get(key, [])
        for kind, value in row["pii"].items():
            inserted[kind] += 1
            if not candidates or any(value in m for m in candidates):
                leaked[kind] += 1
    print(f"{'PII type':18s} {'inserted':>9s} {'leaked':>7s} {'recall':>8s}")
    for kind in sorted(inserted):
        print(f"{kind:18s} {inserted[kind]:9d} {leaked[kind]:7d} {1 - leaked[kind] / inserted[kind]:8.2%}")
    total, total_leaked = sum(inserted.values()), sum(leaked.values())
    print(f"{'ALL':18s} {total:9d} {total_leaked:7d} {1 - total_leaked / total:8.2%}")


if __name__ == "__main__":
    main()
