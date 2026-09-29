# Failure-mode matrix

This matrix states the current externally visible behavior and the production
behavior required by the plan. “Current” is not automatically “acceptable for
HA”; gaps are marked explicitly.

| Dependency or event | Current behavior | Safety posture | Production acceptance condition |
|---|---|---|---|
| API keys missing in `prod` | Startup fails validation. | Fail closed. | Keep; add scoped principal/rotation evidence. |
| Trusted hosts missing in `prod` | Startup fails validation. | Fail closed. | Keep; document proxy/TLS boundary. |
| Redis unavailable at startup | App logs and continues with no job store; cache/idempotency/jobs are disabled; rate limiting fails closed unless explicit fail-open. | Mixed, explicit. | Readiness must reflect required deployment mode; test recovery without restart. |
| Redis unavailable during rate limit | Returns typed 503 by default; explicit `REDAX_RATE_LIMIT_FAIL_OPEN=true` allows traffic. | Configurable, documented. | Require explicit operator acknowledgement and alert on fail-open. |
| Redis unavailable during cache | Request recomputes; cache is skipped. | Fail open for optimization only. | Never let cache failure change redaction semantics. |
| Redis unavailable during jobs | Submission returns 503; current background work may lose its result. | Unsafe for durable jobs. | Durable enqueue/lease/retry worker required before jobs are production-supported. |
| Model cannot load in `prod` | Startup fails; dev may log and downgrade according to detector configuration. | Fail closed in prod. | Add readiness/startup and corrupted-model tests. |
| Model inference failure | Pipeline can use explicit regex fallback and records fallback; policy path returns an error according to route handling. | Route-dependent. | One documented policy matrix; no raw pass-through. |
| Model timeout | Synchronous request returns 504; job marks failure; stream emits timeout event. | Reject/fail closed. | Add cancellation and recovery tests. |
| Circuit breaker opens | Pipeline uses its explicit fallback marker; process-local breaker state. | Degraded, observable. | Define replica semantics and recovery metrics. |
| Policy file missing/invalid | Validation/loading error prevents normal policy execution. | Reject. | Startup validation for required default policy and tests for rolling compatibility. |
| Audit backend unavailable | Current file backend can drop/write-fail according to implementation; request path is not globally mandatory-audit. | Not one uniform policy. | Add `audit_required` mode and centralized durable backend contract. |
| Disk full / permission failure | File audit write failure is counted/logged; no universal successful-request rejection. | Potentially fail open. | Mandatory mode must reject successful processing and alert. |
| Telemetry exporter unavailable | OTLP is optional; request processing should continue. | Fail open for telemetry. | Bound exporter buffers and verify no raw attributes. |
| Request too large | 413 for configured text limit; batch/stream have their own bounds. | Reject. | Add body, batch amplification, slow-client, and response-size limits. |
| Invalid or adversarial Unicode | Pydantic and code-point chunking validate input; property tests cover parts of the transform path. | Bounded in tested paths. | Add fuzz suite and CPU/memory budgets. |
| Client disconnects from stream | Generator cleanup is present; complete cancellation/release evidence is pending. | Incomplete evidence. | Add disconnect and shutdown integration tests. |
| API process dies | In-flight synchronous work is lost; safe because no response is emitted, but client retry semantics apply. | Bounded. | Multi-replica retry/idempotency semantics must be atomic. |
| Worker dies mid-job | Current in-process job is lost or may remain non-terminal. | FAIL for production jobs. | Lease expiry/requeue/dead-letter test required. |
| Duplicate job delivery | No distributed worker delivery protocol yet. | Undefined. | Idempotent completion keyed by job ID and payload fingerprint. |
| Rolling deployment | HTTP state mostly reconstructs; job/background and persisted schema compatibility are not proven. | Incomplete. | Mixed-version Redis/schema and rollback tests. |

## Operator rule

When the chosen deployment mode cannot preserve the required privacy or
durability boundary, mark the instance unready or reject the request. Do not
silently downgrade a security-sensitive operation to pass-through.
