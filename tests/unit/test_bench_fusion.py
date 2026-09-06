from __future__ import annotations

from app.bench.annotation import LabelledSpan, SpanCategory
from app.bench.combinators import build_connector_structure
from app.bench.fusion import fused_entity_groups, selected_contextual_spans


def _structure(text: str, red: list[LabelledSpan], yellow: list[LabelledSpan]):
    return build_connector_structure(text, red, yellow)


def test_selected_contextual_spans_pulls_via_context_component() -> None:
    text = "abc def"
    red = []
    yellow = [
        LabelledSpan(0, 3, SpanCategory.CONTEXTUAL),
        LabelledSpan(4, 7, SpanCategory.CONTEXTUAL),
    ]
    structure = _structure(text, red, yellow)
    selected = selected_contextual_spans(
        yellow, [LabelledSpan(0, 3, SpanCategory.MANDATORY)], structure
    )
    assert {(s.start, s.end) for s in selected} == {(0, 3), (4, 7)}


def test_selected_contextual_spans_pulls_via_pair_range_delimiter() -> None:
    text = '"foo"'
    yellow = [LabelledSpan(1, 4, SpanCategory.CONTEXTUAL)]
    structure = _structure(text, [], yellow)
    selected = selected_contextual_spans(
        yellow, [LabelledSpan(0, 1, SpanCategory.MANDATORY)], structure
    )
    assert {(s.start, s.end) for s in selected} == set()


def test_selected_contextual_spans_propagates_until_fixpoint() -> None:
    text = "abc def"
    yellow = [
        LabelledSpan(0, 3, SpanCategory.CONTEXTUAL),
        LabelledSpan(4, 7, SpanCategory.CONTEXTUAL),
    ]
    structure = _structure(text, [], yellow)
    pred = [LabelledSpan(0, 3, SpanCategory.MANDATORY)]
    selected = selected_contextual_spans(yellow, pred, structure)
    assert {(s.start, s.end) for s in selected} == {(0, 3), (4, 7)}


def test_fused_entity_groups_links_via_context_component() -> None:
    text = "abc def"
    yellow = [
        LabelledSpan(0, 3, SpanCategory.CONTEXTUAL),
        LabelledSpan(4, 7, SpanCategory.CONTEXTUAL),
    ]
    structure = _structure(text, [], yellow)
    entities = fused_entity_groups([], yellow, structure, text)
    assert len(entities.contextual_entities) == 1
    assert {(s.start, s.end) for s in entities.contextual_entities[0].members} == {(0, 3), (4, 7)}


def test_fused_entity_groups_links_via_pair_range() -> None:
    text = "[ABC]"
    yellow = [LabelledSpan(1, 4, SpanCategory.CONTEXTUAL)]
    structure = _structure(text, [], yellow)
    entities = fused_entity_groups([], yellow, structure, text)
    assert len(entities.contextual_entities) == 1


def test_fused_entity_groups_drops_singleton_marker() -> None:
    text = '[ "quoted" ]'
    yellow = [
        LabelledSpan(1, 9, SpanCategory.CONTEXTUAL),
        LabelledSpan(2, 8, SpanCategory.CONTEXTUAL),
    ]
    structure = _structure(text, [], yellow)
    entities = fused_entity_groups([], yellow, structure, text)
    kept = [m for g in entities.contextual_entities for m in g.members]
    assert (2, 8) in {(s.start, s.end) for s in kept}


def test_fused_entity_groups_red_uses_red_fusion() -> None:
    text = "127.0.0.1"
    red = [
        LabelledSpan(0, 3, SpanCategory.MANDATORY),
        LabelledSpan(4, 7, SpanCategory.MANDATORY),
        LabelledSpan(8, 9, SpanCategory.MANDATORY),
    ]
    structure = _structure(text, red, [])
    entities = fused_entity_groups(red, [], structure, text)
    assert len(entities.red_entities) == 1
    members = entities.red_entities[0].members
    assert {(s.start, s.end) for s in members} == {(0, 3), (4, 7), (8, 9)}
