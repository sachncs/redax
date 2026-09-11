"""Per-API-key fixed-window rate limit."""

from __future__ import annotations

import time

from fastapi import HTTPException

from app.errors import TRANSIENT_EXC
from app.state import State


class RateLimitUnavailable(RuntimeError):
    """Raised when the rate limiter cannot reach Redis or its backing config is missing.

    The global error handler in :mod:`app.errors` translates this
    exception to a typed RFC 7807 ``503 rate-limit-unavailable`` problem.
    Tests can also ``pytest.raises(RateLimitUnavailable)`` to assert the
    specific failure mode.
    """


async def rate_limit(api_key: str, state: State) -> str:
    """Enforce the per-API-key fixed-window rate limit.

    Returns the ``api_key`` when the request is allowed; raises 429 when
    the window is over the limit. Fails CLOSED by default: an
    authenticated key cannot bypass the limiter when Redis is
    unavailable (raises :class:`RateLimitUnavailable`). Set
    ``REDAX_RATE_LIMIT_FAIL_OPEN=true`` to log a warning and let the
    request through instead. A disabled limit
    (``rate_limit_per_minute <= 0``) short-circuits without touching
    Redis.

    Args:
        api_key: The authenticated API key (or ``"anonymous"`` for
            unauthenticated probes; these are passed through).
        state: The per-app ``State`` injected by the caller.

    Returns:
        The ``api_key`` when the request is allowed.

    Raises:
        HTTPException: 429 if the per-minute limit is exceeded.
        RateLimitUnavailable: If the limiter is misconfigured or Redis
            is unreachable and fail-open is disabled.
    """
    if api_key == "anonymous":
        return api_key
    settings = state.settings
    if settings is None:
        raise RateLimitUnavailable()
    fail_open = bool(getattr(settings, "rate_limit_fail_open", False))
    limit = getattr(settings, "rate_limit_per_minute", 0)
    if limit <= 0:
        return api_key
    job_store = state.job_store
    if job_store is None:
        if fail_open:
            return api_key
        raise RateLimitUnavailable()
    bucket = f"redax:rl:{api_key}:{minute_bucket()}"
    client = job_store.client
    try:
        count = await client.incr(bucket)
        if count == 1:
            await client.expire(bucket, 60)
        if int(count) > limit:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
    except HTTPException:
        raise
    except (OSError, TimeoutError) as exc:
        from app.logging import get_logger

        get_logger("redax.ratelimit").warning(
            "redax.ratelimit_unavailable", error=exc.__class__.__name__
        )
        if fail_open:
            return api_key
        raise RateLimitUnavailable() from exc
    return api_key


def minute_bucket() -> int:
    """Return the current minute as an integer (seconds since epoch // 60).

    Used as the Redis bucket key suffix so each minute is its own
    counter. The bucketing is monotonic: every call within the same
    wall-clock minute returns the same value regardless of when in the
    minute it fires.
    """
    return int(time.time() // 60)
