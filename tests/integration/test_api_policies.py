from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.policies import register
from app.state import State


@pytest.fixture
def app_with_policies(monkeypatch, policies_path: Path):
    test_state = State()
    test_state.settings = type(
        "S", (), {"policies_dir": str(policies_path), "api_key_set": lambda self: set()}
    )()
    monkeypatch.setattr("app.state.state", test_state)
    app = FastAPI()
    register(app)
    return app


def test_policies_lists_builtins(app_with_policies):
    with TestClient(app_with_policies) as client:
        resp = client.get("/v1/policies")
    assert resp.status_code == 200
    body = resp.json()
    names = {p["name"] for p in body["policies"]}
    assert {"default", "strict", "minimal"}.issubset(names)


def test_policies_includes_fields(app_with_policies):
    with TestClient(app_with_policies) as client:
        resp = client.get("/v1/policies")
    body = resp.json()
    default = next(p for p in body["policies"] if p["name"] == "default")
    assert "free_text" in default["fields"]
