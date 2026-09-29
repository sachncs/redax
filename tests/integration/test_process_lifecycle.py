from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen


def free_tcp_port() -> int:
    """Return a currently unused loopback port for the child server."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_until_ready(port: int) -> None:
    """Wait for the real application lifespan to report readiness."""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/readyz", timeout=0.5) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("uvicorn process did not become ready")


def test_sigterm_drains_an_active_http_request_within_deadline(tmp_path: Path) -> None:
    """Exercise the real signal path while an HTTP request is still admitted."""
    port = free_tcp_port()
    environment = os.environ.copy()
    environment.update(
        {
            "REDAX_ENV": "dev",
            "REDAX_DETECTOR": "regex",
            "REDAX_HASH_SALT": "lifecycle-test-salt",
            "REDAX_AUDIT_PATH": str(tmp_path / "audit.jsonl"),
            "REDAX_SHUTDOWN_TIMEOUT_SECONDS": "0.5",
            "REDAX_REDIS_CONNECT_TIMEOUT_SECONDS": "0.2",
            "REDAX_REDIS_SOCKET_TIMEOUT_SECONDS": "0.2",
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--timeout-graceful-shutdown",
            "1",
            "--log-level",
            "info",
        ],
        cwd=Path(__file__).parents[2],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    client_socket: socket.socket | None = None
    try:
        wait_until_ready(port)
        client_socket = socket.create_connection(("127.0.0.1", port), timeout=2)
        client_socket.sendall(
            b"POST /v1/redact HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 100000\r\n"
            b"Connection: close\r\n\r\n"
            b'{"text":"held-open-request'
        )
        time.sleep(0.1)
        started = time.monotonic()
        process.send_signal(signal.SIGTERM)
        return_code = process.wait(timeout=5)
        output = process.stdout.read().decode() if process.stdout is not None else ""
        # Uvicorn performs lifespan shutdown before the OS reports the signal
        # exit status, which is -SIGTERM on POSIX and 128+SIGTERM in shells.
        assert return_code in {0, -signal.SIGTERM, 128 + signal.SIGTERM}
        assert "Application shutdown complete." in output
        assert time.monotonic() - started < 4
    finally:
        if client_socket is not None:
            client_socket.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
