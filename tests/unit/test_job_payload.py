from __future__ import annotations

import pytest

from app.jobs.payload import JobPayloadCipher

KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="  # 32 zero bytes, base64 encoded


def test_encrypted_payload_does_not_contain_original_text() -> None:
    payload = {"text": "alice@example.com", "policy": None, "entity_types": None}
    envelope = JobPayloadCipher(KEY).encode(payload)

    assert envelope != payload
    assert "alice@example.com" not in repr(envelope)
    assert JobPayloadCipher(KEY).decode(envelope) == payload


def test_tampered_encrypted_payload_is_rejected() -> None:
    envelope = JobPayloadCipher(KEY).encode({"text": "sensitive"})
    assert isinstance(envelope, dict)
    envelope["encrypted"] = envelope["encrypted"][:-1] + "A"

    with pytest.raises(ValueError, match="invalid job payload"):
        JobPayloadCipher(KEY).decode(envelope)


def test_empty_key_preserves_local_development_behavior() -> None:
    payload = {"text": "local-only"}
    assert JobPayloadCipher().encode(payload) == payload
    assert JobPayloadCipher().decode(payload) == payload
