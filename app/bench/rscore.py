"""R-Score metric from RedactionBench (Brynjolfsson et al. 2026, Section 3.3).

The metric is computed at the unit (entity) level:

    mandatory entity r:    (n_r, d_r) = (mean over s in r of |s cap P| / |s|, 1)
    contextual entity y:   empty active subset -> no scoring term
                           else (n_y, d_y) = (0, 1 - mean coverage of active s)
                           exception: if the document has no mandatory spans
                                      AND A_y(P) is non-empty, the contextual
                                      entity becomes a positive contributor:
                                      (n_y, d_y) = (mean coverage, 1)
    false positive f:      (n_f, d_f) = (0, 1 + 1{ f covers an entire gap >= 3 })

R-Score = (sum n) / (sum d), with the sum taken over all entities and FPs that
emit a non-empty term.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from statistics import mean

from app.bench.annotation import LabelledSpan, SpanCategory
from app.bench.combinators import build_connector_structure
from app.bench.fusion import (
    fused_entity_groups,
    selected_contextual_spans,
)

_GAP_THRESHOLD = 3


def _prediction_chars(spans: Iterable[LabelledSpan], text_len: int) -> list[tuple[int, int]]:
    """Convert a list of prediction spans to disjoint character ranges.

    Predictions may overlap; we union them into disjoint runs before scoring.
    Returns the disjoint runs as (start, end) tuples, sorted by start.
    """
    intervals = sorted(((s.start, s.end) for s in spans), key=lambda p: (p[0], p[1]))
    merged: list[tuple[int, int]] = []
    for s, e in intervals:
        s = max(0, min(s, text_len))
        e = max(0, min(e, text_len))
        if s >= e:
            continue
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _support_runs(spans: Iterable[LabelledSpan], text_len: int) -> list[tuple[int, int]]:
    """Union of mandatory + contextual spans as disjoint runs."""
    return _prediction_chars(spans, text_len)


def false_positive_runs(
    prediction_runs: list[tuple[int, int]],
    support_runs: list[tuple[int, int]],
    text_len: int,
) -> list[tuple[int, int]]:
    """Compute maximal contiguous FP runs: redacted chars outside support.

    An FP run is a maximal interval `[a, b)` such that every char in `[a, b)`
    is in some prediction run AND no char in `[a, b)` is in any support run.
    """
    if not prediction_runs:
        return []

    def overlaps(a: int, b: int, runs: list[tuple[int, int]]) -> bool:
        return any(s < b and e > a for s, e in runs)

    fps: list[tuple[int, int]] = []
    for ps, pe in prediction_runs:
        cursor = ps
        while cursor < pe:
            while cursor < pe and overlaps(cursor, cursor + 1, support_runs):
                cursor += 1
            if cursor >= pe:
                break
            start = cursor
            while cursor < pe and not overlaps(cursor, cursor + 1, support_runs):
                cursor += 1
            fps.append((start, cursor))
    return fps


def _gap_runs(support_runs: list[tuple[int, int]], text_len: int) -> list[tuple[int, int]]:
    """Return disjoint contiguous non-support regions, possibly empty.

    A "gap" for R-Score purposes is any contiguous block of non-support
    characters in the text, including leading and trailing regions.
    """
    if text_len == 0:
        return []
    gaps: list[tuple[int, int]] = []
    cursor = 0
    for s, e in support_runs:
        if cursor < s:
            gaps.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < text_len:
        gaps.append((cursor, text_len))
    return gaps


def coverage(span: LabelledSpan, pred_runs: list[tuple[int, int]]) -> float:
    """Character coverage of `span` by the prediction, in `[0, 1]`."""
    total = span.end - span.start
    if total <= 0:
        return 0.0
    hit = 0
    for ps, pe in pred_runs:
        if pe <= span.start:
            continue
        if ps >= span.end:
            break
        hit += min(pe, span.end) - max(ps, span.start)
    return hit / total


@dataclass(frozen=True)
class EntityScore:
    """The (n, d) term contributed by one entity to R-Score."""

    entity_index: int
    kind: str
    n: float
    d: float
    active_members: tuple[LabelledSpan, ...] = ()


@dataclass(frozen=True)
class FPScore:
    """The (n, d) term contributed by one false positive."""

    fp_index: int
    n: float
    d: float
    covers_entire_gap: bool


@dataclass(frozen=True)
class RDocument:
    """Per-document scoring result.

    `n` and `d` are the aggregates over entities and FPs. `r_score` is
    `n / d` (or 0.0 if `d == 0`). `mandatory_entities`, `contextual_entities`,
    `false_positives` are the contributing terms.
    """

    doc_id: str
    mandatory_entities: tuple[EntityScore, ...]
    contextual_entities: tuple[EntityScore, ...]
    false_positives: tuple[FPScore, ...]
    skipped_contextual: int = 0
    skipped_reason: str = ""
    n: float = 0.0
    d: float = 0.0
    r_score: float = 0.0

    def has_mandatory(self) -> bool:
        return bool(self.mandatory_entities)


@dataclass(frozen=True)
class RScoreReport:
    """Aggregate R-Score report across a corpus of documents."""

    per_document: dict[str, RDocument]
    corpus_mean: float
    per_category: dict[str, dict[str, float]] = field(default_factory=dict)

    def percentiles(self) -> dict[str, float]:
        if not self.per_document:
            return {"p20": 0.0, "p50": 0.0, "mean": 0.0}
        scores = sorted(d.r_score for d in self.per_document.values())
        return {
            "p20": _percentile(scores, 20),
            "p50": _percentile(scores, 50),
            "mean": mean(scores),
        }


def _percentile(sorted_scores: list[float], pct: float) -> float:
    if not sorted_scores:
        return 0.0
    if len(sorted_scores) == 1:
        return sorted_scores[0]
    rank = (pct / 100.0) * (len(sorted_scores) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return sorted_scores[lo]
    frac = rank - lo
    return sorted_scores[lo] + frac * (sorted_scores[hi] - sorted_scores[lo])


def score_document(
    text: str,
    annotation_spans: list[LabelledSpan],
    prediction_spans: list[LabelledSpan],
    doc_id: str = "",
) -> RDocument:
    """Score one document's predictions against its annotation.

    Pipeline:
        1. Normalize predictions into disjoint prediction runs.
        2. Build support = union of mandatory + contextual annotation spans.
        3. Run Algorithms 1 & 2 to obtain red fusion groups, contextual
           components, and fused entities.
        4. Compute (n, d) for each mandatory entity, contextual entity, and FP.
        5. Aggregate into RDocument.
    """
    text_len = len(text)
    pred_runs = _prediction_chars(prediction_spans, text_len)
    support_spans = [
        s
        for s in annotation_spans
        if s.category
        in (
            SpanCategory.MANDATORY,
            SpanCategory.CONTEXTUAL,
        )
    ]
    support_runs = _support_runs(support_spans, text_len)

    mandatory = [s for s in annotation_spans if s.category is SpanCategory.MANDATORY]
    contextual = [s for s in annotation_spans if s.category is SpanCategory.CONTEXTUAL]

    structure = build_connector_structure(text, mandatory, contextual)
    selected = selected_contextual_spans(contextual, prediction_spans, structure)
    entities = fused_entity_groups(mandatory, contextual, structure, text)

    red_scores: list[EntityScore] = []
    for idx, group in enumerate(entities.red_entities):
        members = list(group.members)
        if not members:
            continue
        cov = mean(coverage(s, pred_runs) for s in members)
        red_scores.append(EntityScore(entity_index=idx, kind="mandatory", n=cov, d=1.0))

    contextual_scores: list[EntityScore] = []
    skipped = 0
    has_mandatory = bool(mandatory)
    all_ctx_active = (not has_mandatory) and bool(contextual)
    selected_ids = {(s.start, s.end, s.category) for s in selected}

    for idx, group in enumerate(entities.contextual_entities):
        members = list(group.members)
        active = [m for m in members if (m.start, m.end, m.category) in selected_ids]
        if not active:
            skipped += 1
            continue
        cov = mean(coverage(s, pred_runs) for s in active)
        if all_ctx_active:
            contextual_scores.append(
                EntityScore(
                    entity_index=idx,
                    kind="contextual-optional",
                    n=cov,
                    d=1.0,
                    active_members=tuple(active),
                )
            )
        else:
            contextual_scores.append(
                EntityScore(
                    entity_index=idx,
                    kind="contextual-penalty",
                    n=0.0,
                    d=1.0 - cov,
                    active_members=tuple(active),
                )
            )

    fp_runs = false_positive_runs(pred_runs, support_runs, text_len)
    gap_runs = _gap_runs(support_runs, text_len)
    gaps_ge3 = [g for g in gap_runs if (g[1] - g[0]) >= _GAP_THRESHOLD]

    def _covers_entire_gap(fp: tuple[int, int]) -> bool:
        return any(fp[0] <= g[0] and fp[1] >= g[1] for g in gaps_ge3)

    fp_scores = [
        FPScore(
            fp_index=i,
            n=0.0,
            d=2.0 if _covers_entire_gap(fp) else 1.0,
            covers_entire_gap=_covers_entire_gap(fp),
        )
        for i, fp in enumerate(fp_runs)
    ]

    total_n = sum(e.n for e in red_scores) + sum(e.n for e in contextual_scores)
    total_d = (
        sum(e.d for e in red_scores)
        + sum(e.d for e in contextual_scores)
        + sum(f.d for f in fp_scores)
    )
    r = (total_n / total_d) if total_d > 0 else 0.0

    return RDocument(
        doc_id=doc_id,
        mandatory_entities=tuple(red_scores),
        contextual_entities=tuple(contextual_scores),
        false_positives=tuple(fp_scores),
        skipped_contextual=skipped,
        skipped_reason="empty_active_subset" if skipped else "",
        n=total_n,
        d=total_d,
        r_score=r,
    )


def rscore(
    corpus: list[tuple[str, str, list[LabelledSpan], list[LabelledSpan]]],
    per_doc_categories: dict[str, str] | None = None,
) -> RScoreReport:
    """Score a corpus and produce an aggregated report.

    Each input is `(doc_id, text, annotation_spans, prediction_spans)`.
    `per_doc_categories` optionally maps `doc_id` -> category label for the
    per-category breakdown.
    """
    per_doc: dict[str, RDocument] = {}
    for doc_id, text, ann, pred in corpus:
        per_doc[doc_id] = score_document(text, ann, pred, doc_id=doc_id)

    if not per_doc:
        return RScoreReport(per_document={}, corpus_mean=0.0, per_category={})

    scores = [d.r_score for d in per_doc.values()]
    corpus_mean = mean(scores)

    per_category: dict[str, list[float]] = {}
    if per_doc_categories:
        for doc_id, rdoc in per_doc.items():
            cat = per_doc_categories.get(doc_id, "")
            if not cat:
                continue
            per_category.setdefault(cat, []).append(rdoc.r_score)
    per_category_summaries = {
        cat: {"mean": mean(v), "p50": _percentile(sorted(v), 50), "n": len(v)}
        for cat, v in per_category.items()
    }

    return RScoreReport(
        per_document=per_doc,
        corpus_mean=corpus_mean,
        per_category=per_category_summaries,
    )


__all__ = [
    "EntityScore",
    "FPScore",
    "RDocument",
    "RScoreReport",
    "rscore",
    "score_document",
]
