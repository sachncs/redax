# Rollback and disaster recovery

## Symptom

A release causes elevated 5xx/429, latency, readiness failures, incorrect
redaction, job-state errors, or a security regression.

## Diagnose

Download `RELEASE-METADATA.json` with the release assets and compare its commit,
dependency-lock digest, model manifest digest/revisions, and persisted schema
versions with the running image. Use synthetic canaries and dashboards; do not
replay production request bodies into debugging tools.

## Immediate mitigation

Stop rollout, remove unhealthy replicas from service, and route to the last
known-good immutable image digest. Preserve Redis and audit data. Do not roll back
across an untested persisted-schema migration. Verify the matching `SHA256SUMS`
entry before trusting the metadata file.

## Recovery and verification

Verify readiness, synthetic `/v1/redact`, idempotency reuse, rate limiting,
worker/job state, audit metadata, and telemetry privacy. Document RPO/RTO and
restore from a tested backup before declaring recovery. The repository includes
a disposable Redis RDB restore drill; managed Redis and audit-volume restore
evidence remain deployment acceptance gates.
