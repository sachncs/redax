from __future__ import annotations

import httpx
import pytest

from scripts.load_bench import (
    benchmark_text,
    pinned_model_metadata,
    request_payload,
    run_job_once,
    stream_completed,
)


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("redact", {"text": "synthetic"}),
        ("batch", {"items": [{"text": "synthetic"}, {"text": "synthetic"}]}),
        ("stream", {"text": "synthetic", "chunk_chars": 100}),
        ("job", {"text": "synthetic"}),
        ("model", {"text": "synthetic"}),
        ("cache-hot", {"text": "synthetic"}),
        ("cache-cold", {"text": "synthetic"}),
    ],
)
def test_request_payload_builds_bounded_synthetic_workload(mode: str, expected: dict) -> None:
    assert request_payload(mode, "synthetic") == expected


def test_request_payload_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="unsupported benchmark mode"):
        request_payload("unknown", "synthetic")


def test_benchmark_text_separates_cold_cache_requests() -> None:
    assert benchmark_text("cache-hot", "synthetic", 4) == "synthetic"
    assert benchmark_text("cache-cold", "synthetic", 4) == "synthetic request-4"


def test_pinned_model_metadata_reads_committed_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDAX_MODEL_NAME", "fastino/GLiNER2-Guardrails-PII-Multi")
    monkeypatch.setenv("REDAX_MODEL_REVISION", "aad696b2f6815e3dfc2d95908129eea5ed598562")

    metadata = pinned_model_metadata()

    assert metadata["name"] == "fastino/GLiNER2-Guardrails-PII-Multi"
    assert metadata["revision"] == "aad696b2f6815e3dfc2d95908129eea5ed598562"
    assert len(metadata["manifest_sha256"]) == 64


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ('data: {"text": "safe"}\n\ndata: [DONE]\n\n', True),
        ('data: {"error": "internal error"}\n\n', False),
        ('data: {"text": "safe"}\n\n', False),
    ],
)
def test_stream_completed_requires_terminal_success(body: str, expected: bool) -> None:
    assert stream_completed(body) is expected


@pytest.mark.asyncio
async def test_run_job_once_measures_terminal_state_without_exposing_job_id() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(202, json={"id": "sensitive-job-id", "status": "queued"})
        return httpx.Response(200, json={"id": "sensitive-job-id", "status": "done"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        status = await run_job_once(
            client,
            "http://redax.test/v1/jobs",
            "synthetic",
            api_key="benchmark-key",
            timeout=1.0,
        )

    assert status == "done"
    assert calls == [("POST", "/v1/jobs"), ("GET", "/v1/jobs/sensitive-job-id")]
