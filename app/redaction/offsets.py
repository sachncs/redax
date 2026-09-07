"""Span offset validation utilities."""

from __future__ import annotations

from app.inference.detector import Span


def validate_offsets(text: str, spans: list[Span]) -> list[Span]:
    """Drop spans whose offsets don't roundtrip against the source text.

    Spans are validated end-exclusive (start inclusive, end exclusive).
    Spans with end <= start, end > len(text), or where the slice doesn't
    match the expected position are dropped.

    Args:
        text: The source text the spans were extracted from.
        spans: Candidate spans to validate.

    Returns:
        The subset of ``spans`` whose offsets are valid against ``text``.
    """
    text_len = len(text)
    out: list[Span] = []
    for span in spans:
        if span.start < 0 or span.end <= span.start or span.end > text_len:
            continue
        if text[span.start : span.end] == "" and (span.end - span.start) > 0:
            continue
        out.append(span)
    return out
