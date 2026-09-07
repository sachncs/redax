"""Async job submission + status endpoints (``/v1/jobs``).

Submission is rate-limited and per-key admission-capped; the actual
redaction runs as a background task that writes its outcome back into
the shared ``JobStore``. ``record_failure`` is a small helper for the
failure path used by both the worker and the timeout handler.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.audit.backend import Event, span_summary
from app.auth import require_api_key
from app.errors import internal_error, job_limit, payload_too_large, problem_response, queue_full
from app.jobs.store import JobStore
from app.logging import get_logger
from app.observability import ERRORS, QUEUE_DEPTH, REQUESTS, queue_depth
from app.ratelimit import rate_limit
from app.state import State, get_state

JOB_FAILED = "job failed"


class JobSubmit(BaseModel):
    """Request body for POST /v1/jobs."""

    text: str = Field(min_length=1)
    policy: dict[str, Any] | None = None
    entity_types: list[str] | None = None


def register(app: FastAPI) -> None:
    """Mount the POST /v1/jobs and GET /v1/jobs/{id} routes on ``app``."""

    router = APIRouter()

    @router.post("/v1/jobs", status_code=202, response_model=None)
    async def submit_job(
        body: JobSubmit,
        background_tasks: BackgroundTasks,
        request: Request,
        state: Annotated[State, Depends(get_state)],
        api_key: Annotated[str, Depends(require_api_key)],
    ) -> dict[str, Any] | JSONResponse:
        """Admit a new redaction job; schedule the worker and return the job id."""
        endpoint = "POST /v1/jobs"
        method = "POST"
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex

        await rate_limit(api_key, state)
        try:
            settings = state.settings
            max_chars = getattr(settings, "max_text_chars", 100_000)
            if len(body.text) > max_chars:
                REQUESTS.labels(endpoint=endpoint, method=method, status="413").inc()
                return payload_too_large(request, f"text exceeds {max_chars} chars")
            store: JobStore | None = state.job_store
            if store is None:
                REQUESTS.labels(endpoint=endpoint, method=method, status="503").inc()
                return internal_error(request, "job store not initialized")
            max_inflight = getattr(settings, "max_inflight", 32)
            if queue_depth() >= max_inflight:
                REQUESTS.labels(endpoint=endpoint, method=method, status="429").inc()
                return queue_full(request)
            max_jobs_per_key = getattr(settings, "max_jobs_per_key", 50)
            if await store.count_for_key(api_key) >= max_jobs_per_key:
                REQUESTS.labels(endpoint=endpoint, method=method, status="429").inc()
                return job_limit(request)
            record = await store.create(owner=api_key)
            QUEUE_DEPTH.inc()
            background_tasks.add_task(
                run_job, record.id, body.model_dump(), store, request_id, state
            )
            REQUESTS.labels(endpoint=endpoint, method=method, status="202").inc()
            return {"id": record.id, "status": record.status}
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            REQUESTS.labels(endpoint=endpoint, method=method, status="500").inc()
            get_logger("redax.api").error("redax.queue_failed", error=exc.__class__.__name__)
            return internal_error(request)

    @router.get("/v1/jobs/{job_id}", response_model=None)
    async def get_job(
        job_id: str,
        request: Request,
        state: Annotated[State, Depends(get_state)],
        api_key: Annotated[str, Depends(require_api_key)],
    ) -> dict[str, Any] | JSONResponse:
        """Return the current status, result, and error marker for ``job_id``."""
        endpoint = "GET /v1/jobs/{id}"
        method = "GET"
        store: JobStore | None = state.job_store
        if store is None:
            REQUESTS.labels(endpoint=endpoint, method=method, status="503").inc()
            return internal_error(request, "job store not initialized")
        record = await store.get(job_id)
        if record is None:
            REQUESTS.labels(endpoint=endpoint, method=method, status="404").inc()
            return problem_response(
                request,
                type="https://redax.ai/errors/job-not-found",
                title="Job not found",
                status=404,
                detail=f"No job with id {job_id!r}",
            )
        REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
        return {
            "id": record.id,
            "status": record.status,
            "result": record.result,
            "error": JOB_FAILED if record.status == "failed" else None,
        }

    app.include_router(router)


async def run_job(
    job_id: str,
    payload: dict[str, Any],
    store: JobStore,
    request_id: str,
    state: State,
) -> None:
    """Background-task worker that re-runs the redactor and writes back.

    The state is captured at submit time and passed in because the
    background task runs after the originating request has returned;
    there is no live request to read ``request.app.state`` from.
    """
    logger = get_logger("redax.jobs")
    try:
        await store.set_status(job_id, "running")
    except (OSError, TimeoutError, RuntimeError) as exc:
        ERRORS.labels(type="job_store_unavailable").inc()
        logger.error("redax.job_store_unavailable", job_id=job_id, error=exc.__class__.__name__)
        QUEUE_DEPTH.dec()
        return
    start = time.perf_counter()
    redactor = state.redactor
    if redactor is None:
        ERRORS.labels(type="job_redactor_unavailable").inc()
        await record_failure(job_id, store, logger)
        logger.error("redax.job_failed", job_id=job_id, error="redactor not initialized")
        QUEUE_DEPTH.dec()
        return
    try:
        timeout_seconds = getattr(state.settings, "request_timeout_seconds", 30.0)
        async with asyncio.timeout(timeout_seconds):
            result = await redactor.redact(
                payload["text"],
                policy=payload.get("policy"),
                entity_types=payload.get("entity_types"),
            )
        inference_ms = int((time.perf_counter() - start) * 1000)
        await store.set_result(
            job_id,
            {
                "text": result.text,
                "spans": [s.__dict__ for s in result.spans],
                "relex_map": result.relex_map,
                "inference_ms": inference_ms,
            },
        )
        audit = state.audit
        if audit is not None:
            await audit.record(
                Event(
                    request_id=request_id,
                    ts="",
                    policy_version="default",
                    text_chars=len(payload["text"]),
                    entities_detected=span_summary(result.spans),
                    inference_ms=inference_ms,
                )
            )
    except TimeoutError:
        logger.error("redax.job_timeout", job_id=job_id)
        ERRORS.labels(type="job_timeout").inc()
        await record_failure(job_id, store, logger)
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        logger.error("redax.job_failed", job_id=job_id, error=exc)
        ERRORS.labels(type="job_failed").inc()
        await record_failure(job_id, store, logger)
    finally:
        QUEUE_DEPTH.dec()


async def record_failure(job_id: str, store: JobStore, logger: Any) -> None:
    """Mark a job as failed in the JobStore; logs and counts write failures."""
    try:
        await store.set_error(job_id, JOB_FAILED)
    except (OSError, TimeoutError, RuntimeError):
        logger.error("redax.job_store_write_failed", job_id=job_id)
        ERRORS.labels(type="job_store_write_failed").inc()
