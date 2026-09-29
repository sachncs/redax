# Production security review

This review records the local gates run against the current Redax image and
repository. It is evidence for the release process, not a substitute for a
cloud-provider security review or managed-service configuration.

## Dependency, filesystem, and image scanning

The following Trivy gates completed with no HIGH or CRITICAL findings:

```bash
docker run --rm -v "$PWD:/repo:ro" -v redax-trivy-cache:/root/.cache \
  aquasec/trivy:latest fs /repo \
  --scanners vuln,misconfig --severity HIGH,CRITICAL \
  --ignore-unfixed=false --skip-dirs /repo/.git \
  --skip-dirs /repo/.venv --skip-dirs /repo/models_cache

docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  -v redax-trivy-cache:/root/.cache aquasec/trivy:latest image \
  redax/redax:0.1.0 --scanners vuln,misconfig \
  --severity HIGH,CRITICAL --ignore-unfixed=false
```

The repository CI workflow and release workflow remain the authoritative
repeatable gates: they generate SBOMs and fail on HIGH/CRITICAL vulnerabilities,
secrets, or supported misconfigurations. The image scan was run against the
locally built `redax/redax:0.1.0`; rerun it for every release digest.

## Edge and firewall controls

The Kubernetes reference deployment now provides ingress-nginx starting
limits of 20 requests/second per client, a five-times burst, and 100 concurrent
connections per client. The application/API-key limiter remains the tenant
control and is fail-closed when Redis is unavailable. The API and worker
NetworkPolicies accept API traffic only from a namespace labelled
`redax.ingress-access=true`.

The cloud/VPC firewall is intentionally operator-owned. The public rule must
allow TCP 443 only; API 8000, Redis 6379/6380, OTLP 4317/4318, Prometheus,
Grafana, Loki, and Tempo must not be internet reachable. Redis and telemetry
egress must be restricted to their managed endpoints because Kubernetes
NetworkPolicy port rules cannot constrain provider-owned external IPs.

## Remaining production gates

These local scans do not prove managed Redis HA/failover, cloud firewall
correctness, secret rotation, multi-replica isolation, or production SLOs.
Those must be completed in the target account and attached to the launch
checklist before declaring the service production-ready.
