# API key compromise and rotation

## Symptom

Unexpected request volume, key-specific rate-limit alarms, suspected key
exposure, or unauthorized access to policy/job/metrics endpoints.

## Diagnose

Use principal identifiers, request IDs, endpoint/status metrics, and ingress
logs. Never print the key, bearer value, request body, or Redis key.

## Mitigate

Revoke the compromised key at the secret manager/allow-list, add a replacement
key, and preserve an overlap window only when explicitly approved. Reduce the
affected principal's rate limit or block it at the ingress.

## Recover and verify

Confirm the old key is rejected, the new key is accepted only for its intended
scope, and metrics contain identifiers rather than secrets. Record the rotation
time and deployment version. Scoped key rotation/revocation is still a P1
implementation item.
