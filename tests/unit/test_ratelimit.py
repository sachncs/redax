from __future__ import annotations

import pytest
from fastapi import HTTPException

import app.ratelimit as ratelimit_mod
from app.ratelimit import minute_bucket, rate_limit
from app.state import State


class FakeClient:
    def __init__(
        self, *, responses: list[int] | None = None, error: Exception | None = None
    ) -> None:
        self.responses = list(responses or [1])
        self.error = error
        self.incr_calls: list[str] = []
        self.expire_calls: list[tuple[str, int]] = []
        self.eval_calls: list[tuple[str, int, str, str]] = []

    async def incr(self, key: str) -> int:
        self.incr_calls.append(key)
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)

    async def expire(self, key: str, seconds: int) -> None:
        self.expire_calls.append((key, seconds))

    async def eval(self, script: str, key_count: int, key: str, seconds: str) -> int:
        self.eval_calls.append((script, key_count, key, seconds))
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


class FakeStore:
    def __init__(self, client: FakeClient) -> None:
        self.client = client


class DisconnectedStore:
    client = None


class FakeSettings:
    def __init__(self, rate_limit_per_minute: int = 5, *, fail_open: bool = False) -> None:
        self.rate_limit_per_minute = rate_limit_per_minute
        self.rate_limit_fail_open = fail_open


def build_state(*, store: FakeStore | None, settings: FakeSettings | None) -> State:
    test_state = State()
    test_state.job_store = store
    test_state.settings = settings
    return test_state


@pytest.mark.asyncio
async def test_anonymous_passthrough_without_state() -> None:
    state = build_state(store=None, settings=None)
    assert await rate_limit("anonymous", state) == "anonymous"


@pytest.mark.asyncio
async def test_missing_job_store_fails_closed_503() -> None:
    from app.ratelimit import RateLimitUnavailable

    state = build_state(store=None, settings=FakeSettings(5))
    with pytest.raises(RateLimitUnavailable):
        await rate_limit("key-1", state)


@pytest.mark.asyncio
async def test_disconnected_job_store_fails_closed_503() -> None:
    from app.ratelimit import RateLimitUnavailable

    state = build_state(store=DisconnectedStore(), settings=FakeSettings(5))
    with pytest.raises(RateLimitUnavailable):
        await rate_limit("key-1", state)


@pytest.mark.asyncio
@pytest.mark.parametrize("store", [None, DisconnectedStore()])
async def test_fail_open_rate_limit_bypass_is_observable(store) -> None:
    from app.observability import RATE_LIMIT_UNAVAILABLE

    before = RATE_LIMIT_UNAVAILABLE._value.get()
    state = build_state(store=store, settings=FakeSettings(5, fail_open=True))

    assert await rate_limit("key-1", state) == "key-1"
    assert RATE_LIMIT_UNAVAILABLE._value.get() == before + 1


@pytest.mark.asyncio
async def test_missing_settings_fails_closed_503() -> None:
    from app.ratelimit import RateLimitUnavailable

    store = FakeStore(FakeClient())
    state = build_state(store=store, settings=None)
    with pytest.raises(RateLimitUnavailable):
        await rate_limit("key-1", state)
    assert store.client.incr_calls == []


@pytest.mark.asyncio
async def test_zero_limit_disables_ratelimit() -> None:
    client = FakeClient()
    store = FakeStore(client)
    state = build_state(store=store, settings=FakeSettings(0))
    assert await rate_limit("key-1", state) == "key-1"
    assert client.incr_calls == []


@pytest.mark.asyncio
async def test_within_limit_returns_key_and_sets_expiry_on_first_use() -> None:
    client = FakeClient(responses=[1, 2])
    store = FakeStore(client)
    state = build_state(store=store, settings=FakeSettings(5))
    assert await rate_limit("key-1", state) == "key-1"
    assert await rate_limit("key-1", state) == "key-1"
    bucket = minute_bucket()
    import hashlib

    digest = hashlib.sha256(b"key-1").hexdigest()[:32]
    expected = f"redax:rl:{digest}:{bucket}"
    assert [call[2:] for call in client.eval_calls] == [(expected, "60"), (expected, "60")]
    assert client.expire_calls == []


@pytest.mark.asyncio
async def test_over_limit_raises_429() -> None:
    client = FakeClient(responses=[6])
    store = FakeStore(client)
    state = build_state(store=store, settings=FakeSettings(5))
    with pytest.raises(HTTPException) as exc_info:
        await rate_limit("key-1", state)
    assert exc_info.value.status_code == 429
    assert exc_info.value.headers is not None
    assert int(exc_info.value.headers["Retry-After"]) >= 1
    assert exc_info.value.headers["X-RateLimit-Limit"] == "5"
    assert exc_info.value.headers["X-RateLimit-Remaining"] == "0"


@pytest.mark.asyncio
async def test_redis_down_fails_closed_503() -> None:
    from app.ratelimit import RateLimitUnavailable

    client = FakeClient(error=ConnectionRefusedError("redis down"))
    store = FakeStore(client)
    state = build_state(store=store, settings=FakeSettings(5))
    with pytest.raises(RateLimitUnavailable):
        await rate_limit("key-1", state)


@pytest.mark.asyncio
async def test_bucket_rotates_across_minute_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient(responses=[1, 1])
    store = FakeStore(client)
    state = build_state(store=store, settings=FakeSettings(5))
    base = 1_700_000_000
    monkeypatch.setattr(ratelimit_mod.time, "time", lambda: base)
    await rate_limit("key-1", state)
    monkeypatch.setattr(ratelimit_mod.time, "time", lambda: base + 60)
    await rate_limit("key-1", state)
    import hashlib

    digest = hashlib.sha256(b"key-1").hexdigest()[:32]
    assert [call[2] for call in client.eval_calls] == [
        f"redax:rl:{digest}:28333333",
        f"redax:rl:{digest}:28333334",
    ]


def testminute_bucket_floors_to_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ratelimit_mod.time, "time", lambda: 90)
    assert minute_bucket() == 1
