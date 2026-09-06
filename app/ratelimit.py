from __future__ import annotations

import time

from fastapi import HTTPException

from app.state import model_state


async def rate_limit(api_key: str) -> str:
    """Redis-backed fixed-window rate limit per API key.

    Returns the key when allowed; raises 429 when over the limit. Fails
    CLOSED: an authenticated key cannot bypass the limiter when Redis is
    unavailable (503) or when settings are missing (503). A disabled limit
    (rate_limit_per_minute <= 0) short-circuits without touching Redis.
    """
    if api_key == "anonymous":
        return api_key
    settings = model_state.settings
    if settings is None:
        raise HTTPException(status_code=503, detail="Rate limiting unavailable")
    limit = settings.rate_limit_per_minute
    if limit <= 0:
        return api_key
    job_store = model_state.job_store
    if job_store is None:
        raise HTTPException(status_code=503, detail="Rate limiting unavailable")
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
    except Exception:
        raise HTTPException(status_code=503, detail="Rate limiting unavailable") from None
    return api_key


def minute_bucket() -> int:
    return int(time.time() // 60)
