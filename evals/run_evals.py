"""NexusAI evaluation suite with an MLflow-logged quality gate.

Suites (all run on labelled data in evals/datasets):
  retrieval       hit@1 / hit@3 / MRR for dense, BM25 and hybrid retrieval
  routing         classifier accuracy on the hand-written challenge set (+ LLM fallback when enabled)
  security        attack recall and false-positive rate (rules, + LLM classifier when enabled)
  recommendation  top-1 / top-3 accuracy, role violations, collaborative-filtering offline metrics
  answers         end-to-end run_agent via mlflow.genai.evaluate: fact recall, citations,
                  refusal on unanswerable questions, latency, tokens, cost; optional LLM judge

Profiles set the environment (models) and select the thresholds in evals/thresholds.yaml:
  offline   fake LLM + hashing embeddings + rules-only security   (CI, free, deterministic)
  local     Ollama models + nomic embeddings + LLM security scan  (free, needs Ollama)
  cloud     like local, but COMPLEX_REASONING answered by Claude  (paid - see docs/PAID_TESTS.md)

    python -m evals.run_evals --profile offline --gate
    python -m evals.run_evals --profile local --judge ollama --mlflow-uri http://localhost:5001
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "evals" / "datasets"
THRESHOLDS = ROOT / "evals" / "thresholds.yaml"

PROFILES = {
    "offline": {"NEXUS_REASONER_PROVIDER": "fake", "NEXUS_EMBEDDINGS": "hash", "NEXUS_SECURITY_LLM_SCAN": "false",
                "NEXUS_ROUTER_LLM_FALLBACK": "false", "MONGO_URI": ""},
    "local": {"NEXUS_REASONER_PROVIDER": "ollama", "NEXUS_EMBEDDINGS": "ollama", "NEXUS_SECURITY_LLM_SCAN": "true",
              "NEXUS_ROUTER_LLM_FALLBACK": "true", "MONGO_URI": ""},
    "cloud": {"NEXUS_REASONER_PROVIDER": "anthropic", "NEXUS_EMBEDDINGS": "ollama", "NEXUS_SECURITY_LLM_SCAN": "true",
              "NEXUS_ROUTER_LLM_FALLBACK": "true", "MONGO_URI": ""},
}


def jsonl(name: str) -> list[dict]:
    return [json.loads(line) for line in (DATASETS / name).read_text(encoding="utf-8").splitlines() if line.strip()]


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))], 2) if ordered else 0.0


# ---------------------------------------------------------------- suites
def eval_retrieval() -> tuple[dict, list[dict]]:
    from ai_orchestrator.knowledge.rag import get_retriever

    retriever = get_retriever()
    cases = [c for c in jsonl("rag_golden.jsonl") if c["expected_sources"]]
    metrics, rows = {}, []
    for mode in ("dense", "sparse", "hybrid"):
        h1 = h3 = rr = 0.0
        by_style: dict[str, list[int]] = {}
        for c in cases:
            sources = [h.source for h in retriever.retrieve(c["question"], top_k=3, mode=mode)]
            rank = next((i + 1 for i, s in enumerate(sources) if s in c["expected_sources"]), None)
            h1 += rank == 1
            h3 += rank is not None
            rr += 1 / rank if rank else 0
            by_style.setdefault(c["style"], []).append(rank is not None)
            if mode == "hybrid":
                rows.append({"id": c["id"], "question": c["question"], "retrieved": sources, "hit": rank is not None})
        n = len(cases)
        metrics.update({f"{mode}_hit_at_1": round(h1 / n, 4), f"{mode}_hit_at_3": round(h3 / n, 4),
                        f"{mode}_mrr": round(rr / n, 4)})
        for style, hits in by_style.items():
            metrics[f"{mode}_hit_at_3_{style}"] = round(sum(hits) / len(hits), 4)
    return metrics, rows


def eval_routing() -> tuple[dict, list[dict]]:
    from ai_orchestrator.config import get_settings
    from ai_orchestrator.router import get_router

    router = get_router()
    with open(DATASETS / "routing_challenge.csv", encoding="utf-8") as fh:
        cases = list(csv.DictReader(fh))
    correct_clf = correct_final = fallbacks = fallback_correct = 0
    latencies, rows = [], []
    for c in cases:
        probs = router.pipeline.predict_proba([c["text"]])[0]
        clf_label = str(router.pipeline.classes_[int(probs.argmax())])
        decision = router.route(c["text"])
        latencies.append(decision.latency_ms)
        correct_clf += clf_label == c["label"]
        correct_final += decision.intent == c["label"]
        if decision.source == "llm":
            fallbacks += 1
            fallback_correct += decision.intent == c["label"]
        rows.append({"text": c["text"], "expected": c["label"], "classifier": clf_label, "final": decision.intent,
                     "source": decision.source, "confidence": decision.confidence})
    n = len(cases)
    metrics = {"classifier_accuracy": round(correct_clf / n, 4), "final_accuracy": round(correct_final / n, 4),
               "llm_fallback_rate": round(fallbacks / n, 4), "latency_p50_ms": pct(latencies, 0.5),
               "latency_p95_ms": pct(latencies, 0.95),
               "confidence_threshold": get_settings().router_confidence_threshold}
    if fallbacks:
        metrics["llm_fallback_accuracy"] = round(fallback_correct / fallbacks, 4)
    return metrics, rows


def eval_security() -> tuple[dict, list[dict]]:
    from ai_orchestrator.security import get_guard

    guard = get_guard()
    cases = jsonl("security_cases.jsonl")
    counts = {"rules": [0, 0, 0, 0], "full": [0, 0, 0, 0]}  # tp, fn, fp, tn
    latencies, rows = [], []
    for c in cases:
        rules = guard.check_rules(c["text"])
        full = rules
        if rules.passed and guard.llm_scan:
            full = guard.check_llm(c["text"])
            latencies.append(full.latency_ms)
        for name, verdict in (("rules", rules), ("full", full)):
            blocked = not verdict.passed
            m = counts[name]
            if c["label"] == "attack":
                m[0 if blocked else 1] += 1
            else:
                m[2 if blocked else 3] += 1
        rows.append({"text": c["text"], "label": c["label"], "technique": c["technique"],
                     "rules_blocked": not rules.passed, "blocked": not full.passed, "layer": full.layer,
                     "category": full.category})
    metrics = {}
    for name, (tp, fn, fp, tn) in counts.items():
        if name == "full" and not guard.llm_scan:
            continue
        metrics[f"{name}_recall"] = round(tp / (tp + fn), 4)
        metrics[f"{name}_false_positive_rate"] = round(fp / (fp + tn), 4)
    if latencies:
        metrics["llm_scan_latency_p50_ms"] = pct(latencies, 0.5)
    metrics["policy_version"] = guard.version
    return metrics, rows


def eval_recommendation() -> tuple[dict, list[dict]]:
    from ai_orchestrator.recommender import get_recommender

    rec = get_recommender()
    cases = jsonl("recommendation_cases.jsonl")
    top1 = top3 = graded = violations = 0
    rows = []
    for c in cases:
        ids = [r.id for r in rec.recommend(c["query"], c["role"])]
        violations += len(set(ids) & set(c.get("forbidden", [])))
        if c.get("expected"):
            graded += 1
            top1 += bool(ids) and ids[0] == c["expected"]
            top3 += c["expected"] in ids
        rows.append({**c, "recommended": ids})
    metrics = {"top1_accuracy": round(top1 / graded, 4), "top3_accuracy": round(top3 / graded, 4),
               "role_violations": violations}
    metrics.update({f"offline_{k}": v for k, v in rec.evaluate_offline().items()})
    return metrics, rows


JUDGE_PROMPT = """\
You grade an assistant's answer for groundedness. Score 1-5:
5 = every factual claim is supported by the context; 3 = partly supported or partly invented;
1 = mostly unsupported or contradicts the context. If the context is empty and the answer says the
knowledge base does not cover the question, score 5.
Reply with JSON only: {"score": <1-5>, "rationale": "<one sentence>"}"""


def eval_answers(judge: str, workers: int) -> tuple[dict, list[dict]]:
    import mlflow
    from mlflow.entities import Feedback
    from mlflow.genai.scorers import scorer

    from ai_orchestrator.graph import run_agent
    from ai_orchestrator.llm import parse_json_object

    os.environ.setdefault("MLFLOW_GENAI_EVAL_MAX_WORKERS", str(workers))
    os.environ.setdefault("MLFLOW_GENAI_EVAL_SKIP_TRACE_VALIDATION", "true")
    cases = jsonl("rag_golden.jsonl")
    refusal = re.compile(r"does not cover|not cover|no information|doesn't|does not|cannot|can't"
                         r"|not (mentioned|provided)", re.IGNORECASE)

    @mlflow.trace(name="eval_predict")  # root span, so the trace response is this dict
    def predict(question: str) -> dict:
        r = run_agent(question, principal="eval-suite", role="ANALYST", include_context=True)
        return {"answer": r["answer"], "status": r["status"], "sources": [s["source"] for s in r["sources"]],
                "context": r.get("context", []), "latency_ms": r["latency_ms"], "usage": r["usage"],
                "route": (r["route"] or {}).get("intent")}

    @scorer
    def fact_recall(outputs, expectations) -> Feedback:
        pats = expectations["must_include"]
        hits = [bool(re.search(p, outputs["answer"], re.IGNORECASE)) for p in pats]
        if expectations["style"] == "unanswerable" and outputs["status"] == "BLOCKED":
            hits = [True] * len(pats)
        return Feedback(value=sum(hits) / len(pats), rationale=f"{sum(hits)}/{len(pats)} required facts present")

    @scorer
    def cites_expected_source(outputs, expectations) -> bool | None:
        if not expectations["expected_sources"]:
            return None
        return any(f"[{s}]" in outputs["answer"] for s in expectations["expected_sources"])

    @scorer
    def retrieved_expected_source(outputs, expectations) -> bool | None:
        if not expectations["expected_sources"]:
            return None
        return bool(set(outputs["sources"]) & set(expectations["expected_sources"]))

    @scorer
    def refuses_unanswerable(outputs, expectations) -> bool | None:
        if expectations["style"] != "unanswerable":
            return None
        return outputs["status"] == "BLOCKED" or bool(refusal.search(outputs["answer"]))

    scorers = [fact_recall, cites_expected_source, retrieved_expected_source, refuses_unanswerable]
    if judge != "none":
        judge_model = _judge_model(judge)

        @scorer
        def groundedness(inputs, outputs) -> Feedback:
            context = "\n\n".join(f"[{c['source']}] {c['text']}" for c in outputs["context"]) or "(empty)"
            user = f"<question>{inputs['question']}</question>\n<context>{context}</context>\n" \
                   f"<answer>{outputs['answer']}</answer>"
            try:
                reply = judge_model.complete(JUDGE_PROMPT, user, max_tokens=120, json_mode=True)
                result = parse_json_object(reply.text)
                score = float(result["score"])
            except Exception as exc:  # judge failures are reported, not fatal
                return Feedback(error=str(exc))
            return Feedback(value=score / 5, rationale=str(result.get("rationale", ""))[:300])

        scorers.append(groundedness)

    data = [{"inputs": {"question": c["question"]},
             "expectations": {"must_include": c["must_include"], "expected_sources": c["expected_sources"],
                              "style": c["style"]}} for c in cases]
    started = time.perf_counter()
    result = mlflow.genai.evaluate(data=data, predict_fn=predict, scorers=scorers)
    wall_s = time.perf_counter() - started

    table = result.tables["eval_results"]
    rows, latencies, cost, tokens = [], [], 0.0, 0
    for _, row in table.iterrows():
        resp = row.get("response")
        out = resp if isinstance(resp, dict) else json.loads(resp) if isinstance(resp, str) else {}
        latencies.append(out.get("latency_ms", 0.0))
        cost += out.get("usage", {}).get("cost_usd", 0.0) or 0.0
        usage = out.get("usage") or {}
        tokens += (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
        rows.append({"question": (row.get("request") or {}).get("question") if isinstance(row.get("request"), dict)
                     else row.get("request"), "answer": out.get("answer", "")[:400], "route": out.get("route"),
                     "sources": out.get("sources"), **{k: row[k] for k in row.index if k.endswith("/value")}})
    metrics = {k.replace("/mean", ""): round(float(v), 4) for k, v in result.metrics.items() if k.endswith("/mean")}
    metrics.update({"latency_p50_ms": pct(latencies, 0.5), "latency_p95_ms": pct(latencies, 0.95),
                    "total_cost_usd": round(cost, 6), "total_tokens": tokens, "wall_time_s": round(wall_s, 1),
                    "mlflow_run_id": result.run_id})
    return metrics, rows


def _judge_model(kind: str):
    from ai_orchestrator.config import get_settings
    from ai_orchestrator.llm import AnthropicChat, OllamaChat, spend_tracker

    s = get_settings()
    if kind == "anthropic":
        return AnthropicChat(s.anthropic_model, s, spend_tracker())
    return OllamaChat(os.getenv("NEXUS_JUDGE_MODEL", "llama3:latest"), s)


SUITES = {"retrieval": eval_retrieval, "routing": eval_routing, "security": eval_security,
          "recommendation": eval_recommendation}


# ---------------------------------------------------------------- gate + reporting
def check_gate(profile: str, results: dict) -> list[str]:
    limits = yaml.safe_load(THRESHOLDS.read_text())[profile]
    failures = []
    for key, limit in limits.items():
        suite, metric = key.split(".", 1)
        is_max = metric.endswith("_max")
        metric = metric.removesuffix("_max")
        value = results.get(suite, {}).get("metrics", {}).get(metric)
        if value is None:
            continue  # suite not run in this invocation
        if (value > limit) if is_max else (value < limit):
            failures.append(f"{suite}.{metric} = {value} ({'>' if is_max else '<'} {limit})")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="offline")
    parser.add_argument("--suites", default="retrieval,routing,security,recommendation,answers")
    parser.add_argument("--judge", choices=["none", "ollama", "anthropic"], default="none")
    parser.add_argument("--mlflow-uri", default=os.getenv("MLFLOW_TRACKING_URI", ""))
    parser.add_argument("--workers", type=int, default=4, help="parallel answer-suite requests")
    parser.add_argument("--gate", action="store_true", help="exit 1 if any metric misses its threshold")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    if args.profile == "cloud" and not os.getenv("ANTHROPIC_API_KEY"):
        print("profile 'cloud' needs ANTHROPIC_API_KEY (this run would make paid calls)", file=sys.stderr)
        return 2
    os.environ.update(PROFILES[args.profile])
    os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
    # MLflow usage telemetry lazily imports modules from scorer threads and can deadlock.
    os.environ["MLFLOW_DISABLE_TELEMETRY"] = "true"
    tmp = None
    if not args.mlflow_uri:
        tmp = tempfile.mkdtemp(prefix="nexus-evals-")
        args.mlflow_uri = f"sqlite:///{tmp}/mlflow.db"
    os.environ["MLFLOW_TRACKING_URI"] = args.mlflow_uri
    os.environ["MLFLOW_EXPERIMENT_NAME"] = "nexus-evals"
    if args.profile == "offline" and not os.getenv("NEXUS_DATA_DIR"):
        os.environ["NEXUS_DATA_DIR"] = tempfile.mkdtemp(prefix="nexus-evals-data-")

    import mlflow

    from ai_orchestrator.config import get_settings
    from ai_orchestrator.prompts import PROMPT_VERSION
    from ai_orchestrator.router import get_router
    from ai_orchestrator.telemetry import init_tracing

    settings = get_settings()
    if not settings.router_model_path.exists() and not settings.router_model_uri:
        from ai_orchestrator.training.train_router import train
        train(settings.router_model_path)
    init_tracing(settings)
    mlflow.set_tracking_uri(args.mlflow_uri)
    mlflow.set_experiment("nexus-evals")

    suites = [s.strip() for s in args.suites.split(",") if s.strip()]
    params = {"profile": args.profile, "reasoner_provider": settings.reasoner_provider,
              "local_model": settings.local_model, "reasoner_ollama_model": settings.reasoner_ollama_model,
              "anthropic_model": settings.anthropic_model if settings.reasoner_provider == "anthropic" else "-",
              "embeddings": settings.embeddings, "prompt_version": PROMPT_VERSION, "judge": args.judge,
              "router_version": get_router().version, "suites": ",".join(suites)}
    results: dict[str, dict] = {}
    with mlflow.start_run(run_name=f"eval-{args.profile}-{datetime.now(UTC):%Y%m%d-%H%M%S}") as run:
        mlflow.log_params(params)
        for suite in suites:
            started = time.perf_counter()
            if suite == "answers":
                metrics, rows = eval_answers(args.judge, args.workers)
            else:
                metrics, rows = SUITES[suite]()
            results[suite] = {"metrics": metrics, "seconds": round(time.perf_counter() - started, 1)}
            numeric = {f"{suite}.{k}": float(v) for k, v in metrics.items()
                       if isinstance(v, int | float) and not isinstance(v, bool)}
            mlflow.log_metrics(numeric)
            mlflow.log_dict({"rows": rows}, f"cases/{suite}.json")
            print(f"\n== {suite} ({results[suite]['seconds']}s)")
            for k, v in metrics.items():
                print(f"   {k:38s} {v}")
        failures = check_gate(args.profile, results)
        mlflow.set_tag("gate", "fail" if failures else "pass")
        report = {"created_at": datetime.now(UTC).isoformat(timespec="seconds"), "params": params,
                  "mlflow_run_id": run.info.run_id, "results": results, "gate_failures": failures}
        mlflow.log_dict(report, "eval_report.json")

    report_path = args.report or ROOT / "reports" / f"eval_{args.profile}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nreport: {report_path}\nmlflow run: {run.info.run_id} ({args.mlflow_uri})")
    if failures:
        print("\nQUALITY GATE FAILED:\n  " + "\n  ".join(failures))
    else:
        print("\nquality gate: pass")
    return 1 if (args.gate and failures) else 0


if __name__ == "__main__":
    sys.exit(main())
