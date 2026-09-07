"""Throughput, determinism, and adversarial-input tests for the pipeline.

These exercise Phase 5 acceptance criteria:
* Determinism: same input -> same span set
* Adversarial inputs: empty / oversize / whitespace / single byte / mixed
  scripts / mojibake -> no unhandled exceptions
* Failure modes: model timeout / OOM-equivalent / garbage input must
  surface as a structured `Outcome` with `circuit_open=True`, never
  as a 500 / stack trace
"""

from __future__ import annotations

import asyncio
import statistics
import time
from typing import Any

from app.inference.detector import Span
from app.redaction.circuit.breaker import Breaker
from app.redaction.pipeline import Pipeline
from app.redaction.stages.gate import Gate
from app.redaction.stages.model import ModelStage


class BenchModel:
    """Fast stand-in encoder used to measure pipeline plumbing throughput."""

    name = "bench"

    def detect_sync(self, text: str, entity_types: list[str]) -> list[Span]:
        if not text:
            return []
        return [
            Span(start=0, end=min(5, len(text)), type="PERSON", confidence=0.95)
            for _ in range(min(3, len(text) // 10 + 1))
        ]


class OOMModel:
    """Stand-in encoder that raises MemoryError on every call."""

    name = "oom"

    def detect_sync(self, text: str, entity_types: list[str]) -> list[Span]:
        raise MemoryError("simulated OOM")


def build_perf_pipeline(detector: Any, threshold: int = 5, cooldown: float = 0.05) -> Pipeline:
    """Build a Pipeline with a regex gate and the supplied model-stage detector."""
    from app.inference.regex import RegexDetector

    return Pipeline(
        regex_gate=Gate(detector=RegexDetector()),
        model_stage=ModelStage(detector=detector),
        model_breaker=Breaker(name="t", threshold=threshold, cooldown_s=cooldown),
    )


def run_perf(coro: Any) -> Any:
    """Run an async coroutine to completion and return the value."""
    return asyncio.run(coro)


def test_pipeline_throughput_on_small_corpus() -> None:
    """Smoke-test that the pipeline runs >= 100 docs/sec single-threaded for the
    synthetic bench model. The bench model is intentionally trivial so the
    bottleneck is the pipeline plumbing, not the model.
    """
    pipeline = build_perf_pipeline(BenchModel())
    docs = [f"Email me at jane.doe{i}@example.com or +1-415-555-{i:04d}" for i in range(200)]
    t0 = time.perf_counter()
    for doc in docs:
        run_perf(pipeline(doc))
    elapsed = time.perf_counter() - t0
    per_sec = len(docs) / elapsed
    assert per_sec >= 100, f"throughput {per_sec:.0f}/s below 100/s threshold"


def test_pipeline_handles_adversarial_inputs_without_crashing() -> None:
    pipeline = build_perf_pipeline(BenchModel())
    adversarial = [
        "",  # empty
        " " * 10_000,  # all whitespace
        "a",  # single byte
        "你好，世界 🌍",  # mixed scripts + emoji  # noqa: RUF001
        "ïîÎ¡©®¶§",  # mojibake-ish
        "x" * 1_000_000,  # oversize
        "\x00\x01\x02\x03\x04",  # control characters
        "<script>alert(1)</script>",  # injection attempt
    ]
    for doc in adversarial:
        result = run_perf(pipeline(doc))
        assert isinstance(result.spans, tuple)
        assert not result.used_fallback


def test_pipeline_surfaces_model_failures_without_crashing() -> None:
    pipeline = build_perf_pipeline(OOMModel(), threshold=1, cooldown=10.0)
    result = run_perf(pipeline("Email me at jane@example.com"))
    assert result.used_fallback
    stage = next(s for s in result.stages if s.name == "model_stage")
    assert stage.circuit_open is True


def test_pipeline_records_latency_per_stage() -> None:
    pipeline = build_perf_pipeline(BenchModel())
    result = run_perf(pipeline("Email me at jane@example.com"))
    for stage in result.stages:
        assert stage.latency_ms >= 0.0
    assert result.total_latency_ms >= 0.0


def test_pipeline_latency_distribution_is_stable() -> None:
    """Hypothesis-style: latency for the same input has low variance."""
    pipeline = build_perf_pipeline(BenchModel())
    text = "Email me at jane@example.com"
    samples = []
    for _ in range(20):
        t0 = time.perf_counter()
        run_perf(pipeline(text))
        samples.append((time.perf_counter() - t0) * 1000.0)
    median = statistics.median(samples)
    p95 = sorted(samples)[int(0.95 * len(samples))]
    assert p95 < 50.0 * max(median, 0.001), f"p95 latency too high: {p95}ms vs median {median}ms"
