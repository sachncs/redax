from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.inference.detector import Span


@dataclass
class RelexResult:
    text: str
    relex_map: dict[str, str]


def relexicalize(
    text: str,
    spans: list[Span],
    seed: str | None = None,
    cross_request_cache: dict[str, str] | None = None,
) -> RelexResult:
    """Hiding-in-Plain-Sight relexicalizer.

    Each unique entity text becomes a typed placeholder like
    `[PERSON_0001]`. With a `seed` (e.g. a per-document salt) the same
    entity text always maps to the same placeholder within the call;
    without a seed the placeholder is derived only from the entity text.

    A `cross_request_cache` dict (or any dict-like) is consulted first
    so the same entity string seen in a previous call gets the same
    placeholder across calls. The cache is mutated in place; callers
    that want cross-request persistence should pass a long-lived dict.
    """
    if not spans:
        return RelexResult(text=text, relex_map={})

    cache = cross_request_cache if cross_request_cache is not None else {}
    replacements: dict[str, str] = {}
    counts: dict[str, int] = {}
    out_pairs: list[tuple[Span, str]] = []

    for span in spans:
        entity = text[span.start : span.end]
        canonical_type = span.type.upper()
        cache_key = f"{seed}|{canonical_type}|{entity}" if seed else f"{canonical_type}|{entity}"

        if cache_key in cache:
            placeholder = cache[cache_key]
        else:
            counts[canonical_type] = counts.get(canonical_type, 0) + 1
            placeholder = f"[{canonical_type}_{counts[canonical_type]:04d}]"
            if seed is not None:
                placeholder = with_seed_signature(placeholder, seed)
            cache[cache_key] = placeholder

        replacements[entity] = placeholder
        out_pairs.append((span, placeholder))

    from app.redaction.apply import apply_spans

    masked = apply_spans(
        text,
        [s for s, _ in out_pairs],
        [r for _, r in out_pairs],
    )
    return RelexResult(text=masked, relex_map=replacements)


def with_seed_signature(placeholder: str, seed: str) -> str:
    """Append a short deterministic suffix derived from the seed so that
    different seeds produce visibly different placeholders for the same
    logical entity."""
    digest = hashlib.sha256(f"{seed}|{placeholder}".encode()).hexdigest()[:4]
    return f"{placeholder}-{digest}"
