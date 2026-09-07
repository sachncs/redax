from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.inference.detector import Span
from app.inference.regex import RegexDetector
from app.redaction.pipeline import Pipeline
from app.redaction.stages.gate import Gate
from app.redaction.stages.model import ModelStage


class FakeModel:
    """Model-stage detector that always returns one PERSON span at the start of the text."""

    name = "fake"

    def detect_sync(self, text: str, entity_types: list[str]) -> list[Span]:
        if not text:
            return []
        return [Span(start=0, end=min(5, len(text)), type="PERSON", confidence=0.9)]


def build_test_pipeline(
    *,
    detector: Any | None = None,
    threshold: int = 1,
    cooldown: float = 0.05,
) -> Pipeline:
    """Build a Pipeline with a regex gate and a model stage; default model is FakeModel."""
    from app.redaction.circuit.breaker import Breaker

    detector = detector or FakeModel()
    regex = RegexDetector()
    return Pipeline(
        regex_gate=Gate(detector=regex),
        model_stage=ModelStage(detector=detector),
        model_breaker=Breaker(name="m", threshold=threshold, cooldown_s=cooldown),
    )


def run_async_coro(coro: Any) -> Any:
    """Run an async coroutine to completion and return the value."""
    return asyncio.run(coro)


def test_pipeline_basic_consensus() -> None:
    pipeline = build_test_pipeline()
    result = run_async_coro(pipeline("Reach me at jane@example.com or +1-415-555-0199"))
    assert isinstance(result.spans, tuple)
    assert len(result.spans) >= 1
    assert not result.used_fallback


def test_pipeline_is_byte_deterministic_on_spans() -> None:
    """Same input -> same span set, byte-for-byte.

    Latency can vary run-to-run (we don't assert on it); we only require the
    span set and the input hash are stable.
    """
    pipeline = build_test_pipeline()
    text = "Email me at jane@example.com tomorrow please"
    a = run_async_coro(pipeline(text))
    b = run_async_coro(pipeline(text))
    assert a.spans == b.spans
    assert a.digest == b.digest


def test_pipeline_model_circuit_opens_after_failures() -> None:
    class BoomModel:
        """Model that always raises ConnectionError to force the breaker open."""

        name = "boom"

        def detect_sync(self, text: str, entity_types: list[str]) -> list[Span]:
            raise ConnectionError("model down")

    pipeline = build_test_pipeline(detector=BoomModel(), threshold=1, cooldown=10.0)
    result = run_async_coro(pipeline("Email me at jane@example.com"))
    assert result.used_fallback
    fallback_stage = next(s for s in result.stages if s.name == "fallback")
    assert fallback_stage.spans == ()


def test_pipeline_recovers_after_circuit_cooldown() -> None:
    state = {"fail": True}

    class FlakyModel:
        """Model that fails until a flag is cleared, then returns one span."""

        name = "flaky"

        def detect_sync(self, text: str, entity_types: list[str]) -> list[Span]:
            if state["fail"]:
                raise ConnectionError("transient")
            return [Span(start=0, end=5, type="PERSON", confidence=0.9)]

    pipeline = build_test_pipeline(detector=FlakyModel(), threshold=1, cooldown=0.05)
    first = run_async_coro(pipeline("hi there"))
    assert first.used_fallback
    state["fail"] = False
    import time

    time.sleep(0.06)
    second = run_async_coro(pipeline("hi there"))
    assert not second.used_fallback
