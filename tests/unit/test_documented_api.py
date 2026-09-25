from __future__ import annotations

from pathlib import Path

from app.main import app

ROOT = Path(__file__).parents[2]


def test_api_docs_cover_every_openapi_operation() -> None:
    """Keep the public API guide from silently losing a route."""
    docs = (ROOT / "docs" / "api.md").read_text(encoding="utf-8")
    documented = docs.replace("/v1/jobs/{id}", "/v1/jobs/{job_id}")

    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            assert f"{method.upper()} {path}" in documented
