"""Shared application state populated by the FastAPI lifespan."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import Request

if TYPE_CHECKING:
    from app.redaction.pipeline import Pipeline


@dataclass
class State:
    """Long-lived process state shared between the lifespan and the routes.

    Populated once during ``app/main.py`` lifespan startup and read by
    every API route. No route should mutate this object; if a route
    needs to share transient state with another route, use the
    request-scoped ``Request.state`` instead.

    Attributes:
        ready: ``True`` after lifespan startup completes; routes can
            reject requests with 503 while this is ``False``.
        detector: The primary encoder (GLiNER2 or OpenMed) used by the
            legacy ``Redactor`` path and the multi-stage pipeline.
        regex_detector: The deterministic regex detector used as the
            Stage-1 high-precision anchor in the pipeline and as the
            default fallback when no encoder is configured.
        redactor: The legacy ``Redactor`` orchestrator; kept for the
            default ``/v1/redact`` path when the pipeline is disabled.
        audit: The ``Backend`` for the JSONL redaction log; every
            successful ``/v1/redact`` records counts/durations only,
            never input or output text.
        settings: The validated pydantic-settings ``Settings`` instance.
        shutdown_event: ``asyncio.Event`` set during lifespan teardown.
        job_store: ``JobStore`` for the in-process job queue; ``None``
            when Redis is unavailable.
        redis: The async Redis client used by ``JobStore`` and the
            rate limiter; ``None`` when Redis is unavailable.
        extras: Extension point for downstream deployments to stash
            arbitrary objects on the shared state.
        request: The currently-active ``Request``; ``None`` outside a
            request scope. Routes should prefer ``request.state`` for
            per-request data.
        pipeline: The multi-stage redaction ``Pipeline`` (regex gate +
            model stage + consensus + circuit-broken fallback) used
            when ``/v1/redact`` is called with ``use_pipeline=true``.
    """

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


state = State()
