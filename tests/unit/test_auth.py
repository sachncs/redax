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
from app.auth import principal_id, require_api_key
from app.errors import install_error_handlers
from app.state import State


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

    def __init__(self, api_keys: set[str], scopes: dict[str, set[str]] | None = None) -> None:
        self.api_keys = api_keys
        self.scopes = scopes or {}

    def api_key_set(self) -> set[str]:
        return self.api_keys

    def api_key_scope_map(self) -> dict[str, set[str]]:
        return self.scopes


def make_state(*, api_keys: set[str], scopes: dict[str, set[str]] | None = None) -> State:
    test_state = State()
    test_state.settings = StubSettings(api_keys, scopes)
    test_state.redactor = StubRedactor()
    return test_state


def make_app(state: State) -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    register_redact(app)
    register_batch(app)
    register_stream(app)
    register_jobs(app)
    register_policies(app)
    app.state.state = state
    return app


def test_require_api_key_missing_rejected() -> None:
    state = make_state(api_keys={"k1"})
    with pytest.raises(HTTPException) as exc_info:
        require_api_key(state=state)
    assert exc_info.value.status_code == 401


def test_principal_id_is_stable_and_does_not_include_api_key() -> None:
    identifier = principal_id("secret-api-key", "deployment-salt")
    assert identifier == principal_id("secret-api-key", "deployment-salt")
    assert len(identifier) == 24
    assert "secret-api-key" not in identifier
    assert identifier != principal_id("other-api-key", "deployment-salt")


def test_openapi_advertises_api_key_security_scheme() -> None:
    schema = make_app(make_state(api_keys={"k1"})).openapi()

    assert schema["components"]["securitySchemes"]["APIKeyHeader"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": (
            "Deployment API key; endpoint scopes are configured by REDAX_API_KEY_SCOPES."
        ),
    }
    assert schema["paths"]["/v1/redact"]["post"]["security"] == [{"APIKeyHeader": []}]


def test_require_api_key_invalid_rejected() -> None:
    state = make_state(api_keys={"k1"})
    with pytest.raises(HTTPException) as exc_info:
        require_api_key(state=state, x_api_key="wrong")
    assert exc_info.value.status_code == 401


def test_require_api_key_valid_returns_key() -> None:
    state = make_state(api_keys={"k1"})
    assert require_api_key(state=state, x_api_key="k1") == "k1"


def test_multiple_active_keys_support_rotation_overlap() -> None:
    state = make_state(api_keys={"old-key", "new-key"})
    assert require_api_key(state=state, x_api_key="old-key") == "old-key"
    assert require_api_key(state=state, x_api_key="new-key") == "new-key"


def test_api_key_comparison_checks_all_rotation_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    state = make_state(api_keys={"old-key", "new-key", "future-key"})
    compared: list[str] = []

    def compare_digest(left: str, right: str) -> bool:
        compared.append(right)
        return left == right

    monkeypatch.setattr("app.auth.secrets.compare_digest", compare_digest)

    assert require_api_key(state=state, x_api_key="old-key") == "old-key"
    assert sorted(compared) == ["future-key", "new-key", "old-key"]


def test_revoked_key_is_rejected_while_replacement_remains_valid() -> None:
    from app.config import Settings

    state = make_state(api_keys={"placeholder"})
    state.settings = Settings(
        env="dev",
        api_keys="old-key,new-key",
        api_key_revocations="old-key",
    )
    with pytest.raises(HTTPException) as exc_info:
        require_api_key(state=state, x_api_key="old-key")
    assert exc_info.value.status_code == 401
    assert require_api_key(state=state, x_api_key="new-key") == "new-key"


def test_require_api_key_disabled_passthrough() -> None:
    state = make_state(api_keys=set())
    assert require_api_key(state=state) == "anonymous"


def test_require_api_key_no_settings_passthrough() -> None:
    state = make_state(api_keys={"k1"})
    state.settings = None
    assert require_api_key(state=state) == "anonymous"


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/v1/redact", {"text": "hi a@b.com"}),
        ("/v1/redact/batch", {"items": [{"text": "hi a@b.com"}]}),
        ("/v1/redact/stream", {"text": "hi"}),
        ("/v1/jobs", {"text": "hi a@b.com"}),
    ],
)
def test_protected_routes_reject_missing_key(path: str, payload: dict) -> None:
    app = make_app(make_state(api_keys={"test-key"}))
    with TestClient(app) as client:
        resp = client.post(path, json=payload)
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_auth_and_validation_failures_do_not_echo_canary(capsys) -> None:
    canary = "auth.validation.canary.7f8d@example.com"
    app = make_app(make_state(api_keys={"test-key"}))
    with TestClient(app, raise_server_exceptions=False) as client:
        auth_failure = client.post(
            "/v1/redact",
            json={"text": canary},
            headers={"X-API-Key": canary},
        )
        validation_failure = client.post(
            "/v1/redact",
            json={"text": {"value": canary}},
            headers={"X-API-Key": "test-key"},
        )
    output = capsys.readouterr().out
    assert auth_failure.status_code == 401
    assert validation_failure.status_code == 422
    assert canary not in auth_failure.text
    assert canary not in validation_failure.text
    assert canary not in output


def test_jobs_get_rejects_missing_key() -> None:
    app = make_app(make_state(api_keys={"test-key"}))
    with TestClient(app) as client:
        resp = client.get("/v1/jobs/xyz")
    assert resp.status_code == 401


def test_policies_rejects_missing_key() -> None:
    app = make_app(make_state(api_keys={"test-key"}))
    with TestClient(app) as client:
        resp = client.get("/v1/policies")
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_policies_accepts_valid_key(tmp_path) -> None:
    state = make_state(api_keys={"test-key"})
    (tmp_path / "default.yaml").write_text(
        '{"name": "default", "version": "1.0.0", "description": "d", "fields": {}}'
    )
    state.settings.policies_dir = str(tmp_path)
    app = make_app(state)
    with TestClient(app) as client:
        resp = client.get("/v1/policies", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
    assert resp.json()["policies"][0]["name"] == "default"


def test_scoped_key_cannot_read_policies_without_policy_scope(tmp_path) -> None:
    state = make_state(api_keys={"test-key"}, scopes={"test-key": {"redact"}})
    (tmp_path / "default.yaml").write_text(
        '{"name": "default", "version": "1.0.0", "description": "d", "fields": {}}'
    )
    state.settings.policies_dir = str(tmp_path)
    app = make_app(state)
    with TestClient(app) as client:
        response = client.get("/v1/policies", headers={"X-API-Key": "test-key"})
    assert response.status_code == 403


def test_batch_accepts_valid_key() -> None:
    app = make_app(make_state(api_keys={"test-key"}))
    with TestClient(app) as client:
        resp = client.post(
            "/v1/redact/batch",
            json={"items": [{"text": "hi a@b.com"}]},
            headers={"X-API-Key": "test-key"},
        )
    assert resp.status_code == 200
    assert resp.json()["results"][0]["text"] == "hi a@b.com"
