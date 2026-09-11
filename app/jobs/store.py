"""Redis-backed job lifecycle + result store for ``/v1/jobs``.

The store is shared across the ``/v1/jobs`` submission, ``/v1/jobs/{id}``
poll, and background-task worker. Records are kept as Redis hashes with a
configurable TTL; the per-key in-flight counter is incremented on submit
and decremented on terminal transitions.
"""

from __future__ import annotations

import json
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

    KEY_TEMPLATE = "{ns}:job:{id}"
    COUNT_KEY_TEMPLATE = "{ns}:jobs:{owner}"

    def __init__(
        self,
        redis_url: str,
        ttl_seconds: int = 86_400,
        client: aioredis.Redis | None = None,
        namespace: str = "redax",
    ) -> None:
        self.url = redis_url
        self.ttl_seconds = ttl_seconds
        self.client = client
        self.namespace = namespace

    def _key(self, job_id: str) -> str:
        return self.KEY_TEMPLATE.format(ns=self.namespace, id=job_id)

    def _count_key(self, owner: str) -> str:
        return self.COUNT_KEY_TEMPLATE.format(ns=self.namespace, owner=owner)

    async def start(self) -> None:
        """Connect to Redis and verify the link with a ping.

        Builds the async client from ``self.url`` only if one was not
        injected via the constructor (the latter path is used by tests).
        """
        if self.client is None:
            self.client = aioredis.from_url(  # type: ignore[no-untyped-call]
                self.url, decode_responses=True
            )
            await self.client.ping()

    async def stop(self) -> None:
        """Close the Redis client; safe to call when already stopped."""
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    async def create(self, owner: str = "") -> JobRecord:
        """Mint a new job id, store the queued record, and bump the per-owner counter.

        Args:
            owner: The API key (or empty string for an unauthenticated
                job) that will own this job's admission slot.

        Returns:
            The new :class:`JobRecord` in ``"queued"`` status.
        """
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before create()")
        job_id = uuid.uuid4().hex
        record = JobRecord(id=job_id, status="queued", result=None, error=None, owner=owner)
        await self.set_record(record)
        if owner:
            count_key = self._count_key(owner)
            await client.incr(count_key)
            await client.expire(count_key, self.ttl_seconds)
        return record

    async def count_for_key(self, owner: str) -> int:
        """Return the number of in-flight jobs for ``owner``; 0 if the counter is missing."""
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before count_for_key()")
        raw = await client.get(self._count_key(owner))
        return int(raw) if raw else 0

    async def get(self, job_id: str) -> JobRecord | None:
        """Return the :class:`JobRecord` for ``job_id`` or ``None`` if absent.

        Empty ``result`` / ``error`` fields stored on disk are mapped
        back to ``None`` so callers can rely on ``is None`` checks.
        """
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before get()")
        raw = await client.hgetall(self._key(job_id))  # type: ignore[misc]
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
        """Set the ``status`` field on the job hash and refresh the TTL."""
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before set_status()")
        key = self._key(job_id)
        await client.hset(key, "status", status)  # type: ignore[misc]
        await client.expire(key, self.ttl_seconds)

    async def set_result(self, job_id: str, result: dict[str, Any]) -> None:
        """Mark the job as ``done``, store its result, and release the per-key slot."""
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before set_result()")
        key = self._key(job_id)
        await client.hset(key, "result", json.dumps(result))  # type: ignore[misc]
        await client.hset(key, "status", "done")  # type: ignore[misc]
        await client.expire(key, self.ttl_seconds)
        await release_owner_count(client, key, self.namespace)

    async def set_error(self, job_id: str, error: str) -> None:
        """Mark the job as ``failed``, record the error, and release the per-key slot."""
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before set_error()")
        key = self._key(job_id)
        await client.hset(key, "error", error)  # type: ignore[misc]
        await client.hset(key, "status", "failed")  # type: ignore[misc]
        await client.expire(key, self.ttl_seconds)
        await release_owner_count(client, key, self.namespace)

    async def set_record(self, record: JobRecord) -> None:
        """Write the full :class:`JobRecord` fields into the job hash.

        ``None`` ``result`` is stored as the empty string; any other
        value is JSON-encoded normally. The job's TTL is refreshed.
        """
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before set_record()")
        result_value = json.dumps(record.result) if record.result is not None else ""
        key = self._key(record.id)
        await client.hset(  # type: ignore[misc]
            key,
            mapping={
                "id": record.id,
                "status": record.status,
                "result": result_value,
                "error": record.error or "",
                "owner": record.owner,
            },
        )
        await client.expire(key, self.ttl_seconds)


async def release_owner_count(
    client: aioredis.Redis, job_key: str, namespace: str = "redax"
) -> None:
    """Decrement (or delete) the per-owner counter when a job reaches a terminal state."""
    owner = await client.hget(job_key, "owner")  # type: ignore[misc]
    if not owner:
        return
    count_key = JobStore.COUNT_KEY_TEMPLATE.format(ns=namespace, owner=owner)
    raw = await client.get(count_key)
    if raw is None:
        return
    if int(raw) <= 1:
        await client.delete(count_key)
    else:
        await client.decr(count_key, 1)
