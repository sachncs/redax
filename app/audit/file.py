"""Append-only JSONL audit log with a single background flusher.

Writes are coalesced through an ``asyncio.Queue`` and drained by a task
that holds the file descriptor open across writes (so heavy redaction
traffic doesn't open+close the file per event). File I/O runs in the
default executor so it doesn't block the event loop.

Hardening is configurable: optional fsync per line, size-based rotation
with a bounded backup count, and a retention window enforced on
startup.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from app.audit.backend import Event, event_to_dict


class FileAudit:
    """Append-only JSONL audit log with a single background flusher.

    Writes are coalesced through an ``asyncio.Queue`` and drained by a
    task that holds the file descriptor open across writes (so heavy
    redaction traffic doesn't open+close the file per event). File I/O
    runs in the default executor so it doesn't block the event loop.

    Hardening is configurable: optional fsync per line, size-based
    rotation with a bounded backup count, and a retention window
    enforced on startup.

    Attributes:
        path: Destination JSONL file.
        fsync: ``True`` to flush + ``os.fsync`` every line.
        max_bytes: Rotation threshold; 0 disables rotation.
        rotation_backups: How many ``.1`` .. ``.N`` backups to keep.
        retention_seconds: Lines older than this are pruned at startup.
        dropped: Count of events dropped because the queue was full.
    """

    def __init__(
        self,
        path: str,
        fsync: bool = True,
        max_bytes: int = 1_000_000_000,
        rotation_backups: int = 5,
        retention_seconds: int = 90 * 24 * 3600,
    ) -> None:
        self.path = Path(path)
        self.fsync = fsync
        self.max_bytes = max_bytes
        self.rotation_backups = rotation_backups
        self.retention_seconds = retention_seconds
        self.queue: asyncio.Queue[Event] | None = None
        self.task: asyncio.Task[None] | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.dropped = 0

    async def start(self) -> None:
        """Open the destination file and start the background flusher."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self.loop = asyncio.get_running_loop()
        await self.loop.run_in_executor(None, prune_old_events, self.path, self.retention_seconds)
        self.queue = asyncio.Queue(maxsize=10000)
        self.task = asyncio.create_task(self.drain())

    async def stop(self) -> None:
        """Flush pending writes and stop the background flusher."""
        if self.queue is not None:
            await self.queue.put(SENTINEL)
        if self.task is not None:
            await self.task
        self.loop = None

    async def record(self, event: Event) -> None:
        """Enqueue one event; drop if the queue is full.

        Args:
            event: The audit event to persist.
        """
        if self.queue is None:
            return
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            self.dropped += 1

    async def drain(self) -> None:
        """Drain queued events to disk until a sentinel arrives."""
        assert self.queue is not None and self.loop is not None
        loop = self.loop
        while True:
            item = await self.queue.get()
            if item is SENTINEL:
                return
            line = json.dumps(event_to_dict(with_timestamp(item))) + "\n"
            with contextlib.suppress(Exception):
                await loop.run_in_executor(
                    None,
                    append_line,
                    self.path,
                    line,
                    self.fsync,
                    self.max_bytes,
                    self.rotation_backups,
                )


SENTINEL: Event = Event(request_id="", ts="", policy_version="", text_chars=0)


def append_line(path: Path, line: str, fsync: bool, max_bytes: int, rotation_backups: int) -> None:
    """Append one JSONL line to ``path``, rotating first if needed."""
    rotate_if_needed(path, max_bytes, rotation_backups)
    with open(path, "a", encoding="utf-8") as fp:
        fp.write(line)
        if fsync:
            fp.flush()
            os.fsync(fp.fileno())


def rotate_if_needed(path: Path, max_bytes: int, rotation_backups: int) -> None:
    """Rotate the current log into path.1..path.{backups} once it is full.

    A rotation_backups of 0 truncates the file instead of keeping backups.
    """
    if max_bytes <= 0:
        return
    if not path.exists() or path.stat().st_size < max_bytes:
        return
    if rotation_backups <= 0:
        with open(path, "w", encoding="utf-8") as fp:
            fp.truncate()
        return
    for i in range(rotation_backups, 1, -1):
        src = Path(f"{path}.{i - 1}")
        if src.exists():
            src.rename(Path(f"{path}.{i}"))
    path.rename(Path(f"{path}.1"))


def prune_old_events(path: Path, retention_seconds: int) -> None:
    """Drop lines older than ``retention_seconds`` (startup maintenance).

    Lines without a parseable timestamp are kept. Never rewrites the file
    unless at least one line was removed, so a no-op startup is cheap.
    """
    if retention_seconds <= 0 or not path.exists():
        return
    cutoff = datetime.now(UTC).timestamp() - retention_seconds
    lines = path.read_text(encoding="utf-8").splitlines()
    kept: list[str] = []
    removed = False
    for line in lines:
        try:
            ts_value = json.loads(line).get("ts")
            if not ts_value:
                kept.append(line)
                continue
            if datetime.fromisoformat(ts_value).timestamp() >= cutoff:
                kept.append(line)
            else:
                removed = True
        except (ValueError, TypeError):
            kept.append(line)
    if removed:
        path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")


def with_timestamp(event: Event) -> Event:
    """Return a copy of ``event`` with ``ts`` set to now if it was empty."""
    if event.ts:
        return event
    return Event(
        request_id=event.request_id,
        ts=datetime.now(UTC).isoformat(),
        policy_version=event.policy_version,
        text_chars=event.text_chars,
        entities_detected=event.entities_detected,
        inference_ms=event.inference_ms,
        redactor_version=event.redactor_version,
        model_hash=event.model_hash,
        direction=event.direction,
    )
