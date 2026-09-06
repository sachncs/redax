from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Policy:
    name: str
    version: str
    description: str = ""
    fields: dict[str, dict[str, Any]] = field(default_factory=dict)


def load_policy(path: str | Path) -> Policy:
    """Parse a policy YAML file into a Policy dataclass."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"policy not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return parse_policy(raw, source=str(path))


def parse_policy_dict(raw: dict[str, Any], source: str = "<dict>") -> Policy:
    """Parse an in-memory dict into a Policy. Useful for tests + API
    bodies that ship policies inline."""
    return parse_policy(raw, source=source)


def parse_policy(raw: dict[str, Any], source: str) -> Policy:
    fields_raw = raw.get("fields", {}) or {}
    if not isinstance(fields_raw, dict):
        raise ValueError(f"{source}: 'fields' must be a mapping")
    for fname, fcfg in fields_raw.items():
        if not isinstance(fcfg, dict):
            raise ValueError(f"{source}: field {fname!r} must be a mapping")
        if "strategy" not in fcfg:
            raise ValueError(f"{source}: field {fname!r} missing 'strategy'")
    return Policy(
        name=str(raw.get("name", "default")),
        version=str(raw.get("version", "0.0.0")),
        description=str(raw.get("description", "")),
        fields=fields_raw,
    )


def list_policies(policies_dir: str | Path) -> list[Policy]:
    """Load every .yaml in `policies_dir` and return them sorted by name."""
    directory = Path(policies_dir)
    if not directory.exists():
        return []
    out: list[Policy] = []
    for path in sorted(directory.glob("*.yaml")):
        out.append(load_policy(path))
    return out
