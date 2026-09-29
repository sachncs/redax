from __future__ import annotations

import asyncio

import pytest
import structlog
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.middleware import register_request_context


def make_app_with_probe(seen: dict) -> FastAPI:
    app = FastAPI()

    @app.get("/probe")
    def probe(request: Request) -> dict[str, bool]:
        ctx = structlog.contextvars.get_contextvars()
        seen["bound"] = ctx.get("request_id")
        return {"ok": True}

    register_request_context(app)
    return app


def test_request_context_echoes_client_request_id() -> None:
    seen: dict = {}
    app = make_app_with_probe(seen)
    with TestClient(app) as client:
        resp = client.get("/probe", headers={"X-Request-ID": "req-abc"})
    assert resp.status_code == 200
    assert resp.headers["X-Request-ID"] == "req-abc"
    assert seen["bound"] == "req-abc"
    assert structlog.contextvars.get_contextvars().get("request_id") is None


def test_request_context_generates_id_when_absent() -> None:
    seen: dict = {}
    app = make_app_with_probe(seen)
    with TestClient(app) as client:
        resp = client.get("/probe")
    assert resp.status_code == 200
    request_id = resp.headers["X-Request-ID"]
    assert len(request_id) == 32
    assert seen["bound"] == request_id


def test_request_context_replaces_log_injection_request_id() -> None:
    seen: dict = {}
    app = make_app_with_probe(seen)
    with TestClient(app) as client:
        resp = client.get("/probe", headers={"X-Request-ID": "secret\nforged=1"})
    assert resp.status_code == 200
    assert resp.headers["X-Request-ID"] != "secret\nforged=1"
    assert len(resp.headers["X-Request-ID"]) == 32


def test_request_context_echoes_on_problem_response() -> None:
    from fastapi import HTTPException

    app = FastAPI()

    @app.get("/nope")
    def nope() -> None:
        raise HTTPException(status_code=404, detail="nope")

    register_request_context(app)
    with TestClient(app) as client:
        resp = client.get("/nope", headers={"X-Request-ID": "req-x"})
    assert resp.status_code == 404
    assert resp.headers["X-Request-ID"] == "req-x"


def test_request_context_clears_context_after_request() -> None:
    seen: dict = {}
    app = make_app_with_probe(seen)
    with TestClient(app) as client:
        client.get("/probe", headers={"X-Request-ID": "req-1"})
        client.get("/probe", headers={"X-Request-ID": "req-2"})
    assert seen["bound"] == "req-2"
    assert structlog.contextvars.get_contextvars().get("request_id") is None


def test_chunked_request_body_is_bounded_before_handler_reads_it() -> None:
    from types import SimpleNamespace

    app = FastAPI()

    @app.post("/body")
    async def body(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    app.state.state = SimpleNamespace(
        settings=SimpleNamespace(max_body_bytes=1024),
        request_admission=None,
    )
    register_request_context(app)

    def chunks():
        yield b"a" * 800
        yield b"b" * 400

    with TestClient(app) as client:
        response = client.post("/body", content=chunks())

    assert response.status_code == 413
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["title"] == "Request body too large"


@pytest.mark.asyncio
async def test_slow_chunked_request_body_times_out() -> None:
    from app.middleware import read_bounded_body

    async def slow_receive() -> dict[str, object]:
        await asyncio.sleep(0.05)
        return {"type": "http.request", "body": b"a", "more_body": False}

    with pytest.raises(TimeoutError):
        await read_bounded_body(slow_receive, max_body_bytes=1024, timeout_seconds=0.01)  # type: ignore[arg-type]


def test_request_span_contains_metadata_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import middleware as mw

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(mw, "request_tracer", provider.get_tracer("test"))
    app = make_app_with_probe({})
    canary = "trace.canary.7f8d@example.com"

    with TestClient(app) as client:
        response = client.get(f"/probe?value={canary}")

    assert response.status_code == 200
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "redax.http.request"
    assert span.attributes == {
        "http.request.method": "GET",
        "http.response.status_code": 200,
    }
    assert canary not in repr(span)


def capture_access_line(monkeypatch: pytest.MonkeyPatch, captured: dict) -> None:
    from app import middleware as mw

    def spy(*, method: str, path: str, status: int, duration_ms: int, request_id: str) -> None:
        captured.update(
            method=method,
            path=path,
            status=status,
            request_id=request_id,
            duration_ms=duration_ms,
        )

    monkeypatch.setattr(mw, "emit_access_line", spy)


def test_access_log_line_carries_request_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    capture_access_line(monkeypatch, captured)
    app = make_app_with_probe({})
    with TestClient(app) as client:
        resp = client.get("/probe", headers={"X-Request-ID": "req-access"})
    assert resp.status_code == 200
    assert captured["method"] == "GET"
    assert captured["path"] == "/probe"
    assert captured["status"] == 200
    assert captured["request_id"] == "req-access"
    assert captured["duration_ms"] >= 0


def test_access_log_uses_route_template_for_identifier_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    capture_access_line(monkeypatch, captured)
    app = FastAPI()

    @app.get("/users/{user_id}")
    def user(user_id: str) -> dict[str, str]:
        return {"user_id": user_id}

    register_request_context(app)
    with TestClient(app) as client:
        response = client.get("/users/email-alice@example.com")

    assert response.status_code == 200
    assert captured["path"] == "/users/{user_id}"
    assert "email-alice@example.com" not in repr(captured)


def test_access_log_uses_fixed_path_for_unmatched_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    capture_access_line(monkeypatch, captured)
    app = make_app_with_probe({})
    with TestClient(app) as client:
        response = client.get("/missing/email-alice@example.com")

    assert response.status_code == 404
    assert captured["path"] == "<unmatched>"
    assert "email-alice@example.com" not in repr(captured)


def test_access_log_line_records_500_on_unhandled_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    capture_access_line(monkeypatch, captured)

    app = FastAPI()

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("boom")

    register_request_context(app)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/boom")
    assert resp.status_code == 500
    assert captured["status"] == 500
    assert captured["path"] == "/boom"


def test_emit_access_line_emits_expected_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Direct unit test for :func:`app.middleware.emit_access_line`.

    Asserts the structured log event carries the required keys even when
    tracing is disabled (``trace_id`` falls back to ``""``).
    """
    from app import middleware as mw

    captured: list[dict] = []

    class Logger:
        def info(self, event: str, **kwargs) -> None:
            captured.append({"event": event, **kwargs})

    monkeypatch.setattr(mw, "current_trace_id_hex", lambda: None)
    monkeypatch.setattr(mw, "get_logger", lambda _name: Logger())
    mw.emit_access_line(
        method="POST",
        path="/v1/redact",
        status=200,
        duration_ms=42,
        request_id="abc",
    )
    assert captured and captured[0]["event"] == "redax.access"
    assert captured[0]["method"] == "POST"
    assert captured[0]["path"] == "/v1/redact"
    assert captured[0]["status"] == 200
    assert captured[0]["duration_ms"] == 42
    assert captured[0]["request_id"] == "abc"
    assert captured[0]["trace_id"] == ""
