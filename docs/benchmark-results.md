# Benchmark results

There is no current release-grade result table checked into this repository.
Earlier working-tree snapshots contained exploratory comparisons, but their
raw result artifacts, model provenance, and reproducible environment were not
part of the release contract. They are intentionally not presented as current
product claims.

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
