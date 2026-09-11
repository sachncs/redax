"""Redax FastAPI entrypoint.

Defines the application lifespan that wires the detector registry,
redactor, optional pipeline, audit backend, and Redis job store into
``app.state.state``. Also exposes ``run()`` for ``python -m app.main``.
"""

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
from app.audit.file import FileAudit
from app.config import Settings
from app.errors import install_error_handlers
from app.inference.gliner2 import GLiNER2Detector
from app.inference.regex import RegexDetector
from app.inference.registry import DetectorRegistry
from app.jobs.store import JobStore
from app.logging import configure_logging, get_logger
from app.middleware import register_request_context
from app.observability import configure_tracing
from app.redaction.circuit.breaker import Breaker
from app.redaction.pipeline import Pipeline
from app.redaction.redactor import Redactor
from app.redaction.stages.gate import Gate
from app.redaction.stages.model import ModelStage
from app.redaction.strategy import Deid, Hash, Mask, Regex, Skip, Strategy
from app.state import State


async def build_state(settings: Settings) -> State:
    """Construct a fully-populated ``State`` for the running app.

    Wires the regex detector, GLiNER2 detector, redactor, optional
    pipeline, audit backend, and Redis job store. Failures during
    detector loading propagate (the app refuses to start); Redis being
    unavailable is logged and downgraded to ``job_store=None`` so the
    HTTP surface still serves traffic.

    Args:
        settings: The validated pydantic-settings ``Settings``.

    Returns:
        A ``State`` with every long-lived resource populated.
    """
    log = get_logger("redax.lifespan")

    regex = RegexDetector()
    await regex.warmup()

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
        except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
            log.error(
                "redax.detector_load_failed",
                model=settings.model_name,
                revision=settings.model_revision,
                error=exc.__class__.__name__,
            )
            raise
        detectors.append(gliner2)
        active: Any = gliner2
    else:
        # REDAX_DETECTOR=regex is the only opt-in for the fallback path.
        active = regex

    registry = DetectorRegistry(detectors)

    strategies: dict[str, Strategy] = {
        "passThrough": Skip(),
        "mask": Mask(),
        "hash": Hash(salt=settings.hash_salt),
        "regex": Regex(detector=regex),
        "autoDeID": Deid(active, detectors=registry, max_passes=settings.multi_pass_max),
    }
    redactor = Redactor(
        detector=active,
        strategies=strategies,
        replacement="[REDACTED]",
    )

    pipeline: Pipeline | None = None
    if active is not regex:
        pipeline = Pipeline(
            regex_gate=Gate(detector=regex),
            model_stage=ModelStage(detector=active),
            model_breaker=Breaker(
                name="model",
                threshold=settings.pipeline_breaker_threshold,
                cooldown_s=settings.pipeline_breaker_cooldown_s,
            ),
        )

    store = JobStore(settings.redis_url, ttl_seconds=settings.job_ttl_seconds)
    try:
        await store.start()
        job_store: JobStore | None = store
    except Exception as exc:
        log.warning("redax.redis_unavailable", error=str(exc))
        job_store = None
    if job_store is None:
        log.warning(
            "redax.cache_disabled",
            note="idempotency and response caches skipped until Redis recovers",
        )

    audit = FileAudit(
        settings.audit_path,
        fsync=settings.audit_fsync,
        max_bytes=settings.audit_max_bytes,
        rotation_backups=settings.audit_rotation_backups,
        retention_seconds=settings.audit_retention_seconds,
    )
    await audit.start()

    return State(
        ready=False,
        detector=active,
        regex_detector=regex,
        redactor=redactor,
        audit=audit,
        settings=settings,
        job_store=job_store,
        pipeline=pipeline,
    )


async def teardown_state(state: State) -> None:
    """Stop and release every long-lived resource on ``state``.

    Idempotent: each handler tolerates being called once on a partially
    populated state (e.g. Redis never came up). Errors during shutdown
    are logged but never re-raised so the lifespan finaliser always
    completes and the process can exit cleanly.

    Args:
        state: The ``State`` whose resources should be released.
    """
    log = get_logger("redax.lifespan")
    try:
        if state.audit is not None:
            await state.audit.stop()
    except Exception as exc:
        log.warning("redax.audit_stop_failed", error=exc.__class__.__name__)
    try:
        if state.job_store is not None:
            await state.job_store.stop()
    except Exception as exc:
        log.warning("redax.job_store_stop_failed", error=exc.__class__.__name__)
    state.ready = False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialise and tear down long-lived resources for the FastAPI app.

    Args:
        app: The FastAPI instance being brought up.

    Yields:
        ``None`` once every resource is wired into ``app.state.state``.
    """
    settings = Settings()
    settings.verify()
    configure_logging(settings.log_level)
    configure_tracing(settings.service_name, settings.otlp_endpoint)
    log = get_logger("redax.lifespan")

    state = await build_state(settings)
    app.state.state = state

    log.info(
        "redax.startup",
        log_level=settings.log_level,
        detector=state.detector.name if state.detector is not None else "",
        model=settings.model_name,
        revision=settings.model_revision,
        redis=state.job_store is not None,
    )
    state.ready = True
    try:
        yield
    finally:
        log.info("redax.shutdown")
        await teardown_state(state)


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
    """Boot uvicorn with the redax application entrypoint.

    Honours ``settings.host`` and ``settings.port``. Structured logging is
    already configured by ``lifespan`` so ``log_config`` is disabled here.
    """
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
