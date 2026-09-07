from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.inference.detector import Detector, Span
from app.inference.regex import RegexDetector


@dataclass
class StrategyResult:
    """The output of one :meth:`Strategy.run` invocation.

    Attributes:
        text: The text after the strategy has been applied.
        spans: The spans the strategy operated on (detected for
            detection-based strategies, or the input spans for
            substitution-only strategies).
        relex_map: Original-entity-to-placeholder map; populated by
            relex-capable strategies (e.g. ``Deid`` with ``relex=True``).
        substitutions: One (span, replacement_string) per applied
            substitution. The Redactor uses this to keep reported
            span coordinates aligned with the original input.
    """

    text: str
    spans: list[Span]
    relex_map: dict[str, str]
    substitutions: list[tuple[Span, str]] | None = None


@runtime_checkable
class Strategy(Protocol):
    """A per-field action that turns (text, optional spans, config) into a
    redacted result with optional relex mapping."""

    name: str

    async def run(
        self,
        text: str,
        spans: list[Span],
        config: dict[str, Any],
    ) -> StrategyResult: ...


class Skip:
    """Returns the input untouched. Used for non-PII fields like 'gender'."""

    name = "passThrough"

    async def run(self, text: str, spans: list[Span], config: dict[str, Any]) -> StrategyResult:
        """Return the input text and spans unchanged (no PII redaction)."""
        return StrategyResult(text=text, spans=[], relex_map={})


class Mask:
    """Replace every span with a configured format string."""

    name = "mask"

    async def run(self, text: str, spans: list[Span], config: dict[str, Any]) -> StrategyResult:
        """Replace every input span with the configured format string.

        The format is read from ``config["format"]`` and defaults to
        ``"[REDACTED]"``.
        """
        from app.redaction.apply import apply_spans

        fmt = config.get("format", "[REDACTED]")
        masked = apply_spans(text, spans, [fmt] * len(spans))
        return StrategyResult(
            text=masked,
            spans=spans,
            relex_map={},
            substitutions=[(s, fmt) for s in spans],
        )


class Hash:
    """Replace every span with a deterministic SHA256-derived tag."""

    name = "hash"

    def __init__(self, salt: str = "") -> None:
        self.salt = salt

    async def run(self, text: str, spans: list[Span], config: dict[str, Any]) -> StrategyResult:
        """Replace every input span with ``[HASH:<first-N-of-SHA256(salt+text)>]``.

        Deterministic: the same input text + same salt always produces
        the same placeholder, so the same entity in different
        documents maps to the same token.
        """
        import hashlib

        from app.redaction.apply import apply_spans

        replacements: list[str] = []
        for span in spans:
            digest = hashlib.sha256(
                f"{self.salt}{text[span.start : span.end]}".encode()
            ).hexdigest()
            length = int(config.get("length", 8))
            replacements.append(f"[HASH:{digest[:length]}]")
        masked = apply_spans(text, spans, replacements)
        return StrategyResult(
            text=masked,
            spans=spans,
            relex_map={},
            substitutions=list(zip(spans, replacements, strict=True)),
        )


class Regex:
    """Run the regex detector on `text` and apply mask format."""

    name = "regex"

    def __init__(self, detector: RegexDetector | None = None) -> None:
        self.detector = detector

    def resolve_detector(self) -> RegexDetector:
        """Return the bound detector, lazily constructing a default.

        Returns:
            The ``RegexDetector`` instance attached to this strategy.
        """
        if self.detector is None:
            self.detector = RegexDetector()
        return self.detector

    async def run(self, text: str, spans: list[Span], config: dict[str, Any]) -> StrategyResult:
        """Run the regex detector over ``text`` and mask each hit.

        Entity-type filter and format string are read from
        ``config["entity_types"]`` and ``config["format"]``.
        """
        from app.redaction.apply import apply_spans

        detector = self.resolve_detector()
        entity_types = config.get("entity_types", [])
        detected = await detector.detect(text, entity_types)
        fmt = config.get("format", "[REDACTED]")
        masked = apply_spans(text, detected, [fmt] * len(detected))
        return StrategyResult(
            text=masked,
            spans=detected,
            relex_map={},
            substitutions=[(s, fmt) for s in detected],
        )


class Deid:
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
        self.detector = detector
        self.detectors = detectors or {}
        self.max_passes = max_passes

    async def run(self, text: str, spans: list[Span], config: dict[str, Any]) -> StrategyResult:
        """Run multi-pass NER detection and emit relex or format placeholders.

        Reads ``config["detector"]`` (optional name into ``self.detectors``),
        ``config["entity_types"]``, ``config["multi_pass"]``, ``config["relex"]``,
        and ``config["format"]`` (only when ``relex`` is false). Raises
        :class:`ValueError` if a policy names a detector that was not
        registered.
        """
        from app.inference.multipass import multi_pass_detect
        from app.redaction.apply import apply_spans

        chosen = self.detector
        per_policy = config.get("detector")
        if per_policy is not None:
            if per_policy not in self.detectors:
                raise ValueError(
                    f"policy requests unknown detector {per_policy!r}; "
                    f"available: {sorted(self.detectors)}"
                )
            chosen = self.detectors[per_policy]

        entity_types = config.get("entity_types", [])
        passes = int(config.get("multi_pass", 1))
        relex = bool(config.get("relex", False))

        detected = await multi_pass_detect(
            chosen, text, entity_types, passes, max_passes=self.max_passes
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
        return StrategyResult(
            text=masked,
            spans=detected,
            relex_map=relex_map,
            substitutions=list(zip(detected, replacements, strict=True)),
        )
