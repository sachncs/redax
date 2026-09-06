#!/usr/bin/env python3
"""Convert a stratified sample of `ai4privacy/pii-masking-200k` into the
RedactionBench corpus format used by `app/bench`.

Run:
    python scripts/convert_ai4privacy.py --out tests/fixtures/pii200k

Source dataset version: ai4privacy/pii-masking-200k (verified 2026-09-06,
HuggingFace `datasets` 5.0.1).
Sample seed: 1725613817 (captured in the file header below).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import textwrap
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

SAMPLE_SEED = 1725613817
SOURCE_DATASET = "ai4privacy/pii-masking-200k"
SOURCE_VERSION = "2026-09-06"
MIN_PER_CATEGORY = 700
MAX_PER_CATEGORY = 900
SYNTH_PER_CATEGORY = {
    "code": 60,
    "files": 60,
    "logs": 60,
    "terminal": 60,
    "government": 100,
    "legal": 350,
}


CATEGORY_FROM_PII: dict[str, str] = {
    "MEDICALRECORDNUMBER": "medical",
    "HEALTHPLANID": "medical",
    "BLOODTYPE": "medical",
    "BIOMETRICIDENTIFIER": "medical",
    "SSN": "government",
    "VEHICLEVIN": "government",
    "VEHICLEVRM": "government",
    "DRIVERLICENSENUM": "government",
    "TAXNUM": "financial",
    "IBAN": "financial",
    "CREDITCARDNUMBER": "financial",
    "CREDITCARDISSUER": "financial",
    "CREDITCARDCVV": "financial",
    "ACCOUNTNUMBER": "financial",
    "ACCOUNTNAME": "financial",
    "BITCOINADDRESS": "financial",
    "ETHEREUMADDRESS": "financial",
    "LITECOINADDRESS": "financial",
    "BIC": "financial",
    "PIN": "financial",
}


def classify(labels: set[str], text: str) -> str:
    for label in labels:
        if label in CATEGORY_FROM_PII:
            return CATEGORY_FROM_PII[label]
    lowered = text.lower()
    if any(kw in lowered for kw in ("lawyer", "court", "attorney", "deposition", "litigation")):
        return "legal"
    if any(
        kw in lowered
        for kw in ("school", "university", "professor", "transcript", "gpa", "syllabus", "academic")
    ):
        return "academic"
    if any(kw in lowered for kw in (" invoice", "wire transfer", "ledger", "balance sheet")):
        return "financial"
    if any(
        kw in lowered
        for kw in ("discharge", "patient", "hospital", "clinic", "diagnosis", "treatment")
    ):
        return "medical"
    if any(
        kw in lowered for kw in ("dmv", "passport office", "social security admin", "visa", "uscis")
    ):
        return "government"
    if any(
        kw in lowered
        for kw in ("dear ", "regards", "sincerely", "kind regards", "email:", "phone:", "@")
    ):
        return "emails"
    return "operations"


LABEL_TO_REDACT_TYPE: dict[str, str] = {
    "EMAIL": "EMAIL",
    "PHONENUMBER": "PHONE_E164",
    "PHONEIMEI": "PHONE_E164",
    "CREDITCARDNUMBER": "CREDIT_CARD",
    "CREDITCARDISSUER": "CREDIT_CARD",
    "CREDITCARDCVV": "CREDIT_CARD",
    "IBAN": "IBAN",
    "ACCOUNTNUMBER": "CREDIT_CARD",
    "ACCOUNTNAME": "CREDIT_CARD",
    "SSN": "SSN_US",
    "VEHICLEVIN": "URL",
    "VEHICLEVRM": "URL",
    "TAXNUM": "SSN_US",
    "DRIVERLICENSENUM": "URL",
    "PASSPORT": "URL",
    "IDCARDNUM": "SSN_US",
    "IPV4": "IP_ADDRESS",
    "IPV6": "IP_ADDRESS",
    "IP": "IP_ADDRESS",
    "URL": "URL",
    "USERNAME": "EMAIL",
    "BITCOINADDRESS": "IBAN",
    "ETHEREUMADDRESS": "IBAN",
    "LITECOINADDRESS": "IBAN",
    "SWIFT": "IBAN",
    "BIC": "IBAN",
    "FIRSTNAME": "PERSON",
    "LASTNAME": "PERSON",
    "MIDDLENAME": "PERSON",
    "PREFIX": "PERSON",
    "AGE": "PERSON",
    "GENDER": "PERSON",
    "SEX": "PERSON",
    "HEIGHT": "PERSON",
    "EYECOLOR": "PERSON",
    "ZODIACSIGN": "PERSON",
    "DOB": "PERSON",
    "DATE": "URL",
    "MASKEDNUMBER": "PERSON",
    "BUILDINGNUMBER": "URL",
    "STREET": "URL",
    "CITY": "URL",
    "COUNTY": "URL",
    "STATE": "URL",
    "ZIPCODE": "URL",
    "NEARBYGPSCOORDINATE": "IP_ADDRESS",
    "COUNTRY": "URL",
    "COMPANYNAME": "URL",
    "JOBTITLE": "URL",
    "JOBTYPE": "URL",
    "JOBAREA": "URL",
    "EMPLOYEEID": "URL",
    "SECONDARYADDRESS": "URL",
    "ORDINALDIRECTION": "URL",
    "TIME": "URL",
    "PASSWORD": "URL",
    "USERAGENT": "URL",
    "CURRENCY": "URL",
    "CURRENCYCODE": "URL",
    "CURRENCYNAME": "URL",
    "CURRENCYSYMBOL": "URL",
    "AMOUNT": "URL",
}


@dataclass
class Entry:
    doc_id: str
    text: str
    category: str
    genre: str
    spans: list[tuple[int, int, str]]


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").strip()


def _load_ai4privacy(target_per_category: dict[str, int], seed: int) -> dict[str, list[Entry]]:
    import datasets

    buckets: dict[str, list[Entry]] = defaultdict(list)
    seen_ids: set[str] = set()
    counts: dict[str, int] = defaultdict(int)
    random.Random(seed)

    ds = datasets.load_dataset(SOURCE_DATASET, split="train", streaming=True)
    for example in ds:
        if all(counts[c] >= target_per_category[c] for c in target_per_category):
            break
        if example.get("language") != "en":
            continue
        if not example.get("privacy_mask"):
            continue
        text = _normalize(example["source_text"])
        if not text:
            continue
        labels = {m["label"] for m in example["privacy_mask"]}
        category = classify(labels, text)
        if counts[category] >= target_per_category[category]:
            continue
        if example["id"] in seen_ids:
            continue
        seen_ids.add(example["id"])
        spans: list[tuple[int, int, str]] = []
        for m in example["privacy_mask"]:
            canonical = LABEL_TO_REDACT_TYPE.get(m["label"], "URL")
            spans.append((int(m["start"]), int(m["end"]), canonical))
        spans.sort(key=lambda s: (s[0], s[1]))
        entry = Entry(
            doc_id=f"ai4p_{example['id']}",
            text=text,
            category=category,
            genre="ai4privacy_conversation",
            spans=spans,
        )
        buckets[category].append(entry)
        counts[category] += 1
    return buckets


SYNTHETIC_TEMPLATES: dict[str, list[tuple[str, list[tuple[int, int, str, str]]]]] = {}


def _synth_code(n: int) -> list[Entry]:
    snippets = [
        (
            "API_KEY = 'ak_FAKE_PLACEHOLDER_DO_NOT_USE'\nheaders = {'Authorization': f'Bearer {API_KEY}'}",
            [("ak_FAKE_PLACEHOLDER_DO_NOT_USE", "URL")],
        ),
        (
            "DATABASE_URL = 'postgres://admin:secret@db.internal.example:5432/prod'",
            [("postgres://admin:secret@db.internal.example:5432/prod", "URL")],
        ),
        (
            "CLOUD_PROVIDER_KEY = 'placeholder_cloud_key_do_not_use'",
            [("placeholder_cloud_key_do_not_use", "URL")],
        ),
        (
            "github_token = 'placeholder_github_token_do_not_use'",
            [("placeholder_github_token_do_not_use", "URL")],
        ),
        (
            "card = '0000 0000 0000 0000'\ncvv = '000'\nemail = 'buyer@example.com'",
            [("0000 0000 0000 0000", "CREDIT_CARD"), ("buyer@example.com", "EMAIL")],
        ),
    ]
    out: list[Entry] = []
    for i in range(n):
        snip, span_defs = snippets[i % len(snippets)]
        canonical_spans = []
        for value, cat in span_defs:
            s = snip.index(value)
            canonical_spans.append((s, s + len(value), cat))
        out.append(
            Entry(
                doc_id=f"code_synth_{i:04d}",
                text=snip,
                category="code",
                genre="python_snippet",
                spans=canonical_spans,
            )
        )
    return out


def _synth_files(n: int) -> list[Entry]:
    rows = [
        (
            "user_id,email,phone,ssn,iban\n1,jane@example.com,+1-415-555-0199,000-00-0000,GB00FAKE00000000000000",
            ["jane@example.com", "+1-415-555-0199", "000-00-0000", "GB00FAKE00000000000000"],
            ["EMAIL", "PHONE_E164", "SSN_US", "IBAN"],
        ),
        (
            "export DB_PASSWORD='hunter2'\nexport STRIPE_KEY='tok_FAKE_PLACEHOLDER_DO_NOT_USE'",
            ["hunter2", "tok_FAKE_PLACEHOLDER_DO_NOT_USE"],
            ["URL", "URL"],
        ),
        (
            '{\n  "twilio_sid": "AC_FAKE_PLACEHOLDER_DO_NOT_USE",\n  "twilio_token": "fakefakefakefake"\n}',
            ["AC_FAKE_PLACEHOLDER_DO_NOT_USE"],
            ["URL"],
        ),
        (
            "PLACEHOLDER_KEY_DATA — DO NOT USE",
            ["PLACEHOLDER_KEY_DATA — DO NOT USE"],
            ["URL"],
        ),
        (
            "name,email,phone\nalice,alice@corp.io,555-555-0100\nbob,bob@corp.io,555-555-0101",
            ["alice@corp.io", "bob@corp.io", "555-555-0100", "555-555-0101"],
            ["EMAIL", "EMAIL", "PHONE_E164", "PHONE_E164"],
        ),
    ]
    out: list[Entry] = []
    for i in range(n):
        text, values, cats = rows[i % len(rows)]
        canonical_spans = []
        for value, cat in zip(values, cats, strict=True):
            s = text.index(value)
            canonical_spans.append((s, s + len(value), cat))
        out.append(
            Entry(
                doc_id=f"files_synth_{i:04d}",
                text=text,
                category="files",
                genre="config_or_csv",
                spans=canonical_spans,
            )
        )
    return out


def _synth_logs(n: int) -> list[Entry]:
    lines = [
        "2025-09-06T12:34:56Z INFO auth user=jane@example.com from 192.168.1.42 session=abc123 OK",
        "2025-09-06T12:35:01Z ERROR payment card=0000-0000-0000-0000 cvv=000 amount=$42.00 declined",
        "2025-09-06T12:36:12Z WARN health_phi mrn=FAKE-MRN-0000 patient=John Doe dob=1985-03-15 accessed",
        "2025-09-06T12:40:00Z DEBUG sshd Accepted publickey for ops from 10.0.0.5 port 51234",
        "2025-09-06T12:42:00Z ERROR auth_invalid user=root reason=bad_password from 203.0.113.42",
        "2025-09-06T12:50:00Z INFO api_token issued client=acme-corp scope=read_token",
    ]
    out: list[Entry] = []
    for i in range(n):
        text = lines[i % len(lines)]
        canonical_spans = []
        for value, cat in [
            ("jane@example.com", "EMAIL"),
            ("192.168.1.42", "IP_ADDRESS"),
            ("10.0.0.5", "IP_ADDRESS"),
            ("203.0.113.42", "IP_ADDRESS"),
            ("0000-0000-0000-0000", "CREDIT_CARD"),
            ("FAKE-MRN-0000", "SSN_US"),
            ("acme-corp", "URL"),
        ]:
            if value in text:
                s = text.index(value)
                canonical_spans.append((s, s + len(value), cat))
        out.append(
            Entry(
                doc_id=f"logs_synth_{i:04d}",
                text=text,
                category="logs",
                genre="structured_log",
                spans=canonical_spans,
            )
        )
    return out


def _synth_terminal(n: int) -> list[Entry]:
    sessions = [
        "$ ssh admin@db.internal\nadmin@db.internal password:\nLast login: Fri Sep 6 from 10.0.0.7",
        "$ export TOKEN=$(curl -s -u api:secret https://internal.example.com/token)\n$ echo $TOKEN\ntok_FAKE_PLACEHOLDER_DO_NOT_USE",
        "$ mysql -u root -p'hunter2' -h 127.0.0.1 prod\nmysql> SELECT ssn FROM users LIMIT 1;\n000-00-0000",
        "$ scp backup.tar.gz deploy@10.0.0.20:/srv/backup/\ndeploy@10.0.0.20 password:",
        "$ aws s3 cp s3://internal-bucket/secret.json .\ndownload: s3://internal-bucket/secret.json to ./secret.json",
    ]
    out: list[Entry] = []
    for i in range(n):
        text = sessions[i % len(sessions)]
        canonical_spans = []
        for value, cat in [
            ("10.0.0.7", "IP_ADDRESS"),
            ("10.0.0.20", "IP_ADDRESS"),
            ("127.0.0.1", "IP_ADDRESS"),
            ("tok_FAKE_PLACEHOLDER_DO_NOT_USE", "URL"),
            ("hunter2", "URL"),
            ("000-00-0000", "SSN_US"),
        ]:
            if value in text:
                s = text.index(value)
                canonical_spans.append((s, s + len(value), cat))
        out.append(
            Entry(
                doc_id=f"terminal_synth_{i:04d}",
                text=text,
                category="terminal",
                genre="shell_session",
                spans=canonical_spans,
            )
        )
    return out


def _synth_government(n: int) -> list[Entry]:
    samples = [
        "Driver's License #: D_FAKE_PLACEHOLDER (State of California). Issued 03/14/2022. Name: Jane Q. Public. Address: 123 Main St, Sacramento, CA 95814.",
        "Passport No. FAKE-PASSPORT-NUMBER (United States of America). Date of Birth: 1985-03-15. Place of Birth: Boston, MA.",
        "Social Security Number: 000-00-0000. Name on record: John H. Doe. Filing status: Single. AGI: $84,200.",
        "Form I-9, Employment Eligibility Verification. Alien Registration Number: A-FAKE-NUMBER. SSN: 000-00-0000.",
        "Voter Registration Card. County: King. State: WA. Registration #: WA-VR-FAKE-NUMBER.",
    ]
    out: list[Entry] = []
    for i in range(n):
        text = samples[i % len(samples)]
        canonical_spans = []
        for value, cat in [
            ("000-00-0000", "SSN_US"),
            ("D_FAKE_PLACEHOLDER", "URL"),
            ("FAKE-PASSPORT-NUMBER", "URL"),
            ("A-FAKE-NUMBER", "URL"),
            ("WA-VR-FAKE-NUMBER", "URL"),
            ("jane@example.com", "EMAIL"),
        ]:
            if value in text:
                s = text.index(value)
                canonical_spans.append((s, s + len(value), cat))
        out.append(
            Entry(
                doc_id=f"gov_synth_{i:04d}",
                text=text,
                category="government",
                genre="government_form",
                spans=canonical_spans,
            )
        )
    return out


def _synth_legal(n: int) -> list[Entry]:
    samples = [
        "Case No. FAKE-CASE-NUMBER. In the Superior Court of California, County of San Francisco. Smith v. Jones Industries. Counsel for Plaintiff: Jane Doe, Esq. (SBN 245678).",
        "Settlement Agreement. This Agreement is entered into between Acme Corp and Beta Holdings. Effective Date: 09/01/2026. Governing Law: Delaware.",
        "Deposition of John Q. Witness, taken on 08/15/2026 at the offices of Smith & Associates, 555 California St, San Francisco, CA 94104.",
        "Promissory Note. Principal Amount: $50,000.00. Borrower: Jane Smith. Lender: First National Bank. Annual Interest Rate: 6.5%.",
        "Subpoena Duces Tecum. To: Records Custodian, Acme Hospital. Re: Patient FAKE-MRN-0000. Date of Service: 09/05/2026.",
    ]
    out: list[Entry] = []
    for i in range(n):
        text = samples[i % len(samples)]
        canonical_spans = []
        for value, cat in [
            ("Jane Doe, Esq.", "PERSON"),
            ("John Q. Witness", "PERSON"),
            ("Jane Smith", "PERSON"),
            ("FAKE-MRN-0000", "SSN_US"),
            ("$50,000.00", "URL"),
            ("FAKE-CASE-NUMBER", "URL"),
            ("jane@example.com", "EMAIL"),
            ("555 California St, San Francisco, CA 94104", "URL"),
        ]:
            if value in text:
                s = text.index(value)
                canonical_spans.append((s, s + len(value), cat))
        out.append(
            Entry(
                doc_id=f"legal_synth_{i:04d}",
                text=text,
                category="legal",
                genre="legal_filing",
                spans=canonical_spans,
            )
        )
    return out


SYNTH_FUNCS = {
    "code": _synth_code,
    "files": _synth_files,
    "logs": _synth_logs,
    "terminal": _synth_terminal,
    "government": _synth_government,
    "legal": _synth_legal,
}


def _write(out_dir: Path, ai4p_buckets: dict[str, list[Entry]]) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    docs_path = out_dir / "documents.jsonl"
    anns_path = out_dir / "annotations.jsonl"

    counts: dict[str, int] = defaultdict(int)
    with (
        docs_path.open("w", encoding="utf-8") as doc_f,
        anns_path.open("w", encoding="utf-8") as ann_f,
    ):
        for category, entries in ai4p_buckets.items():
            for e in entries:
                doc_f.write(
                    json.dumps(
                        {
                            "id": e.doc_id,
                            "text": e.text,
                            "category": e.category,
                            "genre": e.genre,
                            "source": "ai4privacy_200k",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                ann_f.write(
                    json.dumps(
                        {
                            "doc_id": e.doc_id,
                            "spans": [
                                {"start": s, "end": ed, "category": "mandatory", "type": t}
                                for s, ed, t in e.spans
                            ],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                counts[category] += 1
        for category, synth_fn in SYNTH_FUNCS.items():
            for e in synth_fn(SYNTH_PER_CATEGORY.get(category, 3)):
                doc_f.write(
                    json.dumps(
                        {
                            "id": e.doc_id,
                            "text": e.text,
                            "category": e.category,
                            "genre": e.genre,
                            "source": "synthetic",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                ann_f.write(
                    json.dumps(
                        {
                            "doc_id": e.doc_id,
                            "spans": [
                                {"start": s, "end": en, "category": "mandatory", "type": t}
                                for s, en, t in e.spans
                            ],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                counts[category] += 1

    readme = out_dir / "README.md"
    readme.write_text(
        textwrap.dedent(
            f"""
            # ai4privacy/pii-masking-200k → RedactionBench conversion

            | field | value |
            |-------|-------|
            | source dataset | {SOURCE_DATASET} |
            | snapshot | {SOURCE_VERSION} |
            | sample seed | {SAMPLE_SEED} |
            | min per category | {MIN_PER_CATEGORY} |
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
            """
        ).strip()
        + "\n"
    )
    return dict(counts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("tests/fixtures/pii200k"))
    parser.add_argument("--min-per-category", type=int, default=MIN_PER_CATEGORY)
    parser.add_argument("--max-per-category", type=int, default=MAX_PER_CATEGORY)
    parser.add_argument("--seed", type=int, default=SAMPLE_SEED)
    args = parser.parse_args()

    unstructured_cats = [
        "academic",
        "emails",
        "financial",
        "government",
        "legal",
        "medical",
        "operations",
    ]
    target = {c: args.min_per_category for c in unstructured_cats}

    print(f"Streaming {SOURCE_DATASET}...", file=sys.stderr)
    buckets = _load_ai4privacy(target, args.seed)
    for category, entries in buckets.items():
        if len(entries) > args.max_per_category:
            buckets[category] = entries[: args.max_per_category]

    counts = _write(args.out, buckets)
    print(f"Wrote {args.out}/documents.jsonl and annotations.jsonl", file=sys.stderr)
    for c in sorted(counts):
        print(f"  {c:12s}: {counts[c]}", file=sys.stderr)
    print(f"  total       : {sum(counts.values())}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
