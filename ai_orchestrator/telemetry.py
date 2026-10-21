"""Tracing (MLflow) and the local request-event log.

Two separate concerns with different failure policies:

* MLflow tracing is observability. It is set up lazily (never at import), probes the server
  with a 1.5 s timeout, uses async logging, and turns itself off if the server is
  unreachable - a dead MLflow server must never block or fail a user request.
* The JSONL event log under ``data/events`` is the local record of every request
  (redacted text only). The Spark ETL job loads it into the lake and warehouse.
  The authoritative security audit trail is the PostgreSQL ledger written by the gateway.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from ai_orchestrator.config import Settings, get_settings

log = logging.getLogger(__name__)

_init_lock = threading.Lock()
_tracing_enabled: bool | None = None


def init_tracing(settings: Settings | None = None) -> bool:
    """Configure MLflow tracing once per process. Returns True if traces will be recorded."""
    global _tracing_enabled
    if _tracing_enabled is not None:
        return _tracing_enabled
    with _init_lock:
        if _tracing_enabled is not None:
            return _tracing_enabled
        settings = settings or get_settings()
        os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "0")
        os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "5")
        import mlflow

        uri = settings.mlflow_tracking_uri
        if not uri:
            mlflow.tracing.disable()
            _tracing_enabled = False
            return False
        if uri.startswith("http"):
            import requests

            try:
                requests.get(uri.rstrip("/") + "/health", timeout=1.5).raise_for_status()
            except requests.RequestException as exc:
                log.warning("MLflow at %s unreachable (%s); tracing disabled for this process", uri, exc)
                mlflow.tracing.disable()
                _tracing_enabled = False
                return False
        try:
            mlflow.set_tracking_uri(uri)
            mlflow.set_experiment(settings.mlflow_experiment)
            mlflow.config.enable_async_logging(True)
            mlflow.langchain.autolog()   # LangGraph nodes + Ollama chat calls, with token usage
            mlflow.anthropic.autolog()   # Claude calls, with token usage
            _tracing_enabled = True
            log.info("MLflow tracing enabled (%s, experiment %s)", uri, settings.mlflow_experiment)
        except Exception as exc:  # misconfigured store, permissions, version skew
            log.warning("MLflow tracing setup failed (%s); tracing disabled", exc)
            mlflow.tracing.disable()
            _tracing_enabled = False
        return _tracing_enabled


def reset_tracing_state() -> None:
    """For tests."""
    global _tracing_enabled
    _tracing_enabled = None


class EventLog:
    """Append-only JSONL file per UTC day; one line per request."""

    def __init__(self, directory: Path):
        self.directory = directory
        self._lock = threading.Lock()

    def path_for(self, when: datetime) -> Path:
        return self.directory / f"agent_events-{when:%Y-%m-%d}.jsonl"

    def write(self, event: dict) -> None:
        now = datetime.now(UTC)
        event = {"ts": now.isoformat(timespec="milliseconds"), **event}
        line = json.dumps(event, default=str, separators=(",", ":"))
        try:
            with self._lock:
                self.directory.mkdir(parents=True, exist_ok=True)
                with open(self.path_for(now), "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
        except OSError as exc:
            log.error("Could not write request event: %s", exc)


@lru_cache(maxsize=1)
def get_event_log() -> EventLog:
    return EventLog(get_settings().events_dir)
