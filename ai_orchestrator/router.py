"""Intent routing: trained classifier first, local LLM only when the classifier is unsure."""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass
from functools import lru_cache

import joblib

from ai_orchestrator.config import Settings, get_settings
from ai_orchestrator.llm import LLMError, get_local_model, parse_json_object
from ai_orchestrator.prompt_registry import get_prompt

log = logging.getLogger(__name__)

INTENTS = ("RAG_KNOWLEDGE", "RECOMMENDATION", "COMPLEX_REASONING")


@dataclass
class RouteDecision:
    intent: str
    confidence: float
    source: str           # classifier | llm | classifier_low_confidence
    latency_ms: float
    model_version: str

    def to_dict(self) -> dict:
        return asdict(self)


class IntentRouter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.pipeline, self.version = self._load()

    def _load(self):
        s = self.settings
        if s.router_model_uri:
            try:
                import mlflow

                if s.mlflow_tracking_uri:
                    mlflow.set_tracking_uri(s.mlflow_tracking_uri)
                pipe = mlflow.sklearn.load_model(s.router_model_uri)
                log.info("Loaded router from MLflow registry %s", s.router_model_uri)
                return pipe, s.router_model_uri
            except Exception as exc:
                log.warning("Could not load router from %s (%s); using local artifact", s.router_model_uri, exc)
        if not s.router_model_path.exists():
            raise FileNotFoundError(
                f"Router model not found at {s.router_model_path}. "
                "Train it with: python -m ai_orchestrator.training.train_router")
        bundle = joblib.load(s.router_model_path)
        return bundle["pipeline"], f"local:{bundle['meta']['trained_at']}"

    def route(self, query: str) -> RouteDecision:
        started = time.perf_counter()
        probs = self.pipeline.predict_proba([query])[0]
        best = int(probs.argmax())
        intent, confidence = str(self.pipeline.classes_[best]), float(probs[best])
        source = "classifier"
        if confidence < self.settings.router_confidence_threshold:
            source = "classifier_low_confidence"
            if self.settings.router_llm_fallback:
                try:
                    reply = get_local_model().complete(get_prompt("nexus-router-fallback")[0], query,
                                                       max_tokens=40, json_mode=True)
                    llm_intent = str(parse_json_object(reply.text).get("intent", "")).upper()
                    if llm_intent in INTENTS:
                        intent, source = llm_intent, "llm"
                except (LLMError, ValueError) as exc:
                    log.warning("Router LLM fallback failed (%s); keeping classifier label", exc)
        return RouteDecision(intent, round(confidence, 4), source,
                             round((time.perf_counter() - started) * 1000, 3), self.version)


@lru_cache(maxsize=1)
def get_router() -> IntentRouter:
    return IntentRouter(get_settings())
