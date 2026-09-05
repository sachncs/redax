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
from app.config import Settings
from app.logging import configure_logging, get_logger
from app.observability import configure_tracing
from app.state import model_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    configure_logging(settings.log_level)
    configure_tracing(settings.service_name, settings.otlp_endpoint)
    log = get_logger("redax.lifespan")

    model_state.settings = settings
    model_state.ready = False

    log.info("redax.startup", log_level=settings.log_level, model=settings.model_name)
    model_state.ready = True
    try:
        yield
    finally:
        log.info("redax.shutdown")
        model_state.ready = False


app = FastAPI(
    title="Redax",
    version="0.1.0",
    description="Self-hosted PII redaction engine.",
    lifespan=lifespan,
)

register_health(app)
# Other route modules will be registered in later milestones.


def run() -> None:
    import uvicorn  # noqa: PLC0415

    settings = Settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_config=None,
    )


if __name__ == "__main__":
    run()
