# Deployment

## Docker Compose (default)

```bash
docker compose up
curl http://localhost:8000/healthz
```

Brings up `redax`, `redax-worker`, and `redis` with healthcheck-gated
dependency. Volumes persist the model cache and audit log. This remains a
development topology with ephemeral Redis and shared local audit storage.

## Kubernetes reference topology

Production-shaped Kubernetes assets live in
[`deploy/kubernetes/`](../deploy/kubernetes/README.md). They define three API
replicas, two worker replicas, rolling-update budgets,
readiness/startup/liveness probes, CPU/memory bounds, restricted security
contexts, and CPU-based autoscaling. Redis is intentionally external and must
be supplied through the `redax-redis` Secret. Replace the example image tag
with the signed release digest before applying the manifests.

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

The `/v1/jobs` API writes accepted work to Redis and enqueues it for the
separate `redax-worker` process. Run API and worker replicas independently;
the API tier can scale for request traffic while worker concurrency scales for
model throughput. Redis persistence, failover, queue recovery, and worker
drain behavior remain deployment acceptance gates.

## Configuration

All settings read from environment variables prefixed with `REDAX_`. See
`app/config.py:Settings` for the full list.

| Variable | Default | Notes |
|---|---|---|
| `REDAX_LOG_LEVEL` | `INFO` | structlog level |
| `REDAX_HOST` | `0.0.0.0` | uvicorn bind address |
| `REDAX_PORT` | `8000` | uvicorn bind port |
| `REDAX_REDIS_URL` | `redis://localhost:6379/0` | for jobs / cache / rate limit |
| `REDAX_REDIS_REQUIRED` | `false` | when true, readiness fails unless the Redis client and durable job queue are connected |
| `REDAX_REDIS_NAMESPACE` | `redax` | namespace all Redis keys when sharing a Redis instance |
| `REDAX_REDIS_CONNECT_TIMEOUT_SECONDS` | `1.0` | bounded Redis connection timeout |
| `REDAX_REDIS_SOCKET_TIMEOUT_SECONDS` | `1.0` | bounded Redis command socket timeout |
| `REDAX_REDIS_MAX_CONNECTIONS` | `64` | per-process Redis pool bound |
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
| `REDAX_AUDIT_REQUIRED` | `true` | fail redaction requests closed when audit is uninitialized, unavailable, or saturated |
| `REDAX_HASH_SALT` | `change-me` | rejected at startup; set a unique random value |
| `REDAX_MAX_TEXT_CHARS` | `100000` | reject inputs longer than this |
| `REDAX_API_KEYS` | `""` | comma-separated; required when `REDAX_ENV=prod` |
| `REDAX_API_KEY_SCOPES` | `""` | optional JSON object mapping each configured key to scopes such as `redact`, `detect`, `jobs`, `policies:read`, and `metrics:read`; omitted means legacy full access |
| `REDAX_RATE_LIMIT_PER_MINUTE` | `60` | per API key; 0 disables |
| `REDAX_RATE_LIMIT_FAIL_OPEN` | `false` | allow authenticated traffic when Redis rate limiting is unavailable |
| `REDAX_CACHE_TTL_SECONDS` | `3600` | response cache TTL |
| `REDAX_CACHE_SHARED` | `false` | share the response cache across deployments (requires identical `REDAX_HASH_SALT`) |
| `REDAX_IDEMPOTENCY_TTL_SECONDS` | `86400` | idempotency cache TTL |
| `REDAX_MAX_INFLIGHT` | `32` | jobs admitted while this many are in flight; else 429 |
| `REDAX_MAX_JOBS_PER_KEY` | `50` | max admitted jobs per API key; else 429 |
| `REDAX_MAX_CONCURRENT_REQUESTS` | `128` | per-process HTTP handler admission cap; excess requests receive 503 |
| `REDAX_REQUEST_ADMISSION_TIMEOUT_SECONDS` | `0.01` | maximum wait for a request-admission slot before 503 |
| `REDAX_JOB_TTL_SECONDS` | `86400` | how long job records live in Redis |
| `REDAX_JOB_STALE_SECONDS` | `300` | startup recovery threshold for queued/running jobs left without a state update |
| `REDAX_STREAM_CHUNK_CHARS` | `2000` | default SSE chunk size when the client omits `chunk_chars` |
| `REDAX_STREAM_CHUNK_BYTES` | `4096` | per-event UTF-8 byte ceiling in `/v1/redact/stream` |
| `REDAX_AUDIT_FSYNC` | `true` | fsync each audit line written |
| `REDAX_AUDIT_MAX_BYTES` | `1000000000` | rotate the audit log when it reaches this size |
| `REDAX_AUDIT_ROTATION_BACKUPS` | `5` | keep this many rotated audit files; 0 truncates instead |
| `REDAX_AUDIT_RETENTION_SECONDS` | `7776000` | drop audit lines older than this at startup |
| `REDAX_REQUEST_TIMEOUT_SECONDS` | `30` | per-request and job inference timeout |
| `REDAX_SHUTDOWN_TIMEOUT_SECONDS` | `30` | total budget for dependency cleanup after readiness drops |
| `REDAX_INFERENCE_CONCURRENCY` | `2` | concurrent model detector calls |
| `REDAX_MULTI_PASS_MAX` | `3` | maximum detector passes for `multi_pass` policies |
| `REDAX_PIPELINE_ENABLED` | `true` | enable staged pipeline wiring when a model detector is active |
| `REDAX_PIPELINE_BREAKER_THRESHOLD` | `3` | consecutive model failures before opening the circuit |
| `REDAX_PIPELINE_BREAKER_COOLDOWN_S` | `5` | seconds before a circuit probe |
| `REDAX_METRICS_BY_TENANT` | `false` | reserved setting; tenant labels are disabled by default |
| `REDAX_WORKER_CONCURRENCY` | `1` | concurrent ARQ jobs per `redax-worker` process |
| `REDAX_JOB_RETRY_JITTER_SECONDS` | `1.0` | maximum random delay added to exponential job retries |
| `REDAX_JOB_DEAD_LETTER_MAX` | `1000` | maximum payload-free permanent-failure records retained in Redis |
| `REDAX_JOB_PAYLOAD_ENCRYPTION_KEY` | `""` | Fernet key for ARQ payloads; required in `prod`, generate with `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` |
| `REDAX_OTLP_ENDPOINT` | `""` | OTLP gRPC endpoint for traces |

## Production checklist

- Set `REDAX_ENV=prod`, `REDAX_API_KEYS`, and `REDAX_TRUSTED_HOSTS`
- Set `REDAX_HASH_SALT` to a per-deployment random value
- Mount `REDAX_AUDIT_PATH` to durable storage (e.g. an EBS volume or a
  log shipper tail)
- Set `REDAX_REDIS_URL` to a stable Redis (jobs and rate limit depend on it)
- Run `redax-worker` as a separate deployment with the same model, policy, and
  Redis configuration as the API tier
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
