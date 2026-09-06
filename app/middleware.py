from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import Response

from app.logging import get_logger


def emit_access_line(
    *, method: str, path: str, status: int, duration_ms: int, request_id: str
) -> None:
    get_logger("redax.access").info(
        "redax.access",
        method=method,
        path=path,
        status=status,
        duration_ms=duration_ms,
        request_id=request_id,
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
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            status = response.status_code
            return response
        finally:
            emit_access_line(
                method=request.method,
                path=request.url.path,
                status=status,
                duration_ms=int((time.perf_counter() - start) * 1000),
                request_id=request_id,
            )
            structlog.contextvars.clear_contextvars()
