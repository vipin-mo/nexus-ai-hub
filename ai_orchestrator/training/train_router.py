"""Train, evaluate and register the intent router.

Model: TF-IDF (word 1-2 grams + character 3-5 grams) -> logistic regression.
Metrics: held-out split of the templated data and the hand-written challenge set.

With an MLflow tracking URI the run is logged, the model is registered as
``nexus-intent-router`` and promoted to the ``@champion`` alias only if it beats
the current champion's challenge-set macro-F1 (otherwise it becomes ``@challenger``).

    python -m ai_orchestrator.training.train_router                 # local artifact only
    python -m ai_orchestrator.training.train_router --mlflow-uri http://localhost:5001
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import FeatureUnion, Pipeline

from ai_orchestrator.config import get_settings
from ai_orchestrator.training.build_intent_dataset import build

DATA_DIR = Path(__file__).resolve().parent / "data"
CHALLENGE_CSV = Path(__file__).resolve().parents[2] / "evals" / "datasets" / "routing_challenge.csv"
LABELS = ["RAG_KNOWLEDGE", "RECOMMENDATION", "COMPLEX_REASONING"]
REGISTERED_NAME = "nexus-intent-router"
PARAMS = {"word_ngrams": "1-2", "char_ngrams": "3-5", "C": 4.0, "class_weight": "balanced",
          "test_size": 0.2, "seed": 42}


def _read_csv(path: Path) -> tuple[list[str], list[str]]:
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return [r["text"] for r in rows], [r["label"] for r in rows]


def make_pipeline() -> Pipeline:
    features = FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)),
    ])
    clf = LogisticRegression(C=PARAMS["C"], max_iter=2000, class_weight=PARAMS["class_weight"])
    return Pipeline([("features", features), ("clf", clf)])


def _scores(prefix: str, y_true: list[str], y_pred: list[str]) -> dict[str, float]:
    return {f"{prefix}_accuracy": round(accuracy_score(y_true, y_pred), 4),
            f"{prefix}_macro_f1": round(f1_score(y_true, y_pred, average="macro"), 4)}


def train(output_path: Path, mlflow_uri: str | None = None) -> dict:
    texts, labels = zip(*build(), strict=True)
    x_train, x_test, y_train, y_test = train_test_split(
        list(texts), list(labels), test_size=PARAMS["test_size"], random_state=PARAMS["seed"], stratify=labels)
    x_chal, y_chal = _read_csv(CHALLENGE_CSV)

    pipe = make_pipeline().fit(x_train, y_train)
    pred_test, pred_chal = pipe.predict(x_test), pipe.predict(x_chal)
    metrics = {**_scores("test", y_test, pred_test), **_scores("challenge", y_chal, pred_chal)}

    timings = []
    for q in x_chal:
        t0 = time.perf_counter()
        pipe.predict_proba([q])
        timings.append((time.perf_counter() - t0) * 1000)
    timings.sort()
    metrics["latency_p50_ms"] = round(statistics.median(timings), 3)
    metrics["latency_p95_ms"] = round(timings[int(len(timings) * 0.95) - 1], 3)

    report = classification_report(y_chal, pred_chal, labels=LABELS, output_dict=True, zero_division=0)
    matrix = confusion_matrix(y_chal, pred_chal, labels=LABELS).tolist()
    misses = [{"text": t, "expected": e, "predicted": p}
              for t, e, p in zip(x_chal, y_chal, pred_chal, strict=True) if e != p]
    meta = {"model": REGISTERED_NAME, "labels": LABELS, "params": PARAMS, "metrics": metrics,
            "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "train_rows": len(x_train), "challenge_rows": len(x_chal)}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipeline": pipe, "meta": meta}, output_path)
    output_path.with_suffix(".json").write_text(json.dumps({**meta, "challenge_misses": misses}, indent=2))

    if mlflow_uri:
        meta["registry"] = _log_to_mlflow(mlflow_uri, pipe, metrics, report, matrix, misses, x_chal[:3])
    return meta


def _log_to_mlflow(uri, pipe, metrics, report, matrix, misses, examples) -> dict:
    import mlflow
    from mlflow import MlflowClient
    from mlflow.models import infer_signature

    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment("nexus-intent-router")
    with mlflow.start_run(run_name=f"router-{int(time.time())}") as run:
        mlflow.log_params(PARAMS)
        mlflow.log_metrics(metrics)
        mlflow.log_dict(report, "challenge_classification_report.json")
        mlflow.log_dict({"labels": LABELS, "matrix": matrix}, "challenge_confusion_matrix.json")
        mlflow.log_dict({"misses": misses}, "challenge_misses.json")
        signature = infer_signature(list(examples), list(pipe.predict(examples)))
        info = mlflow.sklearn.log_model(pipe, name="model", signature=signature,
                                        registered_model_name=REGISTERED_NAME)
    client = MlflowClient()
    version = str(info.registered_model_version)
    new_score = metrics["challenge_macro_f1"]
    try:
        champion = client.get_model_version_by_alias(REGISTERED_NAME, "champion")
        old_score = client.get_run(champion.run_id).data.metrics.get("challenge_macro_f1", 0.0)
    except Exception:  # no champion yet
        champion, old_score = None, -1.0
    alias = "champion" if new_score >= old_score else "challenger"
    client.set_registered_model_alias(REGISTERED_NAME, alias, version)
    client.set_model_version_tag(REGISTERED_NAME, version, "challenge_macro_f1", str(new_score))
    print(f"registered {REGISTERED_NAME} v{version} as @{alias} "
          f"(challenge macro-F1 {new_score} vs champion {old_score if champion else 'none'})")
    return {"run_id": run.info.run_id, "version": version, "alias": alias}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=None, help="artifact path (default from settings)")
    parser.add_argument("--mlflow-uri", default=None, help="log + register the model in this MLflow server")
    args = parser.parse_args()
    output = args.output or get_settings().router_model_path
    meta = train(output, args.mlflow_uri)
    print(json.dumps(meta["metrics"], indent=2))
    print(f"saved router to {output}")


if __name__ == "__main__":
    main()
