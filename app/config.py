"""Process-wide typed configuration for redax.

Read from environment variables prefixed with ``REDAX_`` and (optionally)
from a ``.env`` file in the working directory. Values are validated at
construction; missing or unknown values raise so a typo or a stale var
(e.g. the removed ``REDAX_JWT_SECRET``) can never silently change
behavior.
"""

from __future__ import annotations

import json
import os
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SUPPORTED_API_SCOPES = frozenset({"redact", "detect", "jobs", "policies:read", "metrics:read"})


class Settings(BaseSettings):
    """Pydantic-settings container for every redax knob.

    ``Settings()`` reads ``REDAX_*`` environment variables (and any
    ``.env`` in the working directory). Every field is typed; passing a
    string where a bool/int is expected raises at construction so a typo
    in the deployment config cannot silently downgrade behavior.
    """

    model_config = SettingsConfigDict(
        env_prefix="REDAX_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000
    env: Literal["dev", "prod"] = "prod"
    redis_namespace: str = "redax"
    cors_origins: str = ""
    trusted_hosts: str = ""

    redis_url: str = "redis://localhost:6379/0"
    redis_required: bool = False
    service_name: str = "redax"
    redis_connect_timeout_seconds: float = Field(default=1.0, ge=0.1)
    redis_socket_timeout_seconds: float = Field(default=1.0, ge=0.1)
    redis_max_connections: int = Field(default=64, ge=1)

    detector: Literal["gliner2", "regex"] = "gliner2"
    model_cache: str = "./models_cache"
    model_name: str = "fastino/gliner2-privacy-filter-PII-multi"
    model_revision: str = "c153999da5f4c509df4322b0c6a1baf3d2c284d7"
    model_threshold: float = Field(default=0.5, ge=0.0, le=1.0)

    policies_dir: str = "./policies"
    default_policy: str = "default"

    audit_backend: Literal["file", "redis"] = "file"
    audit_path: str = "./audit.jsonl"
    audit_required: bool = True
    audit_fsync: bool = True
    audit_max_bytes: int = Field(default=1_000_000_000, ge=1)
    audit_rotation_backups: int = Field(default=5, ge=0)
    audit_retention_seconds: int = Field(default=90 * 24 * 3600, ge=1)
    audit_redis_max_events: int = Field(default=100_000, ge=1)

    hash_salt: str = "change-me"
    max_body_bytes: int = Field(default=4_000_000, ge=1024)
    max_text_chars: int = Field(default=100_000, ge=1)
    max_batch_chars: int = Field(default=1_000_000, ge=1)

    api_keys: str = ""
    api_key_scopes: str = ""
    api_key_revocations: str = ""

    rate_limit_per_minute: int = Field(default=60, ge=0)
    rate_limit_fail_open: bool = False
    idempotency_ttl_seconds: int = Field(default=86_400, ge=0)
    cache_ttl_seconds: int = Field(default=3_600, ge=0)
    cache_shared: bool = False

    inference_concurrency: int = Field(default=2, ge=1)
    worker_concurrency: int = Field(default=1, ge=1)
    job_retry_jitter_seconds: float = Field(default=1.0, ge=0.0, le=30.0)
    job_payload_encryption_key: str = ""
    job_dead_letter_max: int = Field(default=1000, ge=1)
    max_inflight: int = Field(default=32, ge=1)
    max_jobs_per_key: int = Field(default=50, ge=1)
    max_concurrent_requests: int = Field(default=128, ge=1)
    request_admission_timeout_seconds: float = Field(default=0.01, ge=0.0, le=1.0)
    job_ttl_seconds: int = Field(default=86_400, ge=1)
    job_stale_seconds: int = Field(default=300, ge=1)
    request_timeout_seconds: float = Field(default=30.0, ge=0.1)
    request_body_timeout_seconds: float = Field(default=30.0, ge=0.1)
    shutdown_timeout_seconds: float = Field(default=30.0, ge=0.1)
    stream_chunk_bytes: int = Field(default=4096, ge=64)
    stream_chunk_chars: int = Field(default=2000, ge=100, le=50_000)
    stream_timeout_seconds: float = Field(default=60.0, ge=0.1)

    multi_pass_max: int = Field(default=3, ge=1)

    pipeline_breaker_threshold: int = Field(default=3, ge=1)
    pipeline_breaker_cooldown_s: float = Field(default=5.0, ge=0.1)
    pipeline_enabled: bool = True

    metrics_by_tenant: bool = False

    otlp_endpoint: str | None = None

    def api_key_set(self) -> set[str]:
        """Parse ``api_keys`` (comma-separated) into a deduped set of trimmed keys."""
        return self.configured_api_key_set() - self.api_key_revoked_set()

    def configured_api_key_set(self) -> set[str]:
        """Return every configured key before deployment revocations apply."""
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

    def api_key_revoked_set(self) -> set[str]:
        """Parse the deployment-provided comma-separated revocation denylist."""
        return {k.strip() for k in self.api_key_revocations.split(",") if k.strip()}

    def api_key_scope_map(self) -> dict[str, set[str]]:
        """Parse optional JSON API-key scopes without exposing key values."""
        if not self.api_key_scopes.strip():
            return {}
        parsed = json.loads(self.api_key_scopes)
        if not isinstance(parsed, dict):
            raise ValueError("REDAX_API_KEY_SCOPES must be a JSON object")
        scope_map: dict[str, set[str]] = {}
        for key, scopes in parsed.items():
            if (
                not isinstance(key, str)
                or not isinstance(scopes, list)
                or not all(isinstance(scope, str) for scope in scopes)
            ):
                raise ValueError("REDAX_API_KEY_SCOPES values must be arrays of strings")
            scope_map[key] = set(scopes)
        return scope_map

    def redis_prefix(self) -> str:
        """Return the Redis key prefix for this deployment.

        Default ``"redax"`` matches the historical key layout
        (``redax:cache:...``, ``redax:jobs:...``). Operators sharing
        one Redis between deployments should set
        ``REDAX_REDIS_NAMESPACE`` to a unique tag (e.g.
        ``"redax-prod-acme"``); every cache, idempotency, rate-limit,
        and job key is then namespaced as
        ``{namespace}:cache:...`` so two deployments cannot collide.
        """
        ns = self.redis_namespace.strip() or "redax"
        return ns

    def csv_values(self, value: str) -> list[str]:
        """Parse a comma-separated setting into stable, trimmed values."""
        return [item.strip() for item in value.split(",") if item.strip()]

    def cors_origin_list(self) -> list[str]:
        """Return configured CORS origins, empty when browser CORS is disabled."""
        return self.csv_values(self.cors_origins)

    def trusted_host_list(self) -> list[str]:
        """Return configured hostnames accepted by the HTTP middleware."""
        return self.csv_values(self.trusted_hosts)

    def verify(self) -> None:
        """Fail loudly on configuration that would undermine safety.

        Raised at boot (lifespan) so a misconfiguration is impossible to
        run silently. Covers the secrets guard and downgrade-sensitive
        settings.
        """
        defaults = {"change-me", "dev-key"}
        if self.hash_salt in defaults:
            raise ValueError(
                "REDAX_HASH_SALT must not use a default value; "
                "the placeholder (change-me) seeds the hash strategy and "
                "cache key and is unsafe regardless of REDAX_API_KEYS."
            )
        keys = self.configured_api_key_set()
        revoked = self.api_key_revoked_set()
        unknown_revocations = revoked - keys
        if unknown_revocations:
            raise ValueError("REDAX_API_KEY_REVOCATIONS must reference configured API keys only")
        scope_map = self.api_key_scope_map()
        if scope_map and set(scope_map) != keys:
            raise ValueError("REDAX_API_KEY_SCOPES must define exactly the configured API keys")
        unknown_scopes = (
            set().union(*scope_map.values()) - SUPPORTED_API_SCOPES if scope_map else set()
        )
        if unknown_scopes:
            raise ValueError(
                f"REDAX_API_KEY_SCOPES contains unsupported scopes: {sorted(unknown_scopes)}"
            )
        if keys and (keys & defaults):
            raise ValueError(
                "REDAX_API_KEYS must not use a default value; "
                "the placeholders (change-me/dev-key) are refused when "
                "authentication is enabled."
            )
        if "REDAX_JWT_SECRET" in os.environ:
            raise ValueError(
                "REDAX_JWT_SECRET no longer exists; remove it from the "
                "environment (API keys now live in REDAX_API_KEYS)."
            )
        if self.env == "prod" and not keys:
            raise ValueError(
                "REDAX_API_KEYS must be configured when REDAX_ENV=prod; "
                "use REDAX_ENV=dev only for local unauthenticated development."
            )
        if self.env == "prod" and not self.api_key_set():
            raise ValueError("REDAX_API_KEY_REVOCATIONS cannot revoke every production API key")
        if self.env == "prod" and not self.trusted_host_list():
            raise ValueError("REDAX_TRUSTED_HOSTS must be configured when REDAX_ENV=prod.")
        if self.job_payload_encryption_key:
            try:
                Fernet(self.job_payload_encryption_key.encode("ascii"))
            except (ValueError, UnicodeError) as exc:
                raise ValueError(
                    "REDAX_JOB_PAYLOAD_ENCRYPTION_KEY must be a valid Fernet key"
                ) from exc
        elif self.env == "prod":
            raise ValueError(
                "REDAX_JOB_PAYLOAD_ENCRYPTION_KEY must be configured when REDAX_ENV=prod"
            )
        if self.detector == "regex":
            # Explicit opt-in only; regex is the boot-time fallback path.
            return
        if not self.model_name or not self.model_revision:
            raise ValueError("REDAX_MODEL_NAME and REDAX_MODEL_REVISION are required")
