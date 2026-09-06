"""Cache-key derivation for /v1/redact responses and idempotency."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def redaction_cache_payload(
    text: str,
    policy: dict[str, Any] | None,
    entity_types: list[str] | None,
    hash_salt: str,
    shared: bool = False,
) -> dict[str, Any]:
    """Build the canonical cache identity for a redaction request.

    The hash salt is part of the identity unless the cache is explicitly
    shared: the salt seeds the hash strategy, so cross-tenant responses
    must stay isolated unless ``cache_shared`` opts into sharing them.

    Args:
        text: The input text.
        policy: The resolved policy mapping (or ``None`` for no policy).
        entity_types: The list of entity types passed to the detector.
        hash_salt: The salt to seed the cache hash with.
        shared: If ``True``, the salt is omitted so per-tenant identity
            becomes cross-tenant.

    Returns:
        A dict that hashes deterministically via ``redaction_cache_key``.
    """
    payload: dict[str, Any] = {
        "text": text,
        "policy": policy or {},
        "entity_types": entity_types or [],
    }
    if not shared:
        payload["salt"] = hash_salt or ""
    return payload


def redaction_cache_key(payload: dict[str, Any]) -> str:
    """Compute a SHA-256 hex digest of the canonical cache identity.

    Args:
        payload: A dict produced by ``redaction_cache_payload``.

    Returns:
        The 64-character hex digest.
    """
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
