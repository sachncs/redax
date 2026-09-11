from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_dummy_state():
    """Yield a fresh FastAPI app for tests that want to register their own routes.

    Tests that need the real lifespan (``app.main:app``) instead use
    ``fastapi.testclient.TestClient(app)`` directly; this fixture is
    only for tests that want a clean FastAPI instance without lifespan.
    """
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
