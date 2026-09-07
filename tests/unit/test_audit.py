from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.audit.backend import Backend, Event
from app.audit.file import FileAudit


@pytest.mark.asyncio
async def test_writes_jsonl_line(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    backend = FileAudit(str(path))
    await backend.start()
    event = Event(
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
    backend = FileAudit(str(path))
    await backend.start()
    backend.queue = asyncio.Queue(maxsize=2)
    for _ in range(5):
        await backend.record(Event(request_id="x", ts="t", policy_version="p", text_chars=0))
    assert backend.dropped >= 1
    await backend.stop()


def test_local_file_satisfies_protocol() -> None:
    backend = FileAudit("/tmp/r.jsonl")
    assert isinstance(backend, Backend)


def test_rotate_if_needed_moves_full_log_and_shifts_backups(tmp_path: Path) -> None:
    from app.audit.file import rotate_if_needed

    path = tmp_path / "audit.jsonl"
    path.write_text("line1\n" * 1000)
    rotate_if_needed(path, max_bytes=100, rotation_backups=3)
    assert not path.exists() or path.stat().st_size == 0
    backup = tmp_path / "audit.jsonl.1"
    assert backup.exists()
    assert len(backup.read_text().splitlines()) == 1000
    path.write_text("x" * 500)
    rotate_if_needed(path, max_bytes=100, rotation_backups=3)
    assert (tmp_path / "audit.jsonl.2").exists()
    assert not (tmp_path / "audit.jsonl.3").exists()


def test_rotate_without_backups_truncates(tmp_path: Path) -> None:
    from app.audit.file import rotate_if_needed

    path = tmp_path / "audit.jsonl"
    path.write_text("line1\n" * 1000)
    rotate_if_needed(path, max_bytes=100, rotation_backups=0)
    assert path.exists()
    assert path.stat().st_size == 0
    assert not (tmp_path / "audit.jsonl.1").exists()


def test_append_line_rotates_then_writes(tmp_path: Path, monkeypatch) -> None:
    from app.audit.file import append_line

    spy = []
    monkeypatch.setattr("app.audit.file.rotate_if_needed", lambda *a: spy.append(a))
    path = tmp_path / "audit.jsonl"
    append_line(path, "abc\n", fsync=False, max_bytes=100, rotation_backups=2)
    assert spy and path.read_text() == "abc\n"


def test_prune_old_events_drops_expired_and_keeps_recent(tmp_path: Path) -> None:
    from app.audit.file import prune_old_events

    path = tmp_path / "audit.jsonl"
    old = datetime.now(UTC) - timedelta(days=30)
    new = datetime.now(UTC) - timedelta(minutes=5)
    path.write_text(
        json.dumps({"ts": old.isoformat(), "request_id": "old"})
        + "\n"
        + json.dumps({"ts": new.isoformat(), "request_id": "new"})
        + "\n"
        + "not-json\n"
    )
    prune_old_events(path, retention_seconds=3600)
    remaining = path.read_text().splitlines()
    ids = [json.loads(line)["request_id"] for line in remaining if line != "not-json"]
    assert ids == ["new"]
    assert "not-json" in remaining


def test_prune_is_a_noop_when_nothing_expired(tmp_path: Path) -> None:
    from app.audit.file import prune_old_events

    path = tmp_path / "audit.jsonl"
    new = datetime.now(UTC).isoformat()
    path.write_text(json.dumps({"ts": new}) + "\n")
    prune_old_events(path, retention_seconds=3600)
    assert path.read_text() == json.dumps({"ts": new}) + "\n"
