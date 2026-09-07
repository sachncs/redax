from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import register_batch, register_jobs, register_stream
from app.errors import install_error_handlers
from app.state import State


class Result:
    def __init__(self, text: str) -> None:
        self.text = text
        self.spans = []
        self.relex_map = {}


class FastRedactor:
    async def redact(self, text, policy=None, entity_types=None):
        return Result(text)


class SlowRedactor(FastRedactor):
    async def redact(self, text, policy=None, entity_types=None):
        await asyncio.sleep(0.1)
        return Result(text)


class FakeClient:
    def __init__(self, responses: list[int] | None = None, error: Exception | None = None) -> None:
        self.responses = list(responses or [1])
        self.error = error

    async def incr(self, key: str) -> int:
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)

    async def expire(self, key: str, seconds: int) -> None:
        return None


class FakeStore:
    def __init__(self, client: FakeClient) -> None:
        self.client = client


class StubSettings:
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


def build_app(
    *, redactor: FastRedactor, client: FakeClient | None, settings: StubSettings
) -> FastAPI:
    test_state = State()
    test_state.redactor = redactor
    test_state.job_store = FakeStore(client) if client else None
    test_state.settings = settings
    app = FastAPI()
    install_error_handlers(app)
    register_batch(app)
    register_stream(app)
    register_jobs(app)
    app.state.state = test_state
    return app


def test_batch_over_limit_returns_429() -> None:
    app = build_app(
        redactor=FastRedactor(),
        client=FakeClient([6]),
        settings=StubSettings(5),
    )
    with TestClient(app) as client:
        resp = client.post(
            "/v1/redact/batch",
            json={"items": [{"text": "hi"}]},
            headers={"X-API-Key": "limited-key"},
        )
    assert resp.status_code == 429
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_batch_rate_limit_down_returns_503() -> None:
    app = build_app(
        redactor=FastRedactor(),
        client=FakeClient(error=ConnectionRefusedError("redis down")),
        settings=StubSettings(5),
    )
    with TestClient(app) as client:
        resp = client.post(
            "/v1/redact/batch",
            json={"items": [{"text": "hi"}]},
            headers={"X-API-Key": "limited-key"},
        )
    assert resp.status_code == 503
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_batch_timeout_returns_504() -> None:
    app = build_app(
        redactor=SlowRedactor(),
        client=FakeClient([1]),
        settings=StubSettings(5, request_timeout_seconds=0.001),
    )
    with TestClient(app) as client:
        resp = client.post(
            "/v1/redact/batch",
            json={"items": [{"text": "hi"}]},
            headers={"X-API-Key": "limited-key"},
        )
    assert resp.status_code == 504
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_batch_payload_too_large_returns_413() -> None:
    app = build_app(
        redactor=FastRedactor(),
        client=FakeClient([1]),
        settings=StubSettings(5),
    )
    with TestClient(app) as client:
        resp = client.post(
            "/v1/redact/batch",
            json={"items": [{"text": "x" * 2000}]},
            headers={"X-API-Key": "limited-key"},
        )
    assert resp.status_code == 413
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_stream_timeout_yields_504_event() -> None:
    app = build_app(
        redactor=SlowRedactor(),
        client=FakeClient([1]),
        settings=StubSettings(5, request_timeout_seconds=0.001),
    )
    with TestClient(app) as client:
        resp = client.post(
            "/v1/redact/stream",
            json={"text": "x" * 100},
            headers={"X-API-Key": "limited-key"},
        )
        lines = list(resp.iter_lines())
    assert any('"status": 504' in line for line in lines)


def test_stream_payload_too_large_returns_413() -> None:
    app = build_app(
        redactor=FastRedactor(),
        client=FakeClient([1]),
        settings=StubSettings(5),
    )
    with TestClient(app) as client:
        resp = client.post(
            "/v1/redact/stream",
            json={"text": "x" * 2000},
            headers={"X-API-Key": "limited-key"},
        )
    assert resp.status_code == 413
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_jobs_over_limit_returns_429() -> None:
    app = build_app(
        redactor=FastRedactor(),
        client=FakeClient([6]),
        settings=StubSettings(5),
    )
    with TestClient(app) as client:
        resp = client.post(
            "/v1/jobs",
            json={"text": "hi"},
            headers={"X-API-Key": "limited-key"},
        )
    assert resp.status_code == 429
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_jobs_payload_too_large_returns_413() -> None:
    app = build_app(
        redactor=FastRedactor(),
        client=FakeClient([1]),
        settings=StubSettings(5),
    )
    with TestClient(app) as client:
        resp = client.post(
            "/v1/jobs",
            json={"text": "x" * 2000},
            headers={"X-API-Key": "limited-key"},
        )
    assert resp.status_code == 413
    assert resp.headers["content-type"].startswith("application/problem+json")
