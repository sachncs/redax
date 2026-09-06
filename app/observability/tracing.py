"""OpenTelemetry tracing configuration."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_initialized = False


def configure_tracing(service_name: str, otlp_endpoint: str | None = None) -> trace.Tracer:
    """Configure the process-wide OpenTelemetry tracer.

    Idempotent: subsequent calls only return the existing tracer without
    reconfiguring the provider.

    Args:
        service_name: The ``service.name`` resource attribute attached to
            every emitted span.
        otlp_endpoint: Optional gRPC OTLP endpoint URL. If provided, a
            ``BatchSpanProcessor`` is wired to push spans there. If
            ``None``, spans are recorded in-memory only.

    Returns:
        The OpenTelemetry ``Tracer`` bound to ``service_name``.
    """
    global _initialized
    if not _initialized:
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        if otlp_endpoint:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
            )
        trace.set_tracer_provider(provider)
        _initialized = True
    return trace.get_tracer(service_name)


def current_trace_id_hex() -> str | None:
    """Return the current span's trace ID as a 32-char hex string.

    Returns:
        The trace ID if the current context has a valid span, else
        ``None``.
    """
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if not ctx.is_valid:
        return None
    return format(ctx.trace_id, "032x")