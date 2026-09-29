from __future__ import annotations

import pytest

from app.audit.backend import Event
from app.audit.file import FileAudit


@pytest.mark.asyncio
async def test_required_audit_rejects_uninitialized_backend(tmp_path) -> None:
    backend = FileAudit(str(tmp_path / "audit.jsonl"), required=True)

    with pytest.raises(RuntimeError, match="not initialized"):
        await backend.record(Event(request_id="req", ts="", policy_version="p", text_chars=1))


@pytest.mark.asyncio
async def test_required_audit_rejects_after_write_failure(tmp_path) -> None:
    backend = FileAudit(str(tmp_path / "audit.jsonl"), required=True)
    backend.failed = True
    backend.queue = object()  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="unavailable"):
        await backend.record(Event(request_id="req", ts="", policy_version="p", text_chars=1))
