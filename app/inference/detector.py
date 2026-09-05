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
    """Anything that can produce Spans from a text string."""

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]: ...

    async def warmup(self) -> None: ...
