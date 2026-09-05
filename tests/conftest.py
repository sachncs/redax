from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_dummy_state():
    """Yield a TestClient. Real wiring lands in later milestones; this
    fixture exists so unit + integration tests can register their own
    routes against a clean FastAPI app."""
    from fastapi import FastAPI

    app = FastAPI(title="Redax test")
    yield app


@pytest.fixture
def fixture_path() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def policies_path() -> Path:
    return Path(__file__).parent.parent / "policies"


@pytest.fixture
def client(app_with_dummy_state) -> Iterator[TestClient]:
    with TestClient(app_with_dummy_state) as c:
        yield c
