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
    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None

    def to_response(self, request: Request) -> JSONResponse:
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
    return Problem(
        type=type,
        title=title,
        status=status,
        detail=detail,
        instance=instance,
    ).to_response(request)


def bad_request(request: Request, detail: str) -> JSONResponse:
    return problem_response(
        request,
        type="https://redax.ai/errors/bad-request",
        title="Bad request",
        status=400,
        detail=detail,
    )


def unauthorized(request: Request, detail: str = "Invalid or missing API key") -> JSONResponse:
    return problem_response(
        request,
        type="https://redax.ai/errors/unauthorized",
        title="Unauthorized",
        status=401,
        detail=detail,
    )


def rate_limited(request: Request, detail: str = "Rate limit exceeded") -> JSONResponse:
    return problem_response(
        request,
        type="https://redax.ai/errors/rate-limited",
        title="Too Many Requests",
        status=429,
        detail=detail,
    )


def payload_too_large(request: Request, detail: str) -> JSONResponse:
    return problem_response(
        request,
        type="https://redax.ai/errors/payload-too-large",
        title="Payload Too Large",
        status=413,
        detail=detail,
    )


def internal_error(request: Request, detail: str = "Internal server error") -> JSONResponse:
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
    """RFC 7807 response for per-request asyncio.timeout expiry (504)."""
    return problem_response(
        request,
        type="https://redax.ai/errors/timeout",
        title="Gateway Timeout",
        status=504,
        detail=detail,
    )


def _flatten_validation_errors(exc: RequestValidationError) -> list[str]:
    out: list[str] = []
    for error in exc.errors():
        loc = ".".join(str(p) for p in error.get("loc", ()))
        msg = error.get("msg", "invalid")
        out.append(f"{loc}: {msg}")
    return out


def install_error_handlers(app: FastAPI) -> None:
    """Route every error path to RFC 7807 application/problem+json bodies.

    Unhandled exceptions become a generic 500 problem without leaking
    internal details; HTTPException (e.g. auth 401) and validation errors
    are converted too, so the public error surface is uniform.
    TimeoutError (asyncio.timeout expiry) maps to a 504 problem.
    """

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
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
        issues = _flatten_validation_errors(exc)
        return problem_response(
            request,
            type="https://redax.ai/errors/validation-error",
            title="Validation error",
            status=422,
            detail="; ".join(issues) if issues else "Invalid request",
        )

    @app.exception_handler(TimeoutError)
    async def _timeout_error(request: Request, exc: TimeoutError) -> JSONResponse:
        get_logger("redax.errors").warning("redax.request_timeout", exc_info=exc)
        return timeout_error(request)

    @app.exception_handler(Exception)
    async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        get_logger("redax.errors").error("redax.unhandled_error", exc_info=exc)
        return problem_response(
            request,
            type="https://redax.ai/errors/internal",
            title="Internal Server Error",
            status=500,
        )
