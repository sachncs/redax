"""Prometheus metrics for the redax FastAPI app."""

from __future__ import annotations

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
