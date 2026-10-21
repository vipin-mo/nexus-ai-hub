from __future__ import annotations

from evals import run_evals


def test_gate_flags_minimums_and_maximums(tmp_path, monkeypatch):
    thresholds = tmp_path / "thresholds.yaml"
    thresholds.write_text("offline:\n  retrieval.hybrid_hit_at_3: 0.8\n  security.rules_false_positive_rate_max: 0.05\n"
                          "  answers.fact_recall: 0.5\n")
    monkeypatch.setattr(run_evals, "THRESHOLDS", thresholds)
    results = {"retrieval": {"metrics": {"hybrid_hit_at_3": 0.75}},
               "security": {"metrics": {"rules_false_positive_rate": 0.10}}}
    failures = run_evals.check_gate("offline", results)
    assert len(failures) == 2  # answers suite not run -> not judged
    assert any("hybrid_hit_at_3" in f and "<" in f for f in failures)
    assert any("rules_false_positive_rate" in f and ">" in f for f in failures)


def test_gate_passes_when_metrics_meet_thresholds(tmp_path, monkeypatch):
    thresholds = tmp_path / "thresholds.yaml"
    thresholds.write_text("offline:\n  routing.classifier_accuracy: 0.8\n  recommendation.role_violations_max: 0\n")
    monkeypatch.setattr(run_evals, "THRESHOLDS", thresholds)
    results = {"routing": {"metrics": {"classifier_accuracy": 0.8667}},
               "recommendation": {"metrics": {"role_violations": 0}}}
    assert run_evals.check_gate("offline", results) == []
