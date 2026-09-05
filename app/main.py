from __future__ import annotations

from contextlib import asynccontextmanager

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
from app.inference.regex_detector import RegexDetector
from app.jobs.store import JobStore
from app.logging import configure_logging, get_logger
from app.observability import configure_tracing
from app.redaction.redactor import Redactor
from app.redaction.strategy import AutoDeID, Hash, Mask, PassThrough, Regex
from app.state import model_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    configure_logging(settings.log_level)
    configure_tracing(settings.service_name, settings.otlp_endpoint)
    log = get_logger("redax.lifespan")

    model_state.settings = settings
    model_state.ready = False

    regex = RegexDetector()
    await regex.warmup()
    model_state.regex_detector = regex
    model_state.detector = regex

    strategies = {
        "passThrough": PassThrough(),
        "mask": Mask(),
        "hash": Hash(salt=settings.hash_salt),
        "regex": Regex(),
        "autoDeID": AutoDeID(regex),
    }
    model_state.redactor = Redactor(
        detector=regex,
        strategies=strategies,
        replacement="[REDACTED]",
    )

    store = JobStore(settings.redis_url)
    try:
        await store.start()
        model_state.job_store = store
    except Exception as exc:
        log.warning("redax.redis_unavailable", error=str(exc))
        model_state.job_store = None

    audit = LocalFileAuditBackend(settings.audit_path)
    await audit.start()
    model_state.audit = audit

    log.info(
        "redax.startup",
        log_level=settings.log_level,
        detector="regex",
        model=settings.model_name,
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
