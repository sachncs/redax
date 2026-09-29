"""X-API-Key authentication dependency for FastAPI routes."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

from app.ratelimit import rate_limit
from app.state import State, get_state

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="Deployment API key; endpoint scopes are configured by REDAX_API_KEY_SCOPES.",
)


def principal_id(api_key: str, hash_salt: str) -> str:
    """Return a stable, non-secret identifier for an authenticated principal."""
    return hmac.new(
        hash_salt.encode("utf-8", errors="replace"),
        api_key.encode("utf-8", errors="replace"),
        hashlib.sha256,
    ).hexdigest()[:24]


def require_api_key(
    state: Annotated[State, Depends(get_state)],
    x_api_key: Annotated[str | None, Security(api_key_header)] = None,
) -> str:
    """Validate the X-API-Key header against ``REDAX_API_KEYS``.

    Returns the matched key. Raises HTTPException (RFC 7807 via the global
    handler) when the header is missing or invalid. Disabled (returns a
    sentinel ``"anonymous"``) when ``REDAX_API_KEYS`` is empty.

    State is resolved through FastAPI dependency injection so the typed
    container flows in via ``app.state.state`` rather than a module
    global.

    Args:
        state: The per-app ``State`` injected by FastAPI.
        x_api_key: The ``X-API-Key`` header value, populated by FastAPI.

    Returns:
        The matched API key, or ``"anonymous"`` if the limiter is
        disabled.

    Raises:
        HTTPException: 401 if the header is missing or invalid.
    """
    settings = state.settings
    if settings is None:
        return "anonymous"
    valid = settings.api_key_set()
    if not valid:
        return "anonymous"
    if x_api_key is None:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    matched = False
    for candidate in valid:
        # Evaluate every configured key so rotation order does not reveal
        # which key matched through an early return.
        if secrets.compare_digest(x_api_key, candidate):
            matched = True
    if not matched:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return x_api_key


async def require_api_key_and_rate_limit(
    state: Annotated[State, Depends(get_state)],
    x_api_key: Annotated[str | None, Security(api_key_header)] = None,
) -> str:
    """Combined auth + rate-limit dependency for v1/* routes.

    Validates the X-API-Key header and runs the per-minute rate limiter
    in one call so each route only declares a single dependency
    (``api_key: Annotated[str, Depends(require_api_key_and_rate_limit)]``)
    instead of repeating the auth + rate-limit pair verbatim.

    Args:
        state: The per-app ``State`` injected by FastAPI.
        x_api_key: The ``X-API-Key`` header value.

    Returns:
        The matched API key.
    """
    api_key = require_api_key(state, x_api_key)
    await rate_limit(api_key, state)
    return api_key


def require_scope(scope: str) -> Callable[..., Awaitable[str]]:
    """Return a dependency enforcing one optional principal scope.

    Existing deployments with no ``REDAX_API_KEY_SCOPES`` retain their
    authenticated-key behavior. Once scopes are configured, a principal must
    explicitly include the requested scope or receives 403.
    """

    async def dependency(
        state: Annotated[State, Depends(get_state)],
        api_key: Annotated[str, Depends(require_api_key)],
    ) -> str:
        settings = state.settings
        scope_map_factory = getattr(settings, "api_key_scope_map", None)
        scope_map = scope_map_factory() if callable(scope_map_factory) else {}
        if scope_map and scope not in scope_map.get(api_key, set()):
            raise HTTPException(status_code=403, detail="API key lacks required scope")
        return api_key

    return dependency


__all__ = ["principal_id", "require_api_key", "require_api_key_and_rate_limit", "require_scope"]
