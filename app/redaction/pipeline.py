from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.inference.detector import Span
from app.redaction.circuit.breaker import CircuitBreaker, CircuitOpenError
from app.redaction.stages.consensus import fuse
from app.redaction.stages.fallback import from_regex_only
from app.redaction.stages.model_stage import ModelStage
from app.redaction.stages.regex_gate import RegexGate

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StageOutcome:
    """One stage's contribution to a pipeline run."""

    name: str
    spans: tuple[Span, ...]
    latency_ms: float
    circuit_open: bool = False
    note: str = ""


@dataclass(frozen=True)
class PipelineResult:
    """Final pipeline output for one `/v1/redact` request."""

    text: str
    spans: tuple[Span, ...]
    stages: tuple[StageOutcome, ...]
    used_fallback: bool
    total_latency_ms: float
    text_hash: str  # SHA-256 of input text; never log the text itself


@dataclass
class Pipeline:
    """Multi-stage redaction pipeline.

    Construct once in `app/main.py` lifespan, then call `__call__` per
    request. `__call__` is the only public method aside from `stats`.
    """

    regex_gate: RegexGate
    model_stage: ModelStage
    model_breaker: CircuitBreaker
    stages: list[PipelineStage] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.stages:
            self.stages = [
                PipelineStage(name="regex_gate", fn=lambda t: self._run_regex_gate(t)),
                PipelineStage(name="model_stage", fn=lambda t: self._run_model_stage(t, ())),
                PipelineStage(name="consensus", fn=lambda t: self._run_consensus(t)),
                PipelineStage(name="fallback", fn=lambda t: self._run_fallback(tuple(), False)),
            ]

    async def __call__(self, text: str) -> PipelineResult:
        import hashlib

        if not isinstance(text, str):
            raise TypeError("text must be str")

        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        outcomes: list[StageOutcome] = []
        regex_outcome = await self._run_regex_gate(text)
        outcomes.append(regex_outcome)

        model_outcome = await self._run_model_stage(text, regex_outcome.spans)
        outcomes.append(model_outcome)

        fused = fuse(regex_outcome.spans, model_outcome.spans)
        consensus_outcome = StageOutcome(
            name="consensus",
            spans=fused,
            latency_ms=0.0,
            circuit_open=model_outcome.circuit_open,
            note=f"regex={len(regex_outcome.spans)} model={len(model_outcome.spans)} fused={len(fused)}",
        )
        outcomes.append(consensus_outcome)

        fallback_outcome = self._run_fallback(fused, model_outcome.circuit_open)
        outcomes.append(fallback_outcome)

        total_latency = sum(o.latency_ms for o in outcomes)
        return PipelineResult(
            text=text,
            spans=fused,
            stages=tuple(outcomes),
            used_fallback=model_outcome.circuit_open,
            total_latency_ms=total_latency,
            text_hash=text_hash,
        )

    async def _run_regex_gate(self, text: str) -> StageOutcome:
        t0 = time.perf_counter()
        spans = await self.regex_gate.run(text)
        return StageOutcome(
            name="regex_gate",
            spans=spans,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )

    async def _run_model_stage(self, text: str, _regex_hits: tuple[Span, ...]) -> StageOutcome:
        t0 = time.perf_counter()

        def _sync_call() -> tuple[Span, ...]:
            return tuple(self.model_stage.detector_sync(text, []))

        try:
            spans = await asyncio.to_thread(self.model_breaker.call, _sync_call)
        except CircuitOpenError:
            return StageOutcome(
                name="model_stage",
                spans=(),
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                circuit_open=True,
                note="circuit open",
            )
        except (OSError, RuntimeError, ValueError, TimeoutError, MemoryError) as exc:
            log.warning("model_stage_failure", extra={"error": exc.__class__.__name__})
            return StageOutcome(
                name="model_stage",
                spans=(),
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                circuit_open=True,
                note=f"transient: {exc.__class__.__name__}",
            )
        return StageOutcome(
            name="model_stage",
            spans=spans,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )

    def _run_consensus(self, _text: str) -> StageOutcome:
        return StageOutcome(name="consensus", spans=(), latency_ms=0.0)

    def _run_fallback(self, fused: tuple[Span, ...], circuit_open: bool) -> StageOutcome:
        return StageOutcome(
            name="fallback",
            spans=from_regex_only(fused) if not circuit_open else (),
            latency_ms=0.0,
            circuit_open=circuit_open,
        )

    def stats(self) -> dict[str, object]:
        return {
            "regex_detector": self.regex_gate.detector.name,
            "model_detector": self.model_stage.detector.name,
            "model_breaker": self.model_breaker.stats(),
        }


@dataclass(frozen=True)
class PipelineStage:
    name: str
    fn: Callable[[str], Awaitable[StageOutcome] | StageOutcome]
