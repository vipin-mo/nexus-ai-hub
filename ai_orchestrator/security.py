"""Input guard: text normalisation + versioned rules + local LLM classifier.

Layer 1 (rules) runs on several normalised views of the input so trivial obfuscation does not
work: Unicode NFKC, zero-width characters removed, common Cyrillic look-alikes and leetspeak
mapped back, whitespace collapsed, and a "compact" view with all separators removed
("i g n o r e  previous" -> "ignoreprevious").

Layer 2 (optional) asks the local model to classify the text. It can only flag a request; it
never rewrites the query. If the classifier is unavailable or returns garbage, the request is
blocked when ``fail_closed`` is set (the default).

There are no bypass flags or trusted phrases: audio transcripts go through the same checks.
Detection rates are measured by the evaluation suite (tests/eval), not assumed.
"""
from __future__ import annotations

import base64
import binascii
import logging
import re
import time
import unicodedata
from dataclasses import asdict, dataclass
from functools import lru_cache

from ai_orchestrator.config import Settings, get_settings, load_yaml
from ai_orchestrator.llm import LLMError, get_local_model, parse_json_object
from ai_orchestrator.prompt_registry import get_prompt

log = logging.getLogger(__name__)

CONFUSABLES = str.maketrans({"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i",
                             "ѕ": "s", "ј": "j", "ԁ": "d", "ɡ": "g", "ո": "n"})
LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})


@dataclass
class Verdict:
    passed: bool
    layer: str                 # rules | llm | none
    category: str | None = None
    rule_id: str | None = None
    reason: str | None = None
    latency_ms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


BASE64_BLOB = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")


def _decoded_payloads(text: str) -> list[str]:
    """Decode base64-looking blobs so 'decode and follow: aWdub3Jl...' is checked as text."""
    out = []
    for blob in BASE64_BLOB.findall(text)[:5]:
        try:
            decoded = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            continue
        if decoded.isprintable():
            out.append(decoded)
    return out


def normalised_views(text: str) -> dict[str, list[str]]:
    text = " ".join([text, *_decoded_payloads(text)])
    base = unicodedata.normalize("NFKC", text)
    base = "".join(ch for ch in base if unicodedata.category(ch) != "Cf")  # zero-width, bidi controls
    base = base.translate(CONFUSABLES).casefold()
    spaced = re.sub(r"\s+", " ", base).strip()
    leet = spaced.translate(LEET)
    return {"spaced": [spaced, leet],
            "compact": [re.sub(r"[^a-z0-9]", "", spaced), re.sub(r"[^a-z0-9]", "", leet)]}


class SecurityGuard:
    def __init__(self, settings: Settings):
        policy = load_yaml("security_policies.json")
        self.version = policy.get("security_policy_version", "unknown")
        self.max_chars = int(policy.get("runtime", {}).get("max_query_chars", 4000))
        self.rules = [(r["id"], r["category"], r["variant"], re.compile(r["pattern"])) for r in policy["rules"]]
        self.llm_scan = settings.security_llm_scan
        self.fail_closed = settings.security_fail_closed

    def check_rules(self, text: str) -> Verdict:
        started = time.perf_counter()
        if len(text) > self.max_chars:
            return Verdict(False, "rules", "oversized_input", "max-chars", f"over {self.max_chars} characters")
        views = normalised_views(text)
        for rule_id, category, variant, pattern in self.rules:
            if any(pattern.search(view) for view in views[variant]):
                return Verdict(False, "rules", category, rule_id, "matched security rule",
                               round((time.perf_counter() - started) * 1000, 3))
        return Verdict(True, "none", latency_ms=round((time.perf_counter() - started) * 1000, 3))

    def check_llm(self, text: str) -> Verdict:
        started = time.perf_counter()
        try:
            prompt = get_prompt("nexus-security-scan")[0]
            reply = get_local_model().complete(prompt, f"<user_input>\n{text}\n</user_input>",
                                               max_tokens=80, json_mode=True)
            result = parse_json_object(reply.text)
            verdict = str(result.get("verdict", "")).lower()
            if verdict not in {"safe", "unsafe"}:
                raise ValueError(f"unexpected verdict {verdict!r}")
        except (LLMError, ValueError) as exc:
            elapsed = round((time.perf_counter() - started) * 1000, 2)
            log.warning("Security classifier unavailable (%s); fail_closed=%s", exc, self.fail_closed)
            if self.fail_closed:
                return Verdict(False, "llm", "scanner_unavailable", None, str(exc), elapsed)
            return Verdict(True, "none", reason="scanner unavailable, fail-open configured", latency_ms=elapsed)
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        if verdict == "unsafe":
            return Verdict(False, "llm", str(result.get("category") or "llm_flagged")[:40], None,
                           str(result.get("reason", ""))[:200], elapsed)
        return Verdict(True, "none", latency_ms=elapsed)

    def check(self, text: str, redacted_text: str | None = None) -> Verdict:
        """Rules on the raw text; the LLM classifier sees the PII-redacted text."""
        verdict = self.check_rules(text)
        if not verdict.passed or not self.llm_scan:
            return verdict
        llm_verdict = self.check_llm(redacted_text if redacted_text is not None else text)
        llm_verdict.latency_ms = round(llm_verdict.latency_ms + verdict.latency_ms, 2)
        return llm_verdict


@lru_cache(maxsize=1)
def get_guard() -> SecurityGuard:
    return SecurityGuard(get_settings())
