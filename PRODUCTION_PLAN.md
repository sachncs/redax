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

The repository now contains a distributed ARQ worker, atomic job admission and
completion primitives, a digest-pinned reference Kubernetes topology, a
restore-tested Redis backup procedure, and verified release
SBOM/scanning/signing/provenance workflows. It still lacks measured SLO/load
evidence, complete chaos/recovery evidence, managed audit durability, and a
complete production-readiness matrix.

## Prioritized gaps

| ID | Severity | Component | Current evidence and failure scenario | Consequence | Correction | Required tests / acceptance |
|---|---|---|---|---|---|---|
| P0-01 | P0 | Jobs / deployment | `app/api/jobs.py` enqueues to the ARQ worker and `app/jobs/queue.py` retries attempts; stale-job reconciliation, bounded payload-free DLQ handling, lease expiry, duplicate terminal delivery, and real worker-process recovery are tested. Redis failover, cancellation, rolling-deploy, and poison-job evidence remain. | Accepted work may remain non-terminal or be retried without an operator-visible recovery boundary during infrastructure failover. | Add managed Redis failover, cancellation, and rolling-deploy drills. | Kill worker during execution; duplicate delivery; lease expiry; rolling deploy; no accepted job silently disappears. |
| P0-02 | P0 | Redis state transitions | Idempotency reservations, rate-limit windows, job admission, terminal completion, and response-cache envelopes use atomic/versioned operations; durable-job transitions refuse incompatible schemas, and cache/idempotency mixed-version tests now prove safe miss/reacquisition. API-level response-cache read/write outage tests prove recomputation without changing redaction semantics; managed/real-Redis failover drills remain. | Remaining schema races can produce stale or incompatible state during crashes or rollouts. | Keep mixed-version compatibility, cache failure, and failover tests in the release gate. | Concurrent multi-client tests against real Redis; same key/different body returns 409; crash between transitions leaves recoverable state. |
| P0-03 | P0 | Redaction failure semantics | Model fallback, timeout responses, and stream cancellation handling exist, but audit failure, policy-file failure, and some transport/dependency failures are not governed by one explicit mandatory/optional matrix. | A future exception path could accidentally return successful-looking output without the required privacy or audit boundary. | Define dependency failure policy; make sensitive-path fallback explicit, observable, and fail closed where required. | Fault-injection tests for model, policy, Redis, audit, timeout, cancellation, and disk failure; no raw pass-through after internal failure. |
| P0-04 | P0 | PII leakage | Canaries cover synchronous response, metrics, audit, detector-failure logs, metadata-only request/stream traces, streaming response/audit, durable-job success/failure/cancellation output/store/audit, stream cancellation logs, Redis outage, timeout, auth, validation, audit failure, and real-Redis persisted values; exporter coverage remains incomplete. | A new operational path can expose sensitive input in logs, traces, Redis, job metadata, or exceptions. | Extend the canary suite across all operational sinks and failure paths. | Release-blocking canary tests cover auth, validation, detector/model failure, Redis outage, timeout, cancellation, job failure, audit failure, and streaming disconnect. |
| P0-05 | P0 | Supply chain / release | CI generates a filesystem SBOM, passes the HIGH/CRITICAL Trivy gate, and publishes signed/provenanced images; the release workflow now generates `RELEASE-METADATA.json` after push, binds the immutable image digest to the commit, lockfile/model-manifest digests, model revisions, and persisted schema versions, and asserts that binding before checksumming artifacts. Recurring release evidence remains. | Consumers may not be able to verify every future shipped dependency/model supply chain. | Keep release gates mandatory and define time-bounded exceptions. | Release fails on configured severity threshold; assets map to commit, image digest, lockfile, model digest, and schema version. |
| P1-01 | P1 | Availability / SLO | SLO definitions, machine-readable local regex baselines, and a 300-request concurrency matrix at 1/10/20/40 now exist; model/cache/batch/stream/job ramp, soak, capacity, and error-budget evidence remain absent. | “Production-grade” cannot be evaluated or operated against complete measurable targets. | Run repeatable detector/API/worker ramp and soak benchmarks and publish capacity evidence. | Machine-readable results with environment, commit, model digest, concurrency, CPU, memory, throughput, and percentiles; no invented targets. |
| P1-02 | P1 | Horizontal scaling | Model and circuit breaker remain process-local and jobs are distributed through Redis; the default audit file is local, while an opt-in bounded Redis audit sink is shared. A two-process API gate now proves idempotency replay and request-fingerprint conflict through shared Redis. | HA Redis, failover, and scaled deployment behavior remain unproven. | Separate API/worker state, centralize required durable state, document replica/worker behavior, and provide deployment assets. | Keep the multi-process Redis gate, then add failure and standard/scaled deployment smoke tests. |
| P1-03 | P1 | Authentication / authorization | Constant-time API-key auth supports optional JSON scopes, endpoint enforcement, overlapping active keys, and a deployment-native revocation denylist for redact, detect, jobs, policies, and metrics; external rotation/control-plane evidence remains. | A valid key can still be broadly privileged when scopes are omitted, and revocation requires configuration rollout. | Define principal identifiers and an external rotation/revocation workflow without logging secrets. | Scope matrix tests for redact/detect/policies/jobs/metrics/admin; rotation and revoked-key tests. |
| P1-04 | P1 | Admission / overload | Declared and chunked body, bounded body-receive timeout, text, batch, chunk, stream-duration, request-concurrency, response-size, in-flight HTTP, inference, job-admission, and oldest-job-age controls exist; Redis-pool, worker-queue, and sustained-recovery evidence remain. | 10x traffic or slow clients can exhaust memory, CPU, connections, or event-loop capacity. | Add connection/pool controls and repeatable ramp/spike/recovery evidence. | Ramp/spike/recovery tests; predictable 429/503; bounded memory/task/connection counts. |
| P1-05 | P1 | Health / shutdown | `/healthz` and `/readyz` exist; readiness drops before teardown, a process-level Uvicorn SIGTERM test drains a held HTTP request within a deadline, and a real-Redis ARQ test drains an active job before worker exit. Active stream SIGTERM integration evidence remains. | Deployments can terminate active stream work without a demonstrated bounded handoff. | Add a signal-driven stream shutdown test and retain worker stop/release semantics. | Signal integration tests for active HTTP, stream, and job; readiness changes before termination. |
| P1-06 | P1 | Audit / observability | Local JSONL and the opt-in bounded Redis audit backend are structured, metadata-only, mandatory-audit capable, versioned, and principal-attributed; RED/USE dashboards, response-size, queue depth, oldest queue age, retry/failure metrics, and alerts exist. Managed Redis durability and worker-runtime metrics remain. | Compliance deployments need a centrally durable, tamper-evident sink and complete dependency signals. | Add managed centralized audit retention/integrity controls and remaining dependency/runtime metrics. | Backend contract tests, audit failure mode tests, metric-cardinality tests, dashboard/query checks. |
| P1-07 | P1 | Persistence / recovery | Idempotency, response-cache, durable-job, and audit records are versioned; cache/idempotency mixed-version tests and a real Redis RDB restore drill/operator runbook exist, while managed-service restore, audit-volume restore, mixed-version migration, and measured RPO/RTO remain untested. | Rolling upgrades and recovery can corrupt or lose job/cache/idempotency state without a known outcome. | Version schemas, document disposable vs durable data, define backup/restore and compatibility windows. | Restore test from backup; keep mixed-version compatibility tests; measure RPO/RTO. |
| P2-01 | P2 | Deployment | Compose is development-oriented; a Kubernetes reference topology now provides resource requests, PDB, probes, restricted security contexts, autoscaling, immutable image pinning, rollback guidance, fail-closed NetworkPolicies, and an ingress-nginx TLS/body/timeout contract. External Redis HA and disposable-cluster smoke evidence remain. | Operators may still omit controls at the ingress and managed-Redis boundary. | Add disposable-cluster smoke evidence and validate the managed-Redis boundary. | Manifest validation and disposable-cluster smoke test where available. |
| P2-02 | P2 | Performance | Benchmark harness exists but no current release-grade result or regression baseline is published. | Capacity and autoscaling recommendations are unknown. | Produce licensed, reproducible machine-readable benchmark artifacts for regex/model/cache/batch/stream/jobs. | Re-run from exact commit and compare against stored baseline; publish methodology and limitations. |
| P2-03 | P2 | Testing depth | Unit/property/regression tests exist; no systematic concurrency, fuzz, chaos, soak, or real-Redis worker suite is present. | Race, recovery, and pathological-input failures can escape CI. | Add staged reliability/security/performance gates with bounded runtime and artifacts. | Each gate has a named command and evidence artifact; PR gate remains fast. |
| P3-01 | P3 | Maintainability | Core boundaries are reasonably explicit, but the worker, authorization, audit backend, and deployment contracts are not yet implemented. | Future extensions risk coupling transport and infrastructure. | Introduce only the concrete interfaces needed by the distributed worker/audit/auth changes. | Architecture review and contract tests; no speculative plugin framework. |

## Implementation sequence

1. **M1 — Baseline and contracts:** keep `PRODUCTION_READINESS.md`, SLOs,
   failure matrix, unresolved-risk register, and machine-readable schemas
   synchronized with implementation evidence.
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
7. **M7 — Supply chain and HA release:** maintain hardened release container,
   SBOM, vulnerability scan, provenance, reference deployment, rollback
   procedure, and final PASS/FAIL/NOT-APPLICABLE readiness review.

## Immediate next slice

The first implementation slice is M1: create the required production-readiness
artifacts and failure matrix from this audit. No production claim will be
marked PASS without a named test, command, configuration check, or artifact.
