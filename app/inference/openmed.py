"""OpenMed-PII-SuperClinical-Large-434M-v1 wrapper.

This is the winner of the Phase 1 model survey
(`docs/models-survey.md`). Apache-2.0 licensed DeBERTa-v3-large fine-tune
with 54 entity types, including the healthcare/PHI labels redax needs.

The detector is intentionally thin: it wraps the `transformers`
`AutoModelForTokenClassification` pipeline. Model loading is gated by the
`Scripts/download_models.py` SHA-256 manifest; if the cache is missing or
the hash mismatches, the detector raises and the pipeline's circuit
breaker takes over.

`sanitize_label` maps OpenMed's 54 fine-grained labels to one of redax's
seven canonical regex-style categories + `PERSON`. The mapping is
intentionally conservative: a label we don't recognise falls back to
`URL` rather than being dropped, so the audit log shows the unexpected
output.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.inference.detector import Span

log = logging.getLogger(__name__)

OPENMED_MODEL_NAME = "OpenMed/OpenMed-PII-SuperClinical-Large-434M-v1"
OPENMED_SHA256_MANIFEST_KEY = "openmed-pii-superclinical-large-434m-v1"


_LABEL_MAP: dict[str, str] = {
    "account_number": "CREDIT_CARD",
    "api_key": "URL",
    "bank_routing_number": "CREDIT_CARD",
    "certificate_license_number": "URL",
    "credit_card_number": "CREDIT_CARD",
    "credit_debit_card": "CREDIT_CARD",
    "cvv": "CREDIT_CARD",
    "device_identifier": "URL",
    "email": "EMAIL",
    "employee_id": "URL",
    "fax_number": "PHONE_E164",
    "health_plan_beneficiary_number": "SSN_US",
    "ipv4": "IP_ADDRESS",
    "ipv6": "IP_ADDRESS",
    "mac_address": "URL",
    "medical_record_number": "SSN_US",
    "passport_number": "URL",
    "phone_number": "PHONE_E164",
    "social_security_number": "SSN_US",
    "ssn": "SSN_US",
    "tax_id": "SSN_US",
    "url": "URL",
    "iban": "IBAN",
    "account_id": "URL",
    "username": "EMAIL",
    "driver's_license_number": "URL",
    "license_number": "URL",
    "first_name": "PERSON",
    "last_name": "PERSON",
    "name": "PERSON",
    "date_of_birth": "PERSON",
    "age": "PERSON",
    "gender": "PERSON",
    "occupation": "URL",
    "address": "URL",
    "city": "URL",
    "state": "URL",
    "zipcode": "URL",
    "postcode": "URL",
    "street_address": "URL",
    "date": "URL",
    "time": "URL",
    "company_name": "URL",
    "organization": "URL",
}


def sanitize_label(label: str) -> str:
    """Map an OpenMed label to one of redax's canonical Span types.

    Unknown labels fall back to `URL` so the caller's audit log records the
    unexpected output rather than silently dropping it.
    """
    if not label:
        return "URL"
    cleaned = label.lower().strip().replace(" ", "_").replace("-", "_")
    return _LABEL_MAP.get(cleaned, "URL")


@dataclass
class OpenMedPIIDetector:
    """Thin sync/async wrapper around the OpenMed token-classifier."""

    name: str = "openmed"
    model_name: str = OPENMED_MODEL_NAME
    model_cache: Path | None = None
    threshold: float = 0.5
    device: str = "cpu"
    _model: Any = None
    _tokenizer: Any = None

    def _load(self) -> None:
        if self._model is not None:
            return
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        cache_dir = str(self.model_cache) if self.model_cache else None
        self._tokenizer = AutoTokenizer.from_pretrained(  # type: ignore[no-untyped-call]
            self.model_name, cache_dir=cache_dir
        )
        self._model = AutoModelForTokenClassification.from_pretrained(
            self.model_name, cache_dir=cache_dir
        )

    def detect_sync(self, text: str, entity_types: list[str]) -> list[Span]:
        """Synchronous inference — used by the pipeline's circuit breaker."""
        self._load()
        import torch

        assert self._tokenizer is not None and self._model is not None
        inputs = self._tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=384,
        )
        with torch.no_grad():
            outputs = self._model(**inputs)
        preds = outputs.logits.argmax(dim=-1)[0].tolist()
        word_ids = inputs.word_ids(0)
        id2label = self._model.config.id2label

        spans: list[Span] = []
        current: dict[str, Any] | None = None
        for idx, wid in enumerate(word_ids):
            if wid is None:
                current = None
                continue
            label = id2label.get(preds[idx], "O")
            if label.startswith("B-"):
                if current is not None:
                    spans.append(self._to_span(text, current))
                current = {
                    "label": label[2:],
                    "start": inputs["input_ids"][0][idx],
                    "end": inputs["input_ids"][0][idx],
                    "word_id": wid,
                }
            elif label.startswith("I-") and current is not None:
                current["end"] = inputs["input_ids"][0][idx]
            else:
                if current is not None:
                    spans.append(self._to_span(text, current))
                current = None
        if current is not None:
            spans.append(self._to_span(text, current))

        offsets = inputs.get("offset_mapping")
        if offsets is not None:
            resolved: list[Span] = []
            for span in spans:
                start, end = _resolve_offsets(text, offsets, span)
                resolved.append(
                    Span(start=start, end=end, type=sanitize_label(span.type), confidence=0.9)
                )
            return resolved

        decoded: list[Span] = []
        for span in spans:
            decoded_text = self._tokenizer.decode([span.start, span.end])
            s = text.find(decoded_text)
            if s == -1:
                continue
            decoded.append(
                Span(
                    start=s,
                    end=s + len(decoded_text),
                    type=sanitize_label(str(span.type)),
                    confidence=0.9,
                )
            )
        return decoded

    @staticmethod
    def _to_span(text: str, current: dict[str, Any]) -> Span:
        return Span(
            start=current["start"],
            end=current["end"] + 1,
            type=str(current["label"]),
            confidence=0.9,
        )

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
        return await asyncio.to_thread(self.detect_sync, text, entity_types)

    async def warmup(self) -> None:
        await asyncio.to_thread(self._load)


def _resolve_offsets(
    text: str,
    offsets: Any,
    span: Span,
) -> tuple[int, int]:
    for _i, (s, e) in enumerate(offsets[0].tolist()):
        if s == span.start:
            return int(s), int(e)
    return 0, min(len(text), span.end)
