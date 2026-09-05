from __future__ import annotations

from app.inference.detector import Span
from app.inference.gliner2 import normalize_gliner2_result


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
