"""Sweep the router's LLM-fallback confidence threshold for several fallback models.

Each model labels every challenge query once; accuracy at each threshold is then computed
offline (queries below the threshold take the LLM's label, the rest keep the classifier's).

    python -m evals.sweep_router_threshold --models qwen2.5:1.5b,qwen2.5:3b,llama3:8b
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from ai_orchestrator.config import get_settings
from ai_orchestrator.llm import LLMError, OllamaChat, parse_json_object
from ai_orchestrator.prompt_registry import get_prompt
from ai_orchestrator.router import INTENTS, get_router

ROOT = Path(__file__).resolve().parents[1]
THRESHOLDS = [0.0, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", default="qwen2.5:1.5b,qwen2.5:3b,llama3:8b")
    parser.add_argument("--out", type=Path, default=ROOT / "reports" / "router_threshold_sweep.json")
    args = parser.parse_args()

    settings, router = get_settings(), get_router()
    with open(ROOT / "evals" / "datasets" / "routing_challenge.csv", encoding="utf-8") as fh:
        cases = list(csv.DictReader(fh))
    rows = []
    for c in cases:
        probs = router.pipeline.predict_proba([c["text"]])[0]
        best = int(probs.argmax())
        rows.append({"text": c["text"], "y": c["label"], "clf": str(router.pipeline.classes_[best]),
                     "conf": float(probs[best])})

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    prompt = get_prompt("nexus-router-fallback")[0]
    for model in models:
        chat = OllamaChat(model, settings)
        for row in rows:
            try:
                reply = chat.complete(prompt, row["text"], max_tokens=40, json_mode=True)
                label = str(parse_json_object(reply.text).get("intent", "")).upper()
            except (LLMError, ValueError):
                label = "ERROR"
            row[model] = label if label in INTENTS else "INVALID"

    n = len(rows)
    result = {"cases": n, "classifier_only": round(sum(r["clf"] == r["y"] for r in rows) / n, 4),
              "llm_only": {m: round(sum(r[m] == r["y"] for r in rows) / n, 4) for m in models}, "sweep": []}
    for t in THRESHOLDS:
        entry = {"threshold": t, "fallback_rate": round(sum(r["conf"] < t for r in rows) / n, 4)}
        for m in models:
            entry[m] = round(sum((r[m] if r["conf"] < t else r["clf"]) == r["y"] for r in rows) / n, 4)
        result["sweep"].append(entry)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2))
    print(f"{n} challenge queries | classifier only {result['classifier_only']:.3f} | LLM only {result['llm_only']}")
    print("threshold  fallback  " + "  ".join(f"{m:>14s}" for m in models))
    for e in result["sweep"]:
        print(f"  {e['threshold']:.2f}     {e['fallback_rate']:.3f}   " + "  ".join(f"{e[m]:14.3f}" for m in models))


if __name__ == "__main__":
    main()
