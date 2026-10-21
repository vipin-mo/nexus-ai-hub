"""WebSocket server that the Java gateway forwards authenticated requests to.

* Handshake requires ``Authorization: Bearer <NEXUS_INTERNAL_TOKEN>`` (when configured),
  so only the gateway - which has already authenticated and authorised the caller -
  can submit work. ``principal`` and ``role`` in the payload are therefore trusted.
* ``GET /healthz`` answers plain HTTP for container health checks.
* At most ``max_concurrency`` agent runs execute at once. A request that finds every slot busy
  waits up to ``queue_wait_s`` for one (a bounded queue) and then gets a ``BUSY`` reply, so a
  burst of short requests is absorbed while a sustained overload still fails fast.
* Each run has a deadline (``request_timeout_s``).

Run: ``python -m ai_orchestrator.server``
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from ai_orchestrator.config import get_settings
from ai_orchestrator.graph import run_agent

log = logging.getLogger("nexus.server")

MAX_QUERY_CHARS = 4000
ROLES = {"ADMIN", "ANALYST", "INGEST_SERVICE"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")


class PayloadError(ValueError):
    pass


def validate(payload: dict) -> dict:
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise PayloadError("'query' must be a non-empty string")
    if len(query) > MAX_QUERY_CHARS:
        raise PayloadError(f"'query' exceeds {MAX_QUERY_CHARS} characters")
    principal = payload.get("principal", "")
    if not isinstance(principal, str) or not ID_PATTERN.match(principal):
        raise PayloadError("'principal' is required")
    role = payload.get("role")
    if role not in ROLES:
        raise PayloadError(f"'role' must be one of {sorted(ROLES)}")
    for field in ("session_id", "user_id", "request_id"):
        value = payload.get(field)
        if value is not None and (not isinstance(value, str) or not ID_PATTERN.match(value)):
            raise PayloadError(f"'{field}' has an invalid format")
    source = payload.get("source", "text")
    if source not in {"text", "audio"}:
        raise PayloadError("'source' must be 'text' or 'audio'")
    return {"query": query.strip(), "principal": principal, "role": role, "source": source,
            "session_id": payload.get("session_id"), "user_id": payload.get("user_id"),
            "request_id": payload.get("request_id")}


class AgentServer:
    def __init__(self):
        self.settings = get_settings()
        self.slots = asyncio.Semaphore(self.settings.max_concurrency)
        self.pool = ThreadPoolExecutor(max_workers=self.settings.max_concurrency, thread_name_prefix="agent")

    def process_request(self, connection: ServerConnection, request):
        if request.path == "/healthz":
            problem = dependency_problem(self.settings)
            if problem:
                return connection.respond(HTTPStatus.SERVICE_UNAVAILABLE, problem + "\n")
            return connection.respond(HTTPStatus.OK, "ok\n")
        token = self.settings.internal_token
        if token:
            supplied = request.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied, f"Bearer {token}"):
                log.warning("Rejected WebSocket handshake without a valid internal token")
                return connection.respond(HTTPStatus.UNAUTHORIZED, "unauthorized\n")
        return None

    async def handle(self, websocket: ServerConnection) -> None:
        try:
            async for message in websocket:
                await websocket.send(json.dumps(await self._serve_one(message)))
        except ConnectionClosed:
            pass

    async def _serve_one(self, message: str | bytes) -> dict:
        try:
            request = validate(json.loads(message))
        except (json.JSONDecodeError, PayloadError) as exc:
            return {"status": "INVALID_REQUEST", "error": str(exc)}
        try:
            await asyncio.wait_for(self.slots.acquire(), timeout=self.settings.queue_wait_s)
        except TimeoutError:
            return {"status": "BUSY", "request_id": request["request_id"],
                    "error": "orchestrator at capacity, retry later"}
        try:
            loop = asyncio.get_running_loop()
            query = request.pop("query")
            future = loop.run_in_executor(self.pool, lambda: run_agent(query, **request))
            try:
                return await asyncio.wait_for(future, timeout=self.settings.request_timeout_s)
            except TimeoutError:
                # The worker thread keeps running to completion; the slot is released now so
                # the server stays responsive. Timeouts are visible in the gateway audit log.
                return {"status": "TIMEOUT", "request_id": request["request_id"],
                        "error": f"no answer within {self.settings.request_timeout_s:.0f}s"}
        finally:
            self.slots.release()


_dependency_cache: dict[str, tuple[float, str | None]] = {}


def dependency_problem(settings) -> str | None:
    """Unhealthy if the local model server is unreachable: with a fail-closed guard every request would
    be blocked, so the container should report it instead of looking healthy. Cached for 10 s."""
    if settings.reasoner_provider == "fake":
        return None
    cached = _dependency_cache.get("ollama")
    if cached and time.monotonic() - cached[0] < 10:
        return cached[1]
    import requests

    try:
        requests.get(settings.ollama_base_url.rstrip("/") + "/api/tags", timeout=1.5).raise_for_status()
        problem = None
    except requests.RequestException as exc:
        problem = f"ollama unreachable at {settings.ollama_base_url}: {exc.__class__.__name__}"
        log.error("Health check: %s", problem)
    _dependency_cache["ollama"] = (time.monotonic(), problem)
    return problem


def warm_up() -> None:
    """Load the router, vector index and recommender before accepting traffic."""
    from ai_orchestrator.knowledge.rag import get_retriever
    from ai_orchestrator.recommender import get_recommender
    from ai_orchestrator.router import get_router
    from ai_orchestrator.telemetry import init_tracing

    init_tracing()
    get_router()
    get_retriever().ensure_ready()
    get_recommender()


async def main() -> None:
    settings = get_settings()
    if not settings.internal_token:
        log.warning("NEXUS_INTERNAL_TOKEN is not set: any local process can submit requests")
    server = AgentServer()
    await asyncio.get_running_loop().run_in_executor(server.pool, warm_up)
    async with serve(server.handle, settings.server_host, settings.server_port,
                     process_request=server.process_request, max_size=64 * 1024) as ws:
        log.info("NexusAI orchestrator listening on ws://%s:%d", settings.server_host, settings.server_port)
        await ws.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "bm25s", "websockets.server"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    asyncio.run(main())
