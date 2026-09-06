# Deployment

## Docker Compose (default)

```bash
docker compose up
curl http://localhost:8000/healthz
```

Brings up `redax` and `redis` with healthcheck-gated dependency. Volumes
persist the model cache and audit log.

## Configuration

All settings read from environment variables prefixed with `REDAX_`. See
`app/config.py:Settings` for the full list.

| Variable | Default | Notes |
|---|---|---|
| `REDAX_LOG_LEVEL` | `INFO` | structlog level |
| `REDAX_HOST` | `0.0.0.0` | uvicorn bind address |
| `REDAX_PORT` | `8000` | uvicorn bind port |
| `REDAX_REDIS_URL` | `redis://localhost:6379/0` | for jobs / cache / rate limit |
| `REDAX_MODEL_CACHE` | `./models_cache` | HF_HOME redirect |
| `REDAX_MODEL_NAME` | `fastino/gliner2-privacy-filter-PII-multi` | HF model id |
| `REDAX_POLICIES_DIR` | `./policies` | where to find policy YAMLs |
| `REDAX_DEFAULT_POLICY` | `default` | name of the default policy |
| `REDAX_AUDIT_PATH` | `./audit.jsonl` | append-only audit log path |
| `REDAX_HASH_SALT` | `change-me` | salt for `hash` strategy and cache keys |
| `REDAX_MAX_TEXT_CHARS` | `100000` | reject inputs longer than this |
| `REDAX_API_KEYS` | `""` | comma-separated; empty disables auth |
| `REDAX_RATE_LIMIT_PER_MINUTE` | `60` | per API key; 0 disables |
| `REDAX_CACHE_TTL_SECONDS` | `3600` | response cache TTL |
| `REDAX_IDEMPOTENCY_TTL_SECONDS` | `86400` | idempotency cache TTL |
| `REDAX_MAX_INFLIGHT` | `32` | jobs admitted while this many are in flight; else 429 |
| `REDAX_JOB_TTL_SECONDS` | `86400` | how long job records live in Redis |
| `REDAX_OTLP_ENDPOINT` | `""` | OTLP gRPC endpoint for traces |

## Production checklist

- Set `REDAX_API_KEYS` (comma-separated) to enable auth
- Set `REDAX_HASH_SALT` to a per-deployment random value
- Mount `REDAX_AUDIT_PATH` to durable storage (e.g. an EBS volume or a
  log shipper tail)
- Set `REDAX_REDIS_URL` to a stable Redis (jobs and rate limit depend on it)
- Behind a load balancer: configure `/readyz` as the readiness probe;
  `/healthz` is always 200

## Observability

- Prometheus metrics on `GET /metrics`
- Structured JSON logs on stdout (log_level configurable)
- OpenTelemetry traces via OTLP gRPC if `REDAX_OTLP_ENDPOINT` is set

## WASM bundle (browser)

```bash
make build-wasm
cd examples/wasm-demo
python3 -m http.server 8080
# Open http://localhost:8080
```

The model (`wasm/model.int8.onnx`) must be served alongside the page.
