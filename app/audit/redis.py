"""Redis-backed centralized audit event storage."""

from __future__ import annotations

import json

import redis.asyncio as aioredis

from app.audit.backend import Event, event_to_dict


class RedisAudit:
    """Persist metadata-only audit events in a bounded shared Redis list."""

    def __init__(
        self,
        client: aioredis.Redis | None,
        namespace: str = "redax",
        max_events: int = 100_000,
    ) -> None:
        self.client = client
        self.key = f"{namespace}:audit:events"
        self.max_events = max_events

    async def start(self) -> None:
        """Verify that the shared Redis client is available."""
        if self.client is None:
            raise RuntimeError("Redis audit backend requires a connected Redis client")

    async def stop(self) -> None:
        """Leave the shared Redis client open for the owning job store."""

    async def record(self, event: Event) -> None:
        """Append one bounded, JSON-encoded metadata event."""
        if self.client is None:
            raise RuntimeError("Redis audit backend is unavailable")
        payload = json.dumps(event_to_dict(event), separators=(",", ":"), sort_keys=True)
        await self.client.rpush(self.key, payload)  # type: ignore[misc]
        await self.client.ltrim(self.key, -self.max_events, -1)  # type: ignore[misc]
