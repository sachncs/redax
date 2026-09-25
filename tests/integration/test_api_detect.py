from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.detect import register
from app.errors import install_error_handlers
from app.inference.detector import Span
from app.state import State


class StubDetector:
    name = "stub"

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
        start = text.index("alice@example.com")
        return [Span(start, start + len("alice@example.com"), "EMAIL", 1.0)]


def make_app() -> FastAPI:
    state = State()
    state.settings = type(
        "SettingsStub",
        (),
        {"max_text_chars": 1000, "api_key_set": lambda self: set(), "rate_limit_per_minute": 0},
    )()
    state.detector = StubDetector()
    app = FastAPI()
    install_error_handlers(app)
    app.state.state = state
    register(app)
    return app


def test_detect_is_explicitly_raw_and_returns_spans() -> None:
    with TestClient(make_app()) as client:
        response = client.post("/v1/detect", json={"text": "Email alice@example.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "Email alice@example.com"
    assert body["spans"] == [{"start": 6, "end": 23, "type": "EMAIL", "confidence": 1.0}]
