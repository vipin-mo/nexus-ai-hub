"""Runtime configuration: config/settings.yaml with environment-variable overrides.

Nothing here touches the network; settings are loaded on first use and cached.
Tests call ``get_settings.cache_clear()`` after changing the environment.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None else value


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip().upper() for item in value.split(",") if item.strip())


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p


@dataclass(frozen=True)
class Settings:
    environment: str
    data_dir: Path
    artifacts_dir: Path

    ollama_base_url: str
    local_model: str
    reasoner_provider: str
    cloud_routes: tuple[str, ...]
    reasoner_ollama_model: str
    anthropic_model: str
    max_output_tokens: int
    llm_timeout_s: float
    fallback_to_local: bool
    pricing: dict[str, dict[str, float]]
    spend_cap_usd: float

    router_model_path: Path
    router_model_uri: str
    router_confidence_threshold: float
    router_llm_fallback: bool

    embeddings: str
    embed_model: str
    chunk_size: int
    chunk_overlap: int
    retrieval_top_k: int

    mongo_uri: str
    memory_turns: int
    memory_retention_days: int

    mlflow_tracking_uri: str
    mlflow_experiment: str

    server_host: str
    server_port: int
    max_concurrency: int
    request_timeout_s: float
    internal_token: str

    security_llm_scan: bool
    security_fail_closed: bool

    @property
    def events_dir(self) -> Path:
        return self.data_dir / "events"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"


def load_yaml(name: str) -> dict[str, Any]:
    with open(CONFIG_DIR / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    raw = load_yaml("settings.yaml")
    paths, llm, router = raw.get("paths", {}), raw.get("llm", {}), raw.get("router", {})
    reasoner = llm.get("reasoner", {})
    retrieval, memory = raw.get("retrieval", {}), raw.get("memory", {})
    telemetry, server = raw.get("telemetry", {}), raw.get("server", {})
    security = load_yaml("security_policies.json").get("runtime", {})

    artifacts_dir = _resolve(_env_str("NEXUS_ARTIFACTS_DIR", paths.get("artifacts_dir", "artifacts")))
    provider = _env_str("NEXUS_REASONER_PROVIDER", reasoner.get("provider", "ollama")).lower()
    if provider not in {"ollama", "anthropic", "fake"}:
        raise ValueError(f"Unknown NEXUS_REASONER_PROVIDER '{provider}'")
    embeddings = _env_str("NEXUS_EMBEDDINGS", retrieval.get("embeddings", "ollama")).lower()
    if embeddings not in {"ollama", "hash"}:
        raise ValueError(f"Unknown NEXUS_EMBEDDINGS '{embeddings}'")

    return Settings(
        environment=_env_str("NEXUS_ENV", raw.get("environment", "development")),
        data_dir=_resolve(_env_str("NEXUS_DATA_DIR", paths.get("data_dir", "data"))),
        artifacts_dir=artifacts_dir,
        ollama_base_url=_env_str("OLLAMA_BASE_URL", llm.get("ollama_base_url", "http://localhost:11434")),
        local_model=_env_str("NEXUS_LOCAL_MODEL", llm.get("local_model", "llama3:8b")),
        reasoner_provider=provider,
        cloud_routes=_csv(_env_str("NEXUS_CLOUD_ROUTES",
                                   ",".join(reasoner.get("cloud_routes", ["COMPLEX_REASONING"])))),
        reasoner_ollama_model=_env_str("NEXUS_REASONER_OLLAMA_MODEL", reasoner.get("ollama_model", "qwen2.5:3b")),
        anthropic_model=_env_str("NEXUS_ANTHROPIC_MODEL", reasoner.get("anthropic_model", "claude-haiku-4-5")),
        max_output_tokens=int(reasoner.get("max_output_tokens", 700)),
        llm_timeout_s=float(reasoner.get("timeout_s", 90)),
        fallback_to_local=bool(reasoner.get("fallback_to_local", True)),
        pricing=llm.get("pricing_usd_per_million_tokens", {}),
        spend_cap_usd=float(_env_str("NEXUS_SPEND_CAP_USD", str(llm.get("spend_cap_usd_per_process", 2.0)))),
        router_model_path=artifacts_dir / router.get("model_file", "intent_router.joblib"),
        router_model_uri=_env_str("NEXUS_ROUTER_MODEL_URI", router.get("model_uri", "")),
        router_confidence_threshold=float(router.get("confidence_threshold", 0.45)),
        router_llm_fallback=_env_bool("NEXUS_ROUTER_LLM_FALLBACK", bool(router.get("llm_fallback", True))),
        embeddings=embeddings,
        embed_model=retrieval.get("embed_model", "nomic-embed-text"),
        chunk_size=int(retrieval.get("chunk_size", 220)),
        chunk_overlap=int(retrieval.get("chunk_overlap", 30)),
        retrieval_top_k=int(retrieval.get("top_k", 3)),
        mongo_uri=_env_str("MONGO_URI", memory.get("mongo_uri", "")),
        memory_turns=int(memory.get("history_turns", 3)),
        memory_retention_days=int(memory.get("retention_days", 30)),
        mlflow_tracking_uri=_env_str("MLFLOW_TRACKING_URI", telemetry.get("mlflow_tracking_uri", "")),
        mlflow_experiment=_env_str("MLFLOW_EXPERIMENT_NAME", telemetry.get("mlflow_experiment", "nexus-agent")),
        server_host=server.get("host", "0.0.0.0"),  # noqa: S104 - container port, not internet-facing
        server_port=int(_env_str("NEXUS_SERVER_PORT", str(server.get("port", 8765)))),
        max_concurrency=int(_env_str("NEXUS_MAX_CONCURRENCY", str(server.get("max_concurrency", 8)))),
        request_timeout_s=float(server.get("request_timeout_s", 120)),
        internal_token=_env_str("NEXUS_INTERNAL_TOKEN", server.get("internal_token", "")),
        security_llm_scan=_env_bool("NEXUS_SECURITY_LLM_SCAN", bool(security.get("llm_scan", True))),
        security_fail_closed=bool(security.get("fail_closed", True)),
    )
