from __future__ import annotations

from importlib import import_module

import pytest

from app.observability import tracing


def test_otlp_exporter_uses_bounded_batch_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeExporter:
        def __init__(self, *, endpoint: str) -> None:
            captured["endpoint"] = endpoint

    class FakeProcessor:
        def __init__(self, exporter: object, **kwargs: object) -> None:
            captured["exporter"] = exporter
            captured.update(kwargs)

        def shutdown(self) -> None:
            return None

        def force_flush(self, timeout_millis: int = 30_000) -> bool:
            del timeout_millis
            return True

    exporter_module = import_module("opentelemetry.exporter.otlp.proto.grpc.trace_exporter")
    monkeypatch.setattr(exporter_module, "OTLPSpanExporter", FakeExporter)
    monkeypatch.setattr(tracing, "BatchSpanProcessor", FakeProcessor)
    monkeypatch.setattr(tracing.trace, "set_tracer_provider", lambda _provider: None)
    monkeypatch.setattr(tracing.Tracing, "initialized", False)

    tracing.Tracing().configure("redax-test", "https://collector.example.test:4317")

    assert captured["endpoint"] == "https://collector.example.test:4317"
    assert captured["max_queue_size"] == tracing.OTLP_MAX_QUEUE_SIZE
    assert captured["max_export_batch_size"] == tracing.OTLP_MAX_EXPORT_BATCH_SIZE
    assert captured["schedule_delay_millis"] == tracing.OTLP_SCHEDULE_DELAY_MILLIS
    assert captured["export_timeout_millis"] == tracing.OTLP_EXPORT_TIMEOUT_MILLIS
