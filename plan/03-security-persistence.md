# Phase 3 — Security, persistence, and operational limits

## Objective

Make the local stack safe for production-like testing and recoverable across
container restarts, without implying production secret management.

## Work

- Add `.env` to `.gitignore` and provide generated-development-secret
  instructions for API keys, hash salt, audit integrity, and Fernet job
  encryption.
- Label every local credential as development-only and list the values that
  must be replaced before any real deployment.
- Preserve the existing production configuration validation; do not weaken it
  to make Compose start.
- Persist Redis, Grafana, Prometheus, Loki, Tempo, model, and audit data in
  named volumes.
- Add Redis backup and restore commands using `redis-cli --rdb` or an
  equivalent checked procedure, including where the resulting file is stored.
- Add Docker log rotation (`max-size`/`max-file`) to application and worker
  services and avoid logging request bodies or secrets.
- Expose only API, Grafana, and Prometheus by default. Keep Redis, collector,
  Loki, Tempo, and the worker internal.
- Add resource and response/request limits suitable for the initial local
  target of 5–20 requests/sec average, 50–100 peak, 50–200 concurrent
  connections, and payloads below 1 MB.
- Keep localhost HTTP as the default. Document optional Caddy/local
  certificate HTTPS only if the final implementation needs it; do not make
  public DNS or public TLS a prerequisite.

## Deliverables

- Secure `.env.example` and ignore rules.
- Persistent volumes and backup/restore procedure.
- Bounded logging and local-only exposure rules.
- Any narrowly scoped application configuration changes needed by the local
  collector or limits.

## Exit gate

No committed secret is required to start, `git diff`/secret scanning finds no
credential material, restart preserves required local state, logs are bounded,
and all published ports are intentional and documented.

