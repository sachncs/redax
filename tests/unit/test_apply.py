from __future__ import annotations

from itertools import pairwise

import hypothesis.strategies as st
from hypothesis import given

from app.inference.detector import Span
from app.redaction.apply import apply_spans, dedupe_overlaps, inverse_position_remap


def test_single_replacement_string() -> None:
    text = "Email me at a@b.com tomorrow"
    spans = [Span(12, 19, "EMAIL", 1.0)]
    assert apply_spans(text, spans, ["[REDACTED]"]) == "Email me at [REDACTED] tomorrow"


def test_per_span_replacements() -> None:
    text = "Alice and Bob"
    spans = [Span(0, 5, "PERSON", 1.0), Span(10, 13, "PERSON", 1.0)]
    out = apply_spans(text, spans, ["[PERSON_0001]", "[PERSON_0002]"])
    assert out == "[PERSON_0001] and [PERSON_0002]"


def test_no_spans_returns_text_unchanged() -> None:
    assert apply_spans("hello", [], []) == "hello"


def test_replacement_list_length_must_match() -> None:
    text = "abcdef"
    spans = [Span(0, 3, "A", 1.0), Span(3, 6, "B", 1.0)]
    import pytest

    with pytest.raises(ValueError):
        apply_spans(text, spans, ["only-one"])


def test_empty_replacement_yields_concatenation() -> None:
    text = "hello world"
    spans = [Span(5, 11, "X", 1.0)]
    assert apply_spans(text, spans, [""]) == "hello"


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
    new = apply_spans(text, spans, ["[R]"])
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


@st.composite
def segmented_layout(draw):
    """Text built from segments; some segments are marked as redacted spans.

    Returns (text, spans, replacements, parts, redact_mask) where spans are
    mutually non-overlapping and in ascending order by construction.
    """
    parts = draw(st.lists(st.text("ab ", max_size=4), min_size=0, max_size=6))
    redact = draw(st.lists(st.booleans(), min_size=len(parts), max_size=len(parts)))
    spans = []
    pos = 0
    for part, do_redact in zip(parts, redact, strict=True):
        if do_redact and part:
            spans.append(Span(pos, pos + len(part), "T", 1.0))
        pos += len(part)
    replacements = draw(st.lists(st.text(max_size=4), min_size=len(spans), max_size=len(spans)))
    return "".join(parts), spans, replacements, parts, redact


def _expected(text, spans, replacements, parts, redact) -> str:
    out = ""
    repl_iter = iter(replacements)
    for part, do_redact in zip(parts, redact, strict=True):
        if do_redact and part:
            out += next(repl_iter)
        else:
            out += part
    return out


@given(segmented_layout())
def test_apply_preserves_kept_segments_and_length(layout) -> None:
    text, spans, replacements, parts, redact = layout
    out = apply_spans(text, spans, replacements)
    assert out == _expected(text, spans, replacements, parts, redact)
    assert len(out) == len(text) - sum(s.end - s.start for s in spans) + sum(
        len(r) for r in replacements
    )


@given(segmented_layout())
def test_apply_is_permutation_invariant(layout) -> None:
    text, spans, replacements, _, _ = layout
    assert apply_spans(text, list(reversed(spans)), list(reversed(replacements))) == apply_spans(
        text, spans, replacements
    )


@given(segmented_layout())
def test_apply_string_replacement_keeps_kept_chars(layout) -> None:
    text, spans, _, parts, redact = layout
    out = apply_spans(text, spans, ["[X]"] * len(spans))
    expected = "".join(
        "[X]" if do_redact and part else part for part, do_redact in zip(parts, redact, strict=True)
    )
    assert out == expected


@given(segmented_layout())
def test_remap_maps_each_output_char_to_its_origin(layout) -> None:
    text, spans, replacements, parts, redact = layout
    out = apply_spans(text, spans, replacements)
    remap = inverse_position_remap(text, spans, replacements)
    old_pos = 0
    new_pos = 0
    repl_iter = iter(replacements)
    for part, do_redact in zip(parts, redact, strict=True):
        if do_redact and part:
            replacement = next(repl_iter)
            span = Span(old_pos, old_pos + len(part), "T", 1.0)
            for j in range(len(replacement)):
                assert out[new_pos + j] == replacement[j]
                assert remap(new_pos + j) == span.start
            new_pos += len(replacement)
        else:
            for j, ch in enumerate(part):
                assert out[new_pos + j] == ch
                assert remap(new_pos + j) == old_pos + j
            new_pos += len(part)
        old_pos += len(part)
    for i in range(1, len(out)):
        assert remap(i - 1) <= remap(i)


@given(st.lists(st.tuples(st.integers(0, 15), st.integers(0, 15)), max_size=8), st.floats(0.0, 1.0))
def test_dedupe_output_is_sorted_and_non_overlapping(bounds, conf) -> None:
    spans = [Span(a, b, "T", conf) for a, b in bounds if a < b]
    out = dedupe_overlaps(spans)
    assert all(span in spans for span in out)
    for a, b in pairwise(out):
        assert a.start <= b.start
        assert a.end <= b.start
    if spans:
        assert len(out) >= 1


@given(st.lists(st.tuples(st.integers(0, 12), st.integers(0, 12)), max_size=8))
def test_dedupe_never_drops_below_one_for_nonempty(bounds) -> None:
    spans = [Span(a, b, "T", 0.5) for a, b in bounds if a < b]
    assert len(dedupe_overlaps(spans)) <= len(spans)


def test_apply_roundtrips_multibyte_and_emoji() -> None:
    text = "héllo 😀wörld ĉao"
    spans = [Span(2, 7, "PERSON", 1.0), Span(8, 13, "EMAIL", 1.0)]
    out = apply_spans(text, spans, ["[P]", "[E]"])
    assert out == "hé[P]w[E]ĉao"
    spans_alt = [Span(8, 13, "EMAIL", 1.0), Span(2, 7, "PERSON", 1.0)]
    assert apply_spans(text, spans_alt, ["[E]", "[P]"]) == out
