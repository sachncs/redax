from __future__ import annotations

from app.errors import rate_limited
from app.state import model_state


async def rate_limit(api_key: str) -> str:
    """Redis-backed fixed-window rate limit per API key.

    Returns the key when allowed; raises 429 otherwise. Disabled when
    JobStore is unavailable (degraded mode).
    """
    if api_key == "anonymous":
        return api_key
    job_store = getattr(model_state, "job_store", None)
    if job_store is None:
        return api_key
    settings = model_state.settings
    if settings is None:
        return api_key
    limit = settings.rate_limit_per_minute
    if limit <= 0:
        return api_key
    bucket = f"redax:rl:{api_key}:{_minute_bucket()}"
    client = job_store.client
    try:
        count = await client.incr(bucket)
        if count == 1:
            await client.expire(bucket, 60)
        if int(count) > limit:
            raise rate_limited(None, f"limit {limit}/min exceeded")  # type: ignore[arg-type]
    except Exception as exc:
        if hasattr(exc, "status_code"):
            raise
        return api_key
    return api_key


def _minute_bucket() -> int:
    import time

    return int(time.time() // 60)
