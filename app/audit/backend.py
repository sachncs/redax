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
