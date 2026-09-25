# Threat model

Redax is a text transformation boundary. It is intended to reduce accidental
PII transfer from an application to a downstream system; it is not a complete
DLP product or an anonymity guarantee.

## Assets

- Request text and the entity values embedded in it.
- Redacted output sent to downstream applications.
- API keys, hash salt, model files, policy files, audit records, and Redis
  state.

## Redax is designed to help with

- An application accidentally sending recognized PII to an LLM or other
  downstream provider.
- Operational records retaining recognized entity values in Redax's audit,
  cache, idempotency, job-result, metrics, or normal error paths.
- Repeated structured identifiers such as email, phone, IP, IBAN, SSN, URL,
  and Luhn-valid card numbers when the corresponding regex detector is enabled.
- Applications forgetting to apply the same replacement policy to every text
  request.

## Redax does not automatically protect against

- PII the configured detectors do not recognize, secrets, credentials, or new
  entity types outside the policy and detector taxonomy.
- Prompt injection, intentional encoding, steganography, or side channels.
- OCR/image/audio PII; Redax currently processes text.
- A compromised host, container runtime, dependency, model, reverse proxy,
  Redis, audit volume, telemetry collector, backup, or downstream provider.
- Infrastructure access logs, packet capture, crash dumps, debug logging added
  by an operator, or retention/access-control mistakes outside the process.

## Trust boundaries and controls

1. The caller sends raw text to the Redax HTTP process. TLS, ingress access
   control, request-body logging, and network policy are deployment concerns.
2. Authentication, request limits, and fixed-window rate limiting admit work.
   Production startup requires API keys and trusted hosts.
3. Detector spans are validated and overlap-resolved before replacement.
4. `/v1/redact` returns transformed text. Detection diagnostics are not a
   license to forward the request body downstream.
5. Audit events contain counts, types, timing, keyed digests, and request metadata;
   they must not contain original entity values. Redis state is TTL-bound and
   stores redacted responses; API keys are represented by one-way tokens in
   rate-limit/job ownership keys.
6. Optional model inference runs locally from the configured model cache. A
   production GLiNER2 configuration fails startup when its model cannot load;
   development may explicitly use regex mode.

## Operator responsibilities

Use TLS at the ingress, restrict Redis and audit storage, protect the hash
salt and API keys, review inline and named policies, disable request-body
logging in proxies, control OTLP exporter destinations, set retention, and
test the actual deployment with representative synthetic data. The guarantees
above are implementation boundaries, not a promise about surrounding
infrastructure.
