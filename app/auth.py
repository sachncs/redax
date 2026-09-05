from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header

from app.errors import unauthorized


def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> str:
    """Validate the X-API-Key header against REDAX_API_KEYS.

    Returns the matched key. Raises an RFC 7807 unauthorized response
    when the header is missing or invalid. Disabled (always returns a
    sentinel "anonymous") when REDAX_API_KEYS is empty.
    """
    from app.state import model_state  # noqa: PLC0415

    settings = model_state.settings
    if settings is None:
        return "anonymous"
    valid = settings.api_key_set()
    if not valid:
        return "anonymous"
    if x_api_key is None or x_api_key not in valid:
        raise unauthorized(detail="Invalid or missing API key") from None
    return x_api_key


def require_jwt(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """Validate a Bearer JWT against REDAX_JWT_SECRET (HS256).

    Disabled when REDAX_JWT_SECRET is None.
    """
    from app.state import model_state  # noqa: PLC0415

    settings = model_state.settings
    if settings is None or settings.jwt_secret is None:
        return "anonymous"
    if authorization is None or not authorization.startswith("Bearer "):
        raise unauthorized(detail="Missing bearer token") from None
    token = authorization[len("Bearer ") :]
    try:
        import jwt  # type: ignore[import-not-found]

        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except Exception as exc:  # noqa: BLE001
        raise unauthorized(detail=f"invalid token: {exc}") from None
    return str(payload.get("sub", "anonymous"))


__all__ = ["require_api_key", "require_jwt", "Depends"]  # noqa: F401
