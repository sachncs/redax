from __future__ import annotations

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from app.bench.annotation import LabelledSpan, SpanCategory
from app.bench.rscore import score_document


@st.composite
def mandatory_only_doc(draw):
    """Hypothesis strategy: text + 1-3 MANDATORY spans with non-overlapping offsets."""
    text = draw(
        st.text(
            alphabet=st.characters(min_codepoint=32, max_codepoint=126), min_size=8, max_size=40
        )
    )
    n = draw(st.integers(min_value=1, max_value=min(3, len(text))))
    starts = sorted(
        draw(
            st.lists(
                st.integers(min_value=0, max_value=len(text) - 1),
                min_size=n,
                max_size=n,
                unique=True,
            )
        )
    )
    spans: list[LabelledSpan] = []
    for s in starts:
        end = min(s + draw(st.integers(min_value=1, max_value=4)), len(text))
        if end > s:
            spans.append(LabelledSpan(s, end, SpanCategory.MANDATORY))
    return text, spans


def test_R_score_in_unit_interval() -> None:
    text = "alice@example.com lives here"
    span = LabelledSpan(0, 17, SpanCategory.MANDATORY)
    for pred in (
        [],
        [LabelledSpan(0, 5, SpanCategory.MANDATORY)],
        [LabelledSpan(0, 17, SpanCategory.MANDATORY)],
        [LabelledSpan(0, len(text), SpanCategory.MANDATORY)],
    ):
        result = score_document(text, [span], pred)
        assert 0.0 <= result.r_score <= 1.0


def test_perfect_prediction_yields_R_one() -> None:
    text = "alice@example.com lives here"
    span = LabelledSpan(0, 17, SpanCategory.MANDATORY)
    result = score_document(text, [span], [LabelledSpan(0, 17, SpanCategory.MANDATORY)])
    assert result.r_score == 1.0


def test_no_predictions_with_mandatory_yields_R_zero() -> None:
    text = "alice@example.com lives here"
    span = LabelledSpan(0, 17, SpanCategory.MANDATORY)
    result = score_document(text, [span], [])
    assert result.r_score == 0.0


def test_overlapping_predictions_never_decrease_R() -> None:
    text = "alice@example.com lives here"
    span = LabelledSpan(0, 17, SpanCategory.MANDATORY)
    base = score_document(text, [span], [LabelledSpan(0, 5, SpanCategory.MANDATORY)])
    extended = score_document(
        text,
        [span],
        [LabelledSpan(0, 5, SpanCategory.MANDATORY), LabelledSpan(5, 17, SpanCategory.MANDATORY)],
    )
    assert extended.r_score >= base.r_score


def test_wrong_predictions_never_increase_R_when_mandatory_exists() -> None:
    text = "alice@example.com lives here"
    span = LabelledSpan(0, 17, SpanCategory.MANDATORY)
    base = score_document(text, [span], [])
    with_fp = score_document(
        text,
        [span],
        [LabelledSpan(20, 30, SpanCategory.MANDATORY)],
    )
    assert with_fp.r_score <= base.r_score


def test_unified_predictions_match_split_predictions() -> None:
    text = "abcdefghij"
    span = LabelledSpan(0, 5, SpanCategory.MANDATORY)
    unified = score_document(text, [span], [LabelledSpan(0, 5, SpanCategory.MANDATORY)])
    split = score_document(
        text,
        [span],
        [
            LabelledSpan(0, 2, SpanCategory.MANDATORY),
            LabelledSpan(2, 5, SpanCategory.MANDATORY),
        ],
    )
    assert unified.r_score == split.r_score


@given(mandatory_only_doc())
@settings(max_examples=50)
def test_property_R_in_unit_interval(doc) -> None:
    text, spans = doc
    preds = [
        LabelledSpan(0, len(text), SpanCategory.MANDATORY),
    ]
    result = score_document(text, spans, preds)
    assert 0.0 <= result.r_score <= 1.0


@given(mandatory_only_doc())
@settings(max_examples=50)
def test_property_perfect_predictions_score_one(doc) -> None:
    text, spans = doc
    preds = list(spans)
    result = score_document(text, spans, preds)
    assert result.r_score == pytest.approx(1.0)
