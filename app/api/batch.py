from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, FastAPI, Request
from pydantic import BaseModel, Field

from app.errors import internal_error, payload_too_large
from app.observability import REQUEST_LATENCY, REQUESTS


class BatchItem(BaseModel):
    text: str = Field(min_length=1)
    entity_types: list[str] | None = None


class BatchRequest(BaseModel):
    items: list[BatchItem] = Field(min_length=1, max_length=1000)


class BatchResponse(BaseModel):
    results: list[dict]


def register(app: FastAPI) -> None:
    router = APIRouter()

    @router.post("/v1/redact/batch", response_model=BatchResponse)
    async def redact_batch(request: Request, body: BatchRequest) -> BatchResponse:
        from app.state import model_state

        start = time.perf_counter()
        endpoint = "POST /v1/redact/batch"
        method = "POST"
        try:
            settings = model_state.settings
            redactor = model_state.redactor
            if redactor is None:
                REQUESTS.labels(endpoint=endpoint, method=method, status="503").inc()
                return internal_error(request, "redactor not initialized")  # type: ignore[return-value]
            max_chars = getattr(settings, "max_text_chars", 100_000)
            for item in body.items:
                if len(item.text) > max_chars:
                    REQUESTS.labels(endpoint=endpoint, method=method, status="413").inc()
                    return payload_too_large(  # type: ignore[return-value]
                        request, f"item exceeds {max_chars} chars"
                    )
            results = await asyncio.gather(
                *(redactor.redact(item.text, entity_types=item.entity_types) for item in body.items)
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
        except Exception as exc:
            REQUESTS.labels(endpoint=endpoint, method=method, status="500").inc()
            return internal_error(request, str(exc))  # type: ignore[return-value]
        finally:
            REQUEST_LATENCY.labels(endpoint=endpoint, method=method).observe(
                time.perf_counter() - start
            )

    app.include_router(router)
