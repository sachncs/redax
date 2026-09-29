"""Atomic Redis-backed idempotency reservations for HTTP requests."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal

IDEMPOTENCY_VERSION = 3
ReservationStatus = Literal["acquired", "completed", "conflict", "in_progress"]

COMPLETE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
  redis.call('DEL', KEYS[1])
  return 1
end
return 0
"""

RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  redis.call('DEL', KEYS[1])
  return 1
end
return 0
"""


@dataclass(frozen=True)
class Reservation:
    """Result of attempting to reserve one idempotency key."""

    status: ReservationStatus
    token: str | None = None
    response: dict[str, Any] | None = None


def lock_key(storage_key: str) -> str:
    """Return the separate short-lived lock key for a result key."""
    return f"{storage_key}:lock"


def _decode(raw: str | bytes | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


async def reserve(
    client: Any,
    storage_key: str,
    fingerprint: str,
    ttl_seconds: int,
) -> Reservation:
    """Atomically acquire a lease or inspect a completed reservation.

    A completed result is replayable only for the same request fingerprint.
    An active lease returns ``in_progress`` and expires automatically if the
    owning process dies, allowing a later retry to recover.
    """
    existing = _decode(await client.get(storage_key))
    if existing and existing.get("version") == IDEMPOTENCY_VERSION:
        if existing.get("fingerprint") != fingerprint:
            return Reservation("conflict")
        response = existing.get("response")
        if existing.get("state") == "complete" and isinstance(response, dict):
            return Reservation("completed", response=response)

    token = uuid.uuid4().hex
    lock = lock_key(storage_key)
    acquired = await client.set(lock, token, ex=ttl_seconds, nx=True)
    if acquired:
        return Reservation("acquired", token=token)

    return Reservation("in_progress")


async def complete(
    client: Any,
    storage_key: str,
    fingerprint: str,
    token: str,
    response: dict[str, Any],
    ttl_seconds: int,
) -> bool:
    """Publish a result only while the caller still owns the lease."""
    envelope = json.dumps(
        {
            "version": IDEMPOTENCY_VERSION,
            "state": "complete",
            "fingerprint": fingerprint,
            "response": response,
        },
        separators=(",", ":"),
    )
    result = await client.eval(
        COMPLETE_SCRIPT,
        2,
        lock_key(storage_key),
        storage_key,
        token,
        envelope,
        str(ttl_seconds),
    )
    return bool(result)


async def release(client: Any, storage_key: str, token: str) -> bool:
    """Release a reservation without deleting another request's lease."""
    result = await client.eval(RELEASE_SCRIPT, 1, lock_key(storage_key), token)
    return bool(result)
