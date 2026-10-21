"""Generate synthetic application logs with known PII, for the pipeline and its benchmarks.

Every PII value inserted is also written to a ground-truth file, so redaction recall can be
measured: a value "leaks" if it still appears in the sanitized output.

    python data_pipeline/scripts/generate_logs.py --lines 200000
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FIRST = ["James", "Maria", "Wei", "Aisha", "Carlos", "Priya", "John", "Elena", "Kwame", "Sofia", "Hiroshi",
         "Fatima", "Liam", "Olga", "Mateo", "Grace", "Arjun", "Chloe", "Omar", "Hannah"]
LAST = ["Smith", "Garcia", "Chen", "Khan", "Rodriguez", "Patel", "Johnson", "Petrova", "Mensah", "Rossi",
        "Tanaka", "Haddad", "Murphy", "Ivanova", "Lopez", "Kim", "Sharma", "Martin", "Farouk", "Weber"]
COMPONENTS = {  # component -> baseline error rate
    "GatewayController": 0.01, "AuthModule": 0.03, "AudioEngine": 0.02, "SecurityAgent": 0.04,
    "QueryProcessor": 0.015, "Billing": 0.02, "Orchestrator": 0.025, "VectorStore": 0.01,
}


def luhn_card(rng: random.Random) -> str:
    digits = [4] + [rng.randint(0, 9) for _ in range(14)]
    total = 0
    for i, d in enumerate(reversed(digits)):
        total += (d * 2 - 9 if d > 4 else d * 2) if i % 2 == 0 else d
    digits.append((10 - total % 10) % 10)
    s = "".join(map(str, digits))
    return f"{s[:4]} {s[4:8]} {s[8:12]} {s[12:]}"


def pii_value(kind: str, rng: random.Random) -> str:
    first, last = rng.choice(FIRST), rng.choice(LAST)
    if kind == "EMAIL":
        return f"{first.lower()}.{last.lower()}@nexus-corp.com"
    if kind == "EMAIL_OBFUSCATED":
        return f"{first.lower()} (at) nexus-corp [dot] com"
    if kind == "PERSON":
        return f"{first} {last}"
    if kind == "PHONE":
        return f"({rng.randint(200, 989)}) {rng.randint(200, 999)}-{rng.randint(0, 9999):04d}"
    if kind == "SSN":
        return f"{rng.randint(100, 665)}-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}"
    if kind == "CREDIT_CARD":
        return luhn_card(rng)
    if kind == "IP_ADDRESS":
        return f"10.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"
    if kind == "SECRET":
        return "sk-ant-" + "".join(rng.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(24))
    if kind == "USERNAME":
        return f"{first[0].lower()}{last.lower()}"
    raise ValueError(kind)


TEMPLATES = [  # (weight, level, template, PII kinds)
    (30, "INFO", "Request served in {ms} ms for tenant t{n}", []),
    (12, "INFO", "Cache hit ratio {pct}% on shard {n}", []),
    (10, "INFO", "Order {order} shipped to warehouse {n}", []),
    (12, "DEBUG", "Heartbeat from node-{n} ok", []),
    (8, "INFO", "User {EMAIL} logged in from {IP_ADDRESS}", ["EMAIL", "IP_ADDRESS"]),
    (4, "WARN", "Deprecated token used by {EMAIL}", ["EMAIL"]),
    (4, "WARN", "Password reset requested for {EMAIL_OBFUSCATED}", ["EMAIL_OBFUSCATED"]),
    (5, "INFO", "Callback scheduled for {PERSON} at {PHONE}", ["PERSON", "PHONE"]),
    (4, "INFO", "Refund approved for {PERSON}, card {CREDIT_CARD}", ["PERSON", "CREDIT_CARD"]),
    (3, "WARN", "KYC document for SSN {SSN} flagged for review", ["SSN"]),
    (1, "ERROR", "Unauthorized access attempt by Employee {USERNAME} on node {n}", ["USERNAME"]),
    (1, "ERROR", "Leaked credential detected in request body: {SECRET}", ["SECRET"]),
    (1, "ERROR", "Ticket escalated by {PERSON} - customer {EMAIL} unreachable", ["PERSON", "EMAIL"]),
    (5, "INFO", "Transcript received from audio-ingest, {ms} ms of speech", []),
]
WEIGHTS = [t[0] for t in TEMPLATES]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lines", type=int, default=50_000)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "raw_logs")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    start = datetime(2026, 10, 1, tzinfo=UTC)
    span_s = args.days * 86400
    incidents = [(rng.randint(0, span_s - 3600), rng.choice(list(COMPONENTS))) for _ in range(args.days)]
    log_path, truth_path = args.out / "app.log", args.out / "pii_truth.jsonl"
    malformed = 0
    with open(log_path, "w", encoding="utf-8") as log, open(truth_path, "w", encoding="utf-8") as truth:
        offsets = sorted(rng.randint(0, span_s) for _ in range(args.lines))
        for line_no, offset in enumerate(offsets, start=1):
            ts = start + timedelta(seconds=offset)
            if rng.random() < 0.004:  # truncated / garbage lines the parser must reject, not drop silently
                log.write(rng.choice(["<<binary blob>>", "stack trace continues...", "]]] partial line"]) + "\n")
                malformed += 1
                continue
            component = rng.choice(list(COMPONENTS))
            _, level, template, kinds = rng.choices(TEMPLATES, weights=WEIGHTS)[0]
            in_incident = any(o <= offset < o + 3600 and c == component for o, c in incidents)
            if level != "ERROR" and rng.random() < COMPONENTS[component] * (12 if in_incident else 1):
                level, template, kinds = "ERROR", "Upstream timeout after {ms} ms (attempt {n})", []
            values = {k: pii_value(k, rng) for k in kinds}
            message = template.format(ms=rng.randint(3, 4000), pct=rng.randint(40, 99), n=rng.randint(1, 64),
                                      order=rng.randint(10**12, 10**13 - 1), **values)
            log.write(f"[{ts:%Y-%m-%d %H:%M:%S}] {level} {component} - {message}\n")
            if values:
                truth.write(json.dumps({"line": line_no, "pii": values}) + "\n")
    print(json.dumps({"log": str(log_path), "truth": str(truth_path), "lines": args.lines,
                      "malformed": malformed, "incident_windows": len(incidents)}))


if __name__ == "__main__":
    main()
