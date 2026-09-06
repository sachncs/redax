from __future__ import annotations

from pathlib import Path

from app.bench.annotation import (
    Annotation,
    AnnotationInput,
    LabelledSpan,
    SpanCategory,
    build_annotation,
    load_annotations,
    split_on_newlines,
    write_annotations,
)
from app.bench.corpus import (
    Category,
    Document,
    Structure,
    load_corpus,
    structure_of,
    write_corpus,
)


def test_category_structure_mapping_is_paper_faithful() -> None:
    unstructured = (
        Category.ACADEMIC,
        Category.EMAILS,
        Category.FINANCIAL,
        Category.GOVERNMENT,
        Category.LEGAL,
        Category.MEDICAL,
        Category.OPERATIONS,
    )
    structured = (Category.CODE, Category.FILES, Category.LOGS, Category.TERMINAL)
    for cat in unstructured:
        assert structure_of(cat) is Structure.UNSTRUCTURED
    for cat in structured:
        assert structure_of(cat) is Structure.STRUCTURED
    assert len(unstructured) + len(structured) == 11


def test_document_structure_property_matches_table_4() -> None:
    assert Document("x", "t", Category.EMAILS, "g", "synthetic").structure is Structure.UNSTRUCTURED
    assert Document("x", "t", Category.CODE, "g", "synthetic").structure is Structure.STRUCTURED


def test_load_corpus_roundtrip(tmp_path: Path) -> None:
    docs = [
        Document("d1", "hello", Category.EMAILS, "g", "synthetic"),
        Document("d2", "world", Category.CODE, "g", "real"),
    ]
    path = tmp_path / "docs.jsonl"
    write_corpus(docs, path)
    loaded = load_corpus(path)
    assert [d.id for d in loaded] == ["d1", "d2"]
    assert [d.category for d in loaded] == [Category.EMAILS, Category.CODE]
    assert loaded[1].source == "real"


def test_load_corpus_rejects_unknown_category(tmp_path: Path) -> None:
    import pytest

    path = tmp_path / "docs.jsonl"
    path.write_text('{"id": "x", "text": "t", "category": "not-a-cat"}\n')
    with pytest.raises(ValueError):
        load_corpus(path)


def test_split_on_newlines_breaks_across_newline() -> None:
    text = "abc\ndef"
    span = LabelledSpan(0, 7, SpanCategory.MANDATORY)
    pieces = split_on_newlines(span, text)
    assert pieces == [
        LabelledSpan(0, 3, SpanCategory.MANDATORY),
        LabelledSpan(4, 7, SpanCategory.MANDATORY),
    ]


def test_split_on_newlines_is_idempotent_for_pure_segment() -> None:
    text = "abc\ndef"
    span = LabelledSpan(0, 3, SpanCategory.MANDATORY)
    assert split_on_newlines(span, text) == [span]


def test_build_annotation_validates_offsets() -> None:
    import pytest

    text = "hello"
    with pytest.raises(ValueError):
        build_annotation(
            AnnotationInput(
                doc_id="x",
                spans=[LabelledSpan(0, 10, SpanCategory.MANDATORY)],
                text=text,
                meta={},
            )
        )


def test_build_annotation_dedupes_and_sorts() -> None:
    text = "abcdef"
    ann = build_annotation(
        AnnotationInput(
            doc_id="x",
            spans=[
                LabelledSpan(2, 4, SpanCategory.MANDATORY),
                LabelledSpan(2, 4, SpanCategory.MANDATORY),
                LabelledSpan(0, 2, SpanCategory.CONTEXTUAL),
            ],
            text=text,
            meta={},
        )
    )
    assert [(s.start, s.end) for s in ann.spans] == [(0, 2), (2, 4)]


def test_load_annotations_with_corpus_text(tmp_path: Path) -> None:
    docs = [Document("d1", "alice@example.com", Category.EMAILS, "g", "synthetic")]
    doc_path = tmp_path / "docs.jsonl"
    write_corpus(docs, doc_path)

    ann_path = tmp_path / "anns.jsonl"
    write_annotations(
        [
            Annotation(
                doc_id="d1",
                spans=(LabelledSpan(0, 17, SpanCategory.MANDATORY),),
                meta={},
            )
        ],
        ann_path,
    )
    annotations = load_annotations(ann_path, {d.id: d.text for d in load_corpus(doc_path)})
    assert annotations[0].doc_id == "d1"
    assert annotations[0].spans[0].start == 0


def test_load_annotations_validates_offset_against_corpus_text(tmp_path: Path) -> None:
    import pytest

    docs = [Document("d1", "abc", Category.EMAILS, "g", "synthetic")]
    doc_path = tmp_path / "docs.jsonl"
    write_corpus(docs, doc_path)
    ann_path = tmp_path / "anns.jsonl"
    ann_path.write_text(
        '{"doc_id": "d1", "spans": [{"start": 0, "end": 10, "category": "mandatory"}]}\n'
    )
    with pytest.raises(ValueError):
        load_annotations(ann_path, {d.id: d.text for d in load_corpus(doc_path)})
