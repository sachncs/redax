<p align="center">
  <h1 align="center">Redax</h1>
  <p align="center">A self-hosted PII redaction engine that sits between your text and your LLM.</p>
  <p align="center">
    <a href="#installation"><img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="License"></a>
    <a href="https://github.com/sachncs/redax/releases/latest"><img src="https://img.shields.io/github/v/release/sachncs/redax" alt="Latest release"></a>
    <a href="https://github.com/sachncs/redax/actions"><img src="https://img.shields.io/github/actions/workflow/status/sachncs/redax/ci.yml?branch=master" alt="CI"></a>
    <a href="https://github.com/sachncs/redax/pkgs/container/redax"><img src="https://img.shields.io/badge/ghcr.io-redax-blue" alt="Docker image"></a>
    <a href="https://github.com/sachncs/redax/stargazers"><img src="https://img.shields.io/github/stars/sachncs/redax" alt="Stars"></a>
    <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/code%20style-ruff-000000.svg" alt="Ruff"></a>
    <a href="https://mypy-lang.org/"><img src="https://img.shields.io/badge/type%20checked-mypy-blue.svg" alt="mypy"></a>
  </p>
</p>

---

## What is this?

Redax is a small Python service that answers one question:

> *"How do I make sure no email, phone number, name, or other
> personally identifiable information ever leaves my server in
> cleartext?"*

You send it a document; it sends back the same document with every
PII span replaced by a typed placeholder. The redaction is
**deterministic**: the same input always produces the same output, so
two replicas of the service behind a load balancer will return
byte-for-byte identical results. The original text is never logged.

It runs entirely on your own hardware. No data leaves the box. The
default detector ([`fastino/gliner2-privacy-filter-PII-multi`](https://huggingface.co/fastino/gliner2-privacy-filter-PII-multi),
0.3B parameters) is small enough to run on CPU, and the heavier
[`OpenMed/OpenMed-PII-SuperClinical-Large-434M-v1`](https://huggingface.co/OpenMed/OpenMed-PII-SuperClinical-Large-434M-v1)
detector fits in a single server's RAM. A regex safety net is
always on top of the model so a high-confidence pattern never gets
through even if the model misses it.

---

## Who is this for?

You, even if:

- You've never run a model before — the regex detector is built in
  and works out of the box.
- You don't know what PII stands for — it means *personally
  identifiable information*: anything that could be used to
  identify a real person.
- You've never deployed a model service.

If you can run `docker compose up` and `curl`, you can use Redax.
When the docs use a term you don't know, look it up in
[docs/architecture.md](docs/architecture.md).

If you've deployed ML services before, you'll be productive in five
minutes.

---

## What can it do?

- **Deterministic regex detection** — Seven structured PII types
  (email, phone, IP, IBAN, SSN, credit card with Luhn check, URL)
  with no model round-trip.
- **GLiNER2 zero-shot NER** — A 0.3B encoder that catches PERSON,
  organisation, and contextual entities the regex misses.
- **OpenMed-PII (optional)** — A 434M clinical-grade encoder with
  54 entity types; swap in by setting `REDAX_DETECTOR=openmed`.
- **Multi-stage pipeline** — Regex gate + encoder + circuit-broken
  fallback + consensus fusion. See
  [docs/architecture.md](docs/architecture.md).
- **Reversible typed placeholders** — `[EMAIL_0001]` instead of
  `[REDACTED]`, so the same entity gets the same placeholder
  everywhere it appears.
- **Hiding-in-Plain-Sight relexicalization** — Replace names with
  plausible lookalikes so the output still reads like English.
- **Versioned YAML policies** — Field-by-field redaction rules
  checked into git. See [docs/policies.md](docs/policies.md).
- **Append-only audit log** — Records what was redacted, never the
  values. Configurable rotation, retention, and fsync.
- **Prometheus + OpenTelemetry** — `/metrics` for scraping,
  optional OTLP gRPC exporter for traces.
- **Rate limit + idempotency + response cache** — Per-API-key token
  bucket in Redis; `Idempotency-Key` short-circuits retries.
- **RedactionBench R-Score** — Quantified against the
  `ai4privacy/pii-masking-200k` benchmark. See
  [docs/bench.md](docs/bench.md) and
  [docs/benchmark-results.md](docs/benchmark-results.md).
- **WASM bundle** — Same model, INT8-quantised, runs in the
  browser via Transformers.js. See
  [docs/deployment.md](docs/deployment.md).
- **RFC 7807 error responses** — Every error path returns a
  problem-details JSON body.

---

## Before you start

You'll need **Python 3.11 or newer** installed on your computer,
and **git** for downloading the code.

If you don't know what Python is or whether you have it:

1. Open a terminal (on macOS: `Cmd + Space`, type "Terminal"; on
   Windows: open "PowerShell"; on Linux: open your usual terminal).
2. Type `python3 --version` and press Enter.
3. If you see a version number starting with `3.11` or higher,
   you're set.
4. Otherwise, follow the
   [official Python installer guide](https://realpython.com/installing-python/).

You'll also need **git** (a tool for downloading code). Same drill:
type `git --version` in your terminal.

If you want the one-command path, you'll also need **Docker** and
**Docker Compose**.

---

## Installation

Pick whichever option fits your setup.

### Option 1 — Docker Compose (fastest)

```bash
git clone https://github.com/sachncs/redax.git
cd redax
docker compose up
```

The image bundles Python + Redax + its pinned dependencies + the
GLiNER2 model snapshot. Redis comes up alongside the service so
rate limiting, idempotency, and the response cache work out of the
box. Wait for `redax  | Application startup complete.` in the logs.

### Option 2 — Pre-built container from GHCR

```bash
docker run --rm -p 8000:8000 ghcr.io/sachncs/redax:latest
```

No `git clone`, no local build. Useful on servers or in CI.

### Option 3 — From source (recommended for development)

A "virtual environment" is an isolated Python sandbox that keeps
this package's stuff from interfering with your other Python
projects.

```bash
# 1. Download the code
git clone https://github.com/sachncs/redax.git
cd redax

# 2. Make a sandbox for it
python3 -m venv .venv
source .venv/bin/activate            # macOS / Linux
# .venv\Scripts\activate             # Windows (PowerShell)

# 3. Install Redax and its dev tools
pip install -r requirements.lock
pip install -e '.[dev]'
```

> 💡 **The dot in `.[dev]` is intentional.** It means "install this
> package and also the dev extras." The square brackets are part of
> the command, not punctuation.

After this, your terminal prompt will probably have `(.venv)` at the
front. That tells you the sandbox is active. To leave the sandbox
later, type `deactivate`.

---

## Your first run — the command line

The fastest way to see Redax work. No Python required:

```bash
curl -s -X POST http://localhost:8000/v1/redact \
  -H 'Content-Type: application/json' \
  -d '{"text": "Email me at alice@example.com or +1-415-555-2671."}'
```

You'll see something like:

```json
{
  "text": "Email me at [EMAIL_0000] or [PHONE_E164_0000].",
  "spans": [
    {"start": 12, "end": 29, "type": "EMAIL", "confidence": 1.0},
    {"start": 33, "end": 47, "type": "PHONE_E164", "confidence": 1.0}
  ],
  "relex_map": {
    "alice@example.com": "[EMAIL_0000]",
    "+1-415-555-2671": "[PHONE_E164_0000]"
  },
  "used_pipeline": false,
  "used_fallback": false,
  "digest": "8f1d2c..."
}
```

The audit log recorded the same information in `./audit.jsonl` —
without the email or the phone number themselves.

Other endpoints you can hit with `curl`:

```bash
curl http://localhost:8000/healthz                    # liveness
curl http://localhost:8000/readyz                     # readiness
curl http://localhost:8000/metrics                    # Prometheus
curl http://localhost:8000/v1/policies                # built-in policies
curl http://localhost:8000/v1/stats                   # detectors + breaker
```

See [docs/api.md](docs/api.md) for the full HTTP surface.

---

## Your first run — Python

Open a Python interpreter (`python3` in your terminal) and try this:

```python
import asyncio
from app.redaction.redactor import Redactor
from app.redaction.strategy import Hash, Mask, Skip
from app.inference.regex import RegexDetector

# Build a redactor with the regex detector + a couple of strategies.
detector = RegexDetector()
redactor = Redactor(
    detector=detector,
    strategies={
        "passThrough": Skip(),
        "mask": Mask(),
        "hash": Hash(salt="change-me"),
    },
    replacement="[REDACTED]",
)

# Run a single redaction.
text = "Email me at alice@example.com or +1-415-555-2671."
result = asyncio.run(redactor.redact(text))
print(result.text)
# -> "Email me at [REDACTED] or [REDACTED]."
print(result.spans)
# -> [Span(start=12, end=29, type='EMAIL', confidence=1.0), ...]
```

You can also pass a policy that maps field names to strategies:

```python
result = asyncio.run(
    redactor.redact(
        text,
        policy={
            "fields": {
                "free_text": {"strategy": "mask", "format": "[EMAIL]"},
                "phone": {"strategy": "hash"},
            }
        },
    )
)
```

The full Python surface (Detector, Strategy, Pipeline, the Relex
helper, the OpenMed / GLiNER2 wrappers) is documented in
[docs/api.md](docs/api.md).

---

## Configuration

All settings are read from environment variables prefixed with
`REDAX_` (and optionally a `.env` file in the working directory).
A typical `.env` looks like:

```bash
REDAX_LOG_LEVEL=INFO
REDAX_API_KEYS=prod-key-1,prod-key-2
REDAX_HASH_SALT=change-me-to-a-random-string
REDAX_REDIS_URL=redis://localhost:6379/0
REDAX_AUDIT_PATH=/var/lib/redax/audit.jsonl
REDAX_DETECTOR=gliner2           # or "regex" for the regex-only path
REDAX_MODEL_NAME=fastino/gliner2-privacy-filter-PII-multi
```

What each field means:

| Variable | Default | Plain English |
|---|---|---|
| `REDAX_LOG_LEVEL` | `INFO` | How chatty Redax should be: `DEBUG` (very chatty), `INFO` (normal), `WARNING` (only problems), `ERROR` (only failures). |
| `REDAX_API_KEYS` | empty | Comma-separated list of valid API keys. Empty = auth disabled (don't do this in production). |
| `REDAX_HASH_SALT` | `change-me` | Salt for the `hash` strategy and the response cache. Pick a per-deployment random string. |
| `REDAX_REDIS_URL` | `redis://localhost:6379/0` | Redis URL for jobs, rate limit, and the response cache. |
| `REDAX_AUDIT_PATH` | `./audit.jsonl` | Append-only JSONL audit log. Mount this on durable storage. |
| `REDAX_AUDIT_FSYNC` | `true` | `fsync` the audit log after every line. Set `false` only if you're shipping logs to a separate sink. |
| `REDAX_DETECTOR` | `gliner2` | Which detector to use. `regex` runs the deterministic path only; `gliner2` adds zero-shot NER. |
| `REDAX_MODEL_NAME` | `fastino/gliner2-privacy-filter-PII-multi` | HuggingFace model id for the active detector. Pinned revision lives in `MODEL_HASHES.txt`. |
| `REDAX_INFERENCE_CONCURRENCY` | `2` | Maximum number of in-flight model calls. Increase for GPUs. |
| `REDAX_RATE_LIMIT_PER_MINUTE` | `60` | Per-API-key fixed-window rate limit. `0` disables. |
| `REDAX_MAX_TEXT_CHARS` | `100000` | Reject inputs longer than this with a 413. |
| `REDAX_OTLP_ENDPOINT` | empty | OTLP gRPC endpoint for OpenTelemetry traces. |

The full list lives in [`app/config.py`](app/config.py); see
[docs/deployment.md](docs/deployment.md) for the production
checklist.

---

## Where to go next

For users:

- **[docs/api.md](docs/api.md)** — Full HTTP surface: request and
  response shapes, headers, error codes. Bookmark this once you
  start integrating.
- **[docs/integration.md](docs/integration.md)** — Drop-in patterns
  for the common LLM SDKs: how to wrap the prompt, stream the
  response, handle retries.
- **[docs/policies.md](docs/policies.md)** — Authoring redaction
  policies; the field-strategy mapping; relex vs format strings.
- **[docs/architecture.md](docs/architecture.md)** — How the
  multi-stage pipeline is put together and why.
- **[docs/bench.md](docs/bench.md)** — The RedactionBench R-Score
  metric, the worked example, and the scoring API.
- **[docs/benchmark-results.md](docs/benchmark-results.md)** — The
  per-corpus comparison table against `ai4privacy/pii-masking-200k`.

For operators / maintainers:

- **[docs/deployment.md](docs/deployment.md)** — Docker, Compose,
  Kubernetes, behind a load balancer, observability hooks.
- **[docs/models-survey.md](docs/models-survey.md)** — Why the
  default detector is GLiNER2 and what to swap in if you need
  higher recall on healthcare / multilingual text.
- **[CHANGELOG.md](CHANGELOG.md)** — Per-release notes.
- **[AGENTS.md](AGENTS.md)** — Conventions for anyone editing the
  codebase.

---

## Contributing

Want to improve Redax? See [CONTRIBUTING.md](CONTRIBUTING.md) for
how to set up a development environment and submit changes.

## Code of Conduct

We expect everyone to follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## Security

Found a security issue? See [SECURITY.md](SECURITY.md) — please don't
open a public GitHub issue for security problems.

## License

Apache 2.0 — see [LICENSE](LICENSE). Use it, fork it, ship it.
