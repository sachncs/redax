from __future__ import annotations

from types import SimpleNamespace

from app.jobs.queue import worker_redis_settings


def test_worker_redis_settings_overrides_parsed_connection_limits() -> None:
    settings = SimpleNamespace(
        redis_url="redis://redis.example.test:6380/2",
        redis_connect_timeout_seconds=0.2,
        redis_max_connections=17,
    )

    redis_settings = worker_redis_settings(settings)

    assert redis_settings.host == "redis.example.test"
    assert redis_settings.port == 6380
    assert redis_settings.database == 2
    assert redis_settings.conn_timeout == 1
    assert redis_settings.max_connections == 17
    assert redis_settings.retry_on_timeout is True
