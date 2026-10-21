"""parser.pl behaviour (stage 1 of the log pipeline) and the shared card-number rule."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ai_orchestrator.pii import luhn_ok

PARSER = Path(__file__).parents[2] / "data_pipeline" / "scripts" / "parser.pl"
pytestmark = pytest.mark.skipif(shutil.which("perl") is None, reason="perl not installed")


def run_parser(tmp_path: Path, lines: list[str]) -> tuple[list[dict], dict, str]:
    raw = tmp_path / "raw.log"
    raw.write_text("\n".join(lines) + "\n")
    out, rejects, stats = tmp_path / "out.jsonl", tmp_path / "rejects.log", tmp_path / "stats.json"
    subprocess.run(["perl", str(PARSER), "--out", str(out), "--rejects", str(rejects), "--stats", str(stats),
                    str(raw)], check=True, capture_output=True)
    records = [json.loads(line) for line in out.read_text().splitlines()]
    return records, json.loads(stats.read_text()), rejects.read_text()


def test_redaction_keeps_the_rest_of_the_line(tmp_path):
    records, _, _ = run_parser(tmp_path, [
        "[2026-10-01 00:00:00] ERROR Auth - Unauthorized access attempt by Employee jsmith on node 4"])
    assert records[0]["message"] == "Unauthorized access attempt by Employee <USERNAME> on node 4"


def test_structured_pii_and_non_pii_numbers(tmp_path):
    records, stats, _ = run_parser(tmp_path, [
        "[2026-10-01 00:00:01] INFO Billing - card 4111 1111 1111 1111 for jo@nexus.com, (312) 555-0199, "
        "SSN 123-45-6789, ip 10.1.2.3, key sk-ant-abcdefghij0123456789",
        "[2026-10-01 00:00:02] INFO Orders - Order 4111111111111 shipped from 300.1.2.3",
        "[2026-10-01 00:00:03] WARN Auth - reset for jo (at) nexus [dot] com"])
    first = records[0]["message"]
    for placeholder in ("<CREDIT_CARD>", "<EMAIL>", "<PHONE>", "<SSN>", "<IP_ADDRESS>", "<SECRET>"):
        assert placeholder in first
    assert records[1]["message"] == "Order 4111111111111 shipped from 300.1.2.3"   # 13-digit order id, invalid IP
    assert records[2]["message"] == "reset for <EMAIL>"
    assert stats["redacted"]["EMAIL"] == 2 and stats["redacted"]["CREDIT_CARD"] == 1


def test_malformed_lines_are_rejected_and_counted(tmp_path):
    records, stats, rejects = run_parser(tmp_path, [
        "[2026-10-01 00:00:00] INFO Gateway - ok", "garbage without a header", "[bad ts] INFO X - y"])
    assert len(records) == 1
    assert stats == {**stats, "lines": 3, "parsed": 1, "rejected": 2}
    assert "garbage without a header" in rejects


def test_card_rule_requires_length_prefix_and_checksum():
    assert luhn_ok("4111 1111 1111 1111")         # Visa test number
    assert luhn_ok("378282246310005")              # Amex test number
    assert not luhn_ok("4111111111111")            # 13 digits: legacy length, treated as an order id
    assert not luhn_ok("9111111111111117")         # valid Luhn, no issuer prefix
    assert not luhn_ok("4111 1111 1111 1112")      # bad checksum
