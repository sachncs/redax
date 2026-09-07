"""Stage 3: fuse regex hits and model hits into one deduped span list."""

from __future__ import annotations

from dataclasses import dataclass

from app.inference.detector import Span
from app.redaction.apply import dedupe_overlaps


@dataclass(frozen=True)
class ConsensusConfig:
    """Configuration for the consensus-fusion stage.

    Attributes:
        min_model_confidence: Model spans below this confidence are
            dropped from the fused output.
    """

    min_model_confidence: float = 0.5


DEFAULT_CONSENSUS_CONFIG = ConsensusConfig()


def overlaps(a: Span, b: Span) -> bool:
    """Return ``True`` when two half-open spans share at least one character."""
    return a.start < b.end and b.start < a.end


def fuse(
    regex_spans: tuple[Span, ...],
    model_spans: tuple[Span, ...],
    config: ConsensusConfig = DEFAULT_CONSENSUS_CONFIG,
) -> tuple[Span, ...]:
    """Combine regex and model spans into a single deduped, ordered list.

    Rules (in priority order):

    1. Regex spans are always included (the safety net).
    2. A model span that overlaps a regex span is kept only when its
       confidence is at least ``config.min_model_confidence``; otherwise
       the regex span wins.
    3. A model span that does not overlap any regex span is kept when
       its confidence is at least the threshold.
    4. The resulting list is deduped via ``app.redaction.apply.dedupe_overlaps``.

    Args:
        regex_spans: Spans from the deterministic regex detector.
        model_spans: Spans from the encoder model stage.
        config: Threshold + reserved-for-future options.

    Returns:
        A tuple of deduped ``Span`` instances, ordered by start.
    """
    kept: list[Span] = list(regex_spans)

    for span in model_spans:
        if span.confidence < config.min_model_confidence:
            continue
        if any(overlaps(span, r) for r in regex_spans):
            continue
        kept.append(span)

    deduped = dedupe_overlaps(kept)
    return tuple(deduped)
