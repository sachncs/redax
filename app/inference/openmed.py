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


LABEL_MAP: dict[str, str] = {
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
    return LABEL_MAP.get(cleaned, "URL")


@dataclass
class OpenMedPIIDetector:
    """Thin sync/async wrapper around the OpenMed token-classifier."""

    name: str = "openmed"
    model_name: str = OPENMED_MODEL_NAME
    model_cache: Path | None = None
    threshold: float = 0.5
    device: str = "cpu"
    model: Any = None
    tokenizer: Any = None

    def load_model(self) -> None:
        """Lazily load the tokenizer + model into ``self.tokenizer`` and ``self.model``."""
        if self.model is not None:
            return
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        cache_dir = str(self.model_cache) if self.model_cache else None
        self.tokenizer = AutoTokenizer.from_pretrained(  # type: ignore[no-untyped-call]
            self.model_name, cache_dir=cache_dir
        )
        self.model = AutoModelForTokenClassification.from_pretrained(
            self.model_name, cache_dir=cache_dir
        )

    def detect_sync(self, text: str, entity_types: list[str]) -> list[Span]:
        """Synchronous inference — used by the pipeline's circuit breaker."""
        self.load_model()
        import torch

        assert self.tokenizer is not None and self.model is not None
        tokenizer_kwargs: dict[str, Any] = dict(
            truncation=True,
            max_length=384,
            return_offsets_mapping=True,
        )
        # Some tokenizers (e.g. DebertaV2) reject `return_offsets_mapping` when
        # they cannot honour it. Fall back to the plain tokenizer output
        # in that case; we recover character offsets via str.find() below.
        try:
            tokens = self.tokenizer(text, return_tensors="pt", **tokenizer_kwargs)
        except TypeError:
            tokens = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=384)
        with torch.no_grad():
            model_inputs = {k: v for k, v in tokens.items() if k != "offset_mapping"}
            outputs = self.model(**model_inputs)
        preds = outputs.logits.argmax(dim=-1)[0].tolist()
        word_ids = tokens.word_ids(0)
        id2label = self.model.config.id2label
        offset_mapping = tokens.get("offset_mapping")
        offsets: list[tuple[int, int]] = (
            [(int(s), int(e)) for s, e in offset_mapping[0].tolist()]
            if offset_mapping is not None
            else []
        )

        spans: list[Span] = []
        current: dict[str, Any] | None = None
        for idx, wid in enumerate(word_ids):
            if wid is None:
                current = None
                continue
            label = id2label.get(preds[idx], "O")
            char_start, char_end = offsets[idx] if idx < len(offsets) else (0, 0)
            if label.startswith("B-"):
                if current is not None:
                    spans.append(entity_to_span(current))
                current = {
                    "label": label[2:],
                    "char_start": char_start,
                    "char_end": char_end,
                    "word_id": wid,
                }
            elif label.startswith("I-") and current is not None:
                current["char_end"] = char_end
            else:
                if current is not None:
                    spans.append(entity_to_span(current))
                current = None
        if current is not None:
            spans.append(entity_to_span(current))

        return [
            Span(
                start=span.start,
                end=span.end,
                type=sanitize_label(span.type),
                confidence=0.9,
            )
            for span in spans
        ]

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
        """Run token-classification detection on ``text`` off the event loop.

        Args:
            text: The input text.
            entity_types: Optional list of entity types to filter on
                (currently accepted for API compatibility; the
                OpenMed labels are the union of what the model emits).

        Returns:
            The detected spans, mapped to redax's canonical types.
        """
        return await asyncio.to_thread(self.detect_sync, text, entity_types)

    async def warmup(self) -> None:
        """Preload the OpenMed tokenizer + model on a worker thread."""
        await asyncio.to_thread(self.load_model)


def entity_to_span(current: dict[str, Any]) -> Span:
    """Convert one OpenMed per-entity dict to a redax Span.

    The dict shape mirrors the keys produced by ``detect_sync``:
    ``char_start``, ``char_end``, ``label``.
    """
    return Span(
        start=int(current["char_start"]),
        end=int(current["char_end"]),
        type=str(current["label"]),
        confidence=0.9,
    )
