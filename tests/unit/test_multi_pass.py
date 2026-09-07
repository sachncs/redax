from __future__ import annotations

import pytest

from app.inference.detector import Span
from app.inference.multipass import multi_pass_detect


class VariableDetector:
    """Detector that returns a different span list on each successive call."""

    def __init__(self, name: str, outputs: list[list[Span]]) -> None:
        self.name = name
        self._outputs = outputs
        self._call_count = 0

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
        idx = min(self._call_count, len(self._outputs) - 1)
        self._call_count += 1
        return list(self._outputs[idx])

    async def warmup(self) -> None:
        return None


@pytest.mark.asyncio
async def test_single_pass_returns_deduped() -> None:
    d = VariableDetector("v", [[Span(0, 5, "PERSON", 0.9), Span(2, 5, "PERSON", 0.5)]])
    out = await multi_pass_detect(d, "alice", ["person"], passes=1)
    assert len(out) == 1
    assert out[0].confidence == 0.9


@pytest.mark.asyncio
async def test_two_passes_union_spans() -> None:
    d = VariableDetector(
        "v",
        [
            [Span(0, 5, "PERSON", 0.9)],
            [Span(10, 15, "EMAIL", 0.8)],
        ],
    )
    out = await multi_pass_detect(d, "alice xxxxxx email@x", ["person", "email"], passes=2)
    types = {s.type for s in out}
    assert types == {"PERSON", "EMAIL"}


@pytest.mark.asyncio
async def test_zero_passes_raises() -> None:
    class ZeroPassStub:
        """Detector for the zero-passes validation test; returns no spans."""

        name = "x"

        async def detect(self, text, entity_types):
            return []

        async def warmup(self):
            return None

    with pytest.raises(ValueError):
        await multi_pass_detect(ZeroPassStub(), "x", [], passes=0)


@pytest.mark.asyncio
async def test_two_passes_with_same_output_dedupes() -> None:
    d = VariableDetector("v", [[Span(0, 5, "PERSON", 0.9)], [Span(0, 5, "PERSON", 0.9)]])
    out = await multi_pass_detect(d, "alice", ["person"], passes=2)
    assert len(out) == 1


@pytest.mark.asyncio
async def test_passes_capped_by_max_passes() -> None:
    d = VariableDetector("v", [[Span(0, 5, "PERSON", 0.9)]])
    with pytest.raises(ValueError, match=r"max_passes \(3\)"):
        await multi_pass_detect(d, "alice", ["person"], passes=4)


@pytest.mark.asyncio
async def test_passes_allow_custom_max() -> None:
    d = VariableDetector("v", [[Span(0, 5, "PERSON", 0.9)]])
    assert await multi_pass_detect(d, "alice", ["person"], passes=5, max_passes=5)
