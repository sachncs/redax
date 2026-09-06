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
    """Canonical cache identity for a redaction request.

    The hash salt is part of the identity unless the cache is explicitly
    shared: the salt seeds the hash strategy, so cross-tenant responses
    must stay isolated unless cache_shared opts into sharing them.
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
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
