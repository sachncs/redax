from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import Response


def register_request_context(app: FastAPI) -> None:
    """Carry a request_id across each request.

    Uses the client's X-Request-ID (or a generated one), binds it into the
    structlog context so every structured log line for the request carries
    it, echoes it back in the X-Request-ID response header, then clears the
    context so background tasks don't inherit a stale id.
    """

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            structlog.contextvars.clear_contextvars()
