"""Multi-stage redaction pipeline.

Combines a regex gate, an encoder-backed model stage wrapped in a
circuit breaker, a consensus fusion step, and a fallback path. The
class is constructed once in ``app/main.py`` lifespan and invoked per
request via :meth:`Pipeline.__call__`.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass

from app.inference.detector import Span
from app.redaction.circuit.breaker import Breaker, OpenError
from app.redaction.stages.consensus import fuse
from app.redaction.stages.fallback import from_regex_only
from app.redaction.stages.gate import Gate
from app.redaction.stages.model import ModelStage

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Outcome:
    """One stage's contribution to a pipeline run."""

    name: str
    spans: tuple[Span, ...]
    latency_ms: float
    circuit_open: bool = False
    note: str = ""


@dataclass(frozen=True)
class PipelineResult:
    """Final pipeline output for one ``/v1/redact`` request."""

    text: str
    spans: tuple[Span, ...]
    stages: tuple[Outcome, ...]
    used_fallback: bool
    total_latency_ms: float
    digest: str  # SHA-256 of input text; never log the text itself


@dataclass
class Pipeline:
    """Multi-stage redaction pipeline.

    Construct once in ``app/main.py`` lifespan, then call the instance
    per request. The public surface is :meth:`__call__` and
    :meth:`stats`; per-stage methods exist so tests can exercise them
    in isolation but they are not part of the stable API.
    """

    regex_gate: Gate
    model_stage: ModelStage
    model_breaker: Breaker

    async def __call__(self, text: str) -> PipelineResult:
        if not isinstance(text, str):
            raise TypeError("text must be str")

        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        outcomes: list[Outcome] = []
        regex_outcome = await self.regex_gate_stage(text)
        outcomes.append(regex_outcome)

        model_outcome = await self.model_stage_stage(text, regex_outcome.spans)
        outcomes.append(model_outcome)

        fused = fuse(regex_outcome.spans, model_outcome.spans)
        consensus_outcome = Outcome(
            name="consensus",
            spans=fused,
            latency_ms=0.0,
            circuit_open=model_outcome.circuit_open,
            note=f"regex={len(regex_outcome.spans)} model={len(model_outcome.spans)} fused={len(fused)}",
        )
        outcomes.append(consensus_outcome)

        fallback_outcome = self.fallback_stage(fused, model_outcome.circuit_open)
        outcomes.append(fallback_outcome)

        total_latency = sum(o.latency_ms for o in outcomes)
        return PipelineResult(
            text=text,
            spans=fused,
            stages=tuple(outcomes),
            used_fallback=model_outcome.circuit_open,
            total_latency_ms=total_latency,
            digest=digest,
        )

    async def regex_gate_stage(self, text: str) -> Outcome:
        """Run the Stage-1 regex gate and time the call.

        Args:
            text: The input text.

        Returns:
            The :class:`Outcome` with the regex gate's spans and latency.
        """
        t0 = time.perf_counter()
        spans = await self.regex_gate.run(text)
        return Outcome(
            name="regex_gate",
            spans=spans,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )

    async def model_stage_stage(self, text: str, _regex_hits: tuple[Span, ...]) -> Outcome:
        """Run the Stage-2 encoder through the circuit breaker.

        The detector is invoked on a worker thread (``asyncio.to_thread``)
        so the event loop is never blocked by model inference. A
        breaker-open or transient failure returns an empty
        :class:`Outcome` with ``circuit_open=True``; the consensus
        stage then falls back to the regex-only path.

        Args:
            text: The input text.
            _regex_hits: Regex hits (currently unused, kept for
                future cross-attention between stages).

        Returns:
            The :class:`Outcome` with the model's spans and latency, or
            an empty outcome with ``circuit_open=True`` when the
            breaker is open or the call failed transiently.
        """
        t0 = time.perf_counter()

        def sync_call() -> tuple[Span, ...]:
            return tuple(self.model_stage.detector_sync(text, []))

        try:
            spans = await asyncio.to_thread(self.model_breaker.call, sync_call)
        except OpenError:
            return Outcome(
                name="model_stage",
                spans=(),
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                circuit_open=True,
                note="circuit open",
            )
        except (OSError, RuntimeError, ValueError, TimeoutError, MemoryError) as exc:
            log.warning("model_stage_failure", extra={"error": exc.__class__.__name__})
            return Outcome(
                name="model_stage",
                spans=(),
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                circuit_open=True,
                note=f"transient: {exc.__class__.__name__}",
            )
        return Outcome(
            name="model_stage",
            spans=spans,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )

    def consensus_stage(self, _text: str) -> Outcome:
        """Record the consensus-fusion outcome (the fusion itself happens in __call__).

        Args:
            _text: The input text (currently unused; fusion only
                operates on the two stage outcomes).

        Returns:
            An empty :class:`Outcome` placeholder for the audit log;
            the fused spans are returned by :meth:`__call__` directly.
        """
        return Outcome(name="consensus", spans=(), latency_ms=0.0)

    def fallback_stage(self, fused: tuple[Span, ...], circuit_open: bool) -> Outcome:
        """Return the Stage-4 fallback :class:`Outcome`.

        Args:
            fused: The fused spans from the consensus stage.
            circuit_open: ``True`` if the model stage breaker is open;
                the fallback then yields an empty span set so the
                caller knows no model output was applied.

        Returns:
            The :class:`Outcome` for the fallback stage.
        """
        return Outcome(
            name="fallback",
            spans=from_regex_only(fused) if not circuit_open else (),
            latency_ms=0.0,
            circuit_open=circuit_open,
        )

    def stats(self) -> dict[str, object]:
        """Return a JSON-serialisable snapshot of the live pipeline wiring.

        Returned dict has ``regex_detector`` (str), ``model_detector``
        (str), and ``model_breaker`` (a :class:`Stats` dataclass).

        Returns:
            The introspection dict for the ``/v1/stats`` endpoint.
        """
        return {
            "regex_detector": self.regex_gate.detector.name,
            "model_detector": self.model_stage.detector.name,
            "model_breaker": self.model_breaker.report(),
        }
