# Phase 2 — Local observability

## Objective

Provide useful local metrics, logs, traces, and dashboards without any hosted
observability service.

## Work

- Add an OpenTelemetry Collector with OTLP gRPC `4317` and OTLP HTTP `4318`
  receivers bound to the private Compose network.
- Configure Redax to export traces to `http://otel-collector:4317` and keep
  export failure behavior fail-open for request processing.
- Add Prometheus scraping of `http://redax:8000/metrics`; keep metrics
  pull-based because that is the application’s existing contract.
- Add Tempo as the local trace backend and wire the collector exporter to it.
- Keep structured application logs on stdout, bound Docker JSON log files
  with rotation, and route them through a small local log shipper into Loki.
  The selected shipper must work on Linux and be documented for Docker
  Desktop path differences.
- Add Grafana provisioning for Prometheus, Loki, and Tempo datasources, with
  a minimal Redax dashboard covering request rate/errors/latency, readiness,
  Redis pool health, queue depth, worker activity, response-size rejections,
  and telemetry export failures.
- Ensure no user text, API keys, tokens, or sensitive payloads enter logs,
  metric labels, trace attributes, or dashboards.

## Deliverables

- `observability/otel-collector-config.yaml`
- `observability/prometheus.yml`
- `observability/tempo.yaml`
- `observability/loki-config.yaml`
- Local log-shipping configuration.
- Grafana datasource provisioning and a small dashboard.
- Compose services and internal endpoints for the stack.

## Exit gate

Prometheus shows Redax metrics, Grafana can query Prometheus/Loki/Tempo,
synthetic traffic creates a trace visible in Tempo, and a test log is visible
in Loki without requiring an external endpoint.

