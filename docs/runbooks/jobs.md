# Jobs and worker failure

## Symptom

Queue depth or oldest-job age rises, jobs remain queued/running, workers crash,
or retry/DLQ metrics increase.

## Diagnose

Check API admission, Redis job state, worker health, lease age, retry count, and
the deployment version. Inspect only job IDs and metadata; never fetch raw
input for incident chat.

## Mitigate

Stop admitting new jobs if the durable queue is unavailable or saturated.
Preserve queued records. Do not delete stuck records until lease/recovery state
is understood.

## Recover and verify

Restart or replace workers, allow expired leases to be reclaimed, and inspect
the dead-letter path. Submit a synthetic job and verify one terminal result,
bounded retries, and no duplicate completion. The ARQ worker path is wired,
and startup reconciliation fails stale queued/running jobs after
`REDAX_JOB_STALE_SECONDS`. Permanent failures are also recorded in the
bounded Redis `redax:jobs:dead-letter` list as schema-versioned metadata only
(job ID, attempt count, safe error marker, timestamp; never request payload).
Expired-lease recovery is covered by the real-Redis integration test, but a
process-kill drill and Redis failover drill remain release gates.
