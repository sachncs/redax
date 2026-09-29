"""Redax FastAPI entrypoint.

Defines the application lifespan that wires the detector registry,
redactor, optional pipeline, audit backend, and Redis job store into
``app.state.state``. Also exposes ``run()`` for ``python -m app.main``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from typing import Any

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import (
    register_batch,
    register_detect,
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

try:
    PROJECT_VERSION = package_version("redax")
except PackageNotFoundError:
    PROJECT_VERSION = "0.1.0"


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
    active: Any = regex
    if settings.detector == "gliner2":
        gliner2: GLiNER2Detector | None = GLiNER2Detector(
            model_name=settings.model_name,
            model_revision=settings.model_revision,
            model_cache=settings.model_cache,
            threshold=settings.model_threshold,
            device="cpu",
            concurrency=settings.inference_concurrency,
            local_files_only=True,
        )
        try:
            assert gliner2 is not None
            await gliner2.load()
            await gliner2.warmup()
        except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
            if settings.env == "prod":
                raise RuntimeError(
                    "configured GLiNER2 detector could not be loaded; "
                    "production startup refuses to downgrade to regex-only"
                ) from exc
            log.warning(
                "redax.detector_load_failed",
                model=settings.model_name,
                revision=settings.model_revision,
                error=exc.__class__.__name__,
            )
            gliner2 = None
        else:
            assert gliner2 is not None
            detectors.append(gliner2)
            active = gliner2
    # else: REDAX_DETECTOR=regex is the only opt-in for the fallback path.

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
    if settings.pipeline_enabled and active is not regex:
        pipeline = Pipeline(
            regex_gate=Gate(detector=regex),
            model_stage=ModelStage(detector=active),
            model_breaker=Breaker(
                name="model",
                threshold=settings.pipeline_breaker_threshold,
                cooldown_s=settings.pipeline_breaker_cooldown_s,
            ),
            digest_salt=settings.hash_salt,
        )

    store = JobStore(
        settings.redis_url,
        ttl_seconds=settings.job_ttl_seconds,
        namespace=settings.redis_namespace,
        connect_timeout_seconds=settings.redis_connect_timeout_seconds,
        socket_timeout_seconds=settings.redis_socket_timeout_seconds,
        max_connections=settings.redis_max_connections,
        dead_letter_max=settings.job_dead_letter_max,
    )
    try:
        await store.start()
        job_store: JobStore | None = store
        try:
            reaped = await store.reap_stale_jobs(settings.job_stale_seconds)
            if reaped:
                log.warning("redax.stale_jobs_reaped", count=reaped)
        except (OSError, RuntimeError, TimeoutError) as exc:
            log.warning("redax.stale_jobs_recovery_failed", error=exc.__class__.__name__)
    except Exception as exc:
        log.warning("redax.redis_unavailable", error=exc.__class__.__name__)
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
        request_admission=asyncio.Semaphore(settings.max_concurrent_requests),
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
    state.ready = False
    # Readiness must drop before any dependency is closed so a load balancer
    # can stop routing new work while the process drains existing work.
    timeout_seconds = float(getattr(state.settings, "shutdown_timeout_seconds", 30.0))
    deadline = asyncio.get_running_loop().time() + timeout_seconds

    async def close_component(name: str, close: Any) -> None:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            log.warning("redax.shutdown_timeout", component=name)
            return
        try:
            async with asyncio.timeout(remaining):
                await close()
        except TimeoutError:
            log.warning("redax.shutdown_timeout", component=name)
        except Exception as exc:
            log.warning(f"redax.{name}_stop_failed", error=exc.__class__.__name__)

    if state.job_queue is not None:
        await close_component("job_queue", state.job_queue.close)
    if state.audit is not None:
        await close_component("audit", state.audit.stop)
    if state.job_store is not None:
        await close_component("job_store", state.job_store.stop)


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
    if state.job_store is not None:
        try:
            redis_settings = RedisSettings.from_dsn(settings.redis_url)
            redis_settings.conn_timeout = max(1, int(settings.redis_connect_timeout_seconds))
            redis_settings.max_connections = settings.redis_max_connections
            redis_settings.retry_on_timeout = True
            state.job_queue = await create_pool(redis_settings)
        except Exception as exc:
            log.warning("redax.job_queue_unavailable", error=exc.__class__.__name__)
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
    version=PROJECT_VERSION,
    description="Self-hosted PII redaction engine.",
    lifespan=lifespan,
)

install_error_handlers(app)
register_request_context(app)

middleware_settings = Settings()
cors_origins = middleware_settings.cors_origin_list()
trusted_hosts = middleware_settings.trusted_host_list()
app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        cors_origins if cors_origins else (["*"] if middleware_settings.env == "dev" else [])
    ),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=(
        trusted_hosts if trusted_hosts else (["*"] if middleware_settings.env == "dev" else [])
    ),
)

register_health(app)
register_policies(app)
register_redact(app)
register_batch(app)
register_detect(app)
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
