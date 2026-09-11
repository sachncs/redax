# API

All endpoints speak JSON. Errors come back as RFC 7807 `application/problem+json`.

## POST /v1/redact

Redact a single text. Returns `{text, spans, relex_map, used_pipeline,
used_fallback, digest}`. The shape is stable across the legacy
`Redactor` path (default) and the new multi-stage pipeline path
(`use_pipeline=true`).

**Request body**:

```json
{
  "text": "Email me at alice@example.com",
  "entity_types": ["email"],          // optional, overrides policy
  "policy": {                          // optional inline policy
    "name": "ad-hoc",
    "version": "0.1.0",
    "fields": {
      "free_text": {"strategy": "autoDeID", "relex": true}
    }
  },
  "use_pipeline": false                // optional, default false; flip to true
                                       // to route through the multi-stage
                                       // pipeline (regex gate + model +
                                       // consensus + circuit-broken model
                                       // fallback). When the pipeline is
                                       // unavailable (regex-only deployment
                                       // or model breaker permanently open)
                                       // the legacy Redactor path is used.
}
```

**Response 200** (legacy Redactor path):

```json
{
  "text": "Email me at [EMAIL_0001]",
  "spans": [{"start": 12, "end": 29, "type": "EMAIL", "confidence": 1.0}],
  "relex_map": {"alice@example.com": "[EMAIL_0001]"},
  "used_pipeline": false,
  "used_fallback": false,
  "digest": null
}
```

**Response 200** (`use_pipeline=true`):

```json
{
  "text": "Email me at alice@example.com",
  "spans": [
    {"start": 8,  "end": 24, "type": "EMAIL",    "confidence": 0.99},
    {"start": 0,  "end": 8,  "type": "PERSON",   "confidence": 0.85}
  ],
  "relex_map": {},
  "used_pipeline": true,
  "used_fallback": false,
  "digest": "e38dfce0ad75a983ef463bae56cb70f6a338b708e253c15104bd01e1649bea1a"
}
```

The pipeline response keeps the original text (no relexicalization at
the route level — the existing redax redactor still owns relex) and
records `used_fallback=true` when the model stage's circuit breaker is
open. `digest` is a SHA-256 of the input text for log correlation;
the audit log records the hash but never the text itself.

**Errors**: 413 (oversize), 422 (validation), 429 (rate-limited), 503 (not ready), 504 (timeout).

**Headers honored**: `X-API-Key`, `Idempotency-Key`.
Every response echoes the request's `X-Request-ID` (or a server-generated one).

## POST /v1/redact/batch

Up to 1000 items per call. Runs in parallel via `asyncio.gather` under a single
overall timeout.

```json
{"items": [{"text": "..."}, {"text": "..."}]}
```

Requires an API key when configured. Enforces `max_text_chars` per item (413),
the shared rate limit (429/503), a per-request timeout (504), and emits one
audit event per request with aggregated span counts.

## POST /v1/redact/stream

Server-Sent Events. Splits the input into chunks (`chunk_chars`, default
`REDAX_STREAM_CHUNK_CHARS`) and emits one event per chunk, then a final `[DONE]`.
Each event is capped at `REDAX_STREAM_CHUNK_BYTES` bytes of UTF-8 (a grapheme is
never split across events).

```bash
curl -N -X POST http://localhost:8000/v1/redact/stream \
  -H 'Content-Type: application/json' \
  -d '{"text": "long doc...", "chunk_chars": 1000}'
```

Requires an API key when configured. Rejects oversized payloads (413), enforces
the shared rate limit (429/503), and a per-chunk timeout yields a
`{"error": "request timeout", "status": 504}` SSE event. Each event is capped
at `REDAX_STREAM_CHUNK_BYTES` (default 4096) bytes and defaults to
`REDAX_STREAM_CHUNK_CHARS` characters when `chunk_chars` is omitted.
Emits one audit event per request.

## POST /v1/jobs, GET /v1/jobs/{id}

Submit an async redaction; poll the result. Useful for long documents or
high-throughput pipelines. Both endpoints require an API key when configured;
submission enforces `max_text_chars` (413), the shared rate limit (429/503),
the `max_inflight` admission cap (429, RFC 7807 `queue-full` when the
in-flight job count is at capacity), and the per-key `max_jobs_per_key` quota
(429, `job-limit`).

**Submit**:

```bash
curl -X POST http://localhost:8000/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{"text": "..."}'
# 202 Accepted
{"id": "...", "status": "queued"}
```

**Poll**:

```bash
curl http://localhost:8000/v1/jobs/{id}
# {"id": "...", "status": "done", "result": {...}, "error": null}
```

An unknown `{id}` returns a 404 `application/problem+json` body. A failed job
surfaces the stable `"error": "job failed"` marker — never an internal
exception string. A job whose redaction exceeds `request_timeout_seconds` fails
the same way (recorded as `redax_errors_total{type="job_timeout"}`). Completed
jobs are recorded in the audit log; job records expire after
`job_ttl_seconds`.

## GET /v1/policies

List the policies shipped in `policies/`.

```json
{
  "policies": [
    {"name": "default", "version": "1.0.0", "description": "...", "fields": ["free_text", ...]}
  ]
}
```

## Health and metrics

| Endpoint | Purpose |
|---|---|
| `GET /healthz` | Process liveness, always 200 |
| `GET /readyz` | Redactor initialized; 200 or 503 `application/problem+json` |
| `GET /v1/stats` | Operator introspection: detector names, audit backend, pipeline stats, breaker state. API-key-gated. |
| `GET /metrics` | Prometheus exposition format |

## GET /v1/stats

Operator-facing snapshot of the live wiring. Requires `X-API-Key` when
`REDAX_API_KEYS` is set. Always JSON, never a problem-details body.

```json
{
  "ready": true,
  "redactor": "[REDACTED]",
  "detector": "gliner2",
  "regex_detector": "regex",
  "audit_backend": "FileAudit",
  "redis_enabled": true,
  "pipeline": {
    "regex_detector": "regex",
    "model_detector": "gliner2",
    "model_breaker": {
      "state": "closed",
      "consecutive_failures": 0,
      "opened_at": null,
      "probes_in_flight": 0,
      "total_calls": 42,
      "total_failures": 0
    }
  }
}
```

The endpoint is read-only and never mutates state. Use it from a
dashboard or a synthetic-monitor script to alert on `model_breaker.state
== "open"` or `redis_enabled == false`.
