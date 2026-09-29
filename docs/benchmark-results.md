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

The concurrency matrix artifacts record the same 300-request workload at
concurrency 1, 10, 20, and 40 against the Python 3.13 regex server on the
recorded macOS host:

- [`regex-api-concurrency-1.json`](benchmarks/regex-api-concurrency-1.json)
- [`regex-api-concurrency-10.json`](benchmarks/regex-api-concurrency-10.json)
- [`regex-api-concurrency-20.json`](benchmarks/regex-api-concurrency-20.json)
- [`regex-api-concurrency-40.json`](benchmarks/regex-api-concurrency-40.json)

All four runs returned 300/300 HTTP 200 responses. They are local regression
measurements only; the harness's RSS/CPU fields describe the load-generator
process, not a production server capacity limit.

The warm ramp artifacts record 1,000 requests at concurrency 1, 20, 40, 80,
128, and 160:

- [`regex-api-ramp-1.json`](benchmarks/regex-api-ramp-1.json)
- [`regex-api-ramp-20.json`](benchmarks/regex-api-ramp-20.json)
- [`regex-api-ramp-40.json`](benchmarks/regex-api-ramp-40.json)
- [`regex-api-ramp-80.json`](benchmarks/regex-api-ramp-80.json)
- [`regex-api-ramp-128.json`](benchmarks/regex-api-ramp-128.json)
- [`regex-api-ramp-160.json`](benchmarks/regex-api-ramp-160.json)

The local knee was concurrency 80 (633.723 requests/sec, p99 133.351 ms);
concurrency 160 fell to 405.3 requests/sec with p99 558.202 ms. These results
are local regression evidence only; the harness process metrics describe the
load generator, and no production safe limit is claimed.

For sustained-load checks, replace `--requests 100` with
`--duration-seconds 3600`; the harness reports request count, throughput,
percentiles, and RSS drift over the bounded run.

Earlier working-tree snapshots contained exploratory comparisons, but their
raw result artifacts, model provenance, and reproducible environment were not
part of the release contract.

## PII200k real-workload run

The checked-in `tests/fixtures/pii200k` corpus contains 5,060 labelled
documents and is used only under its documented synthetic/licensing terms. The
full regex run produced corpus mean R-Score `0.1301` (p50 `0.0`). A pinned
Guardrails GLiNER2 run over the first 500 documents produced corpus mean
`0.5439` (p50 `0.5`). The sample is an accuracy signal, not a release SLA;
the category breakdown and per-document scores are retained in the generated
JSON artifacts from `scripts/run_bench.py`.

The HTTP harness can now cycle through the corpus without recording payloads:

```bash
python scripts/load_bench.py --url http://127.0.0.1:8000/v1/redact \
  --corpus tests/fixtures/pii200k --requests 1000 --concurrency 4 \
  --api-key "$REDAX_BENCH_API_KEY" --output /tmp/pii200k-load.json
```

On the recorded Python 3.13/macOS local stack, a 1,000-request, concurrency-4
run returned 1,000/1,000 HTTP 200 responses at 379.386 requests/second,
p50 10.118 ms, p95 13.330 ms, and p99 16.761 ms. A 2,000-request,
concurrency-8 run returned 2,000/2,000 HTTP 200 responses at 362.706
requests/second, p50 21.181 ms, p95 27.951 ms, and p99 33.226 ms. The local
rate limit was raised only for this bounded test; these results are not a
production capacity claim.

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
