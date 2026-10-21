"""The NexusAI request workflow as a LangGraph state machine.

    guard ──blocked──► END
      │
    route ─► retrieve ─RECOMMENDATION──► recommend ──┐
                 └─────RAG_KNOWLEDGE / COMPLEX_REASONING──┴─► reason ─► END

Every request is grounded in retrieved documents, so a misrouted policy question still sees
the policy instead of being answered from the model's imagination. The route decides
(1) whether the tool recommender runs and (2) the model tier: with a cloud provider
configured, only ``cloud_routes`` intents (default COMPLEX_REASONING) are sent to Claude.

The graph's shape is fixed and testable; which branch runs is decided per request by the
trained intent router (with an LLM fallback for low-confidence queries).
``run_agent`` is the single entry point used by the WebSocket server, the evaluation
suite and the tests.
"""
from __future__ import annotations

import logging
import operator
import time
import uuid
from functools import lru_cache
from typing import Annotated, Any, TypedDict

import mlflow
from langgraph.graph import END, START, StateGraph
from mlflow.entities import SpanType

from ai_orchestrator.config import get_settings
from ai_orchestrator.knowledge.rag import get_retriever
from ai_orchestrator.llm import LLMError, get_fallback_reasoner, get_reasoner
from ai_orchestrator.memory import get_memory, session_key
from ai_orchestrator.pii import get_redactor
from ai_orchestrator.prompt_registry import get_prompt
from ai_orchestrator.prompts import build_reasoner_input
from ai_orchestrator.recommender import get_recommender
from ai_orchestrator.router import get_router
from ai_orchestrator.security import get_guard
from ai_orchestrator.telemetry import get_event_log, init_tracing

log = logging.getLogger(__name__)


class AgentState(TypedDict, total=False):
    request_id: str
    principal: str
    role: str
    user_id: str | None
    session_id: str
    source: str
    query: str
    clean_query: str
    security: dict
    route: dict
    sources: list[dict]
    recommendations: list[dict]
    history_turns: int
    answer: str
    llm: dict
    degraded: bool
    prompt_version: str
    timings_ms: Annotated[dict[str, float], operator.or_]


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def guard_node(state: AgentState) -> dict:
    """Block attacks, then redact PII so no model, log or store ever sees the raw identifiers."""
    started = time.perf_counter()
    guard = get_guard()
    query = state["query"]
    rules = guard.check_rules(query)
    redaction = get_redactor().redact(query) if rules.passed else None
    verdict = rules if not rules.passed or not guard.llm_scan else guard.check_llm(redaction.text)
    security = {**verdict.to_dict(), "policy_version": guard.version,
                "pii_redacted": redaction.counts if redaction else {}}
    update: dict[str, Any] = {"clean_query": redaction.text if redaction else "[blocked]", "security": security,
                              "timings_ms": {"guard": _elapsed(started)}}
    if not verdict.passed:
        update["answer"] = ("Request blocked by the security policy "
                            f"({verdict.category}). If this is a mistake, rephrase the question.")
    return update


def route_node(state: AgentState) -> dict:
    """Pick the branch: knowledge lookup, tool recommendation or open reasoning."""
    started = time.perf_counter()
    decision = get_router().route(state["clean_query"])
    return {"route": decision.to_dict(), "timings_ms": {"route": _elapsed(started)}}


def retrieve_node(state: AgentState) -> dict:
    """Hybrid (dense + BM25) retrieval from the internal policy documents."""
    started = time.perf_counter()
    with mlflow.start_span("hybrid_retrieval", span_type=SpanType.RETRIEVER) as span:
        chunks = get_retriever().retrieve(state["clean_query"])
        span.set_inputs({"query": state["clean_query"]})
        span.set_outputs({"sources": [c.source for c in chunks]})
    return {"sources": [c.to_dict() for c in chunks], "timings_ms": {"retrieve": _elapsed(started)}}


def recommend_node(state: AgentState) -> dict:
    """Rank tools the caller's role may use by request relevance and usage affinity."""
    started = time.perf_counter()
    recs = get_recommender().recommend(state["clean_query"], state["role"], state.get("user_id"))
    return {"recommendations": [r.to_dict() for r in recs], "timings_ms": {"recommend": _elapsed(started)}}


def reason_node(state: AgentState) -> dict:
    """Write the answer with the configured reasoner; fall back to the local model on cloud failure."""
    started = time.perf_counter()
    memory = get_memory()
    key = session_key(state["principal"], state["session_id"])
    history = memory.history(key)
    user_input = build_reasoner_input(state["clean_query"], state.get("sources", []), history,
                                      state.get("recommendations", []))
    degraded = False
    primary = get_reasoner(state["route"]["intent"])
    system_prompt, prompt_version = get_prompt("nexus-reasoner-system")
    try:
        result = primary.complete(system_prompt, user_input)
    except LLMError as exc:
        fallback = get_fallback_reasoner(primary)
        if fallback is None:
            raise
        log.warning("Primary reasoner failed (%s); answering with local fallback", exc)
        result = fallback.complete(system_prompt, user_input)
        degraded = True
    # Output filter: models can echo identifiers from documents or history.
    answer = get_redactor().redact(result.text).text
    memory.append(key, state["clean_query"], answer,
                  {"request_id": state["request_id"], "route": state.get("route", {}).get("intent")})
    return {"answer": answer, "llm": result.to_dict(), "degraded": degraded, "prompt_version": prompt_version,
            "history_turns": len(history), "timings_ms": {"reason": _elapsed(started)}}


def _dedupe_sources(chunks: list[dict]) -> list[dict]:
    best: dict[str, float] = {}
    for c in chunks:
        best[c["source"]] = max(best.get(c["source"], 0.0), c["score"])
    return [{"source": k, "score": v} for k, v in sorted(best.items(), key=lambda kv: -kv[1])]


def _after_guard(state: AgentState) -> str:
    return "route" if state["security"]["passed"] else END


def _after_retrieve(state: AgentState) -> str:
    return "recommend" if state["route"]["intent"] == "RECOMMENDATION" else "reason"


@lru_cache(maxsize=1)
def build_graph():
    g = StateGraph(AgentState)
    g.add_node("guard", guard_node)
    g.add_node("route", route_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("recommend", recommend_node)
    g.add_node("reason", reason_node)
    g.add_edge(START, "guard")
    g.add_conditional_edges("guard", _after_guard, ["route", END])
    g.add_edge("route", "retrieve")
    g.add_conditional_edges("retrieve", _after_retrieve, ["recommend", "reason"])
    g.add_edge("recommend", "reason")
    g.add_edge("reason", END)
    return g.compile()


@mlflow.trace(name="nexus_request", span_type=SpanType.CHAIN)
def _invoke(state: AgentState) -> tuple[dict, str | None]:
    final = build_graph().invoke(state)
    span = mlflow.get_current_active_span()
    if span is None:
        return final, None
    mlflow.update_current_trace(
        tags={"route": final.get("route", {}).get("intent", "BLOCKED"),
              "provider": final.get("llm", {}).get("provider", "none"),
              "source": state["source"], "prompt_version": final.get("prompt_version", "-")},
        session_id=session_key(state["principal"], state["session_id"]), user=state["principal"])
    return final, span.trace_id


def run_agent(query: str, *, principal: str = "local", role: str = "ANALYST", session_id: str | None = None,
              user_id: str | None = None, source: str = "text", request_id: str | None = None,
              include_context: bool = False) -> dict:
    """Run one request through the graph and return the response contract used by every client.

    ``include_context`` adds the retrieved chunk texts (used by the evaluation judge)."""
    init_tracing()
    started = time.perf_counter()
    state: AgentState = {
        "request_id": request_id or str(uuid.uuid4()), "principal": principal, "role": role,
        "user_id": user_id, "session_id": session_id or uuid.uuid4().hex[:12], "source": source,
        "query": query, "timings_ms": {},
    }
    status, error = "OK", None
    try:
        final, trace_id = _invoke(state)
        if not final["security"]["passed"]:
            status = "BLOCKED"
    except Exception as exc:  # the caller always gets a well-formed response
        log.exception("Request %s failed", state["request_id"])
        final = {**state, "answer": "The assistant failed to process this request."}
        trace_id, status, error = None, "ERROR", str(exc)

    llm = final.get("llm") or {}
    response = {
        "request_id": state["request_id"],
        "session_id": state["session_id"],
        "status": status,
        "answer": final.get("answer", ""),
        "route": final.get("route"),
        "security": final.get("security"),
        "sources": _dedupe_sources(final.get("sources", [])),
        "recommendations": final.get("recommendations", []),
        "usage": {"provider": llm.get("provider"), "model": llm.get("model"),
                  "input_tokens": llm.get("input_tokens", 0), "output_tokens": llm.get("output_tokens", 0),
                  "cost_usd": llm.get("cost_usd", 0.0)},
        "degraded": final.get("degraded", False),
        "latency_ms": _elapsed(started),
        "timings_ms": final.get("timings_ms", {}),
        "trace_id": trace_id,
        "prompt_version": final.get("prompt_version"),
        "error": error,
    }
    if include_context:
        response["context"] = [{"source": c["source"], "text": c["text"]} for c in final.get("sources", [])]
    get_event_log().write({
        "request_id": response["request_id"], "principal": principal, "role": role, "source": source,
        "status": status, "query": final.get("clean_query", query)[:300],
        "route": (response["route"] or {}).get("intent"), "route_source": (response["route"] or {}).get("source"),
        "route_confidence": (response["route"] or {}).get("confidence"),
        "security_passed": (response["security"] or {}).get("passed"),
        "security_category": (response["security"] or {}).get("category"),
        **{f"llm_{k}": v for k, v in response["usage"].items()},
        "n_sources": len(response["sources"]), "degraded": response["degraded"],
        "latency_ms": response["latency_ms"], "timings_ms": response["timings_ms"],
        "trace_id": trace_id, "prompt_version": response["prompt_version"], "environment": get_settings().environment,
    })
    return response


if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    question = " ".join(sys.argv[1:]) or "Who has to approve destructive database writes by an AI agent?"
    print(json.dumps(run_agent(question), indent=2))
