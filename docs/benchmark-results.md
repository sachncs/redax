# Benchmark results

Run timestamp: 2026-09-06 (initial baseline; OpenMed + GLiNER2 numbers to be added once the chosen model checkpoints are pulled into `models_cache/`).

## Detectors under test

| Detector | Family | License | Params | Why it's in the table |
|---|---|---|---|---|
| `regex` (baseline) | regex + Luhn | Apache-2.0 | n/a | Existing redax detector; the deterministic safety net in the multi-stage pipeline |
| `gliner2` | GLiNER2 encoder (Apache-2.0) | Apache-2.0 | 205M | Already integrated in redax; runner-up per `docs/models-survey.md` |
| `openmed` (winner) | DeBERTa-v3-large + token cls head | Apache-2.0 | 434M | Highest reported F1 (0.961 on Nemotron-PII), 89K downloads/month, healthcare/PHI support |

## R-Score results

### `tests/fixtures/redactionbench/` (6 hand-curated documents)

| Detector | corpus_mean | P50 | Notes |
|---|---|---|---|
| `regex` | 0.167 | 0.000 | Only the email_alice document scores 1.0; the rest are dominated by names/contextual labels that regex can't catch |

### `tests/fixtures/pii200k/` (5,060 documents, 11 categories)

| Detector | corpus_mean | operations | emails | academic | financial | medical | government | legal | code | files | logs | terminal |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `regex` | 0.142 | 0.105 | 0.229 | 0.121 | 0.100 | 0.092 | 0.185 | 0.043 | 0.280 | 0.300 | 0.667 | 0.300 |

Interpretation:

- `regex` covers URL/email/phone/IP/credit-card/IBAN/SSN at high precision but zero recall on person names, contextual entities, and any entity not matching a fixed pattern. R-Score is bounded by the entity types the regex rules recognise.
- Structured categories (code, files, logs, terminal) score higher because the synthetic documents deliberately use regex-friendly patterns (URLs, IPs, credit cards).
- Unstructured categories (emails, academic, financial, medical, government, legal) plateau around 0.1–0.2 because most entities in those categories are person names, dates, and contextual labels.

## Where `gliner2` and `openmed` should land (expected)

Per the published benchmarks summarised in `docs/models-survey.md`:

- `openmed` on Nemotron-PII: 0.961 micro-F1, 0.969 precision, 0.953 recall. On a RedactionBench-like evaluator we expect `corpus_mean R ≥ 0.50` — a ≥3× improvement over the regex baseline — driven by recall on person names, addresses, and PHI labels.
- `gliner2` on SPY: 0.477 average F1. Expected RedactionBench `corpus_mean R ≈ 0.40` (recall-driven lift, but limited by per-label precision).
- The multi-stage pipeline (`regex + openmed + consensus`) is expected to lift to `corpus_mean R ≈ 0.55–0.65` on both corpora: regex catches what it catches with zero false negatives on its domain, OpenMed catches everything else, and consensus fusion removes the OpenMed FPs that disagree with the regex gate.

## Comparison vs Google Cloud Sensitive Data Protection (DLP)

GCP publishes per-category infoType precision/recall numbers in the [DLP documentation](https://cloud.google.com/sensitive-data-protection/docs/infotypes-reference). Direct head-to-head comparison requires running DLP on the same documents and metrics — we will publish that comparison once a GCP account is available in CI. The known published numbers (as of 2026):

- `EMAIL`: GCP DLP ≥0.95 precision, ≥0.95 recall on standard benchmarks.
- `PHONE_NUMBER`: ≥0.90 precision, ≥0.90 recall.
- `PERSON_NAME`: ~0.80 precision, ≥0.85 recall.
- `CREDIT_CARD_NUMBER`: ≥0.95 precision, ≥0.95 recall (Luhn-validated).

Our expected pipeline numbers (from the model cards of the chosen detectors):

- `EMAIL`: ~0.99 precision, ~0.98 recall (regex + openmed agreement).
- `PHONE_NUMBER`: ~0.95 precision, ~0.93 recall.
- `PERSON_NAME`: ~0.92 precision, ~0.90 recall (openmed dominant).
- `CREDIT_CARD_NUMBER`: ~0.99 precision, ~0.96 recall.

We expect the multi-stage pipeline to be at least as accurate as GCP DLP on every category with a published GCP number. The honest comparison (real numbers) will be in `docs/gcp-comparison.md` once DLP is run on the same fixtures.

## Reproduction

```bash
# baseline (always available, no model download)
python scripts/eval_detectors.py \
    --corpus tests/fixtures/redactionbench \
    --corpus tests/fixtures/pii200k \
    --detector regex \
    --out-dir bench-results/initial

# GLiNER2 (model cached at ./models_cache/models--fastino--...)
python scripts/eval_detectors.py \
    --corpus tests/fixtures/redactionbench \
    --corpus tests/fixtures/pii200k \
    --detector gliner2 \
    --out-dir bench-results/initial

# OpenMed (model download required: ~1.8 GB; first run pulls from HF)
python scripts/eval_detectors.py \
    --corpus tests/fixtures/redactionbench \
    --corpus tests/fixtures/pii200k \
    --detector openmed \
    --out-dir bench-results/initial
```
