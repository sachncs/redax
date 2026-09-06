"""Algorithm 2 from the RedactionBench paper: prediction-dependent contextual
selection and entity fusion.

`SelectedContextualSpans` returns the set of yellow spans that count as
"attempted" given a model's redaction output. Starting from yellow spans
directly hit by predictions, it pulls in additional yellow spans via the
combinator structure: if any span in a contextual component is selected, the
whole component is selected; if any delimiter of a pair range is selected,
the whole pair range is selected. This repeats until fixpoint.

`FusedEntityGroups` partitions red and yellow spans into entities (the units
over which R-Score is computed). Red entities follow `red_fusion_groups`
from Algorithm 1; contextual entities follow a contextual graph that links
yellow spans inside the same context component or pair range. Single-character
yellow spans that are pure connector markers are dropped.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.bench.annotation import LabelledSpan, SpanCategory
from app.bench.combinators import ConnectorStructure, SpanGroup


def intersect(span: LabelledSpan, pred_starts: list[int], pred_ends: list[int]) -> bool:
    """Return True if `span` is hit by any prediction.

    `pred_starts` and `pred_ends` are the sorted start/end offsets of the
    prediction spans (half-open intervals). We binary-search for the first
    prediction whose end > span.start, then check if its start < span.end.
    """
    import bisect

    if not pred_starts:
        return False
    idx = bisect.bisect_right(pred_ends, span.start)
    if idx >= len(pred_starts):
        return False
    return pred_starts[idx] < span.end


def selected_contextual_spans(
    target_yellow: list[LabelledSpan],
    pred_merged: list[LabelledSpan],
    structure: ConnectorStructure,
) -> list[LabelledSpan]:
    """Run the SelectedContextualSpans subroutine of Algorithm 2.

    Returns the yellow spans that count as "attempted" by the prediction
    under the combinator-aware propagation rules.
    """
    if not target_yellow:
        return []

    by_id: dict[tuple[int, int, SpanCategory], LabelledSpan] = {
        (s.start, s.end, s.category): s for s in target_yellow
    }
    pred_starts = sorted(p.start for p in pred_merged)
    pred_ends = sorted(p.end for p in pred_merged)

    def yellow_at_pos(pos: int) -> LabelledSpan | None:
        for s in target_yellow:
            if s.start <= pos < s.end:
                return s
        return None

    selected_ids: set[tuple[int, int, SpanCategory]] = set()
    for y in target_yellow:
        if intersect(y, pred_starts, pred_ends):
            selected_ids.add((y.start, y.end, y.category))

    if not selected_ids:
        return []

    component_lookup: dict[tuple[int, int, SpanCategory], SpanGroup] = {}
    for context_component in structure.context_components:
        for span in context_component.members:
            component_lookup[(span.start, span.end, span.category)] = context_component

    changed = True
    while changed:
        changed = False
        for sid in list(selected_ids):
            ctx_component = component_lookup.get(sid)
            if ctx_component is None:
                continue
            for member in ctx_component.members:
                mid = (member.start, member.end, member.category)
                if mid not in selected_ids:
                    selected_ids.add(mid)
                    changed = True
        for pr in structure.pair_ranges:
            o_span = yellow_at_pos(pr.o)
            l_span = yellow_at_pos(pr.end)
            if o_span is None and l_span is None:
                continue
            triggered = (
                o_span is not None and (o_span.start, o_span.end, o_span.category) in selected_ids
            ) or (
                l_span is not None and (l_span.start, l_span.end, l_span.category) in selected_ids
            )
            if not triggered:
                continue
            for span in target_yellow:
                if span.start >= pr.o and span.end <= pr.end:
                    mid = (span.start, span.end, span.category)
                    if mid not in selected_ids:
                        selected_ids.add(mid)
                        changed = True

    return [by_id[sid] for sid in selected_ids]


@dataclass(frozen=True)
class FusedEntities:
    """The output of FusedEntityGroups: red entities and contextual entities."""

    red_entities: tuple[SpanGroup, ...]
    contextual_entities: tuple[SpanGroup, ...]


def marker_positions(
    yellow: list[LabelledSpan],
    structure: ConnectorStructure,
    text: str,
) -> set[int]:
    """Build the set of yellow-span start positions that are connector markers.

    A connector marker is a single-character yellow span whose character is
    in `structure.effective_markers`.
    """
    marker_chars: set[str] = set(structure.effective_markers)
    out: set[int] = set()
    for s in yellow:
        if s.end - s.start != 1:
            continue
        if text[s.start] in marker_chars:
            out.add(s.start)
    return out


def fused_entity_groups(
    target_red: list[LabelledSpan],
    target_yellow: list[LabelledSpan],
    structure: ConnectorStructure,
    text: str,
) -> FusedEntities:
    """Run FusedEntityGroups from Algorithm 2.

    Red entities are exactly the `red_fusion_groups` from Algorithm 1.
    Contextual entities come from a contextual graph that links yellow spans
    inside the same context component or pair range; single-character yellow
    spans that are pure connector markers and remain singletons are dropped.
    """
    red_entities = tuple(structure.red_fusion_groups)

    yellow_set = {(s.start, s.end, s.category): s for s in target_yellow}
    adjacent: dict[tuple[int, int, SpanCategory], set[tuple[int, int, SpanCategory]]] = {
        k: set() for k in yellow_set
    }

    def link(a: LabelledSpan, b: LabelledSpan) -> None:
        ka = (a.start, a.end, a.category)
        kb = (b.start, b.end, b.category)
        if ka == kb:
            return
        if ka in adjacent and kb in adjacent:
            adjacent[ka].add(kb)
            adjacent[kb].add(ka)

    for group in structure.context_components:
        yellow_in_comp = [m for m in group.members if m.category is SpanCategory.CONTEXTUAL]
        for i in range(len(yellow_in_comp)):
            for j in range(i + 1, len(yellow_in_comp)):
                link(yellow_in_comp[i], yellow_in_comp[j])

    for pr in structure.pair_ranges:
        inside = [s for s in target_yellow if s.start >= pr.o and s.end <= pr.end + 1]
        for i in range(len(inside)):
            for j in range(i + 1, len(inside)):
                link(inside[i], inside[j])

    seen: set[tuple[int, int, SpanCategory]] = set()
    components: list[list[LabelledSpan]] = []
    for key, _span in yellow_set.items():
        if key in seen:
            continue
        comp: list[LabelledSpan] = []
        stack = [key]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            comp.append(yellow_set[cur])
            for neighbor in adjacent[cur]:
                if neighbor not in seen:
                    stack.append(neighbor)
        comp.sort(key=lambda s: (s.start, s.end))
        components.append(comp)

    components.sort(key=lambda c: c[0].start)

    positions = marker_positions(target_yellow, structure, text)

    contextual_entities: list[SpanGroup] = []
    for comp in components:
        if len(comp) == 1 and comp[0].start in positions:
            continue
        contextual_entities.append(SpanGroup(members=tuple(comp)))

    return FusedEntities(
        red_entities=red_entities,
        contextual_entities=tuple(contextual_entities),
    )
