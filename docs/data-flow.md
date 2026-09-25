# Data flow and storage boundary

Offsets are Python string indices (Unicode code points) over the original
request text. Redax does not promise byte offsets for JavaScript clients.

```text
HTTP request
  │ raw text in process memory
  ▼
auth → size/timeout admission → regex/model detection
  ▼
validate offsets → resolve overlaps → evaluate policy → replace spans
  │                                      │
  │                                      ├─ safe response text
  │                                      └─ span metadata / digest
  ├─ audit: counts, types, timing, request metadata; no values
  ├─ metrics: bounded names and aggregate labels; no text
  ├─ traces: operation metadata only; exporter is operator-controlled
  ├─ Redis: redacted cache/idempotency/job results and one-way key tokens
  └─ logs: event names, bounded metadata, exception class names
```

## What each path may contain

| Location | Raw request text | Entity values | Safe text | Notes |
|---|---:|---:|---:|---|
| Process memory | yes, transiently | yes, transiently | yes | Required to detect and transform text. |
| HTTP response | no, for redaction outputs | no | yes | `relex_map` is intentionally `{}` at HTTP boundaries. |
| Audit file | no | no | no | Counts, types, durations, keyed digest, and request metadata only. |
| Prometheus metrics | no | no | no | Never put user text or credentials in labels. |
| Redis cache/idempotency | no | no | yes | TTL-bound response records; cache keys are digests. |
| Redis jobs | no after submission payload leaves memory | no | yes | Job results are redacted; ownership uses one-way tokens. |
| OTLP/exported traces | not intentionally | not intentionally | no | Export destination and SDK instrumentation remain deployment concerns. |
| Reverse proxy / host logs | possible | possible | possible | Configure these systems separately; Redax cannot control them. |

The re-identification map used by library-level strategies is deliberately not
serialized by the HTTP, batch, stream, or job APIs. If an application needs a
reversible workflow, it must own that mapping in a separate access-controlled
system and accept the additional risk explicitly.

## Verification checklist

For a deployment, send synthetic PII and inspect the response, audit line,
Redis keys/values, metrics labels, trace exporter, container logs, and ingress
logs. Repeat with Redis unavailable, the model unavailable, a timeout, and an
open circuit breaker. A deployment is only as private as its least-controlled
side path.
