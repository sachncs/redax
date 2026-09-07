from __future__ import annotations

from pathlib import Path

import pytest

from app.bench.annotation import (
    LabelledSpan,
    SpanCategory,
    load_annotations,
)
from app.bench.corpus import load_corpus
from app.bench.rscore import rscore, score_document

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "redactionbench"


def vehicle_annotation() -> list[LabelledSpan]:
    """Hand-built annotation for the worked-example vehicle record (matches docs/bench.md)."""
    text = 'Vehicle: "5N1AT2MK4FC824170" "2015 Nissan Rogue" plate= 321ABC'
    return [
        LabelledSpan(text.find('"'), text.find('"') + 1, SpanCategory.CONTEXTUAL),
        LabelledSpan(
            text.find("5N1AT2MK4FC824170"),
            text.find("5N1AT2MK4FC824170") + 17,
            SpanCategory.MANDATORY,
        ),
        LabelledSpan(text.find('"', 27), text.find('"', 27) + 1, SpanCategory.CONTEXTUAL),
        LabelledSpan(text.find('"2015'), text.find('"2015') + 19, SpanCategory.CONTEXTUAL),
        LabelledSpan(text.find("321ABC"), text.find("321ABC") + 6, SpanCategory.MANDATORY),
    ]


VEHICLE_TEXT = 'Vehicle: "5N1AT2MK4FC824170" "2015 Nissan Rogue" plate= 321ABC'


def test_mandatory_fullcoverage_yields_R_one() -> None:
    text = "Email me at alice@example.com please"
    span = LabelledSpan(12, 29, SpanCategory.MANDATORY)
    pred = [LabelledSpan(12, 29, SpanCategory.MANDATORY)]
    result = score_document(text, [span], pred)
    assert result.r_score == 1.0
    assert len(result.mandatory_entities) == 1
    assert result.mandatory_entities[0].n == 1.0
    assert result.mandatory_entities[0].d == 1.0


def test_mandatory_no_predictions_yields_R_zero() -> None:
    text = "Email me at alice@example.com please"
    span = LabelledSpan(12, 29, SpanCategory.MANDATORY)
    result = score_document(text, [span], [])
    assert result.r_score == 0.0
    assert result.mandatory_entities[0].n == 0.0
    assert result.mandatory_entities[0].d == 1.0


def test_mandatory_partialcoverage_scores_partial_credit() -> None:
    text = "abcdefghij"
    span = LabelledSpan(0, 5, SpanCategory.MANDATORY)
    pred = [LabelledSpan(0, 3, SpanCategory.MANDATORY)]
    result = score_document(text, [span], pred)
    assert result.r_score == pytest.approx(3 / 5)


def test_overlapping_predictions_are_unioned_before_scoring() -> None:
    text = "abcdefghij"
    span = LabelledSpan(0, 5, SpanCategory.MANDATORY)
    pred = [
        LabelledSpan(0, 3, SpanCategory.MANDATORY),
        LabelledSpan(2, 6, SpanCategory.MANDATORY),
    ]
    result = score_document(text, [span], pred)
    assert result.mandatory_entities[0].n == 1.0


def test_false_positive_default_weight_is_one() -> None:
    text = "abcXXXdef"
    span = LabelledSpan(0, 3, SpanCategory.MANDATORY)
    pred = [
        LabelledSpan(0, 3, SpanCategory.MANDATORY),
        LabelledSpan(3, 6, SpanCategory.MANDATORY),
    ]
    result = score_document(text, [span], pred)
    assert result.r_score == pytest.approx(1.0 / 2.0)


def test_false_positive_covering_entire_gap_ge_3_gets_weight_two() -> None:
    text = "AAAA bbb CCCC"
    span = LabelledSpan(5, 8, SpanCategory.MANDATORY)
    pred_full_gap = [
        LabelledSpan(0, 5, SpanCategory.MANDATORY),
        LabelledSpan(5, 8, SpanCategory.MANDATORY),
    ]
    result = score_document(text, [span], pred_full_gap)
    fp_weights = sorted(f.d for f in result.false_positives)
    assert fp_weights == [2.0]


def test_false_positive_partial_gapcoverage_still_weight_one() -> None:
    text = "AAAA bbb CCCC"
    span = LabelledSpan(5, 8, SpanCategory.MANDATORY)
    pred_partial = [
        LabelledSpan(0, 4, SpanCategory.MANDATORY),
        LabelledSpan(5, 8, SpanCategory.MANDATORY),
    ]
    result = score_document(text, [span], pred_partial)
    fp_weights = sorted(f.d for f in result.false_positives)
    assert fp_weights == [1.0]


def test_contextual_inactive_is_skipped() -> None:
    text = "John M. Doe lives here"
    span = LabelledSpan(0, 11, SpanCategory.CONTEXTUAL)
    result = score_document(text, [span], [])
    assert result.contextual_entities == ()
    assert result.skipped_contextual == 1
    assert result.r_score == 0.0


def test_contextual_all_contextual_document_uses_positive_formula() -> None:
    text = "John M. Doe lives here"
    span = LabelledSpan(0, 11, SpanCategory.CONTEXTUAL)
    pred = [LabelledSpan(0, 11, SpanCategory.CONTEXTUAL)]
    result = score_document(text, [span], pred)
    assert result.contextual_entities[0].kind == "contextual-optional"
    assert result.contextual_entities[0].n == 1.0
    assert result.contextual_entities[0].d == 1.0
    assert result.r_score == 1.0


def test_contextual_with_mandatory_uses_penalty_formula() -> None:
    text = "VIN: ABC123, name: John M. Doe"
    ann = [
        LabelledSpan(5, 11, SpanCategory.MANDATORY),
        LabelledSpan(19, 30, SpanCategory.CONTEXTUAL),
    ]
    pred = [
        LabelledSpan(5, 11, SpanCategory.MANDATORY),
        LabelledSpan(19, 30, SpanCategory.CONTEXTUAL),
    ]
    result = score_document(text, ann, pred)
    ctx = result.contextual_entities[0]
    assert ctx.kind == "contextual-penalty"
    assert ctx.n == 0.0
    assert ctx.d == 0.0


def test_contextual_partial_hit_penalises_when_mandatory_exists() -> None:
    text = "VIN: ABC123, name: John M. Doe"
    ann = [
        LabelledSpan(5, 11, SpanCategory.MANDATORY),
        LabelledSpan(19, 30, SpanCategory.CONTEXTUAL),
    ]
    pred = [
        LabelledSpan(5, 11, SpanCategory.MANDATORY),
        LabelledSpan(19, 25, SpanCategory.CONTEXTUAL),
    ]
    result = score_document(text, ann, pred)
    ctx = result.contextual_entities[0]
    assert ctx.n == 0.0
    assert ctx.d == pytest.approx(1 - 6 / 11)


def test_worked_example_perfect_prediction_yields_R_one() -> None:
    annotation = vehicle_annotation()
    pred = [
        LabelledSpan(
            VEHICLE_TEXT.find("5N1AT2MK4FC824170"),
            VEHICLE_TEXT.find("5N1AT2MK4FC824170") + 17,
            SpanCategory.MANDATORY,
        ),
        LabelledSpan(27, 28, SpanCategory.CONTEXTUAL),
        LabelledSpan(29, 48, SpanCategory.CONTEXTUAL),
        LabelledSpan(56, 62, SpanCategory.MANDATORY),
    ]
    result = score_document(VEHICLE_TEXT, annotation, pred, doc_id="vehicle")
    assert result.r_score == pytest.approx(1.0)


def test_worked_example_empty_prediction_yields_R_zero() -> None:
    result = score_document(VEHICLE_TEXT, vehicle_annotation(), [], doc_id="vehicle")
    assert result.r_score == 0.0


def test_worked_example_only_mandatory_predictions_yields_R_one() -> None:
    pred = [
        LabelledSpan(
            VEHICLE_TEXT.find("5N1AT2MK4FC824170"),
            VEHICLE_TEXT.find("5N1AT2MK4FC824170") + 17,
            SpanCategory.MANDATORY,
        ),
        LabelledSpan(56, 62, SpanCategory.MANDATORY),
    ]
    result = score_document(VEHICLE_TEXT, vehicle_annotation(), pred, doc_id="vehicle")
    assert result.r_score == 1.0


def test_worked_example_all_text_penalises_over_redaction() -> None:
    pred = [LabelledSpan(0, len(VEHICLE_TEXT), SpanCategory.MANDATORY)]
    result = score_document(VEHICLE_TEXT, vehicle_annotation(), pred, doc_id="vehicle")
    fp_weights = sorted(f.d for f in result.false_positives)
    assert fp_weights == [1.0, 2.0, 2.0]
    assert result.r_score == pytest.approx(2.0 / 7.0)


def test_worked_example_open_quote_singleton_does_not_penalise() -> None:
    pred = [LabelledSpan(9, 10, SpanCategory.CONTEXTUAL)]
    result = score_document(VEHICLE_TEXT, vehicle_annotation(), pred, doc_id="vehicle")
    assert result.r_score == 0.0


def test_worked_example_close_quote_pulls_in_2015_via_punct() -> None:
    pred = [LabelledSpan(27, 28, SpanCategory.CONTEXTUAL)]
    result = score_document(VEHICLE_TEXT, vehicle_annotation(), pred, doc_id="vehicle")
    ctx = result.contextual_entities[0]
    assert ctx.n == 0.0
    assert ctx.d == pytest.approx(0.5)


def test_rscore_aggregates_per_document_and_per_category() -> None:
    inputs = [
        (
            "a",
            "alice@example.com",
            [LabelledSpan(0, 17, SpanCategory.MANDATORY)],
            [LabelledSpan(0, 17, SpanCategory.MANDATORY)],
        ),
        (
            "b",
            "VIN: ABC123",
            [LabelledSpan(5, 11, SpanCategory.MANDATORY)],
            [],
        ),
    ]
    cats = {"a": "emails", "b": "operations"}
    report = rscore(inputs, cats)
    assert report.per_document["a"].r_score == 1.0
    assert report.per_document["b"].r_score == 0.0
    assert report.corpus_mean == 0.5
    assert report.per_category["emails"]["mean"] == 1.0
    assert report.per_category["operations"]["mean"] == 0.0


def test_rscore_handles_empty_corpus() -> None:
    report = rscore([])
    assert report.corpus_mean == 0.0
    assert report.per_document == {}


def test_fixture_perfect_predictions_score_one() -> None:
    import json

    docs = load_corpus(FIXTURE_DIR / "documents.jsonl")
    annotations_dict = {
        a.doc_id: a
        for a in load_annotations(FIXTURE_DIR / "annotations.jsonl", {d.id: d.text for d in docs})
    }
    perfect = {
        obj["doc_id"]: [
            LabelledSpan(p["start"], p["end"], SpanCategory.MANDATORY) for p in obj["predictions"]
        ]
        for obj in (
            json.loads(line)
            for line in (FIXTURE_DIR / "predictions_perfect.jsonl").read_text().splitlines()
            if line.strip()
        )
    }
    inputs = [(d.id, d.text, list(annotations_dict[d.id].spans), perfect[d.id]) for d in docs]
    cats = {d.id: d.category.value for d in docs}
    report = rscore(inputs, cats)
    for rdoc in report.per_document.values():
        assert rdoc.r_score == pytest.approx(1.0), f"expected 1.0 for {rdoc.doc_id}"
    assert report.corpus_mean == 1.0


def test_fixture_empty_predictions_score_zero_for_mandatory_docs() -> None:
    import json

    docs = load_corpus(FIXTURE_DIR / "documents.jsonl")
    annotations_dict = {
        a.doc_id: a
        for a in load_annotations(FIXTURE_DIR / "annotations.jsonl", {d.id: d.text for d in docs})
    }
    empty = {
        obj["doc_id"]: []
        for obj in (
            json.loads(line)
            for line in (FIXTURE_DIR / "predictions_empty.jsonl").read_text().splitlines()
            if line.strip()
        )
    }
    mandatory_docs = [
        d
        for d in docs
        if any(s.category is SpanCategory.MANDATORY for s in annotations_dict[d.id].spans)
    ]
    for d in mandatory_docs:
        result = score_document(d.text, list(annotations_dict[d.id].spans), empty[d.id])
        assert result.r_score == 0.0


def test_fixture_partial_predictions_yield_partial_R() -> None:
    import json

    docs = load_corpus(FIXTURE_DIR / "documents.jsonl")
    annotations_dict = {
        a.doc_id: a
        for a in load_annotations(FIXTURE_DIR / "annotations.jsonl", {d.id: d.text for d in docs})
    }
    partial = {
        obj["doc_id"]: [
            LabelledSpan(p["start"], p["end"], SpanCategory.MANDATORY) for p in obj["predictions"]
        ]
        for obj in (
            json.loads(line)
            for line in (FIXTURE_DIR / "predictions_partial.jsonl").read_text().splitlines()
            if line.strip()
        )
    }
    inputs = [(d.id, d.text, list(annotations_dict[d.id].spans), partial[d.id]) for d in docs]
    cats = {d.id: d.category.value for d in docs}
    report = rscore(inputs, cats)
    for rdoc in report.per_document.values():
        assert 0.0 < rdoc.r_score <= 1.0
