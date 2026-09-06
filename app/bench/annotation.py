"""Annotation data model for RedactionBench.

The paper distinguishes three label classes (mandatory, contextual, gap) at the
*unit* level. At the *span* level we model only the two sensitive classes:
mandatory and contextual. Gaps are implicit (non-support regions) and are
computed by the R-Score scorer from the union of all entity spans.
"""

from __future__ import annotations

import enum
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


class SpanCategory(enum.StrEnum):
    """The two span-level labels in RedactionBench."""

    MANDATORY = "mandatory"
    CONTEXTUAL = "contextual"


@dataclass(frozen=True)
class LabelledSpan:
    """A character-level span labelled as mandatory or contextual.

    Offsets are half-open `[start, end)` into the parent document text. The
    paper explicitly breaks multi-line boundaries across newline characters
    (Section 3.2); `split_on_newlines` enforces that rule at load time.
    """

    start: int
    end: int
    category: SpanCategory


@dataclass(frozen=True)
class Annotation:
    """The full label set for a single document.

    `doc_id` matches a `Document.id`. `spans` are the entity spans; gaps are
    derived. `meta` is opaque and may hold, e.g., "genre" or "source" for
    debugging.
    """

    doc_id: str
    spans: tuple[LabelledSpan, ...]
    meta: dict[str, str]

    def mandatory(self) -> list[LabelledSpan]:
        return [s for s in self.spans if s.category is SpanCategory.MANDATORY]

    def contextual(self) -> list[LabelledSpan]:
        return [s for s in self.spans if s.category is SpanCategory.CONTEXTUAL]


def split_on_newlines(span: LabelledSpan, text: str) -> list[LabelledSpan]:
    """Break a span into multiple spans wherever a newline is enclosed.

    Per Section 3.2: "Multi-line entity boundaries are definitively broken
    across newline characters while labeling." This function is idempotent:
    spans that already respect the rule are returned unchanged.
    """
    if "\n" not in text[span.start : span.end]:
        return [span]
    out: list[LabelledSpan] = []
    cursor = span.start
    end = span.end
    while cursor < end:
        next_nl = text.find("\n", cursor, end)
        if next_nl == -1:
            out.append(LabelledSpan(cursor, end, span.category))
            break
        if next_nl > cursor:
            out.append(LabelledSpan(cursor, next_nl, span.category))
        cursor = next_nl + 1
    return out


def _normalize_spans(
    spans: Iterable[LabelledSpan], text: str, text_len: int
) -> tuple[LabelledSpan, ...]:
    """Validate, dedupe, sort, and split multi-line spans."""
    out: list[LabelledSpan] = []
    seen: set[tuple[int, int, SpanCategory]] = set()
    for span in spans:
        if span.start < 0 or span.end > text_len or span.start >= span.end:
            raise ValueError(
                f"span out of range: [{span.start}, {span.end}) for text length {text_len}"
            )
        for piece in split_on_newlines(span, text):
            key = (piece.start, piece.end, piece.category)
            if key in seen:
                continue
            seen.add(key)
            out.append(piece)
    out.sort(key=lambda s: (s.start, s.end, s.category.value))
    return tuple(out)


@dataclass(frozen=True)
class AnnotationInput:
    """The raw loader form before normalization. Tests may construct this."""

    doc_id: str
    spans: list[LabelledSpan]
    text: str
    meta: dict[str, str]


def build_annotation(inp: AnnotationInput) -> Annotation:
    """Validate and normalize an annotation against its document text."""
    spans = _normalize_spans(inp.spans, inp.text, len(inp.text))
    return Annotation(doc_id=inp.doc_id, spans=spans, meta=dict(inp.meta))


def load_annotations(
    path: Path,
    documents: dict[str, str] | None = None,
) -> list[Annotation]:
    """Load JSONL annotations.

    Each line is a JSON object: `{"doc_id": "...", "text": "...", "spans":
    [{"start": int, "end": int, "category": "mandatory|contextual"}], ...}`.

    If `documents` is provided (a doc_id -> text map), the `text` field on each
    line is optional and the canonical text comes from the corpus. Spans are
    validated against the resolved text.
    """
    annotations: list[Annotation] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        doc_id = str(obj["doc_id"])
        if documents is not None and doc_id in documents:
            text = documents[doc_id]
        else:
            text = str(obj.get("text", ""))
        raw_spans = [
            LabelledSpan(
                start=int(s["start"]),
                end=int(s["end"]),
                category=SpanCategory(s["category"]),
            )
            for s in obj.get("spans", [])
        ]
        meta = {k: str(v) for k, v in obj.get("meta", {}).items()}
        annotations.append(build_annotation(AnnotationInput(doc_id, raw_spans, text, meta)))
    return annotations


def write_annotations(annotations: Iterable[Annotation], path: Path) -> None:
    """Write annotations to JSONL."""
    with path.open("w", encoding="utf-8") as fh:
        for ann in annotations:
            fh.write(
                json.dumps(
                    {
                        "doc_id": ann.doc_id,
                        "spans": [
                            {"start": s.start, "end": s.end, "category": s.category.value}
                            for s in ann.spans
                        ],
                        "meta": ann.meta,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
