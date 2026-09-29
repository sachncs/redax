from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import grpc
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2, trace_service_pb2_grpc
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from app.observability.tracing import CountingSpanExporter


class TraceReceiver(trace_service_pb2_grpc.TraceServiceServicer):
    """Minimal OTLP receiver used to test the exporter wire contract."""

    def __init__(self) -> None:
        self.requests: list[trace_service_pb2.ExportTraceServiceRequest] = []
        self.received = Event()
        self.lock = Lock()

    def Export(self, request, context):
        del context
        with self.lock:
            self.requests.append(request)
        self.received.set()
        return trace_service_pb2.ExportTraceServiceResponse()


def test_otlp_exporter_delivers_metadata_only_span() -> None:
    receiver = TraceReceiver()
    server = grpc.server(ThreadPoolExecutor(max_workers=1))
    trace_service_pb2_grpc.add_TraceServiceServicer_to_server(receiver, server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()

    provider = TracerProvider()
    exporter = CountingSpanExporter(
        OTLPSpanExporter(endpoint=f"127.0.0.1:{port}", insecure=True, timeout=1)
    )
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        with provider.get_tracer("redax.test").start_as_current_span("redax.canary") as span:
            span.set_attribute("http.request.method", "POST")
            span.set_attribute("http.response.status_code", 200)
        assert provider.force_flush(1000)
        assert receiver.received.wait(timeout=2)
    finally:
        provider.shutdown()
        server.stop(grace=0)

    assert len(receiver.requests) == 1
    scope_spans = receiver.requests[0].resource_spans[0].scope_spans
    span = scope_spans[0].spans[0]
    assert span.name == "redax.canary"
    assert {attribute.key for attribute in span.attributes} == {
        "http.request.method",
        "http.response.status_code",
    }
    assert "sensitive.canary@example.com" not in str(receiver.requests[0])
