from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from app.inference.detector import Span


@dataclass(frozen=True)
class Rule:
    """One pattern + validator pair for the regex detector.

    Attributes:
        type: Canonical Span type label (e.g. ``"EMAIL"``).
        pattern: Compiled regular expression.
        validator: Optional callable that accepts the matched substring
            and returns ``True`` if the match is accepted. Used by
            ``CREDIT_CARD`` to run a Luhn checksum.
    """

    type: str
    pattern: re.Pattern[str]
    validator: Callable[[str], bool] | None = None


def luhn_ok(number: str) -> bool:
    """Return True if ``number`` (digits + optional separators) passes the Luhn checksum."""
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


RULES: tuple[Rule, ...] = (
    Rule("EMAIL", re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b")),
    Rule(
        "CREDIT_CARD",
        re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
        validator=luhn_ok,
    ),
    Rule("IP_ADDRESS", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    Rule(
        "PHONE_E164",
        re.compile(r"(?<!\d)\+\d{1,3}[\s\-]?\d{2,4}[\s\-]?\d{2,4}[\s\-]?\d{2,4}(?!\d)"),
    ),
    Rule(
        "SSN_US",
        re.compile(r"\b(?!000|666|9\d{2})\d{3}[-\s]?(?!00)\d{2}[-\s]?(?!0000)\d{4}\b"),
    ),
    Rule(
        "IBAN",
        re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
    ),
    Rule("URL", re.compile(r"\bhttps?://[^\s<>\"']+\b")),
)


class RegexDetector:
    """Deterministic Detector for structured PII types.

    The 'entity_types' argument filters which rules fire; passing an empty
    list runs all rules. Spans returned are sorted by start offset.
    """

    name = "regex"

    def __init__(self, rules: tuple[Rule, ...] = RULES) -> None:
        self.rules = rules

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
        """Run every matching rule over ``text`` and return sorted, validated spans.

        Args:
            text: The input text to scan.
            entity_types: List of ``Rule.type`` labels to fire; an
                empty list runs every rule.

        Returns:
            The matched spans, sorted by ``(start, end)``.
        """
        active = (
            [r for r in self.rules if r.type in entity_types] if entity_types else list(self.rules)
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
        """No-op: the regex detector has no model state to load."""
        return None
