"""Provider logic, tested offline. The Anthropic client is replaced by a stub that returns real
``anthropic.types.Message`` objects, so parsing and cost accounting run exactly as in production."""
from __future__ import annotations

import anthropic
import pytest
from anthropic.types import Message

from ai_orchestrator.config import get_settings
from ai_orchestrator.llm import (
    AnthropicChat,
    BudgetExceeded,
    FakeChat,
    LLMError,
    SpendTracker,
    cost_usd,
    parse_json_object,
)


def make_message(blocks, input_tokens=1200, output_tokens=300, stop_reason="end_turn") -> Message:
    return Message.model_validate({
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-haiku-4-5",
        "content": blocks, "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    })


class StubMessages:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.reply


class StubClient:
    def __init__(self, **kw):
        self.messages = StubMessages(**kw)


def test_anthropic_joins_text_blocks_and_reports_real_usage():
    settings = get_settings()
    client = StubClient(reply=make_message([{"type": "text", "text": "Approval needs "},
                                            {"type": "text", "text": "a named engineer."}]))
    spend = SpendTracker(cap_usd=1.0)
    result = AnthropicChat("claude-haiku-4-5", settings, spend, client=client).complete("sys", "question")

    assert result.text == "Approval needs a named engineer."
    assert (result.input_tokens, result.output_tokens) == (1200, 300)
    # $1/M input + $5/M output for claude-haiku-4-5
    assert result.cost_usd == pytest.approx(0.0012 + 0.0015)
    assert spend.spent_usd == pytest.approx(result.cost_usd)
    sent = client.messages.calls[0]
    assert sent["system"] == "sys" and sent["messages"] == [{"role": "user", "content": "question"}]


def test_anthropic_spend_cap_blocks_further_calls():
    spend = SpendTracker(cap_usd=0.001)
    chat = AnthropicChat("claude-haiku-4-5", get_settings(), spend,
                         client=StubClient(reply=make_message([{"type": "text", "text": "ok"}])))
    chat.complete("s", "u")  # costs $0.0027 -> over the cap
    with pytest.raises(BudgetExceeded):
        chat.complete("s", "u")


def test_anthropic_api_errors_become_llm_errors():
    error = anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]
    chat = AnthropicChat("claude-haiku-4-5", get_settings(), SpendTracker(1.0), client=StubClient(error=error))
    with pytest.raises(LLMError):
        chat.complete("s", "u")


def test_anthropic_refusal_without_text_returns_explanation():
    chat = AnthropicChat("claude-haiku-4-5", get_settings(), SpendTracker(1.0),
                         client=StubClient(reply=make_message([], stop_reason="refusal")))
    result = chat.complete("s", "u")
    assert result.stop_reason == "refusal" and "declined" in result.text


def test_cost_for_unknown_or_local_model_is_zero():
    assert cost_usd(get_settings().pricing, "qwen2.5:1.5b", 1000, 1000) == 0.0


def test_parse_json_object_handles_prose_and_nested_braces():
    reply = 'Sure! {"verdict": "safe", "meta": {"a": 1}} done'
    assert parse_json_object(reply) == {"verdict": "safe", "meta": {"a": 1}}
    with pytest.raises(ValueError):
        parse_json_object("no json here")


def test_fake_chat_cites_first_source():
    user = "<sources>\n[security_policy.md]\nAll destructive writes need a named engineer to approve them.\n</sources>"
    assert FakeChat().complete("s", user).text.endswith("[security_policy.md]")
