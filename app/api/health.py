from __future__ import annotations

from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest


def register(app: FastAPI) -> None:
    from app.observability import REGISTRY
    from app.state import model_state

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz() -> tuple[dict[str, str], int]:
        if model_state.ready:
            return {"status": "ready"}, 200
        return {"status": "loading"}, 503

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> tuple[bytes, int, dict[str, str]]:
        return generate_latest(REGISTRY), 200, {"content-type": CONTENT_TYPE_LATEST}
