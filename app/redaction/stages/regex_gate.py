"""Stage 1: regex gate. Runs the deterministic regex detector first."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.inference.detector import Span


class HasAsyncDetect(Protocol):
    name: str

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]: ...


@dataclass
class RegexGate:
    """Wrap any `Detector` with a uniform async signature."""

    detector: HasAsyncDetect

    @classmethod
    def default(cls) -> RegexGate:
        from app.inference.regex_detector import RegexDetector

        return cls(detector=RegexDetector())

    async def run(self, text: str) -> tuple[Span, ...]:
        return tuple(await self.detector.detect(text, []))
