from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api import (
    register_batch,
    register_jobs,
    register_policies,
    register_redact,
    register_stream,
)
from app.auth import require_api_key
from app.errors import install_error_handlers
from app.state import state


class StubResult:
    def __init__(self, text: str) -> None:
        self.text = text
        self.spans = []
        self.relex_map = {}


class StubRedactor:
    async def redact(
        self, text: str, policy: dict | None = None, entity_types: list[str] | None = None
    ):
        return StubResult(text)


class StubSettings:
    max_text_chars = 100_000
    request_timeout_seconds = 10.0
    cache_ttl_seconds = 3600
    idempotency_ttl_seconds = 86400
    hash_salt = ""
    rate_limit_per_minute = 0
    policies_dir = "./policies"

    def __init__(self, api_keys: set[str]) -> None:
        self.api_keys = api_keys

    def api_key_set(self) -> set[str]:
        return self.api_keys


def stub_state(monkeypatch: pytest.MonkeyPatch, *, api_keys: set[str]) -> None:
    monkeypatch.setattr(state, "settings", StubSettings(api_keys))
    monkeypatch.setattr(state, "redactor", StubRedactor())


def make_app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    register_redact(app)
    register_batch(app)
    register_stream(app)
    register_jobs(app)
    register_policies(app)
    return app


def test_require_api_key_missing_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_state(monkeypatch, api_keys={"k1"})
    with pytest.raises(HTTPException) as exc_info:
        require_api_key()
    assert exc_info.value.status_code == 401


def test_require_api_key_invalid_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_state(monkeypatch, api_keys={"k1"})
    with pytest.raises(HTTPException) as exc_info:
        require_api_key("wrong")
    assert exc_info.value.status_code == 401


def test_require_api_key_valid_returns_key(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_state(monkeypatch, api_keys={"k1"})
    assert require_api_key("k1") == "k1"


def test_require_api_key_disabled_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_state(monkeypatch, api_keys=set())
    assert require_api_key() == "anonymous"


def test_require_api_key_no_settings_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state, "settings", None)
    assert require_api_key() == "anonymous"


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/v1/redact", {"text": "hi a@b.com"}),
        ("/v1/redact/batch", {"items": [{"text": "hi a@b.com"}]}),
        ("/v1/redact/stream", {"text": "hi"}),
        ("/v1/jobs", {"text": "hi a@b.com"}),
    ],
)
def test_protected_routes_reject_missing_key(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    payload: dict,
) -> None:
    stub_state(monkeypatch, api_keys={"test-key"})
    app = make_app()
    with TestClient(app) as client:
        resp = client.post(path, json=payload)
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_jobs_get_rejects_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_state(monkeypatch, api_keys={"test-key"})
    app = make_app()
    with TestClient(app) as client:
        resp = client.get("/v1/jobs/xyz")
    assert resp.status_code == 401


def test_policies_rejects_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_state(monkeypatch, api_keys={"test-key"})
    app = make_app()
    with TestClient(app) as client:
        resp = client.get("/v1/policies")
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_policies_accepts_valid_key(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    stub_state(monkeypatch, api_keys={"test-key"})
    (tmp_path / "default.yaml").write_text(
        '{"name": "default", "version": "1.0.0", "description": "d", "fields": {}}'
    )
    monkeypatch.setattr(state.settings, "policies_dir", str(tmp_path))
    app = make_app()
    with TestClient(app) as client:
        resp = client.get("/v1/policies", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
    assert resp.json()["policies"][0]["name"] == "default"


def test_batch_accepts_valid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_state(monkeypatch, api_keys={"test-key"})
    app = make_app()
    with TestClient(app) as client:
        resp = client.post(
            "/v1/redact/batch",
            json={"items": [{"text": "hi a@b.com"}]},
            headers={"X-API-Key": "test-key"},
        )
    assert resp.status_code == 200
    assert resp.json()["results"][0]["text"] == "hi a@b.com"
