# Scaling and capacity

Current status: **local capacity and ramp evidence exists; production capacity
is not yet established**. The checked-in artifacts are useful for regression tracking,
but they are not evidence of a safe HA service throughput limit. Do not infer
production capacity from a local laptop run.

Current local evidence on Python 3.13/macOS is available in
[`regex-api-local-baseline.json`](benchmarks/regex-api-local-baseline.json)
(200 requests at concurrency 20) and
[`regex-api-sustained-local.json`](benchmarks/regex-api-sustained-local.json)
(5 seconds at concurrency 20). Both completed with 100% HTTP 200 responses;
the sustained run measured 471.635 requests/sec, p99 40.889 ms, and an RSS
increase of about 8.4 MiB. These are regression baselines only, not safe
operating limits or SLO evidence for a production topology.

The current concurrency matrix adds 300-request regex runs at concurrency 1,
10, 20, and 40 in
[`docs/benchmark-results.md`](benchmark-results.md). Every run returned 100%
HTTP 200 responses. The matrix shows p99 rising from 3.398 ms at concurrency 1
to 111.732 ms at concurrency 20 and 74.606 ms at concurrency 40 on this local
host; it is useful for regression tracking, not a production saturation limit.

The 1,000-request warm ramp at concurrency 1/20/40/80/128/160 is recorded in
the `regex-api-ramp-*.json` artifacts under `docs/benchmarks/`. Every point
returned 100% HTTP 200 responses. On the recorded host, throughput peaked at
633.723 requests/sec and p99 was 133.351 ms at concurrency 80; p99 rose to
325.873 ms at 128 and 558.202 ms at 160 while throughput fell to 405.3
requests/sec. This identifies a local regression knee near concurrency 80,
not a production operating limit.

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

`/v1/jobs` now uses a separate ARQ worker tier. A reference Kubernetes
topology is checked in under
[`deploy/kubernetes/`](../deploy/kubernetes/README.md). There is still no
measured safe production throughput, no HA Redis evidence, and no multi-hour
soak artifact in the current release. These are P0/P1 gaps in
[`PRODUCTION_PLAN.md`](../PRODUCTION_PLAN.md),
not hidden assumptions.
