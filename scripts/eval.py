#!/usr/bin/env python3
"""Compute span-level precision/recall/F1 against a labeled JSONL fixture.

Usage:
    python scripts/eval.py --fixture tests/fixtures/synthetic_pii.jsonl

Each line in the fixture is a JSON object:
    {"text": "...", "entities": [{"start": int, "end": int, "type": str, "confidence": float}]}

A span is considered correct if its (start, end, type) matches exactly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

from app.inference.regex_detector import RegexDetector


def load_fixture(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


async def evaluate(fixture: list[dict]) -> dict:
    detector = RegexDetector()
    by_type: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    for item in fixture:
        text = item["text"]
        gold = {(e["start"], e["end"], e["type"]) for e in item["entities"]}
        predicted = {(s.start, s.end, s.type) for s in await detector.detect(text, [])}
        for g in gold:
            by_type[g[2]]["tp" if g in predicted else "fn"] += 1
        for p in predicted:
            if p not in gold:
                by_type[p[2]]["fp"] += 1
    return by_type


def summarize(by_type: dict[str, dict[str, int]]) -> dict:
    total = {"tp": 0, "fp": 0, "fn": 0}
    rows = []
    for t, counts in sorted(by_type.items()):
        tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        rows.append((t, tp, fp, fn, precision, recall, f1))
        total["tp"] += tp
        total["fp"] += fp
        total["fn"] += fn
    p = total["tp"] / (total["tp"] + total["fp"]) if (total["tp"] + total["fp"]) else 0.0
    r = total["tp"] / (total["tp"] + total["fn"]) if (total["tp"] + total["fn"]) else 0.0
    f = (2 * p * r / (p + r)) if (p + r) else 0.0
    return {"rows": rows, "precision": p, "recall": r, "f1": f, "total": total}


def render(report: dict) -> str:
    out = ["Entity            TP   FP   FN   Precision   Recall   F1"]
    out.append("-" * 60)
    for t, tp, fp, fn, p, r, f in report["rows"]:
        out.append(f"{t:<17} {tp:>3}  {fp:>3}  {fn:>3}   {p:>7.3f}    {r:>6.3f}   {f:>5.3f}")
    out.append("-" * 60)
    out.append(
        f"{'OVERALL':<17} {report['total']['tp']:>3}  {report['total']['fp']:>3}  {report['total']['fn']:>3}   {report['precision']:>7.3f}    {report['recall']:>6.3f}   {report['f1']:>5.3f}"
    )
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default="tests/fixtures/synthetic_pii.jsonl")
    parser.add_argument("--threshold", type=float, default=None)
    args = parser.parse_args()
    fixture = load_fixture(Path(args.fixture))
    by_type = asyncio.run(evaluate(fixture))
    report = summarize(by_type)
    print(render(report), file=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
