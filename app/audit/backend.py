"""Audit-event Protocol, value object, and persistence Protocols."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class Event:
    """One record of a redaction action.

    NEVER contains the original text or the entity text values. Only
    counts, types, durations, and request metadata. This is what makes
    the audit log safe to keep.

    Attributes:
        request_id: The correlation id propagated by the request middleware.
        trace_id: The OpenTelemetry trace id (32-char hex) when
            tracing is enabled, else the empty string.
        ts: ISO-8601 timestamp; empty until the backend stamps it.
        policy_version: Logical version of the policy that was applied.
        text_chars: Length of the input text.
        entities_detected: Per-type counts and mean confidences.
        inference_ms: Wall-clock inference time.
        redactor_version: The redax release that processed this request.
        model_name: Human-readable detector family name (e.g.
            ``"gliner2"``, ``"regex"``); *not* a model checkpoint hash.
            The checkpoint SHA-256 lives in ``MODEL_HASHES.txt`` and
            on disk under the model cache; it is intentionally not
            shipped in the per-event log.
        direction: ``"egress"`` for outbound redaction, ``"ingress"`` for
            restoration flows.
    """

    request_id: str
    ts: str
    policy_version: str
    text_chars: int
    entities_detected: list[dict[str, Any]] = field(default_factory=list)
    inference_ms: int = 0
    redactor_version: str = "0.1.0"
    model_name: str = ""
    trace_id: str = ""
    direction: str = "egress"


@runtime_checkable
class Backend(Protocol):
    """Persist ``Event`` somewhere durable. Implementations may buffer
    and flush asynchronously.
    """

    async def start(self) -> None:
        """Open any backing resource (file, socket, queue)."""
        ...

    async def stop(self) -> None:
        """Flush pending writes and close the backing resource."""
        ...

    async def record(self, event: Event) -> None:
        """Persist one event.

        Args:
            event: The audit event to record.
        """
        ...


def event_to_dict(event: Event) -> dict[str, Any]:
    """Convert an ``Event`` into a JSON-serialisable dict."""
    return asdict(event)


def span_summary(spans: list[Any]) -> list[dict[str, Any]]:
    """Aggregate detected spans into per-type count + mean confidence.

    Mirrors what the API routes report in audit events; spans are the
    detector Span objects. Never includes entity text.

    Args:
        spans: The detector ``Span`` objects detected for one request.

    Returns:
        A list of per-type ``{"type", "count", "confidence_avg"}`` dicts.
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


def pipeline_to_event(
    *,
    request_id: str,
    text_chars: int,
    policy_version: str,
    inference_ms: int,
    spans: list[Any],
    used_fallback: bool,
    model_checkpoint_hash: str = "",
    redactor_version: str = "0.1.0",
) -> Event:
    """Build an ``Event`` from a pipeline run.

    The event carries *aggregate* metrics (``used_fallback``,
    ``model_checkpoint_hash``) and per-type counts — never any original or
    redacted text — so the audit log remains safe to keep under any
    retention regime.

    Args:
        request_id: The correlation id for the request.
        text_chars: Length of the input text.
        policy_version: The policy version applied.
        inference_ms: Pipeline latency in milliseconds.
        spans: The detected spans.
        used_fallback: ``True`` if the pipeline fell back to regex-only.
        model_checkpoint_hash: SHA-256 of the model checkpoint.
        redactor_version: The redax release string.

    Returns:
        A new ``Event`` ready to hand to a ``Backend``.
    """
    entities = span_summary(spans)
    if used_fallback:
        entities = [{"type": "__used_fallback__", "count": 1, "confidence_avg": 0.0}, *entities]
    return Event(
        request_id=request_id,
        ts="",
        policy_version=policy_version,
        text_chars=text_chars,
        entities_detected=entities,
        inference_ms=inference_ms,
        redactor_version=redactor_version,
        model_name=model_checkpoint_hash,
        trace_id="",
    )
