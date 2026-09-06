from __future__ import annotations

import os
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide configuration.

    Read from environment variables prefixed with REDAX_. Values are
    validated at construction; missing or unknown values raise so a typo
    or a stale var (e.g. the removed REDAX_JWT_SECRET) can never silently
    change behavior.
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

    redis_url: str = "redis://localhost:6379/0"
    service_name: str = "redax"

    detector: Literal["gliner2", "regex"] = "gliner2"
    model_cache: str = "./models_cache"
    model_name: str = "fastino/gliner2-privacy-filter-PII-multi"
    model_revision: str = "c153999da5f4c509df4322b0c6a1baf3d2c284d7"
    model_threshold: float = Field(default=0.5, ge=0.0, le=1.0)

    policies_dir: str = "./policies"
    default_policy: str = "default"

    audit_path: str = "./audit.jsonl"
    audit_fsync: bool = True
    audit_max_bytes: int = Field(default=1_000_000_000, ge=1)
    audit_rotation_backups: int = Field(default=5, ge=0)
    audit_retention_seconds: int = Field(default=90 * 24 * 3600, ge=1)

    hash_salt: str = "change-me"
    max_text_chars: int = Field(default=100_000, ge=1)

    api_keys: str = ""

    rate_limit_per_minute: int = Field(default=60, ge=0)
    idempotency_ttl_seconds: int = Field(default=86_400, ge=0)
    cache_ttl_seconds: int = Field(default=3_600, ge=0)
    cache_shared: bool = False

    inference_concurrency: int = Field(default=2, ge=1)
    worker_concurrency: int = Field(default=1, ge=1)
    max_inflight: int = Field(default=32, ge=1)
    max_jobs_per_key: int = Field(default=50, ge=1)
    job_ttl_seconds: int = Field(default=86_400, ge=1)
    request_timeout_seconds: float = Field(default=30.0, ge=0.1)
    stream_chunk_bytes: int = Field(default=4096, ge=64)
    stream_chunk_chars: int = Field(default=2000, ge=100, le=50_000)

    relex_cache_size: int = Field(default=10_000, ge=0)
    multi_pass_max: int = Field(default=3, ge=1)

    metrics_by_tenant: bool = False

    otlp_endpoint: str | None = None

    def api_key_set(self) -> set[str]:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

    def verify(self) -> None:
        """Fail loudly on configuration that would undermine safety.

        Raised at boot (lifespan) so a misconfiguration is impossible to
        run silently. Covers the secrets guard and downgrade-sensitive
        settings.
        """
        keys = self.api_key_set()
        if keys:
            defaults = {"change-me", "dev-key"}
            if self.hash_salt in defaults or (keys & defaults):
                raise ValueError(
                    "REDAX_HASH_SALT and REDAX_API_KEYS must be real secrets; "
                    "the defaults (change-me/dev-key) are refused when "
                    "authentication is enabled."
                )
        if "REDAX_JWT_SECRET" in os.environ:
            raise ValueError(
                "REDAX_JWT_SECRET no longer exists; remove it from the "
                "environment (API keys now live in REDAX_API_KEYS)."
            )
        if self.detector == "regex":
            # Explicit opt-in only; regex is the boot-time fallback path.
            return
        if not self.model_name or not self.model_revision:
            raise ValueError("REDAX_MODEL_NAME and REDAX_MODEL_REVISION are required")
