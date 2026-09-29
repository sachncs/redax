from __future__ import annotations

from pathlib import Path

import pytest

from app.api.policy import (
    PolicyUnavailableError,
    default_policy,
    effective_policy,
    policy_version,
)


class SettingsStub:
    default_policy = "default"
    policies_dir = str(Path(__file__).parents[2] / "policies")


def test_default_policy_is_shared_by_http_transports() -> None:
    policy = default_policy(SettingsStub())

    assert policy is not None
    assert policy["name"] == "default"
    assert policy["version"] == "1.0.0"
    assert "free_text" in policy["fields"]
    assert effective_policy(SettingsStub(), None, None) == policy


def test_explicit_entity_types_bypass_default_policy() -> None:
    assert effective_policy(SettingsStub(), None, ["EMAIL"]) is None


def test_policy_version_uses_effective_policy_metadata() -> None:
    assert policy_version({"version": "2.3.0"}) == "2.3.0"
    assert policy_version(None) == "default"


def test_configured_default_policy_failure_is_explicit(tmp_path) -> None:
    settings = type("Settings", (), {"default_policy": "default", "policies_dir": str(tmp_path)})()

    with pytest.raises(PolicyUnavailableError):
        default_policy(settings)
