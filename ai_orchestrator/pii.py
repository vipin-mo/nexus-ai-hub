"""PII redaction for everything that leaves the request boundary.

Structured identifiers are found with regular expressions (payment cards are Luhn-checked
to avoid redacting order numbers); person names are found with spaCy NER, because regex
cannot recognise names reliably. Matches are replaced with typed placeholders
(``<EMAIL>``, ``<PERSON>`` ...) so downstream models still understand the sentence.

Redacted text is what gets stored (memory, event log, MLflow traces) and what is sent to any
model, local or cloud. Recall on synthetic data is reported by the data-pipeline benchmark.
"""
from __future__ import annotations

import logging
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache

from ai_orchestrator.config import load_yaml

log = logging.getLogger(__name__)

_BR_OPEN, _BR_CLOSE = r"[\(\[\{<]", r"[\)\]\}>]"
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("SECRET", re.compile(
        r"sk-ant-[A-Za-z0-9_-]{10,}|\bsk-[A-Za-z0-9]{20,}|\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{30,}"
        r"|\bxox[baprs]-[A-Za-z0-9-]{10,}|\b[Bb]earer\s+[A-Za-z0-9._~+/-]{20,}=*"
        r"|-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("EMAIL", re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
        rf"|\b[\w.+-]+\s*{_BR_OPEN}\s*at\s*{_BR_CLOSE}\s*[\w-]+(?:\s*(?:{_BR_OPEN}\s*dot\s*{_BR_CLOSE}|\.)\s*[\w-]+)+"
        r"|\b[\w.+-]+\s+at\s+[\w-]+\s+dot\s+[A-Za-z]{2,}\b", re.IGNORECASE)),
    ("CREDIT_CARD", re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")),
    ("SSN", re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")),
    ("PHONE", re.compile(
        r"(?<![\w-])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?![\w-])"
        r"|(?<![\w-])\+\d{1,3}[\s.-]\d{2,4}[\s.-]\d{3,4}[\s.-]\d{3,4}(?![\w-])")),
    ("IP_ADDRESS", re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])")),
]
PLACEHOLDER = re.compile(r"<[A-Z_]+>")
IDENTIFIER = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")  # CONSTANT_CASE tool/config names, never people


CARD_PREFIX = re.compile(r"^(?:4|5[1-5]|2[2-7]|3[47]|6011|65)")  # Visa, Mastercard, Amex, Discover


def luhn_ok(digits: str) -> bool:
    """Card check: 15-19 digits, a known issuer prefix and a valid Luhn checksum.

    Length and prefix matter: about 1 in 10 random digit strings passes Luhn alone, which
    redacted ~10% of order numbers in the synthetic logs before this check was added."""
    nums = [int(d) for d in digits if d.isdigit()]
    if not 15 <= len(nums) <= 19 or not CARD_PREFIX.match("".join(map(str, nums))):
        return False
    total = 0
    for i, n in enumerate(reversed(nums)):
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


@dataclass
class Redaction:
    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def found(self) -> bool:
        return bool(self.counts)


class PIIRedactor:
    def __init__(self, ner_enabled: bool = True, allow_terms: list[str] | None = None):
        self.allow = {t.lower() for t in (allow_terms or [])}
        self._nlp = None
        self._nlp_lock = threading.Lock()
        if ner_enabled:
            try:
                import spacy

                self._nlp = spacy.load("en_core_web_sm", disable=["parser", "lemmatizer", "attribute_ruler", "tagger"])
            except OSError:
                log.warning("spaCy model en_core_web_sm missing; person-name redaction disabled")

    def redact(self, text: str) -> Redaction:
        counts: Counter[str] = Counter()

        def substitute(kind: str, pattern: re.Pattern, value: str) -> str:
            def repl(m: re.Match) -> str:
                if kind == "CREDIT_CARD" and not luhn_ok(m.group(0)):
                    return m.group(0)
                counts[kind] += 1
                return f"<{kind}>"
            return pattern.sub(repl, value)

        for kind, pattern in PATTERNS:
            text = substitute(kind, pattern, text)

        if self._nlp is not None and any(c.isupper() for c in text):
            with self._nlp_lock:
                doc = self._nlp(text)
            spans = [e for e in doc.ents if e.label_ == "PERSON" and len(e.text) > 2
                     and not PLACEHOLDER.search(e.text) and not IDENTIFIER.search(e.text)
                     and e.text.lower() not in self.allow
                     and not any(tok.lower() in self.allow for tok in e.text.split())]
            for ent in reversed(spans):
                text = text[:ent.start_char] + "<PERSON>" + text[ent.end_char:]
                counts["PERSON"] += 1
        return Redaction(text, dict(counts))


@lru_cache(maxsize=1)
def get_redactor() -> PIIRedactor:
    cfg = load_yaml("security_policies.json").get("pii", {})
    return PIIRedactor(ner_enabled=cfg.get("ner_enabled", True), allow_terms=cfg.get("allow_terms", []))
