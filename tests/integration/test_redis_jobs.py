from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import redis.asyncio as aioredis

from app.jobs.store import JobStore


@pytest.fixture
async def real_job_store() -> JobStore:
    url = os.environ.get("REDAX_TEST_REDIS_URL", "redis://localhost:6379/15")
    client = aioredis.from_url(url, decode_responses=True)
    try:
        await client.ping()
    except (OSError, aioredis.RedisError) as exc:
        await client.aclose()
        pytest.skip(f"real Redis is unavailable: {exc.__class__.__name__}")
    store = JobStore(
        url,
        ttl_seconds=60,
        client=client,
        namespace=f"redax-test-{uuid.uuid4().hex[:12]}",
    )
    try:
        yield store
    finally:
        cleanup_client = store.client
        if cleanup_client is not None:
            async for key in cleanup_client.scan_iter(match=f"{store.namespace}:*"):
                await cleanup_client.delete(key)
            await cleanup_client.aclose()


@pytest.mark.asyncio
async def test_real_redis_admission_and_terminal_transitions_are_atomic(
    real_job_store: JobStore,
) -> None:
    attempts = await asyncio.gather(
        *(
            real_job_store.create_admitted("tenant-a", max_inflight=3, max_jobs_per_key=3)
            for _ in range(12)
        )
    )
    admitted = [record for record in attempts if record is not None]
    assert len(admitted) == 3
    assert await real_job_store.count_inflight() == 3

    await asyncio.gather(
        *(real_job_store.set_error(record.id, "job failed") for record in admitted)
    )
    assert await real_job_store.count_inflight() == 0
    assert await real_job_store.count_for_key("tenant-a") == 0

    # A duplicate terminal delivery must not decrement shared counters twice.
    await asyncio.gather(
        real_job_store.set_error(admitted[0].id, "duplicate failure"),
        real_job_store.set_result(admitted[0].id, {"text": "safe"}),
    )
    assert await real_job_store.count_inflight() == 0

    await real_job_store.record_dead_letter("job-dlq", "job failed", attempts=5)
    dead_letters = await real_job_store.client.lrange(
        f"{real_job_store.namespace}:jobs:dead-letter", 0, -1
    )
    assert len(dead_letters) == 1
    assert "job-dlq" in dead_letters[0]
    assert "payload" not in dead_letters[0]


@pytest.mark.asyncio
async def test_real_redis_client_recovers_after_connection_close(
    real_job_store: JobStore,
) -> None:
    client = real_job_store.client
    assert client is not None
    await client.aclose()
    assert await real_job_store.count_inflight() == 0
