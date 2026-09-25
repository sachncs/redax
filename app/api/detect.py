"""Detection-only endpoint (``POST /v1/detect``).

Unlike ``/v1/redact``, this diagnostic surface intentionally returns the input
text alongside validated spans. Callers must not forward its ``text`` field to
downstream systems as if it were redacted output.
"""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import BaseModel, Field

from app.audit.backend import Event, span_summary
from app.auth import require_api_key
from app.errors import TRANSIENT_EXC, internal_error, payload_too_large, timeout_error
from app.logging import get_logger
from app.middleware import get_request_id
from app.observability import REQUEST_LATENCY, REQUESTS
from app.ratelimit import rate_limit
from app.redaction.apply import dedupe_overlaps
from app.redaction.offsets import validate_offsets
from app.state import State, get_state


class DetectRequest(BaseModel):
    """Request body for ``POST /v1/detect``."""

    text: str = Field(min_length=1)
    entity_types: list[str] | None = None


class DetectResponse(BaseModel):
    """Detection result containing the original text and validated spans."""

    text: str
    spans: list[dict[str, Any]]


def register(app: FastAPI) -> None:
    """Mount the detection-only route."""

    router = APIRouter()

    @router.post("/v1/detect", response_model=DetectResponse)
    async def detect(
        request: Request,
        body: DetectRequest,
        state: Annotated[State, Depends(get_state)],
        api_key: Annotated[str, Depends(require_api_key)],
        request_id: Annotated[str, Depends(get_request_id)] = "",
    ) -> DetectResponse | Any:
        """Return original text plus detector spans for diagnostics only."""
        endpoint = "POST /v1/detect"
        method = "POST"
        start = time.perf_counter()
        await rate_limit(api_key, state)
        try:
            settings = state.settings
            max_chars = getattr(settings, "max_text_chars", 100_000)
            if len(body.text) > max_chars:
                REQUESTS.labels(endpoint=endpoint, method=method, status="413").inc()
                return payload_too_large(request, f"text exceeds {max_chars} chars")
            detector = state.detector or state.regex_detector
            if detector is None:
                REQUESTS.labels(endpoint=endpoint, method=method, status="503").inc()
                return internal_error(request, "detector not initialized")
            timeout_seconds = getattr(settings, "request_timeout_seconds", 30.0)
            async with asyncio.timeout(timeout_seconds):
                raw_spans = await detector.detect(body.text, body.entity_types or [])
            spans = dedupe_overlaps(validate_offsets(body.text, raw_spans))
            if state.audit is not None:
                from app.observability.tracing import current_trace_id_hex

                await state.audit.record(
                    Event(
                        request_id=request_id,
                        ts="",
                        policy_version="detect",
                        text_chars=len(body.text),
                        entities_detected=span_summary(spans),
                        trace_id=current_trace_id_hex() or "",
                        direction="detect",
                    )
                )
            REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
            return DetectResponse(
                text=body.text,
                spans=[s.__dict__ for s in spans],
            )
        except TimeoutError:
            REQUESTS.labels(endpoint=endpoint, method=method, status="504").inc()
            return timeout_error(request)
        except TRANSIENT_EXC as exc:
            REQUESTS.labels(endpoint=endpoint, method=method, status="500").inc()
            get_logger("redax.api").error("redax.detect_failed", error=exc.__class__.__name__)
            return internal_error(request)
        finally:
            REQUEST_LATENCY.labels(endpoint=endpoint, method=method).observe(
                time.perf_counter() - start
            )

    app.include_router(router)
