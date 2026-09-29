from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress

import httpx
import pytest
import redis.asyncio as aioredis
from cryptography.fernet import Fernet


def free_tcp_port() -> int:
    """Return a currently unused loopback port for a disposable API process."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_api_process(port: int, env: dict[str, str]) -> subprocess.Popen[str]:
    """Start one production-configured API replica without shell interpolation."""
    child_env = {**os.environ, **env, "REDAX_PORT": str(port)}
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


async def wait_until_ready(process: subprocess.Popen[str], port: int) -> None:
    """Wait for one replica to pass its real readiness probe."""
    url = f"http://127.0.0.1:{port}/readyz"
    async with httpx.AsyncClient(timeout=0.5) as client:
        for _ in range(120):
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout is not None else ""
                raise AssertionError(f"API replica exited during startup: {output[-2000:]}")
            try:
                if (await client.get(url)).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.1)
    raise AssertionError(f"API replica did not become ready on port {port}")


async def wait_for_redis(client: aioredis.Redis) -> None:
    """Wait briefly for a disposable Redis process to accept connections."""
    for _ in range(100):
        try:
            await client.ping()
            return
        except (OSError, aioredis.RedisError):
            await asyncio.sleep(0.05)
    await client.ping()


async def stop_api_process(process: subprocess.Popen[str]) -> None:
    """Stop a disposable API process and avoid leaving a child behind."""
    if process.poll() is None:
        process.terminate()
        try:
            await asyncio.to_thread(process.wait, 5)
        except subprocess.TimeoutExpired:
            process.kill()
            await asyncio.to_thread(process.wait, 5)
    if process.stdout is not None:
        process.stdout.close()


@pytest.fixture
async def replica_redis() -> AsyncIterator[tuple[aioredis.Redis, str, str]]:
    """Yield a unique real-Redis namespace for the replica integration gate."""
    url = os.environ.get("REDAX_TEST_REDIS_URL", "redis://localhost:6379/15")
    client = aioredis.from_url(url, decode_responses=True)
    namespace = f"redax-replica-test-{uuid.uuid4().hex[:12]}"
    redis_process: subprocess.Popen[bytes] | None = None
    redis_directory: tempfile.TemporaryDirectory[str] | None = None
    try:
        try:
            await client.ping()
        except (OSError, aioredis.RedisError):
            await client.aclose()
            if shutil.which("redis-server") is None:
                pytest.skip("real Redis is unavailable and redis-server is not installed")
            redis_directory = tempfile.TemporaryDirectory()
            port = free_tcp_port()
            redis_process = subprocess.Popen(
                [
                    "redis-server",
                    "--bind",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--dir",
                    redis_directory.name,
                    "--save",
                    "",
                    "--appendonly",
                    "no",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            url = f"redis://127.0.0.1:{port}/15"
            client = aioredis.from_url(url, decode_responses=True)
            await wait_for_redis(client)
    except (OSError, aioredis.RedisError) as exc:
        await client.aclose()
        pytest.skip(f"real Redis is unavailable: {exc.__class__.__name__}")
    try:
        yield client, namespace, url
    finally:
        async for key in client.scan_iter(match=f"{namespace}:*"):
            await client.delete(key)
        await client.aclose()
        if redis_process is not None and redis_process.poll() is None:
            redis_process.terminate()
            redis_process.wait(timeout=5)
        if redis_directory is not None:
            redis_directory.cleanup()


@pytest.mark.asyncio
async def test_two_api_replicas_share_idempotency_state(replica_redis) -> None:
    """Two API processes must replay and conflict through shared Redis state."""
    redis_client, namespace, redis_url = replica_redis
    del redis_client
    key = "replica-test-key"
    env = {
        "REDAX_ENV": "prod",
        "REDAX_DETECTOR": "regex",
        "REDAX_API_KEYS": key,
        "REDAX_HASH_SALT": "replica-test-hash-salt",
        "REDAX_TRUSTED_HOSTS": "127.0.0.1",
        "REDAX_REDIS_URL": redis_url,
        "REDAX_REDIS_NAMESPACE": namespace,
        "REDAX_REDIS_REQUIRED": "true",
        "REDAX_AUDIT_BACKEND": "redis",
        "REDAX_AUDIT_REQUIRED": "true",
        "REDAX_AUDIT_INTEGRITY_KEY": "replica-audit-integrity-key",
        "REDAX_AUDIT_REDIS_MAX_EVENTS": "1000",
        "REDAX_JOB_PAYLOAD_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "REDAX_RATE_LIMIT_PER_MINUTE": "0",
        "REDAX_PIPELINE_ENABLED": "false",
        "REDAX_LOG_LEVEL": "WARNING",
        "REDAX_SHUTDOWN_TIMEOUT_SECONDS": "3",
    }
    first_port = free_tcp_port()
    second_port = free_tcp_port()
    first = start_api_process(first_port, env)
    second = start_api_process(second_port, env)
    try:
        await asyncio.gather(
            wait_until_ready(first, first_port),
            wait_until_ready(second, second_port),
        )
        body = {"text": "Email replica.canary@example.com"}
        headers = {"X-API-Key": key, "Idempotency-Key": "shared-idempotency-key"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            first_response = await client.post(
                f"http://127.0.0.1:{first_port}/v1/redact", json=body, headers=headers
            )
            replay_response = await client.post(
                f"http://127.0.0.1:{second_port}/v1/redact", json=body, headers=headers
            )
            conflict_response = await client.post(
                f"http://127.0.0.1:{second_port}/v1/redact",
                json={"text": "Email different@example.com"},
                headers=headers,
            )

        assert first_response.status_code == 200
        assert replay_response.status_code == 200
        assert replay_response.json() == first_response.json()
        assert conflict_response.status_code == 409
    finally:
        await asyncio.gather(stop_api_process(first), stop_api_process(second))
        with suppress(Exception):
            await asyncio.to_thread(first.wait, 1)
