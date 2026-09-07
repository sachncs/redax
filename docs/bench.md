# RedactionBench benchmark harness

Redax ships a faithful implementation of the [RedactionBench](https://arxiv.org/html/2606.18782v1) metric and benchmark runner
(Brynjolfsson et al. 2026, arXiv:2606.18782). This document explains what
the metric computes, how the harness is structured, and how to extend it
with a new detector.

## Why a new metric

Traditional PII benchmarks report strict F1 over (start, end, type)
triples. That penalises a model that produces *almost-right* spans (e.g.
`(415) 555-2671` vs `415-555-2671`) and conflates surface-formatting
choices with privacy. RedactionBench introduces three ideas that this
harness supports:

1. **Mandatory vs. contextual spans.** A *mandatory* entity is always
   unsafe; a *contextual* entity is unsafe only under additional context
   (e.g. a name on a public webpage vs. a name on an internal
   memo). Following Nissenbaum's contextual-integrity framework, the
   metric treats them differently.
2. **Character-level R-Score.** Coverage is computed per-character, so a
   prediction that overlaps an entity partially still receives partial
   credit. The score is invariant to span length and penalises sloppy
   boundaries more than missing optional entities.
3. **Combinator-aware fusion.** Punctuation between labeled spans (dots
   in `127.0.0.1`, spaces after `)` in `(415) 555-2671`, matched
   brackets) is detected by Algorithm 1 of the paper and used to fuse
   adjacent spans into single entities.

## What R-Score computes

For each entity (a *mandatory* or *contextual* group of spans produced
by Algorithm 1 + Algorithm 2) and each false-positive character run,
R-Score accumulates `(n, d)` pairs:

| Term | `(n, d)` | Notes |
| --- | --- | --- |
| Mandatory entity `r` | `(mean over s in r of |s ∩ P| / |s|, 1)` | covered in proportion |
| Contextual entity `y`, active subset non-empty, document has mandatory spans | `(0, 1 − mean coverage)` | attempted redactions are penalised, no reward |
| Contextual entity `y`, active subset non-empty, document has no mandatory spans | `(mean coverage, 1)` | exception from §3.3: optional entities become positive contributors |
| Contextual entity, active subset empty | no term emitted | un-attempted entities do not penalise |
| False positive (default) | `(0, 1)` | over-redaction of one character |
| False positive covering an entire gap ≥ 3 chars | `(0, 2)` | penalises "double covering" both sides of an entity break |

`R = Σ n / Σ d`, with `d = 0` mapped to `R = 0` for empty documents.

### Worked example (paper Appendix H)

The repository's fixture corpus contains a worked example from the paper
(text `Vehicle: "5N1AT2MK4FC824170" "2015 Nissan Rogue" plate= 321ABC`)
annotated as:

* red: VIN `[10, 27)`, plate `[56, 62)`
* yellow: open quote `[9, 10)`, close quote `[27, 28)`, `"2015 Nissan Rogue"` `[29, 48)`

The expected scores per prediction input are locked in
`tests/unit/test_bench_rscore.py::test_worked_example_*`:

| Prediction | R-Score |
| --- | --- |
| All red + close quote + `"2015 Nissan Rogue"` + 321ABC (perfect) | 1.0 |
| No predictions | 0.0 |
| VIN + 321ABC (mandatory only) | 1.0 |
| All text (over-redaction) | 2/7 ≈ 0.286 |
| VIN only | 0.5 |
| Open quote `[9, 10)` only (connector-marker singleton) | 0.0 |
| Close quote `[27, 28)` only (pulls in `"2015 Nissan Rogue"` via Punct) | 0.0 |

## Package layout

```
app/bench/
  __init__.py          re-exports the public surface
  corpus.py            Document, Category, Structure, load_corpus
  annotation.py        LabelledSpan, Annotation, load_annotations
  combinators.py       Algorithm 1: build_connector_structure
  fusion.py            Algorithm 2: selected_contextual_spans, fused_entity_groups
  rscore.py            score_document, rscore, RDocument, RScoreReport
  disagreement.py      UnitRating, krippendorff_alpha, per_unit_type_*,
                       wilson_interval, spearman_rank
```

The disagreement module implements the user-study analyses
(Krippendorff's α, per-unit-type mean pairwise disagreement `D_t`,
Wilson's 95 % CI, Spearman's ρ) so future redactions of the user-study
data can be scored without adding a new dependency.

## Corpus format

Documents live in `documents.jsonl`; annotations in `annotations.jsonl`:

```json
{"id": "vehicle_record", "text": "Vehicle: \"5N1AT2MK4FC824170\" ...", "category": "operations", "genre": "vehicle_record", "source": "synthetic"}
```

```json
{"doc_id": "vehicle_record", "spans": [
  {"start": 9, "end": 10, "category": "contextual"},
  {"start": 10, "end": 27, "category": "mandatory"},
  {"start": 27, "end": 28, "category": "contextual"},
  {"start": 29, "end": 48, "category": "contextual"},
  {"start": 56, "end": 62, "category": "mandatory"}
]}
```

Offsets are half-open `[start, end)` character indices. Multi-line spans
are split at `\n` per §3.2 at load time. The 11 categories and their
unstructured/structured classification mirror Tables 4–6 of the paper.

## Running the harness

```bash
python scripts/run_bench.py \
  --corpus tests/fixtures/redactionbench \
  --detector regex \
  --output /tmp/rb.json
```

The JSON report contains per-document `(r_score, n, d, skipped_contextual,
n_mandatory, n_contextual, n_fp)` plus corpus mean, percentiles (P20, P50,
mean), and per-category summaries.

An end-to-end approval-test confirms the snapshot at
`tests/integration/test_bench_approved.py`.

## Adding a new detector

Detectors live in `app/inference/`. To wire one into the benchmark:

1. Implement `async detect(text: str, entity_types: list[str]) -> list[Span]`
   on your detector class.
2. Add it to `scripts/run_bench.py:_build_detector`'s else-branch.
3. Update `scripts/run_bench.py` to map the detector's `Span.type` to
   mandatory vs. contextual (the default maps every detector span to
   `MANDATORY`, which is what the benchmark expects for raw
   span-classification models).
4. Add a fixture and a `predictions_*.jsonl` so the score can be
   verified by hand.

## Disagreement / user-study metrics

`app/bench/disagreement.py` exposes:

```python
from app.bench.disagreement import (
    UnitRating,
    krippendorff_alpha,
    per_unit_type_alpha,
    per_unit_type_disagreement,
    pairwise_disagreement,
    wilson_interval,
    spearman_rank,
    disagreement_report,
)
```

The paper's worked example (Tables 12–14, Appendix H) is locked in by
`tests/unit/test_bench_disagreement.py::_worked_example_ratings`,
which encodes the four-user ratings on the 10-unit vehicle-record window
and reproduces:

* `D_r = 0.333`, `D_y = 0.667`, `D_g = 0.133`
* `α_global = 0.286`
* `α_red = 0.222`, `α_yellow = -0.222`, `α_gap (combined) = 0.297`

## Out of scope (and intentionally not implemented)

* The full 200-document RedactionBench corpus. Re-licensing the source
  documents is not feasible; the fixture corpus is a deliberately small
  synthetic set that exercises every code path of the metric. Wiring a
  larger corpus is just a matter of providing more `documents.jsonl`
  entries.
* The 85-user annotator study itself. The disagreement-metric code is
  in place so the study data can be scored later.
* Frontier-LLM tool-calling harnesses. The runner integrates with
  whatever detector the user supplies; bring your own tool-calling glue
  if you want to score GPT/Claude/GLM against this metric.

## References

* Brynjolfsson, Jayakrishnan, Sali, Purwar, Aggarwal. *RedactionBench:
  A Benchmark for PII Redaction in the Era of LLMs.* arXiv:2606.18782,
  June 2026.
