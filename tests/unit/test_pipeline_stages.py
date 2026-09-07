from __future__ import annotations

from app.bench.annotation import LabelledSpan, SpanCategory
from app.inference.detector import Span
from app.redaction.stages.consensus import ConsensusConfig, fuse


def make_test_span(start: int, end: int, conf: float = 0.5, type: str = "PERSON") -> Span:
    """Build a detector Span with the common defaults used in stage tests."""
    return Span(start=start, end=end, type=type, confidence=conf)


def test_consensus_keeps_all_regex_spans() -> None:
    regex = (make_test_span(0, 5), make_test_span(10, 14))
    model = ()
    assert fuse(regex, model) == regex


def test_consensus_keeps_model_spans_above_threshold() -> None:
    regex = ()
    model = (make_test_span(0, 5, conf=0.9),)
    assert fuse(regex, model) == model


def test_consensus_drops_low_confidence_model_spans() -> None:
    regex = ()
    model = (make_test_span(0, 5, conf=0.1),)
    assert fuse(regex, model) == ()


def test_consensus_drops_model_spans_overlapping_regex() -> None:
    regex = (make_test_span(0, 5),)
    model = (make_test_span(2, 7, conf=0.9),)
    assert fuse(regex, model) == regex


def test_consensus_keeps_non_overlapping_high_confidence_model_spans() -> None:
    regex = (make_test_span(0, 5),)
    model = (make_test_span(10, 15, conf=0.9),)
    result = fuse(regex, model)
    assert len(result) == 2


def test_consensus_dedupes_overlapping_model_spans() -> None:
    regex = ()
    model = (
        make_test_span(0, 5, conf=0.9),
        make_test_span(2, 7, conf=0.8),
    )
    result = fuse(regex, model)
    assert len(result) == 1
    assert result[0].start == 0


def test_consensus_custom_threshold() -> None:
    regex = ()
    model = (make_test_span(0, 5, conf=0.7),)
    assert fuse(regex, model, ConsensusConfig(min_model_confidence=0.8)) == ()
    assert fuse(regex, model, ConsensusConfig(min_model_confidence=0.5)) == model


def test_pipeline_inputs_compatible_with_redactionbench_annotations() -> None:
    """Sanity: LabelledSpan and Span use compatible start/end semantics."""
    regex = (make_test_span(0, 17),)
    annotated = LabelledSpan(0, 17, SpanCategory.MANDATORY)
    assert regex[0].start == annotated.start
    assert regex[0].end == annotated.end
