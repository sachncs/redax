# Production readiness review

Status: **NOT production-grade yet**. This is a checkable review of the
current repository, not a marketing claim. A requirement is `PASS` only when
the cited evidence covers the stated scope; `FAIL` means implementation or
evidence is still missing; `N/A` means the requirement is outside the current
supported product surface.

Review baseline: `85b2112` and the current `master` tree. Update this matrix
as each production milestone lands.

## Reliability and distributed correctness

| Requirement | Status | Evidence / gap |
|---|---|---|
| API correctness across replicas | FAIL | Redis is shared for some state, but jobs and circuit breakers still have process-local behavior; no multi-replica integration gate. |
| Durable jobs survive worker failure | FAIL | `/v1/jobs` uses FastAPI `BackgroundTasks`; no `app/jobs/queue.py` worker exists. |
| Redis failure behavior is explicit | PASS | `docs/failure-modes.md`, `app/ratelimit.py`, and configuration tests define current cache/job/rate-limit degradation. Durable-job behavior remains pending. |
| Graceful shutdown is verified | PARTIAL | Readiness now drops before queue/audit/Redis teardown, but there is no SIGTERM integration test for active HTTP/stream/job work. |
| Overload is bounded | FAIL | Text/chunk/inference/job admission limits exist, but HTTP, stream, Redis-pool, and worker queue bounds are not demonstrated under load. |
| Dependency recovery works | FAIL | Unit fault paths exist; no Redis restart, worker lease recovery, or audit-storage recovery test is present. |

## Security and privacy

| Requirement | Status | Evidence / gap |
|---|---|---|
| Production configuration fails securely | PASS | `Settings.verify()`, `tests/unit/test_config.py`, and production API-key/trusted-host/hash-salt checks. |
| Secrets stay out of telemetry | PARTIAL | Error, audit, cache, idempotency, metrics, and detector-failure log canaries exist; full traces/Redis/jobs/failure coverage is pending. |
| Automated PII leak suite | PARTIAL | `tests/integration/test_api_redact.py` covers response, audit, metrics, and detector-failure logs; the complete release-blocking failure matrix is pending. |
| No silent raw pass-through after internal failure | PARTIAL | Model fallback and error handlers are tested; audit, policy, cancellation, stream disconnect, and job recovery semantics need the failure matrix and tests. |
| Threat model matches implementation | PASS | `docs/threat-model.md`, `docs/data-flow.md`, and `docs/failure-modes.md`; update when the worker/audit architecture lands. |
| High/critical vulnerability gate | FAIL | No dependency or container vulnerability scan is required by CI. |

## Scalability and performance

| Requirement | Status | Evidence / gap |
|---|---|---|
| Horizontally scalable API | PARTIAL | Redaction state is composed in lifespan, but local audit, breaker, and job execution are not a complete scaled topology. |
| Independently scalable workers | FAIL | Worker process and durable queue are not implemented. |
| Measured performance characteristics | FAIL | Benchmark harness exists, but no current machine-readable capacity result is published. |
| Known saturation limits | FAIL | No ramp/spike/soak artifact records p99, queueing, CPU, memory, Redis, or model saturation. |
| Autoscaling guidance | FAIL | No production deployment or measured scaling model exists. |

## Maintainability and interfaces

| Requirement | Status | Evidence / gap |
|---|---|---|
| Clear domain boundaries | PASS | `docs/architecture.md`, route modules, detector/redactor/audit separation, and typed settings. |
| Versioned persisted schemas | FAIL | Idempotency envelopes are versioned, but all Redis job/cache/audit schemas and mixed-version compatibility are not. |
| Configuration validation and documentation | PASS | `Settings` plus documented configuration drift tests. |
| API/OpenAPI contract | PASS | API contract tests and documented paths; authorization scopes are not yet part of the contract. |

## Observability and operations

| Requirement | Status | Evidence / gap |
|---|---|---|
| Actionable RED/USE metrics | FAIL | Basic request/redaction/job counters exist; in-flight, response size, Redis pool/errors, queue age, retries, worker, runtime, and saturation metrics are missing. |
| Privacy-safe structured logs/traces | PARTIAL | Access/error/audit paths avoid values and metrics regression exists; trace exporter and all failure paths need canary tests. |
| Alerts and dashboards | FAIL | No checked-in alert rules or dashboard queries. |
| Operational runbooks | PARTIAL | Current runbooks in `docs/runbooks/` describe safe response and evidence; they remain bounded by the current in-process job limitations. |

## Deployment, recovery, and release

| Requirement | Status | Evidence / gap |
|---|---|---|
| Hardened container | PARTIAL | Non-root, pinned dependencies, model verification, and slim runtime exist; base digest, read-only filesystem, capabilities, SBOM, and scan gate are pending. |
| Reference HA deployment | FAIL | Compose is development/local; Kubernetes/Helm or equivalent reference assets are absent. |
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
