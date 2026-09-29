"""Run a repeatable, privacy-safe HTTP load baseline against a Redax API."""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
import psutil


def percentile(values: list[float], fraction: float) -> float:
    """Return a percentile using linear interpolation over sorted samples."""
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def git_commit() -> str:
    """Return the measured checkout commit without including request data."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


async def run_load(
    url: str,
    total: int | None,
    concurrency: int,
    text: str,
    duration_seconds: float = 0.0,
) -> dict[str, Any]:
    """Issue bounded concurrent requests and return aggregate measurements."""
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    statuses: dict[str, int] = {}
    process = psutil.Process()
    process.cpu_percent(None)
    rss_before = process.memory_info().rss
    started = time.perf_counter()
    deadline = started + duration_seconds if duration_seconds else None

    async with httpx.AsyncClient(timeout=30.0) as client:

        async def request_once() -> None:
            async with semaphore:
                request_started = time.perf_counter()
                try:
                    response = await client.post(url, json={"text": text})
                    status = str(response.status_code)
                except httpx.HTTPError:
                    status = "transport_error"
                latencies.append((time.perf_counter() - request_started) * 1000)
                statuses[status] = statuses.get(status, 0) + 1

        if deadline is None:
            assert total is not None
            await asyncio.gather(*(request_once() for _ in range(total)))
        else:
            while time.perf_counter() < deadline:
                await asyncio.gather(*(request_once() for _ in range(concurrency)))

    elapsed = time.perf_counter() - started
    request_count = len(latencies)
    rss_after = process.memory_info().rss
    return {
        "requests": request_count,
        "concurrency": concurrency,
        "elapsed_seconds": round(elapsed, 6),
        "throughput_requests_per_second": round(request_count / elapsed, 3) if elapsed else 0.0,
        "status_counts": statuses,
        "latency_ms": {
            "p50": round(percentile(latencies, 0.50), 3),
            "p90": round(percentile(latencies, 0.90), 3),
            "p95": round(percentile(latencies, 0.95), 3),
            "p99": round(percentile(latencies, 0.99), 3),
            "max": round(max(latencies, default=0.0), 3),
            "mean": round(statistics.mean(latencies), 3) if latencies else 0.0,
        },
        "process": {
            "rss_before_bytes": rss_before,
            "rss_after_bytes": rss_after,
            "rss_delta_bytes": rss_after - rss_before,
            "cpu_percent": process.cpu_percent(None),
        },
    }


def parse_args() -> argparse.Namespace:
    """Parse the intentionally small load-test CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000/v1/redact")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=0.0,
        help="sustain concurrent waves for this duration; overrides --requests when positive",
    )
    parser.add_argument("--text", default="Contact alice@example.com for a safe response.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1 or args.duration_seconds < 0:
        parser.error("--requests and --concurrency must be positive; duration cannot be negative")
    return args


def main() -> None:
    """Run the load test and optionally write a machine-readable artifact."""
    args = parse_args()
    result = {
        "schema_version": 1,
        "kind": "redax_api_load_baseline",
        "measurement_scope": "local_baseline",
        "commit": git_commit(),
        "runtime": {"python": platform.python_version(), "platform": platform.platform()},
        "target": args.url,
        "workload": {
            "requests": args.requests if args.duration_seconds == 0 else None,
            "concurrency": args.concurrency,
            "duration_seconds": args.duration_seconds or None,
        },
        "result": asyncio.run(
            run_load(
                args.url,
                args.requests if args.duration_seconds == 0 else None,
                args.concurrency,
                args.text,
                args.duration_seconds,
            )
        ),
    }
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
