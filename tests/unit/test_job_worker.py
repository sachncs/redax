from __future__ import annotations

import pytest

from app.jobs import queue


class Store:
    pass


class State:
    job_store = Store()


@pytest.mark.asyncio
async def test_process_job_retries_before_dead_letter(monkeypatch):
    calls: list[bool] = []

    async def failed_run(*_args, **kwargs):
        calls.append(kwargs["mark_failure"])
        return False

    async def failure(*_args, **_kwargs):
        calls.append(True)

    monkeypatch.setattr(queue, "run_job", failed_run)
    monkeypatch.setattr(queue, "record_failure", failure)

    with pytest.raises(queue.Retry) as raised:
        await queue.process_job(
            {"state": State(), "job_try": 1}, "job-1", {"text": "x"}, "request-1"
        )

    assert raised.value.defer_score == 1000
    assert calls == [False]


@pytest.mark.asyncio
async def test_process_job_records_failure_after_final_attempt(monkeypatch):
    calls: list[str] = []

    async def failed_run(*_args, **_kwargs):
        return False

    async def failure(*_args, **_kwargs):
        calls.append("failed")

    monkeypatch.setattr(queue, "run_job", failed_run)
    monkeypatch.setattr(queue, "record_failure", failure)

    await queue.process_job(
        {"state": State(), "job_try": queue.MAX_TRIES}, "job-1", {"text": "x"}, "request-1"
    )

    assert calls == ["failed"]
