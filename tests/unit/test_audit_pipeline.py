from __future__ import annotations

from app.audit.backend import pipeline_to_event, span_summary


def test_span_summary_counts_per_type() -> None:
    class _S:
        def __init__(self, t: str, c: float) -> None:
            self.type = t
            self.confidence = c

    spans = [
        _S("EMAIL", 0.9),
        _S("EMAIL", 0.7),
        _S("PHONE", 0.8),
    ]
    summary = span_summary(spans)
    by_type = {row["type"]: row for row in summary}
    assert by_type["EMAIL"]["count"] == 2
    assert by_type["EMAIL"]["confidence_avg"] == 0.8
    assert by_type["PHONE"]["count"] == 1


def test_pipeline_to_event_does_not_carry_text() -> None:
    class _S:
        def __init__(self, t: str, c: float, v: str = "") -> None:
            self.type = t
            self.confidence = c
            self.value = v

    spans = [_S("EMAIL", 0.9, "jane@example.com")]
    event = pipeline_to_event(
        request_id="r1",
        text_chars=42,
        policy_version="default",
        inference_ms=12,
        spans=spans,
        used_fallback=False,
    )
    rendered = str(event)
    assert "jane@example.com" not in rendered
    assert "EMAIL" in rendered
    assert event.text_chars == 42
    assert event.inference_ms == 12


def test_pipeline_to_event_records_fallback_marker() -> None:
    event = pipeline_to_event(
        request_id="r1",
        text_chars=10,
        policy_version="default",
        inference_ms=5,
        spans=[],
        used_fallback=True,
    )
    types = [row["type"] for row in event.entities_detected]
    assert "__used_fallback__" in types
