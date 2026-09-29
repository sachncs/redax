"""Durable ARQ worker entrypoint for asynchronous redaction jobs."""

from __future__ import annotations

import asyncio
import contextlib
import os
import random
import uuid
from typing import Any

from arq import Retry
from arq.connections import RedisSettings
from arq.worker import Worker
from redis.exceptions import RedisError

from app.api.jobs import record_failure, run_job
from app.config import Settings
from app.jobs.payload import JobPayloadCipher
from app.logging import configure_logging, get_logger
from app.main import build_state, teardown_state
from app.observability import JOB_PERMANENT_FAILURES, JOB_RETRIES

QUEUE_NAME = "redax:jobs"
FUNCTION_NAME = "process_job"
MAX_TRIES = 5


def worker_redis_settings(settings: Any) -> RedisSettings:
    """Build bounded ARQ Redis settings without duplicating parsed fields."""
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    redis_settings.conn_timeout = max(1, int(settings.redis_connect_timeout_seconds))
    redis_settings.max_connections = settings.redis_max_connections
    redis_settings.retry_on_timeout = True
    return redis_settings


def shutdown_wait_seconds(settings: Any) -> int:
    """Return the bounded ARQ signal-drain window from validated settings."""
    return max(1, int(getattr(settings, "shutdown_timeout_seconds", 30.0)))


async def run_worker(worker: Worker) -> None:
    """Run an ARQ worker until normal exit or signal-driven cancellation."""
    # ARQ cancels its main task after the configured active-job completion
    # window. That is an expected lifecycle event, not an application error.
    with contextlib.suppress(asyncio.CancelledError):
        await worker.async_run()


async def process_job(
    ctx: dict[str, Any],
    job_id: str,
    payload: dict[str, Any],
    request_id: str,
    principal_identifier: str = "",
) -> None:
    """Run one job attempt and ask ARQ to retry transient failures."""
    state = ctx["state"]
    ctx["active_jobs"] = int(ctx.get("active_jobs", 0)) + 1
    try:
        try:
            payload = JobPayloadCipher(
                getattr(getattr(state, "settings", None), "job_payload_encryption_key", "")
            ).decode(payload)
        except ValueError as exc:
            JOB_PERMANENT_FAILURES.inc()
            get_logger("redax.jobs").error(
                "redax.job_payload_rejected", error=exc.__class__.__name__
            )
            await record_failure(
                job_id,
                state.job_store,
                get_logger("redax.jobs"),
                attempts=int(ctx.get("job_try", 1)),
            )
            return
        success = await run_job(
            job_id,
            payload,
            state.job_store,
            request_id,
            state,
            principal_identifier,
            mark_failure=False,
        )
        if success:
            return
        if int(ctx.get("job_try", 1)) < MAX_TRIES:
            attempt = int(ctx.get("job_try", 1))
            base_delay = 2 ** max(0, attempt - 1)
            settings = getattr(state, "settings", None)
            jitter_limit = float(getattr(settings, "job_retry_jitter_seconds", 0.0))
            delay = min(60, base_delay + random.uniform(0.0, jitter_limit))
            JOB_RETRIES.inc()
            raise Retry(defer=delay)
        JOB_PERMANENT_FAILURES.inc()
        await record_failure(
            job_id,
            state.job_store,
            get_logger("redax.jobs"),
            attempts=int(ctx.get("job_try", MAX_TRIES)),
        )
    finally:
        ctx["active_jobs"] = max(0, int(ctx.get("active_jobs", 1)) - 1)


async def worker_heartbeat(ctx: dict[str, Any], worker_id: str, max_jobs: int) -> None:
    """Refresh the worker's short-lived liveness key until cancellation."""
    state = ctx["state"]
    store = state.job_store
    while True:
        try:
            await store.worker_heartbeat(worker_id, int(ctx.get("active_jobs", 0)), max_jobs)
        except (OSError, RedisError, RuntimeError, TimeoutError, ValueError) as exc:
            get_logger("redax.jobs").warning(
                "redax.worker_heartbeat_failed", error=exc.__class__.__name__
            )
        await asyncio.sleep(5.0)


async def worker_main() -> None:
    """Build an isolated worker state and run until SIGTERM/SIGINT."""
    settings = Settings()
    settings.verify()
    configure_logging(settings.log_level)
    state = await build_state(settings)
    if state.job_store is None:
        raise RuntimeError("Redis is required for the durable Redax worker")
    ctx: dict[str, Any] = {"state": state, "active_jobs": 0}
    worker = Worker(
        functions=[process_job],
        queue_name=QUEUE_NAME,
        redis_settings=worker_redis_settings(settings),
        ctx=ctx,
        max_jobs=settings.worker_concurrency,
        max_tries=MAX_TRIES,
        job_timeout=settings.request_timeout_seconds,
        job_completion_wait=shutdown_wait_seconds(settings),
        retry_jobs=True,
    )
    worker_id = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    ctx["worker_id"] = worker_id
    heartbeat_task = asyncio.create_task(
        worker_heartbeat(ctx, worker_id, settings.worker_concurrency)
    )
    try:
        await run_worker(worker)
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
        with contextlib.suppress(OSError, RuntimeError, TimeoutError, asyncio.CancelledError):
            await worker.close()
        with contextlib.suppress(OSError, RuntimeError, TimeoutError, ValueError):
            await state.job_store.worker_stop(worker_id)
        await teardown_state(state)


def run() -> None:
    """Console entrypoint for ``redax-worker``."""
    asyncio.run(worker_main())
