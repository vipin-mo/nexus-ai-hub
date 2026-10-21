"""Build the synthetic intent-routing training set (templates x slot fillers).

The hand-written ``challenge.csv`` is deliberately NOT generated here: it uses
different phrasing so its score shows how the router generalises beyond the
templates. Run: ``python -m ai_orchestrator.training.build_intent_dataset``.
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
PER_CLASS = 220
SEED = 7

POLICY_TOPICS = [
    "destructive database writes", "customer data storage", "conversation memory retention",
    "audit log retention", "API key rotation", "PII redaction", "deployment windows",
    "database migrations", "SEV1 incidents", "SEV2 incidents", "post-incident reviews",
    "critical vulnerability patching", "TLS for database connections", "leaked secrets",
    "the AI budget", "cloud model usage", "human-in-the-loop approvals", "admin access reviews",
    "data subject deletion requests", "raw log retention", "refund approvals", "rollback criteria",
    "vendor reviews", "prompt injection handling", "the analyst role", "the ingest service role",
]
RAG_TEMPLATES = [
    "What is our policy on {t}?", "What are the rules for {t}?", "Who needs to approve {t}?",
    "How long do we keep data for {t}?", "What does the handbook say about {t}?",
    "Is there a requirement around {t}?", "Where is {t} documented?", "Can you look up the guideline for {t}?",
    "according to company policy, how should {t} be handled", "what's the official procedure for {t}",
    "Summarize the internal standard for {t}.", "What timeline applies to {t}?",
    "Are we allowed to skip {t}?", "Quote the policy section covering {t}.",
    "per our runbook, what happens with {t}?", "What are the compliance requirements for {t}?",
    "remind me what the rule is for {t}", "What does governance say about {t}?",
]

TASKS = [
    "export query results to a spreadsheet", "open a ticket for a bug", "snapshot a dashboard for a meeting",
    "search the application logs for errors", "report on this week's AI spend", "page the on-call engineer",
    "freeze the audit log during an investigation", "issue a refund to a customer", "start an access review",
    "rotate an API key", "share KPI charts with leadership", "track a follow-up task",
    "find failed logins in the logs", "get cost numbers for the finance review", "escalate an outage",
]
REC_TEMPLATES = [
    "Which tool should I use to {t}?", "What tool can help me {t}?", "Recommend a tool to {t}.",
    "Suggest the best tool for when I need to {t}.", "I need to {t} - what should I use?",
    "is there a tool to {t}", "Which of our internal tools lets me {t}?",
    "What would you recommend for me to {t}?", "point me to the right tool to {t}",
    "What tools do people in my role use to {t}?", "Any tool suggestions to {t}?",
    "what's the quickest tool to {t}", "Give me tool recommendations so I can {t}.",
]

REASONING_SUBJECTS = [
    "our Q3 incident trends", "a migration from MongoDB to PostgreSQL",
    "the latency regression after Tuesday's release",
    "a three-step plan to reduce API costs", "the trade-offs between batch and streaming ETL",
    "an email to customers about planned downtime", "why p95 latency could rise while p50 stays flat",
    "a project plan for rolling out the assistant to two new teams", "the pros and cons of fine-tuning versus RAG",
    "how to estimate capacity for 10x traffic", "a summary of this error message for a non-technical manager",
    "how vector search differs from keyword search", "a testing strategy for the new gateway",
    "the root cause hypotheses for intermittent timeouts", "a comparison of three caching strategies",
    "the math behind a 99.9% availability target", "a short status update for leadership",
    "how to prioritise a backlog of 40 bugs", "risks in our current on-call rotation",
]
REASONING_TEMPLATES = [
    "Analyze {s}.", "Help me think through {s}.", "Can you draft {s}?", "Explain {s}.",
    "Write {s}.", "Break down {s} for me.", "Give me your reasoning on {s}.", "Walk me through {s}.",
    "I'd like a detailed analysis of {s}.", "brainstorm ideas about {s}", "Compare options for {s}.",
    "Evaluate {s} and recommend next steps.", "think step by step about {s}",
    "What are the implications of {s}?", "Outline {s}.",
]


def _expand(templates: list[str], fillers: list[str], key: str, rng: random.Random, n: int) -> list[str]:
    combos = sorted({tpl.format(**{key: f}) for tpl in templates for f in fillers})
    rng.shuffle(combos)
    return combos[:n]


def build(per_class: int = PER_CLASS, seed: int = SEED) -> list[tuple[str, str]]:
    rng = random.Random(seed)
    rows = [(q, "RAG_KNOWLEDGE") for q in _expand(RAG_TEMPLATES, POLICY_TOPICS, "t", rng, per_class)]
    rows += [(q, "RECOMMENDATION") for q in _expand(REC_TEMPLATES, TASKS, "t", rng, per_class)]
    rows += [(q, "COMPLEX_REASONING") for q in _expand(REASONING_TEMPLATES, REASONING_SUBJECTS, "s", rng, per_class)]
    rng.shuffle(rows)
    return rows


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rows = build()
    with open(DATA_DIR / "intents.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["text", "label"])
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {DATA_DIR / 'intents.csv'}")


if __name__ == "__main__":
    main()
