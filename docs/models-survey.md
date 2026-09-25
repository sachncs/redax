# Model support and provenance

Redax currently ships one model-backed detector: `fastino/gliner2-privacy-filter-PII-multi`.
The runtime loads it locally from the configured cache with
`local_files_only=True`; it does not call a hosted inference API on the
request path.

## Supported model

| Field | Value |
|---|---|
| Model | `fastino/gliner2-privacy-filter-PII-multi` |
| Revision | `c153999da5f4c509df4322b0c6a1baf3d2c284d7` |
| Snapshot digest | `6c8acb9f91f7de13bec075211229981df09aa2a265f0d2bd6dc6a313cebdfeca` |
| Runtime | `gliner2` with local Torch dependencies |
| Default device | CPU |
| Mode | Beta; regex-only is the explicit stable fallback mode |
| Download behavior | Build/deployment step only; request inference is local-only |
| Label mapping | Model labels are normalized to uppercase Redax span types at the adapter boundary |

`MODEL_HASHES.txt` is the machine-readable integrity manifest. Run
`python scripts/download_models.py --model ... --revision ...` during a
deployment or image build; an unknown or changed snapshot fails verification.
The container build performs this verification before the image is usable.

## Runtime behavior

- `REDAX_DETECTOR=gliner2` is the default. In production, startup fails if
  the pinned local model cannot load; it does not silently downgrade to regex.
- `REDAX_DETECTOR=regex` is an explicit regex-only mode. It covers structured
  identifiers and does not claim comprehensive contextual PII detection.
- The staged pipeline uses regex gating, the local model, deterministic span
  fusion, typed replacement, and an explicit regex fallback when the model
  circuit breaker is open.
- Model results are version-dependent. Do not claim byte-for-byte stability
  across model, Torch, tokenizer, or hardware changes; pin and record those
  inputs when publishing benchmarks.

## Known limitations

The model card's taxonomy and reported scores are not a guarantee for a
particular workload. Redax does not currently provide an independent claim of
complete multilingual, clinical, OCR, image, or secret detection. Validate
the entity types and false-positive/false-negative profile against synthetic
fixtures representative of your deployment.

## Candidates not shipped

OpenMed, Piiranha, NVIDIA GLiNER variants, and other models may appear in
historical benchmark or research notes, but they are not supported runtime
backends in this release. They must not be described as available detectors,
downloaded by the production Dockerfile, or used as evidence for the current
runtime contract until they have an adapter, license review, pinned revision,
integrity entry, reproducible benchmark, and CI coverage.

## Reproducing model evidence

The benchmark harness emits machine-readable JSON. Record the Redax commit,
model revision, snapshot digest, Python/Torch versions, hardware, corpus
revision, thresholds, and timestamp with every published run. See
[`docs/bench.md`](bench.md) and [`docs/benchmark-results.md`](benchmark-results.md)
for the current methodology and limitations.
