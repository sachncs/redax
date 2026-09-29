from __future__ import annotations

import asyncio
import multiprocessing
import os
import shutil
import socket
import subprocess
import tempfile
import uuid

import pytest
import redis.asyncio as aioredis
from arq import create_pool
from arq.connections import RedisSettings
from arq.constants import in_progress_key_prefix
from arq.worker import Worker, func

from app.audit.backend import Event
from app.audit.redis import RedisAudit
from app.jobs.store import JobStore


def free_tcp_port() -> int:
    """Reserve a currently unused local TCP port for the restart drill."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_ephemeral_redis(port: int, directory: str) -> subprocess.Popen[bytes]:
    """Start a disposable Redis instance with persistence enabled."""
    return subprocess.Popen(
        [
            "redis-server",
            "--bind",
            "127.0.0.1",
            "--port",
            str(port),
            "--dir",
            directory,
            "--appendonly",
            "yes",
            "--save",
            "",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def wait_for_redis(client: aioredis.Redis) -> None:
    """Wait briefly for a disposable Redis process to accept connections."""
    deadline = asyncio.get_running_loop().time() + 5
    while True:
        try:
            await client.ping()
            return
        except (OSError, aioredis.RedisError):
            if asyncio.get_running_loop().time() >= deadline:
                raise
            await asyncio.sleep(0.05)


async def crashable_recovery_job(ctx: dict[str, object], marker_key: str) -> str:
    """Sleep on the first delivery so the parent can simulate a worker kill."""
    client = ctx["pool"]
    assert isinstance(client, aioredis.Redis)
    started_key = f"{marker_key}:started"
    if not await client.get(started_key):
        await client.set(started_key, "1", ex=60)
        await asyncio.sleep(60)
    await client.set(f"{marker_key}:done", "1", ex=60)
    return "done"


async def run_crashable_worker(redis_url: str, queue_name: str) -> None:
    pool = await create_pool(RedisSettings.from_dsn(redis_url), default_queue_name=queue_name)
    worker = Worker(
        [func(crashable_recovery_job, name="crashable_recovery_job")],
        redis_pool=pool,
        queue_name=queue_name,
        handle_signals=False,
        poll_delay=0.01,
        max_tries=5,
        ctx={"pool": pool},
    )
    worker.in_progress_timeout_s = 0.2
    try:
        await worker.async_run()
    finally:
        await pool.aclose()


def run_crashable_worker_process(redis_url: str, queue_name: str) -> None:
    asyncio.run(run_crashable_worker(redis_url, queue_name))


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
    assert await real_job_store.oldest_job_age_seconds() >= 0

    await asyncio.gather(
        *(real_job_store.set_error(record.id, "job failed") for record in admitted)
    )
    assert await real_job_store.count_inflight() == 0
    assert await real_job_store.count_for_key("tenant-a") == 0
    assert await real_job_store.oldest_job_age_seconds() == 0.0

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
async def test_real_redis_job_claim_allows_one_duplicate_delivery(
    real_job_store: JobStore,
) -> None:
    record = await real_job_store.create(owner="tenant-a")
    claims = await asyncio.gather(*(real_job_store.claim(record.id) for _ in range(12)))
    assert sum(claims) == 1
    stored = await real_job_store.get(record.id)
    assert stored is not None
    assert stored.status == "running"


@pytest.mark.asyncio
async def test_real_redis_pii_canary_is_absent_from_job_and_audit_values(
    real_job_store: JobStore,
) -> None:
    canary = "redis.canary.7f8d@example.com"
    audit = RedisAudit(real_job_store.client, namespace=real_job_store.namespace, required=True)
    await audit.start()
    record = await real_job_store.create(owner=canary)
    await real_job_store.set_result(record.id, {"text": "Email [REDACTED]"})
    await audit.record(
        Event(
            request_id="redis-canary",
            ts="",
            policy_version="default-1.0.0",
            text_chars=len(canary),
            principal_id="principal-canary",
            entities_detected=[{"type": "EMAIL", "count": 1, "confidence_avg": 1.0}],
        )
    )

    client = real_job_store.client
    assert client is not None
    persisted: list[object] = []
    async for key in client.scan_iter(match=f"{real_job_store.namespace}:*"):
        kind = await client.type(key)
        if kind == "hash":
            persisted.append(await client.hgetall(key))
        elif kind == "list":
            persisted.append(await client.lrange(key, 0, -1))
        else:
            persisted.append(await client.get(key))
    assert canary not in repr(persisted)


@pytest.mark.asyncio
async def test_real_redis_client_recovers_after_connection_close(
    real_job_store: JobStore,
) -> None:
    client = real_job_store.client
    assert client is not None
    await client.aclose()
    assert await real_job_store.count_inflight() == 0


@pytest.mark.asyncio
async def test_redis_client_recovers_after_server_restart() -> None:
    if shutil.which("redis-server") is None:
        pytest.skip("redis-server is unavailable for the restart drill")
    port = free_tcp_port()
    with tempfile.TemporaryDirectory() as directory:
        process = start_ephemeral_redis(port, directory)
        client = aioredis.from_url(
            f"redis://127.0.0.1:{port}/15",
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
            retry_on_timeout=True,
            health_check_interval=0.1,
        )
        try:
            await wait_for_redis(client)
            await client.set("redax:restart-drill", "before", ex=60)
            process.terminate()
            process.wait(timeout=5)
            process = start_ephemeral_redis(port, directory)
            await wait_for_redis(client)
            assert await client.get("redax:restart-drill") == "before"
        finally:
            await client.aclose()
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


@pytest.mark.asyncio
async def test_real_redis_worker_claims_job_after_expired_lease(
    real_job_store: JobStore,
) -> None:
    queue_name = f"redax-test-queue-{uuid.uuid4().hex[:12]}"
    job_id = uuid.uuid4().hex
    pool = await create_pool(
        RedisSettings.from_dsn(real_job_store.url), default_queue_name=queue_name
    )
    completed = asyncio.Event()

    async def recover_job(ctx: dict[str, object], value: str) -> str:
        del ctx
        completed.set()
        return value

    try:
        job = await pool.enqueue_job("recover_job", "safe", _job_id=job_id, _queue_name=queue_name)
        assert job is not None
        await pool.psetex(in_progress_key_prefix + job_id, 100, b"1")
        await asyncio.sleep(0.15)

        worker = Worker(
            [func(recover_job, name="recover_job")],
            redis_pool=pool,
            queue_name=queue_name,
            burst=True,
            handle_signals=False,
            poll_delay=0.01,
            max_tries=5,
            ctx={"pool": pool},
        )
        await asyncio.wait_for(worker.async_run(), timeout=3)
        assert completed.is_set()
    finally:
        await pool.delete(
            f"{queue_name}",
            f"arq:job:{job_id}",
            f"arq:retry:{job_id}",
            f"arq:result:{job_id}",
            in_progress_key_prefix + job_id,
        )
        await pool.aclose()


@pytest.mark.asyncio
async def test_real_redis_job_recovers_after_worker_process_kill(
    real_job_store: JobStore,
) -> None:
    queue_name = f"redax-kill-queue-{uuid.uuid4().hex[:12]}"
    job_id = uuid.uuid4().hex
    marker_key = f"redax-kill-marker-{uuid.uuid4().hex[:12]}"
    pool = await create_pool(
        RedisSettings.from_dsn(real_job_store.url), default_queue_name=queue_name
    )
    try:
        job = await pool.enqueue_job(
            "crashable_recovery_job",
            marker_key,
            _job_id=job_id,
            _queue_name=queue_name,
        )
        assert job is not None
        context = multiprocessing.get_context("spawn")
        process = context.Process(
            target=run_crashable_worker_process,
            args=(real_job_store.url, queue_name),
        )
        process.start()
        try:
            for _ in range(100):
                if await pool.get(f"{marker_key}:started"):
                    break
                await asyncio.sleep(0.02)
            else:
                pytest.fail("worker did not claim the job before the kill")
        finally:
            process.kill()
            process.join(timeout=3)
        assert not process.is_alive()

        replacement = Worker(
            [func(crashable_recovery_job, name="crashable_recovery_job")],
            redis_pool=pool,
            queue_name=queue_name,
            burst=True,
            handle_signals=False,
            poll_delay=0.01,
            max_tries=5,
            ctx={"pool": pool},
        )
        replacement.in_progress_timeout_s = 0.2
        await asyncio.wait_for(replacement.async_run(), timeout=3)
        assert await pool.get(f"{marker_key}:done")
    finally:
        await pool.delete(
            queue_name,
            f"arq:job:{job_id}",
            f"arq:retry:{job_id}",
            f"arq:result:{job_id}",
            f"arq:in-progress:{job_id}",
            f"{marker_key}:started",
            f"{marker_key}:done",
        )
        await pool.aclose()


@pytest.mark.asyncio
async def test_redis_rdb_backup_restores_into_fresh_instance() -> None:
    """Prove a Redis RDB snapshot can restore durable job state elsewhere."""
    if shutil.which("redis-server") is None:
        pytest.skip("redis-server is unavailable for the restore drill")
    source_port = free_tcp_port()
    restore_port = free_tcp_port()
    with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as restore_dir:
        source = subprocess.Popen(
            [
                "redis-server",
                "--bind",
                "127.0.0.1",
                "--port",
                str(source_port),
                "--dir",
                source_dir,
                "--save",
                "60",
                "1",
                "--appendonly",
                "no",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        source_client = aioredis.from_url(
            f"redis://127.0.0.1:{source_port}/15", decode_responses=True
        )
        restored_client = aioredis.from_url(
            f"redis://127.0.0.1:{restore_port}/15", decode_responses=True
        )
        restore_process: subprocess.Popen[bytes] | None = None
        try:
            await wait_for_redis(source_client)
            await source_client.set("redax:restore-drill", "durable", ex=60)
            await source_client.save()
            source.terminate()
            source.wait(timeout=5)
            shutil.copy2(f"{source_dir}/dump.rdb", f"{restore_dir}/dump.rdb")
            restore_process = subprocess.Popen(
                [
                    "redis-server",
                    "--bind",
                    "127.0.0.1",
                    "--port",
                    str(restore_port),
                    "--dir",
                    restore_dir,
                    "--save",
                    "",
                    "--appendonly",
                    "no",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            await wait_for_redis(restored_client)
            assert await restored_client.get("redax:restore-drill") == "durable"
        finally:
            await source_client.aclose()
            await restored_client.aclose()
            if source.poll() is None:
                source.terminate()
                source.wait(timeout=5)
            if restore_process is not None and restore_process.poll() is None:
                restore_process.terminate()
                restore_process.wait(timeout=5)
