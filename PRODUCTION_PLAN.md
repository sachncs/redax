# Production-grade gap analysis and implementation plan

Status: baseline audit for the production-grade program, 2026-09-29.

This document records what the repository proves today and what still must be
implemented. A passing unit suite or a successful container build is evidence
for only the behavior that test actually covers; it is not evidence of HA,
durability, capacity, or disaster recovery.

## Evidence baseline

The current repository has a Python 3.13 FastAPI service, a pinned local
GLiNER2 model, a regex detector, Redis-backed cache/idempotency/rate-limit/job
state, local JSONL audit logging, Prometheus metrics, optional OTLP tracing,
Docker Compose, a production Dockerfile, CI, Pages deployment, and a verified
`v0.1.0` release. The current CI gate covers tests, Ruff, mypy, deterministic
regressions, a synthetic evaluation, and the Astro site build.

The repository now contains a distributed ARQ worker and atomic job admission
and completion primitives, but it still lacks a reference HA deployment,
measured SLO/load evidence, chaos/recovery evidence, an SBOM or container
vulnerability gate, a restore-tested backup procedure, and a complete
production-readiness matrix.

## Prioritized gaps

| ID | Severity | Component | Current evidence and failure scenario | Consequence | Correction | Required tests / acceptance |
|---|---|---|---|---|---|---|
| P0-01 | P0 | Jobs / deployment | `app/api/jobs.py` enqueues to the ARQ worker and `app/jobs/queue.py` retries attempts; startup stale-job reconciliation now fails abandoned queued/running records, but leases, poison-job/DLQ handling, cancellation, and real worker-failure recovery are not evidenced. | Accepted work may remain non-terminal or be retried without an operator-visible recovery boundary. | Add lease/requeue/DLQ semantics and real Redis API/worker failure tests. | Kill worker during execution; duplicate delivery; lease expiry; rolling deploy; no accepted job silently disappears. |
| P0-02 | P0 | Redis state transitions | Idempotency reservations, rate-limit windows, job admission, and job terminal completion now use atomic Lua operations; cache writes remain separate and schemas are not uniformly versioned. | Remaining cache/schema races can produce stale or incompatible state during crashes or rollouts. | Finish versioned cache operations and persisted-schema compatibility tests. | Concurrent multi-client tests against real Redis; same key/different body returns 409; crash between transitions leaves recoverable state. |
| P0-03 | P0 | Redaction failure semantics | Model fallback and Redis degradation exist, but audit failure, policy-file failure, and some transport/dependency failures are not governed by one explicit mandatory/optional matrix. | A future exception path could accidentally return successful-looking output without the required privacy or audit boundary. | Define dependency failure policy; make sensitive-path fallback explicit, observable, and fail closed where required. | Fault-injection tests for model, policy, Redis, audit, timeout, cancellation, and disk failure; no raw pass-through after internal failure. |
| P0-04 | P0 | PII leakage | A canary now covers successful response, metrics, audit, and detector-failure logs; stream/job/Redis/traces/failure matrix coverage is not yet release-gated. | A new operational path can expose sensitive input in logs, traces, Redis, job metadata, or exceptions. | Extend the canary suite across all operational sinks and failure paths. | Release-blocking canary tests cover auth, validation, detector/model failure, Redis outage, timeout, cancellation, job failure, audit failure, and streaming disconnect. |
| P0-05 | P0 | Supply chain / release | CI now generates a filesystem SBOM and passes the HIGH/CRITICAL Trivy gate; release image scanning/signing/attestation remains unexecuted. Docker now pins the Python base manifest digest. | Consumers cannot yet verify a complete immutable shipped dependency/model supply chain. | Execute the release gates and define time-bounded exceptions. | Release fails on configured severity threshold; assets map to commit, lockfile, model digest, and schema version. |
| P1-01 | P1 | Availability / SLO | SLO definitions and a machine-readable local regex baseline now exist; model/cache/batch/stream/job ramp, soak, capacity, and error-budget evidence remain absent. | “Production-grade” cannot be evaluated or operated against complete measurable targets. | Run repeatable detector/API/worker ramp and soak benchmarks and publish capacity evidence. | Machine-readable results with environment, commit, model digest, concurrency, CPU, memory, throughput, and percentiles; no invented targets. |
| P1-02 | P1 | Horizontal scaling | Model, circuit breaker, audit file, and job admission are process-local; local audit is not centralized and jobs are not distributed. | Multiple API replicas do not yet provide a documented correctness-preserving topology. | Separate API/worker state, centralize required durable state, document replica/worker behavior, and provide deployment assets. | Multi-process Redis integration and failure tests; standard and scaled deployment smoke tests. |
| P1-03 | P1 | Authentication / authorization | Constant-time API-key auth now supports optional JSON scopes and endpoint enforcement for redact, detect, jobs, policies, and metrics; rotation/revocation remains deployment/env based and has no control-plane evidence. | A valid key can still be broadly privileged when scopes are omitted, and revocation requires configuration rollout. | Define principal identifiers and an external rotation/revocation workflow without logging secrets. | Scope matrix tests for redact/detect/policies/jobs/metrics/admin; rotation and revoked-key tests. |
| P1-04 | P1 | Admission / overload | Text, chunk, and inference limits exist; request concurrency, response size, in-flight HTTP, Redis pool, oldest queue age, and stream duration are not all bounded/measured. | 10x traffic or slow clients can exhaust memory, CPU, connections, or event-loop capacity. | Add explicit admission controller, bounded semaphores/queues, response limits, cancellation, and saturation metrics. | Ramp/spike/recovery tests; predictable 429/503; bounded memory/task/connection counts. |
| P1-05 | P1 | Health / shutdown | `/healthz` and `/readyz` exist, but readiness/drain state and graceful SIGTERM admission shutdown are not a demonstrated protocol. | Deployments can receive traffic while unsafe or terminate active work without a bounded handoff. | Add drain state, bounded in-flight shutdown, worker stop/release semantics, and startup/shutdown probes. | Signal integration tests for active HTTP, stream, and job; readiness changes before termination. |
| P1-06 | P1 | Audit / observability | Local JSONL is structured and metadata-only, but no durable centralized backend, mandatory-audit mode, RED/USE dashboard/alerts, Redis metrics, or job age/retry metrics exists. | Compliance deployments cannot select durable/tamper-evident audit; operators lack actionable saturation signals. | Version audit schema, add backend contract and mandatory mode, expand metrics, and publish alert thresholds/runbooks. | Backend contract tests, audit failure mode tests, metric-cardinality tests, dashboard/query checks. |
| P1-07 | P1 | Persistence / recovery | Redis values are not fully versioned across all state; no RPO/RTO, backup, restore, or migration procedure is tested. | Rolling upgrades and recovery can corrupt or lose job/cache/idempotency state without a known outcome. | Version schemas, document disposable vs durable data, define backup/restore and compatibility windows. | Restore test from backup; mixed-version compatibility test; measured RPO/RTO evidence. |
| P2-01 | P2 | Deployment | Compose is development-oriented; no Kubernetes/Helm reference topology, resource requests, PDB, network policy, TLS/proxy, autoscaling, or rollback assets exist. | Operators must invent the HA deployment boundary and may omit required controls. | Add a minimal reference production deployment and explicit sizing/rollback guidance. | Manifest validation and disposable-cluster smoke test where available. |
| P2-02 | P2 | Performance | Benchmark harness exists but no current release-grade result or regression baseline is published. | Capacity and autoscaling recommendations are unknown. | Produce licensed, reproducible machine-readable benchmark artifacts for regex/model/cache/batch/stream/jobs. | Re-run from exact commit and compare against stored baseline; publish methodology and limitations. |
| P2-03 | P2 | Testing depth | Unit/property/regression tests exist; no systematic concurrency, fuzz, chaos, soak, or real-Redis worker suite is present. | Race, recovery, and pathological-input failures can escape CI. | Add staged reliability/security/performance gates with bounded runtime and artifacts. | Each gate has a named command and evidence artifact; PR gate remains fast. |
| P3-01 | P3 | Maintainability | Core boundaries are reasonably explicit, but the worker, authorization, audit backend, and deployment contracts are not yet implemented. | Future extensions risk coupling transport and infrastructure. | Introduce only the concrete interfaces needed by the distributed worker/audit/auth changes. | Architecture review and contract tests; no speculative plugin framework. |

## Implementation sequence

1. **M1 — Baseline and contracts:** add `PRODUCTION_READINESS.md`, SLOs,
   failure matrix, unresolved-risk register, and a machine-readable audit
   format. Lock down API/config/schema versions before changing persistence.
2. **M2 — Distributed state:** implement Redis atomic scripts/envelopes for
   idempotency, rate limiting, job admission, terminal completion, and cache;
   add real-Redis race tests.
3. **M3 — Durable jobs:** implement the API enqueue/worker process, leases,
   retries, DLQ, recovery, metrics, and deployment entrypoints; remove the
   production path's use of FastAPI `BackgroundTasks`.
4. **M4 — Security and admission:** scoped authentication, explicit failure
   matrix, canary leak suite, bounded request/stream concurrency, drain-aware
   readiness, and graceful shutdown.
5. **M5 — Observability and operations:** RED/USE metrics, audit backend mode,
   alerts, dashboards, and runbooks for every required incident.
6. **M6 — Evidence:** load/soak/chaos/concurrency tests, measured SLO/capacity
   artifacts, backup/restore, and mixed-version deployment tests.
7. **M7 — Supply chain and HA release:** hardened release container, SBOM,
   vulnerability scan, provenance, reference deployment, rollback procedure,
   and final PASS/FAIL/NOT-APPLICABLE readiness review.

## Immediate next slice

The first implementation slice is M1: create the required production-readiness
artifacts and failure matrix from this audit. No production claim will be
marked PASS without a named test, command, configuration check, or artifact.
