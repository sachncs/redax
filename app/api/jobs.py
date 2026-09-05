from __future__ import annotations

import time

from fastapi import APIRouter, BackgroundTasks, FastAPI, Request
from pydantic import BaseModel, Field

from app.errors import internal_error
from app.jobs.store import JobStore
from app.observability import REQUESTS


class JobSubmit(BaseModel):
    text: str = Field(min_length=1)
    policy: dict | None = None
    entity_types: list[str] | None = None


def register(app: FastAPI) -> None:
    router = APIRouter()

    @router.post("/v1/jobs", status_code=202)
    async def submit_job(body: JobSubmit, background_tasks: BackgroundTasks) -> dict:
        from app.state import model_state

        endpoint = "POST /v1/jobs"
        method = "POST"
        store: JobStore | None = getattr(model_state, "job_store", None)
        if store is None:
            REQUESTS.labels(endpoint=endpoint, method=method, status="503").inc()
            return internal_error(None, "job store not initialized")  # type: ignore[arg-type]
        record = await store.create()
        background_tasks.add_task(run_job, record.id, body.model_dump(), store)
        REQUESTS.labels(endpoint=endpoint, method=method, status="202").inc()
        return {"id": record.id, "status": record.status}

    @router.get("/v1/jobs/{job_id}")
    async def get_job(job_id: str, request: Request) -> dict:
        from app.state import model_state

        endpoint = "GET /v1/jobs/{id}"
        method = "GET"
        store: JobStore | None = getattr(model_state, "job_store", None)
        if store is None:
            REQUESTS.labels(endpoint=endpoint, method=method, status="503").inc()
            return internal_error(request, "job store not initialized")  # type: ignore[return-value]
        record = await store.get(job_id)
        if record is None:
            REQUESTS.labels(endpoint=endpoint, method=method, status="404").inc()
            return {"type": "not_found", "status": 404, "title": "Job not found"}
        REQUESTS.labels(endpoint=endpoint, method=method, status="200").inc()
        return {
            "id": record.id,
            "status": record.status,
            "result": record.result,
            "error": record.error,
        }

    app.include_router(router)


async def run_job(job_id: str, payload: dict, store: JobStore) -> None:
    from app.state import model_state

    await store.set_status(job_id, "running")
    start = time.perf_counter()
    try:
        redactor = model_state.redactor
        assert redactor is not None
        result = await redactor.redact(
            payload["text"],
            policy=payload.get("policy"),
            entity_types=payload.get("entity_types"),
        )
        await store.set_result(
            job_id,
            {
                "text": result.text,
                "spans": [s.__dict__ for s in result.spans],
                "relex_map": result.relex_map,
                "inference_ms": int((time.perf_counter() - start) * 1000),
            },
        )
    except Exception as exc:
        await store.set_error(job_id, str(exc))
