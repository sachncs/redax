from __future__ import annotations

import time

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.errors import problem_response
from app.observability import REQUEST_LATENCY, REQUESTS


def register(app: FastAPI) -> None:
    from app.observability import REGISTRY
    from app.state import model_state

    @app.get("/healthz", include_in_schema=False)
    def healthz(request: Request) -> dict[str, str]:
        start = time.perf_counter()
        endpoint = "GET /healthz"
        method = "GET"
        try:
            REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
            return {"status": "ok"}
        finally:
            REQUEST_LATENCY.labels(endpoint=endpoint, method=method).observe(
                time.perf_counter() - start
            )

    @app.get("/readyz", include_in_schema=False, response_model=None)
    def readyz(request: Request) -> dict[str, str] | JSONResponse:
        start = time.perf_counter()
        endpoint = "GET /readyz"
        method = "GET"
        try:
            if model_state.ready and getattr(model_state, "redactor", None) is not None:
                REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
                return {"status": "ready"}
            REQUESTS.labels(endpoint=endpoint, method=method, status="503").inc()
            return problem_response(
                request,
                type="https://redax.ai/errors/not-ready",
                title="Not ready",
                status=503,
                detail="Service has not finished initializing",
            )
        finally:
            REQUEST_LATENCY.labels(endpoint=endpoint, method=method).observe(
                time.perf_counter() - start
            )

    @app.get("/metrics", include_in_schema=False)
    def metrics(request: Request) -> Response:
        start = time.perf_counter()
        endpoint = "GET /metrics"
        method = "GET"
        try:
            REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
            return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
        finally:
            REQUEST_LATENCY.labels(endpoint=endpoint, method=method).observe(
                time.perf_counter() - start
            )
