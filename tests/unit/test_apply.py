from __future__ import annotations

from app.inference.detector import Span
from app.redaction.apply import apply_spans, dedupe_overlaps, inverse_position_remap


def test_single_replacement_string() -> None:
    text = "Email me at a@b.com tomorrow"
    spans = [Span(12, 19, "EMAIL", 1.0)]
    assert apply_spans(text, spans) == "Email me at [REDACTED] tomorrow"


def test_per_span_replacements() -> None:
    text = "Alice and Bob"
    spans = [Span(0, 5, "PERSON", 1.0), Span(10, 13, "PERSON", 1.0)]
    out = apply_spans(text, spans, ["[PERSON_0001]", "[PERSON_0002]"])
    assert out == "[PERSON_0001] and [PERSON_0002]"


def test_no_spans_returns_text_unchanged() -> None:
    assert apply_spans("hello", []) == "hello"


def test_replacement_list_length_must_match() -> None:
    text = "abcdef"
    spans = [Span(0, 3, "A", 1.0), Span(3, 6, "B", 1.0)]
    import pytest

    with pytest.raises(ValueError):
        apply_spans(text, spans, ["only-one"])


def test_empty_replacement_yields_concatenation() -> None:
    text = "hello world"
    spans = [Span(5, 11, "X", 1.0)]
    assert apply_spans(text, spans, "") == "hello"


def test_dedupe_overlaps_keeps_higher_confidence() -> None:
    spans = [
        Span(0, 10, "PERSON", 0.5),
        Span(2, 8, "PERSON", 0.9),
    ]
    out = dedupe_overlaps(spans)
    assert len(out) == 1
    assert out[0].confidence == 0.9


def test_dedupe_overlaps_keeps_disjoint() -> None:
    spans = [
        Span(0, 5, "PERSON", 1.0),
        Span(10, 15, "EMAIL", 1.0),
    ]
    out = dedupe_overlaps(spans)
    assert len(out) == 2


def test_dedupe_overlaps_sorts_by_start() -> None:
    spans = [
        Span(20, 25, "X", 1.0),
        Span(0, 5, "Y", 1.0),
    ]
    out = dedupe_overlaps(spans)
    assert out[0].start < out[1].start


def test_dedupe_overlaps_empty() -> None:
    assert dedupe_overlaps([]) == []


def test_inverse_remap_follows_substitution_layout() -> None:
    text = "Alice, email a@b.com"
    spans = [Span(0, 5, "PERSON", 1.0)]
    new = apply_spans(text, spans, "[R]")
    remap = inverse_position_remap(text, spans, ["[R]"])
    assert new == "[R], email a@b.com"
    assert remap(0) == 0  # inside replaced range -> span start
    assert remap(3) == 5  # first kept char after replacement -> old 5
    assert remap(11) == 13  # email start in new text -> old 13


def test_inverse_remap_multiple_spans() -> None:
    text = "Alice and Bob"
    spans = [Span(0, 5, "PERSON", 1.0), Span(10, 13, "PERSON", 1.0)]
    new = apply_spans(text, spans, ["[P1]", "[P2]"])
    remap = inverse_position_remap(text, spans, ["[P1]", "[P2]"])
    assert new == "[P1] and [P2]"
    assert remap(0) == 0
    assert remap(4) == 5  # " and " kept segment start -> where replacement ends
    assert remap(9) == 10  # second replacement start -> old 10
    assert remap(12) == 10  # inside replaced range [-P2-] -> span start


def test_inverse_remap_empty_span_list_is_identity() -> None:
    remap = inverse_position_remap("hello", [], [])
    assert remap(4) == 4


def test_inverse_remap_rejects_length_mismatch() -> None:
    import pytest

    with pytest.raises(ValueError):
        inverse_position_remap("abc", [Span(0, 1, "A", 1.0)], [])
