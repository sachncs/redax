# Production readiness review

Status: **NOT production-grade yet**. This is a checkable review of the
current repository, not a marketing claim. A requirement is `PASS` only when
the cited evidence covers the stated scope; `FAIL` means implementation or
evidence is still missing; `N/A` means the requirement is outside the current
supported product surface.

Review baseline: `0c16f0e` and the current `master` tree. Update this matrix
as each production milestone lands.

## Reliability and distributed correctness

| Requirement | Status | Evidence / gap |
|---|---|---|
| API correctness across replicas | PARTIAL | Redis-backed idempotency, rate limits, durable jobs, audit, and model-breaker coordination are implemented with atomic integration coverage; `tests/integration/test_api_replicas.py::test_two_api_replicas_share_idempotency_state` proves replay and same-key/different-body conflict across two real API processes, while HA Redis and failure evidence remain pending. |
| Durable jobs survive worker failure | PARTIAL | ARQ worker, jittered retries, atomic admission/claim/completion/cancellation, startup stale-job reconciliation, bounded payload-free DLQ records, real-Redis recovery after a killed worker process, and a real-Redis SIGTERM drain of an active job are tested; Redis failover and production-scale evidence remain pending. |
| Redis failure behavior is explicit | PASS | `docs/failure-modes.md`, typed Redis exception handling in API/jobs/readiness, `app/ratelimit.py`, and configuration tests define current cache/job/rate-limit degradation. Durable-job failover behavior remains pending. |
| Graceful shutdown is verified | PARTIAL | Readiness drops before teardown, a process-level Uvicorn SIGTERM test drains a held HTTP request within `REDAX_SHUTDOWN_TIMEOUT_SECONDS`, and a real-Redis ARQ test verifies SIGTERM stops pickup and drains an active job; active-stream signal integration evidence is still pending. |
| Overload is bounded | PARTIAL | Declared request-body, text, aggregate batch, chunk, total stream duration, HTTP, inference, and job admission limits exist; chunked slow-client, Redis-pool, worker queue, and sustained overload recovery evidence remain. |
| Dependency recovery works | PARTIAL | Real-Redis worker lease recovery, disposable Redis restart/reconnect, and required Redis-audit write recovery after an outage are tested; managed Redis failover evidence remains missing. |

## Security and privacy

| Requirement | Status | Evidence / gap |
|---|---|---|
| Production configuration fails securely | PASS | `Settings.verify()`, `tests/unit/test_config.py`, and production API-key/trusted-host/hash-salt checks. |
| Scoped authorization | PARTIAL | Optional JSON scopes enforce redact, detect, jobs, policies, and metrics endpoints; overlapping active keys and deployment-native revocation are supported, while external rotation/control-plane audit remain pending. |
| Secrets stay out of telemetry | PARTIAL | Error, audit, cache, idempotency, metrics, detector-failure log, metadata-only request/stream trace, auth/validation failures, and real-Redis job/audit canaries exist; remaining failure and exporter coverage is incomplete. |
| Automated PII leak suite | PARTIAL | Canaries cover synchronous response, metrics, audit, detector-failure logs, auth/validation failures, Redis outage, timeout, streaming response/audit/traces/cancellation, durable-job success/failure/cancellation output/store/audit, and real-Redis persisted values; exporter matrix coverage remains pending. Required file-audit first-write failure now rejects the request before success. |
| No silent raw pass-through after internal failure | PARTIAL | Model fallback, synchronous required-audit rejection, error handlers, and stream cancellation are tested; policy, shutdown, and full failure-matrix coverage remain. |
| Threat model matches implementation | PASS | `docs/threat-model.md`, `docs/data-flow.md`, and `docs/failure-modes.md`; update when the worker/audit architecture lands. |
| High/critical vulnerability gate | PARTIAL | GitHub security run `36560012477` passed SBOM generation and the filesystem Trivy gate; the successful `v0.1.0` release run `36130306271` also scanned the release image, but recurring release evidence is still required. |

## Scalability and performance

| Requirement | Status | Evidence / gap |
|---|---|---|
| Horizontally scalable API | PARTIAL | Reference Kubernetes API replicas, probes, rolling budgets, shared Redis audit, and a two-process Redis-backed idempotency gate now exist without a shared filesystem dependency; HA Redis, failover, and multi-replica failure evidence remain pending. |
| Independently scalable workers | PARTIAL | `redax-worker` and Redis-backed ARQ enqueueing exist; capacity, lease recovery, and deployment evidence are pending. |
| Measured performance characteristics | PARTIAL | `docs/benchmarks/regex-local-baseline.json`, current Python 3.13 API baseline/sustained artifacts, a 300-request concurrency matrix at 1/10/20/40, and a 1,000-request warm ramp at 1/20/40/80/128/160 record detector/API p50-p99, throughput, CPU, and RSS locally; worker/model/cache/batch/stream capacity and soak evidence remain pending. |
| Known saturation limits | PARTIAL | The local warm ramp identifies a regression knee near concurrency 80 and p99 degradation at 128/160; CI now gates a 500-request regex ramp at concurrency 10/40/80 with error and p99 thresholds, but this is not a production safe limit until server-side resource metrics, representative workloads, and HA/soak evidence exist. |
| Autoscaling guidance | PARTIAL | Kubernetes HPAs now combine CPU with per-pod admitted-request concurrency and worker queue depth/oldest-age metrics; the reference deployment documents Prometheus Adapter requirements and conservative starting targets. Production load validation and measured scaling limits remain pending. |

## Maintainability and interfaces

| Requirement | Status | Evidence / gap |
|---|---|---|
| Clear domain boundaries | PASS | `docs/architecture.md`, route modules, detector/redactor/audit separation, and typed settings. |
| Versioned persisted schemas | PARTIAL | Idempotency, response-cache, durable-job, and audit-event records carry schema versions; incompatible durable-job records are now refused by reads, status updates, terminal transitions, and stale reaping; migration evidence for all persisted stores is still pending. |
| Configuration validation and documentation | PASS | `Settings` plus documented configuration drift tests. |
| API/OpenAPI contract | PASS | API contract tests and documented paths; authorization scopes are not yet part of the contract. |
| Meaningful coverage threshold | PASS | `pyproject.toml` enforces 80% branch-aware coverage through `make test-cov`; the Python 3.13 suite currently measures 83.43%. |

## Observability and operations

| Requirement | Status | Evidence / gap |
|---|---|---|
| Actionable RED/USE metrics | PARTIAL | RED metrics, Prometheus alert rules, accepted in-flight job depth, response-size histogram, shared Redis-backed oldest queue age, Redis pool gauges/alert, expiring Redis-backed worker heartbeats, job duration/retry/permanent-failure metrics, versioned audit records with non-secret principal IDs, and a Grafana dashboard are checked in; worker capacity and exporter evidence remain. |
| Privacy-safe structured logs/traces | PARTIAL | Access/error/audit paths avoid values; request and streaming spans emit only method/status metadata with canary assertions, while OTLP exporter delivery and all failure paths need evidence. |
| Alerts and dashboards | PARTIAL | Checked-in Prometheus alert rules and a Grafana dashboard cover HTTP, audit, dependency, API replica, worker availability, queue age, retries, job latency, and Redis-pool utilization; exporter and production-query evidence remain. |
| Operational runbooks | PARTIAL | Current runbooks in `docs/runbooks/` describe safe response and evidence, including the Redis audit mode; managed durability and in-process job limitations remain. |

## Deployment, recovery, and release

| Requirement | Status | Evidence / gap |
|---|---|---|
| Hardened container | PARTIAL | Non-root, hash-enforced locked dependencies, model verification, slim runtime, and a digest-pinned Python base exist; Kubernetes config supplies read-only filesystem/capability restrictions, and release run `36130306271` generated an image SBOM and passed the release scan; standalone Docker runtime restrictions remain deployment-specific. |
| Reference HA deployment | PARTIAL | `deploy/kubernetes/` defines API/worker replicas, PDBs, probes, resource bounds, autoscaling, immutable signed image digest, and fail-closed NetworkPolicies; external Redis HA, ingress/TLS, and deployment smoke/failure evidence remain pending. |
| Health/readiness/startup probes | PARTIAL | `/healthz`, `/readyz`, and Docker probes exist; required Redis readiness performs a bounded ping, mandatory audit failure drops readiness, and readiness drops before teardown, while full deployment drain evidence remains. |
| Rolling deployment and rollback | PARTIAL | Immutable image pinning, zero-unavailable rolling strategies, PDBs, mixed-version state-compatibility tests, and an operator rollback procedure are checked in; a disposable-cluster rollout/rollback drill remains pending. |
| Backup/restore and RPO/RTO | PARTIAL | A real Redis RDB restore drill and operator backup/restore runbook now exist; managed-service restore, audit-volume restore, and measured production RPO/RTO remain pending. |
| Reproducible release artifacts | PASS | `v0.1.0` release publishes wheel, sdist, checksums, and GHCR image with a tag/version guard; release run `36130306271` generated the image SBOM, signed the image, and published provenance attestation. |

## Required next gates

The review cannot become `PASS` until the P0/P1 failures above have named test
or artifact evidence. The execution order is in
[`PRODUCTION_PLAN.md`](PRODUCTION_PLAN.md); the target SLO definitions are in
[`docs/slo.md`](docs/slo.md), and current dependency behavior is in
[`docs/failure-modes.md`](docs/failure-modes.md).
