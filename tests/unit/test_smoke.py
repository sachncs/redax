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


def test_readyz_returns_503_problem_until_ready() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.health import register
    from app.state import State

    test_state = State()
    test_state.ready = False
    test_state.redactor = None
    app = FastAPI()
    app.state.state = test_state
    register(app)
    with TestClient(app) as client:
        resp = client.get("/readyz")
    assert resp.status_code == 503
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["title"] == "Not ready"


def test_readyz_200_when_ready() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.health import register
    from app.state import State

    test_state = State()
    test_state.ready = True
    test_state.redactor = object()
    app = FastAPI()
    app.state.state = test_state
    register(app)
    with TestClient(app) as client:
        resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}


def test_health_metrics_instrumented() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.health import register
    from app.state import State

    test_state = State()
    test_state.ready = True
    test_state.redactor = object()
    app = FastAPI()
    app.state.state = test_state
    register(app)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 200
        resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text
    assert 'redax_requests_total{endpoint="GET /healthz",method="GET",status="200"}' in body
    assert 'redax_requests_total{endpoint="GET /readyz",method="GET",status="200"}' in body
    assert 'redax_requests_total{endpoint="GET /metrics",method="GET",status="200"}' in body
    assert 'redax_request_duration_seconds_count{endpoint="GET /healthz",method="GET"}' in body
    assert 'redax_request_duration_seconds_count{endpoint="GET /readyz",method="GET"}' in body


def test_stats_endpoint_requires_api_key() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.health import register
    from app.errors import install_error_handlers
    from app.state import State

    class AuthSettings:
        """Settings stub that advertises one valid API key 'k1'."""

        def api_key_set(self) -> set[str]:
            return {"k1"}

    test_state = State()
    test_state.ready = True
    test_state.redactor = object()
    test_state.settings = AuthSettings()
    app = FastAPI()
    app.state.state = test_state
    install_error_handlers(app)
    register(app)
    with TestClient(app) as client:
        resp = client.get("/v1/stats")
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_stats_endpoint_reports_pipeline_when_present() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.health import register
    from app.errors import install_error_handlers
    from app.redaction.circuit.breaker import Breaker
    from app.redaction.pipeline import Pipeline
    from app.redaction.stages.gate import Gate
    from app.redaction.stages.model import ModelStage
    from app.state import State

    class StatsStubModel:
        """Detector stub for the /v1/stats pipeline-stats test; returns no spans."""

        name = "stub_model"

        def detect_sync(self, text, entity_types):
            return []

        async def detect(self, text, entity_types):
            return []

    class NoAuthSettings:
        """Settings stub with an empty API key set, so the endpoint is un-gated."""

        def api_key_set(self) -> set[str]:
            return set()

    test_state = State()
    test_state.ready = True
    test_state.redactor = object()
    test_state.settings = NoAuthSettings()
    test_state.detector = StatsStubModel()
    test_state.regex_detector = type("R", (), {"name": "regex"})()
    test_state.pipeline = Pipeline(
        regex_gate=Gate(detector=test_state.regex_detector),
        model_stage=ModelStage(detector=test_state.detector),
        model_breaker=Breaker(name="m", threshold=3, cooldown_s=5.0),
    )

    app = FastAPI()
    app.state.state = test_state
    install_error_handlers(app)
    register(app)
    with TestClient(app) as client:
        resp = client.get("/v1/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["detector"] == "stub_model"
    assert body["regex_detector"] == "regex"
    assert "pipeline" in body
    assert body["pipeline"]["model_breaker"]["state"] == "closed"
