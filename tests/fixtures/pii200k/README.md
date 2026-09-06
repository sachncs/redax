# ai4privacy/pii-masking-200k → RedactionBench conversion

| field | value |
|-------|-------|
| source dataset | ai4privacy/pii-masking-200k |
| snapshot | 2026-09-06 |
| sample seed | 1725613817 |
| min per category | 700 |
| synthetic supplement | code, files, logs, terminal (ai4privacy has none) |

Run `python scripts/convert_ai4privacy.py --out tests/fixtures/pii200k` to
regenerate deterministically. The classifier maps ai4privacy PII labels to
RedactionBench categories (medical, government, financial first; legal/academic
by keyword; emails by email/phone presence; otherwise operations). The
`scripts/convert_ai4privacy.py:label_to_redact_type` table maps each
ai4privacy label to one of redax's seven canonical regex types
(EMAIL, PHONE_E164, CREDIT_CARD, IP_ADDRESS, SSN_US, IBAN, URL) plus
PERSON, so that downstream detectors and the existing regex baseline can
consume the corpus.
