from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.audit.backend import AuditBackend, AuditEvent
from app.audit.local_file import LocalFileAuditBackend


@pytest.mark.asyncio
async def test_writes_jsonl_line(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    backend = LocalFileAuditBackend(str(path))
    await backend.start()
    event = AuditEvent(
        request_id="req-1",
        ts="",
        policy_version="default-1.0.0",
        text_chars=42,
        entities_detected=[{"type": "PERSON", "count": 1, "confidence_avg": 0.9}],
        inference_ms=12,
    )
    await backend.record(event)
    await backend.stop()
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["request_id"] == "req-1"
    assert obj["text_chars"] == 42
    assert obj["entities_detected"][0]["type"] == "PERSON"
    assert obj["ts"]  # auto-stamped


@pytest.mark.asyncio
async def test_drops_when_queue_full(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "audit.jsonl"
    backend = LocalFileAuditBackend(str(path))
    await backend.start()
    backend._queue = asyncio.Queue(maxsize=2)  # type: ignore[assignment]
    for _ in range(5):
        await backend.record(
            AuditEvent(
                request_id="x", ts="t", policy_version="p", text_chars=0
            )
        )
    assert backend._dropped >= 1
    await backend.stop()


def test_local_file_satisfies_protocol() -> None:
    backend = LocalFileAuditBackend("/tmp/r.jsonl")
    assert isinstance(backend, AuditBackend)
