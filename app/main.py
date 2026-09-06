from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from app.api import (
    register_batch,
    register_health,
    register_jobs,
    register_policies,
    register_redact,
    register_stream,
)
from app.audit.local_file import LocalFileAuditBackend
from app.config import Settings
from app.errors import install_error_handlers
from app.inference.gliner2 import GLiNER2Detector
from app.inference.regex_detector import RegexDetector
from app.inference.registry import DetectorRegistry
from app.jobs.store import JobStore
from app.logging import configure_logging, get_logger
from app.middleware import register_request_context
from app.observability import configure_tracing
from app.redaction.redactor import Redactor
from app.redaction.strategy import AutoDeID, Hash, Mask, PassThrough, Regex, Strategy
from app.state import model_state


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    settings.verify()
    configure_logging(settings.log_level)
    configure_tracing(settings.service_name, settings.otlp_endpoint)
    log = get_logger("redax.lifespan")

    model_state.settings = settings
    model_state.ready = False

    regex = RegexDetector()
    await regex.warmup()
    model_state.regex_detector = regex

    detectors: list[Any] = [regex]
    if settings.detector == "gliner2":
        gliner2 = GLiNER2Detector(
            model_name=settings.model_name,
            model_revision=settings.model_revision,
            model_cache=settings.model_cache,
            threshold=settings.model_threshold,
            device="cpu",
            concurrency=settings.inference_concurrency,
            local_files_only=True,
        )
        try:
            await gliner2.load()
            await gliner2.warmup()
        except Exception:
            log.error(
                "redax.detector_load_failed",
                model=settings.model_name,
                revision=settings.model_revision,
                exc_info=True,
            )
            raise
        detectors.append(gliner2)
        active: Any = gliner2
    else:
        # REDAX_DETECTOR=regex is the only opt-in for the fallback path.
        active = regex

    registry = DetectorRegistry(detectors)
    model_state.detector = active

    strategies: dict[str, Strategy] = {
        "passThrough": PassThrough(),
        "mask": Mask(),
        "hash": Hash(salt=settings.hash_salt),
        "regex": Regex(detector=regex),
        "autoDeID": AutoDeID(active, detectors=registry, max_passes=settings.multi_pass_max),
    }
    model_state.redactor = Redactor(
        detector=active,
        strategies=strategies,
        replacement="[REDACTED]",
    )

    store = JobStore(settings.redis_url, ttl_seconds=settings.job_ttl_seconds)
    try:
        await store.start()
        model_state.job_store = store
    except Exception as exc:
        log.warning("redax.redis_unavailable", error=str(exc))
        model_state.job_store = None

    audit = LocalFileAuditBackend(
        settings.audit_path,
        fsync=settings.audit_fsync,
        max_bytes=settings.audit_max_bytes,
        rotation_backups=settings.audit_rotation_backups,
        retention_seconds=settings.audit_retention_seconds,
    )
    await audit.start()
    model_state.audit = audit

    log.info(
        "redax.startup",
        log_level=settings.log_level,
        detector=active.name,
        model=settings.model_name,
        revision=settings.model_revision,
        redis=model_state.job_store is not None,
    )
    model_state.ready = True
    try:
        yield
    finally:
        log.info("redax.shutdown")
        if model_state.audit is not None:
            await model_state.audit.stop()
        if model_state.job_store is not None:
            await model_state.job_store.stop()
        model_state.ready = False


app = FastAPI(
    title="Redax",
    version="0.1.0",
    description="Self-hosted PII redaction engine.",
    lifespan=lifespan,
)

install_error_handlers(app)
register_request_context(app)

register_health(app)
register_policies(app)
register_redact(app)
register_batch(app)
register_stream(app)
register_jobs(app)


def run() -> None:
    import uvicorn

    settings = Settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_config=None,
    )


if __name__ == "__main__":
    run()
