# Phase 1 — Local Compose foundation

## Objective

Make the API, worker, and Redis run together reliably on one machine with
health-gated startup and durable local state.

## Work

- Refactor `docker-compose.yml` to load values from `.env` with safe defaults
  documented in `.env.example`; remove hardcoded credentials from the
  committed Compose file.
- Keep `redax` and `redax-worker` built from the existing Python 3.13 image.
- Configure Redis with AOF plus an appropriate snapshot policy, a persistent
  named volume, and a `redis-cli ping` health check.
- Set `REDAX_REDIS_REQUIRED=true` for the local Compose topology so readiness
  reflects the services that the worker and durable jobs actually need.
- Keep the API on `localhost:8000`; do not publish Redis or worker ports.
- Use a private Compose bridge network and service-name URLs such as
  `redis://redis:6379/0`.
- Add health checks and `depends_on: condition: service_healthy` for API,
  worker, Redis, and every critical observability dependency.
- Add bounded CPU/memory settings only where they are portable across Docker
  Compose implementations; document any platform-specific differences.

## Deliverables

- Updated `docker-compose.yml`.
- New `.env.example` and ignored local `.env` contract.
- Redis persistence and service health checks.

## Exit gate

`docker compose config` succeeds, the API and worker start after Redis is
healthy, `/healthz` returns 200, `/readyz` becomes ready, and a representative
redaction request plus one background job can complete using only local
containers.

