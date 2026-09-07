"""Typed container for long-lived resources wired during app startup.

The dataclass ``State`` is a typed bag of process-wide handles (redactor,
audit, settings, job store, pipeline, ...). One instance is created in
``app/main.py``'s lifespan and attached to ``app.state.state`` so every
route can reach it via ``request.app.state.state``. Tests inject a stub by
replacing ``app.state.state``.

The class is intentionally free of behavior: it does not own lifecycle,
does not wire resources, and does not import heavy modules. Methods
that mutate it (lifespan setup/teardown) live in ``app/main.py``.

Attributes:
    ready: ``True`` after lifespan startup completes; routes can reject
        requests with 503 while this is ``False``.
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
    job_store: ``JobStore`` for the in-process job queue; ``None``
        when Redis is unavailable.
    extras: Extension point for downstream deployments to stash
        arbitrary objects on the shared state.
    pipeline: The multi-stage redaction ``Pipeline`` (regex gate +
        model stage + consensus + circuit-broken fallback) used
        when ``/v1/redact`` is called with ``use_pipeline=true``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import Request

if TYPE_CHECKING:
    from app.redaction.pipeline import Pipeline


@dataclass
class State:
    """Typed container for process-wide long-lived resources.

    See module docstring for the full contract.
    """

    ready: bool = False
    detector: Any | None = None
    regex_detector: Any | None = None
    redactor: Any | None = None
    audit: Any | None = None
    settings: Any | None = None
    job_store: Any | None = None
    extras: dict[str, Any] = field(default_factory=dict)
    pipeline: Pipeline | None = None


def get_state(request: Request) -> State:
    """FastAPI dependency that yields the per-app ``State``.

    Use ``Depends(get_state)`` in route handlers so the typed container
    is injected by FastAPI's DI rather than read from a module global.

    Args:
        request: The active Starlette request, supplied by FastAPI.

    Returns:
        The ``State`` attached to ``app.state.state`` during lifespan.
    """
    state_any: Any = request.app.state.state
    assert isinstance(state_any, State)
    return state_any
