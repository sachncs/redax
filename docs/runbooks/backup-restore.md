# Backup and restore

## Scope

Redis job records, idempotency envelopes, rate-limit counters, and response
cache entries are stored under the configured Redis namespace. Audit JSONL is
separate durable data. Cache and rate-limit entries may be reconstructed; jobs,
idempotency state, and audit records require the deployment's durability policy.

## Redis backup

Use the managed Redis provider's encrypted snapshot facility or an equivalent
RDB backup. Record the snapshot timestamp, Redis version, namespace, encryption
key management context, and retention policy. Never copy production request
bodies into an incident workspace.

For a self-managed disposable drill, the repository proves the core restore
operation with:

```bash
REDAX_TEST_REDIS_URL=redis://localhost:6379/15 \
  python -m pytest tests/integration/test_redis_jobs.py \
  -k redis_rdb_backup_restores_into_fresh_instance -q
```

The drill writes a synthetic value, creates an RDB snapshot, copies it into a
fresh Redis data directory, and verifies the value after restore. Run the same
procedure against the managed service and record measured RPO/RTO before
declaring a production recovery target.

## Audit restore

Use a storage snapshot or object-store version of the audit volume. Restore to
a new path, verify permissions and free space, validate JSONL parsing and
`schema_version`, then switch the deployment to the restored path during a
maintenance boundary. In mandatory-audit mode, keep the service unready until
a synthetic redaction produces a fresh audit line.

## Verification

After restore, verify `/readyz`, a synthetic `/v1/redact`, idempotency replay,
job status visibility, audit metadata, and the absence of request values from
logs/metrics/traces. Record the snapshot identifier, restore duration, data
loss window, and operator approvals.
