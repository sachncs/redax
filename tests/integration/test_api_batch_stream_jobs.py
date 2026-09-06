from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import register_batch, register_jobs, register_stream
from app.inference.detector import Span
from app.jobs.store import JobStore
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


class _InMemoryJobStore(JobStore):
    def __init__(self) -> None:
        self._records: dict[str, dict] = {}

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def create(self):
        import uuid

        from app.jobs.store import JobRecord

        rec = JobRecord(id=uuid.uuid4().hex, status="queued", result=None, error=None)
        self._records[rec.id] = rec
        return rec

    async def get(self, job_id):
        return self._records.get(job_id)

    async def set_status(self, job_id, status):
        self._records[job_id].status = status

    async def set_result(self, job_id, result):
        self._records[job_id].result = result
        self._records[job_id].status = "done"

    async def set_error(self, job_id, error):
        self._records[job_id].error = error
        self._records[job_id].status = "failed"


@pytest.fixture
def app_with_state(monkeypatch):
    test_state = ModelState()
    test_state.settings = type(
        "S",
        (),
        {"max_text_chars": 1000, "api_key_set": lambda: set()},
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
    test_state.job_store = _InMemoryJobStore()
    test_state.ready = True
    monkeypatch.setattr("app.state.model_state", test_state)
    app = FastAPI()
    register_batch(app)
    register_stream(app)
    register_jobs(app)
    return app


def test_batch_returns_results_for_each_item(app_with_state):
    with TestClient(app_with_state) as client:
        resp = client.post(
            "/v1/redact/batch",
            json={"items": [{"text": "hi a@b.com"}, {"text": "nothing"}]},
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
        )
        assert resp.status_code == 200
        chunks = list(resp.iter_lines())
    assert any("[DONE]" in c for c in chunks)


def test_job_lifecycle(app_with_state):
    with TestClient(app_with_state) as client:
        sub = client.post("/v1/jobs", json={"text": "hi a@b.com"})
        assert sub.status_code == 202
        job_id = sub.json()["id"]
        deadline = 5.0
        import time

        start = time.time()
        while time.time() - start < deadline:
            r = client.get(f"/v1/jobs/{job_id}")
            if r.json()["status"] == "done":
                break
            time.sleep(0.05)
        body = client.get(f"/v1/jobs/{job_id}").json()
    assert body["status"] == "done"
    assert body["result"]["text"] == "hi [REDACTED]"


def test_job_not_found(app_with_state):
    with TestClient(app_with_state) as client:
        r = client.get("/v1/jobs/does-not-exist")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["status"] == 404
    assert body["title"] == "Job not found"
