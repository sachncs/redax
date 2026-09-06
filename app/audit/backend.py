from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class AuditEvent:
    """One record of a redaction action.

    NEVER contains the original text or the entity text values. Only
    counts, types, durations, and request metadata. This is what makes
    the audit log safe to keep.
    """

    request_id: str
    ts: str
    policy_version: str
    text_chars: int
    entities_detected: list[dict[str, Any]] = field(default_factory=list)
    inference_ms: int = 0
    redactor_version: str = "0.1.0"
    model_hash: str = ""
    direction: str = "egress"


@runtime_checkable
class AuditBackend(Protocol):
    """Persist AuditEvent somewhere durable. Implementations may buffer
    and flush asynchronously."""

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def record(self, event: AuditEvent) -> None: ...


def event_to_dict(event: AuditEvent) -> dict[str, Any]:
    return asdict(event)


def span_summary(spans: list[Any]) -> list[dict[str, Any]]:
    """Aggregate detected spans into per-type count + mean confidence.

    Mirrors what the API routes report in audit events; spans are the
    detector Span objects. Never includes entity text.
    """
    grouped: dict[str, list[float]] = {}
    for span in spans:
        grouped.setdefault(span.type, []).append(span.confidence)
    return [
        {
            "type": entity_type,
            "count": len(confidences),
            "confidence_avg": round(sum(confidences) / len(confidences), 3) if confidences else 0.0,
        }
        for entity_type, confidences in sorted(grouped.items())
    ]


def pipeline_to_audit_event(
    *,
    request_id: str,
    text_chars: int,
    policy_version: str,
    inference_ms: int,
    spans: list[Any],
    used_fallback: bool,
    model_checkpoint_hash: str = "",
    redactor_version: str = "0.1.0",
) -> AuditEvent:
    """Build an `AuditEvent` from a `PipelineResult`.

    The event carries *aggregate* metrics (`used_fallback`,
    `model_checkpoint_hash`) and per-type counts — never any original or
    redacted text — so the audit log remains safe to keep under any
    retention regime.
    """
    entities = span_summary(spans)
    if used_fallback:
        entities = [{"type": "__used_fallback__", "count": 1, "confidence_avg": 0.0}, *entities]
    return AuditEvent(
        request_id=request_id,
        ts="",
        policy_version=policy_version,
        text_chars=text_chars,
        entities_detected=entities,
        inference_ms=inference_ms,
        redactor_version=redactor_version,
        model_hash=model_checkpoint_hash,
    )
