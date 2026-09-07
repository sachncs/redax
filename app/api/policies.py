"""Policy-list endpoint (``GET /v1/policies``).

Returns the name, version, description, and field map of every policy
loaded from the configured ``policies_dir``. Read-only; never mutates
state.
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI

from app.auth import require_api_key
from app.logging import get_logger
from app.observability import REQUEST_LATENCY, REQUESTS
from app.redaction.policies import list_policies
from app.state import State, get_state


def register(app: FastAPI) -> None:
    router = APIRouter()

    @router.get("/v1/policies")
    def policies(
        state: Annotated[State, Depends(get_state)],
        api_key: Annotated[str, Depends(require_api_key)],
    ) -> dict[str, Any]:
        start = time.perf_counter()
        endpoint = "GET /v1/policies"
        method = "GET"
        try:
            settings = state.settings
            policies_dir = getattr(settings, "policies_dir", "./policies")
            loaded = list_policies(policies_dir)
            REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
            return {
                "policies": [
                    {
                        "name": p.name,
                        "version": p.version,
                        "description": p.description,
                        "fields": list(p.fields.keys()),
                    }
                    for p in loaded
                ]
            }
        except (OSError, ValueError, RuntimeError) as exc:
            REQUESTS.labels(endpoint=endpoint, method=method, status="500").inc()
            get_logger("redax.api").error("redax.policies_failed", error=exc.__class__.__name__)
            raise
        finally:
            REQUEST_LATENCY.labels(endpoint=endpoint, method=method).observe(
                time.perf_counter() - start
            )

    app.include_router(router)
