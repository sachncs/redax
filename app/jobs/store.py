"""Redis-backed job lifecycle + result store for ``/v1/jobs``.

The store is shared across the ``/v1/jobs`` submission, ``/v1/jobs/{id}``
poll, and background-task worker. Records are kept as Redis hashes with a
configurable TTL; the per-key in-flight counter is incremented on submit
and decremented on terminal transitions.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from typing import Any

import redis.asyncio as aioredis


@dataclass
class JobRecord:
    """A single job's lifecycle state plus its current result or error.

    Attributes:
        id: Server-assigned 32-char hex identifier.
        status: One of ``queued``, ``running``, ``done``, ``failed``.
        result: The serialized redaction output on success; ``None`` while
            the job is still queued or running.
        error: Human-readable failure reason; ``None`` unless ``status``
            is ``failed``.
        owner: The API key that submitted the job; used for per-key
            admission control.
    """

    id: str
    status: str  # queued | running | done | failed
    result: dict[str, Any] | None
    error: str | None
    owner: str = ""


class JobStore:
    """Async Redis-backed store for background redaction jobs.

    Each job records its API-key owner so admission can be capped per key.
    The terminal transitions (set_result / set_error) release the owner's
    slot automatically.

    Attributes:
        url: Redis URL used when ``client`` is not injected.
        ttl_seconds: Time-to-live for both the per-job hash and the
            per-owner counter.
        client: Underlying ``redis.asyncio.Redis`` instance; populated by
            ``start`` if not supplied at construction.
    """

    KEY = "redax:job:{id}"
    COUNT_KEY = "redax:jobs:{owner}"

    def __init__(
        self,
        redis_url: str,
        ttl_seconds: int = 86_400,
        client: aioredis.Redis | None = None,
    ) -> None:
        self.url = redis_url
        self.ttl_seconds = ttl_seconds
        self.client = client

    async def start(self) -> None:
        if self.client is None:
            self.client = aioredis.from_url(  # type: ignore[no-untyped-call]
                self.url, decode_responses=True
            )
            await self.client.ping()

    async def stop(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    async def create(self, owner: str = "") -> JobRecord:
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before create()")
        job_id = uuid.uuid4().hex
        record = JobRecord(id=job_id, status="queued", result=None, error=None, owner=owner)
        await self.set_record(record)
        if owner:
            count_key = self.COUNT_KEY.format(owner=owner)
            await client.incr(count_key)
            await client.expire(count_key, self.ttl_seconds)
        return record

    async def count_for_key(self, owner: str) -> int:
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before count_for_key()")
        raw = await client.get(self.COUNT_KEY.format(owner=owner))
        return int(raw) if raw else 0

    async def get(self, job_id: str) -> JobRecord | None:
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before get()")
        raw = await client.hgetall(self.KEY.format(id=job_id))  # type: ignore[misc]
        if not raw:
            return None
        result_raw = raw.get("result")
        error_raw = raw.get("error")
        return JobRecord(
            id=raw["id"],
            status=raw["status"],
            result=json.loads(result_raw) if result_raw else None,
            error=error_raw if error_raw else None,
            owner=raw.get("owner", ""),
        )

    async def set_status(self, job_id: str, status: str) -> None:
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before set_status()")
        await client.hset(self.KEY.format(id=job_id), "status", status)  # type: ignore[misc]
        await client.expire(self.KEY.format(id=job_id), self.ttl_seconds)

    async def set_result(self, job_id: str, result: dict[str, Any]) -> None:
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before set_result()")
        key = self.KEY.format(id=job_id)
        await client.hset(key, "result", json.dumps(result))  # type: ignore[misc]
        await client.hset(key, "status", "done")  # type: ignore[misc]
        await client.expire(key, self.ttl_seconds)
        await release_owner_count(client, key)

    async def set_error(self, job_id: str, error: str) -> None:
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before set_error()")
        key = self.KEY.format(id=job_id)
        await client.hset(key, "error", error)  # type: ignore[misc]
        await client.hset(key, "status", "failed")  # type: ignore[misc]
        await client.expire(key, self.ttl_seconds)
        await release_owner_count(client, key)

    async def set_record(self, record: JobRecord) -> None:
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before set_record()")
        result_value = json.dumps(record.result) if record.result is not None else ""
        await client.hset(  # type: ignore[misc]
            self.KEY.format(id=record.id),
            mapping={
                "id": record.id,
                "status": record.status,
                "result": result_value,
                "error": record.error or "",
                "owner": record.owner,
            },
        )
        await client.expire(self.KEY.format(id=record.id), self.ttl_seconds)


async def release_owner_count(client: aioredis.Redis, job_key: str) -> None:
    """Reclaim the job's per-key admission slot when it reaches a terminal state."""
    owner = await client.hget(job_key, "owner")  # type: ignore[misc]
    if not owner:
        return
    count_key = JobStore.COUNT_KEY.format(owner=owner)
    raw = await client.get(count_key)
    if raw is None:
        return
    if int(raw) <= 1:
        await client.delete(count_key)
    else:
        await client.decr(count_key, 1)


def build_default_store(redis_url: str | None = None) -> JobStore:
    return JobStore(redis_url or os.environ.get("REDAX_REDIS_URL", "redis://localhost:6379/0"))
