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
        async for key in client.scan_iter(match=f"{store.namespace}:*"):
            await client.delete(key)
        await client.aclose()


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
