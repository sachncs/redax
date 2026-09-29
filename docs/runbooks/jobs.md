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
bounded retries, and no duplicate completion. The current in-process job path
does not meet this runbook's recovery guarantee and is not HA-supported.
