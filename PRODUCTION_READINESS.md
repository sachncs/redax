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
| API correctness across replicas | FAIL | Redis is shared for some state, but jobs and circuit breakers still have process-local behavior; no multi-replica integration gate. |
| Durable jobs survive worker failure | PARTIAL | ARQ worker, jittered retries, atomic admission/completion, startup stale-job reconciliation, bounded payload-free DLQ records, and real-Redis recovery after a killed worker process are tested; Redis failover and production-scale evidence remain pending. |
| Redis failure behavior is explicit | PASS | `docs/failure-modes.md`, `app/ratelimit.py`, and configuration tests define current cache/job/rate-limit degradation. Durable-job behavior remains pending. |
| Graceful shutdown is verified | PARTIAL | Readiness drops before teardown, admitted HTTP requests drain within `REDAX_SHUTDOWN_TIMEOUT_SECONDS`, and stream client cancellation is bounded and classified; active stream/job SIGTERM integration evidence is still pending. |
| Overload is bounded | PARTIAL | Declared request-body, text, aggregate batch, chunk, total stream duration, HTTP, inference, and job admission limits exist; chunked slow-client, Redis-pool, worker queue, and sustained overload recovery evidence remain. |
| Dependency recovery works | PARTIAL | Real-Redis worker lease recovery and disposable Redis server restart/reconnect are tested; mandatory file-audit recovery after backend restart is covered, while managed Redis failover and automatic audit-storage recovery evidence remain missing. |

## Security and privacy

| Requirement | Status | Evidence / gap |
|---|---|---|
| Production configuration fails securely | PASS | `Settings.verify()`, `tests/unit/test_config.py`, and production API-key/trusted-host/hash-salt checks. |
| Scoped authorization | PARTIAL | Optional JSON scopes enforce redact, detect, jobs, policies, and metrics endpoints; external rotation/revocation and a control-plane audit are pending. |
| Secrets stay out of telemetry | PARTIAL | Error, audit, cache, idempotency, metrics, detector-failure log, and metadata-only request/stream trace canaries exist; audit attribution uses keyed non-secret principal IDs, while full Redis/jobs/failure coverage is pending. |
| Automated PII leak suite | PARTIAL | Canaries cover synchronous response, metrics, audit, detector-failure logs, streaming response/audit/traces, and durable-job output/store/audit; the complete Redis, auth, validation, cancellation, and audit-failure matrix is pending. |
| No silent raw pass-through after internal failure | PARTIAL | Model fallback, audit-required rejection, error handlers, and stream cancellation are tested; policy, shutdown, and full failure-matrix coverage remain. |
| Threat model matches implementation | PASS | `docs/threat-model.md`, `docs/data-flow.md`, and `docs/failure-modes.md`; update when the worker/audit architecture lands. |
| High/critical vulnerability gate | PARTIAL | GitHub security run `36560012477` passed SBOM generation and the filesystem Trivy gate; the successful `v0.1.0` release run `36130306271` also scanned the release image, but recurring release evidence is still required. |

## Scalability and performance

| Requirement | Status | Evidence / gap |
|---|---|---|
| Horizontally scalable API | PARTIAL | Reference Kubernetes API replicas, probes, rolling budgets, and an opt-in shared Redis audit sink now exist; HA Redis and multi-replica failure evidence remain pending. |
| Independently scalable workers | PARTIAL | `redax-worker` and Redis-backed ARQ enqueueing exist; capacity, lease recovery, and deployment evidence are pending. |
| Measured performance characteristics | PARTIAL | `docs/benchmarks/regex-local-baseline.json` plus current Python 3.13 API baseline and sustained artifacts record detector/API p50-p99, throughput, CPU, and RSS locally; worker/model/cache/batch/stream capacity and soak evidence remain pending. |
| Known saturation limits | FAIL | Local baselines exist, but no ramp/spike/soak artifact establishes p99, queueing, CPU, memory, Redis, or model saturation limits. |
| Autoscaling guidance | FAIL | No production deployment or measured scaling model exists. |

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
| Actionable RED/USE metrics | PARTIAL | RED metrics, Prometheus alert rules, accepted in-flight job depth, response-size histogram, shared Redis-backed oldest queue age, Redis pool gauges/alert, versioned audit records with non-secret principal IDs, and a Grafana dashboard are checked in; worker-runtime metrics still need implementation/evidence. |
| Privacy-safe structured logs/traces | PARTIAL | Access/error/audit paths avoid values; request and streaming spans emit only method/status metadata with canary assertions, while OTLP exporter delivery and all failure paths need evidence. |
| Alerts and dashboards | PARTIAL | Checked-in Prometheus alert rules and a Grafana dashboard cover HTTP, audit, dependency, API replica, and worker availability; queue age, retries, and Redis-pool panels remain pending. |
| Operational runbooks | PARTIAL | Current runbooks in `docs/runbooks/` describe safe response and evidence, including the Redis audit mode; managed durability and in-process job limitations remain. |

## Deployment, recovery, and release

| Requirement | Status | Evidence / gap |
|---|---|---|
| Hardened container | PARTIAL | Non-root, pinned dependencies, model verification, slim runtime, and a digest-pinned Python base exist; Kubernetes config supplies read-only filesystem/capability restrictions, and release run `36130306271` generated an image SBOM and passed the release scan; standalone Docker runtime restrictions remain deployment-specific. |
| Reference HA deployment | PARTIAL | `deploy/kubernetes/` defines API/worker replicas, PDBs, probes, resource bounds, autoscaling, and an immutable signed image digest; external Redis HA and deployment smoke/failure evidence remain pending. |
| Health/readiness/startup probes | PARTIAL | `/healthz`, `/readyz`, and Docker probes exist; required Redis readiness now performs a bounded ping and readiness drops before teardown, while full deployment drain evidence remains. |
| Rolling deployment and rollback | FAIL | Versioned release exists, but mixed-version state compatibility and rollback procedure are not tested. |
| Backup/restore and RPO/RTO | PARTIAL | A real Redis RDB restore drill and operator backup/restore runbook now exist; managed-service restore, audit-volume restore, and measured production RPO/RTO remain pending. |
| Reproducible release artifacts | PASS | `v0.1.0` release publishes wheel, sdist, checksums, and GHCR image with a tag/version guard; release run `36130306271` generated the image SBOM, signed the image, and published provenance attestation. |

## Required next gates

The review cannot become `PASS` until the P0/P1 failures above have named test
or artifact evidence. The execution order is in
[`PRODUCTION_PLAN.md`](PRODUCTION_PLAN.md); the target SLO definitions are in
[`docs/slo.md`](docs/slo.md), and current dependency behavior is in
[`docs/failure-modes.md`](docs/failure-modes.md).
