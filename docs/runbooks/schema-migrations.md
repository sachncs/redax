# Persisted schema migrations

## Scope

Redax persists four versioned record types in Redis or the configured audit
backend. The authoritative values live in `app/schema_versions.py` and are
also recorded in `RELEASE-METADATA.json`:

| Store | Current version | Incompatible data behavior |
|---|---:|---|
| Response-cache envelope | 1 | Treat as a cache miss and recompute. |
| Idempotency record | 3 | Do not replay; reacquire the reservation. |
| Durable job record | 1 | Refuse the read/transition and surface an operator-visible error. |
| Audit event | 1 | Preserve the event contract; do not silently reinterpret fields. |

There is no automatic destructive migration. A schema-version change is a
release boundary and must include a compatibility test, a release metadata
review, and a rollback decision before deployment.

## Before deployment

1. Confirm the planned version change in `app/schema_versions.py` and inspect
   the generated version map:

   ```bash
   python scripts/release_metadata.py --output RELEASE-METADATA.json
   ```

2. Run the mixed-version tests and the complete verification gate with the
   release Python interpreter:

   ```bash
   make test
   make lint typecheck
   ```

3. Take an encrypted Redis snapshot and preserve the audit-volume snapshot.
   Record the snapshot IDs, Redis version, namespace, key-management context,
   and the expected restore point. Follow [Backup and restore](backup-restore.md)
   for the deployment-specific procedure.

4. Decide whether old records are disposable. Cache records may be discarded;
   idempotency, durable jobs, and audit records are not disposable without an
   explicit data-retention decision.

## Rollout order

Deploy readers that understand both the previous and new record contract before
deploying writers that emit the new version. Keep the compatibility window open
until every old writer is drained. Then switch writers and verify:

- a synthetic redaction succeeds and produces a current audit event;
- an idempotency replay either returns the current compatible response or
  safely reacquires rather than replaying an incompatible record;
- queued jobs remain visible and terminal transitions do not accept an
  incompatible record;
- cache misses recompute successfully; and
- `/readyz`, queue age, job failures, and audit-write metrics remain healthy.

## Rollback

Do not roll back a writer across a schema change unless the old writer can read
the records it may encounter. If compatibility is not proven, stop the rollout,
keep the service unready for the affected durable path, and restore from the
last compatible snapshot under the [rollback runbook](rollback.md). Never
delete durable job or audit data to make a rollback appear healthy.

Record the release commit, schema map, snapshot ID, migration window, and
measured data-loss/recovery interval in the deployment incident record. Do not
include request bodies, API keys, or raw audit payloads.
