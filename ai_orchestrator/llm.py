"""Chat-model providers behind one interface.

* ``OllamaChat``    - local models (free), token counts from Ollama's response metadata.
* ``AnthropicChat`` - Claude via the official SDK, token counts from ``message.usage``.
* ``FakeChat``      - deterministic, offline; used by unit tests and CI.

Every call returns an ``LLMResult`` with real (or, for FakeChat, clearly labelled
estimated) token counts and the USD cost from the pricing table in settings.yaml.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Protocol

from ai_orchestrator.config import Settings, get_settings

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """A provider call failed; callers may fall back to another provider."""


class BudgetExceeded(LLMError):
    """The per-process cloud spend cap was reached."""


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    stop_reason: str = "end_turn"

    def to_dict(self) -> dict:
        return asdict(self)


class ChatModel(Protocol):
    provider: str
    model: str

    def complete(self, system: str, user: str, *, max_tokens: int | None = None,
                 json_mode: bool = False) -> LLMResult: ...


def cost_usd(pricing: dict[str, dict[str, float]], model: str, input_tokens: int, output_tokens: int) -> float:
    price = pricing.get(model)
    if not price:
        return 0.0
    return round((input_tokens * price["input"] + output_tokens * price["output"]) / 1_000_000, 8)


class SpendTracker:
    """Thread-safe running total of cloud spend for this process."""

    def __init__(self, cap_usd: float):
        self.cap_usd = cap_usd
        self._spent = 0.0
        self._lock = threading.Lock()

    @property
    def spent_usd(self) -> float:
        return self._spent

    def check(self) -> None:
        if self._spent >= self.cap_usd:
            raise BudgetExceeded(f"Cloud spend cap of ${self.cap_usd:.2f} reached (spent ${self._spent:.4f})")

    def add(self, amount: float) -> None:
        with self._lock:
            self._spent += amount


class OllamaChat:
    provider = "ollama"

    def __init__(self, model: str, settings: Settings):
        self.model = model
        self._settings = settings
        self._clients: dict[tuple[bool, int], object] = {}
        self._lock = threading.Lock()

    def _client(self, json_mode: bool, max_tokens: int):
        key = (json_mode, max_tokens)
        with self._lock:
            if key not in self._clients:
                from langchain_ollama import ChatOllama

                self._clients[key] = ChatOllama(
                    model=self.model, base_url=self._settings.ollama_base_url, temperature=0,
                    num_predict=max_tokens, format="json" if json_mode else None,
                    client_kwargs={"timeout": self._settings.llm_timeout_s})
            return self._clients[key]

    def complete(self, system: str, user: str, *, max_tokens: int | None = None,
                 json_mode: bool = False) -> LLMResult:
        from langchain_core.messages import HumanMessage, SystemMessage

        chat = self._client(json_mode, max_tokens or self._settings.max_output_tokens)
        started = time.perf_counter()
        try:
            message = chat.invoke([SystemMessage(system), HumanMessage(user)])
        except Exception as exc:  # httpx/ollama raise several unrelated types
            raise LLMError(f"Ollama call to {self.model} failed: {exc}") from exc
        usage = message.usage_metadata or {}
        return LLMResult(
            text=str(message.content),
            provider=self.provider,
            model=self.model,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            cost_usd=0.0,
            latency_ms=(time.perf_counter() - started) * 1000,
            stop_reason=str(message.response_metadata.get("done_reason", "stop")),
        )


class AnthropicChat:
    provider = "anthropic"

    def __init__(self, model: str, settings: Settings, spend: SpendTracker, client=None):
        import anthropic

        self.model = model
        self._settings = settings
        self._spend = spend
        self._anthropic = anthropic
        self._client = client or anthropic.Anthropic(timeout=settings.llm_timeout_s, max_retries=2)

    def complete(self, system: str, user: str, *, max_tokens: int | None = None,
                 json_mode: bool = False) -> LLMResult:
        a = self._anthropic
        self._spend.check()
        if json_mode:
            system = f"{system}\nRespond with a single JSON object and nothing else."
        started = time.perf_counter()
        try:
            message = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens or self._settings.max_output_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except a.RateLimitError as exc:
            raise LLMError(f"Claude rate limited: {exc.message}") from exc
        except a.APIStatusError as exc:
            raise LLMError(f"Claude API error {exc.status_code}: {exc.message}") from exc
        except a.APIConnectionError as exc:
            raise LLMError(f"Claude connection error: {exc}") from exc

        # message.content is a list of content blocks; only text blocks carry the answer.
        text = "".join(block.text for block in message.content if block.type == "text")
        if message.stop_reason == "refusal":
            text = text or "The model declined to answer this request."
        cost = cost_usd(self._settings.pricing, self.model,
                        message.usage.input_tokens, message.usage.output_tokens)
        self._spend.add(cost)
        return LLMResult(
            text=text,
            provider=self.provider,
            model=self.model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            cost_usd=cost,
            latency_ms=(time.perf_counter() - started) * 1000,
            stop_reason=message.stop_reason or "end_turn",
        )


class FakeChat:
    """Deterministic stand-in for tests: answers by quoting the supplied context."""

    provider = "fake"

    def __init__(self, model: str = "fake-echo"):
        self.model = model

    def complete(self, system: str, user: str, *, max_tokens: int | None = None,
                 json_mode: bool = False) -> LLMResult:
        if json_mode:
            text = json.dumps({"verdict": "safe", "intent": "COMPLEX_REASONING", "reason": "fake"})
        else:
            block = re.search(r"<sources>\s*\[([^\]]+)\]\s*(.*?)(?:\n\n\[|</sources>)", user, flags=re.S)
            if block:
                name, body = block.group(1), block.group(2)
                sentences = [x for x in re.split(r"(?<=[.!?])\s+", re.sub(r"[#*|`]", " ", body)) if len(x.split()) > 4]
                text = f"{sentences[0].strip() if sentences else body.strip()[:200]} [{name}]"
            else:
                question = re.search(r"<question>\s*(.*?)\s*</question>", user, flags=re.S)
                asked = question.group(1) if question else user[:80]
                text = f"(offline test model) No knowledge-base context was needed for: {asked}"
        # Rough 4-chars-per-token estimate; FakeChat results are never billed.
        return LLMResult(text=text, provider=self.provider, model=self.model,
                         input_tokens=(len(system) + len(user)) // 4, output_tokens=len(text) // 4,
                         cost_usd=0.0, latency_ms=0.1)


@lru_cache(maxsize=1)
def spend_tracker() -> SpendTracker:
    return SpendTracker(get_settings().spend_cap_usd)


@lru_cache(maxsize=1)
def _local_reasoner() -> ChatModel:
    s = get_settings()
    return FakeChat() if s.reasoner_provider == "fake" else OllamaChat(s.reasoner_ollama_model, s)


@lru_cache(maxsize=1)
def _cloud_reasoner() -> ChatModel:
    s = get_settings()
    return AnthropicChat(s.anthropic_model, s, spend_tracker())


def get_reasoner(intent: str | None = None) -> ChatModel:
    """Model tiering: only intents listed in ``cloud_routes`` use the paid provider."""
    s = get_settings()
    if s.reasoner_provider == "anthropic" and (intent is None or intent in s.cloud_routes):
        return _cloud_reasoner()
    return _local_reasoner()


@lru_cache(maxsize=1)
def get_local_model() -> ChatModel:
    """Small local model for classification-style calls (security scan, routing fallback)."""
    s = get_settings()
    if s.reasoner_provider == "fake":
        return FakeChat("fake-classifier")
    return OllamaChat(s.local_model, s)


def get_fallback_reasoner(primary: ChatModel) -> ChatModel | None:
    """Local reasoner used when the cloud provider fails (rate limit, outage, budget)."""
    if primary.provider != "anthropic" or not get_settings().fallback_to_local:
        return None
    return _local_reasoner()


def parse_json_object(text: str) -> dict:
    """Parse the first JSON object in a model reply (non-greedy, tolerant of prose around it)."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    depth, start = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    start = None
    raise ValueError("no JSON object found in model output")
