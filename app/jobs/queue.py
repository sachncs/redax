"""Durable ARQ worker entrypoint for asynchronous redaction jobs."""

from __future__ import annotations

import asyncio
from typing import Any

from arq import Retry
from arq.connections import RedisSettings
from arq.worker import Worker

from app.api.jobs import record_failure, run_job
from app.config import Settings
from app.logging import configure_logging, get_logger
from app.main import build_state, teardown_state
from app.observability import JOB_PERMANENT_FAILURES, JOB_RETRIES

QUEUE_NAME = "redax:jobs"
FUNCTION_NAME = "process_job"
MAX_TRIES = 5


async def process_job(
    ctx: dict[str, Any], job_id: str, payload: dict[str, Any], request_id: str
) -> None:
    """Run one job attempt and ask ARQ to retry transient failures."""
    state = ctx["state"]
    success = await run_job(job_id, payload, state.job_store, request_id, state, mark_failure=False)
    if success:
        return
    if int(ctx.get("job_try", 1)) < MAX_TRIES:
        delay = min(60, 2 ** max(0, int(ctx.get("job_try", 1)) - 1))
        JOB_RETRIES.inc()
        raise Retry(defer=delay)
    JOB_PERMANENT_FAILURES.inc()
    await record_failure(job_id, state.job_store, get_logger("redax.jobs"))


async def worker_main() -> None:
    """Build an isolated worker state and run until SIGTERM/SIGINT."""
    settings = Settings()
    settings.verify()
    configure_logging(settings.log_level)
    state = await build_state(settings)
    if state.job_store is None:
        raise RuntimeError("Redis is required for the durable Redax worker")
    worker = Worker(
        functions=[process_job],
        queue_name=QUEUE_NAME,
        redis_settings=RedisSettings(
            **RedisSettings.from_dsn(settings.redis_url).__dict__,
            conn_timeout=max(1, int(settings.redis_connect_timeout_seconds)),
            max_connections=settings.redis_max_connections,
            retry_on_timeout=True,
        ),
        ctx={"state": state},
        max_jobs=settings.worker_concurrency,
        max_tries=MAX_TRIES,
        job_timeout=settings.request_timeout_seconds,
        retry_jobs=True,
    )
    try:
        await worker.async_run()
    finally:
        await teardown_state(state)


def run() -> None:
    """Console entrypoint for ``redax-worker``."""
    asyncio.run(worker_main())
