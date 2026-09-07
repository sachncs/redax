from __future__ import annotations

import pytest

from app.bench.annotation import LabelledSpan, SpanCategory
from app.bench.combinators import (
    PairRange,
    build_connector_structure,
    is_punct_char,
)


def make_labelled_span(
    text: str, sub: str, category: SpanCategory, start: int | None = None
) -> LabelledSpan:
    """Build a LabelledSpan covering the first ``sub`` inside ``text``."""
    if start is None:
        start = text.find(sub)
    assert start >= 0, f"sub not found: {sub!r}"
    return LabelledSpan(start, start + len(sub), category)


WORKED_EXAMPLE_TEXT = 'Vehicle: "5N1AT2MK4FC824170" "2015 Nissan Rogue" plate= 321ABC'


def worked_red_spans() -> list[LabelledSpan]:
    """Mandatory spans from the worked-example vehicle record (VIN + plate)."""
    return [
        make_labelled_span(WORKED_EXAMPLE_TEXT, "5N1AT2MK4FC824170", SpanCategory.MANDATORY),
        make_labelled_span(WORKED_EXAMPLE_TEXT, "321ABC", SpanCategory.MANDATORY),
    ]


def worked_yellow_spans() -> list[LabelledSpan]:
    """Contextual spans from the worked-example vehicle record (quoted strings)."""
    return [
        make_labelled_span(WORKED_EXAMPLE_TEXT, '"', SpanCategory.CONTEXTUAL, start=9),
        make_labelled_span(WORKED_EXAMPLE_TEXT, '"', SpanCategory.CONTEXTUAL, start=27),
        make_labelled_span(WORKED_EXAMPLE_TEXT, '"2015 Nissan Rogue"', SpanCategory.CONTEXTUAL),
    ]


def test_punct_detection_between_two_digit_spans() -> None:
    text = "127.0.0.1"
    red = [
        LabelledSpan(0, 3, SpanCategory.MANDATORY),
        LabelledSpan(4, 7, SpanCategory.MANDATORY),
        LabelledSpan(8, 9, SpanCategory.MANDATORY),
    ]
    structure = build_connector_structure(text, red, [])
    assert structure.effective_markers.count(".") == 2
    assert len(structure.red_fusion_groups) == 1


def test_slash_connector_requires_digit_only_neighbours() -> None:
    text = "03/14 and host/10"
    red_digit = [
        LabelledSpan(0, 2, SpanCategory.MANDATORY),
        LabelledSpan(3, 5, SpanCategory.MANDATORY),
    ]
    struct_digit = build_connector_structure(text, red_digit, [])
    assert struct_digit.effective_markers.count("/") == 1

    red_mixed = [
        LabelledSpan(text.find("host"), text.find("host") + 4, SpanCategory.MANDATORY),
        LabelledSpan(text.find("10"), text.find("10") + 2, SpanCategory.MANDATORY),
    ]
    struct_mixed = build_connector_structure(text, red_mixed, [])
    assert struct_mixed.effective_markers.count("/") == 0


def test_bridge_connector_requires_close_then_whitespace() -> None:
    text = "(415) 555"
    paren = LabelledSpan(0, 5, SpanCategory.MANDATORY)
    digits = LabelledSpan(6, 9, SpanCategory.MANDATORY)
    structure = build_connector_structure(text, [paren, digits], [])
    assert ")" in structure.effective_markers
    assert " " in structure.effective_markers
    assert len(structure.red_fusion_groups) == 2


def test_pair_range_detects_bracketed_yellows() -> None:
    text = "[ABC]"
    yellow = [LabelledSpan(1, 4, SpanCategory.CONTEXTUAL)]
    structure = build_connector_structure(text, [], yellow)
    assert structure.pair_ranges == (PairRange(o=0, end=4),)


def test_pair_range_excludes_pairs_crossing_red() -> None:
    text = '"hello VIN"'
    yellow = [
        LabelledSpan(1, 6, SpanCategory.CONTEXTUAL),
        LabelledSpan(10, 11, SpanCategory.CONTEXTUAL),
    ]
    red = [LabelledSpan(7, 10, SpanCategory.MANDATORY)]
    structure = build_connector_structure(text, red, yellow)
    assert structure.pair_ranges == ()


def test_pair_range_handles_symmetric_quotes() -> None:
    text = '"ABC" "DEF"'
    structure = build_connector_structure(
        text,
        [],
        [
            LabelledSpan(1, 4, SpanCategory.CONTEXTUAL),
            LabelledSpan(7, 10, SpanCategory.CONTEXTUAL),
        ],
    )
    pair_starts = sorted((p.o, p.end) for p in structure.pair_ranges)
    assert pair_starts == [(0, 4), (6, 10)]


def test_worked_example_vehicle_record_structure() -> None:
    red = worked_red_spans()
    yellow = worked_yellow_spans()
    structure = build_connector_structure(WORKED_EXAMPLE_TEXT, red, yellow)

    assert len(structure.red_fusion_groups) == 2
    red_starts = sorted([g.members[0].start for g in structure.red_fusion_groups])
    assert red_starts == [
        WORKED_EXAMPLE_TEXT.find("5N1AT2MK4FC824170"),
        WORKED_EXAMPLE_TEXT.find("321ABC"),
    ]

    assert (29, 47) in [(p.o, p.end) for p in structure.pair_ranges]

    components = structure.context_components
    flat_yellows = [m for c in components for m in c.members]
    flat_starts = sorted(s.start for s in flat_yellows)
    assert flat_starts == sorted(s.start for s in yellow)


def test_worked_example_vehicle_record_drops_open_quote_as_singleton_marker() -> None:
    pytest.importorskip("app.bench.fusion")
    from app.bench.fusion import fused_entity_groups

    structure = build_connector_structure(
        WORKED_EXAMPLE_TEXT, worked_red_spans(), worked_yellow_spans()
    )
    entities = fused_entity_groups(worked_yellow_spans(), structure, WORKED_EXAMPLE_TEXT)
    flat = [m for g in entities.contextual_entities for m in g.members]
    flat_starts = sorted(s.start for s in flat)
    assert flat_starts == [
        WORKED_EXAMPLE_TEXT.find('"', 27),
        WORKED_EXAMPLE_TEXT.find('"2015 Nissan Rogue"'),
    ]


def test_is_punct_char_excludes_letters_digits_and_specials() -> None:
    for ch in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
        assert not is_punct_char(ch)
    for ch in "\\/@[]{}()<>\"'`":
        assert not is_punct_char(ch)
    assert is_punct_char(".")
    assert is_punct_char(" ")
    assert is_punct_char(",")
