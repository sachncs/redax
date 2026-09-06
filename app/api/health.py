"""Health, readiness, and Prometheus scrape endpoints.

Exposes ``GET /healthz`` (liveness), ``GET /readyz`` (readiness, gated on
``model_state.ready`` and a non-null redactor), and ``GET /metrics``
(Prometheus exposition). None of these endpoints appear in the OpenAPI
schema and they are not API-key-gated.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.errors import problem_response
from app.observability import REQUEST_LATENCY, REQUESTS


def register(app: FastAPI) -> None:
    """Attach the health, readiness, and metrics routes to ``app``.

    Args:
        app: The FastAPI application to mutate.
    """
    from app.observability import REGISTRY
    from app.state import model_state

    @app.get("/healthz", include_in_schema=False)
    def healthz(request: Request) -> dict[str, str]:
        """Liveness probe; returns ``{"status": "ok"}`` if the process is alive.

        Args:
            request: The active Starlette request, used for problem
                formatting if needed.

        Returns:
            A dict with a single ``status`` key.
        """
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
        """Readiness probe; 200 once ``model_state.ready`` and the redactor are set.

        Args:
            request: The active Starlette request, used for problem
                formatting on the failure path.

        Returns:
            ``{"status": "ready"}`` on success or a 503 problem response.
        """
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
        """Prometheus exposition over the in-process metric registry.

        Args:
            request: The active Starlette request, used only for timing.

        Returns:
            A plain ``Response`` carrying the rendered metrics payload and
            the Prometheus content-type.
        """
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
