from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.redact import register
from app.audit.backend import Backend, Event
from app.inference.detector import Span
from app.inference.regex_detector import RegexDetector
from app.redaction.circuit.breaker import Breaker
from app.redaction.pipeline import Pipeline
from app.redaction.redactor import Redactor
from app.redaction.stages.model_stage import ModelStage
from app.redaction.stages.regex_gate import RegexGate
from app.redaction.strategy import Deid, Mask, Regex, Skip
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


class _MemoryAudit(Backend):
    def __init__(self) -> None:
        self.records: list[Event] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def record(self, event: Event) -> None:
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
            "passThrough": Skip(),
            "mask": Mask(),
            "regex": Regex(),
            "autoDeID": Deid(_StubDetector()),
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
            "passThrough": Skip(),
            "mask": Mask(),
            "regex": Regex(),
            "autoDeID": Deid(_StubDetector()),
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


class _StubModelDetector:
    name = "stub_model"

    def detect_sync(self, text: str, entity_types: list[str]) -> list[Span]:
        # model finds a name that the regex misses
        name_start = text.find("Dr. Jane Doe")
        if name_start < 0:
            return []
        return [Span(name_start, name_start + 11, "PERSON", 0.9)]

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
        return self.detect_sync(text, entity_types)


def test_redact_pipeline_path_returns_used_pipeline_flag(monkeypatch):
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
    test_state.detector = _StubModelDetector()
    test_state.regex_detector = RegexDetector()
    test_state.pipeline = Pipeline(
        regex_gate=RegexGate(detector=test_state.regex_detector),
        model_stage=ModelStage(detector=test_state.detector),
        model_breaker=Breaker(name="m", failure_threshold=3, cooldown_s=5.0),
    )
    test_state.redactor = Redactor(
        detector=_StubDetector(),
        strategies={
            "passThrough": Skip(),
            "mask": Mask(),
            "regex": Regex(),
            "autoDeID": Deid(_StubDetector()),
        },
    )
    test_state.audit = _MemoryAudit()
    test_state.job_store = None
    test_state.ready = True
    monkeypatch.setattr("app.state.model_state", test_state)

    app = FastAPI()
    register(app)

    text = "Dr. Jane Doe lives at jane@example.com"
    with TestClient(app) as client:
        resp = client.post("/v1/redact", json={"text": text, "use_pipeline": True})

    assert resp.status_code == 200
    body = resp.json()
    assert body["used_pipeline"] is True
    assert body["used_fallback"] is False
    assert body["text_hash"] is not None
    types = [s["type"] for s in body["spans"]]
    assert "EMAIL" in types, f"regex gate should have caught the email: {types}"
    assert "PERSON" in types, f"model stage should have added the name: {types}"


def test_redact_without_use_pipeline_uses_legacy_redactor(monkeypatch):
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
    test_state.detector = _StubModelDetector()
    test_state.regex_detector = RegexDetector()
    test_state.pipeline = Pipeline(
        regex_gate=RegexGate(detector=test_state.regex_detector),
        model_stage=ModelStage(detector=test_state.detector),
        model_breaker=Breaker(name="m", failure_threshold=3, cooldown_s=5.0),
    )
    test_state.redactor = Redactor(
        detector=_StubDetector(),
        strategies={
            "passThrough": Skip(),
            "mask": Mask(),
            "regex": Regex(),
            "autoDeID": Deid(_StubDetector()),
        },
    )
    test_state.audit = _MemoryAudit()
    test_state.job_store = None
    test_state.ready = True
    monkeypatch.setattr("app.state.model_state", test_state)

    app = FastAPI()
    register(app)

    with TestClient(app) as client:
        resp = client.post(
            "/v1/redact",
            json={"text": "Email me at a@b.com tomorrow"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["used_pipeline"] is False
    assert "[REDACTED]" in body["text"]
    assert body["text_hash"] is None
