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
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from app.audit.backend import Event, signed_event_payload, with_timestamp
from app.logging import get_logger
from app.observability import AUDIT_DROPPED, AUDIT_UNINITIALISED, AUDIT_WRITE_FAILED

__all__ = ["FileAudit", "with_timestamp"]


class FileAudit:
    """Append-only JSONL audit log with a single background flusher.

    Writes are coalesced through an ``asyncio.Queue`` and drained by a
    task that holds the file descriptor open across writes (so heavy
    redaction traffic doesn't open+close the file per event). File I/O
    runs in the default executor so it doesn't block the event loop.

    Hardening is configurable: optional fsync per line, size-based
    rotation with a bounded backup count, and a retention window
    enforced on startup.

    Dropped events (queue full) are counted both on the instance
    (``dropped``) and on the global Prometheus counter
    ``redax_audit_dropped_total{backend="file"}`` so an operator can
    alert on audit data loss.

    Attributes:
        path: Destination JSONL file.
        fsync: ``True`` to flush + ``os.fsync`` every line.
        max_bytes: Rotation threshold; 0 disables rotation.
        rotation_backups: How many ``.1`` .. ``.N`` backups to keep.
        retention_seconds: Lines older than this are pruned at startup.
        dropped: Count of events dropped because the queue was full.
        backend_label: Label value used when incrementing
            ``redax_audit_dropped_total``; defaults to ``"file"``.
    """

    def __init__(
        self,
        path: str,
        fsync: bool = True,
        required: bool = False,
        max_bytes: int = 1_000_000_000,
        rotation_backups: int = 5,
        retention_seconds: int = 90 * 24 * 3600,
        backend_label: str = "file",
        integrity_key: str = "",
    ) -> None:
        self.path = Path(path)
        self.fsync = fsync
        self.required = required
        self.max_bytes = max_bytes
        self.rotation_backups = rotation_backups
        self.retention_seconds = retention_seconds
        self.backend_label = backend_label
        self.integrity_key = integrity_key
        self.queue: asyncio.Queue[Event] | None = None
        self.task: asyncio.Task[None] | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.dropped = 0
        self.failed = False

    async def start(self) -> None:
        """Open the destination file and start the background flusher."""
        self.failed = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self.loop = asyncio.get_running_loop()
        await self.loop.run_in_executor(None, prune_old_events, self.path, self.retention_seconds)
        self.queue = asyncio.Queue(maxsize=10000)
        self.task = asyncio.create_task(self.drain())

    async def stop(self) -> None:
        """Flush pending writes and stop the background flusher."""
        task = self.task
        queue = self.queue
        if task is None:
            self.queue = None
            self.loop = None
            return
        if not task.done() and queue is not None:
            try:
                async with asyncio.timeout(1.0):
                    await queue.put(SENTINEL)
            except (TimeoutError, RuntimeError):
                task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            # Shutdown must remain best-effort; consume a failed drain task so
            # its exception cannot become an unobserved-task warning.
            get_logger("redax.audit").warning(
                "redax.audit_drain_stop_failed", error=exc.__class__.__name__
            )
        self.task = None
        self.queue = None
        self.loop = None

    async def record(self, event: Event) -> None:
        """Enqueue one event; drop if the queue is full.

        Args:
            event: The audit event to persist.
        """
        if self.queue is None:
            AUDIT_UNINITIALISED.labels(backend=self.backend_label).inc()
            get_logger("redax.audit").warning(
                "redax.audit_uninitialised", backend=self.backend_label
            )
            if self.required:
                raise RuntimeError("audit backend is not initialized")
            return
        if self.failed and self.required:
            raise RuntimeError("audit backend is unavailable")
        if self.required:
            if self.loop is None:
                raise RuntimeError("audit backend loop is not initialized")
            line = json.dumps(signed_event_payload(event, self.integrity_key)) + "\n"
            try:
                await self.loop.run_in_executor(
                    None,
                    append_line,
                    self.path,
                    line,
                    self.fsync,
                    self.max_bytes,
                    self.rotation_backups,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                self.failed = True
                get_logger("redax.audit").warning(
                    "redax.audit_write_failed",
                    backend=self.backend_label,
                    error=exc.__class__.__name__,
                )
                AUDIT_WRITE_FAILED.labels(backend=self.backend_label).inc()
                raise RuntimeError("audit backend write failed") from exc
            return
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull as exc:
            self.dropped += 1
            AUDIT_DROPPED.labels(backend=self.backend_label).inc()
            if self.required:
                raise RuntimeError("audit queue is full") from exc

    async def drain(self) -> None:
        """Drain queued events to disk until a sentinel arrives."""
        if self.queue is None or self.loop is None:
            raise RuntimeError("audit backend is not initialized")
        log = get_logger("redax.audit")
        loop = self.loop
        while True:
            item = await self.queue.get()
            if item is SENTINEL:
                return
            line = json.dumps(signed_event_payload(item, self.integrity_key)) + "\n"
            try:
                await loop.run_in_executor(
                    None,
                    append_line,
                    self.path,
                    line,
                    self.fsync,
                    self.max_bytes,
                    self.rotation_backups,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                self.failed = True
                log.warning(
                    "redax.audit_write_failed",
                    backend=self.backend_label,
                    error=exc.__class__.__name__,
                )
                AUDIT_WRITE_FAILED.labels(backend=self.backend_label).inc()


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
