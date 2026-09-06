"""Stage 4: fallback when the model stage is unavailable."""

from __future__ import annotations

from app.inference.detector import Span


def from_regex_only(spans: tuple[Span, ...]) -> tuple[Span, ...]:
    """Return the fused spans unchanged.

    Default fallback used by the pipeline when the model circuit breaker
    is open. Kept as a hook so callers can override (e.g. log a regression
    event) without changing the pipeline signature.

    Args:
        spans: The fused spans from the consensus stage.

    Returns:
        The same spans, unmodified.
    """
    return spans
