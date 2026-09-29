# Failure-mode matrix

This matrix states the current externally visible behavior and the production
behavior required by the plan. “Current” is not automatically “acceptable for
HA”; gaps are marked explicitly.

| Dependency or event | Current behavior | Safety posture | Production acceptance condition |
|---|---|---|---|
| API keys missing in `prod` | Startup fails validation. | Fail closed. | Keep; add scoped principal/rotation evidence. |
| Trusted hosts missing in `prod` | Startup fails validation. | Fail closed. | Keep; document proxy/TLS boundary. |
| Redis unavailable at startup | App logs and continues with no job store; cache/idempotency/jobs are disabled; rate limiting fails closed unless explicit fail-open. | Mixed, explicit. | Readiness must reflect required deployment mode; restart/reconnect behavior is covered by the disposable Redis drill. |
| Redis unavailable during rate limit | Returns typed 503 by default; explicit `REDAX_RATE_LIMIT_FAIL_OPEN=true` allows traffic. | Configurable, documented. | Require explicit operator acknowledgement and alert on fail-open. |
| Redis unavailable during cache | Request recomputes; cache is skipped. | Fail open for optimization only. | Never let cache failure change redaction semantics. |
| Redis unavailable during jobs | Required Redis readiness performs a bounded ping and returns 503; new durable-job submissions return 503, while already accepted jobs depend on Redis durability and recovery. | Unsafe without HA/failover evidence. | Verify Redis HA, enqueue recovery, lease expiry, and worker retry/DLQ behavior. |
| Model cannot load in `prod` | Startup fails; dev may log and downgrade according to detector configuration. | Fail closed in prod. | Add readiness/startup and corrupted-model tests. |
| Model inference failure | Pipeline can use explicit regex fallback and records fallback; policy path returns an error according to route handling. | Route-dependent. | One documented policy matrix; no raw pass-through. |
| Model timeout | Synchronous request returns 504; job marks failure; stream emits timeout event. | Reject/fail closed. | Add cancellation and recovery tests. |
| Circuit breaker opens | Pipeline uses its explicit fallback marker; the production path coordinates open/probe state through a namespaced Redis hash, while Redis coordination failure uses the local breaker as an explicit load-shedding fallback. | Degraded, observable. | Keep shared-breaker Redis concurrency coverage and HA Redis evidence in the release gate. |
| Policy file missing/invalid | Validation/loading error prevents normal policy execution. | Reject. | Startup validation for required default policy and tests for rolling compatibility. |
| Audit backend unavailable | `REDAX_AUDIT_REQUIRED=true` rejects processing when the backend is uninitialized, has failed, or its bounded queue is full; optional mode records a metric and continues. File mode uses JSONL; Redis mode uses a bounded centralized metadata-only list and refuses startup without Redis. | Configurable, fail closed by default. | Verify centralized retention, managed Redis durability, and disk-failure propagation end to end. |
| Disk full / permission failure | File audit write failure is counted/logged and marks the required backend unavailable for subsequent requests. | Fail closed after detection. | Add synchronous write-acknowledgement or durable backend evidence for the first failed event. |
| Telemetry exporter unavailable | OTLP is optional; request processing should continue. | Fail open for telemetry. | Bound exporter buffers and verify no raw attributes. |
| Request too large | 413 for configured text limit; batch/stream have their own bounds. | Reject. | Add body, batch amplification, slow-client, and response-size limits. |
| Invalid or adversarial Unicode | Pydantic and code-point chunking validate input; property tests cover parts of the transform path. | Bounded in tested paths. | Add fuzz suite and CPU/memory budgets. |
| Client disconnects from stream | Stream cancellation is classified as status `499`, recorded in the stream span without request values, and generator cleanup always observes end-to-end latency; no audit event is emitted for an incomplete stream. | Bounded cancellation cleanup. | Keep signal-driven disconnect/shutdown integration coverage in the release gate. |
| API process dies | In-flight synchronous work is lost; safe because no response is emitted, but client retry semantics apply. Redis idempotency and the model breaker coordinate across surviving replicas. | Bounded. | Multi-replica retry/idempotency semantics must remain covered by the Redis integration gate. |
| SIGTERM / graceful shutdown | Readiness drops before cleanup; admitted HTTP requests drain, and ARQ stops picking new jobs while allowing active jobs to finish within the validated `REDAX_SHUTDOWN_TIMEOUT_SECONDS` window before cancelling/releasing remaining work. Queue, audit, and Redis cleanup then share the remaining budget. | Bounded, with forced cleanup after the deadline. | Add full active stream/job signal-driven integration evidence. |
| Worker dies mid-job | ARQ retries failed attempts; its in-progress lease expires at the bounded worker timeout and another worker can claim the queued job. Exhausted failures enter a bounded, payload-free Redis dead-letter list. | PARTIAL. | `tests/integration/test_redis_jobs.py::test_real_redis_job_recovers_after_worker_process_kill` proves process-kill recovery; Redis failover and production-scale drills remain required. |
| Duplicate job delivery | An atomic queued-to-running claim permits one worker delivery; later deliveries observe running/terminal state and do no work. Terminal completion is also atomic and releases capacity once. | Fail closed for malformed state. | `tests/integration/test_redis_jobs.py::test_real_redis_job_claim_allows_one_duplicate_delivery` and terminal-transition concurrency coverage. |
| Rolling deployment | HTTP state mostly reconstructs; job/background and persisted schema compatibility are not proven. | Incomplete. | Mixed-version Redis/schema and rollback tests. |

## Operator rule

When the chosen deployment mode cannot preserve the required privacy or
durability boundary, mark the instance unready or reject the request. Do not
silently downgrade a security-sensitive operation to pass-through.
