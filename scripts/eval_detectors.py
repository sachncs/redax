#!/usr/bin/env python3
"""Run multiple redax detectors against one or more RedactionBench corpora
and emit per-detector JSON reports.

This is the Phase 3 multi-detector runner. It complements the single-detector
`scripts/run_bench.py` by running every detector in one process so models load
exactly once.

Usage:
    python scripts/eval_detectors.py \
        --corpus tests/fixtures/redactionbench \
        --corpus tests/fixtures/pii200k \
        --detector regex \
        --detector gliner2 \
        --out-dir bench-results/$(date +%F)

Detectors supported: `regex`, `gliner2`, `openmed`, `fastino`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import resource
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from app.bench.annotation import LabelledSpan, SpanCategory, load_annotations
from app.bench.corpus import load_corpus
from app.bench.rscore import rscore


def build_eval_detector(name: str) -> Any:
    if name == "regex":
        from app.inference.regex import RegexDetector

        return RegexDetector()
    if name == "gliner2":
        from app.inference.gliner2 import GLiNER2Detector

        return GLiNER2Detector()
    if name == "fastino":
        from app.inference.gliner2 import GLiNER2Detector

        return GLiNER2Detector()
    if name == "openmed":
        from app.inference.openmed import OpenMedPIIDetector

        return OpenMedPIIDetector()
    raise SystemExit(f"unknown detector: {name}")


async def run_eval_detector(detector: Any, text: str) -> list[LabelledSpan]:
    spans = await detector.detect(text, [])
    return [LabelledSpan(start=s.start, end=s.end, category=SpanCategory.MANDATORY) for s in spans]


def serialise_eval_report(report: Any) -> dict[str, Any]:
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


async def collect_eval_results(
    detector: Any,
    documents: list,
    annotations_by_id: dict[str, Any],
) -> tuple[Any, dict[str, float]]:
    # Some detectors (notably GLiNER2) require explicit loading before
    # their first detect() call. Call warmup() if it's defined. Redirect
    # the model's stdout chatter so the JSON report stays clean.
    import contextlib
    import io

    warmup = getattr(detector, "warmup", None)
    if callable(warmup):
        with contextlib.redirect_stdout(io.StringIO()):
            await warmup()

    inputs: list[tuple[str, str, list[LabelledSpan], list[LabelledSpan]]] = []
    rss_samples: list[int] = []
    latencies_ms: list[float] = []
    for doc in documents:
        ann = annotations_by_id.get(doc.id)
        if ann is None:
            continue
        t0 = time.perf_counter()
        predictions = await run_eval_detector(detector, doc.text)
        latencies_ms.append(1000.0 * (time.perf_counter() - t0))
        rss_samples.append(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        inputs.append((doc.id, doc.text, list(ann.spans), predictions))
    report = rscore(inputs, {d.id: d.category.value for d in documents})
    metrics = {
        "n_documents": len(inputs),
        "mean_latency_ms": statistics.fmean(latencies_ms) if latencies_ms else 0.0,
        "p50_latency_ms": statistics.median(latencies_ms) if latencies_ms else 0.0,
        "p95_latency_ms": (
            statistics.quantiles(latencies_ms, n=20)[18]
            if len(latencies_ms) >= 20
            else max(latencies_ms, default=0.0)
        ),
        "peak_rss_kb": max(rss_samples) if rss_samples else 0,
    }
    return report, metrics


def summarise_eval_corpus(
    report: Any, metrics: dict[str, float], detector: str, corpus_name: str
) -> dict[str, Any]:
    return {
        "detector": detector,
        "corpus": corpus_name,
        "metrics": metrics,
        "report": serialise_eval_report(report),
    }


async def run_eval_one_detector(detector_name: str, corpora: list[Path]) -> list[dict[str, Any]]:
    print(f"\n=== detector={detector_name} ===", file=sys.stderr)
    detector = build_eval_detector(detector_name)
    out: list[dict[str, Any]] = []
    for corpus_dir in corpora:
        documents = load_corpus(corpus_dir / "documents.jsonl")
        annotations_by_id = {
            a.doc_id: a
            for a in load_annotations(
                corpus_dir / "annotations.jsonl", {d.id: d.text for d in documents}
            )
        }
        report, metrics = await collect_eval_results(detector, documents, annotations_by_id)
        out.append(summarise_eval_corpus(report, metrics, detector_name, corpus_dir.name))
        print(
            f"  {corpus_dir.name:30s}  mean_R={report.corpus_mean:.4f}  "
            f"p50={metrics['p50_latency_ms']:.1f}ms  "
            f"peak_rss={metrics['peak_rss_kb'] / 1024:.1f}MiB",
            file=sys.stderr,
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", action="append", type=Path, required=True)
    parser.add_argument("--detector", action="append", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for detector_name in args.detector:
        per_detector = asyncio.run(run_eval_one_detector(detector_name, args.corpus))
        out_path = args.out_dir / f"{detector_name}.json"
        out_path.write_text(json.dumps(per_detector, indent=2, sort_keys=True), encoding="utf-8")
        print(f"  wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
