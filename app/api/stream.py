from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.errors import internal_error
from app.observability import REQUESTS


class StreamRequest(BaseModel):
    text: str = Field(min_length=1)
    policy: dict[str, Any] | None = None
    entity_types: list[str] | None = None
    chunk_chars: int = Field(default=2000, ge=100, le=50_000)


def register(app: FastAPI) -> None:
    router = APIRouter()

    @router.post("/v1/redact/stream")
    async def redact_stream(request: Request, body: StreamRequest) -> StreamingResponse:
        from app.state import model_state

        endpoint = "POST /v1/redact/stream"
        method = "POST"
        redactor = model_state.redactor
        if redactor is None:
            REQUESTS.labels(endpoint=endpoint, method=method, status="503").inc()
            return internal_error(request, "redactor not initialized")  # type: ignore[return-value]

        async def event_source() -> AsyncIterator[str]:
            text = body.text
            chunk = body.chunk_chars
            try:
                for start in range(0, len(text), chunk):
                    piece = text[start : start + chunk]
                    result = await redactor.redact(
                        piece,
                        policy=body.policy,
                        entity_types=body.entity_types,
                    )
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
