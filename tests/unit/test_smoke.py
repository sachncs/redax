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
