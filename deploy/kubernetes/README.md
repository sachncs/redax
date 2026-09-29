# Kubernetes reference deployment

This directory is a reference topology, not a turnkey managed-Redis product.
It runs three stateless API replicas and two independent ARQ worker replicas.
Before applying it:

1. Confirm the signed image digest in `kustomization.yaml` matches the release
   attestation before applying; update it only as part of an reviewed release.
2. Create the `redax-redis` Secret with a TLS Redis URL and the `redax-api`
   Secret with `REDAX_*` keys, a unique hash salt, and a generated Fernet job
   payload key.
3. Provision an RWX storage class for `redax-audit` or replace the local audit
   backend with the organisation's durable audit sink.
4. Configure an ingress with TLS, request-body limits, timeouts, and the
   service's `/readyz` endpoint as its readiness target.
5. Label the ingress-controller namespace with
   `redax.ingress-access=true`. The checked-in NetworkPolicies deny other
   ingress and restrict API/worker egress to cluster DNS, HTTPS, and Redis
   ports; adjust the policy when the managed Redis endpoint uses a different
   port or the ingress controller uses a different namespace.

The manifests intentionally do not deploy Redis. Redis persistence, failover,
backup, restore, and RPO/RTO are operator-owned production requirements.

```bash
kubectl create namespace redax
kubectl -n redax create secret generic redax-api \
  --from-literal=REDAX_API_KEYS='replace-me' \
  --from-literal=REDAX_HASH_SALT='replace-with-random-value' \
  --from-literal=REDAX_JOB_PAYLOAD_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
kubectl -n redax create secret generic redax-redis \
  --from-literal=url='rediss://redis.example.internal:6380/0'
kubectl apply -k deploy/kubernetes
kubectl -n redax rollout status deployment/redax-api
kubectl -n redax rollout status deployment/redax-worker
```

Do not commit generated Secrets or plaintext production credentials.
