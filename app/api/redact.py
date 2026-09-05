from __future__ import annotations

import time

from fastapi import APIRouter, FastAPI, Request
from pydantic import BaseModel, Field

from app.errors import internal_error, payload_too_large
from app.inference.detector import Span
from app.observability import REQUEST_LATENCY, REQUESTS


class RedactRequest(BaseModel):
    text: str = Field(min_length=1)
    entity_types: list[str] | None = None


class RedactResponse(BaseModel):
    text: str
    spans: list[Span]
    relex_map: dict[str, str]


def register(app: FastAPI) -> None:
    router = APIRouter()

    @router.post("/v1/redact", response_model=RedactResponse)
    async def redact(request: Request, body: RedactRequest) -> RedactResponse:
        from app.state import model_state

        start = time.perf_counter()
        endpoint = "POST /v1/redact"
        method = "POST"
        try:
            settings = model_state.settings
            if settings is not None and len(body.text) > settings.max_text_chars:
                REQUESTS.labels(endpoint=endpoint, method=method, status="413").inc()
                return payload_too_large(  # type: ignore[return-value]
                    request,
                    f"text exceeds {settings.max_text_chars} chars",
                )
            redactor = model_state.redactor
            if redactor is None:
                REQUESTS.labels(endpoint=endpoint, method=method, status="503").inc()
                return internal_error(request, "redactor not initialized")  # type: ignore[return-value]
            result = await redactor.redact(body.text, body.entity_types)
            REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
            return RedactResponse(
                text=result.text,
                spans=result.spans,
                relex_map=result.relex_map,
            )
        except Exception as exc:
            REQUESTS.labels(endpoint=endpoint, method=method, status="500").inc()
            return internal_error(request, str(exc))  # type: ignore[return-value]
        finally:
            REQUEST_LATENCY.labels(endpoint=endpoint, method=method).observe(
                time.perf_counter() - start
            )

    app.include_router(router)
