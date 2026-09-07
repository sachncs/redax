# Policies

A policy is a YAML file under `policies/` describing how each named field
should be redacted. Three built-in policies ship with Redax: `default`,
`strict`, `minimal`. Add your own by dropping a `.yaml` file into
`policies/` and listing it via `GET /v1/policies`.

## Schema

```yaml
name: my-policy            # required, used as lookup key
version: 1.0.0            # required, surfaced in audit log
description: ...          # optional
fields:                   # required
  free_text:
    strategy: autoDeID    # one of: passThrough, mask, hash, regex, autoDeID
    relex: true           # emit typed placeholders [TYPE_NNNN]
    multi_pass: 2         # run the detector N times, union results
    entity_types: [person, email, ...]
  ssn:
    strategy: regex
    format: "[SSN]"
    entity_types: [SSN_US]
```

## Strategies

| Name | Behavior |
|---|---|
| `passThrough` | Returns the text unchanged. Use for non-PII fields like `gender`. |
| `mask` | Substitutes every span (passed in) with a configured format string. |
| `hash` | Replaces every span with `SHA256(salt + text)[:length]`; useful for stable join keys. |
| `regex` | Runs the regex detector on the field's text and applies `format`. |
| `autoDeID` | Runs the NER detector (possibly multi-pass) and emits typed placeholders or format strings. |

## Using a policy

Inline in the request body:

```bash
curl -X POST http://localhost:8000/v1/redact \
  -H 'Content-Type: application/json' \
  -d "$(jq -Rs '{text: ., policy: ...}' < message.txt)"
```

Or via the SDK:

```python
from redax import Redactor

r = Redactor(policy="default")  # looks up policies/default.yaml
```

## Writing a custom policy

1. Copy `policies/default.yaml`
2. Edit fields
3. Drop into `policies/` (mounted into the container at `/policies`)
4. Verify with `curl http://localhost:8000/v1/policies`

## Versioning

Bump the `version` field whenever you change a policy's behavior. The
audit log records `policy_version` so you can answer "what did we redact
on this date?" by diffing the policy YAML against `git`.
