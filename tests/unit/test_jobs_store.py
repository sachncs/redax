from __future__ import annotations

import pytest

from app.jobs.store import JobStore


class FakeRedis:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, str]] = {}
        self.expires: list[tuple[str, int]] = []
        self.counter: dict[str, int] = {}

    async def hset(
        self,
        key: str,
        field: str | None = None,
        value: str | None = None,
        *,
        mapping: dict[str, str] | None = None,
    ) -> None:  # type: ignore[misc]
        record = self.records.setdefault(key, {})
        if mapping is not None:
            record.update(mapping)
        else:
            assert field is not None and value is not None
            record[field] = value

    async def hget(self, key: str, field: str) -> str | None:
        return self.records.get(key, {}).get(field)

    async def hgetall(self, key: str) -> dict[str, str]:
        return self.records.get(key, {})

    async def expire(self, key: str, ttl: int) -> None:
        self.expires.append((key, ttl))

    async def get(self, key: str) -> str | None:
        value = self.counter.get(key)
        return str(value) if value is not None else None

    async def incr(self, key: str) -> int:
        self.counter[key] = self.counter.get(key, 0) + 1
        return self.counter[key]

    async def decr(self, key: str, by: int = 1) -> int:
        self.counter[key] = self.counter.get(key, 0) - by
        return self.counter[key]

    async def delete(self, key: str) -> None:
        self.counter.pop(key, None)


@pytest.fixture
def store(redis_client: FakeRedis) -> JobStore:
    return JobStore("redis://localhost:6379/0", ttl_seconds=60, client=redis_client)  # type: ignore[arg-type]


@pytest.fixture
def redis_client() -> FakeRedis:
    return FakeRedis()


async def test_create_keeps_ttl_and_tracks_owner(store: JobStore, redis_client: FakeRedis) -> None:
    record = await store.create(owner="k1")
    assert redis_client.records[f"redax:job:{record.id}"]["owner"] == "k1"
    assert redis_client.counter["redax:jobs:k1"] == 1
    assert (f"redax:job:{record.id}", 60) in redis_client.expires
    assert ("redax:jobs:k1", 60) in redis_client.expires


async def test_count_for_key_reads_counter(store: JobStore, redis_client: FakeRedis) -> None:
    await store.create(owner="k1")
    await store.create(owner="k1")
    await store.create(owner="k2")
    assert await store.count_for_key("k1") == 2
    assert await store.count_for_key("k2") == 1
    assert await store.count_for_key("missing") == 0


async def test_terminal_transition_releases_owner_slot(
    store: JobStore, redis_client: FakeRedis
) -> None:
    record = await store.create(owner="k1")
    await store.set_result(record.id, {"text": "done"})
    assert await store.count_for_key("k1") == 0
    assert "redax:jobs:k1" not in redis_client.counter


async def test_error_transition_releases_owner_slot(
    store: JobStore, redis_client: FakeRedis
) -> None:
    record = await store.create(owner="k1")
    await store.set_error(record.id, "job failed")
    assert await store.count_for_key("k1") == 0


async def test_job_without_owner_never_touches_counter(
    store: JobStore, redis_client: FakeRedis
) -> None:
    record = await store.create()
    await store.set_result(record.id, {"text": "done"})
    assert redis_client.counter == {}


def test_ttl_defaults_to_86400() -> None:
    store = JobStore("redis://localhost:6379/0")
    assert store.ttl_seconds == 86_400
