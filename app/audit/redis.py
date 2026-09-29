"""Redis-backed centralized audit event storage."""

from __future__ import annotations

import json

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.audit.backend import Event, event_to_dict, with_timestamp
from app.logging import get_logger
from app.observability import AUDIT_DROPPED, AUDIT_WRITE_FAILED


class RedisAudit:
    """Persist metadata-only audit events in a bounded shared Redis list."""

    def __init__(
        self,
        client: aioredis.Redis | None,
        namespace: str = "redax",
        max_events: int = 100_000,
        required: bool = False,
    ) -> None:
        self.client = client
        self.key = f"{namespace}:audit:events"
        self.max_events = max_events
        self.required = required
        self.backend_label = "redis"
        self.failed = False

    async def start(self) -> None:
        """Verify that the shared Redis client is available."""
        if self.client is None:
            raise RuntimeError("Redis audit backend requires a connected Redis client")
        self.failed = False

    async def stop(self) -> None:
        """Leave the shared Redis client open for the owning job store."""

    async def record(self, event: Event) -> None:
        """Append one bounded, JSON-encoded metadata event."""
        if self.client is None:
            raise RuntimeError("Redis audit backend is unavailable")
        payload = json.dumps(
            event_to_dict(with_timestamp(event)), separators=(",", ":"), sort_keys=True
        )
        try:
            await self.client.rpush(self.key, payload)  # type: ignore[misc]
            await self.client.ltrim(self.key, -self.max_events, -1)  # type: ignore[misc]
            self.failed = False
        except (OSError, RedisError, RuntimeError, TimeoutError, ValueError) as exc:
            self.failed = True
            AUDIT_WRITE_FAILED.labels(backend=self.backend_label).inc()
            get_logger("redax.audit").warning(
                "redax.audit_write_failed",
                backend=self.backend_label,
                error=exc.__class__.__name__,
            )
            AUDIT_DROPPED.labels(backend=self.backend_label).inc()
            if self.required:
                raise RuntimeError("audit backend is unavailable") from exc
