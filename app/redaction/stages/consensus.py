"""Stage 3: consensus. Fuse regex hits and model hits.

Rules (in priority order):

1. If a regex span and a model span overlap, the model span is kept
   *only* if it has confidence ≥ `min_model_confidence` (default 0.5).
   Otherwise the regex span wins.
2. Regex spans are *always* included (they are the safety net).
3. Model spans that do NOT overlap any regex span are included if
   confidence ≥ `min_model_confidence`.
4. Spans are deduped and overlap-resolved with the existing
   `app.redaction.apply.dedupe_overlaps`.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.inference.detector import Span
from app.redaction.apply import dedupe_overlaps


@dataclass(frozen=True)
class ConsensusConfig:
    min_model_confidence: float = 0.5


DEFAULT_CONSENSUS_CONFIG = ConsensusConfig()


def overlaps(a: Span, b: Span) -> bool:
    return a.start < b.end and b.start < a.end


def fuse(
    regex_spans: tuple[Span, ...],
    model_spans: tuple[Span, ...],
    config: ConsensusConfig = DEFAULT_CONSENSUS_CONFIG,
) -> tuple[Span, ...]:
    """Combine the two span lists into a single deduped, ordered list.

    Returns a tuple of `Span` (the redax canonical Span — no label
    transformations). Caller is responsible for downstream substitution.
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
