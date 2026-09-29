"""Async job submission + status endpoints (``/v1/jobs``).

Submission is rate-limited and per-key admission-capped; the actual
redaction runs in the durable ARQ worker and writes its outcome back into
the shared ``JobStore``. ``record_failure`` is a small helper for the
failure path used by both the worker and the timeout handler.
"""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from app.api.policy import default_policy, policy_version
from app.audit.backend import Event, span_summary
from app.auth import principal_id, require_scope
from app.errors import (
    TRANSIENT_EXC,
    internal_error,
    job_limit,
    job_store_unavailable,
    payload_too_large,
    problem_response,
    queue_full,
)
from app.jobs.payload import JobPayloadCipher
from app.jobs.store import JobStore
from app.logging import get_logger
from app.middleware import get_request_id
from app.observability import ERRORS, JOB_DURATION, QUEUE_DEPTH, REQUESTS, decrement_queue_depth
from app.ratelimit import rate_limit
from app.state import State, get_state

JOB_FAILED = "job failed"


def store_available(store: JobStore | None) -> bool:
    """Return whether a retained store has a usable Redis client.

    In-memory test/development stores may intentionally omit ``client``;
    those stores remain available. A real ``JobStore`` retains its handle
    across reconnects, so ``client is None`` means the dependency is down.
    """
    return store is not None and (not hasattr(store, "client") or store.client is not None)


class JobSubmit(BaseModel):
    """Request body for POST /v1/jobs."""

    text: str = Field(min_length=1)
    policy: dict[str, Any] | None = None
    entity_types: list[str] | None = None


def register(app: FastAPI) -> None:
    """Mount the async job submission, polling, and cancellation routes."""

    router = APIRouter()

    @router.post("/v1/jobs", status_code=202, response_model=None)
    async def submit_job(
        body: JobSubmit,
        request: Request,
        state: Annotated[State, Depends(get_state)],
        api_key: Annotated[str, Depends(require_scope("jobs"))],
        request_id: Annotated[str, Depends(get_request_id)] = "",
    ) -> dict[str, Any] | JSONResponse:
        """Admit a new redaction job; schedule the worker and return the job id."""
        endpoint = "POST /v1/jobs"
        method = "POST"

        await rate_limit(api_key, state)
        try:
            settings = state.settings
            max_chars = getattr(settings, "max_text_chars", 100_000)
            if len(body.text) > max_chars:
                REQUESTS.labels(endpoint=endpoint, method=method, status="413").inc()
                return payload_too_large(request, f"text exceeds {max_chars} chars")
            if api_key == "anonymous":
                REQUESTS.labels(endpoint=endpoint, method=method, status="401").inc()
                return problem_response(
                    request,
                    type="https://redax.ai/errors/anonymous-jobs",
                    title="Anonymous Jobs Disabled",
                    status=401,
                    detail=(
                        "/v1/jobs requires authentication; configure REDAX_API_KEYS "
                        "and pass the matching X-API-Key header."
                    ),
                )
            store: JobStore | None = state.job_store
            queue = state.job_queue
            if store is None or queue is None:
                REQUESTS.labels(endpoint=endpoint, method=method, status="503").inc()
                return job_store_unavailable(request, "durable job queue not initialized")
            max_inflight = getattr(settings, "max_inflight", 32)
            max_jobs_per_key = getattr(settings, "max_jobs_per_key", 50)
            try:
                record = await store.create_admitted(api_key, max_inflight, max_jobs_per_key)
            except AttributeError:
                if await store.count_inflight() >= max_inflight:
                    REQUESTS.labels(endpoint=endpoint, method=method, status="429").inc()
                    return queue_full(request)
                if await store.count_for_key(api_key) >= max_jobs_per_key:
                    REQUESTS.labels(endpoint=endpoint, method=method, status="429").inc()
                    return job_limit(request)
                record = await store.create(owner=api_key)
            except (OSError, RedisError, RuntimeError, ValueError, KeyError, TimeoutError) as exc:
                get_logger("redax.api").error(
                    "redax.job_create_failed", error=exc.__class__.__name__
                )
                REQUESTS.labels(endpoint=endpoint, method=method, status="500").inc()
                return internal_error(request, "job counter write failed")
            if record is None:
                REQUESTS.labels(endpoint=endpoint, method=method, status="429").inc()
                return queue_full(request)
            QUEUE_DEPTH.inc()
            try:
                queue_payload = JobPayloadCipher(
                    getattr(settings, "job_payload_encryption_key", "")
                ).encode(body.model_dump())
                queued = await queue.enqueue_job(
                    "process_job",
                    record.id,
                    queue_payload,
                    request_id,
                    principal_identifier=principal_id(api_key, getattr(settings, "hash_salt", "")),
                    _job_id=record.id,
                    _queue_name="redax:jobs",
                )
                if queued is None:
                    raise RuntimeError("job was already queued")
            except TRANSIENT_EXC as exc:
                await record_failure(record.id, store, get_logger("redax.jobs"))
                get_logger("redax.api").error(
                    "redax.job_enqueue_failed", error=exc.__class__.__name__
                )
                REQUESTS.labels(endpoint=endpoint, method=method, status="503").inc()
                return job_store_unavailable(request, "durable job queue unavailable")
            REQUESTS.labels(endpoint=endpoint, method=method, status="202").inc()
            return {"id": record.id, "status": record.status}
        except TRANSIENT_EXC as exc:
            REQUESTS.labels(endpoint=endpoint, method=method, status="500").inc()
            get_logger("redax.api").error("redax.queue_failed", error=exc.__class__.__name__)
            return internal_error(request)

    @router.get("/v1/jobs/{job_id}", response_model=None)
    async def get_job(
        job_id: str,
        request: Request,
        state: Annotated[State, Depends(get_state)],
        api_key: Annotated[str, Depends(require_scope("jobs"))],
    ) -> dict[str, Any] | JSONResponse:
        """Return the current status, result, and error marker for ``job_id``."""
        endpoint = "GET /v1/jobs/{id}"
        method = "GET"
        store: JobStore | None = state.job_store
        if not store_available(store):
            REQUESTS.labels(endpoint=endpoint, method=method, status="503").inc()
            return job_store_unavailable(request, "durable job store unavailable")
        assert store is not None
        record = await store.get(job_id)
        if record is None or record.owner != store.owner_token(api_key):
            REQUESTS.labels(endpoint=endpoint, method=method, status="404").inc()
            return problem_response(
                request,
                type="https://redax.ai/errors/job-not-found",
                title="Job not found",
                status=404,
                detail="No matching job was found",
            )
        REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
        return {
            "id": record.id,
            "status": record.status,
            "result": record.result,
            "error": JOB_FAILED if record.status == "failed" else None,
        }

    @router.delete("/v1/jobs/{job_id}", response_model=None)
    async def cancel_job(
        job_id: str,
        request: Request,
        state: Annotated[State, Depends(get_state)],
        api_key: Annotated[str, Depends(require_scope("jobs"))],
    ) -> dict[str, Any] | JSONResponse:
        """Cancel queued work; running jobs remain owned by the worker."""
        endpoint = "DELETE /v1/jobs/{id}"
        method = "DELETE"
        store: JobStore | None = state.job_store
        if not store_available(store):
            REQUESTS.labels(endpoint=endpoint, method=method, status="503").inc()
            return job_store_unavailable(request, "durable job store unavailable")
        assert store is not None
        try:
            record = await store.get(job_id)
            if record is None or record.owner != store.owner_token(api_key):
                REQUESTS.labels(endpoint=endpoint, method=method, status="404").inc()
                return problem_response(
                    request,
                    type="https://redax.ai/errors/job-not-found",
                    title="Job not found",
                    status=404,
                    detail="No matching job was found",
                )
            if record.status == "cancelled":
                REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
                return {"id": record.id, "status": record.status}
            if record.status != "queued":
                REQUESTS.labels(endpoint=endpoint, method=method, status="409").inc()
                return problem_response(
                    request,
                    type="https://redax.ai/errors/job-not-cancellable",
                    title="Job cannot be cancelled",
                    status=409,
                    detail="Only queued jobs can be cancelled; running or terminal jobs are immutable.",
                )
            cancel = getattr(store, "cancel", None)
            if cancel is None or not await cancel(job_id):
                current = await store.get(job_id)
                if current is not None and current.status == "cancelled":
                    REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
                    return {"id": current.id, "status": current.status}
                REQUESTS.labels(endpoint=endpoint, method=method, status="409").inc()
                return problem_response(
                    request,
                    type="https://redax.ai/errors/job-not-cancellable",
                    title="Job cannot be cancelled",
                    status=409,
                    detail="The job was claimed before cancellation completed.",
                )
            decrement_queue_depth()
            REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
            return {"id": job_id, "status": "cancelled"}
        except TRANSIENT_EXC as exc:
            ERRORS.labels(type="job_cancel_failed").inc()
            get_logger("redax.api").error("redax.job_cancel_failed", error=exc.__class__.__name__)
            REQUESTS.labels(endpoint=endpoint, method=method, status="503").inc()
            return job_store_unavailable(request, "durable job queue unavailable")

    app.include_router(router)


async def run_job(
    job_id: str,
    payload: dict[str, Any],
    store: JobStore,
    request_id: str,
    state: State,
    principal_identifier: str = "",
    *,
    mark_failure: bool = True,
) -> bool:
    """Execute one durable job attempt and return whether it succeeded.

    The state is passed explicitly because the worker runs independently of
    the originating request; there is no live request to read from.
    """
    logger = get_logger("redax.jobs")
    try:
        claim = getattr(store, "claim", None)
        claimed = await claim(job_id) if claim is not None else True
        if claim is None:
            await store.set_status(job_id, "running")
        if not claimed:
            existing = await store.get(job_id)
            return existing is not None and existing.status in {
                "running",
                "done",
                "failed",
                "cancelled",
            }
    except (OSError, RedisError, TimeoutError, RuntimeError) as exc:
        ERRORS.labels(type="job_store_unavailable").inc()
        logger.error("redax.job_store_unavailable", job_id=job_id, error=exc.__class__.__name__)
        return False
    start = time.perf_counter()
    redactor = state.redactor
    if redactor is None:
        ERRORS.labels(type="job_redactor_unavailable").inc()
        if mark_failure:
            await record_failure(job_id, store, logger)
        logger.error("redax.job_failed", job_id=job_id, error="redactor not initialized")
        return False
    try:
        timeout_seconds = getattr(state.settings, "request_timeout_seconds", 30.0)
        async with asyncio.timeout(timeout_seconds):
            policy = payload.get("policy")
            entity_types = payload.get("entity_types")
            if policy is None and entity_types is None:
                policy = default_policy(state.settings)
            result = await redactor.redact(
                payload["text"],
                policy=policy,
                entity_types=entity_types,
            )
        inference_ms = int((time.perf_counter() - start) * 1000)
        audit = state.audit
        if audit is not None:
            from app.observability.tracing import current_trace_id_hex

            await audit.record(
                Event(
                    request_id=request_id,
                    principal_id=principal_identifier,
                    ts="",
                    policy_version=policy_version(policy),
                    text_chars=len(payload["text"]),
                    entities_detected=span_summary(result.spans),
                    inference_ms=inference_ms,
                    trace_id=current_trace_id_hex() or "",
                )
            )
        terminalized = await store.set_result(
            job_id,
            {
                "text": result.text,
                "spans": [s.__dict__ for s in result.spans],
                # Re-identification maps contain original values and must not
                # be persisted in or returned from the job API.
                "relex_map": {},
                "inference_ms": inference_ms,
            },
        )
        if terminalized is not False:
            decrement_queue_depth()
    except TimeoutError:
        logger.error("redax.job_timeout", job_id=job_id)
        ERRORS.labels(type="job_timeout").inc()
        if mark_failure:
            await record_failure(job_id, store, logger)
        return False
    except TRANSIENT_EXC as exc:
        logger.error("redax.job_failed", job_id=job_id, error=exc.__class__.__name__)
        ERRORS.labels(type="job_failed").inc()
        if mark_failure:
            await record_failure(job_id, store, logger)
        return False
    finally:
        JOB_DURATION.observe(time.perf_counter() - start)
    return True


async def record_failure(job_id: str, store: JobStore, logger: Any, *, attempts: int = 1) -> None:
    """Mark a job as failed in the JobStore; logs and counts write failures."""
    try:
        terminalized = await store.set_error(job_id, JOB_FAILED)
        if terminalized is not False:
            decrement_queue_depth()
        try:
            await store.record_dead_letter(job_id, JOB_FAILED, attempts)
        except (OSError, RedisError, TimeoutError, RuntimeError):
            logger.error("redax.job_dead_letter_write_failed", job_id=job_id)
            ERRORS.labels(type="job_dead_letter_write_failed").inc()
    except (OSError, RedisError, TimeoutError, RuntimeError):
        logger.error("redax.job_store_write_failed", job_id=job_id)
        ERRORS.labels(type="job_store_write_failed").inc()
