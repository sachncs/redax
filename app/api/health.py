"""Health, readiness, and Prometheus scrape endpoints.

Exposes ``GET /healthz`` (liveness), ``GET /readyz`` (readiness, gated on
``state.ready`` and a non-null redactor), ``GET /v1/stats`` (pipeline +
breaker introspection, API-key-gated), and ``GET /metrics`` (Prometheus
exposition). ``/healthz``, ``/readyz`` and ``/metrics`` are not API-key
gated and are excluded from the OpenAPI schema; ``/v1/stats`` requires
the same key as the rest of the v1 surface.
"""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.auth import require_scope
from app.errors import problem_response
from app.observability import REQUEST_LATENCY, REQUESTS
from app.state import State, get_state


def register(app: FastAPI) -> None:
    """Attach the health, readiness, stats, and metrics routes to ``app``.

    Args:
        app: The FastAPI application to mutate.
    """
    from app.observability import REGISTRY

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        """Liveness probe; returns ``{"status": "ok"}`` if the process is alive."""
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
    async def readyz(
        request: Request,
        state: Annotated[State, Depends(get_state)],
    ) -> dict[str, str] | JSONResponse:
        """Readiness probe; 200 once ``state.ready`` and the redactor are set.

        Args:
            request: The active Starlette request, used for problem
                formatting on the failure path.
            state: The per-app ``State`` injected by FastAPI.

        Returns:
            ``{"status": "ready"}`` on success or a 503 problem response.
        """
        start = time.perf_counter()
        endpoint = "GET /readyz"
        method = "GET"
        try:
            settings = state.settings
            redis_required = bool(getattr(settings, "redis_required", False))
            redis_ready = True
            if redis_required:
                redis_ready = state.job_store is not None and state.job_queue is not None
                client = getattr(state.job_store, "client", None)
                ping = getattr(client, "ping", None)
                if redis_ready and callable(ping):
                    try:
                        timeout_seconds = max(
                            0.1,
                            float(getattr(settings, "redis_socket_timeout_seconds", 1.0)),
                        )
                        async with asyncio.timeout(timeout_seconds):
                            await ping()
                    except (OSError, RuntimeError, TimeoutError):
                        redis_ready = False
                elif redis_ready:
                    redis_ready = False
            if state.ready and getattr(state, "redactor", None) is not None and redis_ready:
                REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
                return {"status": "ready"}
            REQUESTS.labels(endpoint=endpoint, method=method, status="503").inc()
            return problem_response(
                request,
                type="https://redax.ai/errors/not-ready",
                title="Not ready",
                status=503,
                detail=(
                    "Required dependencies are not ready"
                    if redis_required and not redis_ready
                    else "Service has not finished initializing"
                ),
            )
        finally:
            REQUEST_LATENCY.labels(endpoint=endpoint, method=method).observe(
                time.perf_counter() - start
            )

    @app.get("/v1/stats", response_model=None)
    def stats(
        state: Annotated[State, Depends(get_state)],
        api_key: Annotated[str, Depends(require_scope("metrics:read"))],
    ) -> dict[str, Any]:
        """Introspection endpoint for operators and dashboards.

        Returns the redactor name, the active detector, the audit backend
        name, the optional pipeline's stats, and the breaker state. The
        payload is JSON-serialisable so it can be scraped by anything
        that speaks HTTP.

        The endpoint is API-key-gated like the other ``/v1`` routes.
        """
        start = time.perf_counter()
        endpoint = "GET /v1/stats"
        method = "GET"
        try:
            payload: dict[str, Any] = {
                "ready": state.ready,
                "redactor": getattr(state.redactor, "replacement", None),
                "detector": getattr(getattr(state, "detector", None), "name", None),
                "regex_detector": getattr(getattr(state, "regex_detector", None), "name", None),
                "audit_backend": type(state.audit).__name__ if state.audit else None,
                "redis_enabled": state.job_store is not None,
            }
            if state.pipeline is not None:
                payload["pipeline"] = state.pipeline.stats()
            REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
            return payload
        finally:
            REQUEST_LATENCY.labels(endpoint=endpoint, method=method).observe(
                time.perf_counter() - start
            )

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        """Prometheus exposition over the in-process metric registry.

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
