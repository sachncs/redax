from __future__ import annotations

import pytest

from app.inference.detector import Detector, Span
from app.redaction.redactor import Redactor


class _ScriptedDetector:
    def __init__(self, name: str, output: list[Span]) -> None:
        self.name = name
        self._output = output
        self.calls = 0

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
        self.calls += 1
        return list(self._output)

    async def warmup(self) -> None:
        return None


@pytest.mark.asyncio
async def test_redact_runs_detector_and_substitutes() -> None:
    d = _ScriptedDetector(
        "fake",
        [Span(12, 19, "EMAIL", 1.0)],
    )
    r = Redactor(detector=d, replacement="<EMAIL>")
    result = await r.redact("Email me at a@b.com tomorrow")
    assert result.text == "Email me at <EMAIL> tomorrow"
    assert result.spans[0].type == "EMAIL"
    assert d.calls == 1


@pytest.mark.asyncio
async def test_redact_drops_bad_offsets() -> None:
    d = _ScriptedDetector(
        "fake",
        [Span(12, 19, "EMAIL", 1.0), Span(100, 200, "X", 1.0)],
    )
    r = Redactor(detector=d)
    result = await r.redact("Email me at a@b.com")
    assert len(result.spans) == 1


@pytest.mark.asyncio
async def test_redact_dedupes_overlaps() -> None:
    d = _ScriptedDetector(
        "fake",
        [Span(0, 10, "PERSON", 0.5), Span(2, 8, "PERSON", 0.9)],
    )
    r = Redactor(detector=d)
    result = await r.redact("alice bobby", entity_types=["PERSON"])
    assert len(result.spans) == 1
    assert result.spans[0].confidence == 0.9


@pytest.mark.asyncio
async def test_redact_passes_through_when_no_spans() -> None:
    d = _ScriptedDetector("fake", [])
    r = Redactor(detector=d)
    result = await r.redact("nothing here")
    assert result.text == "nothing here"
    assert result.spans == []


@pytest.mark.asyncio
async def test_redact_entity_types_passed_through() -> None:
    d = _ScriptedDetector("fake", [])
    r = Redactor(detector=d)
    await r.redact("hi", entity_types=["email"])
    assert d.calls == 1
