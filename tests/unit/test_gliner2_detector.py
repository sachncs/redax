from __future__ import annotations

import asyncio
import time

import pytest

from app.inference.detector import Span
from app.inference.gliner2 import GLiNER2Detector, normalize_gliner2_result


class _StubResult:
    def __init__(self, entities: dict) -> None:
        self.entities = entities


def test_normalize_dict_with_spans() -> None:
    result = _StubResult(
        {
            "person": [
                {"text": "Alice", "confidence": 0.91, "start": 0, "end": 5},
                {"text": "Bob", "confidence": 0.42, "start": 10, "end": 13},
            ]
        }
    )
    spans = normalize_gliner2_result("Alice and Bob", result)
    assert spans == [
        Span(start=0, end=5, type="PERSON", confidence=0.91),
        Span(start=10, end=13, type="PERSON", confidence=0.42),
    ]


def test_normalize_string_values_finds_offsets() -> None:
    result = _StubResult({"email": ["a@b.com"]})
    spans = normalize_gliner2_result("write to a@b.com today", result)
    assert len(spans) == 1
    assert spans[0].type == "EMAIL"
    assert spans[0].start == 9
    assert spans[0].end == 16
    assert spans[0].confidence == 1.0


def test_normalize_accepts_plain_dict_results() -> None:
    """gliner2 >=0.3 returns a plain dict rather than an object with
    `.entities`. Normalise both shapes."""
    result = {
        "entities": {
            "email": [
                {
                    "text": "a@b.com",
                    "confidence": 0.91,
                    "start": 9,
                    "end": 16,
                }
            ]
        }
    }
    spans = normalize_gliner2_result("write to a@b.com today", result)
    assert len(spans) == 1
    assert spans[0].type == "EMAIL"
    assert spans[0].confidence == 0.91
    assert spans[0].start == 9
    assert spans[0].end == 16


def test_normalize_skips_unmatchable_values() -> None:
    result = _StubResult({"person": ["nothere"]})
    spans = normalize_gliner2_result("Alice and Bob", result)
    assert spans == []


def test_normalize_empty() -> None:
    result = _StubResult({})
    assert normalize_gliner2_result("anything", result) == []


def test_normalize_sorts_by_start() -> None:
    result = _StubResult(
        {
            "person": [
                {"text": "Bob", "confidence": 0.9, "start": 10, "end": 13},
                {"text": "Alice", "confidence": 0.9, "start": 0, "end": 5},
            ]
        }
    )
    spans = normalize_gliner2_result("Alice and Bob", result)
    assert spans[0].start < spans[1].start


class _StubModel:
    def __init__(self) -> None:
        self.calls = 0
        self.concurrent = 0
        self.max_concurrent = 0

    def extract_entities(  # type: ignore[no-untyped-def]
        self, text, labels, threshold=None, include_confidence=None, include_spans=None
    ):
        self.calls += 1
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        time.sleep(0.01)
        self.concurrent -= 1
        return _StubResult(
            {"person": [{"text": text, "confidence": 0.9, "start": 0, "end": max(len(text), 1)}]}
        )


@pytest.mark.asyncio
async def test_detect_before_load_raises() -> None:
    detector = GLiNER2Detector()
    with pytest.raises(RuntimeError, match=r"call load\(\)"):
        await detector.detect("x", ["person"])


@pytest.mark.asyncio
async def test_detect_with_injected_model_and_concurrency_bound() -> None:
    model = _StubModel()
    detector = GLiNER2Detector(concurrency=2, model=model)

    results = await asyncio.gather(*[detector.detect(f"text{i}", ["person"]) for i in range(8)])
    spans = [s for batch in results for s in batch]
    assert len(spans) == 8
    assert model.calls == 8
    assert model.max_concurrent <= 2, model.max_concurrent
    assert detector.is_loaded


@pytest.mark.asyncio
async def test_warmup_loads_and_runs() -> None:
    detector = GLiNER2Detector(model=_StubModel())
    await detector.warmup()
    assert detector.is_loaded


@pytest.mark.asyncio
async def test_model_is_loaded_only_once() -> None:
    detector = GLiNER2Detector(model=_StubModel())
    await detector.load()
    await detector.load()
    await detector.load()
    assert detector.is_loaded
