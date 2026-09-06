from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.inference.detector import Span
from app.inference.regex_detector import RegexDetector
from app.redaction.pipeline import Pipeline
from app.redaction.stages.model_stage import ModelStage
from app.redaction.stages.regex_gate import RegexGate


class _FakeModel:
    name = "fake"

    def detect_sync(self, text: str, entity_types: list[str]) -> list[Span]:
        if not text:
            return []
        return [Span(start=0, end=min(5, len(text)), type="PERSON", confidence=0.9)]


def _build_pipeline(
    *,
    detector: Any | None = None,
    threshold: int = 1,
    cooldown: float = 0.05,
) -> Pipeline:
    from app.redaction.circuit.breaker import Breaker

    detector = detector or _FakeModel()
    regex = RegexDetector()
    return Pipeline(
        regex_gate=RegexGate(detector=regex),
        model_stage=ModelStage(detector=detector),
        model_breaker=Breaker(name="m", threshold=threshold, cooldown_s=cooldown),
    )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_pipeline_basic_consensus() -> None:
    pipeline = _build_pipeline()
    result = _run(pipeline("Reach me at jane@example.com or +1-415-555-0199"))
    assert isinstance(result.spans, tuple)
    assert len(result.spans) >= 1
    assert not result.used_fallback


def test_pipeline_is_byte_deterministic_on_spans() -> None:
    """Same input → same span set, byte-for-byte.

    Latency can vary run-to-run (we don't assert on it); we only require the
    span set and the input hash are stable.
    """
    pipeline = _build_pipeline()
    text = "Email me at jane@example.com tomorrow please"
    a = _run(pipeline(text))
    b = _run(pipeline(text))
    assert a.spans == b.spans
    assert a.text_hash == b.text_hash


def test_pipeline_model_circuit_opens_after_failures() -> None:
    class _Boom:
        name = "boom"

        def detect_sync(self, text: str, entity_types: list[str]) -> list[Span]:
            raise ConnectionError("model down")

    pipeline = _build_pipeline(detector=_Boom(), threshold=1, cooldown=10.0)
    result = _run(pipeline("Email me at jane@example.com"))
    assert result.used_fallback
    fallback_stage = next(s for s in result.stages if s.name == "fallback")
    assert fallback_stage.spans == ()


def test_pipeline_recovers_after_circuit_cooldown() -> None:
    state = {"fail": True}

    class _Flaky:
        name = "flaky"

        def detect_sync(self, text: str, entity_types: list[str]) -> list[Span]:
            if state["fail"]:
                raise ConnectionError("transient")
            return [Span(start=0, end=5, type="PERSON", confidence=0.9)]

    pipeline = _build_pipeline(detector=_Flaky(), threshold=1, cooldown=0.05)
    first = _run(pipeline("hi there"))
    assert first.used_fallback
    state["fail"] = False
    import time

    time.sleep(0.06)
    second = _run(pipeline("hi there"))
    assert not second.used_fallback
    assert len(second.spans) >= 1


def test_pipeline_does_not_log_text() -> None:
    pipeline = _build_pipeline()
    result = _run(pipeline("super secret email jane@example.com ssn 000-00-0000"))
    assert "jane@example.com" not in str(result.stages)
    assert "000-00-0000" not in str(result.stages)
    assert result.text_hash != ""


def test_pipeline_handles_empty_input() -> None:
    pipeline = _build_pipeline()
    result = _run(pipeline(""))
    assert result.spans == ()
    assert not result.used_fallback


def test_pipeline_rejects_non_string() -> None:
    pipeline = _build_pipeline()
    with pytest.raises(TypeError):
        _run(pipeline(123))  # type: ignore[arg-type]


def test_pipeline_stats() -> None:
    pipeline = _build_pipeline()
    stats = pipeline.stats()
    assert stats["regex_detector"] == "regex"
    assert stats["model_detector"] == "fake"
    assert stats["model_breaker"].state == "closed"
