# Integration

The recommended integration pattern is to call Redax immediately before
and after every LLM call. This keeps raw PII from crossing the boundary
in either direction.

## Python SDK

```python
from redax import Redactor

redactor = Redactor(policy="default")


def chat(user_message: str) -> str:
    safe_input = redactor.redact(user_message)
    response = your_llm_call(safe_input)
    safe_output = redactor.redact(response.text)
    return safe_output
```

## Direct HTTP

```python
import httpx


def redact(text: str) -> str:
    r = httpx.post(
        "http://localhost:8000/v1/redact",
        json={"text": text, "policy": {...}},  # or omit policy
        headers={"X-API-Key": "..."},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["text"]
```

## Batch (multiple texts at once)

```python
r = httpx.post(
    "http://localhost:8000/v1/redact/batch",
    json={"items": [{"text": t1}, {"text": t2}]},
)
```

## Streaming (long documents)

```python
with httpx.stream(
    "POST",
    "http://localhost:8000/v1/redact/stream",
    json={"text": long_doc, "chunk_chars": 2000},
) as r:
    for line in r.iter_lines():
        if line.startswith("data:"):
            payload = json.loads(line[len("data:") :].strip())
            ...
```

## Async jobs (large workloads)

```python
r = httpx.post("http://localhost:8000/v1/jobs", json={"text": doc})
job_id = r.json()["id"]

while True:
    s = httpx.get(f"http://localhost:8000/v1/jobs/{job_id}").json()
    if s["status"] == "done":
        redacted = s["result"]["text"]
        break
    if s["status"] == "failed":
        raise RuntimeError(s["error"])
    time.sleep(0.5)
```

## Idempotency

Pass an `Idempotency-Key` header to make repeat POSTs safe. The second call
with the same key returns the cached response (24h TTL).

```python
httpx.post(url, json=body, headers={"Idempotency-Key": "abc-123"})
```

## Response caching

Identical (text + policy + entity_types) requests return the cached response
regardless of API key (1h TTL). Tunable via `REDAX_CACHE_TTL_SECONDS`.

## Audit log

Every successful redaction writes one line to the audit log containing only
counts, types, durations, and request metadata — never the original values.
See `docs/architecture.md` for the schema.
