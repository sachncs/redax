from __future__ import annotations

import asyncio
from typing import ClassVar

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.api import register_batch, register_jobs, register_stream
from app.api.stream import StreamRequest
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
            owner=self.owner_token(owner) if owner else "",
        )
        self.records[rec.id] = rec
        return rec

    async def count_for_key(self, owner: str):
        token = self.owner_token(owner)
        return sum(1 for record in self.records.values() if record.owner == token)

    async def count_inflight(self):
        return sum(record.status in {"queued", "running"} for record in self.records.values())

    async def get(self, job_id):
        return self.records.get(job_id)

    async def set_status(self, job_id, status):
        self.records[job_id].status = status

    async def set_result(self, job_id, result):
        self.records[job_id].result = result
        self.records[job_id].status = "done"
        return True

    async def set_error(self, job_id, error):
        self.records[job_id].error = error
        self.records[job_id].status = "failed"
        return True


class InMemoryJobQueue:
    def __init__(self, state: State) -> None:
        self.state = state

    async def enqueue_job(self, _function, job_id, payload, request_id, **_kwargs):
        from app.api.jobs import run_job

        await run_job(job_id, payload, self.state.job_store, request_id, self.state)
        return object()

    async def close(self):
        return None


@pytest.fixture
def app_with_state():
    test_state = State()
    test_state.settings = type(
        "S",
        (),
        {
            "max_text_chars": 100_000,
            "api_key_set": lambda self: {"test-key", "other-key"},
        },
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
    test_state.job_queue = InMemoryJobQueue(test_state)
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


def test_stream_canary_is_absent_from_response_and_audit(app_with_state):
    canary = "stream.canary.7f8d@example.com"
    with TestClient(app_with_state) as client:
        resp = client.post(
            "/v1/redact/stream",
            json={"text": f"Email {canary}", "chunk_chars": 1000},
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 200
        chunks = list(resp.iter_lines())

    assert canary not in "\n".join(chunks)
    assert canary not in repr(app_with_state.state.state.audit.records)


def test_stream_emits_trace_without_input_values(monkeypatch, app_with_state):
    from app.api import stream

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(stream, "stream_tracer", provider.get_tracer("test"))
    canary = "stream.trace.canary.7f8d@example.com"

    with TestClient(app_with_state) as client:
        response = client.post(
            "/v1/redact/stream",
            json={"text": f"Email {canary}", "chunk_chars": 1000},
            headers={"X-API-Key": "test-key"},
        )
        list(response.iter_lines())

    assert response.status_code == 200
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "redax.redact.stream"
    assert spans[0].attributes == {
        "http.request.method": "POST",
        "http.response.status_code": 200,
    }
    assert canary not in repr(spans[0])
    assert app_with_state.state.state.audit.records[0].trace_id


async def test_stream_cancellation_is_bounded_and_does_not_audit(app_with_state, capsys):
    class BlockingRedactor:
        async def redact(self, text, policy=None, entity_types=None):
            await asyncio.Event().wait()

    app_with_state.state.state.redactor = BlockingRedactor()
    stream_router = next(
        included.original_router
        for included in app_with_state.routes
        if getattr(getattr(included, "original_router", None), "routes", None)
        and any(route.path == "/v1/redact/stream" for route in included.original_router.routes)
    )
    route = next(route for route in stream_router.routes if route.path == "/v1/redact/stream")
    canary = "stream.cancel.canary.7f8d@example.com"
    response = await route.endpoint(
        None,
        StreamRequest(text=f"Email {canary}", chunk_chars=1000),
        app_with_state.state.state,
        "test-key",
        "request-cancelled",
    )

    task = asyncio.create_task(response.body_iterator.__anext__())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert app_with_state.state.state.audit.records == []
    assert canary not in capsys.readouterr().out


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
    from app.observability.metrics import queue_depth

    canary = "job.canary.7f8d@example.com"
    before_depth = queue_depth()
    with TestClient(app_with_state) as client:
        sub = client.post(
            "/v1/jobs", json={"text": f"hi {canary}"}, headers={"X-API-Key": "test-key"}
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
    assert canary not in body["result"]["text"]
    assert canary not in repr(app_with_state.state.state.job_store.records)
    assert canary not in repr(app_with_state.state.state.audit.records)
    assert queue_depth() == before_depth


@pytest.fixture
def app_with_no_redactor():
    test_state = State()
    test_state.settings = type(
        "S", (), {"max_text_chars": 1000, "api_key_set": lambda self: {"test-key"}}
    )()
    test_state.job_store = InMemoryJobStore()
    test_state.job_queue = InMemoryJobQueue(test_state)
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
    test_state.job_queue = InMemoryJobQueue(test_state)
    test_state.audit = MemoryAudit()
    test_state.ready = True
    app = FastAPI()
    app.state.state = test_state
    register_jobs(app)
    return app


def test_durable_worker_completes_slow_job(app_with_slow_redactor):
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
    assert app_with_slow_redactor.state.state.job_store.records[job_id].status == "done"
    assert asyncio.run(app_with_slow_redactor.state.state.job_store.count_inflight()) == 0


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


def test_job_result_is_private_to_the_submitting_api_key(app_with_state):
    with TestClient(app_with_state) as client:
        sub = client.post(
            "/v1/jobs", json={"text": "hi a@b.com"}, headers={"X-API-Key": "test-key"}
        )
        assert sub.status_code == 202
        job_id = sub.json()["id"]
        response = client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": "other-key"})
    assert response.status_code == 404


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
    test_state.job_queue = InMemoryJobQueue(test_state)
    test_state.audit = MemoryAudit()
    test_state.ready = True
    app = FastAPI()
    app.state.state = test_state
    register_jobs(app)
    return app


def test_job_submission_rejected_when_inflight_full(app_with_max_inflight):
    store = app_with_max_inflight.state.state.job_store
    asyncio.run(store.create(owner="test-key"))
    with TestClient(app_with_max_inflight) as client:
        resp = client.post(
            "/v1/jobs", json={"text": "more text"}, headers={"X-API-Key": "test-key"}
        )
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
    test_state.job_queue = InMemoryJobQueue(test_state)
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
    test_state.job_queue = InMemoryJobQueue(test_state)
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
