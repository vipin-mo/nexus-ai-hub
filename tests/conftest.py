"""Shared fixtures: every test runs offline (fake LLM, hashing embeddings, in-process memory)."""
from __future__ import annotations

import os

import pytest

OFFLINE_ENV = {
    "NEXUS_ENV": "test",
    "NEXUS_REASONER_PROVIDER": "fake",
    "NEXUS_EMBEDDINGS": "hash",
    "NEXUS_ROUTER_LLM_FALLBACK": "false",
    "NEXUS_SECURITY_LLM_SCAN": "false",
    "NEXUS_ROUTER_MODEL_URI": "",
    "MONGO_URI": "",
    "MLFLOW_TRACKING_URI": "",
    "NEXUS_INTERNAL_TOKEN": "",
    "MLFLOW_DISABLE_AGENT_HINT": "1",
    "MLFLOW_DISABLE_TELEMETRY": "true",
}


def clear_caches() -> None:
    from ai_orchestrator import config, graph, llm, memory, pii, recommender, router, security, telemetry
    from ai_orchestrator.knowledge import rag

    for fn in (config.get_settings, llm.spend_tracker, llm._local_reasoner, llm._cloud_reasoner,
               llm.get_local_model, memory.get_memory, recommender.get_recommender, router.get_router,
               rag.get_retriever, telemetry.get_event_log, graph.build_graph, security.get_guard,
               pii.get_redactor):
        if hasattr(fn, "cache_clear"):  # tests may monkeypatch a factory with a plain lambda
            fn.cache_clear()
    telemetry.reset_tracing_state()


@pytest.fixture(scope="session", autouse=True)
def offline_environment(tmp_path_factory):
    root = tmp_path_factory.mktemp("nexus")
    saved = {k: os.environ.get(k) for k in [*OFFLINE_ENV, "NEXUS_DATA_DIR", "NEXUS_ARTIFACTS_DIR"]}
    os.environ.update(OFFLINE_ENV)
    os.environ["NEXUS_DATA_DIR"] = str(root / "data")
    os.environ["NEXUS_ARTIFACTS_DIR"] = str(root / "artifacts")
    clear_caches()

    from ai_orchestrator.config import get_settings
    from ai_orchestrator.training.train_router import train

    train(get_settings().router_model_path)
    yield root
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    clear_caches()


@pytest.fixture
def settings_override(monkeypatch):
    """Change environment variables for one test and rebuild the cached singletons."""
    def apply(**env):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        clear_caches()
    yield apply
    clear_caches()
