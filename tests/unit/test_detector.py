from __future__ import annotations

import pytest

from app.inference.detector import Detector, Span


@pytest.mark.asyncio
async def test_detector_protocol_is_runtime_checkable() -> None:
    class Fake:
        async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
            return []

        async def warmup(self) -> None:
            return None

    f = Fake()
    assert isinstance(f, Detector)


def test_span_is_frozen() -> None:
    s = Span(start=0, end=5, type="PERSON", confidence=0.9)
    with pytest.raises(Exception):
        s.start = 1  # type: ignore[misc]
