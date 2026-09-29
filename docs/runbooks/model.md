# Model unavailable or slow

## Symptom

Readiness fails, model-load errors appear, inference latency/p99 rises, the
pipeline fallback counter increases, or the circuit opens.

## Diagnose

Check the configured model ID/revision/digest, local cache permissions, CPU/RSS,
inference concurrency, timeout counts, and model failure metrics. Do not dump
request text or model inputs into diagnostics.

## Mitigate

In production, do not silently downgrade a required model deployment. Route to
a deliberately configured regex-only deployment only when its supported entity
coverage is acceptable and clients know the mode. Reduce traffic or worker
concurrency before increasing timeouts.

## Recover and verify

Validate the pinned snapshot, warm the model, check `/readyz`, and run a
synthetic canary through `/v1/redact`. Confirm the response is transformed and
that fallback/circuit metrics return to baseline.
