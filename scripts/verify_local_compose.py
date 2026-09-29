"""Verify the complete local Compose deployment from the host."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

BASE_URL = os.environ.get("REDAX_LOCAL_URL", "http://localhost:8000")
API_KEY = os.environ.get("REDAX_API_KEY")
COMPOSE = ["docker", "compose"]
MARKER = "local-compose-verification@example.invalid"


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    if urlsplit(url).scheme != "http":
        raise RuntimeError(f"only local HTTP URLs are supported: {url}")
    payload = None if body is None else json.dumps(body).encode()
    request_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
    request = Request(  # noqa: S310 - scheme is checked above
        url, data=payload, headers=request_headers, method=method
    )
    try:
        with urlopen(request, timeout=15) as response:  # noqa: S310 - scheme is checked above
            return json.load(response)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"request failed: {method} {url}: {exc}") from exc


def request_text(url: str) -> str:
    """Fetch a local text endpoint without attempting JSON decoding."""
    if urlsplit(url).scheme != "http":
        raise RuntimeError(f"only local HTTP URLs are supported: {url}")
    request = Request(url, headers={"Accept": "text/plain"})  # noqa: S310 - scheme checked above
    try:
        with urlopen(request, timeout=15) as response:  # noqa: S310 - scheme checked above
            return response.read().decode()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"request failed: GET {url}: {exc}") from exc


def compose_exec(service: str, command: list[str]) -> str:
    result = subprocess.run(
        [*COMPOSE, "exec", "-T", service, *command],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def assert_no_marker(name: str, value: object) -> None:
    if MARKER in json.dumps(value):
        raise RuntimeError(f"{name} contains the synthetic source marker")


def verify() -> None:
    if not API_KEY:
        raise RuntimeError("set REDAX_API_KEY to the value configured in .env")

    auth = {"X-API-Key": API_KEY}
    health = request_json(f"{BASE_URL}/healthz")
    ready = request_json(f"{BASE_URL}/readyz")
    if health.get("status") != "ok" or ready.get("status") != "ready":
        raise RuntimeError(f"API is not healthy: health={health!r} ready={ready!r}")
    metrics = request_text(f"{BASE_URL}/metrics")
    if "redax_requests_total" not in metrics:
        raise RuntimeError("metrics response does not expose redax_requests_total")

    response = request_json(
        f"{BASE_URL}/v1/redact",
        method="POST",
        headers=auth,
        body={"text": f"Contact {MARKER}"},
    )
    assert_no_marker("redaction response", response)
    if "[EMAIL_" not in str(response.get("text", "")):
        raise RuntimeError(f"redaction did not produce an email placeholder: {response!r}")

    job = request_json(
        f"{BASE_URL}/v1/jobs",
        method="POST",
        headers=auth,
        body={"text": f"Async contact {MARKER}"},
    )
    job_id = job.get("id")
    if not isinstance(job_id, str) or not job_id:
        raise RuntimeError(f"job submission did not return an id: {job!r}")
    for _ in range(45):
        status = request_json(f"{BASE_URL}/v1/jobs/{job_id}", headers=auth)
        if status.get("status") == "done":
            assert_no_marker("job result", status)
            if "[EMAIL_" not in json.dumps(status):
                raise RuntimeError(f"job completed without a placeholder: {status!r}")
            break
        if status.get("status") not in {"queued", "running"}:
            raise RuntimeError(f"job ended unexpectedly: {status!r}")
        time.sleep(1)
    else:
        raise RuntimeError(f"job {job_id} did not complete within 45 seconds")

    prometheus = request_json("http://localhost:9090/api/v1/targets")
    active_targets = prometheus.get("data", {}).get("activeTargets", [])
    if not any(
        target.get("labels", {}).get("job") == "redax" and target.get("health") == "up"
        for target in active_targets
    ):
        raise RuntimeError("Prometheus does not report the redax target as up")

    grafana = request_json("http://localhost:3000/api/health")
    if grafana.get("database") != "ok":
        raise RuntimeError(f"Grafana is not healthy: {grafana!r}")

    loki = compose_exec(
        "loki",
        [
            "wget",
            "-qO-",
            "http://localhost:3100/loki/api/v1/query_range?query=%7Bservice%3D%22redax%22%7D&limit=20",
        ],
    )
    assert_no_marker("Loki response", loki)
    if '"status":"success"' not in loki:
        raise RuntimeError("Loki query did not succeed")

    tempo = compose_exec("tempo", ["wget", "-qO-", "http://localhost:3200/api/search?limit=20"])
    assert_no_marker("Tempo response", tempo)
    if '"traces"' not in tempo:
        raise RuntimeError("Tempo search did not return a trace response")

    print(
        "local Compose verification passed: API, worker, Redis-backed state, metrics, logs, traces"
    )


if __name__ == "__main__":
    try:
        verify()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"local Compose verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
