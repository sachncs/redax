# Redis unavailable or slow

## Symptom

Typed rate-limit 503s, cache misses, job-store 503s, rising Redis latency, or
connection errors in logs/metrics.

## Diagnose

Check `redax_rate_limit_unavailable_total`, request 503/429 rates, Redis
health/slowlog, connection pool saturation, and the deployment namespace. Never
log or paste Redis keys containing caller data.

## Mitigate

Keep fail-closed rate limiting for production. Disable cache use only if the
deployment explicitly accepts recomputation. Stop accepting asynchronous jobs
when the durable store is unavailable. Do not enable fail-open as an emergency
default; if approved, record the incident and alert.

## Recover and verify

Restore Redis/HA failover, verify ping and command latency, then submit a
synthetic redaction, repeat the same idempotency key, and check a synthetic job.
Confirm no raw synthetic value appears in Redis inspection, logs, metrics, or
audit output. Current jobs require the distributed-worker milestone before
claiming crash recovery.
