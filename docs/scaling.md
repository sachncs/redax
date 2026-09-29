# Scaling and capacity

Current status: **capacity is not yet measured**. The repository's benchmark
harness is useful for detector comparisons, but it is not evidence of a safe
service throughput limit. Do not infer capacity from a local laptop run.

## Reference topology

```text
client
  → TLS/ingress/load balancer
  → stateless Redax API replicas
  → durable Redis HA for coordination/cache/idempotency
  → independent Redax worker replicas for asynchronous jobs
  → centralized audit/log pipeline
  → metrics and tracing collectors
```

The API replicas must share only versioned, concurrency-safe state. Model
weights may be loaded in each API replica or isolated to a model-serving tier;
the choice must be recorded with memory and latency measurements. Workers must
not depend on an API process's memory, local queue, or local filesystem.

## Required benchmark matrix

Run each scenario at increasing concurrency and record JSON output:

| Scenario | Variables | Required observations |
|---|---|---|
| Regex synchronous | 1 KB, configured maximum, warm process | p50/p95/p99/max, throughput, CPU, RSS, error rate |
| Model synchronous | cold and warm model, same inputs | model queue, inference latency, RSS, CPU, timeout/fallback rate |
| Cache hot/cold | identical and unique requests | Redis latency, hit rate, throughput, p99 |
| Batch | 1, 10, 100, maximum items | amplification, memory, semaphore saturation, errors |
| Stream | small/maximum text, slow client, disconnect | buffer memory, chunk latency, cancellation cleanup |
| Jobs | enqueue ramp, worker concurrency, retries | queue depth, oldest age, job duration, retry/DLQ rate |
| Soak | representative mix for hours | RSS/task/file-descriptor/connection drift and p99 drift |

Every result records Redax commit, lockfile hash, model revision/digest,
corpus/license, policy, hardware, Python/Torch versions, Redis topology,
concurrency, and command line. Results without that metadata are exploratory.

## Capacity model

Until measured, operators should size using the conservative bottleneck:

```text
safe throughput = min(
  API CPU capacity,
  model inference capacity × replicas,
  Redis operation capacity,
  audit sink capacity,
  ingress/request concurrency limit
)
```

The safe point is where p99 and error rate remain within the published SLO and
RSS/queue depth remain bounded during both ramp and recovery. Autoscaling must
consider request concurrency, inference concurrency, queue depth, and oldest
job age—not CPU alone.

## Current limitations

`/v1/jobs` now uses a separate ARQ worker tier. There is still no measured safe
throughput, no HA Redis evidence, and no load/soak artifact in the current
release. These are P0/P1 gaps in [`PRODUCTION_PLAN.md`](../PRODUCTION_PLAN.md),
not hidden assumptions.
