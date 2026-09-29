# Service-level objectives

These are target objectives for a production deployment, not measured claims
about the current pre-1.0 implementation. Measured values must be added from
the load and soak artifacts before an operator treats a target as achieved.

## Availability target

The reference HA architecture targets **99.99% monthly availability** for
`/v1/redact`, excluding a documented maintenance window. That is a monthly
error budget of 0.01% (about 4 minutes 23 seconds in a 30-day month). A
single-process or development Compose deployment does not provide evidence for
this target.

Availability counts requests that reach the service and receive a response;
planned maintenance, client disconnects before admission, and rejected
requests caused by caller authentication or validation are reported separately.
Unexpected 5xx, 429/503 caused by capacity or dependencies, readiness loss, and
failed accepted jobs consume the budget according to the deployment's recorded
measurement policy.

## Request reliability

- Accepted synchronous redaction requests must return either a documented
  transformed response or a documented error; no timeout may be converted into
  a successful-looking raw response.
- Accepted asynchronous jobs must be durably enqueued before `202` is returned,
  and must reach a terminal state or a recoverable retry/dead-letter state.
- Deterministic regex output is compared byte-for-byte for identical code,
  policy, model/configuration, and input. Model-backed output is versioned and
  measured rather than promised deterministic.

Current status: synchronous behavior is tested and accepted jobs are handed to
the separate ARQ worker. Durable accepted-job reliability is **not yet proven**
until Redis failover, worker restart, lease recovery, and DLQ evidence exist.

## Latency and throughput measurements

No latency target is invented before measurement. Each benchmark artifact must
report the following separately for regex, model, `/v1/redact`, batch, stream,
cache hit, and cold/warm startup:

```text
p50, p90, p95, p99, max, requests/sec, concurrency,
CPU, RSS memory, Redis latency/errors, model queue depth, error rate
```

The benchmark must include request size, detector/model revision, policy,
hardware, Python/Torch versions, Redis topology, and exact Redax commit. The
safe operating point is the highest sustained concurrency before p99 or error
rate breaches the published threshold; it must be recorded, not guessed.

## Error budget policy

1. Every release records the latest measured SLO result and unexplained
   regressions.
2. If the monthly budget is exhausted, freeze feature releases affecting the
   request path and prioritize reliability work.
3. Security incidents, PII leakage, accepted-job loss, or an unbounded resource
   failure are release blockers regardless of the remaining availability
   budget.
4. Development/Compose results are labeled non-production and cannot be used
   as HA evidence.

## Required evidence

The current repository has machine-readable local regex API baseline,
sustained-run, concurrency-matrix, and warm-ramp artifacts, but not
release-grade capacity evidence. M6 must still add machine-readable spike,
cache-cold, cache-hot, batch, stream, job, and multi-hour soak results under a
documented environment, then link them from `docs/scaling.md` and this page.
