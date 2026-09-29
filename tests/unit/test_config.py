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
    assert s.model_revision == "aad696b2f6815e3dfc2d95908129eea5ed598562"
    assert s.inference_concurrency == 2
    assert s.worker_concurrency == 1
    assert s.max_inflight == 32
    assert s.max_response_bytes == 4_000_000
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
    s = Settings(
        api_keys="k1",
        hash_salt="a-strong-secret",
        trusted_hosts="localhost",
        job_payload_encryption_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    )
    s.verify()


def test_production_rejects_wildcard_cors(tmp_path) -> None:
    settings = Settings(
        api_keys="k1",
        hash_salt="a-strong-secret",
        trusted_hosts="localhost",
        cors_origins="*",
        policies_dir=str(tmp_path),
        job_payload_encryption_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    )
    (tmp_path / "default.yaml").write_text(
        "name: default\nversion: 1.0.0\nfields: {}\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="wildcard CORS"):
        settings.verify()


def test_production_requires_a_valid_default_policy(tmp_path) -> None:
    settings = Settings(
        api_keys="k1",
        hash_salt="a-strong-secret",
        trusted_hosts="localhost",
        policies_dir=str(tmp_path),
        job_payload_encryption_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    )
    with pytest.raises(ValueError, match="REDAX_DEFAULT_POLICY"):
        settings.verify()

    (tmp_path / "default.yaml").write_text(
        "name: default\nversion: 1.0.0\nfields:\n  email:\n    strategy: unsupported\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="REDAX_DEFAULT_POLICY"):
        settings.verify()


def test_validate_refuses_dev_key() -> None:
    s = Settings(api_keys="dev-key", hash_salt="a-strong-secret")
    with pytest.raises(ValueError, match="REDAX_API_KEYS"):
        s.verify()


def test_production_redis_audit_requires_integrity_key(tmp_path) -> None:
    settings = Settings(
        env="prod",
        api_keys="k1",
        hash_salt="a-strong-secret",
        trusted_hosts="localhost",
        policies_dir=str(tmp_path),
        audit_backend="redis",
        job_payload_encryption_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    )
    (tmp_path / "default.yaml").write_text(
        "name: default\nversion: 1.0.0\nfields: {}\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="REDAX_AUDIT_INTEGRITY_KEY"):
        settings.verify()


def test_validate_refuses_default_salt_even_without_auth() -> None:
    s = Settings(api_keys="", hash_salt="change-me")
    with pytest.raises(ValueError, match="REDAX_HASH_SALT"):
        s.verify()


def test_validate_requires_model_revision() -> None:
    s = Settings(
        model_revision="",
        hash_salt="a-strong-secret",
        api_keys="k1",
        trusted_hosts="localhost",
        job_payload_encryption_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    )
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


def test_api_key_revocation_removes_key_from_authentication_set() -> None:
    s = Settings(api_keys="a,b", api_key_revocations=" b ")
    assert s.configured_api_key_set() == {"a", "b"}
    assert s.api_key_revoked_set() == {"b"}
    assert s.api_key_set() == {"a"}


def test_api_key_revocation_must_reference_configured_key() -> None:
    s = Settings(
        api_keys="a",
        api_key_revocations="b",
        hash_salt="a-strong-secret",
        trusted_hosts="localhost",
        job_payload_encryption_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    )
    with pytest.raises(ValueError, match="configured API keys only"):
        s.verify()


def test_production_cannot_revoke_every_api_key() -> None:
    s = Settings(
        api_keys="a,b",
        api_key_revocations="a,b",
        hash_salt="a-strong-secret",
        trusted_hosts="localhost",
        job_payload_encryption_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    )
    with pytest.raises(ValueError, match="every production API key"):
        s.verify()


def test_api_key_scopes_parse_json() -> None:
    s = Settings(
        api_keys="k1,k2",
        api_key_scopes='{"k1":["redact","jobs"],"k2":["policies:read"]}',
    )
    assert s.api_key_scope_map() == {
        "k1": {"redact", "jobs"},
        "k2": {"policies:read"},
    }


def test_api_key_scopes_must_cover_configured_keys() -> None:
    s = Settings(
        api_keys="k1,k2",
        api_key_scopes='{"k1":["redact"]}',
        hash_salt="a-strong-secret",
        trusted_hosts="localhost",
    )
    with pytest.raises(ValueError, match="exactly the configured API keys"):
        s.verify()


def test_detector_validated() -> None:
    with pytest.raises(ValidationError):
        Settings(detector="ner")


def test_env_prefix_reads_underscore_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDAX_MAX_INFLIGHT", "7")
    s = Settings()
    assert s.max_inflight == 7
