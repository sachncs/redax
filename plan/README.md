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
- **Existing Compose:** `redax`, `redax-worker`, Redis, OpenTelemetry
  Collector, Prometheus, Tempo, Loki, Promtail, and Grafana are defined in
  `docker-compose.yml`. Redis uses AOF plus RDB snapshots, and credentials
  are supplied through the ignored `.env` contract.
- **Ports:** API `8000`, Grafana `3000`, and Prometheus `9090` are published.
  Redis, OTLP, Loki, Tempo, and the worker remain internal by default.
- **Dependencies:** Redis backs jobs, cache, idempotency, rate limits, and
  optional Redis audit. The application does not require PostgreSQL, MySQL,
  MongoDB, or another database.
- **Health and metrics:** `/healthz` is liveness, `/readyz` is readiness, and
  `/metrics` exposes Prometheus metrics.
- **Logging and tracing:** structured JSON logs are written to stdout and
  routed by Promtail to local Loki; OTLP traces use the local Collector and
  Tempo; Prometheus scrapes `/metrics`; Grafana provisions all three sources.
- **Model behavior:** the image builds the pinned
  `fastino/GLiNER2-Guardrails-PII-Multi` snapshot into the image, so the first
  image build needs network access to download dependencies and the model.
  Runtime traffic remains local after the image is built. Redax currently uses
  the checkpoint's PII extraction interface, not its separate safety head.
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

## Phase completion record

The local deployment phases are implemented and verified in order:

| Phase | Evidence |
|---|---|
| 0. Baseline | This topology, service, port, volume, and environment contract |
| 1. Compose foundation | `docker compose config --quiet`; image build; health-gated startup |
| 2. Observability | `scripts/verify_local_compose.py` confirms Prometheus, Loki, Tempo, and Grafana paths |
| 3. Security and persistence | `.env` is ignored; Redis AOF/RDB, named volumes, bounded JSON logs, and intentional published ports |
| 4. Validation | API/worker redaction, Redis-backed job completion, and verification after container restart |
| 5. Handoff | [`docs/local-deployment.md`](../docs/local-deployment.md), k6 scenario, backup/restore, reset, and troubleshooting instructions |

The verification is a single-machine local contract check. It does not prove
managed Redis failover, multi-node availability, public DNS/TLS, or production
capacity.
