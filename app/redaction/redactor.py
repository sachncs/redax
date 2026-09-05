from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.inference.detector import Detector, Span
from app.observability import ENTITIES_DETECTED, INFERENCE_LATENCY
from app.redaction.apply import apply_spans, dedupe_overlaps
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
        self._detector = detector
        self._strategies = strategies
        self._replacement = replacement

    async def redact(
        self,
        text: str,
        policy: dict[str, Any] | None = None,
        entity_types: list[str] | None = None,
    ) -> RedactionResult:
        if policy is None:
            return await self._plain_redact(text, entity_types)
        return await self._policy_redact(text, policy)

    async def _plain_redact(self, text: str, entity_types: list[str] | None) -> RedactionResult:
        labels = entity_types or []
        with INFERENCE_LATENCY.labels(detector=self._detector.name).time():
            raw_spans = await self._detector.detect(text, labels)
        spans = dedupe_overlaps(validate_offsets(text, raw_spans))
        for span in spans:
            ENTITIES_DETECTED.labels(entity_type=span.type, strategy="auto").inc()
        return RedactionResult(
            text=apply_spans(text, spans, self._replacement),
            spans=spans,
        )

    async def _policy_redact(self, text: str, policy: dict[str, Any]) -> RedactionResult:
        result_text = text
        result_spans: list[Span] = []
        relex_map: dict[str, str] = {}

        for _field_name, field_config in policy.get("fields", {}).items():
            strategy_name = field_config.get("strategy")
            if strategy_name is None or strategy_name not in self._strategies:
                continue
            strategy = self._strategies[strategy_name]
            strategy_result = await strategy.apply(result_text, [], field_config)
            result_text = strategy_result.text
            result_spans.extend(strategy_result.spans)
            relex_map.update(strategy_result.relex_map)
            for span in strategy_result.spans:
                ENTITIES_DETECTED.labels(entity_type=span.type, strategy=strategy_name).inc()

        return RedactionResult(text=result_text, spans=result_spans, relex_map=relex_map)
