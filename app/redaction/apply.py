"""Span application utilities: substitute, inverse-map, dedupe."""

from __future__ import annotations

import bisect
from collections.abc import Callable

from app.inference.detector import Span


def apply_spans(text: str, spans: list[Span], replacement: list[str]) -> str:
    """Substitute ``spans`` in ``text`` with ``replacement`` (one per span).

    Spans must not overlap. Callers should deduplicate (e.g. via
    ``dedupe_overlaps``) before invoking this function. The implementation
    sorts right-to-left and mutates a working buffer; this is correct for
    non-overlapping spans.

    Args:
        text: The source text to apply substitutions to.
        spans: The non-overlapping spans to substitute.
        replacement: A list of replacement strings, one per span. To
            broadcast a single string across every span, wrap it: e.g.
            ``replacement=[fmt] * len(spans)``.

    Returns:
        The text with each span replaced.

    Raises:
        ValueError: If ``len(replacement) != len(spans)``.
    """
    if not spans:
        return text
    if len(replacement) != len(spans):
        raise ValueError("replacement list length must match spans length")

    ordered = sorted(range(len(spans)), key=lambda i: spans[i].start, reverse=True)
    out = text
    for i in ordered:
        span = spans[i]
        out = out[: span.start] + replacement[i] + out[span.end :]
    return out


def inverse_position_remap(
    text: str,
    spans: list[Span],
    replacements: list[str],
) -> Callable[[int], int]:
    """Return a function mapping a position in the substituted text back into ``text``.

    Assumes the same substitution layout as ``apply_spans``: kept segments
    survive verbatim and map linearly, while any position inside a
    replaced range maps to the start of that span. Spans must be
    non-overlapping.

    Args:
        text: The original source text.
        spans: The non-overlapping spans that were replaced.
        replacements: The replacement strings (one per span).

    Returns:
        A function ``remap(position) -> int`` that maps a position in
        the substituted text back to its origin in ``text``. Positions
        inside a replaced range map to the start of that range.

    Raises:
        ValueError: If ``len(replacements) != len(spans)``.
    """
    if len(replacements) != len(spans):
        raise ValueError("replacement list length must match spans length")

    ordered = sorted(zip(spans, replacements, strict=True), key=lambda pr: pr[0].start)
    segments: list[tuple[int, int, int, bool]] = []
    new_pos = 0
    prev = 0
    for span, replacement in ordered:
        if span.start > prev:
            segments.append((new_pos, prev, span.start - prev, False))
            new_pos += span.start - prev
        segments.append((new_pos, span.start, len(replacement), True))
        new_pos += len(replacement)
        prev = span.end
    if prev < len(text):
        segments.append((new_pos, prev, len(text) - prev, False))

    starts = [segment[0] for segment in segments]

    def remap(position: int) -> int:
        if position < 0:
            return 0
        index = bisect.bisect_right(starts, position) - 1
        new_start, old_start, _length, replaced = segments[index]
        if replaced:
            return old_start
        return old_start + (position - new_start)

    return remap


def dedupe_overlaps(spans: list[Span]) -> list[Span]:
    """Drop the lower-confidence span whenever two spans overlap.

    Returns spans sorted by start. Ties broken by longer span first, then
    higher confidence.

    Args:
        spans: Input spans in any order.

    Returns:
        Spans with overlaps resolved by dropping the lower-confidence one.
    """
    if not spans:
        return []
    by_start = sorted(spans, key=lambda s: (s.start, -(s.end - s.start), -s.confidence))
    kept: list[Span] = []
    for span in by_start:
        if any(
            span.start < existing.end
            and span.end > existing.start
            and span.confidence <= existing.confidence
            for existing in kept
        ):
            continue
        kept = [k for k in kept if not (span.start < k.end and span.end > k.start)]
        kept.append(span)
    return sorted(kept, key=lambda s: s.start)
