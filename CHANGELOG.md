# Changelog

All notable changes to this project are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/) and this project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

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


## [0.1.0] — 2026-09-05

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
