# Changelog

All notable changes to this project are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/) and this project
adheres to [Semantic Versioning](https://semver.org/).

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
