"""RFC 7807 problem+json error responses for the redax FastAPI app.

Every error path returns an ``application/problem+json`` body. Unhandled
exceptions become a generic 500 problem without leaking internal details;
HTTPException and validation errors are converted too, so the public
error surface is uniform. TimeoutError (asyncio.timeout expiry) maps to
a 504 problem.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging import get_logger


@dataclass
class Problem:
    """RFC 7807 problem-details payload."""

    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None

    def to_response(self, request: Request) -> JSONResponse:
        """Serialize this problem as an ``application/problem+json`` response."""
        body: dict[str, Any] = {
            "type": self.type,
            "title": self.title,
            "status": self.status,
        }
        if self.detail is not None:
            body["detail"] = self.detail
        if self.instance is not None:
            body["instance"] = self.instance
        else:
            body["instance"] = str(request.url.path)
        return JSONResponse(
            content=body,
            status_code=self.status,
            media_type="application/problem+json",
        )


def problem_response(
    request: Request,
    *,
    type: str,
    title: str,
    status: int,
    detail: str | None = None,
    instance: str | None = None,
) -> JSONResponse:
    """Build a problem-details response from raw fields."""
    return Problem(
        type=type,
        title=title,
        status=status,
        detail=detail,
        instance=instance,
    ).to_response(request)


def bad_request(request: Request, detail: str) -> JSONResponse:
    """RFC 7807 400 problem with the caller's ``detail`` message."""
    return problem_response(
        request,
        type="https://redax.ai/errors/bad-request",
        title="Bad request",
        status=400,
        detail=detail,
    )


def unauthorized(request: Request, detail: str = "Invalid or missing API key") -> JSONResponse:
    """RFC 7807 401 problem for missing or bad API-key auth."""
    return problem_response(
        request,
        type="https://redax.ai/errors/unauthorized",
        title="Unauthorized",
        status=401,
        detail=detail,
    )


def rate_limited(request: Request, detail: str = "Rate limit exceeded") -> JSONResponse:
    """RFC 7807 429 problem when the per-API-key rate limit is exceeded."""
    return problem_response(
        request,
        type="https://redax.ai/errors/rate-limited",
        title="Too Many Requests",
        status=429,
        detail=detail,
    )


def queue_full(request: Request, detail: str = "Job queue is full") -> JSONResponse:
    """RFC 7807 429 problem when the in-process job queue has no room."""
    return problem_response(
        request,
        type="https://redax.ai/errors/queue-full",
        title="Queue Full",
        status=429,
        detail=detail,
    )


def job_limit(request: Request, detail: str = "Too many jobs for this API key") -> JSONResponse:
    """RFC 7807 429 problem when the per-API-key job quota is exceeded."""
    return problem_response(
        request,
        type="https://redax.ai/errors/job-limit",
        title="Too Many Jobs",
        status=429,
        detail=detail,
    )


def payload_too_large(request: Request, detail: str) -> JSONResponse:
    """RFC 7807 413 problem when ``text`` exceeds ``max_text_chars``."""
    return problem_response(
        request,
        type="https://redax.ai/errors/payload-too-large",
        title="Payload Too Large",
        status=413,
        detail=detail,
    )


def internal_error(request: Request, detail: str = "Internal server error") -> JSONResponse:
    """RFC 7807 500 problem for any unhandled exception."""
    return problem_response(
        request,
        type="https://redax.ai/errors/internal",
        title="Internal Server Error",
        status=500,
        detail=detail,
    )


def timeout_error(
    request: Request,
    detail: str = "Request exceeded the service timeout",
) -> JSONResponse:
    """RFC 7807 504 problem for per-request asyncio.timeout expiry."""
    return problem_response(
        request,
        type="https://redax.ai/errors/timeout",
        title="Gateway Timeout",
        status=504,
        detail=detail,
    )


def flatten_validation_errors(exc: RequestValidationError) -> list[str]:
    """Render a Pydantic validation error as one ``"loc: msg"`` string per field."""
    out: list[str] = []
    for error in exc.errors():
        loc = ".".join(str(p) for p in error.get("loc", ()))
        msg = error.get("msg", "invalid")
        out.append(f"{loc}: {msg}")
    return out


def install_error_handlers(app: FastAPI) -> None:
    """Register all RFC 7807 exception handlers on ``app``.

    Hooks the four error paths the API surface can produce:
    ``StarletteHTTPException`` (any raised HTTP status), the pydantic
    ``RequestValidationError`` from request body validation, ``TimeoutError``
    (asyncio.timeout expiry), and any uncaught ``Exception``.
    """

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Render a raised HTTP status as an RFC 7807 problem-details body."""
        detail = exc.detail if isinstance(exc.detail, str) else None
        title = detail or "Request failed"
        return problem_response(
            request,
            type=f"https://redax.ai/errors/http-{exc.status_code}",
            title=title,
            status=exc.status_code,
            detail=detail,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Render a pydantic validation failure as an RFC 7807 422 problem."""
        issues = flatten_validation_errors(exc)
        return problem_response(
            request,
            type="https://redax.ai/errors/validation-error",
            title="Validation error",
            status=422,
            detail="; ".join(issues) if issues else "Invalid request",
        )

    @app.exception_handler(TimeoutError)
    async def _timeout_error(request: Request, exc: TimeoutError) -> JSONResponse:
        """Render an asyncio.timeout expiry as an RFC 7807 504 problem."""
        get_logger("redax.errors").warning("redax.request_timeout", exc_info=exc)
        return timeout_error(request)

    @app.exception_handler(Exception)
    async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        """Render any uncaught exception as a generic RFC 7807 500 problem."""
        get_logger("redax.errors").error("redax.unhandled_error", exc_info=exc)
        return problem_response(
            request,
            type="https://redax.ai/errors/internal",
            title="Internal Server Error",
            status=500,
        )
