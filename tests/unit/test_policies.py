from __future__ import annotations

from pathlib import Path

import pytest

from app.redaction.policies import list_policies, load_policy, parse_policy_dict


def test_load_default_policy(policies_path: Path) -> None:
    p = load_policy(policies_path / "default.yaml")
    assert p.name == "default"
    assert p.version == "1.0.0"
    assert "free_text" in p.fields
    assert p.fields["free_text"]["strategy"] == "autoDeID"


def test_parse_inline_dict() -> None:
    p = parse_policy_dict(
        {
            "name": "x",
            "version": "0.1.0",
            "fields": {"name": {"strategy": "mask", "format": "<X>"}},
        }
    )
    assert p.name == "x"
    assert p.fields["name"]["format"] == "<X>"


def test_load_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_policy(tmp_path / "nope.yaml")


def test_field_without_strategy_raises() -> None:
    with pytest.raises(ValueError):
        parse_policy_dict({"fields": {"x": {"format": "[X]"}}})


def test_field_must_be_mapping() -> None:
    with pytest.raises(ValueError):
        parse_policy_dict({"fields": {"x": "not a dict"}})


def test_fields_top_level_must_be_mapping() -> None:
    with pytest.raises(ValueError):
        parse_policy_dict({"fields": "oops"})


def test_list_policies_returns_sorted(policies_path: Path) -> None:
    policies = list_policies(policies_path)
    assert any(p.name == "default" for p in policies)


def test_list_policies_missing_dir(tmp_path: Path) -> None:
    assert list_policies(tmp_path / "nope") == []
