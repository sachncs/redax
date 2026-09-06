from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException


def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> str:
    """Validate the X-API-Key header against REDAX_API_KEYS.

    Returns the matched key. Raises HTTPException (RFC 7807 via the global
    handler) when the header is missing or invalid. Disabled (returns a
    sentinel "anonymous") when REDAX_API_KEYS is empty.

    model_state is resolved at call time (matching every handler module) so
    rebinding app.state.model_state in tests is observed here too.
    """
    from app.state import model_state

    settings = model_state.settings
    if settings is None:
        return "anonymous"
    valid = settings.api_key_set()
    if not valid:
        return "anonymous"
    if x_api_key is None or x_api_key not in valid:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return x_api_key


__all__ = ["Depends", "require_api_key"]
