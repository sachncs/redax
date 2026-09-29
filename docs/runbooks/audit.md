# Audit or disk failure

## Symptom

Audit write failures/drops, filesystem-full alerts, permission errors, or
rotation/retention failures.

## Diagnose

Check audit backend counters, mount health, free space, ownership, rotation
backups, and retention age. Inspect metadata only; do not open request payloads
to prove a write succeeded.

## Mitigate

For compliance deployments, enable mandatory-audit behavior when available and
reject successful processing until a durable backend is healthy. Do not delete
audit data as a first response. For optional audit mode, alert and record the
degradation explicitly.

## Recover and verify

Restore storage or the centralized sink, rotate safely, and run a synthetic
request. Verify a versioned metadata event, retention policy, and absence of
the synthetic value. Tamper-evident centralized audit and restore tests remain
production-program gaps.
