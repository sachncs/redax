from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given

from app.api.cache import redaction_cache_key, redaction_cache_payload
from app.api.idempotency import complete, release, reserve
from app.api.redact import idempotency_storage_key


class FakeIdempotencyRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int, nx: bool = False) -> bool | None:
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    async def eval(self, script: str, key_count: int, *args: str) -> int:
        if key_count == 2:
            lock_key, result_key, token, envelope, _ttl = args
            if self.values.get(lock_key) != token:
                return 0
            self.values[result_key] = envelope
            del self.values[lock_key]
            return 1
        lock_key, token = args
        if self.values.get(lock_key) != token:
            return 0
        del self.values[lock_key]
        return 1


_TEXT = st.text(st.characters(blacklist_categories=["Cs", "Cc"]), min_size=1, max_size=60)


@given(_TEXT, st.dictionaries(st.text(max_size=8), st.text(max_size=8), max_size=4))
def test_key_is_a_stable_hash_of_the_payload(text: str, policy: dict[str, str]) -> None:
    payload = redaction_cache_payload(text, policy, [], "salt-1")
    key = redaction_cache_key(payload)
    assert key == redaction_cache_key(redaction_cache_payload(text, policy, [], "salt-1"))
    assert len(key) == 64
    assert key != redaction_cache_key(redaction_cache_payload(text + "!", policy, [], "salt-1"))


def test_idempotency_storage_key_does_not_include_header_value() -> None:
    key = idempotency_storage_key("redax", "email=alice@example.com")
    assert "alice@example.com" not in key
    assert key.startswith("redax:idem:")


async def test_idempotency_reservation_is_atomic_and_fingerprint_bound() -> None:
    client = FakeIdempotencyRedis()
    storage_key = "redax:idem:abc"

    first = await reserve(client, storage_key, "fingerprint-a", 60)
    assert first.status == "acquired"
    assert first.token is not None

    waiting = await reserve(client, storage_key, "fingerprint-a", 60)
    assert waiting.status == "in_progress"

    conflict = await reserve(client, storage_key, "fingerprint-b", 60)
    assert conflict.status == "in_progress"

    assert await complete(
        client,
        storage_key,
        "fingerprint-a",
        first.token,
        {"text": "safe"},
        60,
    )
    replay = await reserve(client, storage_key, "fingerprint-a", 60)
    assert replay.status == "completed"
    assert replay.response == {"text": "safe"}

    mismatch = await reserve(client, storage_key, "fingerprint-b", 60)
    assert mismatch.status == "conflict"


async def test_idempotency_release_cannot_delete_a_new_owner() -> None:
    client = FakeIdempotencyRedis()
    storage_key = "redax:idem:abc"
    first = await reserve(client, storage_key, "fingerprint-a", 60)
    assert first.token is not None
    assert not await release(client, storage_key, "wrong-token")
    assert (await reserve(client, storage_key, "fingerprint-a", 60)).status == "in_progress"
    assert await release(client, storage_key, first.token)
    assert (await reserve(client, storage_key, "fingerprint-a", 60)).status == "acquired"


@given(_TEXT, st.text(min_size=1, max_size=16))
def test_default_cache_is_isolated_per_salt(text: str, salt: str) -> None:
    assert redaction_cache_key(
        redaction_cache_payload(text, None, None, "a")
    ) != redaction_cache_key(redaction_cache_payload(text, None, None, "b"))


@given(_TEXT, st.text(min_size=1, max_size=16))
def test_shared_cache_key_ignores_salt(text: str, salt: str) -> None:
    a = redaction_cache_key(redaction_cache_payload(text, None, None, salt, shared=True))
    b = redaction_cache_key(redaction_cache_payload(text, None, None, "other", shared=True))
    assert a == b


@given(_TEXT)
def test_shared_and_isolated_keys_differ(text: str) -> None:
    isolated = redaction_cache_payload(text, None, None, "s")
    shared = redaction_cache_payload(text, None, None, "s", shared=True)
    assert redaction_cache_key(isolated) != redaction_cache_key(shared)
