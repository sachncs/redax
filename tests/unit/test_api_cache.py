from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given

from app.api.cache import redaction_cache_key, redaction_cache_payload

_TEXT = st.text(st.characters(blacklist_categories=["Cs", "Cc"]), min_size=1, max_size=60)


@given(_TEXT, st.dictionaries(st.text(max_size=8), st.text(max_size=8), max_size=4))
def test_key_is_a_stable_hash_of_the_payload(text: str, policy: dict[str, str]) -> None:
    payload = redaction_cache_payload(text, policy, [], "salt-1")
    key = redaction_cache_key(payload)
    assert key == redaction_cache_key(redaction_cache_payload(text, policy, [], "salt-1"))
    assert len(key) == 64
    assert key != redaction_cache_key(redaction_cache_payload(text + "!", policy, [], "salt-1"))


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
