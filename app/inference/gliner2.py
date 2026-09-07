from __future__ import annotations

import asyncio
import os
from pathlib import Path

from app.inference.detector import Span


def normalize_gliner2_result(text: str, result: object) -> list[Span]:
    """Convert a gliner2 result into a sorted list of Spans.

    Accepts both:
      * a `gliner2` result object with `.entities` attribute, and
      * a plain `dict` with an `'entities'` key (the current gliner2
        0.3+ API returns a dict).

    Each value is either a dict with `text/confidence/start/end` keys
    or a raw string (position found via `str.find`).
    """
    if isinstance(result, dict):
        entities = result.get("entities") or {}
    else:
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


def run_extract_entities(model: object, text: str, labels: list[str], threshold: float) -> object:
    """Blocking gliner2 inference; run inside a worker thread via to_thread."""
    return model.extract_entities(  # type: ignore[attr-defined]
        text,
        labels,
        threshold=threshold,
        include_confidence=True,
        include_spans=True,
    )


class GLiNER2Detector:
    """GLiNER2 zero-shot NER detector bound to the app's shared resource.

    A single instance is created in the app lifespan; the model is loaded
    once (from the verified local snapshot, never the network), and
    inference runs in a bounded thread pool so concurrent requests cannot
    overload the CPU and never block the event loop.

    Failures stay loud: detection before load(), a download failure, or a
    missing cached snapshot all raise instead of degrading to regex.
    """

    name = "gliner2"

    def __init__(
        self,
        model_name: str = "fastino/gliner2-privacy-filter-PII-multi",
        model_revision: str = "main",
        model_cache: str | os.PathLike[str] = "./models_cache",
        threshold: float = 0.5,
        device: str = "cpu",
        concurrency: int = 2,
        local_files_only: bool = True,
        model: object | None = None,
    ) -> None:
        self.model_name = model_name
        self.model_revision = model_revision
        self.model_cache = Path(model_cache)
        self.threshold = threshold
        self.device = device
        self.concurrency = concurrency
        self.local_files_only = local_files_only
        self.model = model  # None until load(); injectable in tests
        self.semaphore: asyncio.Semaphore | None = None

    @property
    def is_loaded(self) -> bool:
        """Return True once the underlying GLiNER2 model has been loaded."""
        return self.model is not None

    async def load(self) -> None:
        """Load the GLiNER2 model from the local cache on a worker thread.

        Idempotent: a second call when the model is already loaded is a
        no-op. ``HF_HOME`` is pinned to ``self.model_cache`` and
        ``local_files_only`` is honoured so the detector never reaches
        the network.
        """
        if self.model is not None:
            return
        os.environ.setdefault("HF_HOME", str(self.model_cache))
        self.model_cache.mkdir(parents=True, exist_ok=True)
        if self.semaphore is None:
            self.semaphore = asyncio.Semaphore(self.concurrency)

        def load_blocking() -> object:
            """Synchronously load the GLiNER2 model; runs in a worker thread."""
            from gliner2 import GLiNER2

            return GLiNER2.from_pretrained(
                self.model_name,
                revision=self.model_revision,
                cache_dir=str(self.model_cache),
                local_files_only=self.local_files_only,
                map_location=self.device,
            )

        self.model = await asyncio.to_thread(load_blocking)

    async def detect(self, text: str, entity_types: list[str]) -> list[Span]:
        """Run zero-shot NER on ``text`` and return the detected spans.

        Raises:
            RuntimeError: If :meth:`load` has not been called yet.

        Args:
            text: The input text.
            entity_types: List of zero-shot labels; an empty list
                uses :func:`default_labels`.

        Returns:
            The detected spans, sorted by start offset.
        """
        if not self.is_loaded:
            raise RuntimeError(
                "GLiNER2 model is not loaded; call load() in the app lifespan "
                "before serving requests."
            )
        model = self.model
        labels = entity_types if entity_types else default_labels()
        semaphore = self.semaphore
        if semaphore is None:
            semaphore = asyncio.Semaphore(self.concurrency)
            self.semaphore = semaphore
        threshold = self.threshold
        async with semaphore:
            result = await asyncio.to_thread(run_extract_entities, model, text, labels, threshold)
        return normalize_gliner2_result(text, result)

    async def warmup(self) -> None:
        """Load the model and run one detection so the first request is not slow."""
        await self.load()
        await self.detect("warmup", [self.name])


def default_labels() -> list[str]:
    """Return the default zero-shot labels for the GLiNER2 PII model."""
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
