from __future__ import annotations

from dataclasses import dataclass, field

from app.inference.detector import Detector, Span
from app.observability import ENTITIES_DETECTED, INFERENCE_LATENCY
from app.redaction.apply import apply_spans, dedupe_overlaps
from app.redaction.offsets import validate_offsets


@dataclass
class RedactionResult:
    text: str
    spans: list[Span] = field(default_factory=list)
    relex_map: dict[str, str] = field(default_factory=dict)


class Redactor:
    """Orchestrates detection, validation, dedupe, and substitution.

    Composition is explicit: the Redactor is constructed with a Detector
    and a replacement string. No global state. Multi-pass, relex, and
    type-aware routing are added in later milestones.
    """

    def __init__(
        self,
        detector: Detector,
        replacement: str = "[REDACTED]",
        default_entity_types: list[str] | None = None,
    ) -> None:
        self._detector = detector
        self._replacement = replacement
        self._default_entity_types = default_entity_types or []

    async def redact(self, text: str, entity_types: list[str] | None = None) -> RedactionResult:
        labels = entity_types if entity_types is not None else self._default_entity_types

        with INFERENCE_LATENCY.labels(detector=self._detector.name).time():
            raw_spans = await self._detector.detect(text, labels)

        spans = validate_offsets(text, raw_spans)
        spans = dedupe_overlaps(spans)

        for span in spans:
            ENTITIES_DETECTED.labels(entity_type=span.type, strategy="auto").inc()

        redacted = apply_spans(text, spans, self._replacement)
        return RedactionResult(text=redacted, spans=spans)
