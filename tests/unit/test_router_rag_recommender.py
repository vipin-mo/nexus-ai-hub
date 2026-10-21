from __future__ import annotations

import shutil

from ai_orchestrator.config import get_settings
from ai_orchestrator.knowledge.rag import DOCS_DIR, HybridRetriever
from ai_orchestrator.recommender import get_recommender
from ai_orchestrator.router import get_router


# ---------- router ----------
def test_router_routes_clear_examples():
    router = get_router()
    assert router.route("What is our policy on API key rotation?").intent == "RAG_KNOWLEDGE"
    assert router.route("Which tool should I use to export query results to CSV?").intent == "RECOMMENDATION"
    assert router.route("Draft a project plan for migrating our ETL to streaming").intent == "COMPLEX_REASONING"


def test_router_marks_low_confidence_when_fallback_disabled():
    decision = get_router().route("hmm")
    assert decision.source in {"classifier", "classifier_low_confidence"}
    if decision.confidence < get_settings().router_confidence_threshold:
        assert decision.source == "classifier_low_confidence"


# ---------- retrieval ----------
def test_hybrid_retrieval_finds_policy_document():
    retriever = HybridRetriever(get_settings())
    hits = retriever.retrieve("Who approves destructive database writes by an AI agent?")
    assert hits and "security_policy.md" in {h.source for h in hits}
    assert all(h.dense_rank or h.sparse_rank for h in hits)


def test_sparse_only_mode_works_without_embeddings():
    hits = HybridRetriever(get_settings()).retrieve("TTL index conversation memory 30 days", mode="sparse")
    assert hits[0].source == "data_retention_policy.md"


def test_index_rebuilds_when_documents_change(tmp_path):
    docs = tmp_path / "docs"
    shutil.copytree(DOCS_DIR, docs)
    first = HybridRetriever(get_settings(), docs_dir=docs)
    first.ensure_ready()
    (docs / "new_policy.md").write_text("# Parking policy\nVisitors park in garage level 3 called Zebra.")
    second = HybridRetriever(get_settings(), docs_dir=docs)
    second.ensure_ready()
    assert second.manifest != first.manifest
    assert second.chunk_count == first.chunk_count + 1
    assert second.retrieve("where do visitors park, garage Zebra")[0].source == "new_policy.md"


# ---------- recommender ----------
def test_recommender_never_returns_tools_above_callers_role():
    recs = get_recommender().recommend("issue a refund to a customer who was double charged", role="ANALYST")
    assert "REFUND_DISPATCH" not in {r.id for r in recs}
    admin_recs = get_recommender().recommend("issue a refund to a customer who was double charged", role="ADMIN")
    assert admin_recs[0].id == "REFUND_DISPATCH"


def test_recommender_ranks_relevant_tool_first():
    recs = get_recommender().recommend("export last month's orders to a spreadsheet", role="ANALYST", user_id="u001")
    assert recs[0].id == "POSTGRES_EXPORT"


def test_collaborative_filtering_beats_popularity_baseline():
    metrics = get_recommender().evaluate_offline()
    assert metrics["users_evaluated"] > 30
    assert metrics["cf_hit_at_1"] > metrics["popularity_hit_at_1"]
    assert metrics["cf_mrr"] > metrics["popularity_mrr"]
