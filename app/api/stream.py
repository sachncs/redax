"""Streaming NDJSON chunk transport for /v1/redact/stream."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.auth import require_api_key
from app.errors import internal_error, payload_too_large
from app.logging import get_logger
from app.observability import REQUEST_LATENCY, REQUESTS


class StreamRequest(BaseModel):
    text: str = Field(min_length=1)
    policy: dict[str, Any] | None = None
    entity_types: list[str] | None = None
    chunk_chars: int | None = Field(default=None, ge=100, le=50_000)


def split_chunks(text: str, chunk_chars: int, chunk_bytes: int) -> list[str]:
    """Split text into chunks bounded by char and UTF-8 byte budgets.

    Chunks cover the text in order, are non-empty, and each is no longer
    than `chunk_chars` characters and no larger than `chunk_bytes` bytes.
    Boundaries fall between code points; a single character that alone
    exceeds the byte budget becomes its own chunk rather than blocking.
    """
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_chars, len(text))
        while end > start and len(text[start:end].encode("utf-8")) > chunk_bytes:
            end -= 1
        if end == start:
            end = start + 1
        chunks.append(text[start:end])
        start = end
    return chunks


def register(app: FastAPI) -> None:
    router = APIRouter()

    @router.post("/v1/redact/stream", response_model=None)
    async def redact_stream(
        request: Request,
        body: StreamRequest,
        api_key: Annotated[str, Depends(require_api_key)],
    ) -> StreamingResponse | JSONResponse:
        from app.audit.backend import AuditEvent, span_summary
        from app.state import model_state

        endpoint = "POST /v1/redact/stream"
        method = "POST"
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        settings = model_state.settings
        redactor = model_state.redactor
        audit = model_state.audit
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
        chunk_bytes = getattr(settings, "stream_chunk_bytes", 4096)
        default_chunk_chars = getattr(settings, "stream_chunk_chars", 2000)
        latency_start = time.perf_counter()

        async def event_source() -> AsyncIterator[str]:
            try:
                text = body.text
                chunk = body.chunk_chars or default_chunk_chars
                all_spans: list[Any] = []
                inference_ms = 0
                for piece in split_chunks(text, chunk, chunk_bytes):
                    try:
                        async with asyncio.timeout(timeout_seconds):
                            inference_start = time.perf_counter()
                            result = await redactor.redact(
                                piece,
                                policy=body.policy,
                                entity_types=body.entity_types,
                            )
                            inference_ms += int((time.perf_counter() - inference_start) * 1000)
                    except TimeoutError:
                        REQUESTS.labels(endpoint=endpoint, method=method, status="504").inc()
                        yield f"data: {json.dumps({'error': 'request timeout', 'status': 504})}\n\n"
                        return
                    all_spans.extend(result.spans)
                    payload = {
                        "text": result.text,
                        "spans": [s.__dict__ for s in result.spans],
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                yield "data: [DONE]\n\n"
                if audit is not None:
                    await audit.record(
                        AuditEvent(
                            request_id=request_id,
                            ts="",
                            policy_version="default",
                            text_chars=len(text),
                            entities_detected=span_summary(all_spans),
                            inference_ms=inference_ms,
                        )
                    )
                REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
            except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
                yield f"data: {json.dumps({'error': 'internal error'})}\n\n"
                REQUESTS.labels(endpoint=endpoint, method=method, status="500").inc()
                get_logger("redax.api").error(
                    "redax.stream_chunk_failed", error=exc.__class__.__name__
                )
            finally:
                REQUEST_LATENCY.labels(endpoint=endpoint, method=method).observe(
                    time.perf_counter() - latency_start
                )

        return StreamingResponse(event_source(), media_type="text/event-stream")

    app.include_router(router)
