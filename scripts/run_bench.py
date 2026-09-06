#!/usr/bin/env python3
"""Run the RedactionBench harness against a labeled corpus.

Usage:
    python scripts/run_bench.py --corpus tests/fixtures/redactionbench \\
        --detector regex --output /tmp/rb.json

The corpus directory must contain `documents.jsonl` and `annotations.jsonl`
in the formats produced by `app.bench.corpus.load_corpus` and
`app.bench.annotation.load_annotations`. Each document is run through the
chosen redax detector, mapped to mandatory redactions (the detector layer
only marks candidate spans — we treat every detected span as mandatory for
benchmarking purposes), and scored with R-Score.

The output JSON has the shape:

    {
      "corpus_mean": float,
      "percentiles": {"p20": ..., "p50": ..., "mean": ...},
      "per_category": {category: {"mean": ..., "p50": ..., "n": ...}},
      "per_document": {doc_id: {"r_score": ..., "n": ..., "d": ...,
                                "skipped_contextual": int,
                                "n_mandatory": int, "n_contextual": int,
                                "n_fp": int}}
    }
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from app.bench.annotation import LabelledSpan, SpanCategory, load_annotations
from app.bench.corpus import load_corpus
from app.bench.rscore import rscore


def _build_detector(name: str) -> Any:
    if name == "regex":
        from app.inference.regex_detector import RegexDetector

        return RegexDetector()
    if name == "gliner2":
        from app.inference.gliner2 import GLiNER2Detector

        return GLiNER2Detector()
    raise SystemExit(f"unknown detector: {name}")


async def _run_detector(detector: Any, text: str) -> list[LabelledSpan]:
    spans = await detector.detect(text, [])
    return [LabelledSpan(start=s.start, end=s.end, category=SpanCategory.MANDATORY) for s in spans]


def _serialise_report(report: Any) -> dict[str, Any]:
    per_document: dict[str, dict[str, Any]] = {}
    for doc_id, rdoc in report.per_document.items():
        per_document[doc_id] = {
            "r_score": rdoc.r_score,
            "n": rdoc.n,
            "d": rdoc.d,
            "skipped_contextual": rdoc.skipped_contextual,
            "n_mandatory": len(rdoc.mandatory_entities),
            "n_contextual": len(rdoc.contextual_entities),
            "n_fp": len(rdoc.false_positives),
        }
    return {
        "corpus_mean": report.corpus_mean,
        "percentiles": report.percentiles(),
        "per_category": report.per_category,
        "per_document": per_document,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument(
        "--detector",
        choices=("regex", "gliner2"),
        default="regex",
    )
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    documents_path = args.corpus / "documents.jsonl"
    annotations_path = args.corpus / "annotations.jsonl"
    if not documents_path.exists():
        raise SystemExit(f"missing {documents_path}")
    if not annotations_path.exists():
        raise SystemExit(f"missing {annotations_path}")

    documents = load_corpus(documents_path)
    annotations = load_annotations(annotations_path, {d.id: d.text for d in documents})
    ann_by_id = {a.doc_id: a for a in annotations}
    detector = _build_detector(args.detector)

    async def collect() -> list[tuple[str, str, list[LabelledSpan], list[LabelledSpan]]]:
        inputs: list[tuple[str, str, list[LabelledSpan], list[LabelledSpan]]] = []
        for doc in documents:
            ann = ann_by_id.get(doc.id)
            if ann is None:
                print(f"warning: no annotation for {doc.id}, skipping", file=sys.stderr)
                continue
            predictions = await _run_detector(detector, doc.text)
            inputs.append((doc.id, doc.text, list(ann.spans), predictions))
        return inputs

    inputs = asyncio.run(collect())
    cats = {doc.id: doc.category.value for doc in documents}
    report = rscore(inputs, cats)

    payload = _serialise_report(report)
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
