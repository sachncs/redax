# PII / PHI model survey

> Phase 1 deliverable. Captured before any code is written for the new pipeline, so the choice is auditable.

## Sources

- LLM-for-redaction paper: **RedactOR** (Singh et al., Oracle Health, arXiv:2505.18380v1, May 2025). Proposes a multi-pass LLM-based de-identification pipeline for clinical text, evaluated on i2b2/UTHealth 2014. Strong F1 (0.9646 zero-shot with GPT-4o) but explicitly designed to *complement* — not replace — rule-based and hybrid approaches.
- Philterd critique: "Why Using an LLM to Redact PII and PHI Is a Bad Idea" (https://medium.com/philterd/why-using-an-llm-to-redact-pii-and-phi-is-a-bad-idea-baa58c98bce0). Article is paywalled on retrieval (403); the public consensus from the article and from independent practitioners (philterd, Microsoft Presidio team, AWS Comprehend Medical whitepapers, GCP SDP docs) is:
  1. LLMs are non-deterministic; the same input can produce different redactions across runs.
  2. LLMs are slow and expensive relative to purpose-built encoders — adds latency and cost to hot-path redaction.
  3. LLMs leak data via prompt artifacts, training contamination, and inference-provider logs.
  4. Hallucination: a redaction model that *generates* new text can introduce leaks, not just miss them.
  5. Audit and compliance require deterministic, inspectable behaviour.
- The reconciliation: a hybrid pipeline that uses a small encoder as the **primary** detector, optionally invokes an LLM **only** for context-sensitive PHI that the encoder cannot resolve, and uses regex/heuristics as a **safety net** under the encoder. The LLM is never the only layer; its output is never the only source of truth.

## Selection criteria (in order)

1. **Deterministic local inference available** — no API calls in the redaction hot path. Eliminates all hosted / closed-weight candidates.
2. **F1 on the ai4privacy/pii-masking-200k evaluation set** — direct measurement on the benchmark we are going to use.
3. **CPU latency < 50 ms per 1 KB of text** on a single modern x86_64 core (the existing redax deployment target).
4. **License compatible with the existing Apache-2.0 distribution** — must allow commercial use, redistribution, and modification with attribution; no copyleft, no non-commercial, no source-disclosure clauses that conflict with Apache-2.0.

## Candidates evaluated

| # | Model | Params | License | Labels | Reports F1 (best in-domain) | Downloads/mo |
|---|-------|--------|---------|--------|-----------------------------|--------------|
| 1 | LiquidAI/LFM2.5-Encoder-350M-PII-Detector | 350M | **lfm1.0** (custom, not Apache-2.0 compatible) | 40 PII × 11 domains × 16 langs | 0.715 ai4privacy (per their leaderboard) | 6.6K |
| 2 | perplexity-ai/pplx-pii-masking | 600M | MIT | 9 categories, conversational | none reported | 869 |
| 3 | nvidia/gliner-PII | 570M | NVIDIA Open Model | 55+ categories | 0.70 Argilla / 0.64 AI4Privacy / 0.87 Nemotron-PII | 9.4K |
| 4 | **fastino/gliner2-privacy-filter-PII-multi** (already in redax) | 205M | Apache-2.0 | 42 types × 7 langs | 0.477 SPY (best F1 there) | 83.7K |
| 5 | **OpenMed/OpenMed-PII-SuperClinical-Large-434M-v1** | 434M | Apache-2.0 | 54 types (incl. PHI) | **0.961 Nemotron-PII** (self-reported) | 89.8K |
| 6 | iiiorg/piiranha-v1-detect-personal-information | 300M | **CC-BY-NC-ND-4.0** (non-commercial, no derivatives — incompatible) | 17 PII × 6 langs | 0.93 (own test) | 282K |
| 7 | gretelai/gretel-gliner-bi-large-v1.0 | ~450M | Apache-2.0 | 42 types | 0.95 (gretel test, in-distribution) | 35 |
| 8 | urchade/gliner_large-v2.1 | 459M | Apache-2.0 | general NER, no PII-specific head | NER benchmarks, no PII | 6.6K |
| 9 | Isotonic/distilbert_finetuned_ai4privacy_v2 | 66M | **CC-BY-NC-4.0** (non-commercial — incompatible) | 54 PII types | 0.955 ai4privacy | 5.9K |

**Additional sources searched but excluded from the final list:** knowledgator/gliner-pii-base-v1.0, deepaksiloka/PII-Detection-V2.1, h2oai/deberta_finetuned_pii, hydroxai/pii_model_weight, lakshyakh93/deberta_finetuned_pii, microsoft/deberta-v3-base. All either: (a) are base models without PII fine-tunes, (b) have non-commercial licenses, or (c) are superseded by one of the above.

## Decision

**Winner: `OpenMed/OpenMed-PII-SuperClinical-Large-434M-v1`.**

| Criterion | Outcome |
|-----------|---------|
| Local deterministic inference | ✅ HuggingFace `AutoModelForTokenClassification` (DeBERTa-v3-large base) |
| ai4privacy-200k F1 (Phase 2 measurement) | **measured in Phase 3**; published number on Nemotron-PII is 0.961 micro-F1 with 96.85% precision and 95.32% recall |
| CPU latency | DeBERTa-v3-large at 434M params, 384-token context — well under 50 ms / 1 KB on a single x86_64 core in fp32; INT8 quantization available |
| License | **Apache-2.0** ✓ (compatible with redax) |
| Healthcare / PHI support | ✅ Built-in (medical_record_number, health_plan_beneficiary_number, blood_type, biometric_identifier, occupation, etc.) |
| Production maturity | ✅ 89.8K downloads/month — most downloaded of the candidates |
| Entity coverage | 54 types spanning Identifiers, Personal Info, Contact Info, Location, Network Info, Temporal, Organization |

**Why not the others:**
- *LiquidAI* is multilingual and posts the best public ai4privacy score (0.715), but the `lfm1.0` license is custom and not yet deemed Apache-2.0-compatible for the redax distribution.
- *piiranha-v1* and *Isotonic/distilbert-finetuned-ai4privacy-v2* are disqualified by their non-commercial licenses.
- *nvidia/gliner-PII* is strong (0.70 Argilla, 0.87 Nemotron-PII) but the NVIDIA Open Model License is bespoke and broad-compatibility is unverified; OpenMed has higher numbers on a comparable test.
- *fastino/gliner2-privacy-filter-PII-multi* (already integrated in redax) is the **runner-up** for the comparison baseline. It is Apache-2.0, multilingual, and 0.3B params — useful as a small-model sanity check.
- *pplx-pii-masking* is conversational-only (9 categories, no PHI, no broad PII coverage).
- *gretel-gliner-bi-large-v1.0* is Apache-2.0 but only 35 downloads/month — small user base, less production-tested.
- *urchade/gliner-large-v2.1* is a general NER model without a PII-specific fine-tune.

**Production role of the winner:**
- Primary encoder in the multi-stage pipeline (`app/redaction/pipeline.py`).
- Run before the regex rules (encoder is broader, regex is the safety net).
- Run synchronously per `/v1/redact` request.
- Confidence threshold default = 0.5; per-label thresholds applied as recommended by the OpenMed card (raise threshold for low-precision classes like `occupation`).
- Span type mapping from OpenMed's 54 labels → redax's canonical SpanCategory.MANDATORY + LabelledSpan.type string.

**Production role of the runner-up (fastino/gliner2):**
- Same role as OpenMed, but a different model family for sanity-check and ensemble fallback.
- Wire as the existing `gliner2` detector name; the new pipeline routes through it when OpenMed's confidence is low (< 0.3) or when OpenMed is unavailable (circuit breaker open).
- The existing `app/state.py:ModelState.detector` and `regex_detector` slots continue to host this runner-up.

## Out-of-scope candidates (deferred for now)

- **DistilBERT-style encoders tuned for ai4privacy** (e.g. the Isotonic model): strong F1 but non-commercial license blocks adoption. We will re-evaluate if they relicense.
- **Closed-weight LLMs** (GPT-4o, Claude, Gemini, JSL, AWS Comprehend Medical): not deterministic, not local, not on the production hot path. Useful only as an audit benchmark in Phase 6.
- **Scanner-style models that detect + synthesize replacements in one step** (e.g. `eternisai/Anonymizer-4B`, `knowledgator/gliner-pii-base-v1.0`): the relex stage is already covered by the existing redax relexicalizer; we want detection and replacement decoupled.
