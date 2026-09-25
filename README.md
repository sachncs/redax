# Redax

Redax is a self-hosted service for detecting configured PII in text and
returning transformed text before it is sent to a downstream system such as
an LLM.

```text
input text → detect spans → apply policy → return redacted text
```

It is early-stage software (`0.1.0`): the HTTP contract is tested, but model
integrations and policies may change before `1.0`. Redax is a redaction
boundary, not a complete data-loss-prevention system. Undetected PII, secrets,
compromised infrastructure, provider logs, and operator configuration remain
outside its guarantees.

[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/sachncs/redax/ci.yml?branch=master)](https://github.com/sachncs/redax/actions)

## 30-second quickstart

The Compose profile is for local development and uses a development
configuration. Do not reuse its credentials or ephemeral Redis settings for a
public deployment.

```bash
git clone https://github.com/sachncs/redax.git
cd redax
docker compose up --build
curl -s http://localhost:8000/v1/redact \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: local-compose-key' \
  -d '{"text":"Email alice@example.com"}'
```

The response contains safe text and span metadata. The HTTP response does not
include a re-identification map because that map contains original values.

```json
{
  "text": "Email [REDACTED]",
  "spans": [{"start": 6, "end": 23, "type": "EMAIL", "confidence": 1.0}],
  "relex_map": {},
  "used_pipeline": false,
  "used_fallback": false,
  "digest": null
}
```

## What Redax does

- **Detection** finds spans. The current stable detector is structured regex;
  the pinned local GLiNER2 path is beta and covers contextual entities.
- **Redaction** replaces selected spans with `[REDACTED]` or a policy-defined
  replacement. `POST /v1/redact` always returns transformed text.
- **Policies** select entity types and replacement strategies. Explicit
  pass-through fields are possible, so review policies as security-sensitive
  configuration before deployment.
- **Operational controls** include request limits, API-key authentication,
  fixed-window Redis rate limiting, idempotency, response caching, audit
  metadata, Prometheus metrics, and optional OTLP tracing.

The browser demo is illustrative and regex-only. WASM is experimental and is
not assumed to have parity with server-side model inference.

## Security boundary

Redax is designed to keep recognized entity values out of its audit events,
logs, metrics labels, job results, cache responses, and idempotency responses.
The input is still present in process memory while it is being transformed,
and deployment infrastructure may observe requests or files. Review the
[threat model](docs/threat-model.md) and [data flow](docs/data-flow.md) before
handling production data.

Production startup requires all of the following:

```bash
REDAX_ENV=prod
REDAX_API_KEYS='generate-and-store-a-real-secret'
REDAX_TRUSTED_HOSTS='redax.example.com'
REDAX_HASH_SALT='generate-a-unique-random-value'
```

See [deployment](docs/deployment.md) for Redis, audit retention, model
loading, CORS, and readiness behavior.

## Documentation

- [API contract](docs/api.md)
- [Architecture](docs/architecture.md)
- [Threat model](docs/threat-model.md)
- [Data flow](docs/data-flow.md)
- [Policies and replacement strategies](docs/policies.md)
- [Deployment and configuration](docs/deployment.md)
- [Integration patterns](docs/integration.md)
- [Benchmark methodology](docs/bench.md)
- [Benchmark results](docs/benchmark-results.md)
- [Model survey and provenance](docs/models-survey.md)
- [Launch audit and remaining limitations](docs/launch-audit.md)
- [Product status](https://sachncs.github.io/redax/docs/status)

The polished entry point is the [Redax product site](https://sachncs.github.io/redax/).
Technical documentation remains the source of truth; the site links back to
these contracts.

## Development

Redax currently supports Python 3.13+.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install -e '.[dev]'
make test lint typecheck
```

The service package is currently `app.*`; those modules are implementation
internals. The supported integration surface is the versioned HTTP API.

For site work:

```bash
cd site
npm install
npm run dev
npm run check
npm run build
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for architecture, tests, benchmark,
security-review, and release guidance. Report vulnerabilities privately using
[SECURITY.md](SECURITY.md).

## License

Apache 2.0 — see [LICENSE](LICENSE).
