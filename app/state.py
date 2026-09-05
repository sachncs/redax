from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ModelState:
    ready: bool = False
    detector: object | None = None
    regex_detector: object | None = None
    redactor: object | None = None
    audit: object | None = None
    settings: object | None = None
    shutdown_event: object | None = None
    extras: dict = field(default_factory=dict)


model_state = ModelState()
