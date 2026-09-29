from __future__ import annotations

from typing import ClassVar

import pytest

from app.jobs.store import JobStore


class FakeRedis:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, str]] = {}
        self.expires: list[tuple[str, int]] = []
        self.counter: dict[str, int] = {}
        self.lists: dict[str, list[str]] = {}
        self.sorted_sets: dict[str, dict[str, float]] = {}

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

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        self.sorted_sets.setdefault(key, {}).update(mapping)
        return len(mapping)

    async def zrange(self, key: str, start: int, end: int, *, withscores: bool = False):
        values = sorted(self.sorted_sets.get(key, {}).items(), key=lambda item: item[1])
        values = values[start : end + 1 if end >= 0 else None]
        return values if withscores else [value[0] for value in values]

    async def exists(self, key: str) -> int:
        return int(key in self.records)

    async def zrem(self, key: str, member: str) -> int:
        return int(self.sorted_sets.get(key, {}).pop(member, None) is not None)

    async def rpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    async def ltrim(self, key: str, start: int, end: int) -> None:
        values = self.lists.get(key, [])
        self.lists[key] = values[start:] if start < 0 and end == -1 else values[start : end + 1]

    async def scan_iter(self, match: str):
        for key in self.records:
            if key.startswith("redax:job:"):
                yield key

    async def eval(
        self,
        _script: str,
        _numkeys: int,
        job_key: str,
        owner_key: str,
        total_key: str,
        queue_key: str,
        *args: str,
    ) -> int:
        if len(args) == 7:
            status, result, error, ttl, updated_at, schema_version, job_id = args
            record = self.records.get(job_key, {})
            if record.get("status") not in {"queued", "running"}:
                return 0
            record.update(
                {
                    "status": status,
                    "result": result,
                    "error": error,
                    "updated_at": updated_at,
                    "schema_version": schema_version,
                }
            )
            await self.expire(job_key, int(ttl))
            await self.zrem(queue_key, job_id)
            owner = record.get("owner", "")
            if owner:
                count = self.counter.get(owner_key, 0)
                if count <= 1:
                    await self.delete(owner_key)
                else:
                    await self.decr(owner_key)
            count = self.counter.get(total_key, 0)
            if count <= 1:
                await self.delete(total_key)
            else:
                await self.decr(total_key)
            return 1
        (
            job_id,
            status,
            result,
            error,
            owner,
            ttl,
            max_total,
            max_owner,
            updated_at,
            schema_version,
        ) = args
        total = self.counter.get(total_key, 0)
        owner_count = self.counter.get(owner_key, 0)
        if total >= int(max_total) or (owner and owner_count >= int(max_owner)):
            return 0
        await self.hset(
            job_key,
            mapping={
                "id": job_id,
                "status": status,
                "result": result,
                "error": error,
                "owner": owner,
                "updated_at": updated_at,
                "schema_version": schema_version,
            },
        )
        await self.expire(job_key, int(ttl))
        await self.zadd(queue_key, {job_id: float(updated_at)})
        await self.expire(queue_key, int(ttl))
        await self.incr(total_key)
        await self.expire(total_key, int(ttl))
        if owner:
            await self.incr(owner_key)
            await self.expire(owner_key, int(ttl))
        return 1


@pytest.fixture
def store(redis_client: FakeRedis) -> JobStore:
    return JobStore("redis://localhost:6379/0", ttl_seconds=60, client=redis_client)  # type: ignore[arg-type]


@pytest.fixture
def redis_client() -> FakeRedis:
    return FakeRedis()


async def test_start_configures_bounded_redis_client(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class Client:
        async def ping(self) -> bool:
            return True

        async def aclose(self) -> None:
            return None

    def from_url(url: str, **kwargs: object) -> Client:
        captured["url"] = url
        captured.update(kwargs)
        return Client()

    monkeypatch.setattr("app.jobs.store.aioredis.from_url", from_url)
    store = JobStore(
        "redis://redis.example:6379/2",
        connect_timeout_seconds=0.4,
        socket_timeout_seconds=0.8,
        max_connections=12,
    )
    await store.start()

    assert captured == {
        "url": "redis://redis.example:6379/2",
        "decode_responses": True,
        "socket_connect_timeout": 0.4,
        "socket_timeout": 0.8,
        "max_connections": 12,
        "health_check_interval": 30,
        "retry_on_timeout": True,
    }


async def test_create_keeps_ttl_and_tracks_owner(store: JobStore, redis_client: FakeRedis) -> None:
    record = await store.create(owner="k1")
    owner_token = store.owner_token("k1")
    assert redis_client.records[f"redax:job:{record.id}"]["owner"] == owner_token
    assert redis_client.records[f"redax:job:{record.id}"]["schema_version"] == "1"
    assert redis_client.counter[f"redax:jobs:{owner_token}"] == 1
    assert (f"redax:job:{record.id}", 60) in redis_client.expires
    assert (f"redax:jobs:{owner_token}", 60) in redis_client.expires


async def test_oldest_job_age_ignores_expired_index_entries(
    store: JobStore, redis_client: FakeRedis
) -> None:
    await redis_client.zadd("redax:jobs:created", {"missing": 1.0})
    record = await store.create(owner="k1")
    age = await store.oldest_job_age_seconds()
    assert age >= 0
    assert "missing" not in redis_client.sorted_sets["redax:jobs:created"]
    await store.set_result(record.id, {"text": "done"})
    assert await store.oldest_job_age_seconds() == 0.0


def test_pool_stats_exposes_only_bounded_counts(store: JobStore) -> None:
    assert store.pool_stats() == {"in_use": 0, "available": 0, "max": 0}


def test_pool_stats_reports_connection_utilization(
    store: JobStore, redis_client: FakeRedis
) -> None:
    class Pool:
        _in_use_connections: ClassVar[set[object]] = {object(), object()}
        _available_connections: ClassVar[list[object]] = [object()]
        max_connections = 8

    redis_client.connection_pool = Pool()
    assert store.pool_stats() == {"in_use": 2, "available": 1, "max": 8}


async def test_count_for_key_reads_counter(store: JobStore, redis_client: FakeRedis) -> None:
    await store.create(owner="k1")
    await store.create(owner="k1")
    await store.create(owner="k2")
    assert await store.count_for_key("k1") == 2
    assert await store.count_for_key("k2") == 1
    assert await store.count_for_key("missing") == 0


async def test_create_admitted_reserves_shared_and_owner_slots_atomically(
    store: JobStore,
    redis_client: FakeRedis,
) -> None:
    first = await store.create_admitted("k1", max_inflight=1, max_jobs_per_key=1)
    second = await store.create_admitted("k1", max_inflight=1, max_jobs_per_key=1)
    assert first is not None
    assert second is None
    assert await store.count_inflight() == 1
    assert await store.count_for_key("k1") == 1


async def test_reap_stale_job_fails_record_and_releases_capacity(
    store: JobStore,
    redis_client: FakeRedis,
) -> None:
    record = await store.create(owner="k1")
    redis_client.records[f"redax:job:{record.id}"]["updated_at"] = "0"
    assert await store.reap_stale_jobs(max_age_seconds=1) == 1
    assert redis_client.records[f"redax:job:{record.id}"]["status"] == "failed"
    assert redis_client.records[f"redax:job:{record.id}"]["error"] == "job lease expired"
    assert await store.count_inflight() == 0
    assert await store.count_for_key("k1") == 0


async def test_dead_letter_is_bounded_and_payload_free(
    store: JobStore, redis_client: FakeRedis
) -> None:
    await store.record_dead_letter("job-1", "job failed", attempts=5)
    event = redis_client.lists["redax:jobs:dead-letter"][0]
    assert "job-1" in event
    assert "job failed" in event
    assert "payload" not in event


async def test_terminal_transition_releases_owner_slot(
    store: JobStore, redis_client: FakeRedis
) -> None:
    record = await store.create(owner="k1")
    await store.set_result(record.id, {"text": "done"})
    assert await store.count_for_key("k1") == 0
    assert f"redax:jobs:{store.owner_token('k1')}" not in redis_client.counter


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


async def test_set_record_with_none_result_writes_empty_field(
    store: JobStore, redis_client: FakeRedis
) -> None:
    from app.jobs.store import JobRecord

    record = JobRecord(id="abc", status="queued", result=None, error=None, owner="k1")
    await store.set_record(record)
    stored = redis_client.records["redax:job:abc"]
    assert stored["result"] == ""
    assert stored["schema_version"] == "1"


async def test_set_record_with_falsy_but_non_none_result_writes_value(
    store: JobStore, redis_client: FakeRedis
) -> None:
    import json as _json

    from app.jobs.store import JobRecord

    record = JobRecord(id="abc", status="queued", result={"x": 0}, error=None, owner="k1")
    await store.set_record(record)
    stored = redis_client.records["redax:job:abc"]
    assert _json.loads(stored["result"]) == {"x": 0}


async def test_get_returns_none_result_when_field_is_empty(
    store: JobStore, redis_client: FakeRedis
) -> None:
    from app.jobs.store import JobRecord

    record = JobRecord(id="abc", status="queued", result=None, error=None, owner="k1")
    await store.set_record(record)
    fetched = await store.get("abc")
    assert fetched is not None
    assert fetched.result is None
    assert fetched.error is None
    assert fetched.status == "queued"


async def test_release_owner_count_deletes_when_count_reaches_one(
    store: JobStore, redis_client: FakeRedis
) -> None:
    """The count -> 0 branch must delete the counter key entirely."""
    record = await store.create(owner="k1")
    # Counter is at 1; set_result calls release_owner_count, which
    # takes the int(raw) <= 1 path and deletes the key.
    await store.set_result(record.id, {"text": "done"})
    assert f"redax:jobs:{store.owner_token('k1')}" not in redis_client.counter
    assert await store.count_for_key("k1") == 0
