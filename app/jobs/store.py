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

from app.schema_versions import DURABLE_JOB_SCHEMA_VERSION


@dataclass
class JobRecord:
    """A single job's lifecycle state plus its current result or error.

    Attributes:
        id: Server-assigned 32-char hex identifier.
        status: One of ``queued``, ``running``, ``done``, ``failed``, ``cancelled``.
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
    JOB_SCHEMA_VERSION = DURABLE_JOB_SCHEMA_VERSION
    COUNT_KEY_TEMPLATE = "{ns}:jobs:{owner}"
    TOTAL_COUNT_KEY_TEMPLATE = "{ns}:jobs:inflight"
    QUEUE_INDEX_KEY_TEMPLATE = "{ns}:jobs:created"
    WORKER_KEY_TEMPLATE = "{ns}:worker:{worker_id}"
    ADMIT_SCRIPT = """
local total = tonumber(redis.call('GET', KEYS[3]) or '0')
local owner = tonumber(redis.call('GET', KEYS[2]) or '0')
if total >= tonumber(ARGV[7]) then return 0 end
if ARGV[5] ~= '' and owner >= tonumber(ARGV[8]) then return 0 end
redis.call('HSET', KEYS[1], 'id', ARGV[1], 'status', ARGV[2], 'result', ARGV[3], 'error', ARGV[4], 'owner', ARGV[5], 'updated_at', ARGV[9])
redis.call('HSET', KEYS[1], 'schema_version', ARGV[10])
redis.call('ZADD', KEYS[4], ARGV[9], ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[6])
redis.call('EXPIRE', KEYS[4], ARGV[6])
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
if redis.call('HGET', KEYS[1], 'schema_version') ~= ARGV[7] then return 0 end
redis.call('HSET', KEYS[1], 'status', ARGV[1], 'result', ARGV[2], 'error', ARGV[3], 'updated_at', ARGV[5], 'schema_version', ARGV[6])
redis.call('EXPIRE', KEYS[1], ARGV[4])
redis.call('ZREM', KEYS[4], ARGV[8])
local owner = redis.call('HGET', KEYS[1], 'owner')
if owner ~= false and owner ~= '' then
  local owner_count = tonumber(redis.call('GET', KEYS[2]) or '0')
  if owner_count <= 1 then redis.call('DEL', KEYS[2]) else redis.call('DECR', KEYS[2]) end
end
local total = tonumber(redis.call('GET', KEYS[3]) or '0')
if total <= 1 then redis.call('DEL', KEYS[3]) else redis.call('DECR', KEYS[3]) end
return 1
"""
    CLAIM_SCRIPT = """
local status = redis.call('HGET', KEYS[1], 'status')
if status ~= 'queued' then return 0 end
if redis.call('HGET', KEYS[1], 'schema_version') ~= ARGV[3] then return 0 end
redis.call('HSET', KEYS[1], 'status', 'running', 'updated_at', ARGV[2], 'schema_version', ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[1])
return 1
"""
    CANCEL_SCRIPT = """
local status = redis.call('HGET', KEYS[1], 'status')
if status ~= 'queued' then return 0 end
if redis.call('HGET', KEYS[1], 'schema_version') ~= ARGV[5] then return 0 end
redis.call('HSET', KEYS[1], 'status', 'cancelled', 'error', ARGV[1], 'updated_at', ARGV[2], 'schema_version', ARGV[5])
redis.call('EXPIRE', KEYS[1], ARGV[3])
redis.call('ZREM', KEYS[4], ARGV[4])
local owner_count = tonumber(redis.call('GET', KEYS[2]) or '0')
if owner_count <= 1 then redis.call('DEL', KEYS[2]) else redis.call('DECR', KEYS[2]) end
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
        dead_letter_max: int = 1000,
    ) -> None:
        self.url = redis_url
        self.ttl_seconds = ttl_seconds
        self.client = client
        self.namespace = namespace
        self.connect_timeout_seconds = connect_timeout_seconds
        self.socket_timeout_seconds = socket_timeout_seconds
        self.max_connections = max_connections
        self.dead_letter_max = dead_letter_max

    def _key(self, job_id: str) -> str:
        return self.KEY_TEMPLATE.format(ns=self.namespace, id=job_id)

    def _count_key(self, owner: str) -> str:
        return self.COUNT_KEY_TEMPLATE.format(ns=self.namespace, owner=self.owner_token(owner))

    def _total_count_key(self) -> str:
        return self.TOTAL_COUNT_KEY_TEMPLATE.format(ns=self.namespace)

    def _queue_index_key(self) -> str:
        return self.QUEUE_INDEX_KEY_TEMPLATE.format(ns=self.namespace)

    def _dead_letter_key(self) -> str:
        return f"{self.namespace}:jobs:dead-letter"

    def _worker_key(self, worker_id: str) -> str:
        return self.WORKER_KEY_TEMPLATE.format(ns=self.namespace, worker_id=worker_id)

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

    async def worker_heartbeat(self, worker_id: str, active_jobs: int, max_jobs: int) -> None:
        """Publish a short-lived worker heartbeat and bounded capacity snapshot."""
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before worker_heartbeat()")
        key = self._worker_key(worker_id)
        await client.hset(  # type: ignore[misc]
            key,
            mapping={
                "active_jobs": str(max(0, active_jobs)),
                "max_jobs": str(max(1, max_jobs)),
                "updated_at": str(time.time()),
            },
        )
        await client.expire(key, 15)

    async def worker_stop(self, worker_id: str) -> None:
        """Remove a worker heartbeat during an orderly worker shutdown."""
        if self.client is not None:
            await self.client.delete(self._worker_key(worker_id))

    async def active_worker_count(self) -> int:
        """Count workers whose heartbeat keys have not expired."""
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before active_worker_count()")
        count = 0
        async for _key in client.scan_iter(match=f"{self.namespace}:worker:*"):
            count += 1
        return count

    async def worker_capacity(self) -> dict[str, int]:
        """Aggregate active and configured job slots from live worker heartbeats."""
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before worker_capacity()")
        active_jobs = 0
        max_jobs = 0
        async for key in client.scan_iter(match=f"{self.namespace}:worker:*"):
            heartbeat = await client.hgetall(key)  # type: ignore[misc]
            try:
                active_jobs += max(0, int(heartbeat.get("active_jobs", "0")))
                max_jobs += max(0, int(heartbeat.get("max_jobs", "0")))
            except (TypeError, ValueError):
                continue
        return {"active": active_jobs, "max": max_jobs}

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
        await client.zadd(self._queue_index_key(), {job_id: time.time()})
        await client.expire(self._queue_index_key(), self.ttl_seconds)
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
            4,
            self._key(job_id),
            self._count_key(owner),
            self._total_count_key(),
            self._queue_index_key(),
            job_id,
            "queued",
            "",
            "",
            owner_token,
            str(self.ttl_seconds),
            str(max_inflight),
            str(max_jobs_per_key),
            str(time.time()),
            str(self.JOB_SCHEMA_VERSION),
        )
        if int(result) != 1:
            return None
        return JobRecord(job_id, "queued", None, None, owner_token)

    async def oldest_job_age_seconds(self) -> float:
        """Return the age of the oldest live queued/running job."""
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before oldest_job_age_seconds()")
        queue_key = self._queue_index_key()
        for _ in range(16):
            rows = await client.zrange(queue_key, 0, 0, withscores=True)
            if not rows:
                return 0.0
            job_id, created_at = rows[0]
            if await client.exists(self._key(str(job_id))):
                return max(0.0, time.time() - float(created_at))
            await client.zrem(queue_key, job_id)
        return 0.0

    def pool_stats(self) -> dict[str, int]:
        """Return bounded Redis pool utilization without exposing connection data."""
        client = self.client
        if client is None:
            return {"in_use": 0, "available": 0, "max": 0}
        pool = getattr(client, "connection_pool", None)
        if pool is None:
            return {"in_use": 0, "available": 0, "max": 0}
        in_use = len(getattr(pool, "_in_use_connections", ()))
        available = len(getattr(pool, "_available_connections", ()))
        maximum = int(getattr(pool, "max_connections", 0))
        return {"in_use": in_use, "available": available, "max": maximum}

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
        if raw.get("schema_version") != str(self.JOB_SCHEMA_VERSION):
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
        schema_version = await client.hget(key, "schema_version")  # type: ignore[misc]
        if schema_version != str(self.JOB_SCHEMA_VERSION):
            raise RuntimeError("job schema version is not supported")
        await client.hset(  # type: ignore[misc]
            key,
            mapping={
                "status": status,
                "updated_at": str(time.time()),
                "schema_version": str(self.JOB_SCHEMA_VERSION),
            },
        )
        await client.expire(key, self.ttl_seconds)

    async def claim(self, job_id: str) -> bool:
        """Atomically claim a queued job for one worker delivery."""
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before claim()")
        result = await client.eval(  # type: ignore[misc]
            self.CLAIM_SCRIPT,
            1,
            self._key(job_id),
            str(self.ttl_seconds),
            str(time.time()),
            str(self.JOB_SCHEMA_VERSION),
        )
        return bool(result)

    async def cancel(self, job_id: str) -> bool:
        """Atomically cancel a queued job and release its admission slots."""
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before cancel()")
        job_key = self._key(job_id)
        owner = await client.hget(job_key, "owner")  # type: ignore[misc]
        owner_key = self.COUNT_KEY_TEMPLATE.format(ns=self.namespace, owner=owner or "")
        result = await client.eval(  # type: ignore[misc]
            self.CANCEL_SCRIPT,
            4,
            job_key,
            owner_key,
            self._total_count_key(),
            self._queue_index_key(),
            "job cancelled",
            str(time.time()),
            str(self.ttl_seconds),
            job_id,
            str(self.JOB_SCHEMA_VERSION),
        )
        return bool(result)

    async def reap_stale_jobs(self, max_age_seconds: int) -> int:
        """Fail queued/running jobs older than the recovery lease threshold."""
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before reap_stale_jobs()")
        cutoff = time.time() - max_age_seconds
        reaped = 0
        async for key in client.scan_iter(match=f"{self.namespace}:job:*"):
            raw = await client.hgetall(key)  # type: ignore[misc]
            if raw.get("schema_version") != str(self.JOB_SCHEMA_VERSION):
                continue
            if raw.get("status") not in {"queued", "running"}:
                continue
            try:
                updated_at = float(raw.get("updated_at", "0"))
            except ValueError:
                updated_at = 0.0
            if updated_at <= cutoff and await self.set_error(raw["id"], "job lease expired"):
                reaped += 1
        return reaped

    async def set_result(self, job_id: str, result: dict[str, Any]) -> bool:
        """Atomically mark the job done, store its result, and release capacity."""
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before set_result()")
        return await set_terminal(
            client,
            self._key(job_id),
            self._total_count_key(),
            self._queue_index_key(),
            self.namespace,
            "done",
            json.dumps(result),
            "",
            self.ttl_seconds,
        )

    async def set_error(self, job_id: str, error: str) -> bool:
        """Atomically mark the job failed, record the error, and release capacity."""
        client = self.client
        if client is None:
            raise RuntimeError("JobStore.start() must run before set_error()")
        return await set_terminal(
            client,
            self._key(job_id),
            self._total_count_key(),
            self._queue_index_key(),
            self.namespace,
            "failed",
            "",
            error,
            self.ttl_seconds,
        )

    async def record_dead_letter(self, job_id: str, error: str, attempts: int) -> None:
        """Retain bounded, payload-free metadata for a permanently failed job."""
        client = getattr(self, "client", None)
        if client is None:
            raise RuntimeError("JobStore.start() must run before record_dead_letter()")
        event = json.dumps(
            {
                "schema_version": 1,
                "job_id": job_id,
                "error": error,
                "attempts": attempts,
                "recorded_at": time.time(),
            },
            separators=(",", ":"),
        )
        key = self._dead_letter_key()
        await client.rpush(key, event)
        await client.ltrim(key, -self.dead_letter_max, -1)
        await client.expire(key, self.ttl_seconds)

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
                "schema_version": str(self.JOB_SCHEMA_VERSION),
            },
        )
        await client.expire(key, self.ttl_seconds)


async def set_terminal(
    client: aioredis.Redis,
    job_key: str,
    total_key: str,
    queue_key: str,
    namespace: str,
    status: str,
    result: str,
    error: str,
    ttl_seconds: int,
) -> bool:
    """Atomically complete a job and release its admission counters."""
    owner = await client.hget(job_key, "owner")  # type: ignore[misc]
    owner_key = JobStore.COUNT_KEY_TEMPLATE.format(ns=namespace, owner=owner or "")
    result_value = await client.eval(  # type: ignore[misc]
        JobStore.TERMINAL_SCRIPT,
        4,
        job_key,
        owner_key,
        total_key,
        queue_key,
        status,
        result,
        error,
        str(ttl_seconds),
        str(time.time()),
        str(JobStore.JOB_SCHEMA_VERSION),
        str(JobStore.JOB_SCHEMA_VERSION),
        job_key.rsplit(":", 1)[-1],
    )
    return bool(result_value)


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
