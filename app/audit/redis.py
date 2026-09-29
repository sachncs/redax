"""Redis-backed centralized audit event storage."""

from __future__ import annotations

import json
import time

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.audit.backend import Event, signed_event_payload
from app.logging import get_logger
from app.observability import AUDIT_DROPPED, AUDIT_WRITE_FAILED

APPEND_AUDIT_SCRIPT = """
local event_count = redis.call('LLEN', KEYS[1])
local timestamp_count = redis.call('LLEN', KEYS[2])
if timestamp_count < event_count then
  for _ = timestamp_count + 1, event_count do
    redis.call('RPUSH', KEYS[2], ARGV[2])
  end
elseif timestamp_count > event_count then
  redis.call('LTRIM', KEYS[2], -event_count, -1)
end
redis.call('RPUSH', KEYS[1], ARGV[1])
redis.call('RPUSH', KEYS[2], ARGV[2])
redis.call('LTRIM', KEYS[1], -tonumber(ARGV[3]), -1)
redis.call('LTRIM', KEYS[2], -tonumber(ARGV[3]), -1)
local cutoff = tonumber(ARGV[4])
while redis.call('LLEN', KEYS[2]) > 0 do
  local oldest = tonumber(redis.call('LINDEX', KEYS[2], 0))
  if oldest == nil or oldest >= cutoff then break end
  redis.call('LPOP', KEYS[1])
  redis.call('LPOP', KEYS[2])
end
return 1
"""


class RedisAudit:
    """Persist metadata-only audit events in a bounded shared Redis list."""

    def __init__(
        self,
        client: aioredis.Redis | None,
        namespace: str = "redax",
        max_events: int = 100_000,
        retention_seconds: int = 90 * 24 * 3600,
        required: bool = False,
        integrity_key: str = "",
    ) -> None:
        self.client = client
        self.key = f"{namespace}:audit:events"
        self.timestamp_key = f"{namespace}:audit:event-timestamps"
        self.max_events = max_events
        self.retention_seconds = retention_seconds
        self.required = required
        self.integrity_key = integrity_key
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
            signed_event_payload(event, self.integrity_key), separators=(",", ":"), sort_keys=True
        )
        try:
            await self.client.eval(  # type: ignore[misc]
                APPEND_AUDIT_SCRIPT,
                2,
                self.key,
                self.timestamp_key,
                payload,
                str(time.time()),
                str(self.max_events),
                str(time.time() - self.retention_seconds),
            )
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
