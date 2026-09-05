#!/usr/bin/env python3
"""Latency + throughput benchmark on the regex detector.

Usage:
    python scripts/bench.py --text-size 1000 --batch 200 --rounds 5
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time

from app.inference.regex_detector import RegexDetector

SAMPLE = (
    "Reach Dr. Adam Wilson at adam@example.com or +1 415-555-2671. "
    "His IBAN is GB00FAKE00000000000000 and card 4532 0151 1283 0366. "
    "Server at 10.0.0.1 went down. SSN 000-00-0000."
)


def make_text(size: int) -> str:
    chunk = SAMPLE
    out = []
    total = 0
    while total < size:
        out.append(chunk)
        total += len(chunk)
    return " ".join(out)[:size]


async def bench(text: str, batch: int, rounds: int) -> dict:
    detector = RegexDetector()
    await detector.warmup()
    latencies_ms: list[float] = []
    total = 0
    for _r in range(rounds):
        for _ in range(batch):
            start = time.perf_counter()
            await detector.detect(text, [])
            latencies_ms.append((time.perf_counter() - start) * 1000)
            total += 1
    p50 = statistics.median(latencies_ms)
    p95 = statistics.quantiles(latencies_ms, n=20)[18]
    p99 = statistics.quantiles(latencies_ms, n=100)[98]
    mean = statistics.mean(latencies_ms)
    elapsed = sum(latencies_ms) / 1000
    throughput = total / elapsed if elapsed else 0.0
    return {
        "calls": total,
        "mean_ms": mean,
        "p50_ms": p50,
        "p95_ms": p95,
        "p99_ms": p99,
        "throughput_per_sec": throughput,
    }


def render(report: dict, text_size: int) -> str:
    return (
        f"text_chars={text_size}  calls={report['calls']}\n"
        f"  mean = {report['mean_ms']:6.2f} ms\n"
        f"  p50  = {report['p50_ms']:6.2f} ms\n"
        f"  p95  = {report['p95_ms']:6.2f} ms\n"
        f"  p99  = {report['p99_ms']:6.2f} ms\n"
        f"  throughput = {report['throughput_per_sec']:6.1f} req/s"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text-size", type=int, default=1000)
    parser.add_argument("--batch", type=int, default=200)
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()
    text = make_text(args.text_size)
    report = asyncio.run(bench(text, args.batch, args.rounds))
    print(render(report, args.text_size), file=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
