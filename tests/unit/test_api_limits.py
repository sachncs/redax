from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import register_batch, register_stream
from app.errors import install_error_handlers
from app.state import model_state


class _Result:
    def __init__(self, text: str) -> None:
        self.text = text
        self.spans = []
        self.relex_map = {}


class _FastRedactor:
    async def redact(self, text, policy=None, entity_types=None):
        return _Result(text)


class _SlowRedactor(_FastRedactor):
    async def redact(self, text, policy=None, entity_types=None):
        await asyncio.sleep(0.1)
        return _Result(text)


class _FakeClient:
    def __init__(self, responses: list[int] | None = None, error: Exception | None = None) -> None:
        self.responses = list(responses or [1])
        self.error = error

    async def incr(self, key: str) -> int:
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)

    async def expire(self, key: str, seconds: int) -> None:
        return None


class _FakeStore:
    def __init__(self, client: _FakeClient) -> None:
        self.client = client


class _StubSettings:
    max_text_chars = 1000

    def __init__(
        self,
        rate_limit_per_minute: int,
        *,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        self.rate_limit_per_minute = rate_limit_per_minute
        self.request_timeout_seconds = request_timeout_seconds

    def api_key_set(self) -> set[str]:
        return {"limited-key"}


def _state(
    monkeypatch: pytest.MonkeyPatch,
    *,
    redactor: _FastRedactor,
    client: _FakeClient | None,
    settings: _StubSettings,
) -> None:
    monkeypatch.setattr(model_state, "redactor", redactor)
    monkeypatch.setattr(model_state, "job_store", _FakeStore(client) if client else None)
    monkeypatch.setattr(model_state, "settings", settings)


def _app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    register_batch(app)
    register_stream(app)
    return app


def test_batch_over_limit_returns_429(monkeypatch: pytest.MonkeyPatch) -> None:
    _state(
        monkeypatch,
        redactor=_FastRedactor(),
        client=_FakeClient([6]),
        settings=_StubSettings(5),
    )
    app = _app()
    with TestClient(app) as client:
        resp = client.post(
            "/v1/redact/batch",
            json={"items": [{"text": "hi"}]},
            headers={"X-API-Key": "limited-key"},
        )
    assert resp.status_code == 429
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_batch_rate_limit_down_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    _state(
        monkeypatch,
        redactor=_FastRedactor(),
        client=_FakeClient(error=ConnectionRefusedError("redis down")),
        settings=_StubSettings(5),
    )
    app = _app()
    with TestClient(app) as client:
        resp = client.post(
            "/v1/redact/batch",
            json={"items": [{"text": "hi"}]},
            headers={"X-API-Key": "limited-key"},
        )
    assert resp.status_code == 503
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_batch_timeout_returns_504(monkeypatch: pytest.MonkeyPatch) -> None:
    _state(
        monkeypatch,
        redactor=_SlowRedactor(),
        client=_FakeClient([1]),
        settings=_StubSettings(5, request_timeout_seconds=0.001),
    )
    app = _app()
    with TestClient(app) as client:
        resp = client.post(
            "/v1/redact/batch",
            json={"items": [{"text": "hi"}]},
            headers={"X-API-Key": "limited-key"},
        )
    assert resp.status_code == 504
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_batch_payload_too_large_returns_413(monkeypatch: pytest.MonkeyPatch) -> None:
    _state(
        monkeypatch,
        redactor=_FastRedactor(),
        client=_FakeClient([1]),
        settings=_StubSettings(5),
    )
    app = _app()
    with TestClient(app) as client:
        resp = client.post(
            "/v1/redact/batch",
            json={"items": [{"text": "x" * 2000}]},
            headers={"X-API-Key": "limited-key"},
        )
    assert resp.status_code == 413
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_stream_timeout_yields_504_event(monkeypatch: pytest.MonkeyPatch) -> None:
    _state(
        monkeypatch,
        redactor=_SlowRedactor(),
        client=_FakeClient([1]),
        settings=_StubSettings(5, request_timeout_seconds=0.001),
    )
    app = _app()
    with TestClient(app) as client:
        resp = client.post(
            "/v1/redact/stream",
            json={"text": "x" * 100},
            headers={"X-API-Key": "limited-key"},
        )
        lines = list(resp.iter_lines())
    assert any('"status": 504' in line for line in lines)


def test_stream_payload_too_large_returns_413(monkeypatch: pytest.MonkeyPatch) -> None:
    _state(
        monkeypatch,
        redactor=_FastRedactor(),
        client=_FakeClient([1]),
        settings=_StubSettings(5),
    )
    app = _app()
    with TestClient(app) as client:
        resp = client.post(
            "/v1/redact/stream",
            json={"text": "x" * 2000},
            headers={"X-API-Key": "limited-key"},
        )
    assert resp.status_code == 413
    assert resp.headers["content-type"].startswith("application/problem+json")