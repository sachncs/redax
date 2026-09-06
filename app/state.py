from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import Request

if TYPE_CHECKING:
    from app.redaction.pipeline import Pipeline


@dataclass
class ModelState:
    ready: bool = False
    detector: Any | None = None
    regex_detector: Any | None = None
    redactor: Any | None = None
    audit: Any | None = None
    settings: Any | None = None
    shutdown_event: Any | None = None
    job_store: Any | None = None
    redis: Any | None = None
    extras: dict[str, Any] = field(default_factory=dict)
    request: Request | None = None
    pipeline: Pipeline | None = None


model_state = ModelState()
