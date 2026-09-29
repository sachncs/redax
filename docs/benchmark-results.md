# Benchmark results

The checked-in [`regex-local-baseline.json`](benchmarks/regex-local-baseline.json)
is a machine-readable local measurement artifact. It records the commit,
runtime, platform, workload, and percentiles, but is not a production SLA or
capacity claim. Generate a new artifact with:

```bash
python scripts/bench.py --output docs/benchmarks/regex-local-baseline.json
```

The checked-in [`regex-api-local-baseline.json`](benchmarks/regex-api-local-baseline.json)
is a separate HTTP measurement: 100 regex-mode API requests at concurrency 10
recorded 100 successful responses, 441.33 requests/second, p50 16.206 ms,
p95 33.187 ms, and p99 34.973 ms on the recorded Python 3.13/macOS host.
It is exploratory local evidence, not a production capacity limit. Generate a
new API artifact against a running server with:

```bash
python scripts/load_bench.py --requests 100 --concurrency 10 \
  --output docs/benchmarks/regex-api-local-baseline.json
```

Earlier working-tree snapshots contained exploratory comparisons, but their
raw result artifacts, model provenance, and reproducible environment were not
part of the release contract.

## Current supported detector set

| Detector | Status | Reproducible command |
|---|---|---|
| `regex` | Stable structured-identifier baseline | `python scripts/run_bench.py --corpus tests/fixtures/redactionbench --detector regex --output /tmp/redax-regex.json` |
| `gliner2` | Beta local model adapter | Same command with `--detector gliner2` after the pinned snapshot is cached and verified |

The current model provenance is documented in
[`docs/models-survey.md`](models-survey.md) and `MODEL_HASHES.txt`. A model
benchmark should not be compared across runs unless the Redax commit, model
revision/digest, dataset revision, Python/Torch versions, hardware, labels,
thresholds, and preprocessing are recorded together.

## What to publish for a release

Generate machine-readable output from `scripts/run_bench.py` and include:

- standard precision, recall, F1, and the RedactionBench R-Score;
- exact and partial/character matching definitions;
- corpus licensing, split, and revision;
- detector, model revision, snapshot digest, and label mapping;
- warm/cold latency, concurrency, hardware, and runtime versions;
- the Redax commit and command-line parameters.

The small checked-in fixtures are regression fixtures, not evidence of broad
real-world accuracy. They protect the scoring code and benchmark CLI from
drift; they do not establish a production SLA.
