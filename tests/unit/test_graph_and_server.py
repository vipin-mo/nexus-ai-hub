from __future__ import annotations

import asyncio
import json

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import InvalidStatus

from ai_orchestrator.config import get_settings
from ai_orchestrator.graph import run_agent
from ai_orchestrator.memory import get_memory, session_key
from ai_orchestrator.server import AgentServer, PayloadError, validate


# ---------- graph ----------
def test_knowledge_question_is_grounded_and_cited():
    r = run_agent("Who must approve destructive database writes made by an AI agent?", principal="t")
    assert r["status"] == "OK"
    assert r["route"]["intent"] == "RAG_KNOWLEDGE"
    assert "security_policy.md" in {s["source"] for s in r["sources"]}
    assert r["usage"]["provider"] == "fake" and r["usage"]["input_tokens"] > 0
    assert set(r["timings_ms"]) == {"guard", "route", "retrieve", "reason"}


def test_recommendation_route_runs_recommender():
    r = run_agent("Which tool should I use to export query results to a spreadsheet?", principal="t", role="ANALYST")
    assert r["route"]["intent"] == "RECOMMENDATION"
    assert r["recommendations"] and r["recommendations"][0]["id"] == "POSTGRES_EXPORT"
    assert "recommend" in r["timings_ms"]


def test_banned_request_is_blocked_before_any_model_call():
    r = run_agent("DROP TABLE users;", principal="t")
    assert r["status"] == "BLOCKED"
    assert r["usage"]["input_tokens"] == 0 and r["route"] is None


def test_request_events_are_logged(tmp_path):
    r = run_agent("What is the monthly external AI budget per team?", principal="events-test")
    lines = [json.loads(line) for p in get_settings().events_dir.glob("*.jsonl") for line in p.read_text().splitlines()]
    assert any(e["request_id"] == r["request_id"] and e["route"] for e in lines)


def test_sessions_are_isolated_per_principal():
    run_agent("What is our policy on API key rotation?", principal="alice", session_id="s1")
    memory = get_memory()
    assert memory.history(session_key("alice", "s1"))
    assert memory.history(session_key("bob", "s1")) == []


def test_cloud_failure_falls_back_to_local_model(settings_override, monkeypatch):
    from ai_orchestrator import llm

    settings_override(NEXUS_REASONER_PROVIDER="anthropic", ANTHROPIC_API_KEY="test-key-not-used")

    class Failing:
        provider, model = "anthropic", "claude-haiku-4-5"

        def complete(self, *a, **k):
            raise llm.LLMError("simulated outage")

    monkeypatch.setattr(llm, "_cloud_reasoner", lambda: Failing())
    monkeypatch.setattr(llm, "_local_reasoner", lambda: llm.FakeChat())
    r = run_agent("Draft a project plan for migrating our ETL to streaming", principal="t")
    assert r["status"] == "OK" and r["degraded"] is True and r["usage"]["provider"] == "fake"


def test_knowledge_routes_never_use_cloud_provider(settings_override, monkeypatch):
    from ai_orchestrator import llm

    settings_override(NEXUS_REASONER_PROVIDER="anthropic", ANTHROPIC_API_KEY="test-key-not-used")
    monkeypatch.setattr(llm, "_local_reasoner", lambda: llm.FakeChat("local"))
    assert llm.get_reasoner("RAG_KNOWLEDGE").model == "local"
    assert llm.get_reasoner("RECOMMENDATION").model == "local"


# ---------- server ----------
def test_payload_validation():
    ok = validate({"query": " hi ", "principal": "analyst-ui", "role": "ANALYST"})
    assert ok["query"] == "hi" and ok["source"] == "text"
    for bad in ({"query": "", "principal": "p", "role": "ANALYST"},
                {"query": "x", "principal": "p", "role": "ROOT"},
                {"query": "x" * 5000, "principal": "p", "role": "ANALYST"},
                {"query": "x", "principal": "p", "role": "ANALYST", "session_id": "../../etc"}):
        with pytest.raises(PayloadError):
            validate(bad)


def test_websocket_auth_health_and_round_trip(settings_override):
    settings_override(NEXUS_INTERNAL_TOKEN="s3cret")

    async def scenario():
        server = AgentServer()
        async with serve(server.handle, "127.0.0.1", 0, process_request=server.process_request) as ws:
            port = ws.sockets[0].getsockname()[1]
            with pytest.raises(InvalidStatus):
                async with connect(f"ws://127.0.0.1:{port}"):
                    pass
            async with connect(f"ws://127.0.0.1:{port}", additional_headers={"Authorization": "Bearer s3cret"}) as c:
                await c.send(json.dumps({"query": "What is the AI budget?", "principal": "gw", "role": "ANALYST"}))
                reply = json.loads(await c.recv())
                await c.send("not json")
                invalid = json.loads(await c.recv())
            return reply, invalid

    reply, invalid = asyncio.run(scenario())
    assert reply["status"] == "OK" and reply["answer"]
    assert invalid["status"] == "INVALID_REQUEST"


def test_recommendation_answer_cannot_push_tools_above_callers_role(monkeypatch):
    from ai_orchestrator import graph, llm

    class Leaky(llm.FakeChat):
        def complete(self, system, user, **kwargs):
            result = super().complete(system, user, **kwargs)
            assert 'caller_role="ANALYST"' in user          # the model is told the caller's role
            result.text = "You should use the REFUND_DISPATCH tool."
            return result

    monkeypatch.setattr(graph, "get_reasoner", lambda intent=None: Leaky())
    r = run_agent("Which tool should I use to refund a customer who was double charged?", principal="t",
                  role="ANALYST")
    assert r["route"]["intent"] == "RECOMMENDATION"
    assert "REFUND_DISPATCH (requires ADMIN)" in r["answer"]
    assert "your role (ANALYST) cannot use REFUND_DISPATCH" in r["answer"]
    assert "REFUND_DISPATCH" not in {t["id"] for t in r["recommendations"]}


def test_policy_answers_mentioning_admin_tools_are_not_altered():
    from ai_orchestrator.graph import enforce_tool_rbac

    text = "Analysts cannot run REFUND_DISPATCH; it requires ADMIN."
    assert enforce_tool_rbac(text, "ADMIN", []) == text


def test_server_queues_briefly_then_replies_busy(settings_override, monkeypatch):
    import time as _time

    from ai_orchestrator import server as srv

    settings_override(NEXUS_MAX_CONCURRENCY="1")
    monkeypatch.setattr(srv, "run_agent", lambda query, **kw: (_time.sleep(0.3), {"status": "OK"})[1])
    message = json.dumps({"query": "q", "principal": "gw", "role": "ANALYST"})

    async def scenario(queue_wait):
        server = AgentServer()
        server.settings = server.settings.__class__(**{**server.settings.__dict__, "queue_wait_s": queue_wait})
        return await asyncio.gather(server._serve_one(message), server._serve_one(message))

    assert [r["status"] for r in asyncio.run(scenario(2.0))] == ["OK", "OK"]       # second request waited
    assert sorted(r["status"] for r in asyncio.run(scenario(0.05))) == ["BUSY", "OK"]


def test_health_reports_unreachable_model_server(settings_override):
    from ai_orchestrator import server as srv

    settings_override(NEXUS_REASONER_PROVIDER="ollama", OLLAMA_BASE_URL="http://127.0.0.1:9")
    srv._dependency_cache.clear()
    problem = srv.dependency_problem(get_settings())
    assert problem and "ollama unreachable" in problem
    settings_override(NEXUS_REASONER_PROVIDER="fake")
    srv._dependency_cache.clear()
    assert srv.dependency_problem(get_settings()) is None
