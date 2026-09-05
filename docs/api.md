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

**Errors**: 413 (oversize), 422 (validation), 429 (rate-limited), 503 (not ready).

**Headers honored**: `X-API-Key`, `Authorization: Bearer ...`, `Idempotency-Key`.

## POST /v1/redact/batch

Up to 1000 items per call. Runs in parallel via `asyncio.gather`.

```json
{"items": [{"text": "..."}, {"text": "..."}]}
```

## POST /v1/redact/stream

Server-Sent Events. Splits the input into chunks (`chunk_chars`, default 2000)
and emits one event per chunk, then a final `[DONE]`.

```bash
curl -N -X POST http://localhost:8000/v1/redact/stream \
  -H 'Content-Type: application/json' \
  -d '{"text": "long doc...", "chunk_chars": 1000}'
```

## POST /v1/jobs, GET /v1/jobs/{id}

Submit an async redaction; poll the result. Useful for long documents or
high-throughput pipelines.

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
| `GET /readyz` | Model loaded, 200 / 503 |
| `GET /metrics` | Prometheus exposition format |
