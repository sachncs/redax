# Capacity and overload

## Symptoms

High CPU or RSS, event-loop lag, elevated p99 latency, rising `503` admission
responses, elevated `429` responses, Redis-pool saturation, or increasing job
queue depth/oldest age.

## Diagnose

Use the RED/USE dashboard and compare request rate, in-flight requests,
inference concurrency, response size, Redis pool usage, worker capacity, queue
depth, and oldest-job age against the deployment's measured baseline. Break
down by endpoint and status only; do not log request text, API keys, or job
payloads. Check whether the increase is traffic, model latency, Redis latency,
or a worker outage.

## Immediate mitigation

Keep request admission, batch, stream, inference, and job limits enabled.
Allow `429` responses for authenticated rate-limit exhaustion and `503` for
local admission or unavailable durable dependencies. Scale API replicas for
HTTP saturation and workers for queue age only after confirming Redis and model
capacity. Do not increase limits or timeouts during an incident without a
measured capacity review. If overload threatens the privacy boundary, remove
the affected deployment from service and fail closed.

## Recover and verify

Let the queue drain, verify CPU/RSS, Redis pool utilization, p99 latency, error
rate, and event-loop health return to baseline, then run a synthetic redaction,
batch, stream, and job canary. Confirm the canaries are transformed, terminal,
and absent from logs, metrics, traces, Redis inspection, and audit metadata.

## Escalation

Escalate when memory continues to grow after traffic falls, queue age exceeds
the documented SLO, 5xx responses persist after dependencies recover, or the
safe operating limit is exceeded. Preserve only aggregate metrics and release
metadata for the incident review.
