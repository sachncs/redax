from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


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
