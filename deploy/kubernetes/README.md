# Kubernetes reference deployment

This directory is a reference topology, not a turnkey managed-Redis product.
It runs three stateless API replicas and two independent ARQ worker replicas.
Before applying it:

1. Confirm the signed image digest in `kustomization.yaml` matches the release
   attestation before applying; update it only as part of an reviewed release.
2. Create the `redax-redis` Secret with a TLS Redis URL and the `redax-api`
   Secret with `REDAX_*` keys, a unique hash salt, a generated Fernet job
   payload key, and a separate audit-integrity key.
3. The reference topology uses Redis-backed audit events so multiple API
   replicas share one bounded audit stream. If file audit is selected instead,
   provide organisation-managed durable storage and its retention/backup policy.
4. Install an ingress-nginx controller (or translate the checked-in ingress
   annotations for your controller), create the `redax-tls` TLS Secret, and
   review `ingress.yaml` for the production hostname. It enforces the 4 MiB
   body limit and gives streaming responses a bounded 75-second read window.
   The service's `/readyz` endpoint remains the pod readiness target.
5. Label the ingress-controller namespace with
   `redax.ingress-access=true`. The checked-in NetworkPolicies deny other
   ingress and restrict API/worker egress to cluster DNS, HTTPS, and Redis
   ports; adjust the policy when the managed Redis endpoint uses a different
   port or the ingress controller uses a different namespace.
6. Configure the Prometheus Adapter (or an equivalent custom-metrics adapter)
   to expose `redax_requests_inflight` as a per-pod metric and
   `redax_queue_depth` plus `redax_queue_oldest_age_seconds` as external
   metrics. The HPA combines these signals with CPU and scales on the highest
   recommendation; CPU alone is not a safe proxy for model or queue pressure.

The manifests intentionally do not deploy Redis. Redis persistence, failover,
backup, restore, and RPO/RTO are operator-owned production requirements.

The API HPA starts at three replicas and targets 80 admitted requests per pod.
The worker HPA starts at two replicas and targets a queue depth of 10 or an
oldest queued job age of 30 seconds. These are conservative starting points,
not measured production capacity limits: validate them with the benchmark
matrix in [`docs/scaling.md`](../../docs/scaling.md), then change them with a
recorded load-test result. Keep worker scale-down stabilization and the worker
PDB in place so active jobs get the configured termination grace period and
ARQ completion window.

```bash
kubectl create namespace redax
kubectl -n redax create secret generic redax-api \
  --from-literal=REDAX_API_KEYS='replace-me' \
  --from-literal=REDAX_HASH_SALT='replace-with-random-value' \
  --from-literal=job_payload_encryption_key="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  --from-literal=audit_integrity_key='replace-with-independent-random-secret'
kubectl -n redax create secret generic redax-redis \
  --from-literal=url='rediss://redis.example.internal:6380/0'
kubectl -n redax create secret tls redax-tls \
  --cert=/path/to/fullchain.pem --key=/path/to/privkey.pem
kubectl apply -k deploy/kubernetes
kubectl -n redax rollout status deployment/redax-api
kubectl -n redax rollout status deployment/redax-worker
```

## Rollout and rollback

Apply a new release only after verifying its signed image digest and
`RELEASE-METADATA.json`. The API and worker Deployments use one-at-a-time
surges with zero voluntary unavailability, and their PDBs preserve the
minimum replica floor during node maintenance.

```bash
kubectl -n redax rollout status deployment/redax-api --watch
kubectl -n redax rollout status deployment/redax-worker --watch
kubectl -n redax rollout history deployment/redax-api
kubectl -n redax rollout history deployment/redax-worker
kubectl -n redax rollout undo deployment/redax-api --to-revision=<known-good>
kubectl -n redax rollout undo deployment/redax-worker --to-revision=<known-good>
kubectl -n redax rollout status deployment/redax-api --watch
kubectl -n redax rollout status deployment/redax-worker --watch
```

Do not undo only one tier across a persisted-schema change. Confirm the
previous release's metadata schema versions are compatible with the live Redis
namespace, then verify `/readyz`, a synthetic `/v1/redact`, idempotency replay,
job status, and audit delivery before restoring traffic. A disposable-cluster
rollout/rollback drill is still required before treating this reference as
fully production-proven.

Do not commit generated Secrets or plaintext production credentials.
