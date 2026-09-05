from __future__ import annotations

import os
from pathlib import Path

from app.inference.detector import Span
from app.observability import INFERENCE_LATENCY


def normalize_gliner2_result(text: str, result: object) -> list[Span]:
    """Convert a gliner2 result object into a sorted list of Spans.

    Accepts both dict values (with text/confidence/start/end keys) and
    raw string values (position found via str.find).
    """
    entities = getattr(result, "entities", None) or {}
    spans: list[Span] = []
    for label, values in entities.items():
        canonical = label.upper()
        for value in values:
            if isinstance(value, dict):
                text_value = value.get("text", "")
                confidence = float(value.get("confidence", 1.0))
                start = value.get("start")
                end = value.get("end")
                if start is None or end is None:
                    start = text.find(str(text_value))
                    end = start + len(str(text_value)) if start >= 0 else -1
            else:
                text_value = str(value)
                confidence = 1.0
                start = text.find(text_value)
                end = start + len(text_value) if start >= 0 else -1
            if start is None or end is None or start < 0 or end < 0:
                continue
            spans.append(Span(start=start, end=end, type=canonical, confidence=confidence))
    spans.sort(key=lambda s: (s.start, s.end))
    return spans


class GLiNER2Detector:
    """GLiNER2 zero-shot NER detector.

    Loads `fastino/gliner2-privacy-filter-PII-multi` from `model_cache`
    (downloads on first run if cache is empty). Runs on CPU at float32.
    """

    name = "gliner2"

    def __init__(
        self,
        model_name: str = "fastino/gliner2-privacy-filter-PII-multi",
        model_cache: str | os.PathLike[str] = "./models_cache",
        threshold: float = 0.5,
        device: str = "cpu",
    ) -> None:
        self._model_name = model_name
        self._model_cache = Path(model_cache)
        self._threshold = threshold
        self._device = device
        self._model = None

    def _load(self) -> None:
        if self._model is not None:
            return
        os.environ.setdefault("HF_HOME", str(self._model_cache))
        self._model_cache.mkdir(parents=True, exist_ok=True)
        from gliner2 import GLiNER2  # type: ignore[import-not-found]

        self._model = GLiNER2.from_pretrained(self._model_name)

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
        self._load()
        labels = entity_types if entity_types else self._default_labels()
        with INFERENCE_LATENCY.labels(detector=self.name).time():
            result = self._model.extract_entities(  # type: ignore[union-attr]
                text,
                labels,
                threshold=self._threshold,
                include_confidence=True,
                include_spans=True,
            )
        return normalize_gliner2_result(text, result)

    async def warmup(self) -> None:
        self._load()
        await self.detect("warmup", ["person"])

    @staticmethod
    def _default_labels() -> list[str]:
        return [
            "person",
            "full_name",
            "first_name",
            "middle_name",
            "last_name",
            "date_of_birth",
            "email",
            "phone_number",
            "address",
            "street_address",
            "city",
            "state_or_region",
            "postal_code",
            "country",
            "government_id",
            "national_id_number",
            "passport_number",
            "drivers_license_number",
            "license_number",
            "tax_id",
            "tax_number",
            "bank_account",
            "account_number",
            "routing_number",
            "iban",
            "payment_card",
            "card_number",
            "card_expiry",
            "card_cvv",
            "username",
            "ip_address",
            "account_id",
            "sensitive_account_id",
            "password",
            "secret",
            "api_key",
            "access_token",
            "recovery_code",
            "sensitive_date",
            "document_date",
            "expiration_date",
            "transaction_date",
        ]
