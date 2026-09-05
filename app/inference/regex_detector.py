from __future__ import annotations

import re
from dataclasses import dataclass

from app.inference.detector import Span


@dataclass(frozen=True)
class _Rule:
    type: str
    pattern: re.Pattern[str]
    validator: callable | None = None


def luhn_ok(number: str) -> bool:
    digits = [int(c) for c in re.sub(r"\D", "", number)]
    if len(digits) < 13 or len(digits) > 19:
        return False
    total = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


_RULES: tuple[_Rule, ...] = (
    _Rule("EMAIL", re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b")),
    _Rule(
        "CREDIT_CARD",
        re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
        validator=luhn_ok,
    ),
    _Rule("IP_ADDRESS", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    _Rule(
        "PHONE_E164",
        re.compile(r"(?<!\d)\+\d{1,3}[\s\-]?\d{2,4}[\s\-]?\d{2,4}[\s\-]?\d{2,4}(?!\d)"),
    ),
    _Rule(
        "SSN_US",
        re.compile(r"\b(?!000|666|9\d{2})\d{3}[-\s]?(?!00)\d{2}[-\s]?(?!0000)\d{4}\b"),
    ),
    _Rule(
        "IBAN",
        re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
    ),
    _Rule("URL", re.compile(r"\bhttps?://[^\s<>\"']+\b")),
)


class RegexDetector:
    """Deterministic Detector for structured PII types.

    The 'entity_types' argument filters which rules fire; passing an empty
    list runs all rules. Spans returned are sorted by start offset.
    """

    name = "regex"

    def __init__(self, rules: tuple[_Rule, ...] = _RULES) -> None:
        self._rules = rules

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
        active = (
            [r for r in self._rules if r.type in entity_types]
            if entity_types
            else list(self._rules)
        )
        spans: list[Span] = []
        for rule in active:
            for match in rule.pattern.finditer(text):
                if rule.validator is not None and not rule.validator(match.group()):
                    continue
                spans.append(
                    Span(
                        start=match.start(),
                        end=match.end(),
                        type=rule.type,
                        confidence=1.0,
                    )
                )
        spans.sort(key=lambda s: (s.start, s.end))
        return spans

    async def warmup(self) -> None:
        return None
