from __future__ import annotations

import asyncio

from app.inference.detector import Detector, Span
from app.redaction.apply import dedupe_overlaps


async def multi_pass_detect(
    detector: Detector,
    text: str,
    entity_types: list[str],
    passes: int = 2,
    max_passes: int = 3,
) -> list[Span]:
    """Run detection `passes` times and union the results.

    For token-classification detectors, masking between passes does not
    change the model's behavior (it already labels every token), so we
    simply re-detect. The benefit of multi-pass is catching entities that
    a single stochastic or context-sensitive pass missed; for fully
    deterministic NER models this still serves as a defensive default.

    `passes` is capped at `max_passes` to bound cost per request; an
    excessive value raises rather than guessing at an acceptable one.
    """
    if passes < 1:
        raise ValueError("passes must be >= 1")
    if passes > max_passes:
        raise ValueError(f"passes must be <= max_passes ({max_passes}); got {passes}")
    if passes == 1:
        spans = await detector.detect(text, entity_types)
        return dedupe_overlaps(spans)

    results = await asyncio.gather(*(detector.detect(text, entity_types) for _ in range(passes)))
    unioned: list[Span] = []
    for batch in results:
        unioned.extend(batch)
    return dedupe_overlaps(unioned)
