"""Prometheus metrics for the redax FastAPI app."""

from __future__ import annotations

import time

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry()

REQUESTS = Counter(
    "redax_requests_total",
    "Total HTTP requests handled.",
    labelnames=("endpoint", "method", "status"),
    registry=REGISTRY,
)

REQUEST_LATENCY = Histogram(
    "redax_request_duration_seconds",
    "End-to-end request handling latency.",
    labelnames=("endpoint", "method"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)

INFERENCE_LATENCY = Histogram(
    "redax_inference_duration_seconds",
    "Time spent in detector inference for a single detect() call.",
    labelnames=("detector",),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
    registry=REGISTRY,
)

ENTITIES_DETECTED = Counter(
    "redax_entities_detected_total",
    "Total PII entities detected.",
    labelnames=("entity_type", "strategy"),
    registry=REGISTRY,
)

CACHE_HITS = Counter(
    "redax_cache_hits_total",
    "Cache hits (idempotency or response cache).",
    labelnames=("cache",),
    registry=REGISTRY,
)

ERRORS = Counter(
    "redax_errors_total",
    "Total errors by type.",
    labelnames=("type",),
    registry=REGISTRY,
)

QUEUE_DEPTH = Gauge(
    "redax_queue_depth",
    "Current depth of the async job queue.",
    registry=REGISTRY,
)

AUDIT_UNINITIALISED = Counter(
    "redax_audit_uninitialised_total",
    "Audit events dropped because the backend was never started.",
    labelnames=("backend",),
    registry=REGISTRY,
)

AUDIT_WRITE_FAILED = Counter(
    "redax_audit_write_failed_total",
    "Audit events that could not be written to disk.",
    labelnames=("backend",),
    registry=REGISTRY,
)

RATE_LIMIT_UNAVAILABLE = Counter(
    "redax_rate_limit_unavailable_total",
    "Rate-limit checks that failed closed because Redis was unreachable.",
    registry=REGISTRY,
)

AUDIT_DROPPED = Counter(
    "redax_audit_dropped_total",
    "Audit events dropped because the in-process queue was full.",
    labelnames=("backend",),
    registry=REGISTRY,
)


def queue_depth() -> float:
    """Read the current ``QUEUE_DEPTH`` gauge.

    Returns:
        The current in-flight job count. Defaults to 0.0 if the gauge
        has no samples yet.
    """
    for metric in QUEUE_DEPTH.collect():
        for sample in metric.samples:
            return float(sample.value)
    return 0.0


class RequestMetric:
    """Context manager that wraps the per-request metrics boilerplate.

    Each ``/v1/*`` route previously opened with the same five-line
    pattern (``start = time.perf_counter()``; declare ``endpoint`` /
    ``method``; increment ``REQUESTS`` in every branch; observe
    ``REQUEST_LATENCY`` in a ``finally``). ``RequestMetric`` collapses
    the boilerplate so new routes can adopt it with one ``with``
    block and a single ``record(status)`` call per branch.

    Use as::

        timed = RequestMetric("POST /v1/redact")
        try:
            ...return ... record("200")
        except TimeoutError:
            ...record("504")
        except TRANSIENT_EXC:
            ...record("500")
    """

    def __init__(self, endpoint: str, method: str = "POST") -> None:
        self.endpoint = endpoint
        self.method = method
        self.start = time.perf_counter()

    def record(self, status: str) -> None:
        """Increment REQUESTS for the given status; observed in __exit__."""
        REQUESTS.labels(endpoint=self.endpoint, method=self.method, status=status).inc()

    def __enter__(self) -> RequestMetric:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        REQUEST_LATENCY.labels(endpoint=self.endpoint, method=self.method).observe(
            time.perf_counter() - self.start
        )
