from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.inference.detector import Span


@dataclass
class StrategyResult:
    text: str
    spans: list[Span]
    relex_map: dict[str, str]


@runtime_checkable
class Strategy(Protocol):
    """A per-field action that turns (text, optional spans, config) into a
    redacted result with optional relex mapping."""

    name: str

    def apply(
        self,
        text: str,
        spans: list[Span],
        config: dict,
    ) -> StrategyResult: ...


class PassThrough:
    """Returns the input untouched. Used for non-PII fields like 'gender'."""

    name = "passThrough"

    def apply(self, text: str, spans: list[Span], config: dict) -> StrategyResult:
        return StrategyResult(text=text, spans=[], relex_map={})


class Mask:
    """Replace every span with a configured format string."""

    name = "mask"

    def apply(self, text: str, spans: list[Span], config: dict) -> StrategyResult:
        from app.redaction.apply import apply_spans  # noqa: PLC0415

        fmt = config.get("format", "[REDACTED]")
        masked = apply_spans(text, spans, fmt)
        return StrategyResult(text=masked, spans=spans, relex_map={})


class Hash:
    """Replace every span with a deterministic SHA256-derived tag."""

    name = "hash"

    def __init__(self, salt: str = "") -> None:
        self._salt = salt

    def apply(self, text: str, spans: list[Span], config: dict) -> StrategyResult:
        from app.redaction.apply import apply_spans  # noqa: PLC0415

        import hashlib  # noqa: PLC0415

        replacements: list[str] = []
        for span in spans:
            digest = hashlib.sha256(f"{self._salt}{text[span.start : span.end]}".encode()).hexdigest()
            length = int(config.get("length", 8))
            replacements.append(f"[HASH:{digest[:length]}]")
        masked = apply_spans(text, spans, replacements)
        return StrategyResult(text=masked, spans=spans, relex_map={})


class Regex:
    """Run the regex detector on `text` and apply mask format."""

    name = "regex"

    def __init__(self) -> None:
        self._detector = None

    def _get_detector(self):
        if self._detector is None:
            from app.inference.regex_detector import RegexDetector  # noqa: PLC0415

            self._detector = RegexDetector()
        return self._detector

    def apply(self, text: str, spans: list[Span], config: dict) -> StrategyResult:
        from app.redaction.apply import apply_spans  # noqa: PLC0415

        detector = self._get_detector()
        entity_types = config.get("entity_types", [])
        # We need to call the sync detect() because strategies are sync; the
        # detector's detect() is async. Run it on a fresh event loop.
        import asyncio  # noqa: PLC0415

        detected = asyncio.run(detector.detect(text, entity_types))
        fmt = config.get("format", "[REDACTED]")
        masked = apply_spans(text, detected, fmt)
        return StrategyResult(text=masked, spans=detected, relex_map={})


class AutoDeID:
    """Run a NER detector (possibly multi-pass) and apply relex/placeholders.

    Calls into the configured Detector and optional multi_pass_detect when
    passes > 1. Relex is handled in a later milestone; this strategy
    currently emits [TYPE] placeholders so the upstream redactor can swap
    them out.
    """

    name = "autoDeID"

    def __init__(self, detector) -> None:
        self._detector = detector

    def apply(self, text: str, spans: list[Span], config: dict) -> StrategyResult:
        import asyncio  # noqa: PLC0415

        from app.inference.multi_pass import multi_pass_detect  # noqa: PLC0415
        from app.redaction.apply import apply_spans  # noqa: PLC0415

        entity_types = config.get("entity_types", [])
        passes = int(config.get("multi_pass", 1))
        relex = bool(config.get("relex", False))

        async def run() -> list[Span]:
            return await multi_pass_detect(self._detector, text, entity_types, passes)

        detected = asyncio.run(run())

        if relex:
            replacements = [f"[{s.type.upper()}_{i:04d}]" for i, s in enumerate(detected)]
            relex_map = {text[s.start : s.end]: r for s, r in zip(detected, replacements)}
        else:
            fmt = config.get("format", "[REDACTED]")
            replacements = [fmt] * len(detected)
            relex_map = {}

        masked = apply_spans(text, detected, replacements)
        return StrategyResult(text=masked, spans=detected, relex_map=relex_map)
