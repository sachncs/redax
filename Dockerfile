FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --prefix=/install \
        fastapi>=0.115 \
        "uvicorn[standard]>=0.32" \
        "pydantic>=2.9" \
        "pydantic-settings>=2.6" \
        "structlog>=24.4" \
        "httpx>=0.27" \
        "redis>=5.2" \
        "arq>=0.26" \
        "prometheus-client>=0.21" \
        "opentelemetry-api>=1.27" \
        "opentelemetry-sdk>=1.27" \
        "opentelemetry-exporter-otlp>=1.27" \
        "transformers>=4.46" \
        "gliner>=0.2.13" \
        "optimum>=1.23" \
        "onnxruntime>=1.20" \
        "pyyaml>=6.0"

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    REDAX_MODEL_CACHE=/models \
    REDAX_AUDIT_PATH=/var/lib/redax/audit.jsonl \
    REDAX_POLICIES_DIR=/policies

RUN groupadd -r redax && useradd -r -g redax -d /app -s /sbin/nologin redax \
    && mkdir -p /app /models /var/lib/redax /policies \
    && chown -R redax:redax /app /models /var/lib/redax /policies

WORKDIR /app
COPY --from=builder /install /usr/local
COPY app /app/app
COPY policies /policies

USER redax

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/healthz', timeout=2).raise_for_status()" \
    || exit 1

CMD ["python", "-m", "app.main"]
