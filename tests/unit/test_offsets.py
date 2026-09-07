from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given

from app.inference.detector import Span
from app.redaction.offsets import validate_offsets


def test_drops_spans_with_bad_endpoints() -> None:
    text = "hello world"
    spans = [
        Span(0, 5, "X", 1.0),  # valid
        Span(-1, 5, "X", 1.0),  # negative start
        Span(5, 5, "X", 1.0),  # zero length
        Span(5, 4, "X", 1.0),  # end <= start
        Span(0, 100, "X", 1.0),  # past end
    ]
    out = validate_offsets(text, spans)
    assert len(out) == 1
    assert out[0].start == 0 and out[0].end == 5


def test_keeps_overlapping_spans() -> None:
    text = "alice bob charlie"
    spans = [
        Span(0, 5, "FIRST_NAME", 1.0),
        Span(6, 9, "FIRST_NAME", 1.0),
        Span(10, 17, "FIRST_NAME", 1.0),
    ]
    out = validate_offsets(text, spans)
    assert len(out) == 3


_SPAN_BOUNDS = st.tuples(
    st.integers(min_value=-5, max_value=45),
    st.integers(min_value=-5, max_value=45),
)
_TEXT = st.text(st.characters(blacklist_categories=["Cs", "Cc"]), max_size=40)
_TYPES = st.sampled_from(["PERSON", "EMAIL", "PHONE"])


@given(text=_TEXT, bounds=st.lists(_SPAN_BOUNDS, max_size=8), entity_type=_TYPES)
def test_validate_keeps_exactly_in_bounds_spans(text: str, bounds, entity_type: str) -> None:
    spans = [Span(start, end, entity_type, 0.9) for start, end in bounds]
    out = validate_offsets(text, spans)
    for span in out:
        assert span.start >= 0
        assert span.start < span.end
        assert span.end <= len(text)
    assert len(out) <= len(spans)


@given(text=_TEXT, bounds=st.lists(_SPAN_BOUNDS, max_size=8), entity_type=_TYPES)
def test_validate_is_exact_and_idempotent(text: str, bounds, entity_type: str) -> None:
    spans = [Span(start, end, entity_type, 0.9) for start, end in bounds]
    expected = []
    for start, end in bounds:
        span = Span(start, end, entity_type, 0.9)
        if span.start >= 0 and span.end > span.start and span.end <= len(text):
            expected.append(span)
    out = validate_offsets(text, spans)
    assert out == expected
    assert validate_offsets(text, out) == out
