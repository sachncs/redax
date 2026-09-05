from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.redact import register
from app.redaction.redactor import Redactor
from app.state import ModelState, model_state
from app.inference.detector import Detector, Span


class _StubDetector:
    name = "stub"

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
        return [Span(12, 19, "EMAIL", 1.0)] if "@" in text else []

    async def warmup(self) -> None:
        return None


@pytest.fixture
def app_with_redactor(monkeypatch):
    test_state = ModelState()
    test_state.settings = type("S", (), {"max_text_chars": 1000})()
    test_state.redactor = Redactor(detector=_StubDetector())
    test_state.ready = True

    monkeypatch.setattr("app.state.model_state", test_state)
    app = FastAPI()
    register(app)
    return app


def test_redact_returns_substituted_text(app_with_redactor):
    with TestClient(app_with_redactor) as client:
        resp = client.post(
            "/v1/redact",
            json={"text": "Email me at a@b.com tomorrow"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "Email me at [REDACTED] tomorrow"
    assert len(body["spans"]) == 1
    assert body["spans"][0]["type"] == "EMAIL"


def test_redact_validates_empty_text(app_with_redactor):
    with TestClient(app_with_redactor) as client:
        resp = client.post("/v1/redact", json={"text": ""})
    assert resp.status_code == 422


def test_redact_over_max_text_returns_413(app_with_redactor):
    with TestClient(app_with_redactor) as client:
        resp = client.post(
            "/v1/redact",
            json={"text": "x" * 2000},
        )
    assert resp.status_code == 413
