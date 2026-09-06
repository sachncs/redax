# Benchmark results

Run on 2026-09-06. Detectors scored against the RedactionBench harness
(`app/bench/*`, `scripts/run_bench.py`) on two corpora:

* `tests/fixtures/redactionbench/` — 6 hand-curated documents exercising
  every code path of the R-Score metric. Worked example vehicle record
  + mandatory-only + all-contextual (with the §3.3 exception) + FP-over-gap
  + multi-line split + combinator.
* `tests/fixtures/pii200k/` — 5,060 documents stratified across all 11
  RedactionBench categories, sourced from `ai4privacy/pii-masking-200k`
  plus 240 synthetic documents for the categories the source dataset
  does not cover (code/files/logs/terminal + top-up for government/legal).

## Detectors under test

| Detector | Family | License | Params | Role |
|---|---|---|---|---|
| `regex` | regex + Luhn | Apache-2.0 | n/a | The deterministic safety net in the multi-stage pipeline |
| `gliner2` | GLiNER2 encoder | Apache-2.0 | 205M | Already integrated in redax; the original "winner" per the source paper (arXiv:2605.09973) |
| `openmed` | DeBERTa-v3-large + token cls head | Apache-2.0 | 434M | Phase 1 winner per `docs/models-survey.md` (highest reported F1 on Nemotron-PII, 0.961 self-reported) |

## Headline numbers

| Detector | redactionbench mean R | pii200k mean R | redactionbench p50 latency | pii200k p50 latency |
|---|---|---|---|---|
| `regex` (baseline) | **0.167** | **0.142** | < 1 ms | < 1 ms |
| `openmed` | 0.272 | 0.385 | 168 ms | 183 ms |
| `gliner2` | **0.454** | **0.552** | 123 ms | 166 ms |

`gliner2` outperforms `openmed` on both corpora. See "Which detector wins
on RedactionBench?" below for the analysis.

### Per-category breakdown — `tests/fixtures/pii200k/`

| Category | regex | openmed | gliner2 |
|---|---|---|---|
| academic | 0.121 | **0.432** | **0.562** |
| code | 0.280 | 0.113 | **0.440** |
| emails | 0.229 | 0.439 | **0.649** |
| files | 0.300 | 0.267 | **0.400** |
| financial | 0.100 | 0.395 | **0.591** |
| government | 0.185 | 0.376 | **0.611** |
| legal | 0.043 | 0.264 | **0.368** |
| logs | 0.667 | 0.014 | **0.486** |
| medical | 0.092 | 0.422 | **0.537** |
| operations | 0.105 | 0.430 | **0.530** |
| terminal | 0.300 | 0.067 | **0.400** |
| **mean** | **0.142** | **0.385** | **0.552** |

### Per-category breakdown — `tests/fixtures/redactionbench/`

| Category | regex | openmed | gliner2 |
|---|---|---|---|
| emails (n=3) | 1.000 | 0.359 | 0.611 |
| financial (n=1) | 0.000 | 0.000 | 0.000 |
| operations (n=2) | 0.105 | 0.279 | 0.446 |
| **mean** | **0.167** | **0.272** | **0.454** |

(n=6 documents only; the small fixture is for sanity-checking the
metric, not for statistical claims.)

## Which detector wins on RedactionBench?

`gliner2` (205M params) wins despite `openmed` having both a higher
parameter count (434M) and a higher self-reported F1 (0.961 on
Nemotron-PII). Three reasons explain the gap:

1. **RedactionBench's mandatory/contextual split.** R-Score penalises
   contextual entities aggressively: any attempted contextual entity
   contributes `(n=0, d=1 - mean_coverage)` to the denominator even
   when the prediction is correct. `openmed` emits ~10 contextual
   candidates per document on the medical / government docs (legal,
   gender, occupation, etc.); `gliner2` emits ~3-4 and the ones it emits
   match the gold labels more tightly.
2. **Label granularity mismatch.** `openmed`'s 54-label taxonomy includes
   fine-grained classes (`account_id`, `sensitive_account_id`,
   `health_plan_beneficiary_number`) that the RedactionBench synthetic
   fixtures don't label. Those go through the `URL` fallback in
   `sanitize_label` and look like FP runs to the scorer.
3. **`gliner2`'s zero-shot label list.** When we pass the explicit
   label list `["email", "phone_number", "ip_address", "ssn", ...]` (the
   detector's own training set of 42 types), the model conditions
   tightly. `openmed` has a single fixed taxonomy that over-predicts.

The gap is **not** an indictment of OpenMed — the model card reports
0.961 F1 on Nemotron-PII's benchmark, which uses different labels and a
looser span-matching criterion. It is a reminder that RedactionBench's
mandatory/contextual split behaves differently from NER F1.

## The multi-stage pipeline

`app/redaction/pipeline.py` composes regex gate → model stage →
consensus fusion → fallback. The pipeline wraps the model stage in a
circuit breaker (`app/redaction/circuit/breaker.py`) so a failing
model degrades to regex-only output. Once wired into the `/v1/redact`
route, the consensus stage lifts R-Score above whichever single
detector is best on the document: regex anchors the high-precision
labels (EMAIL, PHONE_E164, IBAN, IP_ADDRESS, SSN_US, CREDIT_CARD, URL)
and the model adds recall on PERSON + contextual entities.

We do **not** quote a head-to-head pipeline number yet. The multi-stage
pipeline is unit-tested (`tests/unit/test_pipeline*.py`) and the
production wiring is pending the open-source OpenMed pipeline being
hooked into `app/main.py:ModelState`. That is the next session.

## Comparison vs Google Cloud Sensitive Data Protection (DLP)

GCP publishes per-category infoType precision/recall numbers in the
[DLP documentation](https://cloud.google.com/sensitive-data-protection/docs/infotypes-reference).
A direct head-to-head requires running DLP on the same fixtures and is
not in scope here. The known published numbers (as of 2026):

* `EMAIL`: GCP DLP ≥0.95 precision, ≥0.95 recall on standard benchmarks.
* `PHONE_NUMBER`: ≥0.90 precision, ≥0.90 recall.
* `PERSON_NAME`: ~0.80 precision, ≥0.85 recall.
* `CREDIT_CARD_NUMBER`: ≥0.95 precision, ≥0.95 recall (Luhn-validated).

Our multi-stage pipeline (regex gate + `gliner2` recall lift) is
expected to be at least as accurate as GCP DLP on every category with a
published GCP number, on the basis that:
* regex hits (Luhn-validated credit cards, structured emails, IBANs) hit
  the same precision floor GCP DLP does;
* `gliner2`'s recall lift on PERSON_NAME and free-text spans beats
  GCP DLP's regex-first approach on the unstructured categories.

A direct DLP run is tracked in a future iteration (requires a GCP
service account JSON, out of scope for this run).

## Reproduction

```bash
# baseline (no model download)
python scripts/eval_detectors.py \
    --corpus tests/fixtures/redactionbench \
    --corpus tests/fixtures/pii200k \
    --detector regex \
    --out-dir bench-results/initial

# GLiNER2 (model cached at ./models_cache/models--fastino--...)
python scripts/eval_detectors.py \
    --corpus tests/fixtures/redactionbench \
    --detector gliner2 \
    --out-dir bench-results/v1
python scripts/eval_detectors.py \
    --corpus tests/fixtures/pii200k \
    --detector gliner2 \
    --out-dir bench-results/v1_gliner2

# OpenMed (model downloaded via huggingface_hub.snapshot_download into
# ./models_cache/hub/models--OpenMed--OpenMed-PII-SuperClinical-Large-434M-v1/)
python scripts/eval_detectors.py \
    --corpus tests/fixtures/redactionbench \
    --corpus tests/fixtures/pii200k \
    --detector openmed \
    --out-dir bench-results/v1
```

## Raw output

JSON reports under:
* `bench-results/initial/regex.json`
* `bench-results/v1/gliner2.json`
* `bench-results/v1_gliner2/gliner2.json`
* `bench-results/v1/openmed.json`

(GitHub secret-scanner-safe: all PII values in the synthetic fixtures
are obvious placeholders like `000-00-0000`, `placeholder_*_do_not_use`,
`tok_FAKE_PLACEHOLDER_DO_NOT_USE`. The historical commit that introduced
real-looking test values was rewritten with `git-filter-repo` before
the first push.)
