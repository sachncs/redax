"""Per-request logging middleware and request-id dependency.

Binds a request_id into the structlog context for the lifetime of the
request, echoes it back via the ``X-Request-ID`` response header, emits
one ``redax.access`` summary line, then clears the context so background
tasks don't inherit a stale id. Exposes a single ``get_request_id``
dependency that route handlers can use to read the bound id without
re-implementing the ``X-Request-ID or uuid`` fallback.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from re import fullmatch
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import Response

from app.errors import problem_response
from app.logging import get_logger
from app.observability import ADMISSION_REJECTIONS, REQUESTS_INFLIGHT, RESPONSE_SIZE
from app.observability.tracing import current_trace_id_hex


def safe_request_id(value: str | None) -> str:
    """Accept only bounded correlation IDs that are safe to place in logs."""
    if value and len(value) <= 128 and fullmatch(r"[A-Za-z0-9._:-]+", value):
        return value
    return uuid.uuid4().hex


def get_request_id(request: Request) -> str:
    """Return the per-request id bound by ``register_request_context``.

    Reads from the structlog context vars that the request middleware
    populates; falls back to a generated UUID if the middleware was
    never installed (tests that mount a bare FastAPI app).

    Args:
        request: The active Starlette request.

    Returns:
        The correlated request id (32-char hex).
    """
    bound = structlog.contextvars.get_contextvars().get("request_id")
    if isinstance(bound, str) and bound:
        return bound
    return safe_request_id(request.headers.get("X-Request-ID"))


def emit_access_line(
    *, method: str, path: str, status: int, duration_ms: int, request_id: str
) -> None:
    """Emit one ``redax.access`` log line for a completed request.

    Args:
        method: The HTTP verb that was used.
        path: The request path, including any prefix.
        status: The response status code (or 500 if the handler raised).
        duration_ms: Wall-clock duration of the request in milliseconds.
        request_id: The correlated request id, copied from
            ``X-Request-ID`` or generated server-side.
    """
    trace_id = current_trace_id_hex() or ""
    get_logger("redax.access").info(
        "redax.access",
        method=method,
        path=path,
        status=status,
        duration_ms=duration_ms,
        request_id=request_id,
        trace_id=trace_id,
    )


def register_request_context(app: FastAPI) -> None:
    """Carry a request_id across each request and log one access line.

    Uses the client's X-Request-ID (or a generated one), binds it into the
    structlog context so every structured log line for the request carries
    it, echoes it back in the X-Request-ID response header, emits one
    `redax.access` summary line per request, then clears the context so
    background tasks don't inherit a stale id.

    The status is recorded even when the handler raises (Starlette's
    ServerErrorMiddleware re-raises after sending the 500 body, so the
    summary line is emitted from the exception path too). On that path the
    header echo is skipped, since the body is sent after this middleware
    has already unwound.
    """

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Bind a per-request id, echo it on the response, and emit one access log line.

        The X-Request-ID header is reused if the client sent one; otherwise
        a server-side hex id is generated. The id is bound into the
        structlog context for the lifetime of the request so every
        structured log line carries it. Security headers
        (X-Content-Type-Options, X-Frame-Options, Referrer-Policy,
        Strict-Transport-Security) are stamped on every response.
        """
        request_id = safe_request_id(request.headers.get("X-Request-ID"))
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        status = 500
        admitted = False
        admission: Any | None = None
        response: Response
        try:
            state = getattr(request.app.state, "state", None)
            admission = getattr(state, "request_admission", None)
            probe = request.url.path in {"/healthz", "/readyz", "/metrics"}
            if admission is not None and not probe:
                if not getattr(state, "ready", False):
                    ADMISSION_REJECTIONS.labels(reason="draining").inc()
                    response = problem_response(
                        request,
                        type="https://redax.ai/errors/not-ready",
                        title="Not ready",
                        status=503,
                        detail="Service is draining or has not finished initializing",
                    )
                    response.headers["Retry-After"] = "1"
                    status = response.status_code
                    return response
                timeout_seconds = float(
                    getattr(
                        getattr(state, "settings", None),
                        "request_admission_timeout_seconds",
                        0.01,
                    )
                )
                try:
                    async with asyncio.timeout(timeout_seconds):
                        await admission.acquire()
                except TimeoutError:
                    ADMISSION_REJECTIONS.labels(reason="saturated").inc()
                    response = problem_response(
                        request,
                        type="https://redax.ai/errors/request-capacity",
                        title="Request capacity exhausted",
                        status=503,
                        detail="Request capacity is temporarily exhausted",
                    )
                    response.headers["Retry-After"] = "1"
                    status = response.status_code
                    return response
                admitted = True
                if state is not None:
                    state.active_requests += 1
                REQUESTS_INFLIGHT.inc()
            response = await call_next(request)
            content_length = response.headers.get("content-length")
            if content_length is not None:
                with suppress(ValueError):
                    RESPONSE_SIZE.observe(float(content_length))
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
            response.headers["X-Request-ID"] = request_id
            status = response.status_code
            return response
        finally:
            if admitted and admission is not None:
                state = getattr(request.app.state, "state", None)
                if state is not None:
                    state.active_requests = max(0, state.active_requests - 1)
                    if state.active_requests == 0 and state.drain_event is not None:
                        state.drain_event.set()
                REQUESTS_INFLIGHT.dec()
                admission.release()
            emit_access_line(
                method=request.method,
                path=request.url.path,
                status=status,
                duration_ms=int((time.perf_counter() - start) * 1000),
                request_id=request_id,
            )
            structlog.contextvars.clear_contextvars()
