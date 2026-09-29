# Production readiness review

Status: **NOT production-grade yet**. This is a checkable review of the
current repository, not a marketing claim. A requirement is `PASS` only when
the cited evidence covers the stated scope; `FAIL` means implementation or
evidence is still missing; `N/A` means the requirement is outside the current
supported product surface.

Review baseline: `998119f` and the current `master` tree. Update this matrix
as each production milestone lands.

## Reliability and distributed correctness

| Requirement | Status | Evidence / gap |
|---|---|---|
| API correctness across replicas | FAIL | Redis is shared for some state, but jobs and circuit breakers still have process-local behavior; no multi-replica integration gate. |
| Durable jobs survive worker failure | PARTIAL | ARQ worker, jittered retries, atomic admission/completion, startup stale-job reconciliation, bounded payload-free DLQ records, and real-Redis recovery after a killed worker process are tested; Redis failover and production-scale evidence remain pending. |
| Redis failure behavior is explicit | PASS | `docs/failure-modes.md`, `app/ratelimit.py`, and configuration tests define current cache/job/rate-limit degradation. Durable-job behavior remains pending. |
| Graceful shutdown is verified | PARTIAL | Readiness drops before teardown and cleanup is bounded by `REDAX_SHUTDOWN_TIMEOUT_SECONDS`; active HTTP/stream/job SIGTERM integration evidence is still pending. |
| Overload is bounded | FAIL | Text/chunk/inference/job admission limits exist, but HTTP, stream, Redis-pool, and worker queue bounds are not demonstrated under load. |
| Dependency recovery works | FAIL | Redis worker lease recovery is tested; Redis restart/failover and audit-storage recovery evidence are still missing. |

## Security and privacy

| Requirement | Status | Evidence / gap |
|---|---|---|
| Production configuration fails securely | PASS | `Settings.verify()`, `tests/unit/test_config.py`, and production API-key/trusted-host/hash-salt checks. |
| Scoped authorization | PARTIAL | Optional JSON scopes enforce redact, detect, jobs, policies, and metrics endpoints; external rotation/revocation and a control-plane audit are pending. |
| Secrets stay out of telemetry | PARTIAL | Error, audit, cache, idempotency, metrics, and detector-failure log canaries exist; full traces/Redis/jobs/failure coverage is pending. |
| Automated PII leak suite | PARTIAL | `tests/integration/test_api_redact.py` covers response, audit, metrics, and detector-failure logs; the complete release-blocking failure matrix is pending. |
| No silent raw pass-through after internal failure | PARTIAL | Model fallback, audit-required rejection, and error handlers are tested; policy, cancellation, stream disconnect, and full failure-matrix coverage remain. |
| Threat model matches implementation | PASS | `docs/threat-model.md`, `docs/data-flow.md`, and `docs/failure-modes.md`; update when the worker/audit architecture lands. |
| High/critical vulnerability gate | PARTIAL | GitHub security run `36551462860` passed SBOM generation and the filesystem Trivy gate; release image scan/signature/attestation evidence is pending. |

## Scalability and performance

| Requirement | Status | Evidence / gap |
|---|---|---|
| Horizontally scalable API | PARTIAL | Reference Kubernetes API replicas, probes, and rolling budgets now exist; HA Redis, centralized audit, and multi-replica failure evidence remain pending. |
| Independently scalable workers | PARTIAL | `redax-worker` and Redis-backed ARQ enqueueing exist; capacity, lease recovery, and deployment evidence are pending. |
| Measured performance characteristics | PARTIAL | `docs/benchmarks/regex-local-baseline.json` records a reproducible local detector baseline; API/worker/model capacity and soak evidence remain pending. |
| Known saturation limits | FAIL | No ramp/spike/soak artifact records p99, queueing, CPU, memory, Redis, or model saturation. |
| Autoscaling guidance | FAIL | No production deployment or measured scaling model exists. |

## Maintainability and interfaces

| Requirement | Status | Evidence / gap |
|---|---|---|
| Clear domain boundaries | PASS | `docs/architecture.md`, route modules, detector/redactor/audit separation, and typed settings. |
| Versioned persisted schemas | PARTIAL | Idempotency, response-cache, and durable-job envelopes are versioned; audit schema and mixed-version compatibility are still pending. |
| Configuration validation and documentation | PASS | `Settings` plus documented configuration drift tests. |
| API/OpenAPI contract | PASS | API contract tests and documented paths; authorization scopes are not yet part of the contract. |
| Meaningful coverage threshold | PASS | `pyproject.toml` enforces 80% branch-aware coverage through `make test-cov`; the Python 3.13 suite currently measures 83.43%. |

## Observability and operations

| Requirement | Status | Evidence / gap |
|---|---|---|
| Actionable RED/USE metrics | PARTIAL | RED metrics, Prometheus alert rules, and a Grafana dashboard are checked in; queue age, retries, Redis pool, response-size, and worker-runtime metrics still need implementation/evidence. |
| Privacy-safe structured logs/traces | PARTIAL | Access/error/audit paths avoid values and metrics regression exists; trace exporter and all failure paths need canary tests. |
| Alerts and dashboards | PARTIAL | Checked-in Prometheus alert rules and a Grafana dashboard cover HTTP, audit, dependency, API replica, and worker availability; queue age, retries, and Redis-pool panels remain pending. |
| Operational runbooks | PARTIAL | Current runbooks in `docs/runbooks/` describe safe response and evidence; they remain bounded by the current in-process job limitations. |

## Deployment, recovery, and release

| Requirement | Status | Evidence / gap |
|---|---|---|
| Hardened container | PARTIAL | Non-root, pinned dependencies, model verification, slim runtime, and a digest-pinned Python base exist; read-only filesystem, capabilities, image SBOM, and release scan evidence remain pending. |
| Reference HA deployment | PARTIAL | `deploy/kubernetes/` defines API/worker replicas, PDBs, probes, resource bounds, and autoscaling; external Redis HA and deployment smoke/failure evidence remain pending. |
| Health/readiness/startup probes | PARTIAL | `/healthz`, `/readyz`, and Docker probes exist; readiness drops before teardown, but dependency-aware readiness and full drain semantics need evidence. |
| Rolling deployment and rollback | FAIL | Versioned release exists, but mixed-version state compatibility and rollback procedure are not tested. |
| Backup/restore and RPO/RTO | FAIL | No restore-tested Redis/audit backup procedure or measured RPO/RTO. |
| Reproducible release artifacts | PASS | `v0.1.0` release publishes wheel, sdist, checksums, and GHCR image with a tag/version guard. SBOM/signatures remain pending. |

## Required next gates

The review cannot become `PASS` until the P0/P1 failures above have named test
or artifact evidence. The execution order is in
[`PRODUCTION_PLAN.md`](PRODUCTION_PLAN.md); the target SLO definitions are in
[`docs/slo.md`](docs/slo.md), and current dependency behavior is in
[`docs/failure-modes.md`](docs/failure-modes.md).
