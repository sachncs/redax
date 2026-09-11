from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.fixture(autouse=True)
def clear_redax_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wipe every REDAX_* env var so each test starts from a clean environment."""
    for key in list(__import__("os").environ):
        if key.startswith("REDAX_"):
            monkeypatch.delenv(key, raising=False)


def test_defaults() -> None:
    s = Settings()
    assert s.detector == "gliner2"
    assert s.model_revision == "c153999da5f4c509df4322b0c6a1baf3d2c284d7"
    assert s.inference_concurrency == 2
    assert s.worker_concurrency == 1
    assert s.max_inflight == 32
    assert s.max_jobs_per_key == 50
    assert s.audit_fsync is True
    assert s.cache_shared is False
    assert s.metrics_by_tenant is False


def test_extra_env_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDAX_JWT_SECRET", "stale")
    monkeypatch.setenv("REDAX_HASH_SALT", "a-strong-secret")
    s = Settings()
    with pytest.raises(ValueError, match="no longer exists"):
        s.verify()


def test_validate_refuses_default_secrets_when_auth_enabled() -> None:
    s = Settings(api_keys="k1,k2")
    assert s.api_key_set() == {"k1", "k2"}
    with pytest.raises(ValueError, match="REDAX_HASH_SALT"):
        s.verify()  # hash_salt still "change-me"


def test_validate_accepts_real_secrets() -> None:
    s = Settings(api_keys="k1", hash_salt="a-strong-secret")
    s.verify()


def test_validate_refuses_dev_key() -> None:
    s = Settings(api_keys="dev-key", hash_salt="a-strong-secret")
    with pytest.raises(ValueError, match="REDAX_API_KEYS"):
        s.verify()


def test_validate_refuses_default_salt_even_without_auth() -> None:
    s = Settings(api_keys="", hash_salt="change-me")
    with pytest.raises(ValueError, match="REDAX_HASH_SALT"):
        s.verify()


def test_validate_requires_model_revision() -> None:
    s = Settings(model_revision="", hash_salt="a-strong-secret")
    with pytest.raises(ValueError, match="MODEL_REVISION"):
        s.verify()


def test_bounds_enforced() -> None:
    with pytest.raises(ValidationError):
        Settings(inference_concurrency=0)
    with pytest.raises(ValidationError):
        Settings(model_threshold=1.5)
    with pytest.raises(ValidationError):
        Settings(request_timeout_seconds=0)


def test_api_key_set_strips_blanks() -> None:
    s = Settings(api_keys=" a , , b ")
    assert s.api_key_set() == {"a", "b"}


def test_detector_validated() -> None:
    with pytest.raises(ValidationError):
        Settings(detector="ner")


def test_env_prefix_reads_underscore_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDAX_MAX_INFLIGHT", "7")
    s = Settings()
    assert s.max_inflight == 7
