"""Encryption boundary for payloads serialized into the durable job queue."""

from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class JobPayloadCipher:
    """Encrypt job payloads before ARQ serializes them into Redis."""

    def __init__(self, key: str = "") -> None:
        self.fernet = Fernet(key.encode("ascii")) if key else None

    def encode(self, payload: dict[str, Any]) -> dict[str, str] | dict[str, Any]:
        """Return an encrypted envelope, or the original payload in dev mode."""
        if self.fernet is None:
            return payload
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return {"encrypted": self.fernet.encrypt(serialized.encode("utf-8")).decode("ascii")}

    def decode(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Decrypt an envelope and reject malformed or tampered queue data."""
        token = payload.get("encrypted")
        if token is None:
            if self.fernet is not None:
                raise ValueError("unencrypted job payload")
            return payload
        if not isinstance(token, str) or self.fernet is None:
            raise ValueError("invalid job payload envelope")
        try:
            decoded = json.loads(self.fernet.decrypt(token.encode("ascii")))
        except (InvalidToken, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("invalid job payload envelope") from exc
        if not isinstance(decoded, dict) or not isinstance(decoded.get("text"), str):
            raise ValueError("invalid job payload envelope")
        return decoded
