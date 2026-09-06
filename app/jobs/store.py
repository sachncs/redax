from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from typing import Any

import redis.asyncio as aioredis


@dataclass
class JobRecord:
    id: str
    status: str  # queued | running | done | failed
    result: dict[str, Any] | None
    error: str | None


class JobStore:
    """Thin wrapper over Redis hashes for job lifecycle + result storage."""

    KEY = "redax:job:{id}"
    TTL_SECONDS = 60 * 60 * 24  # 24h

    def __init__(self, redis_url: str) -> None:
        self._url = redis_url
        self._client: aioredis.Redis | None = None

    async def start(self) -> None:
        if self._client is None:
            self._client = aioredis.from_url(  # type: ignore[no-untyped-call]
                self._url, decode_responses=True
            )
            await self._client.ping()

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> aioredis.Redis:
        if self._client is None:
            raise RuntimeError("JobStore not started")
        return self._client

    async def create(self) -> JobRecord:
        job_id = uuid.uuid4().hex
        record = JobRecord(id=job_id, status="queued", result=None, error=None)
        await self._set(record)
        return record

    async def get(self, job_id: str) -> JobRecord | None:
        raw = await self.client.hgetall(self.KEY.format(id=job_id))  # type: ignore[misc]
        if not raw:
            return None
        result_raw = raw.get("result")
        return JobRecord(
            id=raw["id"],
            status=raw["status"],
            result=json.loads(result_raw) if result_raw else None,
            error=raw.get("error"),
        )

    async def set_status(self, job_id: str, status: str) -> None:
        await self.client.hset(self.KEY.format(id=job_id), "status", status)  # type: ignore[misc]
        await self.client.expire(self.KEY.format(id=job_id), self.TTL_SECONDS)

    async def set_result(self, job_id: str, result: dict[str, Any]) -> None:
        await self.client.hset(self.KEY.format(id=job_id), "result", json.dumps(result))  # type: ignore[misc]
        await self.client.hset(self.KEY.format(id=job_id), "status", "done")  # type: ignore[misc]
        await self.client.expire(self.KEY.format(id=job_id), self.TTL_SECONDS)

    async def set_error(self, job_id: str, error: str) -> None:
        await self.client.hset(self.KEY.format(id=job_id), "error", error)  # type: ignore[misc]
        await self.client.hset(self.KEY.format(id=job_id), "status", "failed")  # type: ignore[misc]
        await self.client.expire(self.KEY.format(id=job_id), self.TTL_SECONDS)

    async def _set(self, record: JobRecord) -> None:
        await self.client.hset(  # type: ignore[misc]
            self.KEY.format(id=record.id),
            mapping={
                "id": record.id,
                "status": record.status,
                "result": json.dumps(record.result) if record.result else "",
                "error": record.error or "",
            },
        )
        await self.client.expire(self.KEY.format(id=record.id), self.TTL_SECONDS)


def build_default_store(redis_url: str | None = None) -> JobStore:
    return JobStore(redis_url or os.environ.get("REDAX_REDIS_URL", "redis://localhost:6379/0"))
