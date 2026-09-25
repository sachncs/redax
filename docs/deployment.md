# Deployment

## Docker Compose (default)

```bash
docker compose up
curl http://localhost:8000/healthz
```

Brings up `redax` and `redis` with healthcheck-gated dependency. Volumes
persist the model cache and audit log.

## Deployment tiers

Choose the smallest tier that matches the boundary you need. Redis is not
required for a single-process redaction service when caching, rate limiting,
and asynchronous jobs are disabled, but production authentication and trusted
hosts are still required.

| Tier | Runtime | Redis | Intended use |
|---|---|---|---|
| Simple | One Python/Docker process, usually `REDAX_DETECTOR=regex` | Optional; disable rate limiting and do not use cache/jobs when absent | Local or small controlled service with deterministic structured detection |
| Standard | One or a few processes with the pinned local GLiNER2 model | Recommended for rate limits, cache, idempotency, and jobs | The default production starting point |
| Scaled | Multiple identical API replicas behind an ingress | Shared, durable Redis with a unique namespace | Higher throughput with consistent model, policy, secret, and limit configuration |

The current `/v1/jobs` implementation executes work in FastAPI background
tasks inside the receiving process. It is bounded and useful for modest jobs,
but it is not a durable distributed worker queue; use a separate worker design
before treating jobs as a high-scale workload.

## Configuration

All settings read from environment variables prefixed with `REDAX_`. See
`app/config.py:Settings` for the full list.

| Variable | Default | Notes |
|---|---|---|
| `REDAX_LOG_LEVEL` | `INFO` | structlog level |
| `REDAX_HOST` | `0.0.0.0` | uvicorn bind address |
| `REDAX_PORT` | `8000` | uvicorn bind port |
| `REDAX_REDIS_URL` | `redis://localhost:6379/0` | for jobs / cache / rate limit |
| `REDAX_REDIS_NAMESPACE` | `redax` | namespace all Redis keys when sharing a Redis instance |
| `REDAX_SERVICE_NAME` | `redax` | service name used by tracing and diagnostics |
| `REDAX_ENV` | `prod` | `dev` permits local unauthenticated development; `prod` requires API keys and trusted hosts |
| `REDAX_TRUSTED_HOSTS` | `""` | comma-separated hostnames required in production |
| `REDAX_CORS_ORIGINS` | `""` | comma-separated browser origins; empty disables browser CORS |
| `REDAX_MODEL_CACHE` | `./models_cache` | HF_HOME redirect |
| `REDAX_MODEL_NAME` | `fastino/gliner2-privacy-filter-PII-multi` | HF model id |
| `REDAX_MODEL_REVISION` | pinned commit | model revision required for reproducible loading |
| `REDAX_MODEL_THRESHOLD` | `0.5` | GLiNER2 detection threshold |
| `REDAX_DETECTOR` | `gliner2` | `gliner2` or explicit `regex` mode |
| `REDAX_POLICIES_DIR` | `./policies` | where to find policy YAMLs |
| `REDAX_DEFAULT_POLICY` | `default` | name of the default policy |
| `REDAX_AUDIT_PATH` | `./audit.jsonl` | append-only audit log path |
| `REDAX_HASH_SALT` | `change-me` | rejected at startup; set a unique random value |
| `REDAX_MAX_TEXT_CHARS` | `100000` | reject inputs longer than this |
| `REDAX_API_KEYS` | `""` | comma-separated; required when `REDAX_ENV=prod` |
| `REDAX_RATE_LIMIT_PER_MINUTE` | `60` | per API key; 0 disables |
| `REDAX_RATE_LIMIT_FAIL_OPEN` | `false` | allow authenticated traffic when Redis rate limiting is unavailable |
| `REDAX_CACHE_TTL_SECONDS` | `3600` | response cache TTL |
| `REDAX_CACHE_SHARED` | `false` | share the response cache across deployments (requires identical `REDAX_HASH_SALT`) |
| `REDAX_IDEMPOTENCY_TTL_SECONDS` | `86400` | idempotency cache TTL |
| `REDAX_MAX_INFLIGHT` | `32` | jobs admitted while this many are in flight; else 429 |
| `REDAX_MAX_JOBS_PER_KEY` | `50` | max admitted jobs per API key; else 429 |
| `REDAX_JOB_TTL_SECONDS` | `86400` | how long job records live in Redis |
| `REDAX_STREAM_CHUNK_CHARS` | `2000` | default SSE chunk size when the client omits `chunk_chars` |
| `REDAX_STREAM_CHUNK_BYTES` | `4096` | per-event UTF-8 byte ceiling in `/v1/redact/stream` |
| `REDAX_AUDIT_FSYNC` | `true` | fsync each audit line written |
| `REDAX_AUDIT_MAX_BYTES` | `1000000000` | rotate the audit log when it reaches this size |
| `REDAX_AUDIT_ROTATION_BACKUPS` | `5` | keep this many rotated audit files; 0 truncates instead |
| `REDAX_AUDIT_RETENTION_SECONDS` | `7776000` | drop audit lines older than this at startup |
| `REDAX_REQUEST_TIMEOUT_SECONDS` | `30` | per-request and job inference timeout |
| `REDAX_INFERENCE_CONCURRENCY` | `2` | concurrent model detector calls |
| `REDAX_MULTI_PASS_MAX` | `3` | maximum detector passes for `multi_pass` policies |
| `REDAX_PIPELINE_ENABLED` | `true` | enable staged pipeline wiring when a model detector is active |
| `REDAX_PIPELINE_BREAKER_THRESHOLD` | `3` | consecutive model failures before opening the circuit |
| `REDAX_PIPELINE_BREAKER_COOLDOWN_S` | `5` | seconds before a circuit probe |
| `REDAX_METRICS_BY_TENANT` | `false` | reserved setting; tenant labels are disabled by default |
| `REDAX_WORKER_CONCURRENCY` | `1` | reserved for the planned arq worker (`redax-worker`); jobs currently run in-process via FastAPI background tasks |
| `REDAX_OTLP_ENDPOINT` | `""` | OTLP gRPC endpoint for traces |

## Production checklist

- Set `REDAX_ENV=prod`, `REDAX_API_KEYS`, and `REDAX_TRUSTED_HOSTS`
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
