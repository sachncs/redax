"""Stage 1: regex gate.

Wraps any async ``Detector`` with a uniform ``run(text)`` signature so
the pipeline orchestrator can call the regex gate without knowing the
concrete detector implementation.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.inference.detector import Detector, Span


@dataclass
class Gate:
    """Wrap any async ``Detector`` with a uniform ``run`` entrypoint.

    Attributes:
        detector: The detector to invoke.
    """

    detector: Detector

    async def run(self, text: str) -> tuple[Span, ...]:
        """Invoke ``detector.detect(text, [])`` and return the result as a tuple."""
        return tuple(await self.detector.detect(text, []))
