from __future__ import annotations

from app.inference.detector import Span


def apply_spans(text: str, spans: list[Span], replacement: str | list[str] = "[REDACTED]") -> str:
    """Substitute the spans in `text` with `replacement` (or one per span).

    Spans must not overlap. Callers should deduplicate (e.g. via
    `dedupe_overlaps`) before invoking this function. The implementation
    sorts right-to-left and mutates a working buffer; this is correct for
    non-overlapping spans.
    """
    if not spans:
        return text

    if isinstance(replacement, str):
        replacements = {i: replacement for i in range(len(spans))}
    else:
        if len(replacement) != len(spans):
            raise ValueError("replacement list length must match spans length")
        replacements = {i: r for i, r in enumerate(replacement)}

    ordered = sorted(range(len(spans)), key=lambda i: spans[i].start, reverse=True)
    out = text
    for i in ordered:
        span = spans[i]
        out = out[: span.start] + replacements[i] + out[span.end :]
    return out


def dedupe_overlaps(spans: list[Span]) -> list[Span]:
    """Drop the lower-confidence span whenever two spans overlap.

    Returns spans sorted by start. Ties broken by longer span first, then
    higher confidence.
    """
    if not spans:
        return []
    by_start = sorted(spans, key=lambda s: (s.start, -(s.end - s.start), -s.confidence))
    kept: list[Span] = []
    for span in by_start:
        if any(
            span.start < existing.end and span.end > existing.start
            and span.confidence <= existing.confidence
            for existing in kept
        ):
            continue
        kept = [k for k in kept if not (span.start < k.end and span.end > k.start)]
        kept.append(span)
    return sorted(kept, key=lambda s: s.start)
