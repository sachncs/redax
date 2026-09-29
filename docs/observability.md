# Observability contract

Redax exposes RED metrics on `/metrics`: request rate and status,
end-to-end latency histograms, detector latency, durable job duration and
retry counters, accepted in-flight job depth, cache hits, error types, audit
failures, response-size histograms, oldest durable-job age, Redis pool
utilization, active worker heartbeats, and rate-limit dependency failures.
`redax_queue_depth` is a
per-process gauge of accepted non-terminal jobs; use it with replica count
and Redis-backed admission limits rather than treating one replica's value
as global queue depth. Do not add request text,
entity values, API keys, or Redis keys as labels.

`redax_response_rejections_total` counts buffered responses rejected by the
`REDAX_MAX_RESPONSE_BYTES` ceiling. Streaming responses remain governed by
their chunk and total-duration limits; this counter is intended to surface
unexpected response amplification without recording response content.

The checked-in assets are:

- [`deploy/monitoring/prometheus-rules.yaml`](../deploy/monitoring/prometheus-rules.yaml)
  for Prometheus Operator alerting rules;
- [`deploy/monitoring/redax-dashboard.json`](../deploy/monitoring/redax-dashboard.json)
  for Grafana RED/USE panels.

The rules assume `kube-state-metrics` for replica availability and
`container_*` metrics from the cluster metrics pipeline. Apply the
`PrometheusRule` only in clusters that install the Prometheus Operator CRD.
Alerts are intentionally conservative starting points; tune thresholds only
after the SLO benchmark and error-budget evidence exists.
The API's `redax_active_workers` gauge counts worker heartbeat keys in the
shared Redis namespace; a heartbeat expires after 15 seconds without refresh.
Audit JSONL events include `schema_version: 1` alongside the event fields. Keep
consumers tolerant of additive fields and validate the version before parsing
persisted records; migrations for future versions must preserve the no-PII
event contract. Redis-backed production audit records also include an
HMAC-SHA256 integrity envelope verified with `REDAX_AUDIT_INTEGRITY_KEY`.
Authenticated events also include a keyed `principal_id`; it is stable within
a deployment salt but does not contain the API key.

The HTTP middleware and streaming transport emit OpenTelemetry spans when
tracing is configured. Span attributes are deliberately limited to the HTTP
method and response status; request bodies, query values, headers, entity
values, API keys, and Redis keys are not recorded. Keep exporter-side sampling
and retention aligned with the same privacy contract.
