# API

All endpoints speak JSON. Errors come back as RFC 7807 `application/problem+json`.

## POST /v1/redact

Redact a single text. Returns `{text, spans, relex_map}`.

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
  }
}
```

**Response 200**:

```json
{
  "text": "Email me at [EMAIL_0001]",
  "spans": [{"start": 12, "end": 29, "type": "EMAIL", "confidence": 1.0}],
  "relex_map": {"alice@example.com": "[EMAIL_0001]"}
}
```

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

Server-Sent Events. Splits the input into chunks (`chunk_chars`, default 2000)
and emits one event per chunk, then a final `[DONE]`.

```bash
curl -N -X POST http://localhost:8000/v1/redact/stream \
  -H 'Content-Type: application/json' \
  -d '{"text": "long doc...", "chunk_chars": 1000}'
```

Requires an API key when configured. Rejects oversized payloads (413), enforces
the shared rate limit (429/503), and a per-chunk timeout yields a
`{"error": "request timeout", "status": 504}` SSE event. Emits one audit event
per request.

## POST /v1/jobs, GET /v1/jobs/{id}

Submit an async redaction; poll the result. Useful for long documents or
high-throughput pipelines. Both endpoints require an API key when configured;
submission enforces `max_text_chars` (413), the shared rate limit (429/503),
and the `max_inflight` admission cap (429, RFC 7807 `queue-full` when the
in-flight job count is at capacity).

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
| `GET /metrics` | Prometheus exposition format |
