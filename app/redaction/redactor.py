"""High-level orchestrator: detect, validate, dedupe, substitute.

A ``Redactor`` owns a ``Detector`` plus a name -> ``Strategy`` map. It is
constructed once in ``app/main.py`` lifespan and reused across requests.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.inference.detector import Detector, Span
from app.observability import ENTITIES_DETECTED, INFERENCE_LATENCY
from app.redaction.apply import apply_spans, dedupe_overlaps, inverse_position_remap
from app.redaction.offsets import validate_offsets
from app.redaction.strategy import Strategy


@dataclass
class RedactionResult:
    text: str
    spans: list[Span] = field(default_factory=list)
    relex_map: dict[str, str] = field(default_factory=dict)


class Redactor:
    """Orchestrates detection, validation, dedupe, and substitution.

    Composition is explicit: the Redactor is constructed with a Detector
    and a mapping of strategy_name -> Strategy. Policies arrive as raw
    dicts from M4; without a policy the Redactor does a single-shot detect
    + substitute.
    """

    def __init__(
        self,
        detector: Detector,
        strategies: dict[str, Strategy],
        replacement: str = "[REDACTED]",
    ) -> None:
        self.detector = detector
        self.strategies = strategies
        self.replacement = replacement

    async def redact(
        self,
        text: str,
        policy: dict[str, Any] | None = None,
        entity_types: list[str] | None = None,
    ) -> RedactionResult:
        if policy is None:
            return await self.plain(text, entity_types)
        return await self.policy(text, policy)

    async def plain(self, text: str, entity_types: list[str] | None) -> RedactionResult:
        labels = entity_types or []
        with INFERENCE_LATENCY.labels(detector=self.detector.name).time():
            raw_spans = await self.detector.detect(text, labels)
        spans = dedupe_overlaps(validate_offsets(text, raw_spans))
        for span in spans:
            ENTITIES_DETECTED.labels(entity_type=span.type, strategy="auto").inc()
        return RedactionResult(
            text=apply_spans(text, spans, self.replacement),
            spans=spans,
        )

    async def policy(self, text: str, policy: dict[str, Any]) -> RedactionResult:
        result_text = text
        result_spans: list[Span] = []
        relex_map: dict[str, str] = {}
        remap_to_original: Callable[[int], int] | None = None

        for _field_name, field_config in policy.get("fields", {}).items():
            strategy_name = field_config.get("strategy")
            if strategy_name is None or strategy_name not in self.strategies:
                continue
            strategy = self.strategies[strategy_name]
            strategy_result = await strategy.apply(result_text, [], field_config)
            for span in strategy_result.spans:
                if remap_to_original is not None:
                    recast = Span(
                        start=remap_to_original(span.start),
                        end=remap_to_original(span.end - 1) + 1,
                        type=span.type,
                        confidence=span.confidence,
                    )
                else:
                    recast = span
                result_spans.append(recast)
            substitutions = strategy_result.substitutions or []
            if substitutions:
                spans_to_replace, replacements = zip(*substitutions, strict=True)
                new_to_current = inverse_position_remap(
                    result_text,
                    list(spans_to_replace),
                    list(replacements),
                )
                if remap_to_original is None:
                    remap_to_original = new_to_current
                else:
                    previous = remap_to_original
                    remap_to_original = lambda p, f=new_to_current, g=previous: g(f(p))  # noqa: E731
            result_text = strategy_result.text
            relex_map.update(strategy_result.relex_map)
            for span in strategy_result.spans:
                ENTITIES_DETECTED.labels(entity_type=span.type, strategy=strategy_name).inc()

        return RedactionResult(text=result_text, spans=result_spans, relex_map=relex_map)
