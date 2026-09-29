# Observability contract

Redax exposes RED metrics on `/metrics`: request rate and status,
end-to-end latency histograms, detector latency, durable job duration and
retry counters, accepted in-flight job depth, cache hits, error types, audit
failures, and rate-limit dependency failures. `redax_queue_depth` is a
per-process gauge of accepted non-terminal jobs; use it with replica count
and Redis-backed admission limits rather than treating one replica's value
as global queue depth. Do not add request text,
entity values, API keys, or Redis keys as labels.

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
