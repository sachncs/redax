#!/usr/bin/env python3
"""Bulk-create M11 audit issues on github.com/sachncs/redax.

Each finding becomes one issue, labeled audit/M11, with a body that follows
the Finding report template (.github/ISSUE_TEMPLATE/finding.md).

Run from the repo root:  python scripts/create_m11_issues.py
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Finding:
    severity: str
    title: str
    summary: str
    location: str
    current_state: str = ""
    why: str = ""
    proposed: str = ""
    acceptance: str = ""
    references: str = ""

    def body(self) -> str:
        def section(heading: str, body: str) -> str:
            return f"## {heading}\n\n{body}\n\n" if body else ""

        return (
            section("Summary", self.summary)
            + section(
                "Location",
                f"{self.location}\n- **Severity:** `{self.severity}`",
            )
            + section("Current state", self.current_state)
            + section("Why it matters", self.why)
            + section("Proposed approach", self.proposed)
            + section("Acceptance criteria", self.acceptance)
            + section("References", self.references)
        ).rstrip() + "\n"


# M11 audit findings. Item numbers run from #147 (M11 #146 was the template).
FINDINGS: list[tuple[int, Finding]] = [
    (
        147,
        Finding(
            "major",
            "Redactor.policy assigns a lambda to a public attribute",
            "`app/redaction/redactor.py:150` carries `remap_to_original = lambda p, f=new_to_current, g=previous: g(f(p))  # noqa: E731`. AGENTS.md explicitly bans \"private helper methods on public classes — make them module-level functions instead.\"",
            "- **File:** `app/redaction/redactor.py`\n- **Lines:** `150`",
            "```python\nremap_to_original = lambda p, f=new_to_current, g=previous: g(f(p))  # noqa: E731\n```\nThe lambda is assigned to an instance attribute on `Redactor` (a public class) and exists only to capture two closure variables.",
            "Reading the redactor code requires understanding why `noqa: E731` is silenced and what the lambda captures. New contributors trip over the closure idiom. Tests can't easily swap the remap implementation.",
            "Lift to a module-level `compose_remaps(newer, older) -> Callable[[int], int]` and bind it from `Redactor.policy`. Add a unit test in `tests/unit/test_apply.py` for `compose_remaps`.",
            "- [ ] `Redactor.policy` no longer assigns a lambda.\n- [ ] `compose_remaps` is module-level and unit-tested.\n- [ ] `make verify` green.",
            "- `app/redaction/redactor.py:121-151`\n- `AGENTS.md` (\"private helper methods on public classes\")",
        ),
    ),
    (
        148,
        Finding(
            "major",
            "Drop dead SyncDetector / AsyncDetector Protocols in ModelStage",
            "`SyncDetector` and `AsyncDetector` Protocols are declared in `app/redaction/stages/model.py:19-44` but only one of each is wired into `ModelStage`. AGENTS.md: \"Prefer concrete classes over Protocol unless multiple implementations exist now or are genuinely planned.\"",
            "- **File:** `app/redaction/stages/model.py`\n- **Lines:** `19-44`",
            "```python\nclass SyncDetector(Protocol):\n    name: str\n    def detect_sync(self, text: str, entity_types: list[str]) -> list[Span]: ...\n\nclass AsyncDetector(Protocol):\n    name: str\n    async def detect(self, text: str, entity_types: list[str]) -> list[Span]: ...\n```\nOnly `OpenMedPIIDetector` implements `detect_sync`; only `RegexDetector` implements async `detect`. The runtime branch is the only consumer.",
            "Per AGENTS.md, Protocols declared without a second implementation are speculative abstraction. They make the module longer and the call site harder to read.",
            "Type the field as the concrete `Detector` from `app.inference.detector` (or `Any`) and keep the runtime `getattr(detector, \"detect_sync\", None)` fallback. Drop the Protocols.",
            "- [ ] `SyncDetector` and `AsyncDetector` deleted.\n- [ ] `ModelStage.detector` annotated as `Detector | Any`.\n- [ ] Existing tests still pass.",
            "- `app/redaction/stages/model.py:19-77`\n- `app/inference/detector.py:30-50` (existing `Detector` Protocol)",
        ),
    ),
    (
        149,
        Finding(
            "minor",
            "Drop redundant HasAsyncDetect Protocol in Gate",
            "`HasAsyncDetect` Protocol in `app/redaction/stages/gate.py:16-28` exists for one implementer (`RegexDetector`). The existing `Detector` Protocol in `app.inference.detector` already covers the same shape.",
            "- **File:** `app/redaction/stages/gate.py`\n- **Lines:** `16-28, 39`",
            "```python\nclass HasAsyncDetect(Protocol):\n    name: str\n    async def detect(self, text: str, entity_types: list[str]) -> list[Span]: ...\n```\nField type at line 39 is `detector: HasAsyncDetect`, but the only construction site (`app/main.py:109`) passes a `RegexDetector` which is also a `Detector`.",
            "Two Protocols for one shape. Pick one.",
            "Annotate `Gate.detector` with the existing `Detector` Protocol and delete `HasAsyncDetect`.",
            "- [ ] `HasAsyncDetect` removed.\n- [ ] `Gate.detector: Detector` (or `Any`).\n- [ ] `make verify` green.",
            "- `app/redaction/stages/gate.py:16-43`\n- `app/inference/detector.py:30`",
        ),
    ),
    (
        150,
        Finding(
            "major",
            "Drop the ConsensusConfig YAGNI wrapper",
            "`ConsensusConfig` in `app/redaction/stages/consensus.py:11-23` is a dataclass with one field (`min_model_confidence: float = 0.5`). It is only consumed by `fuse()` itself.",
            "- **File:** `app/redaction/stages/consensus.py`\n- **Lines:** `11-23, 34`",
            "```python\n@dataclass(frozen=True)\nclass ConsensusConfig:\n    min_model_confidence: float = 0.5\n\nDEFAULT_CONSENSUS_CONFIG = ConsensusConfig()\n\ndef fuse(regex_spans, model_spans, config: ConsensusConfig = DEFAULT_CONSENSUS_CONFIG): ...\n```",
            "A one-field dataclass with a module-level default is ceremony. Adding fields speculatively is the AGENTS.md \"just in case\" anti-pattern.",
            "Inline `min_model_confidence: float = 0.5` as a kwarg on `fuse()`. Drop the dataclass and the module-level default.",
            "- [ ] `ConsensusConfig` and `DEFAULT_CONSENSUS_CONFIG` deleted.\n- [ ] `fuse(..., min_model_confidence: float = 0.5)`.\n- [ ] `tests/unit/test_pipeline_stages.py` updated.",
            "- `app/redaction/stages/consensus.py:11-66`",
        ),
    ),
    (
        151,
        Finding(
            "major",
            "Settings.default_policy is dead config",
            "`app/config.py:50` declares `default_policy: str = \"default\"` but no production code reads it (only `tests/unit/test_smoke.py:16` asserts the default).",
            "- **File:** `app/config.py`\n- **Lines:** `50`",
            "```python\ndefault_policy: str = \"default\"\n```\nGrep confirms zero read sites outside the smoke test.",
            "Operators reading `Settings()` expect the field to mean something. Carrying a dead knob trains contributors to ignore settings, and the YAML in `policies/default.yaml` is never loaded as the default.",
            "Either wire it: in `app/main.py` lifespan, look up `load_policy(settings.policies_dir / f\"{settings.default_policy}.yaml\")` and pass the resolved field map into a default `Redactor`. Or delete the field.",
            "- [ ] `default_policy` is either wired or removed.\n- [ ] `policies/default.yaml` is loaded as the default if wired.\n- [ ] `make verify` green.",
            "- `app/config.py:50`\n- `app/redaction/policies.py:23-40`\n- `policies/default.yaml`",
        ),
    ),
    (
        152,
        Finding(
            "major",
            "app.redaction.relex is dead code; Deid inlines its own relex",
            "`app/redaction/relex.py:24-86` exposes `relexicalize(...)` but no runtime code imports it. Only `tests/unit/test_relex.py:9` does. The `Deid` strategy in `app/redaction/strategy.py:211-216` inlines its own relex loop.",
            "- **File:** `app/redaction/relex.py`, `app/redaction/strategy.py`\n- **Lines:** `relex.py:1-94`, `strategy.py:211-216`",
            "```python\n# app/redaction/relex.py\nexport def relexicalize(text, spans, seed=None, cross_request_cache=None) -> RelexResult\n```\nThe Deid strategy builds `[TYPE_NNNN]` placeholders inline; never calls `relexicalize`.",
            "Two implementations of the same HIPS idea, with subtle behavior differences (cache handling, seed signature). A reader who wants to understand relex has to compare both.",
            "Pick one. Either delete `app/redaction/relex.py` + `tests/unit/test_relex.py`, or replace the `Deid` body with `relexicalize(text, detected, seed=..., cross_request_cache=...)`.",
            "- [ ] Only one relex path remains.\n- [ ] Output of `Deid` is byte-identical to before.\n- [ ] `tests/unit/test_relex.py` aligned with the chosen source.",
            "- `app/redaction/relex.py`\n- `app/redaction/strategy.py:181-227`\n- `tests/unit/test_relex.py`",
        ),
    ),
    (
        153,
        Finding(
            "nit",
            "app/jobs/__init__.py is empty",
            "`app/jobs/__init__.py` contains no code (0 bytes). All sibling packages either re-export their public API or carry a one-line docstring.",
            "- **File:** `app/jobs/__init__.py`",
            "Empty file vs. `app/audit/__init__.py` (re-exports) and `app/bench/__init__.py` (re-exports).",
            "Asymmetry; readers don't know `app.jobs` is a real package.",
            "Add one-line docstring + re-export `JobStore, JobRecord, release_owner_count`.",
            "- [ ] `app/jobs/__init__.py` re-exports the public API.",
            "- `app/jobs/__init__.py`\n- `app/audit/__init__.py` (reference style)",
        ),
    ),
    (
        154,
        Finding(
            "nit",
            "app/auth.py __all__ re-exports Depends from stdlib",
            "`app/auth.py:48` declares `__all__ = [\"Depends\", \"require_api_key\"]`. `Depends` is a FastAPI symbol; nobody imports it through `app.auth`.",
            "- **File:** `app/auth.py`\n- **Lines:** `48`",
            "```python\n__all__ = [\"Depends\", \"require_api_key\"]\n```",
            "Pollutes the public namespace; star-imports pull a stdlib name.",
            "Drop `Depends` from `__all__`.",
            "- [ ] `__all__ = [\"require_api_key\"]`.",
            "- `app/auth.py:1-48`",
        ),
    ),
    (
        155,
        Finding(
            "nit",
            "Breaker.transient_predicate default is a per-instance lambda",
            "`app/redaction/circuit/breaker.py:78` assigns `self.transient_predicate = transient_predicate or (lambda exc: isinstance(exc, Exception))`.",
            "- **File:** `app/redaction/circuit/breaker.py`\n- **Lines:** `78`",
            "A `lambda` assigned to a per-instance attribute is hard to introspect, override in subclasses, or mock.",
            "Define `def _is_exception(exc: BaseException) -> bool: return isinstance(exc, Exception)` at module scope and reference it from the default.",
            "- [ ] Module-level `_is_exception` helper; instance default uses the name.\n- [ ] Tests still pass.",
            "- `app/redaction/circuit/breaker.py:68-86`",
        ),
    ),
    (
        156,
        Finding(
            "major",
            "Duplicated request-id plumbing across every route handler",
            "`app/api/redact.py:69`, `app/api/batch.py:63`, `app/api/stream.py:70`, `app/api/jobs.py:56` each run `request.headers.get(\"X-Request-ID\") or uuid.uuid4().hex` even though `app/middleware.py:72-79` already binds the id into structlog context.",
            "- **File:** `app/api/redact.py`, `app/api/batch.py`, `app/api/stream.py`, `app/api/jobs.py`\n- **Lines:** `redact.py:69`, `batch.py:63`, `stream.py:70`, `jobs.py:56`",
            "Same expression in four files; bypasses the structlog context that the middleware already populated.",
            "Two ways to read the same id; easy to drift (e.g. fallback uuid semantics).",
            "Add a `Depends(get_request_id)` provider in `app/middleware.py` that reads `structlog.contextvars.get_contextvars()[\"request_id\"]` and injects into handlers.",
            "- [ ] All four routes use the dependency.\n- [ ] Middleware remains the only place the fallback UUID is minted.\n- [ ] Existing tests pass.",
            "- `app/middleware.py:72-89`\n- `app/api/redact.py:69`, `batch.py:63`, `stream.py:70`, `jobs.py:56`",
        ),
    ),
    (
        157,
        Finding(
            "major",
            "Per-route metrics boilerplate repeated across every endpoint",
            "Every route starts with `start = time.perf_counter()`, declares `endpoint` / `method`, increments `REQUESTS` and observes `REQUEST_LATENCY` in the same try/except/finally scaffolding.",
            "- **File:** `app/api/*.py`\n- **Lines:** `redact.py:66-68, 186, 197-207`; `batch.py:60-62, 105, 116-126`; `stream.py:68-70, 127, 128-137`; `jobs.py:54-56, 82, 84-87, 113`; `policies.py:33-35, 40, 52-58`; `health.py:37-39, 41, 43-46, 63-65, 67-68, 79-81, 97-99, 111, 113-116, 126-128, 130, 132-134`",
            "Six files, ~12 line blocks duplicated; metrics labels duplicated; risk of typos in label values.",
            "Lift to a `@instrumented(endpoint, method)` decorator or FastAPI dependency that wraps the handler and instruments both counters + the histogram.",
            "- [ ] One decorator used by all six route files.\n- [ ] Existing metric labels and behaviour preserved.\n- [ ] `make verify` green.",
            "- `app/observability/metrics.py`\n- All six `app/api/*.py` files",
        ),
    ),
    (
        158,
        Finding(
            "minor",
            "Route transient-exception tuple duplicated",
            "`except (OSError, RuntimeError, ValueError, TypeError, KeyError)` appears verbatim in `app/api/redact.py:200`, `app/api/batch.py:119`, `app/api/stream.py:128`, `app/api/jobs.py:84, 187`, `app/jobs/store.py:140, 199`.",
            "- **File:** `app/api/*.py`, `app/jobs/store.py`",
            "Same tuple in seven places.",
            "If one site adds `ConnectionError` and another doesn't, behavior drifts.",
            "Lift to `from app.errors import TRANSIENT_EXC` and reference.",
            "- [ ] All seven sites import the constant.\n- [ ] `app/errors.py` exports `TRANSIENT_EXC`.",
            "- `app/api/redact.py:200`\n- `app/api/batch.py:119`\n- `app/api/stream.py:128`\n- `app/api/jobs.py:84, 187`\n- `app/jobs/store.py:140, 199`",
        ),
    ),
    (
        159,
        Finding(
            "minor",
            "Duplicate spans = list(...) assignment in /v1/redact legacy path",
            "`app/api/redact.py:147` and `:153` both contain `spans = list(result.spans)`. The second is a dead re-assignment of the same value.",
            "- **File:** `app/api/redact.py`\n- **Lines:** `147, 153`",
            "Pure dead code from an earlier refactor.",
            "Removes a future maintainer's confusion.",
            "Remove line 153.",
            "- [ ] Single `spans = list(result.spans)` in the legacy branch.",
            "- `app/api/redact.py:142-153`",
        ),
    ),
    (
        160,
        Finding(
            "minor",
            "Pipeline path always returns empty relex_map",
            "`app/api/redact.py:136` initialises `relex_map: dict[str, str] = {}` for the pipeline branch; the pipeline never populates it. The legacy `Redactor` path returns `result.relex_map` which may be non-empty.",
            "- **File:** `app/api/redact.py`\n- **Lines:** `136-141, 188-196`",
            "Response shape is asymmetric: pipeline users always see `relex_map = {}` even when the policy would have relexed.",
            "Two paths return different shapes for the same field; downstream consumers can't rely on `relex_map`.",
            "Either return the relex map from `Pipeline.__call__` (build it in `app/redaction/pipeline.py` using the same logic as `Deid.run`), or document the asymmetry in `docs/api.md`.",
            "- [ ] Either both paths populate `relex_map` or docs state the asymmetry.",
            "- `app/api/redact.py:120-141`\n- `app/redaction/pipeline.py:64-97`\n- `app/redaction/strategy.py:181-227`",
        ),
    ),
    (
        161,
        Finding(
            "minor",
            "audit_event.model_hash writes the detector name, not a hash",
            "`app/api/redact.py:183` sets `audit_kwargs[\"model_hash\"] = state.detector.name if state.detector else \"\"`. The detector `name` (e.g. `\"gliner2\"`) is not a SHA-256.",
            "- **File:** `app/api/redact.py`\n- **Lines:** `183`",
            "Audit records claim a `model_hash` but contain a label. Downstream auditors checking the pinned model can't reconstruct.",
            "Either rename the field to `model_name`, or compute the SHA-256 via `app/integrity.py:snapshot_digest(...)` on the model cache and persist that.",
            "- [ ] Audit field is either renamed or carries a real SHA-256.\n- [ ] `tests/unit/test_audit.py` asserts the chosen shape.",
            "- `app/api/redact.py:174-184`\n- `app/audit/backend.py:30-38`\n- `app/integrity.py:39-63`",
        ),
    ),
    (
        162,
        Finding(
            "minor",
            "ModelStage.run_async builds a fresh ThreadPoolExecutor per call",
            "`app/redaction/stages/model.py:99-118` constructs `concurrent.futures.ThreadPoolExecutor(max_workers=1)` for every fallback `run_async` invocation.",
            "- **File:** `app/redaction/stages/model.py`\n- **Lines:** `99-118`",
            "Thread-pool creation cost is paid per call; the executor is single-thread and one-shot.",
            "Hold a module-level executor; close at lifespan teardown via `app/main.py`.",
            "- [ ] Single executor reused.\n- [ ] Lifecycle wired into `app/main.py` teardown.",
            "- `app/redaction/stages/model.py:99-118`\n- `app/main.py:147-169`",
        ),
    ),
    (
        163,
        Finding(
            "major",
            "Redactor.policy() field composition has weak test coverage",
            "No test exercises multi-field composition or verifies that the `remap_to_original` chain returns correct original-input coordinates when each field's substitution shifts offsets.",
            "- **File:** `tests/unit/test_redactor.py`\n- **Lines:** all",
            "Single-field paths tested; the multi-field remap chain (the only place `compose_remaps` is exercised end-to-end) is uncovered.",
            "Regression risk: a coordinate-shifting bug in policy-mode would be invisible to CI.",
            "Add a multi-field test that verifies (a) output text is composed correctly, (b) every reported `span.start` / `span.end` references the original input coordinates.",
            "- [ ] New test in `tests/unit/test_redactor.py` covering ≥3-field composition.\n- [ ] Asserts coordinate remap accuracy.",
            "- `app/redaction/redactor.py:100-156`\n- `tests/unit/test_redactor.py`",
        ),
    ),
    (
        164,
        Finding(
            "major",
            "fuse() contextual-optional branch has no property test",
            "The `(mean coverage, 1)` exception path in `app/bench/rscore.py:271-280` (no mandatory spans + non-empty yellow) is only exercised in `test_bench_rscore.py` end-to-end; `app/redaction/stages/consensus.py:fuse` itself has no test for it.",
            "- **File:** `app/redaction/stages/consensus.py`, `tests/unit/test_pipeline_stages.py`\n- **Lines:** `consensus.py:31-66`, `pipeline_stages.py:1-67`",
            "Only the penalty branch (`(0, 1-cov)`) is unit-tested.",
            "If `fuse` ever changes to drop yellow spans unconditionally when there are no regex hits, the bench R-Score would silently change without a unit test catching it.",
            "Add a `fuse` test asserting that all-empty-red + non-empty-yellow returns the yellow spans (not `(0,)`).",
            "- [ ] New test in `tests/unit/test_pipeline_stages.py`.\n- [ ] Comment links to `docs/bench.md` \"contextual-optional\".",
            "- `app/redaction/stages/consensus.py:31-66`\n- `tests/unit/test_pipeline_stages.py`",
        ),
    ),
    (
        165,
        Finding(
            "minor",
            "cache_shared=True cross-tenant key derivation is untested",
            "`app/api/cache.py:10-41` defines `redaction_cache_payload(..., shared: bool)`; `tests/unit/test_api_cache.py` only covers the salted (per-tenant) path.",
            "- **File:** `app/api/cache.py`, `tests/unit/test_api_cache.py`",
            "`cache_shared=True` is a security-relevant opt-in (cross-tenant cache reuse).",
            "Add a test asserting that with `shared=True` two payloads differing only in salt hash to the same key.",
            "- [ ] Test in `tests/unit/test_api_cache.py` covering shared cache.\n- [ ] Asserts salt-independence.",
            "- `app/api/cache.py:10-41`\n- `tests/unit/test_api_cache.py`",
        ),
    ),
    (
        166,
        Finding(
            "minor",
            "queue_depth() gauge reader is untested",
            "`app/observability/metrics.py:67-77` defines `queue_depth()`; no `test_observability_metrics.py` exists.",
            "- **File:** `app/observability/metrics.py`\n- **Lines:** `67-77`",
            "`/v1/jobs` admission depends on `queue_depth() >= max_inflight`. If the function returns 0 when it should return N, the limiter is silently broken.",
            "Add a unit test that increments `QUEUE_DEPTH`, then asserts `queue_depth()` returns the expected float.",
            "- [ ] New file `tests/unit/test_observability_metrics.py`.\n- [ ] Test for `queue_depth()`.",
            "- `app/observability/metrics.py:53-77`",
        ),
    ),
    (
        167,
        Finding(
            "minor",
            "FileAudit.rotate_if_needed truncation branch untested",
            "`app/audit/file.py:148-151` handles `rotation_backups <= 0` by truncating; `tests/unit/test_audit.py` does not assert this branch.",
            "- **File:** `app/audit/file.py`\n- **Lines:** `148-151`",
            "Operators who set `REDAX_AUDIT_ROTATION_BACKUPS=0` expect truncation.",
            "Add a test that builds a 1-MiB log, sets `max_bytes=1`, `rotation_backups=0`, and asserts the file is empty after one rotation tick.",
            "- [ ] New test in `tests/unit/test_audit.py`.\n- [ ] Asserts `path.read_text() == \"\"`.",
            "- `app/audit/file.py:139-156`\n- `tests/unit/test_audit.py`",
        ),
    ),
    (
        168,
        Finding(
            "minor",
            "FileAudit.prune_old_events no-op branch untested",
            "`app/audit/file.py:159-184` `prune_old_events` short-circuits when `retention_seconds <= 0` or the file is absent; not unit-tested.",
            "- **File:** `app/audit/file.py`\n- **Lines:** `159-184`",
            "Same.",
            "Add a test asserting that with `retention_seconds=0` and an existing file, the file is left untouched.",
            "- [ ] New test in `tests/unit/test_audit.py`.",
            "- `app/audit/file.py:159-184`\n- `tests/unit/test_audit.py`",
        ),
    ),
    (
        169,
        Finding(
            "minor",
            "emit_access_line is transitively tested only",
            "`app/middleware.py:22-42` `emit_access_line(...)` is invoked by the `request_context` middleware but not unit-tested in isolation.",
            "- **File:** `app/middleware.py`, `tests/unit/test_middleware.py`\n- **Lines:** `middleware.py:22-42`",
            "If the logger call changes shape, only end-to-end tests catch it.",
            "Add a unit test that captures `structlog` output and asserts the expected event.",
            "- [ ] New test in `tests/unit/test_middleware.py`.",
            "- `app/middleware.py:22-42`",
        ),
    ),
    (
        170,
        Finding(
            "minor",
            "sha256_file is transitively tested only",
            "`app/integrity.py:20-36` `sha256_file(...)` is the building block of `snapshot_digest`; only `snapshot_digest` is unit-tested.",
            "- **File:** `app/integrity.py`\n- **Lines:** `20-36`",
            "Same.",
            "Add a unit test that compares `sha256_file` against `hashlib.sha256(...).hexdigest()` on a known input.",
            "- [ ] New test in `tests/unit/test_determinism.py` or a new `tests/unit/test_integrity.py`.",
            "- `app/integrity.py:20-36`",
        ),
    ),
    (
        171,
        Finding(
            "minor",
            "release_owner_count int(raw) <= 1 delete branch untested",
            "`app/jobs/store.py:192-204` `release_owner_count` deletes the counter when it reaches 1 (or below); not directly unit-tested.",
            "- **File:** `app/jobs/store.py`, `tests/unit/test_jobs_store.py`\n- **Lines:** `store.py:192-204`",
            "If the delete branch never fires, `redax:jobs:{owner}` accumulates and `count_for_key` overflows.",
            "Add a unit test that drives the counter to 1, calls `release_owner_count`, and asserts the key is gone.",
            "- [ ] New test in `tests/unit/test_jobs_store.py`.\n- [ ] Uses an in-process Redis stub (`fakeredis` if available; otherwise a real one).",
            "- `app/jobs/store.py:192-204`",
        ),
    ),
    (
        172,
        Finding(
            "minor",
            "Redactor.plain() is only transitively tested",
            "`app/redaction/redactor.py:79-98` `Redactor.plain(...)` is exercised through API integration tests; no direct unit test.",
            "- **File:** `app/redaction/redactor.py`, `tests/unit/test_redactor.py`\n- **Lines:** `redactor.py:79-98`",
            "Same as #163.",
            "Add a unit test that drives `plain` with a stub detector and asserts the substituted text + span list.",
            "- [ ] New test in `tests/unit/test_redactor.py`.",
            "- `app/redaction/redactor.py:79-98`",
        ),
    ),
    (
        173,
        Finding(
            "minor",
            "with_seed_signature suffix derivation is untested",
            "`app/redaction/relex.py:89-93` `with_seed_signature(...)` is only hit when `relexicalize` is called with `seed`; no isolated test.",
            "- **File:** `app/redaction/relex.py`, `tests/unit/test_relex.py`\n- **Lines:** `relex.py:89-93`",
            "The 4-char suffix is documented as \"visibly different\" but never asserted.",
            "Add a test that seeds the same placeholder twice with different `seed` values and asserts the suffixes differ.",
            "- [ ] New test in `tests/unit/test_relex.py`.",
            "- `app/redaction/relex.py:89-93`",
        ),
    ),
    (
        174,
        Finding(
            "nit",
            "load_policy FileNotFoundError path is untested",
            "`app/redaction/policies.py:23-40` `load_policy(...)` raises `FileNotFoundError` when the path is absent; no negative test.",
            "- **File:** `app/redaction/policies.py`, `tests/unit/test_policies.py`\n- **Lines:** `policies.py:23-40`",
            "Trivial gap.",
            "Add a `pytest.raises(FileNotFoundError)` test in `tests/unit/test_policies.py`.",
            "- [ ] New test in `tests/unit/test_policies.py`.",
            "- `app/redaction/policies.py:23-40`",
        ),
    ),
    (
        175,
        Finding(
            "major",
            "CHANGELOG missing entries for M11 #142, #143, #144",
            "`CHANGELOG.md` under `## [Unreleased]` only documents the LICENSE and README changes. The M11 #142 (dead-code sweep), M11 #143 (bench simplification), and M11 #144 (RENAME_MAP.md deletion) commits removed user-visible symbols and broke the `fused_entity_groups` signature, but no `### Removed` block was added.",
            "- **File:** `CHANGELOG.md`\n- **Lines:** `13-100`",
            "Per Keep-a-Changelog convention, removals + signature breaks need a `### Removed` entry. Users upgrading past the commits see no warning.",
            "Add a `### Removed` block under `## [Unreleased]` enumerating: `Settings.relex_cache_size`, `errors.bad_request` / `unauthorized` / `rate_limited`, `OPENMED_SHA256_MANIFEST_KEY`, `JobStore.build_default_store`, `Pipeline.consensus_stage`, `Gate.default`, `fused_entity_groups(target_red=...)` parameter, `is_connector_marker`, `RENAME_MAP.md`.",
            "- [ ] CHANGELOG `### Removed` block lists every removed symbol.\n- [ ] Commit message references the milestone.",
            "- `CHANGELOG.md`\n- M11 commit messages #142-#144",
        ),
    ),
    (
        176,
        Finding(
            "minor",
            "No published milestone plan file",
            "Recent commits reference `M<n> #<id>` but no `plans/`, `ROADMAP.md`, or milestone index is committed. Readers can't look up what an item means or what remains.",
            "- **File:** repo root (missing)\n- **Lines:** n/a",
            "M11 sequence numbers are opaque outside the commit log.",
            "Either commit a milestone plan file (e.g. `MILESTONES.md`) listing each item's title and intended scope, or document the plan-reference convention in `AGENTS.md`.",
            "- [ ] `MILESTONES.md` exists, or\n- [ ] `AGENTS.md` says where the plan lives.",
            "- `AGENTS.md`",
        ),
    ),
    (
        177,
        Finding(
            "nit",
            "Verify commit author on every commit",
            "`AGENTS.md` requires `sachin <sachncs@gmail.com>`. Current local config matches; verify on every future commit (CI hook).",
            "- **File:** `.git/hooks/` or CI config\n- **Lines:** n/a",
            "No automated check.",
            "Add a `pre-commit` config (or CI check) that runs `git log --format='%an <%ae>' -1 HEAD` and asserts it equals `sachin <sachncs@gmail.com>`.",
            "- [ ] Either `.pre-commit-config.yaml` exists, or\n- [ ] CI workflow asserts author.",
            "- `AGENTS.md`\n- `.github/workflows/ci.yml`",
        ),
    ),
    (
        178,
        Finding(
            "major",
            "docs/api.md documents response field as text_hash, code returns digest",
            "`docs/api.md:8,45,61,68` writes `text_hash`. `app/api/redact.py:47` declares `digest: str | None`; line 195 returns `digest=digest`. `README.md:192` also says `digest`. Three sources, two names.",
            "- **File:** `docs/api.md`, `app/api/redact.py`, `README.md`\n- **Lines:** `docs/api.md:8,45,61,68`; `redact.py:47,195`; `README.md:192`",
            "Users following the docs send / expect the wrong field name.",
            "Pick one. Either:\n- rename the response field to `text_hash` in `app/api/redact.py`, `app/redaction/pipeline.py`, `README.md`, and `docs/api.md`; or\n- update `docs/api.md` to say `digest`.",
            "- [ ] One name across code, README, docs.\n- [ ] CHANGELOG entry.",
            "- `docs/api.md`\n- `app/api/redact.py:39-48, 192-196`\n- `app/redaction/pipeline.py:39-48`\n- `README.md:192`",
        ),
    ),
    (
        179,
        Finding(
            "major",
            "docs/integration.md Python SDK example is fabricated",
            "`docs/integration.md:7-19` shows `from redax import Redactor`, `Redactor(policy=\"default\")`, and `redactor.redact(user_message)` as sync. None of these match the real API: the package is `app.*`; `Redactor.__init__` takes `(detector, strategies, replacement)`; `redact` is `async def`.",
            "- **File:** `docs/integration.md`\n- **Lines:** `7-19`",
            "Users copying the snippet get an ImportError or a TypeError at the first call.",
            "Replace with a working example using `app.redaction.redactor.Redactor`, the real constructor, and `await redactor.redact(...)`.",
            "- [ ] Snippet runs end-to-end against the running service.\n- [ ] Updated in `docs/integration.md`.",
            "- `docs/integration.md:7-19`\n- `app/redaction/redactor.py:46-77`",
        ),
    ),
    (
        180,
        Finding(
            "major",
            "docs/policies.md Python example shows fabricated Redactor(policy=...) constructor",
            "`docs/policies.md:80-85` shows `Redactor(policy=\"default\")` — the constructor takes `(detector, strategies, replacement)`, not a policy name.",
            "- **File:** `docs/policies.md`\n- **Lines:** `80-85`",
            "Same defect class as #179.",
            "Replace with `Redactor(detector=..., strategies=..., replacement=...)` plus `await redactor.redact(text, policy=load_policy(\"policies/default.yaml\").fields)`.",
            "- [ ] Snippet runs.",
            "- `docs/policies.md:80-85`\n- `app/redaction/redactor.py:46-77`\n- `app/redaction/policies.py:23-40`",
        ),
    ),
    (
        181,
        Finding(
            "major",
            "Policy format strings do not support {last4} placeholder substitution",
            "`policies/default.yaml:18-20` and friends use `[CC-{last4}]`, `[ID]`. `Mask.run` and `Regex.run` apply `format` as a literal — `{last4}` is never substituted. Reproduced:\n\n```\ninput:    \"My card is 4532 0151 1283 0366 thanks.\"\npolicy:   {\"fields\": {\"cc\": {\"strategy\": \"regex\", \"format\": \"[CC-{last4}]\", \"entity_types\": [\"CREDIT_CARD\"]}}}\noutput:   \"My card is [CC-{last4}] thanks.\"     # literal {last4}\n```",
            "- **File:** `policies/*.yaml`, `app/redaction/strategy.py`\n- **Lines:** `strategy.py:73, 147`",
            "Operators believe they get the last four digits; they don't.",
            "Either implement substitution in `Mask.run`/`Regex.run` (use a small template that knows the matched text) or rewrite the YAML to literal strings.",
            "- [ ] `[CC-0366]` (or equivalent) produced for the reproducer above.\n- [ ] YAML unchanged if implementation wins; implementation unchanged if YAML wins.",
            "- `app/redaction/strategy.py:60-90, 118-154`\n- `policies/default.yaml`, `policies/strict.yaml`, `policies/minimal.yaml`",
        ),
    ),
    (
        182,
        Finding(
            "major",
            "docs/architecture.md references nonexistent app/inference/regex_detector.py",
            "`docs/architecture.md:59` lists `app/inference/regex_detector.py | Regex rules + Luhn checksum` in the module map. The actual file is `app/inference/regex.py`.",
            "- **File:** `docs/architecture.md`\n- **Lines:** `59`",
            "Stale rename artifact from the Twelve-Hard-Rules refactor.",
            "Update the module map to `app/inference/regex.py`.",
            "- [ ] All module map entries match `ls app/`.",
            "- `docs/architecture.md:30-65`",
        ),
    ),
    (
        183,
        Finding(
            "blocker",
            "README links to three non-existent files",
            "`README.md:348` links to `CONTRIBUTING.md`, line 353 to `CODE_OF_CONDUCT.md`, line 357 to `SECURITY.md`. None exist (verified via `ls`).",
            "- **File:** `README.md`\n- **Lines:** `348, 353, 357`",
            "Users following the link get a 404 from GitHub.",
            "Either commit minimal versions of each (Apache-2.0 boilerplate + 5-line \"how to contribute / how to report\"), or remove the three sections from `README.md`.",
            "- [ ] Either three files exist or the three sections are deleted.",
            "- `README.md:348-360`",
        ),
    ),
    (
        184,
        Finding(
            "minor",
            "tests/conftest.py:11-18 fixture docstring says milestones are future work",
            "The docstring reads `Real wiring lands in later milestones; this fixture exists so unit + integration tests can register their own routes against a clean FastAPI app.` M1–M11 have shipped.",
            "- **File:** `tests/conftest.py`\n- **Lines:** `11-18`",
            "Stale comment.",
            "Trim the comment to its current behavior.",
            "- [ ] Stale comment removed.",
            "- `tests/conftest.py:11-18`",
        ),
    ),
    (
        185,
        Finding(
            "minor",
            "policies/default.yaml header comment refers to an unshipped milestone",
            "`policies/default.yaml:1-3` reads `Loaded by app.redaction.policies.load_policy() once M4 lands`. M4 has shipped; `Settings.default_policy` is declared but not wired (see #151).",
            "- **File:** `policies/default.yaml`\n- **Lines:** `1-3`",
            "Same staleness as #184.",
            "Delete the comment or wire `Settings.default_policy` into the lifespan.",
            "- [ ] Stale comment removed or the setting wired.",
            "- `policies/default.yaml:1-3`\n- `app/config.py:50`",
        ),
    ),
    (
        186,
        Finding(
            "minor",
            "docs/architecture.md data-flow cache step omits shared/salted key scoping",
            "`docs/architecture.md:39-41` lists the cache steps but does not mention that `cache_shared=False` isolates by salt (per-tenant) and `cache_shared=True` shares.",
            "- **File:** `docs/architecture.md`\n- **Lines:** `39-41`",
            "Operators deploying two replicas with the same `REDAX_HASH_SALT` don't realise the response cache is shared.",
            "Add a one-sentence callout about the `REDAX_CACHE_SHARED` setting.",
            "- [ ] Sentence added to the cache step.",
            "- `docs/architecture.md:39-41`\n- `app/api/cache.py:10-41`",
        ),
    ),
    (
        187,
        Finding(
            "nit",
            "docs/bench.md does not link to the implementation module",
            "`docs/bench.md` describes Algorithm-2 but never links to `app/bench/fusion.py` (the source).",
            "- **File:** `docs/bench.md`\n- **Lines:** `75-80`",
            "Trivial.",
            "Add a \"Source\" section with relative link to `app/bench/fusion.py`.",
            "- [ ] Link present.",
            "- `docs/bench.md`",
        ),
    ),
    (
        188,
        Finding(
            "major",
            ".github/workflows/ci.yml installs via pip install -e .[dev], not requirements.lock",
            "`ci.yml:21` runs `pip install -e \".[dev]\"`. The Dockerfile installs from `requirements.lock` and `AGENTS.md` requires the lockfile. CI is free to pick a different resolver.",
            "- **File:** `.github/workflows/ci.yml`\n- **Lines:** `21`",
            "Bit-for-bit reproducibility claim from `Dockerfile:8` is broken in CI.",
            "Replace with `pip install -r requirements.lock && pip install -e . --no-deps`.",
            "- [ ] CI installs from `requirements.lock`.",
            "- `.github/workflows/ci.yml:21`\n- `Dockerfile:5-9`",
        ),
    ),
    (
        189,
        Finding(
            "major",
            ".github/workflows/ci.yml never runs make verify",
            "`ci.yml:36-39` runs `python scripts/eval.py` + `pytest`. `AGENTS.md`'s pre-commit requirement is `make verify` which adds `ruff`, `mypy`, and the 16-test determinism gate.",
            "- **File:** `.github/workflows/ci.yml`\n- **Lines:** `36-39`",
            "CI is weaker than the documented pre-commit gate.",
            "Replace the `pytest` + `scripts/eval.py` steps with a single `make verify` step (or its constituent commands).",
            "- [ ] CI runs `make verify`.\n- [ ] Block merge on failure.",
            "- `.github/workflows/ci.yml`\n- `Makefile:23`",
        ),
    ),
    (
        190,
        Finding(
            "major",
            ".github/workflows/release.yml does not publish to PyPI",
            "Release workflow builds the wheel, builds the Docker image, pushes GHCR, and uploads the wheel as an artifact — but never publishes to PyPI despite `pyproject.toml` shipping.",
            "- **File:** `.github/workflows/release.yml`\n- **Lines:** `34-44`",
            "Users can't `pip install redax`.",
            "Add `pypa/gh-action-pypi-publish@release/v1` after `python -m build`; gate on `PYPI_API_TOKEN` secret.",
            "- [ ] On tag, wheel + sdist upload to PyPI.",
            "- `.github/workflows/release.yml`\n- `pyproject.toml`",
        ),
    ),
    (
        191,
        Finding(
            "major",
            "Dockerfile pre-downloads OpenMed snapshot while REDAX_DETECTOR defaults to gliner2",
            "`Dockerfile:32-35` runs `python scripts/download_models.py --model OpenMed/... --revision df7af994...` at build time. `Settings.detector` defaults to `Literal[\"gliner2\", \"regex\"]` (`app/config.py:43`) with default `\"gliner2\"`.",
            "- **File:** `Dockerfile`, `app/config.py`\n- **Lines:** `Dockerfile:32-35`; `config.py:43`",
            "Image ships the OpenMed snapshot but the default config uses GLiNER2. First request fails to load the GLiNER2 model.",
            "Either bundle the GLiNER2 snapshot in the Dockerfile, or change the default to `openmed`, or honor `REDAX_DETECTOR` at build time.",
            "- [ ] First request after `docker run` loads a model that exists in the image.",
            "- `Dockerfile:32-37`\n- `app/config.py:43-47`",
        ),
    ),
    (
        192,
        Finding(
            "minor",
            "Makefile hard-pins python3.11",
            "`Makefile:6` sets `PYTHON ?= python3.11`. `pyproject.toml:requires-python = \">=3.11\"` and `mypy` is configured for `python_version = \"3.12\"`. The verification host only has 3.12.",
            "- **File:** `Makefile`\n- **Lines:** `6`",
            "Developers on 3.12-only machines can't run `make verify` without overriding.",
            "Either drop the pin (use `python3`), or document the requirement.",
            "- [ ] `make verify` works on a 3.12-only host.",
            "- `Makefile:1-25`",
        ),
    ),
    (
        193,
        Finding(
            "minor",
            "tests/load/locustfile.py is not exercised by CI or Makefile",
            "`tests/load/locustfile.py` exists; no `make load` target and no CI job.",
            "- **File:** `tests/load/locustfile.py`, `Makefile`, `.github/workflows/ci.yml`",
            "Load tests rot.",
            "Add an opt-in `make load` target; document as a pre-release gate.",
            "- [ ] `make load` runs the locustfile.",
            "- `tests/load/locustfile.py`",
        ),
    ),
    (
        194,
        Finding(
            "nit",
            "docker-compose Redis runs with --save \"\" --appendonly no",
            "`docker-compose.yml:30` uses ephemeral Redis. Fine for dev, breaks for production.",
            "- **File:** `docker-compose.yml`\n- **Lines:** `30`",
            "Operators copy the compose file to production and lose rate-limit + job state on restart.",
            "Add a comment in `docker-compose.yml` and a warning in `docs/deployment.md`.",
            "- [ ] Both files note the persistence caveat.",
            "- `docker-compose.yml:30`\n- `docs/deployment.md`",
        ),
    ),
    (
        195,
        Finding(
            "nit",
            "Dockerfile HEALTHCHECK uses python -c rather than exec form",
            "`Dockerfile:51-53` runs `CMD python -c \"import httpx; httpx.get(...)\"`. Exec form would spawn one fewer shell.",
            "- **File:** `Dockerfile`\n- **Lines:** `51-53`",
            "Cosmetic.",
            "Convert to exec form: `[\"CMD\", \"python\", \"-c\", \"...\"]`.",
            "- [ ] Exec form.",
            "- `Dockerfile:51-53`",
        ),
    ),
    (
        196,
        Finding(
            "major",
            "Rate limit fails closed when Redis is down",
            "`app/ratelimit.py:18-20, 45, 62` returns 503 \"Rate limiting unavailable\" for any authenticated request when Redis is unreachable. This is documented as a fail-closed choice, but the README and docker-compose imply rate-limiting is just \"on.\"",
            "- **File:** `app/ratelimit.py`, `docs/deployment.md`\n- **Lines:** `ratelimit.py:39, 45, 62`",
            "A single transient Redis hiccup takes the API down for every authenticated request. Operators discover this only after the outage.",
            "Add `REDAX_RATE_LIMIT_FAIL_OPEN` (default `false`) and document in `docs/deployment.md`. When set, log a warning + increment `redax_rate_limit_unavailable_total` and let the request proceed.",
            "- [ ] New setting + metric.\n- [ ] Documented in `docs/deployment.md`.",
            "- `app/ratelimit.py:12-63`\n- `app/config.py:60-72`\n- `docs/deployment.md`",
        ),
    ),
    (
        197,
        Finding(
            "major",
            "Anonymous key starves its own per-key quota",
            "`app/auth.py:40-45` returns `\"anonymous\"` when `REDAX_API_KEYS` is empty. `app/api/jobs.py:73` checks `count_for_key(api_key)` against `max_jobs_per_key`. Every anonymous submission counts against the same `redax:jobs:anonymous` bucket.",
            "- **File:** `app/api/jobs.py`, `app/jobs/store.py`\n- **Lines:** `jobs.py:73-76`; `store.py:109-115`",
            "With auth disabled, the quota is per-process (good) but the metric and audit trail collapse to a single bucket.",
            "Reject `/v1/jobs` with 401 when `REDAX_API_KEYS` is empty.",
            "- [ ] New 401 path.",
            "- `app/api/jobs.py:65-77`\n- `app/auth.py:40-45`",
        ),
    ),
    (
        198,
        Finding(
            "minor",
            "FileAudit.record() is a silent no-op when queue is None",
            "`app/audit/file.py:91-103` `record()` returns immediately if `self.queue is None`. No log line, no counter.",
            "- **File:** `app/audit/file.py`\n- **Lines:** `91-103`",
            "Audit gaps are invisible.",
            "Increment a `redax_audit_uninitialised_total` counter; log a warning once per process.",
            "- [ ] Metric + log.",
            "- `app/audit/file.py:91-103`\n- `app/observability/metrics.py:59-64`",
        ),
    ),
    (
        199,
        Finding(
            "minor",
            "FileAudit drain suppresses all exceptions on the write path",
            "`app/audit/file.py:114` uses `contextlib.suppress(Exception)` around the file write.",
            "- **File:** `app/audit/file.py`\n- **Lines:** `114`",
            "Disk-full / permission-denied errors are swallowed; the queue keeps accepting events that never land.",
            "Replace with `try/except Exception as exc: log.warning(...)` and increment a counter.",
            "- [ ] Log + counter on every write failure.",
            "- `app/audit/file.py:105-123`",
        ),
    ),
    (
        200,
        Finding(
            "major",
            "verify() rejects change-me salt only when auth is enabled",
            "`app/config.py:99-105` checks `if keys:` before rejecting `change-me` / `dev-key`. The salt also seeds the `hash` strategy + cache key, so it's unsafe even when auth is disabled.",
            "- **File:** `app/config.py`\n- **Lines:** `99-105`",
            "Operator sets `REDAX_HASH_SALT=change-me REDAX_API_KEYS=` and assumes the defaults are safe; cache keys are predictable.",
            "Move the salt check above the `if keys:` gate.",
            "- [ ] Salt always rejected.",
            "- `app/config.py:91-115`",
        ),
    ),
    (
        201,
        Finding(
            "major",
            "Redis keys share the redax:* prefix across deployments",
            "`app/api/redact.py:88,106,157-166` and `app/jobs/store.py:56-57` use `redax:cache:...`, `redax:idem:...`, `redax:job:...`, `redax:jobs:...` without any per-deployment namespace.",
            "- **File:** `app/api/redact.py`, `app/jobs/store.py`\n- **Lines:** `redact.py:88, 106, 157-166`; `store.py:56-57`",
            "Two redax deployments sharing one Redis collide on idempotency, response cache, and job counters.",
            "Derive a prefix from `REDAX_HASH_SALT` (truncated) or `REDAX_ENV`, applied to every key.",
            "- [ ] All `redax:*` keys carry the deployment prefix.",
            "- `app/api/redact.py:88-166`\n- `app/jobs/store.py:56-57`\n- `app/ratelimit.py:46`",
        ),
    ),
    (
        202,
        Finding(
            "nit",
            "Rate-limit 503 returns a generic problem type",
            "`app/ratelimit.py:39,45,62` raises `HTTPException(503, \"Rate limiting unavailable\")`. The generic handler renders this as `https://redax.ai/errors/http-503` rather than a rate-limit-specific problem type.",
            "- **File:** `app/ratelimit.py`, `app/errors.py`\n- **Lines:** `ratelimit.py:39, 45, 62`",
            "Operators monitoring `type` URLs can't distinguish rate-limit-unavailable from generic 503s.",
            "Add a `rate_limited_unavailable` helper in `app/errors.py` (parallel to `job_limit`); call it from `rate_limit`.",
            "- [ ] Typed problem URL on the rate-limit 503 path.",
            "- `app/ratelimit.py:39-62`\n- `app/errors.py:72-92`",
        ),
    ),
    (
        203,
        Finding(
            "nit",
            "Dockerfile downloads models as root before USER redax",
            "`Dockerfile:35-37` runs `python scripts/download_models.py` before `USER redax`. The `/models` mount is chowned to `redax:redax` but the build step itself runs as root.",
            "- **File:** `Dockerfile`\n- **Lines:** `32-37`",
            "Cosmetic; easy to regress in a refactor.",
            "Add a comment noting the build-then-chown sequence.",
            "- [ ] Comment present.",
            "- `Dockerfile:32-46`",
        ),
    ),
    (
        204,
        Finding(
            "nit",
            "Verify Path.rglob symlink-traversal claim is unfounded",
            "The symlink-traversal worry raised in the M11 audit report does not apply: `Path.rglob` does not follow symlinks by default. No fix needed.",
            "- **File:** `app/integrity.py`\n- **Lines:** `39-63`",
            "Documented for completeness.",
            "No action.",
            "- [ ] None.",
            "- `app/integrity.py:39-63`",
        ),
    ),
    (
        205,
        Finding(
            "major",
            "GLiNER2 model load failure takes down the whole app",
            "`app/main.py:74-84` re-raises on `gliner2.load()` failure; the container exits even though `regex` is already constructed and would serve traffic.",
            "- **File:** `app/main.py`\n- **Lines:** `74-89`",
            "One transient load failure → container restart loop → SLO violation.",
            "Catch the failure, set `active = regex`, log a warning, continue.",
            "- [ ] Lifespan survives GLiNER2 load failure.\n- [ ] Warning logged per failure.",
            "- `app/main.py:60-89`",
        ),
    ),
    (
        206,
        Finding(
            "major",
            "use_pipeline=true silently falls back to legacy Redactor",
            "`app/main.py:107` only constructs the Pipeline when `active is not regex`. `app/api/redact.py:120-121` then checks `if body.use_pipeline and pipeline is not None:` and silently uses the legacy path otherwise.",
            "- **File:** `app/api/redact.py`\n- **Lines:** `120-121`",
            "User asked for the pipeline; got the legacy path; no error.",
            "Return 422 with a typed problem if `body.use_pipeline=true` and `state.pipeline is None`.",
            "- [ ] New 422 path.",
            "- `app/api/redact.py:120-141`\n- `app/main.py:106-116`",
        ),
    ),
    (
        207,
        Finding(
            "minor",
            "Idempotency/response cache silently skipped when Redis is down",
            "`app/main.py:119-124` downgrades `job_store=None`. `app/api/redact.py:87-110` short-circuits the cache lookups without a per-request log line.",
            "- **File:** `app/api/redact.py`, `app/main.py`\n- **Lines:** `redact.py:87-110`; `main.py:119-124`",
            "Operators can't tell the cache is off.",
            "Log once per process when `job_store is None`; per-request DEBUG log when an idempotency lookup is skipped.",
            "- [ ] Log lines present.",
            "- `app/main.py:119-124`\n- `app/api/redact.py:87-110`",
        ),
    ),
    (
        208,
        Finding(
            "major",
            "/v1/jobs counter leak on Redis write failure",
            "`app/api/jobs.py:77` calls `store.create(owner=api_key)` which increments the per-owner counter (`app/jobs/store.py:87-107`). A write-back failure leaves the slot stuck.",
            "- **File:** `app/api/jobs.py`, `app/jobs/store.py`\n- **Lines:** `jobs.py:77`; `store.py:87-107`",
            "Quota counter leaks; subsequent admissions are rejected until TTL.",
            "Wrap `store.create()` in try/except; on failure call `release_owner_count(client, KEY)` to roll back.",
            "- [ ] Counter never leaks.",
            "- `app/api/jobs.py:77-81`\n- `app/jobs/store.py:87-107, 192-204`",
        ),
    ),
    (
        209,
        Finding(
            "minor",
            "No metric when rate limit fails closed",
            "`/v1/redact` returning 503 due to Redis being unreachable is invisible at the metrics layer. Operators see the 503 in logs but no counter to alert on.",
            "- **File:** `app/observability/metrics.py`, `app/ratelimit.py`\n- **Lines:** `metrics.py:46-51`; `ratelimit.py:39-62`",
            "Hard to alert on rate-limit outages.",
            "Add `redax_rate_limit_unavailable_total` counter; increment in `app/ratelimit.py`.",
            "- [ ] Counter exposed at `/metrics`.",
            "- `app/observability/metrics.py`\n- `app/ratelimit.py`",
        ),
    ),
    (
        210,
        Finding(
            "minor",
            "Live HTTP smoke of all four surfaces not in CI",
            "`tests/integration/test_api_batch_stream_jobs.py` covers batch/stream/jobs via TestClient but doesn't boot `app.main:app` through the lifespan in CI.",
            "- **File:** `tests/integration/test_api_batch_stream_jobs.py`\n- **Lines:** n/a",
            "Lifespan-only behavior (e.g. GLiNER2 fallback, Redis-down grading) is uncovered at the HTTP layer.",
            "Add a `tests/smoke/` directory that boots `app.main:app` via TestClient and hits each route.",
            "- [ ] New smoke tests.",
            "- `tests/integration/test_api_batch_stream_jobs.py`",
        ),
    ),
    (
        211,
        Finding(
            "nit",
            "tests/fixtures/redactionbench/ is too small for regression signal",
            "6 documents across 3 categories (`emails`, `financial`, `operations`). Adequate for an approval snapshot; tiny for regression.",
            "- **File:** `tests/fixtures/redactionbench/`\n- **Lines:** n/a",
            "Score drift on a single document moves the corpus mean dramatically.",
            "Add `tests/fixtures/redactionbench/large/` with ≥30 documents spanning the 11 categories referenced by `CHANGELOG.md`.",
            "- [ ] Large fixture present.",
            "- `tests/fixtures/redactionbench/`",
        ),
    ),
    (
        212,
        Finding(
            "nit",
            "scripts/eval_detectors.py has redundant gliner2/fastino aliases",
            "`scripts/eval_detectors.py:46-49` treats `fastino` and `gliner2` as separate names but both instantiate `GLiNER2Detector()` (`fastino/gliner2-privacy-filter-PII-multi` *is* the GLiNER2 model).",
            "- **File:** `scripts/eval_detectors.py`\n- **Lines:** `46-49`",
            "Confusing alias.",
            "Either drop `fastino` or wire it to a different model.",
            "- [ ] One of the two; commit message explains.",
            "- `scripts/eval_detectors.py:37-55`",
        ),
    ),
    (
        213,
        Finding(
            "nit",
            "GLiNER2 detector mutates HF_HOME as a process-global",
            "`app/inference/gliner2.py:110` runs `os.environ.setdefault(\"HF_HOME\", str(self.model_cache))`. The same value is also passed via `cache_dir=` on line 122, so the env-var write is redundant.",
            "- **File:** `app/inference/gliner2.py`\n- **Lines:** `110`",
            "Two detectors with different caches race the env-var write.",
            "Drop the env-var setdefault; rely on `cache_dir=`.",
            "- [ ] Env var no longer mutated.",
            "- `app/inference/gliner2.py:100-127`",
        ),
    ),
    (
        214,
        Finding(
            "nit",
            "Stale __pycache__ from prior renames",
            "`app/redaction/stages/__pycache__/regex_gate.cpython-312.pyc` and `model_stage.cpython-312.pyc` exist from the rename to `gate.py` / `model.py`.",
            "- **File:** `app/redaction/stages/__pycache__/`\n- **Lines:** n/a",
            "Trivial.",
            "`find . -name __pycache__ -exec rm -rf {} +`.",
            "- [ ] Cleaned.",
            "- `app/redaction/stages/__pycache__/`",
        ),
    ),
    (
        215,
        Finding(
            "minor",
            "CHANGELOG claim about hoisted imports is false",
            "`CHANGELOG.md:13-52` says \"All lazy `from x import y` statements inside route handlers have been hoisted to module top.\" `app/ratelimit.py:57` still does `from app.logging import get_logger` inside the function body.",
            "- **File:** `CHANGELOG.md`, `app/ratelimit.py`\n- **Lines:** `CHANGELOG.md:13-52`; `ratelimit.py:57`",
            "AGENTS.md bans function-level imports; the CHANGELOG entry is wrong.",
            "Either move the import to the top of `app/ratelimit.py` or amend the CHANGELOG entry.",
            "- [ ] Either fix the code or fix the CHANGELOG.",
            "- `CHANGELOG.md`\n- `app/ratelimit.py:1-63`",
        ),
    ),
    (
        216,
        Finding(
            "minor",
            "Bump CHANGELOG version since 0.1.0",
            "`CHANGELOG.md:204` lists `[0.1.0] — 2026-09-05 (initial release)` and nothing since. The LICENSE + README + dead-code + bench changes since deserve a new section.",
            "- **File:** `CHANGELOG.md`\n- **Lines:** `204`",
            "Releases aren't tracked.",
            "Add `[0.1.1] — <date>` (or `[0.2.0]`) under the existing entries.",
            "- [ ] New version section present.",
            "- `CHANGELOG.md:200-220`",
        ),
    ),
    (
        217,
        Finding(
            "minor",
            "Verify CHANGELOG claims against current code",
            "`CHANGELOG.md` entries for `RateLimit takes state explicitly`, `run_job receives state as parameter`, `Module-level state singleton removed` describe behavior changes that were committed long before M11 #140–#145 and have not been re-checked against current code.",
            "- **File:** `CHANGELOG.md`\n- **Lines:** all",
            "Docs drift.",
            "Cross-check every claim against `app/state.py`, `app/ratelimit.py`, `app/api/jobs.py`, etc.; correct any that no longer hold.",
            "- [ ] Each CHANGELOG claim verified against current source.",
            "- `CHANGELOG.md`\n- `app/state.py`, `app/ratelimit.py`, `app/api/jobs.py`",
        ),
    ),
    (
        218,
        Finding(
            "major",
            "/v1/jobs returns 500 with misleading Internal Server Error when Redis is down",
            "Verified live:\n```\nPOST /v1/jobs → 500\n{\"type\":\"https://redax.ai/errors/internal\",\"title\":\"Internal Server Error\",\"status\":500,\"detail\":\"job store not initialized\",\"instance\":\"/v1/jobs\"}\n```\n`app/api/jobs.py:67-68` calls `internal_error(request, \"job store not initialized\")` for a known-dependency-down condition.",
            "- **File:** `app/api/jobs.py`, `app/errors.py`\n- **Lines:** `jobs.py:66-68`",
            "Operators see a generic 500 with `Internal Server Error` for a known-and-recoverable condition.",
            "Add a typed `job_store_unavailable` helper in `app/errors.py` (parallel to `queue_full`); return 503 with `type=https://redax.ai/errors/job-store-unavailable`.",
            "- [ ] Typed problem URL on the no-store path.",
            "- `app/api/jobs.py:65-87`\n- `app/errors.py:72-92`",
        ),
    ),
    (
        219,
        Finding(
            "minor",
            "app/redaction/__init__.py is missing",
            "`app/redaction/` has no `__init__.py`; sibling packages (`app/audit`, `app/bench`, `app/inference`) all re-export their public symbols.",
            "- **File:** `app/redaction/__init__.py` (missing)",
            "Asymmetric; `from app.redaction import …` discoverability is worse.",
            "Add `__init__.py` re-exporting `Redactor`, `RedactionResult`, `Pipeline`, `PipelineResult`, `Outcome`, `Gate`, `ModelStage`, `Breaker`, `OpenError`, `Policy`, `load_policy`, `relexicalize`.",
            "- [ ] `__init__.py` re-exports the public API.",
            "- `app/redaction/` directory\n- `app/audit/__init__.py` (reference)",
        ),
    ),
    (
        220,
        Finding(
            "minor",
            "app/jobs/__init__.py is empty (revisit)",
            "Confirmed zero-byte file. See #153 for the same finding with re-export guidance.",
            "- **File:** `app/jobs/__init__.py`\n- **Lines:** n/a",
            "Same as #153.",
            "Add one-line docstring + re-export `JobStore`, `JobRecord`, `release_owner_count`.",
            "- [ ] `__init__.py` re-exports the public API.",
            "- `app/jobs/__init__.py`",
        ),
    ),
    (
        221,
        Finding(
            "minor",
            "app/redaction/stages/__init__.py has only a docstring",
            "`app/redaction/stages/__init__.py` is a one-line \"Pipeline stage modules.\" comment. No re-exports.",
            "- **File:** `app/redaction/stages/__init__.py`",
            "Inconsistent with `app/bench/__init__.py` and `app/audit/__init__.py`.",
            "Either re-export the stage classes (`Gate`, `ModelStage`, `ConsensusConfig`, `fuse`, `from_regex_only`) or document the namespace-only convention.",
            "- [ ] Either re-exports or a docstring note.",
            "- `app/redaction/stages/__init__.py`",
        ),
    ),
    (
        222,
        Finding(
            "nit",
            "/v1/redact/stream response shape diverges from /v1/redact",
            "Verified live: stream chunks are `{text, spans}`; sync response adds `relex_map`, `used_pipeline`, `used_fallback`, `digest`. Asymmetric.",
            "- **File:** `app/api/stream.py`, `app/api/redact.py`\n- **Lines:** `stream.py:110-114`",
            "Stream consumers can't rely on the same shape.",
            "Either unify the per-chunk payload or document the asymmetry in `docs/api.md`.",
            "- [ ] One shape or a docs callout.",
            "- `app/api/stream.py:88-114`\n- `app/api/redact.py:39-48`\n- `docs/api.md`",
        ),
    ),
    (
        223,
        Finding(
            "nit",
            "app/redaction/stages/__init__.py lacks __all__",
            "`app/redaction/stages/__init__.py` doesn't list `__all__`.",
            "- **File:** `app/redaction/stages/__init__.py`",
            "Star-imports pull nothing.",
            "If re-exporting (per #221), add `__all__ = [...]`.",
            "- [ ] `__all__` aligned with re-exports.",
            "- `app/redaction/stages/__init__.py`",
        ),
    ),
    (
        224,
        Finding(
            "nit",
            "Document CHANGELOG entry for the M11 audit report itself",
            "The M11 audit produced 81 findings; the corresponding CHANGELOG entry should mention the audit pass so readers can find them via `audit/M11` label.",
            "- **File:** `CHANGELOG.md`\n- **Lines:** `13-100`",
            "Audit discoverability.",
            "Add a `### Documentation` bullet pointing at the GitHub issues labelled `audit/M11`.",
            "- [ ] Cross-reference present.",
            "- `CHANGELOG.md`",
        ),
    ),
    (
        225,
        Finding(
            "major",
            "CHANGELOG 0.1.0+ lacks an item describing the audit pass itself",
            "Beyond the per-finding CHANGELOG entries, the M11 audit pass deserves a single `### Documentation` line so the release notes mention the audit.",
            "- **File:** `CHANGELOG.md`\n- **Lines:** all",
            "Same as #224; major because every prior release had a documentation entry.",
            "Add a `### Documentation` bullet summarising the audit findings list and linking to the `audit/M11` GitHub issues.",
            "- [ ] Bullet present.",
            "- `CHANGELOG.md`",
        ),
    ),
    (
        226,
        Finding(
            "nit",
            "Document Finding report issue template in AGENTS.md",
            "New `.github/ISSUE_TEMPLATE/finding.md` exists but `AGENTS.md` doesn't mention it.",
            "- **File:** `AGENTS.md`\n- **Lines:** all",
            "New convention undocumented.",
            "Add a one-line reference to the template.",
            "- [ ] AGENTS.md mentions the template.",
            "- `AGENTS.md`\n- `.github/ISSUE_TEMPLATE/finding.md`",
        ),
    ),
    (
        227,
        Finding(
            "nit",
            "Push the M11 audit issues label color",
            "The `audit/M11` label color `#ededed` matches `audit/M10` but is hard to read on a white background.",
            "- **File:** repo label config",
            "Cosmetic.",
            "Either pick a darker color (e.g. `#7057ff`) or add a description emoji.",
            "- [ ] Label color updated.",
            "- GitHub repo labels",
        ),
    ),
]


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--dry-run":
        for item_id, finding in FINDINGS:
            print(f"[{finding.severity}] M11 #{item_id}: {finding.title}")
        return 0

    failures: list[int] = []
    for item_id, finding in FINDINGS:
        title = f"[{finding.severity}] M11 #{item_id}: {finding.title}"
        body_file = Path(f"/tmp/redax-m11-{item_id}.md")
        body_file.write_text(finding.body(), encoding="utf-8")
        cmd = [
            "gh",
            "issue",
            "create",
            "--title",
            title,
            "--body-file",
            str(body_file),
            "--label",
            "audit/M11",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        body_file.unlink(missing_ok=True)
        if result.returncode != 0:
            failures.append(item_id)
            print(f"FAIL  M11 #{item_id}: {result.stderr.strip()}", file=sys.stderr)
        else:
            url = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "(no url)"
            print(f"OK    M11 #{item_id}: {url}")
    if failures:
        print(f"\n{len(failures)} failures: {failures}", file=sys.stderr)
        return 1
    print(f"\nCreated {len(FINDINGS)} issues.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
