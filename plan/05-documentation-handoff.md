# Phase 5 — Documentation and handoff

## Objective

Make the local deployment usable by someone who did not implement it and keep
local testing clearly separated from production launch requirements.

## Work

- Create `docs/local-deployment.md` covering prerequisites, `.env` setup,
  startup, shutdown, full reset, logs, service URLs, health checks, Redis
  backup/restore, Grafana access, and k6 usage.
- Include the local service URL table:
  - API: `http://localhost:8000`
  - Grafana: `http://localhost:3000`
  - Prometheus: `http://localhost:9090`
  - Redis/collector/Loki/Tempo: internal unless an operator intentionally
    publishes a debug port.
- Add troubleshooting for model image builds, readiness failures, stale
  volumes, Redis recovery, collector startup, Docker Desktop mounts, and
  insufficient local resources.
- Link the new guide from `README.md` and `docs/deployment.md`.
- State plainly that local Compose is production-like testing, not proof of
  managed Redis failover, multi-node availability, public TLS, or the hosted
  production launch gate.
- Commit the work in atomic milestone-tagged commits and push after each
  focused implementation phase, following `AGENTS.md`.

## Deliverables

- `docs/local-deployment.md` and links from the main docs.
- A final validation summary with commands, services, ports, assumptions, and
  known limitations.
- Atomic commits pushed to the configured remote.

## Exit gate

Another developer can clone the repository, follow the local guide, start the
stack, run the smoke/load checks, inspect all local telemetry, back up Redis,
and reset the environment without needing a cloud account or undocumented
manual steps.

