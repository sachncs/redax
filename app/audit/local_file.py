from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from app.audit.backend import AuditEvent, event_to_dict


class LocalFileAuditBackend:
    """Append-only JSONL audit log with a single background flusher.

    Writes are coalesced through an asyncio.Queue and drained by a task
    that holds the file descriptor open across writes (so heavy redaction
    traffic doesn't open+close the file per event). File I/O runs in the
    default executor so it doesn't block the event loop.
    """

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._queue: asyncio.Queue[AuditEvent] | None = None
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopped = asyncio.Event()
        self._dropped = 0

    async def start(self) -> None:
        # Ensure parent directory exists synchronously so the very first
        # append has somewhere to land.
        self._path.parent.mkdir(parents=True, exist_ok=True)
        Path(self._path).touch(exist_ok=True)
        self._queue = asyncio.Queue(maxsize=10000)
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._drain())

    async def stop(self) -> None:
        if self._queue is not None:
            await self._queue.put(_SENTINEL)
        if self._task is not None:
            await self._task
        self._loop = None

    async def record(self, event: AuditEvent) -> None:
        if self._queue is None:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._dropped += 1

    async def _drain(self) -> None:
        assert self._queue is not None and self._loop is not None
        loop = self._loop
        while True:
            item = await self._queue.get()
            if item is _SENTINEL:
                return
            try:
                line = json.dumps(event_to_dict(_with_timestamp(item))) + "\n"
                await loop.run_in_executor(None, _append_line, str(self._path), line)
            except Exception:
                pass


_SENTINEL: AuditEvent = AuditEvent(request_id="", ts="", policy_version="", text_chars=0)


def _append_line(path: str, line: str) -> None:
    with open(path, "a", encoding="utf-8") as fp:
        fp.write(line)


def _with_timestamp(event: AuditEvent) -> AuditEvent:
    if event.ts:
        return event
    return AuditEvent(
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
