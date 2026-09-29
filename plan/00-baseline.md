# Phase 0 — Repository baseline and contract

## Objective

Translate the local-only request into verified repository facts and a stable
configuration contract before changing the runtime topology.

## Work

- Confirm the API, worker, Redis, model-cache, policy, and audit paths from
  the current source and image.
- Inventory every environment variable used by Compose and `Settings`.
- Decide which services are necessary: API, worker, Redis, OpenTelemetry
  Collector, Prometheus, Grafana, Loki, Tempo, and the chosen local log
  shipper.
- Keep PostgreSQL/MySQL/MongoDB out of the topology because the codebase has
  no dependency on them.
- Define the internal service names and published ports.
- Define a local-only `.env` contract with safe development values and clear
  production-change markers.
- Record the model-build network requirement so “fully local” means no cloud
  runtime dependency, not an impossible offline first build.

## Deliverables

- The findings and topology recorded in `plan/README.md`.
- A final list of services, volumes, ports, and configuration keys to be
  implemented in later phases.

## Exit gate

The planned topology can be explained from the repository without adding an
unneeded database, proxy, cloud service, or Kubernetes layer.

