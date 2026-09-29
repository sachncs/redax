# Production launch gate

Use this runbook for a new production deployment or a release candidate. Run
all probes with synthetic values only. Record the commit, image digest, model
revision, lockfile digest, Redis topology, timestamps, status codes, and metric
names; never record request bodies, API keys, job identifiers, or audit values.

## Before deployment

1. Confirm the exact commit has green `ci` and `security` workflow runs. Save
   the workflow URLs and the release `RELEASE-METADATA.json`/`SHA256SUMS`.
2. Verify the image digest and model manifest digest match the release metadata.
3. Set `REDAX_ENV=prod`, unique `REDAX_HASH_SALT`, API keys, trusted hosts,
   valid default policy, Fernet job-payload key, and independent audit key.
4. Use TLS Redis (`rediss://`) with a unique `REDAX_REDIS_NAMESPACE`, bounded
   connection and socket timeouts, persistence, backups, and an operator-owned
   failover plan. Do not use the development Compose Redis settings.
5. Configure the ingress body and timeout contract, `/readyz` readiness, TLS,
   Prometheus scraping, alert rules, and an OTLP collector with a documented
   privacy and delivery policy.

## Deploy and canary

For the reference topology, follow [`deploy/kubernetes/README.md`](../../deploy/kubernetes/README.md)
and verify both API and worker rollouts before restoring traffic.

Run these checks in order:

```bash
curl --fail --silent https://redax.example.com/healthz
curl --fail --silent https://redax.example.com/readyz
curl --fail --silent -H 'X-API-Key: <canary-key>' \
  -H 'Content-Type: application/json' \
  --data '{"text":"Synthetic launch canary at canary@example.invalid"}' \
  https://redax.example.com/v1/redact
```

Then verify, using synthetic inputs and a fresh idempotency key:

- the redaction response contains a placeholder and no raw canary in logs,
  traces, metrics, Redis inspection, or audit metadata;
- repeating the same idempotency key replays the same response;
- one durable job reaches a terminal state and its audit event is present;
- `/metrics` exposes request, admission, Redis-pool, queue, worker, audit, and
  response-size metrics;
- the OTLP collector receives metadata-only telemetry.

## Failure and recovery gate

Run these drills before calling the release production-ready:

| Drill | Required observation | Evidence |
|---|---|---|
| Kill one API replica | Traffic continues; idempotency replay remains correct. | timestamps, replica events, canary status, error rate |
| Kill one worker during a job | Job retries or reaches the documented DLQ; no accepted job disappears. | job terminal counts, retry/DLQ metrics |
| Fail over Redis | readiness and errors follow the documented policy; accepted state recovers without duplicate completion. | provider failover event, RPO/RTO, Redis/job/audit checks |
| Ramp and spike traffic | 429/503 responses are bounded and memory, tasks, connections, and queue age recover. | machine-readable benchmark and recovery artifact |
| Roll out and roll back | readiness drains before termination; both API and worker return to a known-good digest. | rollout history, timestamps, rollback result |

Do not mark a drill complete from a local laptop or disposable Redis run when
the acceptance condition names managed infrastructure. Attach the external
artifact to the release and update `PRODUCTION_READINESS.md` and
`docs/unresolved-risks.md` with the measured result.

## Stop conditions

Stop the rollout and route to the last known-good immutable digest if readiness
fails, any canary returns raw text after an internal error, accepted jobs do not
reach a terminal/recoverable state, telemetry contains request values, or the
measured error budget/capacity boundary is exceeded. Use
[`rollback.md`](rollback.md) for recovery.
