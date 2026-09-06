from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Request

from app.auth import require_api_key
from app.observability import REQUEST_LATENCY, REQUESTS
from app.redaction.policies import list_policies


def register(app: FastAPI) -> None:
    router = APIRouter()

    @router.get("/v1/policies")
    def policies(
        request: Request, api_key: Annotated[str, Depends(require_api_key)]
    ) -> dict[str, Any]:
        start = time.perf_counter()
        endpoint = "GET /v1/policies"
        method = "GET"
        try:
            from app.state import model_state

            settings = model_state.settings
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
        except Exception:
            REQUESTS.labels(endpoint=endpoint, method=method, status="500").inc()
            raise
        finally:
            REQUEST_LATENCY.labels(endpoint=endpoint, method=method).observe(
                time.perf_counter() - start
            )

    app.include_router(router)
