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

from ai_orchestrator.config import get_settings, load_yaml
from ai_orchestrator.knowledge.rag import get_retriever
from ai_orchestrator.llm import LLMError, get_fallback_reasoner, get_reasoner
from ai_orchestrator.memory import get_memory, session_key
from ai_orchestrator.prompts import PROMPT_VERSION, REASONER_SYSTEM_PROMPT, build_reasoner_input
from ai_orchestrator.recommender import get_recommender
from ai_orchestrator.router import get_router
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
    timings_ms: Annotated[dict[str, float], operator.or_]


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def guard_node(state: AgentState) -> dict:
    """Reject requests that match the security policy before any model sees them."""
    started = time.perf_counter()
    query = state["query"]
    banned = load_yaml("security_policies.json").get("banned_keywords", [])
    hit = next((kw for kw in banned if kw.lower() in query.lower()), None)
    security = {"passed": hit is None, "layer": "rules" if hit else "none",
                "category": "banned_keyword" if hit else None, "detail": hit}
    update: dict[str, Any] = {"clean_query": query, "security": security, "timings_ms": {"guard": _elapsed(started)}}
    if hit:
        update["answer"] = "Request blocked by the security policy."
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
    try:
        result = primary.complete(REASONER_SYSTEM_PROMPT, user_input)
    except LLMError as exc:
        fallback = get_fallback_reasoner(primary)
        if fallback is None:
            raise
        log.warning("Primary reasoner failed (%s); answering with local fallback", exc)
        result = fallback.complete(REASONER_SYSTEM_PROMPT, user_input)
        degraded = True
    memory.append(key, state["clean_query"], result.text,
                  {"request_id": state["request_id"], "route": state.get("route", {}).get("intent")})
    return {"answer": result.text, "llm": result.to_dict(), "degraded": degraded,
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
              "source": state["source"], "prompt_version": PROMPT_VERSION},
        session_id=session_key(state["principal"], state["session_id"]), user=state["principal"])
    return final, span.trace_id


def run_agent(query: str, *, principal: str = "local", role: str = "ANALYST", session_id: str | None = None,
              user_id: str | None = None, source: str = "text", request_id: str | None = None) -> dict:
    """Run one request through the graph and return the response contract used by every client."""
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
        "prompt_version": PROMPT_VERSION,
        "error": error,
    }
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
        "trace_id": trace_id, "prompt_version": PROMPT_VERSION, "environment": get_settings().environment,
    })
    return response


if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    question = " ".join(sys.argv[1:]) or "Who has to approve destructive database writes by an AI agent?"
    print(json.dumps(run_agent(question), indent=2))
