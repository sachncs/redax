from __future__ import annotations

import asyncio
import time
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import require_api_key
from app.errors import internal_error, payload_too_large, timeout_error
from app.observability import REQUEST_LATENCY, REQUESTS


class BatchItem(BaseModel):
    text: str = Field(min_length=1)
    entity_types: list[str] | None = None


class BatchRequest(BaseModel):
    items: list[BatchItem] = Field(min_length=1, max_length=1000)


class BatchResponse(BaseModel):
    results: list[dict[str, Any]]


def register(app: FastAPI) -> None:
    router = APIRouter()

    @router.post("/v1/redact/batch", response_model=BatchResponse)
    async def redact_batch(
        request: Request,
        body: BatchRequest,
        api_key: Annotated[str, Depends(require_api_key)],
    ) -> BatchResponse | JSONResponse:
        from app.audit.backend import AuditEvent, span_summary
        from app.state import model_state

        start = time.perf_counter()
        endpoint = "POST /v1/redact/batch"
        method = "POST"
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        from app.ratelimit import rate_limit

        await rate_limit(api_key)
        try:
            settings = model_state.settings
            redactor = model_state.redactor
            audit = model_state.audit
            if redactor is None:
                REQUESTS.labels(endpoint=endpoint, method=method, status="503").inc()
                return internal_error(request, "redactor not initialized")
            max_chars = getattr(settings, "max_text_chars", 100_000)
            for item in body.items:
                if len(item.text) > max_chars:
                    REQUESTS.labels(endpoint=endpoint, method=method, status="413").inc()
                    return payload_too_large(request, f"item exceeds {max_chars} chars")
            timeout_seconds = getattr(settings, "request_timeout_seconds", 30.0)
            inference_start = time.perf_counter()
            async with asyncio.timeout(timeout_seconds):
                results = await asyncio.gather(
                    *(
                        redactor.redact(item.text, entity_types=item.entity_types)
                        for item in body.items
                    )
                )
            inference_ms = int((time.perf_counter() - inference_start) * 1000)
            if audit is not None:
                spans = [s for r in results for s in r.spans]
                await audit.record(
                    AuditEvent(
                        request_id=request_id,
                        ts="",
                        policy_version="default",
                        text_chars=sum(len(item.text) for item in body.items),
                        entities_detected=span_summary(spans),
                        inference_ms=inference_ms,
                    )
                )
            REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
            return BatchResponse(
                results=[
                    {
                        "text": r.text,
                        "spans": [s.__dict__ for s in r.spans],
                        "relex_map": r.relex_map,
                    }
                    for r in results
                ]
            )
        except TimeoutError:
            REQUESTS.labels(endpoint=endpoint, method=method, status="504").inc()
            return timeout_error(request)
        except Exception:
            REQUESTS.labels(endpoint=endpoint, method=method, status="500").inc()
            return internal_error(request)
        finally:
            REQUEST_LATENCY.labels(endpoint=endpoint, method=method).observe(
                time.perf_counter() - start
            )

    app.include_router(router)
