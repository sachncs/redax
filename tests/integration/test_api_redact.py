from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.redact import register
from app.audit.backend import AuditBackend, AuditEvent
from app.inference.detector import Span
from app.redaction.redactor import Redactor
from app.redaction.strategy import AutoDeID, Mask, PassThrough, Regex
from app.state import ModelState


class _StubDetector:
    name = "stub"

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
        idx = text.find("@")
        if idx < 0:
            return []
        start = text.rfind(" ", 0, idx) + 1
        end = text.find(" ", idx)
        if end < 0:
            end = len(text)
        return [Span(start, end, "EMAIL", 1.0)]

    async def warmup(self) -> None:
        return None


class _MemoryAudit(AuditBackend):
    def __init__(self) -> None:
        self.records: list[AuditEvent] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def record(self, event: AuditEvent) -> None:
        self.records.append(event)


@pytest.fixture
def app_with_redactor(monkeypatch):
    test_state = ModelState()
    test_state.settings = type(
        "S", (), {"max_text_chars": 1000, "hash_salt": "x", "api_key_set": lambda self: set()}
    )()
    test_state.redactor = Redactor(
        detector=_StubDetector(),
        strategies={
            "passThrough": PassThrough(),
            "mask": Mask(),
            "regex": Regex(),
            "autoDeID": AutoDeID(_StubDetector()),
        },
    )
    test_state.audit = _MemoryAudit()
    test_state.job_store = None  # disable cache/idempotency
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


def test_redact_records_audit_event(monkeypatch):
    test_state = ModelState()
    test_state.settings = type(
        "S",
        (),
        {
            "max_text_chars": 1000,
            "hash_salt": "x",
            "api_key_set": lambda self: set(),
        },
    )()
    audit = _MemoryAudit()
    test_state.audit = audit
    test_state.redactor = Redactor(
        detector=_StubDetector(),
        strategies={
            "passThrough": PassThrough(),
            "mask": Mask(),
            "regex": Regex(),
            "autoDeID": AutoDeID(_StubDetector()),
        },
    )
    test_state.job_store = None
    test_state.ready = True
    monkeypatch.setattr("app.state.model_state", test_state)

    from app.api.redact import register as register_redact

    app = FastAPI()
    register_redact(app)

    with TestClient(app) as client:
        resp = client.post(
            "/v1/redact",
            json={"text": "Email me at a@b.com tomorrow"},
        )
    assert resp.status_code == 200
    assert len(audit.records) == 1
    rec = audit.records[0]
    assert rec.text_chars == len("Email me at a@b.com tomorrow")
    assert rec.entities_detected[0]["type"] == "EMAIL"
