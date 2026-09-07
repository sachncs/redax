from __future__ import annotations

import pytest

from app.inference.detector import Detector, Span
from app.inference.registry import DetectorRegistry


class StubDetector:
    """Test detector that always returns a single PERSON span."""

    name = "stub"

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
        return [Span(0, 1, "PERSON", 1.0)]

    async def warmup(self) -> None:
        return None


class OtherStub(StubDetector):
    """Second test detector sharing the same protocol, registered under a different name."""

    name = "other"


def test_registry_maps_by_name() -> None:
    first = StubDetector()
    second = OtherStub()
    registry = DetectorRegistry([first, second])
    assert registry["stub"] is first
    assert registry["other"] is second
    assert len(registry) == 2
    assert set(registry) == {"stub", "other"}


def test_resolve_returns_instance() -> None:
    detector = StubDetector()
    assert DetectorRegistry([detector]).resolve("stub") is detector


def test_resolve_unknown_raises() -> None:
    registry = DetectorRegistry([StubDetector()])
    with pytest.raises(ValueError, match=r"unknown detector 'nope'"):
        registry.resolve("nope")


def test_handles_protocol_instances() -> None:
    assert isinstance(StubDetector(), Detector)
    registry = DetectorRegistry([StubDetector()])
    registry.resolve("stub")  # no qualification needed at runtime
