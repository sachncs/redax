"""Run a repeatable, privacy-safe HTTP load baseline against a Redax API."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
import psutil

from app.bench.corpus import load_corpus


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


def sha256_file(path: Path) -> str:
    """Return a file digest for benchmark provenance, or ``unknown``."""
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return "unknown"


def pinned_model_metadata() -> dict[str, str]:
    """Read the configured model identity and committed manifest digest."""
    name = os.environ.get("REDAX_MODEL_NAME", "")
    revision = os.environ.get("REDAX_MODEL_REVISION", "")
    digest = ""
    manifest = Path(__file__).resolve().parent.parent / "MODEL_HASHES.txt"
    if name and revision and manifest.exists():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[1] == name and parts[2] == revision:
                digest = parts[0]
                break
    return {"name": name, "revision": revision, "manifest_sha256": digest}


async def run_load(
    url: str,
    total: int | None,
    concurrency: int,
    text: str,
    mode: str = "redact",
    duration_seconds: float = 0.0,
    api_key: str | None = None,
    job_poll_timeout: float = 30.0,
    texts: list[str] | None = None,
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

        async def request_once(request_number: int) -> None:
            async with semaphore:
                request_started = time.perf_counter()
                try:
                    source_text = texts[request_number % len(texts)] if texts else text
                    request_text = benchmark_text(mode, source_text, request_number)
                    if mode == "job":
                        status = await run_job_once(
                            client,
                            url,
                            request_text,
                            api_key=api_key,
                            timeout=job_poll_timeout,
                        )
                    else:
                        headers = {"X-API-Key": api_key} if api_key else None
                        response = await client.post(
                            url,
                            json=request_payload(mode, request_text),
                            headers=headers,
                        )
                        status = str(response.status_code)
                        if (
                            mode == "stream"
                            and response.status_code == 200
                            and not stream_completed(response.text)
                        ):
                            status = "stream_error"
                except httpx.HTTPError:
                    status = "transport_error"
                latencies.append((time.perf_counter() - request_started) * 1000)
                statuses[status] = statuses.get(status, 0) + 1

        if deadline is None:
            assert total is not None
            await asyncio.gather(*(request_once(index) for index in range(total)))
        else:
            request_number = 0
            while time.perf_counter() < deadline:
                batch = range(request_number, request_number + concurrency)
                await asyncio.gather(*(request_once(index) for index in batch))
                request_number += concurrency

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


async def run_job_once(
    client: httpx.AsyncClient,
    url: str,
    text: str,
    *,
    api_key: str | None,
    timeout: float,
) -> str:
    """Submit one durable job and measure its terminal outcome.

    The benchmark never records job payloads or identifiers. A missing API
    key is left to the service's normal authentication contract so the tool
    can be used against both authenticated and intentionally anonymous test
    deployments.
    """
    headers = {"X-API-Key": api_key} if api_key else None
    response = await client.post(url, json=request_payload("job", text), headers=headers)
    if response.status_code != 202:
        return str(response.status_code)
    job_id = response.json().get("id")
    if not isinstance(job_id, str) or not job_id:
        return "invalid_job_response"
    status_url = f"{url.rstrip('/')}/{job_id}"
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        status_response = await client.get(status_url, headers=headers)
        if status_response.status_code != 200:
            return str(status_response.status_code)
        status = status_response.json().get("status")
        if status in {"done", "failed", "cancelled"}:
            return str(status)
        await asyncio.sleep(0.05)
    return "job_timeout"


def request_payload(mode: str, text: str) -> dict[str, Any]:
    """Build one of the supported synthetic, non-sensitive benchmark payloads."""
    if mode in {"redact", "model", "cache-hot", "cache-cold", "job"}:
        return {"text": text}
    if mode == "batch":
        return {"items": [{"text": text}, {"text": text}]}
    if mode == "stream":
        return {"text": text, "chunk_chars": 100}
    raise ValueError(f"unsupported benchmark mode: {mode}")


def benchmark_text(mode: str, text: str, request_number: int) -> str:
    """Return deterministic synthetic text for hot or cold cache workloads."""
    if mode == "cache-cold":
        return f"{text} request-{request_number}"
    return text


def stream_completed(body: str) -> bool:
    """Return whether an SSE response reached a successful terminal event."""
    for line in body.splitlines():
        if line.strip() == "data: [DONE]":
            return True
        if not line.startswith("data: "):
            continue
        try:
            payload = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "error" in payload:
            return False
    return False


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
    parser.add_argument(
        "--corpus",
        type=Path,
        help="cycle through documents.jsonl from a labeled benchmark corpus",
    )
    parser.add_argument(
        "--mode",
        choices=("redact", "model", "batch", "stream", "cache-hot", "cache-cold", "job"),
        default="redact",
    )
    parser.add_argument("--api-key", help="X-API-Key for authenticated HTTP and job benchmarks")
    parser.add_argument(
        "--job-poll-timeout",
        type=float,
        default=30.0,
        help="maximum seconds to wait for each durable job to reach a terminal state",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-on-error", action="store_true")
    parser.add_argument("--max-p99-ms", type=float)
    args = parser.parse_args()
    if args.corpus is not None and not (args.corpus / "documents.jsonl").exists():
        parser.error(f"missing {args.corpus / 'documents.jsonl'}")
    if (
        args.requests < 1
        or args.concurrency < 1
        or args.duration_seconds < 0
        or args.job_poll_timeout <= 0
    ):
        parser.error(
            "--requests and --concurrency must be positive; duration cannot be negative; "
            "job poll timeout must be positive"
        )
    return args


def main() -> None:
    """Run the load test and optionally write a machine-readable artifact."""
    args = parse_args()
    corpus_texts = None
    corpus_sha256 = None
    corpus_documents = None
    if args.corpus is not None:
        corpus_path = args.corpus / "documents.jsonl"
        corpus_texts = [document.text for document in load_corpus(corpus_path)]
        corpus_sha256 = sha256_file(corpus_path)
        corpus_documents = len(corpus_texts)
        if not corpus_texts:
            raise SystemExit("benchmark corpus contains no documents")
    result = {
        "schema_version": 1,
        "kind": "redax_api_load_baseline",
        "measurement_scope": "local_baseline",
        "commit": git_commit(),
        "runtime": {"python": platform.python_version(), "platform": platform.platform()},
        "provenance": {
            "lockfile_sha256": sha256_file(Path("requirements.lock")),
            "model": pinned_model_metadata(),
            "corpus": {
                "documents": corpus_documents,
                "documents_sha256": corpus_sha256,
            }
            if args.corpus is not None
            else None,
        },
        "target": args.url,
        "workload": {
            "mode": args.mode,
            "requests": args.requests if args.duration_seconds == 0 else None,
            "concurrency": args.concurrency,
            "duration_seconds": args.duration_seconds or None,
            "job_poll_timeout_seconds": args.job_poll_timeout if args.mode == "job" else None,
        },
        "result": asyncio.run(
            run_load(
                args.url,
                args.requests if args.duration_seconds == 0 else None,
                args.concurrency,
                args.text,
                args.mode,
                args.duration_seconds,
                args.api_key,
                args.job_poll_timeout,
                corpus_texts,
            )
        ),
    }
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    status_counts = result["result"]["status_counts"]
    p99 = result["result"]["latency_ms"]["p99"]
    successful_statuses = {"done"} if args.mode == "job" else {"200"}
    if args.fail_on_error and any(status not in successful_statuses for status in status_counts):
        raise SystemExit("load benchmark observed a non-200 response")
    if args.max_p99_ms is not None and p99 > args.max_p99_ms:
        raise SystemExit(f"p99 latency {p99}ms exceeds {args.max_p99_ms}ms")


if __name__ == "__main__":
    main()
