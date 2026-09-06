from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.inference.detector import Detector, Span
from app.inference.regex_detector import RegexDetector


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

    async def apply(
        self,
        text: str,
        spans: list[Span],
        config: dict[str, Any],
    ) -> StrategyResult: ...


class PassThrough:
    """Returns the input untouched. Used for non-PII fields like 'gender'."""

    name = "passThrough"

    async def apply(self, text: str, spans: list[Span], config: dict[str, Any]) -> StrategyResult:
        return StrategyResult(text=text, spans=[], relex_map={})


class Mask:
    """Replace every span with a configured format string."""

    name = "mask"

    async def apply(self, text: str, spans: list[Span], config: dict[str, Any]) -> StrategyResult:
        from app.redaction.apply import apply_spans

        fmt = config.get("format", "[REDACTED]")
        masked = apply_spans(text, spans, fmt)
        return StrategyResult(text=masked, spans=spans, relex_map={})


class Hash:
    """Replace every span with a deterministic SHA256-derived tag."""

    name = "hash"

    def __init__(self, salt: str = "") -> None:
        self._salt = salt

    async def apply(self, text: str, spans: list[Span], config: dict[str, Any]) -> StrategyResult:
        import hashlib

        from app.redaction.apply import apply_spans

        replacements: list[str] = []
        for span in spans:
            digest = hashlib.sha256(
                f"{self._salt}{text[span.start : span.end]}".encode()
            ).hexdigest()
            length = int(config.get("length", 8))
            replacements.append(f"[HASH:{digest[:length]}]")
        masked = apply_spans(text, spans, replacements)
        return StrategyResult(text=masked, spans=spans, relex_map={})


class Regex:
    """Run the regex detector on `text` and apply mask format."""

    name = "regex"

    def __init__(self, detector: RegexDetector | None = None) -> None:
        self._detector = detector

    def _get_detector(self) -> RegexDetector:
        if self._detector is None:
            self._detector = RegexDetector()
        return self._detector

    async def apply(self, text: str, spans: list[Span], config: dict[str, Any]) -> StrategyResult:
        from app.redaction.apply import apply_spans

        detector = self._get_detector()
        entity_types = config.get("entity_types", [])
        detected = await detector.detect(text, entity_types)
        fmt = config.get("format", "[REDACTED]")
        masked = apply_spans(text, detected, fmt)
        return StrategyResult(text=masked, spans=detected, relex_map={})


class AutoDeID:
    """Run a NER detector (possibly multi-pass) and apply relex/placeholders.

    Relex populates relex_map so the upstream redactor can swap originals
    back in. When relex is false, every span is replaced with the
    configured format string.

    The detector is selected by the policy via `config["detector"]` when a
    `detectors` map is supplied; otherwise the bound default detector is
    used. An unknown name raises instead of silently falling back.
    """

    name = "autoDeID"

    def __init__(
        self,
        detector: Detector,
        detectors: Mapping[str, Detector] | None = None,
        max_passes: int = 3,
    ) -> None:
        self._detector = detector
        self._detectors = detectors or {}
        self._max_passes = max_passes

    async def apply(self, text: str, spans: list[Span], config: dict[str, Any]) -> StrategyResult:
        from app.inference.multi_pass import multi_pass_detect
        from app.redaction.apply import apply_spans

        chosen = self._detector
        per_policy = config.get("detector")
        if per_policy is not None:
            if per_policy not in self._detectors:
                raise ValueError(
                    f"policy requests unknown detector {per_policy!r}; "
                    f"available: {sorted(self._detectors)}"
                )
            chosen = self._detectors[per_policy]

        entity_types = config.get("entity_types", [])
        passes = int(config.get("multi_pass", 1))
        relex = bool(config.get("relex", False))

        detected = await multi_pass_detect(
            chosen, text, entity_types, passes, max_passes=self._max_passes
        )

        if relex:
            replacements = [f"[{s.type.upper()}_{i:04d}]" for i, s in enumerate(detected)]
            relex_map = {
                text[s.start : s.end]: r for s, r in zip(detected, replacements, strict=True)
            }
        else:
            fmt = config.get("format", "[REDACTED]")
            replacements = [fmt] * len(detected)
            relex_map = {}

        masked = apply_spans(text, detected, replacements)
        return StrategyResult(text=masked, spans=detected, relex_map=relex_map)
