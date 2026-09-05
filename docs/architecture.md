# Architecture

Redax is a self-hosted PII redaction engine. One process, four API surfaces,
two deployment targets (Docker + WASM), one detection pipeline shared across
all of them.

```
                  Clients  (SDK / HTTP / browser WASM bundle)
                              │
   ┌──────────────────────────▼───────────────────────────────────┐
   │  FastAPI application  (app/main.py)                          │
   │                                                              │
   │   POST /v1/redact            POST /v1/redact/batch          │
   │   POST /v1/redact/stream     POST /v1/jobs                  │
   │   GET  /v1/jobs/{id}         GET  /v1/policies              │
   │   GET  /healthz /readyz /metrics                            │
   │                                                              │
   │   Auth  (X-API-Key, Bearer JWT)                              │
   │   Rate limit  (Redis fixed-window per API key)               │
   │   Idempotency-Key  (Redis 24h)                                │
   │   Response cache  (SHA256(text + policy + salt), 1h)        │
   │   RFC 7807 problem responses                                  │
   └──────────────────────────┬───────────────────────────────────┘
                              │
   ┌──────────────────────────▼───────────────────────────────────┐
   │  Detection pipeline                                          │
   │                                                              │
   │   Detector (GLiNER2 / Regex)                                 │
   │   multi_pass_detect (parallel N runs)                        │
   │   validate_offsets (drop bad spans)                          │
   │   dedupe_overlaps (keep higher confidence)                   │
   │   apply_spans (offset-safe substitution)                     │
   │   relexicalize (typed placeholders, Hiding in Plain Sight)   │
   │                                                              │
   │   Strategy routing per policy field                          │
   │   (passThrough / mask / hash / regex / autoDeID)             │
   └──────────────────────────┬───────────────────────────────────┘
                              │
   ┌──────────────────────────▼───────────────────────────────────┐
   │  Audit log  (LocalFileAuditBackend, JSONL append-only)       │
   │   records counts/types/durations only — never entity values  │
   └──────────────────────────────────────────────────────────────┘
```

## Module map

| Module | Responsibility |
|---|---|
| `app/main.py` | FastAPI app, lifespan wiring, route registration |
| `app/config.py` | Pydantic-settings: REDAX_ env vars |
| `app/logging.py` | structlog JSON logging |
| `app/errors.py` | RFC 7807 problem responses |
| `app/auth.py` | API-key + JWT dependencies |
| `app/ratelimit.py` | Redis fixed-window rate limit |
| `app/observability/` | Prometheus + OpenTelemetry |
| `app/api/` | HTTP route modules (one registration function each) |
| `app/inference/detector.py` | `Span` dataclass + `Detector` Protocol |
| `app/inference/regex_detector.py` | Regex rules + Luhn checksum |
| `app/inference/gliner2.py` | GLiNER2 zero-shot NER |
| `app/inference/multi_pass.py` | Run detector N times, union results |
| `app/redaction/redactor.py` | Orchestrator: detect + validate + dedupe + substitute |
| `app/redaction/strategy.py` | 5 strategies implementing the `Strategy` Protocol |
| `app/redaction/apply.py` | `apply_spans`, `dedupe_overlaps` |
| `app/redaction/offsets.py` | `validate_offsets` |
| `app/redaction/relex.py` | Hash-deterministic HIPS relexicalizer |
| `app/redaction/policies.py` | YAML policy loader |
| `app/audit/` | `AuditBackend` Protocol + local-file implementation |
| `app/jobs/store.py` | Redis-backed job lifecycle store |

## Data flow for one request

1. FastAPI receives POST `/v1/redact` with `{text, entity_types?, policy?}`
2. `require_api_key` validates the API key (no-op when keys are unset)
3. `rate_limit` checks the per-minute bucket
4. Idempotency cache hit → return cached response
5. Response cache hit → return cached response
6. `Redactor.redact(text, policy=...)`:
   - If policy provided: iterate `policy.fields`, dispatch each to its strategy
   - Each strategy may invoke the detector, apply its own substitution
   - `apply_spans` mutates the working text with the substitutions
7. Cache the response + record an `AuditEvent`
8. Return the `RedactionResult` as JSON

## Why these abstractions

- **`Detector` Protocol**: only one impl in v1 (GLiNER2), but Piiranha and
  others exist. Real substitutability — keeps swap points honest.
- **`Strategy` Protocol**: five genuinely different code paths. No
  speculative polymorphism here.
- **`AuditBackend` Protocol**: explicitly requested pluggable; one impl ships.
- **No `RedactorFactory`**: composition is direct in `lifespan()`.
- **No `policy.Registry`**: load by path; YAML files are the registry.
