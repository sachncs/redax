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


def test_unknown_strategy_raises() -> None:
    with pytest.raises(ValueError, match="unsupported strategy"):
        parse_policy_dict({"fields": {"x": {"strategy": "unknown"}}})


def test_unknown_field_option_raises() -> None:
    with pytest.raises(ValueError, match="unknown options"):
        parse_policy_dict({"fields": {"x": {"strategy": "mask", "surprise": True}}})


def test_field_must_be_mapping() -> None:
    with pytest.raises(ValueError):
        parse_policy_dict({"fields": {"x": "not a dict"}})


def test_fields_top_level_must_be_mapping() -> None:
    with pytest.raises(ValueError):
        parse_policy_dict({"fields": "oops"})


def test_policy_rejects_too_many_fields() -> None:
    fields = {f"field_{index}": {"strategy": "passThrough"} for index in range(129)}
    with pytest.raises(ValueError, match="at most 128 entries"):
        parse_policy_dict({"fields": fields})


def test_policy_rejects_oversized_entity_type_list() -> None:
    with pytest.raises(ValueError, match=r"entity_types.*at most 128"):
        parse_policy_dict(
            {
                "fields": {
                    "free_text": {
                        "strategy": "autoDeID",
                        "entity_types": ["person"] * 129,
                    }
                }
            }
        )


def test_policy_rejects_oversized_format() -> None:
    with pytest.raises(ValueError, match=r"format.*4096"):
        parse_policy_dict({"fields": {"name": {"strategy": "mask", "format": "x" * 4097}}})


def test_policy_rejects_unbounded_execution_options() -> None:
    with pytest.raises(ValueError, match=r"multi_pass.*1 to 3"):
        parse_policy_dict({"fields": {"name": {"strategy": "autoDeID", "multi_pass": 4}}})
    with pytest.raises(ValueError, match=r"length.*1 to 64"):
        parse_policy_dict({"fields": {"name": {"strategy": "hash", "length": 65}}})


def test_list_policies_returns_sorted(policies_path: Path) -> None:
    policies = list_policies(policies_path)
    assert any(p.name == "default" for p in policies)


def test_list_policies_missing_dir(tmp_path: Path) -> None:
    assert list_policies(tmp_path / "nope") == []
