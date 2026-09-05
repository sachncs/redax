from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide configuration.

    Read from environment variables prefixed with REDAX_. Values are validated
    at construction; missing required values raise.
    """

    model_config = SettingsConfigDict(
        env_prefix="REDAX_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000

    redis_url: str = "redis://localhost:6379/0"

    model_cache: str = "./models_cache"
    model_name: str = "fastino/gliner2-privacy-filter-PII-multi"
    model_revision: str | None = None
    model_threshold: float = 0.5

    policies_dir: str = "./policies"
    default_policy: str = "default"

    audit_path: str = "./audit.jsonl"
    audit_async_flush: bool = True

    hash_salt: str = "change-me"
    max_text_chars: int = 100_000

    api_keys: str = ""
    jwt_secret: str | None = None

    rate_limit_per_minute: int = 60
    idempotency_ttl_seconds: int = 86_400
    cache_ttl_seconds: int = 3_600

    otlp_endpoint: str | None = None
    service_name: str = "redax"

    def api_key_set(self) -> set[str]:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}
