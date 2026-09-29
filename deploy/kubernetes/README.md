# Kubernetes reference deployment

This directory is a reference topology, not a turnkey managed-Redis product.
It runs three stateless API replicas and two independent ARQ worker replicas.
Before applying it:

1. Replace the image tag in `kustomization.yaml` with the signed image digest
   from the release attestation.
2. Create the `redax-redis` Secret with a TLS Redis URL and the `redax-api`
   Secret with production API keys and a unique hash salt.
3. Provision an RWX storage class for `redax-audit` or replace the local audit
   backend with the organisation's durable audit sink.
4. Configure an ingress with TLS, request-body limits, timeouts, and the
   service's `/readyz` endpoint as its readiness target.

The manifests intentionally do not deploy Redis. Redis persistence, failover,
backup, restore, and RPO/RTO are operator-owned production requirements.

```bash
kubectl create namespace redax
kubectl -n redax create secret generic redax-api \
  --from-literal=api-keys='replace-me' \
  --from-literal=hash-salt='replace-with-random-value'
kubectl -n redax create secret generic redax-redis \
  --from-literal=url='rediss://redis.example.internal:6380/0'
kubectl apply -k deploy/kubernetes
kubectl -n redax rollout status deployment/redax-api
kubectl -n redax rollout status deployment/redax-worker
```

Do not commit generated Secrets or plaintext production credentials.
