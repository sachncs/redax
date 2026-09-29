"""Redis-coordinated circuit breaker for horizontally scaled model inference."""

from __future__ import annotations

import time
from typing import Any

import redis.asyncio as aioredis


class SharedBreaker:
    """Coordinate breaker state across API replicas through one Redis hash.

    The breaker only sheds model work; it never changes the redaction contract.
    If Redis coordination is unavailable, callers may use their local breaker
    as an explicit availability fallback.
    """

    ALLOW_SCRIPT = """
local state = redis.call('HGET', KEYS[1], 'state') or 'closed'
if state == 'closed' then
  redis.call('HINCRBY', KEYS[1], 'total_calls', 1)
  return {1, 0}
end
local opened_at = tonumber(redis.call('HGET', KEYS[1], 'opened_at') or '0')
if state == 'open' and (tonumber(ARGV[1]) - opened_at) < tonumber(ARGV[2]) then
  return {0, 0}
end
if redis.call('HGET', KEYS[1], 'probe') == '1' then
  return {0, 0}
end
redis.call('HSET', KEYS[1], 'probe', 1)
redis.call('HINCRBY', KEYS[1], 'total_calls', 1)
return {1, 1}
"""
    SUCCESS_SCRIPT = """
redis.call('HSET', KEYS[1], 'state', 'closed', 'consecutive_failures', 0, 'opened_at', 0, 'probe', 0)
redis.call('EXPIRE', KEYS[1], ARGV[1])
return 1
"""
    FAILURE_SCRIPT = """
local consecutive = redis.call('HINCRBY', KEYS[1], 'consecutive_failures', 1)
redis.call('HINCRBY', KEYS[1], 'total_failures', 1)
if ARGV[2] == '1' or consecutive >= tonumber(ARGV[1]) then
  redis.call('HSET', KEYS[1], 'state', 'open', 'opened_at', ARGV[3], 'probe', 0)
end
redis.call('EXPIRE', KEYS[1], ARGV[4])
return consecutive
"""

    def __init__(
        self,
        client: aioredis.Redis,
        namespace: str,
        name: str,
        threshold: int,
        cooldown_s: float,
        ttl_seconds: int = 86_400,
    ) -> None:
        self.client = client
        self.key = f"{namespace}:breaker:{name}"
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.ttl_seconds = ttl_seconds

    async def allow(self) -> tuple[bool, bool]:
        """Atomically decide whether this replica may execute or probe."""
        result: Any = await self.client.eval(  # type: ignore[misc]
            self.ALLOW_SCRIPT,
            1,
            self.key,
            str(time.time()),
            str(self.cooldown_s),
        )
        return bool(result[0]), bool(result[1])

    async def success(self, was_probe: bool) -> None:
        """Close the shared breaker after a successful model call."""
        await self.client.eval(  # type: ignore[misc]
            self.SUCCESS_SCRIPT,
            1,
            self.key,
            str(self.ttl_seconds),
        )

    async def failure(self, was_probe: bool) -> None:
        """Record one failure and open the shared breaker at the threshold."""
        await self.client.eval(  # type: ignore[misc]
            self.FAILURE_SCRIPT,
            1,
            self.key,
            str(self.threshold),
            "1" if was_probe else "0",
            str(time.time()),
            str(self.ttl_seconds),
        )
