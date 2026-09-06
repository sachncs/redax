"""Detector Protocol and shared Span value object.

Every concrete detector (regex, GLiNER2, OpenMed PII, ...) implements the
``Detector`` Protocol declared here. ``Span`` is the frozen value object
that flows through detection, validation, dedupe, and substitution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Span:
    """A contiguous slice of text identified as a PII entity.

    Offsets are character indices into the original input string, half-open
    [start, end). Type is the canonical label (e.g. 'EMAIL', 'PERSON').
    Confidence is in [0.0, 1.0].
    """

    start: int
    end: int
    type: str
    confidence: float


@runtime_checkable
class Detector(Protocol):
    """Anything that can produce ``Span`` objects from a text string.

    Attributes:
        name: Stable identifier (used for metrics, audit, config).
    """

    name: str

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
        """Run detection on ``text`` and return every ``Span`` found.

        Args:
            text: The input text to scan.
            entity_types: Canonical PII labels to look for; an empty list
                typically means "all supported types".

        Returns:
            The detected spans, in document order.
        """
        ...

    async def warmup(self) -> None:
        """Load any heavy model state so the first request is fast.

        Called once during application startup.
        """
        ...
