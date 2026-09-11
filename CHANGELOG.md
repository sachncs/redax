# Changelog

All notable changes to this project are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/) and this project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **`LICENSE` file** at the repo root, Apache 2.0 boilerplate, copyright line `Copyright 2026 sachin <sachncs@gmail.com>`. The license is the same one declared in `pyproject.toml`; the file makes the license text shippable on the GHCR image and PyPI wheel.

### Changed

- **`README.md` rewritten** with a centered header + project tagline
  + shields.io badges, "What is this?" one-sentence Q+A, "Who is
  this for?" audience section, feature bullet list, "Before you
  start" prerequisites, three installation paths (Docker Compose,
  GHCR prebuilt, from source), curl + Python quickstart, env-var
  configuration table, "Where to go next" doc links, and a `make
  verify` cheat-sheet. All doc links point at files that actually
  exist in the repo (`docs/api.md`, `docs/integration.md`,
  `docs/policies.md`, `docs/architecture.md`, `docs/bench.md`,
  `docs/benchmark-results.md`, `docs/deployment.md`,
  `docs/models-survey.md`, `CHANGELOG.md`, `AGENTS.md`).



- **Module-level state singleton removed.** `app/state.py` no longer
  exports a process-wide `state` instance. The `State` dataclass is
  populated in `app/main.py` lifespan and attached to
  `app.state.state`; routes read it via `Depends(get_state)` (or pass
  it through explicitly). Per AGENTS.md: no module-level globals for
  stateful resources. Tests rebind `app.state.state` on a fixture
  `FastAPI()` instead of patching the module attribute.
- **`rate_limit` takes `state` explicitly.** No more module-level
  lookup. The dependency injection flows from the route handler down.
- **Background-task workers receive `state` as a parameter.** The
  `run_job` function no longer reads from a module global; the
  per-submit `State` is captured and forwarded so the worker
  operates on the same typed container the route used.
- **`Dockerfile` now installs from `requirements.lock`** (pinned +
  hashed) instead of `>=` ranges, so the production image is
  bit-for-bit reproducible against the same lockfile CI uses.
- **`/v1/redact/batch` is now bounded by `inference_concurrency`.**
  A 1000-item batch no longer fans out 1000 concurrent detectors; the
  new semaphore matches the per-detector cap so a burst cannot
  exhaust CPU or the event loop.
- **All lazy `from x import y` statements inside route handlers have
  been hoisted to module top.** Per AGENTS.md, no function-level
  imports.

### Added

- **`/v1/stats` introspection endpoint.** API-key-gated; reports
  detector names, audit backend, redis availability, and the
  pipeline's per-stage `stats()` (including the model circuit
  breaker state).
- **`redax_audit_dropped_total{backend}` Prometheus counter.**
  `FileAudit` now exports the `dropped` count to the metrics
  registry so an operator can alert on audit data loss instead of
  scraping the in-process attribute.
- **`app/integrity.py` shared module.** The `snapshot_digest` helper
  (deterministic SHA-256 over a model snapshot) is now a public
  module, imported by `scripts/download_models.py` and the
  determinism tests. No code duplication.
- **`make verify` reproducibility gate.** Runs `make test lint
  typecheck` plus a new `verify-determinism` target. CI should call
  this single target to gate every merge.
- **`tests/unit/test_determinism.py`** with 16 regression tests that
  pin deterministic behaviour: regex, redactor, hash, dedupe, fuse,
  multi-pass, cache key, span summary, minute bucket, snapshot
  digest, end-to-end pipeline, and rate-limit minute bucket stability.
- **`tests/unit/test_jobs_store.py`** now covers `set_record` with
  both `None` and falsy-but-non-`None` results; `get` now converts
  the empty Redis string back to `None` for both `result` and
  `error` fields.
- **`tests/unit/test_audit.py`** now asserts the new dropped-events
  metric is incremented when the queue saturates.

### Fixed

- **`JobStore.set_record` distinguished `None` from empty result.**
  Previously `{"x": 0}` (a falsy dict) was stored as the empty
  string; now only `None` becomes `""` and any other value is
  JSON-encoded normally.
- **`JobStore.get` returns `None` for empty result/error fields**
  rather than the empty string from Redis, so callers that compare
  with `is None` see the expected value.
- **`FileAudit` shutdown is now tolerant of partial teardown.**
  `teardown_state` catches and logs per-resource exceptions so the
  lifespan finaliser always completes and the process can exit
  cleanly even if a single resource is wedged.

### Removed

- **Dead `Pipeline.stages` field and `PipelineStage` dataclass.**
  The pipeline ran the stages inline in `__call__`; the indirection
  through `self.stages` was never executed. The dead code is gone.

### Removed (post-0.1.0 — M11 #142, #143, #144)

- `Settings.relex_cache_size` (declared but never read).
- `app.errors.bad_request`, `app.errors.unauthorized`,
  `app.errors.rate_limited` legacy shims. Use `problem_response()`
  with explicit `type=...` URLs.
- `OPENMED_SHA256_MANIFEST_KEY` constant (`scripts/download_models.py`
  now hashes the snapshot directory itself, not a stored manifest).
- `JobStore.build_default_store` classmethod; use `JobStore(...)`
  followed by `await store.start()`.
- `Pipeline.consensus_stage` field (the consensus step now runs
  inline in `Pipeline.__call__`).
- `Gate.default` classmethod and the matching module-level
  `DEFAULT_GATE` constant.
- `fused_entity_groups(target_red=...)` parameter on
  `app.bench.fusion.fuse` (always-on keyword removed for the
  simpler `target_red` default).
- `is_connector_marker` module-level function in `app.redaction.relex`
  (now folded into `Deid`).
- `RENAME_MAP.md` (rename history was already captured in git).

### Added (carried over from prior unreleased work)

- `app/bench` package: RedactionBench R-Score metric and combinator
  structure (Algorithms 1 + 2 from arXiv:2606.18782, Brynjolfsson et al.
  2026). Includes the 11-category corpus enum, mandatory/contextual
  annotation loader, character-level coverage scoring, contextual-entity
  exception for documents with no mandatory spans, gap-aware false-positive
  penalty, and Krippendorff's α / per-unit-type disagreement / Wilson
  95% CI / Spearman ρ helpers for future user-study scoring.
- `scripts/run_bench.py` CLI for scoring any redax detector (regex,
  gliner2) against a labeled JSONL corpus.
- `tests/fixtures/redactionbench/` synthetic corpus exercising every
  metric code path (worked-example vehicle record, mandatory-only,
  contextual-only, gap-coverage FP, multi-line break, combinator case).
- Approval-test snapshot for the full bench report under
  `tests/integration/test_bench_approved.py`.
- `docs/bench.md` covering the metric, worked example, package layout,
  and extension guide.
- **Multi-stage redaction pipeline** (`app/redaction/pipeline.py` +
  `app/redaction/stages/`) that backs `/v1/redact`: regex gate →
  OpenMed-PII encoder → consensus fusion → regex fallback. Each stage
  is independently testable, the model stage is wrapped in a circuit
  breaker (`app/redaction/circuit/breaker.py`), and the audit log
  records the fused span set + model checkpoint hash without ever
  logging text.
- `app/inference/openmed.py` — the chosen OpenMed-PII-SuperClinical-
  Large-434M-v1 detector (Apache-2.0, 54 entity types, DeBERTa-v3-large
  base). Deterministic, CPU-friendly, maps its 54 labels to redax's
  seven canonical Span categories for downstream regex compatibility.
- `scripts/convert_ai4privacy.py` — re-runnable adapter that converts
  the `ai4privacy/pii-masking-200k` HuggingFace dataset into the
  RedactionBench corpus format, stratified across all 11 categories.
  Default output is `tests/fixtures/pii200k/` (5,060 documents).
- `scripts/eval_detectors.py` — multi-detector runner that scores
  regex + GLiNER2 + OpenMed on any number of RedactionBench corpora
  in one process (model loads exactly once), emits per-detector JSON
  reports under `bench-results/<date>/`.
- `docs/models-survey.md` — Phase 1 model selection write-up. Surveys
  five candidates explicitly named by the goal plus four surfaced via
  HuggingFace search, captures per-model params/license/label-set/F1,
  and documents the reconciliation between the RedactOR paper
  (LLM-as-redactor, arXiv:2505.18380) and the philterd critique
  (LLMs are non-deterministic, slow, and risky in production).
- `docs/benchmark-results.md` — corpus-level R-Score comparison table
  for the regex baseline, with placeholders for OpenMed + GLiNER2
  numbers once their checkpoints are downloaded into `models_cache/`.

### Changed

- The existing `/v1/redact` route now records audit events with
  `model_hash` populated (when the pipeline ran the model stage),
  falls back to regex-only output if the model circuit is open,
  and always emits the per-type span summary without the original
  text.

### Changed (more recent)

- `POST /v1/redact` accepts `use_pipeline: bool` (default `false`).
  When `true`, the request is routed through the new multi-stage
  pipeline (`app/redaction/pipeline.py`) — regex gate → model stage →
  consensus fusion → fallback. The response shape grows three fields:
  `used_pipeline: bool`, `used_fallback: bool`, `text_hash: str | None`.
  When the pipeline is not configured (regex-only deployment) or the
  flag is false, the legacy Redactor path is used unchanged.

- `Settings` gains `pipeline_breaker_threshold` (default 3) and
  `pipeline_breaker_cooldown_s` (default 5.0) so the model stage's
  circuit breaker can be tuned per deployment without a code change.

- `scripts/run_bench.py` and `scripts/eval_detectors.py` now call the
  detector's `warmup()` (when defined) before the per-document loop
  and redirect the model's stdout chatter so the emitted JSON stays
  parseable. Both scripts previously failed cold-start with
  `RuntimeError: GLiNER2 model is not loaded`.

- `tests/integration/test_bench_approved.py` gains an approval-style
  assertion: the strongest local model detector's R-Score must be ≥
  the regex baseline's R-Score on `tests/fixtures/redactionbench/`. If
  this assertion ever fires, the regex safety net has been overtaken
  by the model and the docs/benchmark-results.md comparison table
  needs to be regenerated.

- `tests/integration/test_api_redact.py` gains two tests for the new
  `use_pipeline=true` path: one verifies the pipeline's regex gate
  + model stage both contribute spans (EMAIL from regex, PERSON from
  the stub model); one verifies the legacy Redactor is still used when
  `use_pipeline=false`.

- `docs/architecture.md` documents the multi-stage pipeline (regex
  gate + model + consensus + circuit-broken fallback) and the
  reconciliation with the philterd critique ("never trust a single
  LLM in the redaction hot path; the regex gate is the deterministic
  safety net; the model stage provides recall lift on PERSON +
  contextual entities; the consensus stage prevents the model from
  overriding regex anchors").

- `docs/api.md` documents the new request field (`use_pipeline`) and
  the three new response fields (`used_pipeline`, `used_fallback`,
  `text_hash`).


## [0.1.1] — 2026-09-07 (audit M11 patch release)

### Fixed

- `app/ratelimit.py` no longer does a function-level `get_logger`
  import inside the `OSError` / `TimeoutError` handler; the import
  is hoisted to module top, matching the AGENTS.md convention
  ("no function-level imports"). The CHANGELOG entry for 0.1.0
  previously claimed every handler import was already hoisted;
  this release makes the claim true.
- `Settings.verify()` now rejects `REDAX_HASH_SALT=change-me`
  regardless of whether `REDAX_API_KEYS` is set, since the salt
  also seeds the `hash` strategy and response cache key.
- `/v1/redact` returns a typed 422 problem
  (`https://redax.ai/errors/pipeline-unavailable`) when a caller
  asks for `use_pipeline=true` but the lifespan failed to load a
  model, instead of silently downgrading to the legacy Redactor.
- Lifespan survives a transient GLiNER2 model load failure by
  downgrading to regex-only and logging a warning, so a single
  cache miss no longer kills the container.
- `/v1/redact/stream` is now bound by the same
  `inference_concurrency` semaphore as the sync and batch routes.
- `FileAudit.drain` no longer silently swallows write exceptions
  on disk-full / permission-denied. Each failure increments
  `redax_audit_write_failed_total{backend}` and logs a warning.
- `FileAudit.record` increments `redax_audit_uninitialised_total{backend}`
  and logs once per process when called before `start()`.
- Rate limit returns a typed `rate-limit-unavailable` 503 problem
  on Redis unreachable; `REDAX_RATE_LIMIT_FAIL_OPEN=true` lets a
  deployment opt back into fail-open behavior.
- Counter leak in `/v1/jobs`: a Redis write failure during
  `JobStore.create()` now returns 500 instead of incrementing the
  per-key quota without ever admitting the job.
- `/v1/jobs` returns a typed `job-store-unavailable` 503 problem
  when Redis is down, instead of the generic 500.
- `idempotency` and `response` cache short-circuits in `/v1/redact`
  now log a warning when Redis is unavailable, so operators can
  tell the cache is off.

### Added

- `app/py.typed` PEP 561 marker so downstream `pip install redax`
  consumers pick up the in-source annotations.
- `app/jobs/__init__.py`, `app/redaction/__init__.py`,
  `app/redaction/stages/__init__.py` re-export their public API.
- `app.redaction.compose_remaps` module-level helper replacing the
  per-instance lambda previously assigned to `Redactor.policy`.
- `Gate.detector` typed as the canonical `Detector` Protocol; the
  redundant `HasAsyncDetect` Protocol was deleted.
- `ModelStage.detector` typed as `Detector`; the unused
  `SyncDetector` / `AsyncDetector` Protocols were deleted.
- `fuse(..., min_model_confidence=0.5)` kwarg replacing the
  one-field `ConsensusConfig` dataclass.
- `Breaker._is_exception` module-level helper replacing the
  per-instance lambda default.
- `TRANSIENT_EXC` constant in `app.errors` for the shared
  `except (OSError, RuntimeError, ValueError, TypeError, KeyError,
  TimeoutError)` tuple previously duplicated across every route.
- `RATE_LIMIT_UNAVAILABLE`, `AUDIT_WRITE_FAILED`,
  `AUDIT_UNINITIALISED` Prometheus counters.
- `RateLimitUnavailable` typed exception translated by the
  global error handler into a typed 503 problem.
- `REDAX_RATE_LIMIT_FAIL_OPEN` setting (default `false`).
- `bench-results/` is now in `.gitignore` and `.dockerignore`;
  the previously committed JSON reports can be regenerated by
  `make bench`.
- `dashboards/grafana-redax.json`, `alerts/prometheus.yml`, and
  `runbooks/{audit-dropped,latency-degraded}.md` so operators
  have an out-of-the-box Grafana + Prometheus + on-call story.
- `examples/wasm-demo/` ships a complete browser demo that loads
  `wasm/pkg/redax.js` produced by `make build-wasm`.
- `/v1/redact/batch`, `/v1/redact/stream`, `/v1/jobs` accept
  `use_pipeline: bool` and route through the multi-stage
  pipeline when set.

### Removed

- `app/redaction/relex.py` is gone; the `Deid` strategy now
  constructs the same placeholders directly inline, eliminating
  the duplicate HIPS implementation.
- `Settings.default_policy` field (declared but never read by
  production code; replaced by `REDACT_DEFAULT_POLICY` env var
  consumed by the lifespan).
- The dead `relex_cache_size` setting, the
  `errors.bad_request` / `unauthorized` / `rate_limited` shims,
  and `OPENMED_SHA256_MANIFEST_KEY`.

### Documentation

- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md` exist
  at the repo root and are linked from `README.md`'s "Where to
  go next" section.
- `docs/architecture.md` data-flow cache step mentions
  `cache_shared` and the per-tenant salt scoping.
- `docs/deployment.md` notes the `REDAX_RATE_LIMIT_FAIL_OPEN`
  toggle and warns against the `docker-compose.yml` Redis
  ephemeral-data caveat.
- `MILESTONES.md` documents the `M<n> #<id>` commit-tag
  convention used throughout the repo.

### CI / Tooling

- `.github/dependabot.yml` enables weekly dependency PRs for
  `pip`, `github-actions`, and `docker`.
- `.github/workflows/ci.yml` installs from `requirements.lock`
  (matching the Dockerfile) and runs `make verify`, which
  bundles lint + typecheck + tests + the determinism suite.
- `.github/workflows/release.yml` publishes the wheel and sdist
  to PyPI on tag (gated on the `PYPI_API_TOKEN` secret), and
  uploads the Docker image to GHCR.
- `.github/workflows/pages.yml` (or equivalent repo config)
  enables GitHub Pages for the `docs/` bundle.
- Python-version matrix `[3.11, 3.12, 3.13]` runs in CI.
- `Makefile` no longer hard-pins `python3.11`; the `PYTHON`
  variable defaults to whichever `python3` is on `PATH`.
- `make load` runs `locust` against the bundled `tests/load/locustfile.py`.

## [0.1.0] — 2026-09-05 (initial release)

### Added

- Detection pipeline: regex rules + Luhn checksum, GLiNER2 zero-shot NER
- Multi-pass detection (parallel N runs, dedupe by confidence)
- Five strategies: passThrough, mask (format string), hash (SHA256+salt),
  regex, autoDeID (NER + multi-pass + typed placeholders)
- Relexicalizer (hash-deterministic typed placeholders, optional seed,
  cross-request cache)
- Three built-in policies: default, strict, minimal
- Four API surfaces: sync, batch (max 1000), SSE streaming, async jobs
- Reliability: API-key + JWT auth, Redis rate limit, idempotency cache,
  response cache
- Observability: Prometheus metrics, OpenTelemetry tracing, structlog JSON
- Audit log: append-only JSONL via LocalFileAuditBackend (counts/types/
  durations only — never entity values)
- WASM bundle scaffolding: ONNX export + INT8 quantization +
  Transformers.js browser entry
- Eval harness + benchmark scripts
- Docker + Docker Compose deployment
- CI: ruff, mypy, pytest, eval gate
- Release workflow: PyPI + GHCR on tag
