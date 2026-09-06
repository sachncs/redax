from __future__ import annotations

import asyncio

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.errors import install_error_handlers, timeout_error


def _make_app() -> tuple[FastAPI, TestClient]:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/ok")
    async def ok() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/http-error")
    async def http_error() -> None:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    @app.get("/crash")
    async def crash() -> None:
        raise ZeroDivisionError("internal secret detail")

    return app, TestClient(app, raise_server_exceptions=False)


def test_error_responses_are_rfc7807() -> None:
    _, client = _make_app()
    resp = client.get("/crash")
    assert resp.status_code == 500
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["type"] == "https://redax.ai/errors/internal"
    assert body["status"] == 500
    assert body["title"] == "Internal Server Error"
    assert "instance" in body


def test_unhandled_errors_do_not_leak_internals() -> None:
    _, client = _make_app()
    body = client.get("/crash").json()
    assert "ZeroDivisionError" not in body.get("detail", "")
    assert "internal secret detail" not in body.get("detail", "")
    assert "detail" not in body  # never include the exception payload


def test_http_exception_becomes_problem() -> None:
    _, client = _make_app()
    resp = client.get("/http-error")
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["title"] == "Invalid or missing API key"
    assert body["status"] == 401


def test_timeout_error_returns_504_problem() -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/slow")
    async def slow() -> None:
        async with asyncio.timeout(0.001):
            await asyncio.sleep(0.1)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/slow")
    assert resp.status_code == 504
    body = resp.json()
    assert body["type"] == "https://redax.ai/errors/timeout"
    assert body["status"] == 504


def test_timeout_error_helper() -> None:
    from starlette.requests import Request

    request = Request({"type": "http", "path": "/v1/redact", "headers": []})
    resp = timeout_error(request)
    assert resp.status_code == 504
    assert resp.headers["content-type"] == "application/problem+json"
