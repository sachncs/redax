from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.errors import problem_response


def register(app: FastAPI) -> None:
    from app.observability import REGISTRY
    from app.state import model_state

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False, response_model=None)
    def readyz(request: Request) -> dict[str, str] | JSONResponse:
        if model_state.ready and getattr(model_state, "redactor", None) is not None:
            return {"status": "ready"}
        return problem_response(
            request,
            type="https://redax.ai/errors/not-ready",
            title="Not ready",
            status=503,
            detail="Service has not finished initializing",
        )

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> tuple[bytes, int, dict[str, str]]:
        return generate_latest(REGISTRY), 200, {"content-type": CONTENT_TYPE_LATEST}
