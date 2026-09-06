from __future__ import annotations


def test_health_module_importable() -> None:
    from app.api.health import register

    assert callable(register)


def test_config_defaults() -> None:
    from app.config import Settings

    s = Settings()
    assert s.log_level == "INFO"
    assert s.model_name == "fastino/gliner2-privacy-filter-PII-multi"
    assert s.default_policy == "default"
    assert s.max_text_chars == 100_000


def test_config_api_key_set_parses_comma_list() -> None:
    from app.config import Settings

    s = Settings(api_keys="a, b,,c")
    assert s.api_key_set() == {"a", "b", "c"}


def test_app_imports() -> None:
    from app.main import app

    assert app.title == "Redax"


def test_healthz(client) -> None:
    from app.api.health import register

    app = client.app
    register(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz_returns_503_problem_until_ready(monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.health import register
    from app.state import model_state

    monkeypatch.setattr(model_state, "ready", False)
    monkeypatch.setattr(model_state, "redactor", None)
    app = FastAPI()
    register(app)
    with TestClient(app) as client:
        resp = client.get("/readyz")
    assert resp.status_code == 503
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["title"] == "Not ready"


def test_readyz_200_when_ready(monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.health import register
    from app.state import model_state

    monkeypatch.setattr(model_state, "ready", True)
    monkeypatch.setattr(model_state, "redactor", object())
    app = FastAPI()
    register(app)
    with TestClient(app) as client:
        resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}
