"""Shared HTTP policy resolution and audit metadata helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.redaction.policies import load_policy, parse_policy_dict


def normalized_policy(raw: dict[str, Any], source: str) -> dict[str, Any]:
    """Validate a policy and return the canonical request shape."""
    parsed = parse_policy_dict(raw, source=source)
    return {
        "name": parsed.name,
        "version": parsed.version,
        "description": parsed.description,
        "fields": parsed.fields,
    }


def default_policy(settings: Any) -> dict[str, Any] | None:
    """Load the configured default policy, or ``None`` when it is unavailable."""
    name = getattr(settings, "default_policy", "") if settings is not None else ""
    directory = getattr(settings, "policies_dir", "./policies") if settings is not None else ""
    if not name or not directory:
        return None
    path = Path(directory) / f"{name}.yaml"
    if not path.exists():
        return None
    loaded = load_policy(path)
    return normalized_policy(
        {
            "name": loaded.name,
            "version": loaded.version,
            "description": loaded.description,
            "fields": loaded.fields,
        },
        str(path),
    )


def effective_policy(
    settings: Any,
    policy: dict[str, Any] | None,
    entity_types: list[str] | None,
) -> dict[str, Any] | None:
    """Resolve explicit policy, entity-type selection, or the configured default."""
    if policy is not None:
        return normalized_policy(policy, "<request>")
    if entity_types is not None:
        return None
    return default_policy(settings)


def policy_version(policy: dict[str, Any] | None) -> str:
    """Return the version recorded in audit metadata for an effective policy."""
    if isinstance(policy, dict) and policy.get("version"):
        return str(policy["version"])
    return "default"
