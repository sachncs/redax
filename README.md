# Redax

Self-hosted PII redaction engine. Sits before your LLM so sensitive data never enters the prompt in cleartext.

- **≤1B params**, runs on CPU (default model: [`fastino/gliner2-privacy-filter-PII-multi`](https://huggingface.co/fastino/gliner2-privacy-filter-PII-multi), 0.3B; production default: [`OpenMed/OpenMed-PII-SuperClinical-Large-434M-v1`](https://huggingface.co/OpenMed/OpenMed-PII-SuperClinical-Large-434M-v1), Apache-2.0)
- Deterministic, inspectable, no second LLM call
- Sync, batch, SSE-stream, and async-job API surfaces
- Versioned YAML policies, diffable for audit
- Reversible typed placeholders + Hiding-in-Plain-Sight relexicalization
- WASM bundle for browser / edge (same model, quantized)
- Audit log records what was redacted, never the values
- RedactionBench-compatible R-Score metric (`scripts/run_bench.py`, see [`docs/bench.md`](docs/bench.md))
- Multi-stage pipeline: regex gate + encoder + circuit-breaker + consensus fusion, see [`docs/pipeline.md`](docs/pipeline.md)
- Quantified vs the `ai4privacy/pii-masking-200k` benchmark; reproducible via `scripts/eval_detectors.py`

## Quickstart

```bash
docker compose up
curl http://localhost:8000/healthz
```

## Usage

```python
from redax import Redactor
from your_llm_client import LLM

redactor = Redactor(policy="llm-outbound")


def chat(user_message, system=None):
    safe_user = redactor.redact(user_message)
    safe_system = redactor.redact(system) if system else None
    response = llm.generate(prompt=safe_user, system=safe_system)
    return redactor.redact(response.text)
```

## API

| Endpoint | Purpose |
|---|---|
| `POST /v1/redact` | Sync, single text |
| `POST /v1/redact/batch` | Sync, list of texts |
| `POST /v1/redact/stream` | SSE/NDJSON streaming |
| `POST /v1/jobs` + `GET /v1/jobs/{id}` | Async, large workloads |
| `GET /v1/policies` | List built-in policies |
| `GET /healthz` `/readyz` `/metrics` | Health, readiness, Prometheus |

## Documentation

See [`docs/`](docs/) for architecture, policies, integration patterns, and deployment.

## License

Apache 2.0
