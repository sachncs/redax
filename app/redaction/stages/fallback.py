"""Stage 4: fallback. When the model stage is unavailable, return only the
regex hits so the caller still gets a deterministic, conservative answer.
"""

from __future__ import annotations

from app.inference.detector import Span


def from_regex_only(spans: tuple[Span, ...]) -> tuple[Span, ...]:
    """Default fallback that returns the fused spans unchanged.

    Kept as a hook so callers can override (e.g. log a `regression` event)
    without changing the pipeline signature.
    """
    return spans
