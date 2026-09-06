from __future__ import annotations

import pytest

from app.jobs.store import JobStore


class FakeRedis:
    def __init__(self) -> None:
        self.expires: list[int] = []
        self.mapping: dict[str, str] = {}

    async def hset(
        self,
        key: str,
        field: str | None = None,
        value: str | None = None,
        *,
        mapping: dict[str, str] | None = None,
    ) -> None:  # type: ignore[misc]
        if mapping is not None:
            self.mapping.update(mapping)
        else:
            assert field is not None and value is not None
            self.mapping[field] = value

    async def expire(self, key: str, ttl: int) -> None:
        self.expires.append(ttl)


@pytest.fixture
def store() -> JobStore:
    return JobStore("redis://localhost:6379/0", ttl_seconds=60)


@pytest.fixture
def redis_client() -> FakeRedis:
    return FakeRedis()


async def test_create_expires_with_configured_ttl(store: JobStore, redis_client: FakeRedis) -> None:
    store._client = redis_client  # type: ignore[assignment]  # inject fake via the client seam
    record = await store.create()
    assert redis_client.expires == [60]
    assert redis_client.mapping["status"] == "queued"
    _ = record


async def test_set_result_expires_with_configured_ttl(
    store: JobStore, redis_client: FakeRedis
) -> None:
    store._client = redis_client  # type: ignore[assignment]
    await store.set_result("abc", {"text": "done"})
    assert redis_client.mapping["status"] == "done"
    assert redis_client.expires == [60]


async def test_set_error_expires_with_configured_ttl(
    store: JobStore, redis_client: FakeRedis
) -> None:
    store._client = redis_client  # type: ignore[assignment]
    await store.set_error("abc", "job failed")
    assert redis_client.mapping["status"] == "failed"
    assert redis_client.expires == [60]


def test_ttl_defaults_to_86400() -> None:
    store = JobStore("redis://localhost:6379/0")
    assert store.ttl_seconds == 86_400
