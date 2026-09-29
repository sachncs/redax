# Local deployment

This guide runs Redax and its local operational dependencies on one Linux or
Docker Desktop machine. It uses Docker Compose only. No cloud account,
managed Redis, Kubernetes cluster, public DNS, or public TLS certificate is
required.

This is a production-like local test environment, not proof of multi-node
availability, managed Redis failover, public ingress security, or the hosted
production launch gate.

## Prerequisites

- Docker Engine plus Docker Compose v2, or Docker Desktop.
- At least 8 GB available to the Docker VM when using the default GLiNER2
  detector. The API and worker each load the pinned local model.
- Network access for the first image build. The Dockerfile downloads and
  verifies the pinned dependency wheels and model; subsequent starts use the
  local image and named volumes.
- The Compose profile bounds the API and worker to 2 CPUs/4 GiB each and Redis
  to 0.5 CPU/512 MiB. These are Compose resource limits, not a capacity claim;
  increase the Docker VM memory if the model workload needs it.
- `curl` for smoke checks.
- Optional: [k6](https://k6.io/) for the load scenario.

## Configure and start

```bash
cp .env.example .env
```

Generate local-only values and put them in `.env`:

```bash
python3.13 -c 'import secrets; print(secrets.token_hex(32))'
python3.13 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Use the first value for `REDAX_HASH_SALT`, a separate random value for
`REDAX_API_KEYS`, the Fernet value for
`REDAX_JOB_PAYLOAD_ENCRYPTION_KEY`, and a separate password for
`GRAFANA_ADMIN_PASSWORD`. Do not commit `.env` or reuse these values outside
the local environment.

Start the complete stack:

```bash
docker compose up -d --build
docker compose ps
```

The API waits for Redis and the local model before becoming ready. Check it:

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

## Services and ports

| Service | URL / address | Exposure |
|---|---|---|
| Redax API | `http://localhost:8000` | Published |
| Prometheus | `http://localhost:9090` | Published |
| Grafana | `http://localhost:3000` | Published; use `GRAFANA_ADMIN_USER`/`GRAFANA_ADMIN_PASSWORD` |
| Redis | `redis:6379` | Internal only |
| OpenTelemetry Collector | `otel-collector:4317` / `4318` | Internal only |
| Tempo | `tempo:3200` | Internal only |
| Loki | `loki:3100` | Internal only |
| Promtail | Docker socket + Loki | Internal only |

The API and worker use Compose service names. Only the API, Prometheus, and
Grafana ports are published by default, and Compose binds them to
`127.0.0.1`. They are not reachable from another host interface unless an
operator explicitly changes the port mapping.

## Redaction smoke test

```bash
curl -sS http://localhost:8000/v1/redact \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: ${REDAX_API_KEY}" \
  -d '{"text":"Synthetic contact alice@example.com"}'
```

If `REDAX_API_KEY` is not exported in the shell, copy the configured local
value from `.env` for the header. The response must not contain the original
synthetic email.

## Observability

The stack provisions three Grafana datasources and a `Redax local overview`
dashboard automatically:

- Prometheus scrapes `redax:8000/metrics` every five seconds.
- Redax exports request traces to the collector at
  `http://otel-collector:4317`; the collector forwards them to Tempo.
- JSON stdout logs are discovered from the Docker socket by Promtail and sent
  to Loki. The local configuration uses bounded service/container labels and
  does not add request payloads to labels.

Open [Grafana](http://localhost:3000), open the `Redax` folder, and select the
overview dashboard. Prometheus can be queried directly at
`http://localhost:9090`.

Useful checks:

```bash
curl -sS http://localhost:9090/api/v1/targets
docker compose exec -T loki wget -qO- \
  'http://localhost:3100/loki/api/v1/query_range?query=%7Bservice%3D%22redax%22%7D&limit=5'
docker compose exec -T tempo wget -qO- \
  'http://localhost:3200/api/search?limit=10'
```

## Load test

Install k6 using its official local package for your operating system, then
run the configurable scenario:

```bash
REDAX_API_KEY='your-local-key' \
  k6 run tests/load/basic.js
```

Override the initial local envelope when needed:

```bash
BASE_URL=http://localhost:8000 VUS=20 DURATION=2m \
  REDAX_API_KEY='your-local-key' TEXT='Synthetic email alice@example.com' \
  k6 run tests/load/basic.js
```

The scenario checks liveness, readiness, metrics, and a configurable synthetic
redaction request. Compose also limits request and response bodies to 1 MiB by
default. Its thresholds are a local smoke signal, not a production SLO or
capacity guarantee.

## Repeatable local verification

After exporting the API key configured in `.env`, run the full local contract
check:

```bash
export REDAX_API_KEY='your-local-key'
make compose-verify
```

The command checks API liveness/readiness, synchronous redaction, a Redis-backed
worker job, Prometheus scraping, Grafana health, Loki query delivery, Tempo
trace delivery, and that the synthetic source marker is absent from the job,
log, and trace responses. It is a local deployment check, not evidence of
managed-service failover or public production capacity.

## Validation record

The local contract was last verified on 2026-09-30 from the repository
checkout with the following results:

| Check | Result |
|---|---|
| `docker compose config --quiet` | Pass |
| `docker compose build --pull=false` | Pass; model snapshot digest verified during image build |
| `docker compose up -d` and container health | Pass; 9/9 services healthy |
| `make PYTHON=.venv313/bin/python verify` | Pass; 523 tests passed, 11 skipped |
| Site `npm run check && npm run build` | Pass; 0 Astro diagnostics, 16 pages built |
| k6 (`VUS=2`, `DURATION=10s`) | Pass; 140 checks, 0% errors, p95 8.79 ms |
| Compose verifier | Pass; API, worker, Redis, metrics, logs, and traces |
| Redis restart persistence | Pass; sentinel value survived `docker compose restart redis` |
| Failure paths | Pass; Redis 503/recovery, collector fail-open, worker queue/recovery, full down/up recovery |

The k6 and latency numbers are laptop smoke-test observations, not a
production capacity claim. The model/dependency download requires network
access during the first image build; runtime inference and telemetry remain
inside the local Compose network after the image exists.

## Redis backup and restore

Create a portable RDB snapshot in the running Redis container and copy it to a
host directory:

```bash
mkdir -p backups
docker compose exec -T redis redis-cli --rdb /data/redax-backup.rdb
docker cp "$(docker compose ps -q redis):/data/redax-backup.rdb" \
  backups/redax-backup.rdb
```

For a disposable local restore, stop the application and Redis, replace the
Redis data volume with the snapshot, then start the stack again. Do this only
when the local data can be discarded; `docker compose down -v` removes all
named state:

```bash
docker compose down
docker compose up -d redis
docker cp backups/redax-backup.rdb "$(docker compose ps -q redis):/data/dump.rdb"
docker compose restart redis
docker compose up -d redax redax-worker
```

Verify `PONG`, `/readyz`, and a representative job after restoring. Keep
backups outside Git and treat them as sensitive operational data.

## Shutdown and reset

```bash
docker compose down       # stop and remove containers; keep named volumes
docker compose logs -f    # inspect logs while the stack is running
docker compose down -v    # full local reset, including Redis and telemetry data
```

Do not use `down -v` if the local audit, Redis, dashboard, metrics, logs, or
traces need to be retained.

## Troubleshooting

- **API exits with code 137:** increase the Docker/Colima VM to at least 8 GB
  or set `REDAX_DETECTOR=regex` for a lightweight local smoke environment.
- **API is healthy but Prometheus is down:** ensure `redax` is included in
  `REDAX_TRUSTED_HOSTS`; Prometheus reaches the API by that internal hostname.
- **Readiness is 503:** inspect `docker compose logs redax redax-worker redis`
  and confirm Redis is healthy and the model finished loading.
- **Grafana has no data:** check that Prometheus is scraping `redax` and that
  Loki/Tempo are healthy before restarting Grafana.
- **Docker Desktop log collection differs:** Promtail requires access to the
  Docker socket; on a restricted desktop installation, enable that mount or
  disable only the local log shipper while retaining application stdout.
