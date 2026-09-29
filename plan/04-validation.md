# Phase 4 — Validation and load testing

## Objective

Prove the complete local stack works instead of stopping after generating
configuration files.

## Work

- Add `tests/load/basic.js` as a small k6 scenario with configurable base URL,
  virtual users, duration, API key, and representative request payload.
- Exercise `/healthz`, `/readyz`, `/metrics`, and one representative redaction
  endpoint. Exercise a background job when the local API contract permits it.
- Build all images with `docker compose build` and record the model/dependency
  download requirement for the first build.
- Start the stack with `docker compose up -d` and verify every container’s
  health state.
- Verify API-to-Redis connectivity, API-to-worker job completion, and
  persistence after a controlled restart.
- Verify metrics in Prometheus, dashboards in Grafana, traces in Tempo, and
  logs in Loki.
- Run the k6 scenario at the intended local traffic envelope and capture
  latency/error observations without treating a single-machine test as a
  production capacity claim.
- Run repository verification (`make PYTHON=.venv313/bin/python verify` when
  that environment exists), site checks if docs/site files change, and
  Compose configuration validation.
- Test failure paths: Redis unavailable, collector unavailable, a stopped
  worker, and a full `docker compose down` followed by restart.

## Deliverables

- `tests/load/basic.js`.
- Validation output and any fixes required by startup/runtime failures.
- A concise pass/fail record in the local deployment documentation or release
  notes.

## Exit gate

The complete stack starts from a clean checkout, passes health checks, serves
redaction traffic, persists required state, and all three observability paths
are verified locally. Any unsupported Docker Desktop behavior is documented
with a reproducible workaround.

