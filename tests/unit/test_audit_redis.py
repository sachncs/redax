from __future__ import annotations

import json

import pytest

from app.audit.backend import Event, verify_event_integrity
from app.audit.redis import RedisAudit


class FakeRedis:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.timestamps: list[float] = []

    async def rpush(self, _key: str, value: str) -> int:
        self.events.append(value)
        return len(self.events)

    async def ltrim(self, _key: str, start: int, end: int) -> None:
        self.events = self.events[start : end + 1 if end >= 0 else None]

    async def eval(
        self,
        _script: str,
        _key_count: int,
        _event_key: str,
        _timestamp_key: str,
        value: str,
        timestamp: str,
        limit: str,
        cutoff: str,
    ) -> int:
        while len(self.timestamps) < len(self.events):
            self.timestamps.append(float(timestamp))
        self.events.append(value)
        self.timestamps.append(float(timestamp))
        max_events = int(limit)
        self.events = self.events[-max_events:]
        self.timestamps = self.timestamps[-max_events:]
        while self.timestamps and self.timestamps[0] < float(cutoff):
            self.events.pop(0)
            self.timestamps.pop(0)
        return 1


class FailingRedis(FakeRedis):
    async def rpush(self, _key: str, value: str) -> int:
        raise ConnectionError("redis unavailable")

    async def eval(self, *args: str) -> int:
        del args
        raise ConnectionError("redis unavailable")


async def test_redis_audit_stores_versioned_metadata_only() -> None:
    client = FakeRedis()
    backend = RedisAudit(client, namespace="test", max_events=2)  # type: ignore[arg-type]
    await backend.start()
    await backend.record(
        Event(
            request_id="req-1",
            ts="",
            policy_version="default-1.0.0",
            text_chars=42,
            entities_detected=[{"type": "EMAIL", "count": 1, "confidence_avg": 1.0}],
        )
    )

    payload = json.loads(client.events[0])
    assert payload["schema_version"] == 1
    assert payload["ts"].endswith("+00:00")
    assert payload["text_chars"] == 42
    assert "alice@example.com" not in client.events[0]
    assert len(client.timestamps) == 1


async def test_redis_audit_retains_only_configured_event_count() -> None:
    client = FakeRedis()
    backend = RedisAudit(client, namespace="test", max_events=2)  # type: ignore[arg-type]
    await backend.start()
    for request_id in ("one", "two", "three"):
        await backend.record(Event(request_id=request_id, ts="", policy_version="p", text_chars=1))

    assert len(client.events) == 2
    assert [json.loads(event)["request_id"] for event in client.events] == ["two", "three"]
    assert len(client.timestamps) == 2


async def test_redis_audit_signs_metadata_for_integrity_verification() -> None:
    client = FakeRedis()
    backend = RedisAudit(client, integrity_key="audit-integrity-key")  # type: ignore[arg-type]
    await backend.start()
    await backend.record(Event(request_id="req", ts="", policy_version="p", text_chars=1))

    payload = json.loads(client.events[0])
    assert payload["integrity"]["algorithm"] == "hmac-sha256"
    assert verify_event_integrity(payload, "audit-integrity-key")
    assert not verify_event_integrity(payload, "wrong-key")


async def test_redis_audit_requires_shared_client() -> None:
    with pytest.raises(RuntimeError, match="requires a connected Redis client"):
        await RedisAudit(None).start()


async def test_required_redis_audit_fails_closed_on_write_error() -> None:
    backend = RedisAudit(FailingRedis(), required=True)  # type: ignore[arg-type]
    await backend.start()

    with pytest.raises(RuntimeError, match="audit backend is unavailable"):
        await backend.record(Event(request_id="req", ts="", policy_version="p", text_chars=1))
    assert backend.failed is True


async def test_optional_redis_audit_drops_failed_write() -> None:
    backend = RedisAudit(FailingRedis(), required=False)  # type: ignore[arg-type]
    await backend.start()
    await backend.record(Event(request_id="req", ts="", policy_version="p", text_chars=1))
