# Suspected PII leakage

## Symptoms

A raw value appears in logs, traces, metrics, audit data, Redis, a job record,
an exception, a support artifact, or an externally visible response; or a
privacy canary test fails.

## Immediate containment

Treat the event as a security incident. Stop the affected deployment from
receiving traffic and disable optional telemetry exporters if they may be
receiving unsafe attributes. Do not copy the suspected value into tickets,
chat, shell history, dashboards, or test fixtures. Preserve timestamps,
request IDs, release commit, exporter destination, and aggregate status data
only. Rotate any credential that may have been exposed.

## Diagnose

Restrict access to the affected logs, traces, Redis namespace, audit store, and
job store. Search using a securely handled canary or keyed digest through an
approved incident process; never print matched records. Identify the exact
sink and path: success, validation, detector/model failure, timeout,
cancellation, job, audit, stream, or exporter delivery. Check the deployed
commit and configuration against `PRODUCTION_READINESS.md` and the release
metadata.

## Recover and verify

Patch or disable the leaking path, expire or securely purge affected stores
according to the retention policy, rotate exposed secrets, and redeploy the
verified immutable artifact. Run the complete PII-canary suite plus synthetic
success and failure requests. Verify no canary appears in response metadata,
logs, metrics, traces, audit records, Redis keys/values, job metadata, or
exception output before restoring traffic.

## Escalation

Escalate immediately to the security and privacy owners when exposure reached
an external collector, shared store, operator surface, or downstream client.
Record scope, retention windows, access logs, containment time, and verification
results without retaining the raw value in the incident record.
