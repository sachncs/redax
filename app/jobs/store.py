"""Redis-backed job lifecycle + result store for ``/v1/jobs``.

The store is shared across the ``/v1/jobs`` submission, ``/v1/jobs/{id}``
poll, and separate ARQ worker process. Records are kept as Redis hashes with a
configurable TTL; the per-key in-flight counter is incremented on submit
and decremented on terminal transitions.
"""

from __future__ import annotations

import hashlib
import json
import time
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
        owner: A one-way API-key token used for admission control and
            ownership checks. The clear API key is never persisted.
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
    TOTAL_COUNT_KEY_TEMPLATE = "{ns}:jobs:inflight"
    ADMIT_SCRIPT = """
local total = tonumber(redis.call('GET', KEYS[3]) or '0')
local owner = tonumber(redis.call('GET', KEYS[2]) or '0')
if total >= tonumber(ARGV[7]) then return 0 end
if ARGV[5] ~= '' and owner >= tonumber(ARGV[8]) then return 0 end
redis.call('HSET', KEYS[1], 'id', ARGV[1], 'status', ARGV[2], 'result', ARGV[3], 'error', ARGV[4], 'owner', ARGV[5], 'updated_at', ARGV[9])
redis.call('EXPIRE', KEYS[1], ARGV[6])
redis.call('INCR', KEYS[3])
redis.call('EXPIRE', KEYS[3], ARGV[6])
if ARGV[5] ~= '' then
  redis.call('INCR', KEYS[2])
  redis.call('EXPIRE', KEYS[2], ARGV[6])
end
return 1
"""
    TERMINAL_SCRIPT = """
local status = redis.call('HGET', KEYS[1], 'status')
if status ~= 'queued' and status ~= 'running' then return 0 end
redis.call('HSET', KEYS[1], 'status', ARGV[1], 'result', ARGV[2], 'error', ARGV[3], 'updated_at', ARGV[5])
redis.call('EXPIRE', KEYS[1], ARGV[4])
local owner = redis.call('HGET', KEYS[1], 'owner')
if owner ~= false and owner ~= '' then
  local owner_count = tonumber(redis.call('GET', KEYS[2]) or '0')
  if owner_count <= 1 then redis.call('DEL', KEYS[2]) else redis.call('DECR', KEYS[2]) end
end
local total = tonumber(redis.call('GET', KEYS[3]) or '0')
if total <= 1 then redis.call('DEL', KEYS[3]) else redis.call('DECR', KEYS[3]) end
return 1
"""

    def __init__(
        self,
        redis_url: str,
        ttl_seconds: int = 86_400,
        client: aioredis.Redis | None = None,
        namespace: str = "redax",
        connect_timeout_seconds: float = 1.0,
        socket_timeout_seconds: float = 1.0,
        max_connections: int = 64,
    ) -> None:
        self.url = redis_url
        self.ttl_seconds = ttl_seconds
        self.client = client
        self.namespace = namespace
        self.connect_timeout_seconds = connect_timeout_seconds
        self.socket_timeout_seconds = socket_timeout_seconds
        self.max_connections = max_connections

    def _key(self, job_id: str) -> str:
        return self.KEY_TEMPLATE.format(ns=self.namespace, id=job_id)

    def _count_key(self, owner: str) -> str:
        return self.COUNT_KEY_TEMPLATE.format(ns=self.namespace, owner=self.owner_token(owner))

    def _total_count_key(self) -> str:
        return self.TOTAL_COUNT_KEY_TEMPLATE.format(ns=self.namespace)

    @staticmethod
    def owner_token(owner: str) -> str:
        """Return the bounded, non-secret token used for job ownership state."""
        return hashlib.sha256(owner.encode("utf-8", errors="replace")).hexdigest()[:32]

    async def start(self) -> None:
        """Connect to Redis and verify the link with a ping.

        Builds the async client from ``self.url`` only if one was not
        injected via the constructor (the latter path is used by tests).
        """
        if self.client is None:
            self.client = aioredis.from_url(  # type: ignore[no-untyped-call]
                self.url,
                decode_responses=True,
                socket_connect_timeout=self.connect_timeout_seconds,
                socket_timeout=self.socket_timeout_seconds,
                max_connections=self.max_connections,
                health_check_interval=30,
                retry_on_timeout=True,
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
        record = JobRecord(
            id=job_id,
            status="queued",
            result=None,
            error=None,
            owner=self.owner_token(owner) if owner else "",
        )
        await self.set_record(record)
        if owner:
            count_key = self._count_key(owner)
            await client.incr(count_key)
            await client.expire(count_key, self.ttl_seconds)
        await client.incr(self._total_count_key())
        await client.expire(self._total_count_key(), self.ttl_seconds)
        return record

    async def create_admitted(
        self, owner: str, max_inflight: int, max_jobs_per_key: int
    ) -> JobRecord | None:
        """Atomically admit and persist a job, or return ``None`` when full."""
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before create_admitted()")
        job_id = uuid.uuid4().hex
        owner_token = self.owner_token(owner) if owner else ""
        result = await client.eval(  # type: ignore[misc]
            self.ADMIT_SCRIPT,
            3,
            self._key(job_id),
            self._count_key(owner),
            self._total_count_key(),
            job_id,
            "queued",
            "",
            "",
            owner_token,
            str(self.ttl_seconds),
            str(max_inflight),
            str(max_jobs_per_key),
            str(time.time()),
        )
        if int(result) != 1:
            return None
        return JobRecord(job_id, "queued", None, None, owner_token)

    async def count_for_key(self, owner: str) -> int:
        """Return the number of in-flight jobs for ``owner``; 0 if the counter is missing."""
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before count_for_key()")
        raw = await client.get(self._count_key(owner))
        return int(raw) if raw else 0

    async def count_inflight(self) -> int:
        """Return the shared Redis count of non-terminal jobs."""
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before count_inflight()")
        raw = await client.get(self._total_count_key())
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
        await client.hset(  # type: ignore[misc]
            key, mapping={"status": status, "updated_at": str(time.time())}
        )
        await client.expire(key, self.ttl_seconds)

    async def reap_stale_jobs(self, max_age_seconds: int) -> int:
        """Fail queued/running jobs older than the recovery lease threshold."""
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before reap_stale_jobs()")
        cutoff = time.time() - max_age_seconds
        reaped = 0
        async for key in client.scan_iter(match=f"{self.namespace}:job:*"):
            raw = await client.hgetall(key)  # type: ignore[misc]
            if raw.get("status") not in {"queued", "running"}:
                continue
            try:
                updated_at = float(raw.get("updated_at", "0"))
            except ValueError:
                updated_at = 0.0
            if updated_at <= cutoff:
                await self.set_error(raw["id"], "job lease expired")
                reaped += 1
        return reaped

    async def set_result(self, job_id: str, result: dict[str, Any]) -> None:
        """Atomically mark the job done, store its result, and release capacity."""
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before set_result()")
        await set_terminal(
            client,
            self._key(job_id),
            self._total_count_key(),
            self.namespace,
            "done",
            json.dumps(result),
            "",
            self.ttl_seconds,
        )

    async def set_error(self, job_id: str, error: str) -> None:
        """Atomically mark the job failed, record the error, and release capacity."""
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before set_error()")
        await set_terminal(
            client,
            self._key(job_id),
            self._total_count_key(),
            self.namespace,
            "failed",
            "",
            error,
            self.ttl_seconds,
        )

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
                "updated_at": str(time.time()),
            },
        )
        await client.expire(key, self.ttl_seconds)


async def set_terminal(
    client: aioredis.Redis,
    job_key: str,
    total_key: str,
    namespace: str,
    status: str,
    result: str,
    error: str,
    ttl_seconds: int,
) -> None:
    """Atomically complete a job and release its admission counters."""
    owner = await client.hget(job_key, "owner")  # type: ignore[misc]
    owner_key = JobStore.COUNT_KEY_TEMPLATE.format(ns=namespace, owner=owner or "")
    await client.eval(  # type: ignore[misc]
        JobStore.TERMINAL_SCRIPT,
        3,
        job_key,
        owner_key,
        total_key,
        status,
        result,
        error,
        str(ttl_seconds),
        str(time.time()),
    )


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


async def release_total_count(client: aioredis.Redis, count_key: str) -> None:
    """Decrement the shared in-flight job count without going negative."""
    raw = await client.get(count_key)
    if raw is None:
        return
    if int(raw) <= 1:
        await client.delete(count_key)
    else:
        await client.decr(count_key, 1)
