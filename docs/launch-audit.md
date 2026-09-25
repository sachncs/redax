# Launch audit

Status for the `v0.1.0` launch. This is an evidence-based scope statement,
not a claim that Redax detects every sensitive value or replaces a complete
DLP program.

## P0 fixed

- `POST /v1/redact` returns transformed text; cleartext diagnostics are
  isolated in `POST /v1/detect` and are explicitly marked unsafe to forward.
- Policy precedence, entity aliases, span overlap handling, Unicode offsets,
  fallback behavior, circuit-breaker behavior, and Redis-unavailable behavior
  are documented and covered by regression tests.
- HTTP responses never carry the Python re-identification map. API-key
  ownership, idempotency, cache, rate-limit, job, audit, log, metric, and
  exception paths avoid storing raw API keys or entity values.
- Production configuration rejects missing API keys, trusted hosts, and the
  default hash salt. Authenticated rate limiting fails closed when Redis is
  unavailable unless the operator explicitly enables fail-open mode.
- Pipeline correlation digests use a deployment-keyed HMAC rather than an
  unkeyed hash of input text.

## P1 fixed

- README, API, architecture, threat-model, data-flow, deployment, integration,
  policy, model-provenance, and benchmark documents describe one HTTP-first
  contract.
- The supported model path is a pinned local GLiNER2 snapshot with a verified
  revision and digest. The regex detector is the stable structured fallback.
- The website links to its own API and security pages, explains the request
  journey, and labels browser/demo/model limitations.

## P2 fixed

- The product site has a coherent desktop-first landing flow, restrained
  spacing and controls, consistent Redax branding, direct documentation links,
  and no unsupported latency or benchmark promises.
- The public demo is visibly illustrative and regex-only; it does not imply
  parity with server-side model inference.

## P3 fixed

- CI runs Python 3.13 tests, lint, formatting, mypy, determinism, synthetic
  evaluation, and the Astro site check/build.
- Drift tests cover documented configuration, documented OpenAPI paths, and
  version alignment across package, API, site, and README.
- Docker builder/runtime builds, package builds, model verification, and
  clean-container health/readiness/redaction smoke tests have been exercised.

## P4 fixed

- The `v0.1.0` tag and GitHub release publish the wheel, sdist, checksums, and
  versioned GHCR image. The release workflow rejects a tag that disagrees with
  the project version.
- Apache-2.0 licensing, contribution guidance, security reporting, code of
  conduct, model provenance, and changelog entry are present.

## Removed

- Unsupported published benchmark numbers and fixed model latency claims.
- Claims that historical detector adapters are supported runtime paths.
- HTTP exposure of reversible re-identification maps.
- Python 3.11/3.12 support claims and unpinned production dependency claims.

## Deferred

- Browser/WASM model parity and a supported browser package remain experimental
  and regex-only because model packaging, bundle provenance, and parity are not
  yet verified.
- Durable distributed job execution, signed/tamper-evident audit records,
  SBOM/signing attestations, and a supported Python SDK remain outside the
  `0.1.0` contract.
- A release-grade accuracy/latency benchmark remains deferred until a licensed
  corpus, pinned environment, and reproducible run record are published.

## Breaking changes

- Runtime support is Python 3.13+ only.
- `/v1/detect` is the cleartext detection endpoint; `/v1/redact` is the
  transformed-text contract and no longer returns original-value maps.
- Production startup requires explicit API keys, trusted hosts, and a unique
  hash salt.
- Pipeline digest values are keyed by `REDAX_HASH_SALT`; operators must keep
  that salt stable when correlating records within a deployment.

## Security-sensitive changes

- Raw API keys are hashed before Redis ownership/rate-limit storage.
- Error logging is exception-class-only at the request boundary.
- Cache and idempotency identities include policy, detector, model, and mode;
  old envelopes are not trusted blindly.
- Audit, metrics, traces, and job responses are documented as metadata-only
  boundaries, with operator-owned retention and exporter controls.

## Remaining limitations and risks

- Detection is configured coverage, not a proof of absence. Undetected PII,
  secrets, malformed input, host compromise, proxy logs, Redis, telemetry, and
  model/runtime supply-chain risk remain deployment concerns.
- Explicit `passThrough` policies can intentionally preserve detected text;
  policy review is part of the security boundary.
- The local JSONL audit backend is not a tamper-proof ledger, and in-process
  jobs are not a durable distributed queue.

## Verification evidence

The launch commit was verified by GitHub Actions CI and Pages deployment. The
repository checks are reproducible with:

```bash
make test lint typecheck
npm --prefix site run check
npm --prefix site run build
```

The released artifacts and checksums are attached to
[GitHub release v0.1.0](https://github.com/sachncs/redax/releases/tag/v0.1.0).
