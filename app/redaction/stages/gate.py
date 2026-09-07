"""Stage 1: regex gate.

Wraps any async ``Detector`` with a uniform ``run(text)`` signature so
the pipeline orchestrator can call the regex gate without knowing the
concrete detector implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.inference.detector import Span


class HasAsyncDetect(Protocol):
    """Structural type for any async detector that ``Gate`` can wrap.

    Attributes:
        name: Human-readable detector name, surfaced on the pipeline's
            stats for observability.
    """

    name: str

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
        """Run detection asynchronously and return the detected spans."""
        ...


@dataclass
class Gate:
    """Wrap any async ``Detector`` with a uniform ``run`` entrypoint.

    Attributes:
        detector: The detector to invoke. Must expose ``async detect``.
    """

    detector: HasAsyncDetect

    @classmethod
    def default(cls) -> Gate:
        """Build a Gate around the process-wide ``RegexDetector``."""
        from app.inference.regex import RegexDetector

        return cls(detector=RegexDetector())

    async def run(self, text: str) -> tuple[Span, ...]:
        """Invoke ``detector.detect(text, [])`` and return the result as a tuple."""
        return tuple(await self.detector.detect(text, []))
