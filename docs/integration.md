# Integration

Redax is an HTTP service. Put it at the boundary where your application sends
text to an external model or stores it in an external system, and choose that
boundary deliberately for your threat model. Redax is not a guarantee that
PII is absent from application memory, logs, prompts, or model output.

## Python application code

The `app.*` modules are implementation details, not a stable Python SDK. New
integrations should call the HTTP API so authentication, limits, policy
precedence, and response semantics stay consistent across languages.

```python
from app.redaction import Redactor, load_policy
from app.inference.regex import RegexDetector

strategies = {"mask": RegexDetector()}
redactor = Redactor(
    detector=RegexDetector(),
    strategies=strategies,
    replacement="[REDACTED]",
)


async def chat(user_message: str) -> str:
    safe_input = (await redactor.redact(user_message)).text
    response = your_llm_call(safe_input)
    safe_output = (await redactor.redact(response.text)).text
    return safe_output
```

## Redact over HTTP

```python
import httpx


def redact(text: str) -> str:
    r = httpx.post(
        "http://localhost:8000/v1/redact",
        json={"text": text},  # add policy or entity_types when required
        headers={"X-API-Key": "..."},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["text"]
```

`/v1/redact` always returns transformed text. It does not return a reversible
mapping of original values. If an application needs to inspect detections
before choosing a redaction policy, call `/v1/detect` explicitly and treat
its original-text response as sensitive data.

## Batch (multiple texts at once)

```python
r = httpx.post(
    "http://localhost:8000/v1/redact/batch",
    json={"items": [{"text": t1}, {"text": t2}]},
    headers={"X-API-Key": "..."},
)
```

## Streaming (long documents)

```python
with httpx.stream(
    "POST",
    "http://localhost:8000/v1/redact/stream",
    json={"text": long_doc, "chunk_chars": 2000},
    headers={"X-API-Key": "..."},
) as r:
    for line in r.iter_lines():
        if line.startswith("data:"):
            payload = json.loads(line[len("data:") :].strip())
            ...
```

## Async jobs (large workloads)

```python
r = httpx.post(
    "http://localhost:8000/v1/jobs",
    json={"text": doc},
    headers={"X-API-Key": "..."},
)
job_id = r.json()["id"]

while True:
    s = httpx.get(
        f"http://localhost:8000/v1/jobs/{job_id}",
        headers={"X-API-Key": "..."},
    ).json()
    if s["status"] == "done":
        redacted = s["result"]["text"]
        break
    if s["status"] == "failed":
        raise RuntimeError(s["error"])  # stable "job failed" marker
    time.sleep(0.5)
```

An unknown job id raises a `404 Not Found` (RFC 7807 body), not a
softly-shaped 200.

## Correlation ids

Send your own trace id in `X-Request-ID`; Redax echoes it back on the response
and includes it (with a server-generated fallback) in every structured log
line and audit event for the request.

## Idempotency

Pass an `Idempotency-Key` header to make repeat POSTs safe. The second call
with the same key returns the cached response (24h TTL).

```python
httpx.post(url, json=body, headers={"Idempotency-Key": "abc-123"})
```

## Response caching

Identical effective requests return the same safe response from the cache when
enabled. The cache key includes the text, policy, entity types, mode, detector,
and model revision; it never stores a reversible mapping. Tunable via
`REDAX_CACHE_TTL_SECONDS`.

## Audit log

Every successful redaction — synchronous, batch, stream, or job — writes one
line to the audit log containing only counts, types, durations, and request
metadata (never the original values). See `docs/architecture.md` for the
schema.
