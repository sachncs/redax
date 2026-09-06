from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.auth import require_api_key
from app.errors import internal_error, payload_too_large
from app.observability import REQUESTS


class StreamRequest(BaseModel):
    text: str = Field(min_length=1)
    policy: dict[str, Any] | None = None
    entity_types: list[str] | None = None
    chunk_chars: int = Field(default=2000, ge=100, le=50_000)


def register(app: FastAPI) -> None:
    router = APIRouter()

    @router.post("/v1/redact/stream", response_model=None)
    async def redact_stream(
        request: Request,
        body: StreamRequest,
        api_key: Annotated[str, Depends(require_api_key)],
    ) -> StreamingResponse | JSONResponse:
        from app.state import model_state

        endpoint = "POST /v1/redact/stream"
        method = "POST"
        settings = model_state.settings
        redactor = model_state.redactor
        if redactor is None:
            REQUESTS.labels(endpoint=endpoint, method=method, status="503").inc()
            return internal_error(request, "redactor not initialized")
        max_chars = getattr(settings, "max_text_chars", 100_000)
        if len(body.text) > max_chars:
            REQUESTS.labels(endpoint=endpoint, method=method, status="413").inc()
            return payload_too_large(request, f"text exceeds {max_chars} chars")
        from app.ratelimit import rate_limit

        await rate_limit(api_key)
        timeout_seconds = getattr(settings, "request_timeout_seconds", 30.0)

        async def event_source() -> AsyncIterator[str]:
            text = body.text
            chunk = body.chunk_chars
            try:
                for start in range(0, len(text), chunk):
                    piece = text[start : start + chunk]
                    try:
                        async with asyncio.timeout(timeout_seconds):
                            result = await redactor.redact(
                                piece,
                                policy=body.policy,
                                entity_types=body.entity_types,
                            )
                    except TimeoutError:
                        REQUESTS.labels(endpoint=endpoint, method=method, status="504").inc()
                        yield f"data: {json.dumps({'error': 'request timeout', 'status': 504})}\n\n"
                        return
                    payload = {
                        "text": result.text,
                        "spans": [s.__dict__ for s in result.spans],
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                yield "data: [DONE]\n\n"
                REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
            except Exception:
                yield f"data: {json.dumps({'error': 'internal error'})}\n\n"
                REQUESTS.labels(endpoint=endpoint, method=method, status="500").inc()

        return StreamingResponse(event_source(), media_type="text/event-stream")

    app.include_router(router)
