from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import main
from app.state import State


class StopRefresh(Exception):
    """Stop the periodic loop after one recovery attempt."""


class RecoveringStore:
    def __init__(self) -> None:
        self.client = None
        self.started = 0

    async def start(self) -> None:
        self.started += 1
        self.client = object()

    async def oldest_job_age_seconds(self) -> float:
        return 0.0

    async def active_worker_count(self) -> int:
        return 0

    async def worker_capacity(self) -> dict[str, int]:
        return {"active": 0, "max": 1}

    def pool_stats(self) -> dict[str, int]:
        return {"in_use": 0, "available": 1, "max": 1}


@pytest.mark.asyncio
async def test_refresh_job_metrics_reconnects_store_and_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = RecoveringStore()
    queue = object()
    state = State(settings=SimpleNamespace(), job_store=store)

    async def create_queue(_settings: object) -> object:
        return queue

    async def stop_after_one_cycle(_seconds: float) -> None:
        raise StopRefresh

    monkeypatch.setattr(main, "create_job_queue", create_queue)
    monkeypatch.setattr(main.asyncio, "sleep", stop_after_one_cycle)

    with pytest.raises(StopRefresh):
        await main.refresh_job_metrics(state)

    assert store.started == 1
    assert state.job_queue is queue
