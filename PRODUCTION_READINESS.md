# Production readiness review

Status: **NOT production-grade yet**. This is a checkable review of the
current repository, not a marketing claim. A requirement is `PASS` only when
the cited evidence covers the stated scope; `FAIL` means implementation or
evidence is still missing; `NOT APPLICABLE` means the requirement is outside the current
supported product surface.

Review baseline: `cc665ff` and the current `master` tree. The latest review
also includes constant-time API-key rotation checks, production wildcard-CORS
rejection, bounded audit shutdown, a real OTLP delivery/privacy canary, bounded
entity-type and inline-policy structures, count/time-bounded Redis audit
retention with a real-Redis age regression test, idempotency publication before
response-cache publication, fail-closed explicit idempotency requests when
Redis is unavailable, fail-closed rate limiting when a retained Redis store is
disconnected, and bounded CI reliability-gate durations.
The request-admission suite also proves a saturated held stream returns 503 to
excess traffic and that the next request succeeds after the stream drains;
branch-scoped CI/security concurrency cancellation prevents superseded launch
gates from consuming runner capacity indefinitely, and the HTTP boundary now
restricts camera, geolocation, microphone, payment, and USB browser features.
`PARTIAL` is not an acceptance status: unresolved implementation or evidence
gaps are recorded as `FAIL` until the stated scope is proven.
Update this matrix as each production milestone lands.

## Reliability and distributed correctness

| Requirement | Status | Evidence / gap |
|---|---|---|
| API correctness across replicas | FAIL | Redis-backed idempotency, rate limits, durable jobs, audit, and model-breaker coordination are implemented with atomic integration coverage; `tests/integration/test_api_replicas.py::test_two_api_replicas_share_idempotency_state` proves replay and same-key/different-body conflict across two real API processes, while HA Redis and failure evidence remain pending. |
| Durable jobs survive worker failure | FAIL | ARQ worker, jittered retries, atomic admission/claim/completion/cancellation, startup stale-job reconciliation, bounded payload-free DLQ records, real-Redis recovery after a killed worker process, and a real-Redis SIGTERM drain of an active job are tested; CI run [36590632488](https://github.com/sachncs/redax/actions/runs/36590632488) now executes the Redis reliability and replica suites with the Redis server binary installed and uploads JUnit evidence; managed Redis failover and production-scale evidence remain pending. |
| Redis failure behavior is explicit | PASS | `docs/failure-modes.md`, typed Redis exception handling in API/jobs/readiness, `app/ratelimit.py`, `tests/integration/test_api_redact.py::test_response_cache_failure_recomputes_without_leaking_canary`, and configuration tests define current cache/job/rate-limit degradation. Durable-job and managed-Redis failover behavior remain pending. |
| Graceful shutdown is verified | PASS | Readiness drops before teardown; process-level Uvicorn SIGTERM tests cover a held HTTP request and a backpressured active stream, while a real-Redis ARQ test verifies SIGTERM stops pickup and drains an active job within the configured deadline. |
| Overload is bounded | FAIL | Declared and chunked request-body bytes plus a bounded chunked-body receive timeout, text, aggregate batch, chunk, total stream duration, HTTP, inference, and job admission limits exist; `tests/unit/test_middleware.py::test_request_admission_recovers_after_saturation` proves local admission recovery after a held stream; Redis-pool, worker queue, and sustained overload recovery evidence remain. |
| Dependency recovery works | FAIL | Real-Redis worker lease recovery, disposable Redis restart/reconnect, required Redis-audit write recovery after an outage, and `tests/unit/test_main_recovery.py::test_refresh_job_metrics_reconnects_store_and_queue` cover recovery behavior; CI run [36590632488](https://github.com/sachncs/redax/actions/runs/36590632488) passes the Redis restart/restore and replica suites; managed Redis failover evidence remains missing. |

## Security and privacy

| Requirement | Status | Evidence / gap |
|---|---|---|
| Production configuration fails securely | PASS | `Settings.verify()`, `tests/unit/test_config.py`, and production API-key/trusted-host/hash-salt checks. |
| Scoped authorization | FAIL | Optional JSON scopes enforce redact, detect, jobs, policies, and metrics endpoints; overlapping active keys and deployment-native revocation are supported, while external rotation/control-plane audit remain pending. |
| Secrets stay out of telemetry | FAIL | Error, audit, cache, idempotency, metrics, detector-failure log, metadata-only request/stream trace, bounded OTLP exporter configuration, asynchronous export-failure counting, auth/validation failures, invalid-policy diagnostics, job identifiers, real-Redis job/audit canaries, and a real OTLP gRPC delivery/privacy canary exist; collector-side delivery evidence is incomplete. |
| Automated PII leak suite | FAIL | Canaries cover synchronous response, metrics, audit, detector-failure logs, auth/validation failures, invalid policies, job lookup errors, Redis outage, timeout, streaming response/audit/traces/cancellation, durable-job success/failure/cancellation output/store/audit, and real-Redis persisted values; exporter delivery matrix coverage remains pending. Required file-audit first-write failure now rejects the request before success. |
| No silent raw pass-through after internal failure | FAIL | Model fallback is explicit and audited; an unavailable model with no regex matches now returns 503; a missing or invalid configured default policy returns a generic 503 across synchronous, batch, streaming, and job admission paths; malformed inline policies are rejected before stream/job execution; batch/stream detector exceptions are covered by canary tests; synchronous, batch, stream, and durable-job audit failures are covered by regression tests; request entity types and inline policy structures are bounded before execution; shutdown and full failure-matrix coverage remain. |
| Threat model matches implementation | PASS | `docs/threat-model.md`, `docs/data-flow.md`, and `docs/failure-modes.md`; update when the worker/audit architecture lands. |
| High/critical vulnerability gate | FAIL | GitHub security run `36560012477` passed SBOM generation and the filesystem Trivy gate; the successful `v0.1.0` release run `36130306271` also scanned the release image, but recurring release evidence is still required. |

## Scalability and performance

| Requirement | Status | Evidence / gap |
|---|---|---|
| Horizontally scalable API | FAIL | Reference Kubernetes API replicas, probes, rolling budgets, shared Redis audit, and a two-process Redis-backed idempotency gate now exist without a shared filesystem dependency; HA Redis, failover, and multi-replica failure evidence remain pending. |
| Independently scalable workers | FAIL | `redax-worker` and Redis-backed ARQ enqueueing exist; capacity, lease recovery, and deployment evidence are pending. |
| Measured performance characteristics | FAIL | `docs/benchmarks/regex-local-baseline.json`, current Python 3.13 API baseline/sustained artifacts, a 300-request concurrency matrix at 1/10/20/40, a 1,000-request warm ramp at 1/20/40/80/128/160, CI batch/stream/cache-hot/cache-cold gates, a 15-second CI soak gate, the CI performance workflow's authenticated durable-job gate, and verified pinned-model artifact [run 36589780886](https://github.com/sachncs/redax/actions/runs/36589780886) record p50-p99, throughput, CPU, RSS, model revision, model manifest digest, and lockfile hash; representative production-topology workload evidence remains pending. |
| Known saturation limits | FAIL | The local warm ramp identifies a regression knee near concurrency 80 and p99 degradation at 128/160; CI now gates a 500-request regex ramp at concurrency 10/40/80 with error and p99 thresholds, but this is not a production safe limit until server-side resource metrics, representative workloads, and HA/soak evidence exist. |
| Autoscaling guidance | FAIL | Kubernetes HPAs now combine CPU with per-pod admitted-request concurrency and worker queue depth/oldest-age metrics; the reference deployment documents Prometheus Adapter requirements and conservative starting targets. Production load validation and measured scaling limits remain pending. |

## Maintainability and interfaces

| Requirement | Status | Evidence / gap |
|---|---|---|
| Clear domain boundaries | PASS | `docs/architecture.md`, route modules, detector/redactor/audit separation, durable ARQ worker boundary, and typed settings. |
| Versioned persisted schemas | FAIL | Idempotency, response-cache, durable-job, and audit-event records carry schema versions; incompatible durable-job records are now refused by reads, status updates, terminal transitions, and stale reaping; migration evidence for all persisted stores is still pending. |
| Configuration validation and documentation | PASS | `Settings` plus documented configuration drift tests. |
| API/OpenAPI contract | PASS | API contract tests and documented paths; generated OpenAPI advertises the `X-API-Key` scheme and the scope matrix is documented as the runtime authorization contract. |
| Bounded policy and request structures | PASS | `app/api/models.py` bounds request entity-type lists and labels; `app/redaction/policies.py` bounds field count, field names, option strings, entity types, detector passes, and hash output length; `tests/unit/test_api_limits.py` and `tests/unit/test_policies.py` exercise rejection boundaries. |
| Meaningful coverage threshold | PASS | `pyproject.toml` enforces 80% branch-aware coverage through `make test-cov`; the Python 3.13 suite currently measures 84.78% (520 passed, 12 skipped). |

## Observability and operations

| Requirement | Status | Evidence / gap |
|---|---|---|
| Actionable RED/USE metrics | FAIL | RED metrics, Prometheus alert rules, accepted in-flight job depth, response-size histogram, shared Redis-backed oldest queue age, Redis pool gauges/alert, expiring Redis-backed worker heartbeats, aggregated worker active/capacity gauges with saturation alert, job duration/retry/permanent-failure metrics, versioned HMAC-verifiable audit records with non-secret principal IDs, and a Grafana dashboard are checked in; exporter evidence remains. |
| Privacy-safe structured logs/traces | FAIL | Access/error/audit paths avoid values; request and streaming spans emit only method/status metadata with canary assertions, the real OTLP gRPC exporter delivery canary verifies metadata-only spans, OTLP buffering is explicitly bounded, asynchronous and shutdown export failures have a metric and alert; collector-side failure evidence remains. |
| Alerts and dashboards | FAIL | Checked-in Prometheus alert rules and a Grafana dashboard cover HTTP, audit, dependency, API replica, worker availability, queue age, retries, job latency, and Redis-pool utilization; exporter and production-query evidence remain. |
| Operational runbooks | FAIL | Current runbooks in `docs/runbooks/` describe Redis, model, jobs, audit, capacity/overload, rollback/recovery, API-key rotation, and suspected-PII incidents with privacy-safe verification; managed durability and production-scale recovery evidence remain. |

## Deployment, recovery, and release

| Requirement | Status | Evidence / gap |
|---|---|---|
| Hardened container | FAIL | Non-root, hash-enforced locked dependencies, model verification, slim runtime, and a digest-pinned Python base exist; Kubernetes config supplies read-only filesystem/capability restrictions, and release run `36130306271` generated an image SBOM and passed the release scan; standalone Docker runtime restrictions remain deployment-specific. |
| Reference HA deployment | FAIL | `deploy/kubernetes/` defines API/worker replicas, PDBs, probes, resource bounds, autoscaling, immutable signed image digest, fail-closed NetworkPolicies, and an ingress-nginx TLS/body/timeout contract; CI run [36591813088](https://github.com/sachncs/redax/actions/runs/36591813088) renders the topology, validates it against a disposable Kubernetes API server, and uploads the manifest artifact; push CI run [36602474954](https://github.com/sachncs/redax/actions/runs/36602474954) also built the current image, rolled out API/worker pods, exercised redaction and durable jobs, and completed rollback; external Redis HA and managed live failure evidence remain pending. |
| Health/readiness/startup probes | FAIL | `/healthz`, `/readyz`, and Docker probes exist; required Redis readiness performs a bounded ping, mandatory audit failure drops readiness, readiness drops before teardown, and run [36602474954](https://github.com/sachncs/redax/actions/runs/36602474954) verified the API startup/readiness path in a disposable cluster; full managed deployment drain evidence remains. |
| Rolling deployment and rollback | FAIL | Immutable image pinning, zero-unavailable rolling strategies, PDBs, mixed-version state-compatibility tests, an operator rollback procedure, and CI server-side validation of the rendered topology now exist; push CI run [36602474954](https://github.com/sachncs/redax/actions/runs/36602474954) completed disposable API/worker rollout, durable-job exercise, and API/worker rollout undo; managed production rollback evidence remains pending. |
| Backup/restore and RPO/RTO | FAIL | A real Redis RDB restore drill and operator backup/restore runbook now exist; managed-service restore, audit-volume restore, and measured production RPO/RTO remain pending. |
| Reproducible release artifacts | PASS | `v0.1.0` release publishes wheel, sdist, checksums, and GHCR image with a tag/version guard; release run `36130306271` generated the image SBOM, signed the image, and published provenance attestation. |

## Required next gates

The review cannot become `PASS` until the P0/P1 failures above have named test
or artifact evidence. The execution order is in
[`PRODUCTION_PLAN.md`](PRODUCTION_PLAN.md); the target SLO definitions are in
[`docs/slo.md`](docs/slo.md), and current dependency behavior is in
[`docs/failure-modes.md`](docs/failure-modes.md).
