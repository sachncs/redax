from __future__ import annotations

import asyncio
from typing import ClassVar

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import register_batch, register_jobs, register_stream
from app.audit.backend import Backend, Event
from app.inference.detector import Span
from app.jobs.store import JobStore
from app.redaction.redactor import Redactor
from app.redaction.strategy import Deid, Mask, Regex, Skip
from app.state import State


class MemoryAudit(Backend):
    def __init__(self) -> None:
        self.records: list[Event] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def record(self, event: Event) -> None:
        self.records.append(event)


class StubDetector:
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


class InMemoryJobStore(JobStore):
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def create(self, owner: str = ""):
        import uuid

        from app.jobs.store import JobRecord

        rec = JobRecord(
            id=uuid.uuid4().hex,
            status="queued",
            result=None,
            error=None,
            owner=owner,
        )
        self.records[rec.id] = rec
        return rec

    async def count_for_key(self, owner: str):
        return sum(1 for record in self.records.values() if record.owner == owner)

    async def get(self, job_id):
        return self.records.get(job_id)

    async def set_status(self, job_id, status):
        self.records[job_id].status = status

    async def set_result(self, job_id, result):
        self.records[job_id].owner = ""
        self.records[job_id].result = result
        self.records[job_id].status = "done"

    async def set_error(self, job_id, error):
        self.records[job_id].owner = ""
        self.records[job_id].error = error
        self.records[job_id].status = "failed"


@pytest.fixture
def app_with_state():
    test_state = State()
    test_state.settings = type(
        "S",
        (),
        {"max_text_chars": 100_000, "api_key_set": lambda self: {"test-key"}},
    )()
    test_state.redactor = Redactor(
        detector=StubDetector(),
        strategies={
            "passThrough": Skip(),
            "mask": Mask(),
            "regex": Regex(),
            "autoDeID": Deid(StubDetector()),
        },
    )
    test_state.job_store = InMemoryJobStore()
    test_state.audit = MemoryAudit()
    test_state.ready = True
    app = FastAPI()
    app.state.state = test_state
    register_batch(app)
    register_stream(app)
    register_jobs(app)
    return app


def test_batch_returns_results_for_each_item(app_with_state):
    with TestClient(app_with_state) as client:
        resp = client.post(
            "/v1/redact/batch",
            json={"items": [{"text": "hi a@b.com"}, {"text": "nothing"}]},
            headers={"X-API-Key": "test-key"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 2
    assert body["results"][0]["text"] == "hi [REDACTED]"


def test_stream_emits_events(app_with_state):
    with TestClient(app_with_state) as client:
        resp = client.post(
            "/v1/redact/stream",
            json={"text": "x" * 5000, "chunk_chars": 1000},
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 200
        chunks = list(resp.iter_lines())
    assert any("[DONE]" in c for c in chunks)


def stream_latency_count() -> float:
    """Read the current value of the redax_request_duration_seconds_count histogram for the stream endpoint."""
    from app.observability import REQUEST_LATENCY

    for metric in REQUEST_LATENCY.collect():
        for sample in metric.samples:
            if (
                sample.name == "redax_request_duration_seconds_count"
                and sample.labels["endpoint"] == "POST /v1/redact/stream"
                and sample.labels["method"] == "POST"
            ):
                return sample.value
    return 0.0


def test_stream_records_end_to_end_request_latency(app_with_state):
    before = stream_latency_count()
    with TestClient(app_with_state) as client:
        resp = client.post(
            "/v1/redact/stream",
            json={"text": "x" * 5000, "chunk_chars": 1000},
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 200
        for _ in resp.iter_lines():
            pass
    after = stream_latency_count()
    assert before >= 0.0
    assert after >= before + 1.0


def test_job_lifecycle(app_with_state):
    with TestClient(app_with_state) as client:
        sub = client.post(
            "/v1/jobs", json={"text": "hi a@b.com"}, headers={"X-API-Key": "test-key"}
        )
        assert sub.status_code == 202
        job_id = sub.json()["id"]
        deadline = 5.0
        import time

        start = time.time()
        while time.time() - start < deadline:
            r = client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": "test-key"})
            if r.json()["status"] == "done":
                break
            time.sleep(0.05)
        body = client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": "test-key"}).json()
    assert body["status"] == "done"
    assert body["result"]["text"] == "hi [REDACTED]"


@pytest.fixture
def app_with_no_redactor():
    test_state = State()
    test_state.settings = type(
        "S", (), {"max_text_chars": 1000, "api_key_set": lambda self: {"test-key"}}
    )()
    test_state.job_store = InMemoryJobStore()
    test_state.ready = True
    app = FastAPI()
    app.state.state = test_state
    register_jobs(app)
    return app


def test_batch_records_audited_entity_summary(app_with_state):
    with TestClient(app_with_state) as client:
        resp = client.post(
            "/v1/redact/batch",
            json={"items": [{"text": "hi a@b.com"}, {"text": "nothing"}]},
            headers={"X-API-Key": "test-key"},
        )
    assert resp.status_code == 200
    audit = app_with_state.state.state.audit
    assert len(audit.records) == 1
    rec = audit.records[0]
    assert rec.text_chars == len("hi a@b.com") + len("nothing")
    assert rec.entities_detected == [{"type": "EMAIL", "count": 1, "confidence_avg": 1.0}]


def test_stream_records_audited_entity_summary(app_with_state):
    with TestClient(app_with_state) as client:
        resp = client.post(
            "/v1/redact/stream",
            json={"text": "x" * 5000, "chunk_chars": 1000},
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 200
        for _ in resp.iter_lines():
            pass
    audit = app_with_state.state.state.audit
    assert len(audit.records) == 1
    assert audit.records[0].text_chars == 5000
    assert audit.records[0].entities_detected == []


class SlowDetector(StubDetector):
    seen: ClassVar[list[float]] = []

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
        from app.observability.metrics import QUEUE_DEPTH

        for metric in QUEUE_DEPTH.collect():
            for sample in metric.samples:
                SlowDetector.seen.append(sample.value)
        await asyncio.sleep(0.3)
        return await super().detect(text, entity_types)


@pytest.fixture
def app_with_slow_redactor():
    test_state = State()
    test_state.settings = type(
        "S", (), {"max_text_chars": 100_000, "api_key_set": lambda self: {"test-key"}}
    )()
    test_state.redactor = Redactor(detector=SlowDetector(), strategies={})
    test_state.job_store = InMemoryJobStore()
    test_state.audit = MemoryAudit()
    test_state.ready = True
    app = FastAPI()
    app.state.state = test_state
    register_jobs(app)
    return app


def test_queue_depth_tracks_in_flight_job_and_returns_to_zero(app_with_slow_redactor):
    from app.observability.metrics import QUEUE_DEPTH

    SlowDetector.seen.clear()
    with TestClient(app_with_slow_redactor) as client:
        sub = client.post(
            "/v1/jobs", json={"text": "hi a@b.com"}, headers={"X-API-Key": "test-key"}
        )
        assert sub.status_code == 202
        job_id = sub.json()["id"]
        deadline = 5.0
        import time

        start = time.time()
        while time.time() - start < deadline:
            body = client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": "test-key"}).json()
            if body["status"] == "done":
                break
            time.sleep(0.05)
    assert body["status"] == "done"
    assert SlowDetector.seen == [1.0]
    final = [s.value for m in QUEUE_DEPTH.collect() for s in m.samples]
    assert final == [0.0]


def test_job_records_audited_entity_summary(app_with_state):
    with TestClient(app_with_state) as client:
        sub = client.post(
            "/v1/jobs", json={"text": "hi a@b.com"}, headers={"X-API-Key": "test-key"}
        )
        assert sub.status_code == 202
        job_id = sub.json()["id"]
        deadline = 5.0
        import time

        start = time.time()
        while time.time() - start < deadline:
            body = client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": "test-key"}).json()
            if body["status"] == "done":
                break
            time.sleep(0.05)
    assert body["status"] == "done"
    audit = app_with_state.state.state.audit
    assert len(audit.records) == 1
    rec = audit.records[0]
    assert rec.text_chars == len("hi a@b.com")
    assert rec.entities_detected == [{"type": "EMAIL", "count": 1, "confidence_avg": 1.0}]


def test_job_not_found(app_with_state):
    with TestClient(app_with_state) as client:
        r = client.get("/v1/jobs/does-not-exist", headers={"X-API-Key": "test-key"})
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["status"] == 404
    assert body["title"] == "Job not found"


def test_failed_job_does_not_leak_internal_error(app_with_no_redactor):
    with TestClient(app_with_no_redactor) as client:
        sub = client.post(
            "/v1/jobs", json={"text": "hi a@b.com"}, headers={"X-API-Key": "test-key"}
        )
        assert sub.status_code == 202
        job_id = sub.json()["id"]
        deadline = 5.0
        import time

        start = time.time()
        while time.time() - start < deadline:
            r = client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": "test-key"})
            body = r.json()
            if body["status"] == "failed":
                break
            time.sleep(0.05)
    assert body["status"] == "failed"
    assert body["error"] == "job failed"


@pytest.fixture
def app_with_max_inflight():
    test_state = State()
    test_state.settings = type(
        "S",
        (),
        {
            "max_text_chars": 100_000,
            "api_key_set": lambda self: {"test-key"},
            "max_inflight": 1,
        },
    )()
    test_state.redactor = Redactor(detector=SlowDetector(), strategies={})
    test_state.job_store = InMemoryJobStore()
    test_state.audit = MemoryAudit()
    test_state.ready = True
    app = FastAPI()
    app.state.state = test_state
    register_jobs(app)
    return app


def test_job_submission_rejected_when_inflight_full(app_with_max_inflight):
    from app.observability.metrics import QUEUE_DEPTH

    QUEUE_DEPTH.set(1.0)
    try:
        with TestClient(app_with_max_inflight) as client:
            resp = client.post(
                "/v1/jobs", json={"text": "more text"}, headers={"X-API-Key": "test-key"}
            )
    finally:
        QUEUE_DEPTH.set(0.0)
    assert resp.status_code == 429
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["title"] == "Queue Full"


@pytest.fixture
def app_with_per_key_quota():
    test_state = State()
    test_state.settings = type(
        "S",
        (),
        {
            "max_text_chars": 100_000,
            "api_key_set": lambda self: {"k1"},
            "max_jobs_per_key": 1,
        },
    )()
    test_state.job_store = InMemoryJobStore()
    test_state.ready = True
    app = FastAPI()
    app.state.state = test_state
    register_jobs(app)
    return app


def test_job_submission_rejected_over_per_key_quota(app_with_per_key_quota):
    import asyncio

    store = app_with_per_key_quota.state.state.job_store
    asyncio.run(store.create(owner="k1"))
    asyncio.run(store.create(owner="k1"))
    with TestClient(app_with_per_key_quota) as client:
        resp = client.post("/v1/jobs", json={"text": "more text"}, headers={"X-API-Key": "k1"})
    assert resp.status_code == 429
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["title"] == "Too Many Jobs"


@pytest.fixture
def app_with_short_job_timeout():
    test_state = State()
    test_state.settings = type(
        "S",
        (),
        {
            "max_text_chars": 100_000,
            "api_key_set": lambda self: {"test-key"},
            "request_timeout_seconds": 0.05,
        },
    )()
    test_state.redactor = Redactor(detector=SlowDetector(), strategies={})
    test_state.job_store = InMemoryJobStore()
    test_state.audit = MemoryAudit()
    test_state.ready = True
    app = FastAPI()
    app.state.state = test_state
    register_jobs(app)
    return app


def test_job_times_out_and_fails_with_job_timeout_error(app_with_short_job_timeout):
    from app.observability.metrics import ERRORS

    def job_timeout_count() -> float:
        for metric in ERRORS.collect():
            for sample in metric.samples:
                if (
                    sample.name == "redax_errors_total"
                    and sample.labels.get("type") == "job_timeout"
                ):
                    return sample.value
        return 0.0

    before = job_timeout_count()
    with TestClient(app_with_short_job_timeout) as client:
        sub = client.post(
            "/v1/jobs", json={"text": "hi a@b.com"}, headers={"X-API-Key": "test-key"}
        )
        assert sub.status_code == 202
        job_id = sub.json()["id"]
        deadline = 5.0
        import time

        start = time.time()
        while time.time() - start < deadline:
            r = client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": "test-key"})
            body = r.json()
            if body["status"] == "failed":
                break
            time.sleep(0.05)
    assert body["status"] == "failed"
    assert body["error"] == "job failed"
    assert job_timeout_count() >= before + 1.0
