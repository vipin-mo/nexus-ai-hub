"""Stage 3: load the Parquet marts into the DuckDB warehouse used by the dashboard.

DuckDB allows one writer per database file, and an open reader blocks a writer in another
process. Instead of writing into the live file, the warehouse is rebuilt in a temporary file
and swapped in with an atomic rename, so the dashboard never sees a lock or a half-written table.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.getenv("NEXUS_DATA_DIR", ROOT / "data"))


def build(data: Path) -> dict:
    marts = data / "lake" / "marts"
    warehouse_dir = data / "warehouse"
    warehouse_dir.mkdir(parents=True, exist_ok=True)
    target = warehouse_dir / "analytics.duckdb"
    tmp = warehouse_dir / f".analytics-{os.getpid()}.duckdb"
    tables = {}
    started = time.perf_counter()
    with duckdb.connect(str(tmp)) as con:
        for mart in sorted(p for p in marts.iterdir() if p.is_dir()):
            # table names come from mart directories written by our own Spark job
            con.execute(f"CREATE TABLE {mart.name} AS SELECT * FROM read_parquet(?)",  # noqa: S608
                        [str(mart / "*.parquet")])
            tables[mart.name] = con.execute(f"SELECT count(*) FROM {mart.name}").fetchone()[0]  # noqa: S608
        dq = json.loads((data / "lake" / "_dq" / "latest.json").read_text())
        con.execute("CREATE TABLE pipeline_runs (loaded_at TIMESTAMP, log_rows BIGINT, event_rows BIGINT, "
                    "dq_ok BOOLEAN, dq JSON)")
        con.execute("INSERT INTO pipeline_runs VALUES (?, ?, ?, ?, ?)",
                    [datetime.now(UTC).replace(tzinfo=None), dq["log_rows"], dq["event_rows"], dq["ok"],
                     json.dumps(dq["checks"])])
    os.replace(tmp, target)  # atomic on POSIX: readers see the old file or the new one, never a partial one
    return {"warehouse": str(target), "tables": tables, "seconds": round(time.perf_counter() - started, 2)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA)
    print(json.dumps(build(parser.parse_args().data_dir), indent=2))
