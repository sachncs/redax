"""OpenTelemetry tracing configuration."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

OTLP_MAX_QUEUE_SIZE = 2_048
OTLP_MAX_EXPORT_BATCH_SIZE = 512
OTLP_SCHEDULE_DELAY_MILLIS = 5_000.0
OTLP_EXPORT_TIMEOUT_MILLIS = 30_000.0


class Tracing:
    """Process-wide OpenTelemetry tracer configuration.

    Holds the ``initialized`` flag as an instance attribute so the
    idempotency check has no module-level mutable state.

    Attributes:
        initialized: ``True`` once ``configure`` has installed a provider
            on the global tracer registry.
    """

    initialized: bool = False

    def configure(self, service_name: str, otlp_endpoint: str | None = None) -> trace.Tracer:
        """Configure the process-wide OpenTelemetry tracer.

        Idempotent: subsequent calls only return the existing tracer
        without reconfiguring the provider.

        Args:
            service_name: The ``service.name`` resource attribute attached
                to every emitted span.
            otlp_endpoint: Optional gRPC OTLP endpoint URL. If provided, a
                ``BatchSpanProcessor`` is wired to push spans there. If
                ``None``, spans are recorded in-memory only.

        Returns:
            The OpenTelemetry ``Tracer`` bound to ``service_name``.
        """
        if not Tracing.initialized:
            resource = Resource.create({"service.name": service_name})
            provider = TracerProvider(resource=resource)
            if otlp_endpoint:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                    OTLPSpanExporter,
                )

                provider.add_span_processor(
                    BatchSpanProcessor(
                        OTLPSpanExporter(endpoint=otlp_endpoint),
                        max_queue_size=OTLP_MAX_QUEUE_SIZE,
                        max_export_batch_size=OTLP_MAX_EXPORT_BATCH_SIZE,
                        schedule_delay_millis=OTLP_SCHEDULE_DELAY_MILLIS,
                        export_timeout_millis=OTLP_EXPORT_TIMEOUT_MILLIS,
                    )
                )
            trace.set_tracer_provider(provider)
            Tracing.initialized = True
        return trace.get_tracer(service_name)


def configure_tracing(service_name: str, otlp_endpoint: str | None = None) -> trace.Tracer:
    """Configure the process-wide OpenTelemetry tracer.

    Thin wrapper that delegates to :class:`Tracing` so existing callers do
    not need to know about the class. See :meth:`Tracing.configure` for
    semantics.

    Args:
        service_name: The ``service.name`` resource attribute attached to
            every emitted span.
        otlp_endpoint: Optional gRPC OTLP endpoint URL.

    Returns:
        The OpenTelemetry ``Tracer`` bound to ``service_name``.
    """
    return Tracing().configure(service_name, otlp_endpoint)


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


def flush_tracing(timeout_millis: int = 30_000) -> bool:
    """Flush buffered spans within a bounded shutdown budget.

    The SDK's proxy provider used when tracing is not configured has no
    flush operation, which is treated as a successful no-op. Exporter
    failures are reported as ``False`` so shutdown can log them without
    turning telemetry loss into an application crash.
    """
    provider = trace.get_tracer_provider()
    force_flush = getattr(provider, "force_flush", None)
    if not callable(force_flush):
        return True
    try:
        return bool(force_flush(timeout_millis))
    except (RuntimeError, TimeoutError, TypeError, ValueError):
        return False
