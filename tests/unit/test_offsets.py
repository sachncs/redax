from __future__ import annotations

from app.redaction.offsets import validate_offsets


def test_drops_spans_with_bad_endpoints() -> None:
    text = "hello world"
    from app.inference.detector import Span

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
    from app.inference.detector import Span

    spans = [
        Span(0, 5, "FIRST_NAME", 1.0),
        Span(6, 9, "FIRST_NAME", 1.0),
        Span(10, 17, "FIRST_NAME", 1.0),
    ]
    out = validate_offsets(text, spans)
    assert len(out) == 3
