from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.redact import register
from app.audit.backend import Backend, Event
from app.inference.detector import Span
from app.inference.regex import RegexDetector
from app.redaction.circuit.breaker import Breaker
from app.redaction.pipeline import Pipeline
from app.redaction.redactor import Redactor
from app.redaction.stages.gate import Gate
from app.redaction.stages.model import ModelStage
from app.redaction.strategy import Deid, Mask, Regex, Skip
from app.state import State


class RedactStubDetector:
    """Stub that returns the email-looking word surrounding any '@' in the text."""

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


class MemoryAuditBackend(Backend):
    """In-memory audit backend that keeps every event in a list for assertion."""

    def __init__(self) -> None:
        self.records: list[Event] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def record(self, event: Event) -> None:
        self.records.append(event)


@pytest.fixture
def app_with_redactor():
    test_state = State()
    test_state.settings = type(
        "S", (), {"max_text_chars": 1000, "hash_salt": "x", "api_key_set": lambda self: set()}
    )()
    test_state.redactor = Redactor(
        detector=RedactStubDetector(),
        strategies={
            "passThrough": Skip(),
            "mask": Mask(),
            "regex": Regex(),
            "autoDeID": Deid(RedactStubDetector()),
        },
    )
    test_state.audit = MemoryAuditBackend()
    test_state.job_store = None  # disable cache/idempotency
    test_state.ready = True

    app = FastAPI()
    app.state.state = test_state
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


def test_redact_records_audit_event():
    test_state = State()
    test_state.settings = type(
        "S",
        (),
        {
            "max_text_chars": 1000,
            "hash_salt": "x",
            "api_key_set": lambda self: set(),
        },
    )()
    audit = MemoryAuditBackend()
    test_state.audit = audit
    test_state.redactor = Redactor(
        detector=RedactStubDetector(),
        strategies={
            "passThrough": Skip(),
            "mask": Mask(),
            "regex": Regex(),
            "autoDeID": Deid(RedactStubDetector()),
        },
    )
    test_state.job_store = None
    test_state.ready = True

    from app.api.redact import register as register_redact

    app = FastAPI()
    app.state.state = test_state
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


class StubModelDetector:
    """Model-stage detector that finds a fixed name string; used to exercise the pipeline path."""

    name = "stub_model"

    def detect_sync(self, text: str, entity_types: list[str]) -> list[Span]:
        # model finds a name that the regex misses
        name_start = text.find("Dr. Jane Doe")
        if name_start < 0:
            return []
        return [Span(name_start, name_start + 11, "PERSON", 0.9)]

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
        return self.detect_sync(text, entity_types)


def test_redact_pipeline_path_returns_used_pipeline_flag():
    test_state = State()
    test_state.settings = type(
        "S",
        (),
        {
            "max_text_chars": 1000,
            "hash_salt": "x",
            "api_key_set": lambda self: set(),
        },
    )()
    test_state.detector = StubModelDetector()
    test_state.regex_detector = RegexDetector()
    test_state.pipeline = Pipeline(
        regex_gate=Gate(detector=test_state.regex_detector),
        model_stage=ModelStage(detector=test_state.detector),
        model_breaker=Breaker(name="m", threshold=3, cooldown_s=5.0),
    )
    test_state.redactor = Redactor(
        detector=RedactStubDetector(),
        strategies={
            "passThrough": Skip(),
            "mask": Mask(),
            "regex": Regex(),
            "autoDeID": Deid(RedactStubDetector()),
        },
    )
    test_state.audit = MemoryAuditBackend()
    test_state.job_store = None
    test_state.ready = True

    app = FastAPI()
    app.state.state = test_state
    register(app)

    text = "Dr. Jane Doe lives at jane@example.com"
    with TestClient(app) as client:
        resp = client.post("/v1/redact", json={"text": text, "use_pipeline": True})

    assert resp.status_code == 200
    body = resp.json()
    assert body["used_pipeline"] is True
    assert body["used_fallback"] is False
    assert body["digest"] is not None
    types = [s["type"] for s in body["spans"]]
    assert "EMAIL" in types, f"regex gate should have caught the email: {types}"
    assert "PERSON" in types, f"model stage should have added the name: {types}"


def test_redact_without_use_pipeline_uses_legacy_redactor():
    test_state = State()
    test_state.settings = type(
        "S",
        (),
        {
            "max_text_chars": 1000,
            "hash_salt": "x",
            "api_key_set": lambda self: set(),
        },
    )()
    test_state.detector = StubModelDetector()
    test_state.regex_detector = RegexDetector()
    test_state.pipeline = Pipeline(
        regex_gate=Gate(detector=test_state.regex_detector),
        model_stage=ModelStage(detector=test_state.detector),
        model_breaker=Breaker(name="m", threshold=3, cooldown_s=5.0),
    )
    test_state.redactor = Redactor(
        detector=RedactStubDetector(),
        strategies={
            "passThrough": Skip(),
            "mask": Mask(),
            "regex": Regex(),
            "autoDeID": Deid(RedactStubDetector()),
        },
    )
    test_state.audit = MemoryAuditBackend()
    test_state.job_store = None
    test_state.ready = True

    app = FastAPI()
    app.state.state = test_state
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
    assert body["digest"] is None


def test_redact_without_policy_uses_default_policy(tmp_path):
    """REDAX_DEFAULT_POLICY is wired: a request without policy fields
    reuses the configured default policy's fields map."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.redact import register
    from app.state import State

    policies_dir = tmp_path / "policies"
    policies_dir.mkdir()
    (policies_dir / "default.yaml").write_text(
        "name: default\nversion: 1.0.0\n"
        "fields:\n  free_text:\n    strategy: passThrough\n"
    )

    state = State()
    state.settings = type(
        "S",
        (),
        {
            "max_text_chars": 100_000,
            "api_key_set": lambda self: set(),
            "default_policy": "default",
            "policies_dir": str(policies_dir),
            "hash_salt": "change-me",
            "cache_shared": False,
            "idempotency_ttl_seconds": 86_400,
            "cache_ttl_seconds": 3600,
        },
    )()
    state.redactor = Redactor(
        detector=RedactStubDetector(),
        strategies={"passThrough": Skip()},
    )
    state.audit = MemoryAuditBackend()
    state.job_store = None
    app = FastAPI()
    app.state.state = state
    register(app)
    with TestClient(app) as client:
        resp = client.post("/v1/redact", json={"text": "hello"})
    assert resp.status_code == 200
    # The default policy's passThrough strategy leaves the text untouched.
    assert resp.json()["text"] == "hello"
