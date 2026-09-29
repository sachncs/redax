# Redax local deployment plan

## Goal

Create a small, production-like Docker Compose deployment that runs entirely
on one Linux or Docker Desktop machine. It must not require AWS, GCP, Azure,
Cloudflare, Grafana Cloud, Upstash, Redis Cloud, Kubernetes, public DNS, or
any other managed service.

This plan covers the local deployment request while preserving the existing
production-launch work as a separate concern. Local readiness is not a claim
that the hosted production deployment is complete.

## Current repository findings

- **Application:** Python 3.13+, FastAPI, Uvicorn, Pydantic Settings.
- **Runtime processes:** `redax-server` serves the API; `redax-worker` runs
  ARQ background jobs.
- **Existing Compose:** `redax`, `redax-worker`, and `redis` are present in
  `docker-compose.yml`. Redis currently runs with persistence disabled even
  though a volume is declared. Configuration is hardcoded in the Compose
  file, including development secrets.
- **Ports:** API `8000`; the current Compose file exposes only that port.
  Planned local observability ports are Grafana `3000` and Prometheus `9090`.
  Redis, OTLP, Loki, and Tempo remain internal by default.
- **Dependencies:** Redis backs jobs, cache, idempotency, rate limits, and
  optional Redis audit. The application does not require PostgreSQL, MySQL,
  MongoDB, or another database.
- **Health and metrics:** `/healthz` is liveness, `/readyz` is readiness, and
  `/metrics` exposes Prometheus metrics.
- **Logging and tracing:** structured JSON logs are written to stdout;
  optional OTLP gRPC tracing is already supported through
  `REDAX_OTLP_ENDPOINT`. There is no local collector, Loki, Tempo, Prometheus,
  or Grafana configuration yet.
- **Model behavior:** the image builds the pinned GLiNER2 model into the
  image, so the first image build needs network access to download dependencies
  and the model. Runtime traffic remains local after the image is built.
- **Tests and scripts:** pytest, Ruff, mypy, deterministic verification,
  readiness validation, Locust load testing, and Docker build scripts already
  exist. A small k6 scenario is not present.

## Planned local topology

```text
client
  -> redax (8000)
       -> redis (internal)
       -> redax-worker (internal Redis queue)
       -> otel-collector (internal OTLP gRPC/HTTP)

redax /metrics -> prometheus (9090)
Docker JSON logs -> local log shipper -> loki (internal)
otel-collector traces -> tempo (internal)
prometheus + loki + tempo -> grafana (3000)
```

The Compose project will use one private bridge network. Only the API,
Grafana, and Prometheus ports are published for normal local use. Containers
refer to one another by Compose service name, never by `localhost`.

## Persistent state

- `redax-models`: pinned model cache.
- `redax-audit`: append-only local audit data.
- `redax-redis`: Redis AOF/RDB data.
- `redax-prometheus`: Prometheus time-series data.
- `redax-grafana`: dashboards and local users.
- `redax-loki`: local logs.
- `redax-tempo`: local traces.

## Files to create

- `.env.example`
- `observability/otel-collector-config.yaml`
- `observability/prometheus.yml`
- `observability/tempo.yaml`
- `observability/loki-config.yaml`
- `observability/promtail-config.yaml` (or an equivalent local log-shipping
  configuration if the final Compose design avoids Promtail)
- `observability/grafana/provisioning/datasources/datasources.yaml`
- `tests/load/basic.js`
- `docs/local-deployment.md`
- Phase-specific validation fixtures or scripts only if existing commands
  cannot verify a requirement.

## Files to modify

- `docker-compose.yml`: local services, health-gated startup, persistence,
  internal networking, environment loading, resource/log limits, and local
  observability wiring.
- `.gitignore`: ignore `.env` and local observability/runtime state where
  necessary, without hiding checked-in configuration.
- `Dockerfile`: only if the existing image needs a minimal local-build change;
  do not duplicate the existing pinned Python/model build logic.
- `app/config.py`, `app/logging.py`, or `app/observability/tracing.py`: only
  where required to make the local collector endpoints configurable and to
  preserve secret/payload redaction.
- `README.md` and `docs/deployment.md`: link to the local deployment guide
  without replacing the existing production guidance.

## Phases

1. [Repository baseline and contract](00-baseline.md)
2. [Local Compose foundation](01-compose-foundation.md)
3. [Local observability](02-observability.md)
4. [Security, persistence, and operational limits](03-security-persistence.md)
5. [Validation and load testing](04-validation.md)
6. [Documentation and handoff](05-documentation-handoff.md)

Each phase has an explicit exit gate. Implementation should proceed in order;
the next phase may consume outputs from earlier phases but must not silently
weaken their requirements.

