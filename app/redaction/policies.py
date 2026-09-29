"""YAML policy loader for redax."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_STRATEGIES = frozenset({"passThrough", "mask", "hash", "regex", "autoDeID"})
SUPPORTED_FIELD_OPTIONS = frozenset(
    {"strategy", "format", "entity_types", "relex", "multi_pass", "detector", "length"}
)
MAX_POLICY_FIELDS = 128
MAX_POLICY_FIELD_NAME_CHARS = 128
MAX_POLICY_STRING_CHARS = 4096
MAX_POLICY_ENTITY_TYPES = 128
MAX_POLICY_ENTITY_TYPE_CHARS = 128
MAX_POLICY_MULTI_PASS = 3
MAX_POLICY_HASH_LENGTH = 64


@dataclass
class Policy:
    """A redaction policy: a name, a version, a description, and a map of
    field name -> per-field redaction config."""

    name: str
    version: str
    description: str = ""
    fields: dict[str, dict[str, Any]] = field(default_factory=dict)


def load_policy(path: str | Path) -> Policy:
    """Parse a policy YAML file into a ``Policy`` dataclass.

    Args:
        path: Path to a YAML file conforming to the redax policy schema.

    Returns:
        The parsed Policy.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If the YAML body is not a well-formed policy mapping.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"policy not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return parse_policy(raw, source=str(path))


def parse_policy_dict(raw: dict[str, Any], source: str = "<dict>") -> Policy:
    """Parse an in-memory dict into a ``Policy``.

    Useful for tests and API bodies that ship policies inline.

    Args:
        raw: The policy mapping, typically decoded from JSON / YAML.
        source: Human-readable origin for error messages.

    Returns:
        The parsed Policy.
    """
    return parse_policy(raw, source=source)


def parse_policy(raw: dict[str, Any], source: str) -> Policy:
    """Validate a raw policy mapping and build a ``Policy`` instance.

    Args:
        raw: Untrusted mapping (typically from YAML / JSON).
        source: Human-readable origin for error messages.

    Returns:
        The parsed Policy.

    Raises:
        ValueError: If ``raw['fields']`` is not a mapping, or if any field
            config is missing the required ``strategy`` key.
    """
    fields_raw = raw.get("fields", {}) or {}
    if not isinstance(fields_raw, dict):
        raise ValueError(f"{source}: 'fields' must be a mapping")
    if len(fields_raw) > MAX_POLICY_FIELDS:
        raise ValueError(f"{source}: 'fields' must contain at most {MAX_POLICY_FIELDS} entries")
    for fname, fcfg in fields_raw.items():
        if not isinstance(fname, str) or not fname:
            raise ValueError(f"{source}: field names must be non-empty strings")
        if len(fname) > MAX_POLICY_FIELD_NAME_CHARS:
            raise ValueError(
                f"{source}: field names must be at most {MAX_POLICY_FIELD_NAME_CHARS} characters"
            )
        if not isinstance(fcfg, dict):
            raise ValueError(f"{source}: field {fname!r} must be a mapping")
        if "strategy" not in fcfg:
            raise ValueError(f"{source}: field {fname!r} missing 'strategy'")
        strategy = fcfg["strategy"]
        if strategy not in SUPPORTED_STRATEGIES:
            raise ValueError(f"{source}: field {fname!r} uses unsupported strategy {strategy!r}")
        unknown_options = set(fcfg) - SUPPORTED_FIELD_OPTIONS
        if unknown_options:
            raise ValueError(
                f"{source}: field {fname!r} has unknown options {sorted(unknown_options)!r}"
            )
        for option in ("format", "detector"):
            value = fcfg.get(option)
            if value is not None and (
                not isinstance(value, str) or len(value) > MAX_POLICY_STRING_CHARS
            ):
                raise ValueError(
                    f"{source}: field {fname!r} option {option!r} must be a string of at most "
                    f"{MAX_POLICY_STRING_CHARS} characters"
                )
        entity_types = fcfg.get("entity_types")
        if entity_types is not None:
            if not isinstance(entity_types, list) or len(entity_types) > MAX_POLICY_ENTITY_TYPES:
                raise ValueError(
                    f"{source}: field {fname!r} 'entity_types' must contain at most "
                    f"{MAX_POLICY_ENTITY_TYPES} entries"
                )
            if any(
                not isinstance(entity_type, str)
                or not entity_type
                or len(entity_type) > MAX_POLICY_ENTITY_TYPE_CHARS
                for entity_type in entity_types
            ):
                raise ValueError(
                    f"{source}: field {fname!r} 'entity_types' entries must be non-empty strings "
                    f"of at most {MAX_POLICY_ENTITY_TYPE_CHARS} characters"
                )
        multi_pass = fcfg.get("multi_pass")
        if multi_pass is not None and (
            isinstance(multi_pass, bool)
            or not isinstance(multi_pass, int)
            or not 1 <= multi_pass <= MAX_POLICY_MULTI_PASS
        ):
            raise ValueError(
                f"{source}: field {fname!r} 'multi_pass' must be an integer from 1 to "
                f"{MAX_POLICY_MULTI_PASS}"
            )
        length = fcfg.get("length")
        if length is not None and (
            isinstance(length, bool)
            or not isinstance(length, int)
            or not 1 <= length <= MAX_POLICY_HASH_LENGTH
        ):
            raise ValueError(
                f"{source}: field {fname!r} 'length' must be an integer from 1 to "
                f"{MAX_POLICY_HASH_LENGTH}"
            )
    for metadata in ("name", "version", "description"):
        value = raw.get(metadata)
        if value is not None and len(str(value)) > MAX_POLICY_STRING_CHARS:
            raise ValueError(
                f"{source}: {metadata!r} must be at most {MAX_POLICY_STRING_CHARS} characters"
            )
    return Policy(
        name=str(raw.get("name", "default")),
        version=str(raw.get("version", "0.0.0")),
        description=str(raw.get("description", "")),
        fields=fields_raw,
    )


def list_policies(policies_dir: str | Path) -> list[Policy]:
    """Load every ``.yaml`` file in ``policies_dir``, sorted by name.

    Args:
        policies_dir: Directory containing one or more ``*.yaml`` policy
            files.

    Returns:
        Sorted list of parsed policies. Empty list if the directory does
        not exist.
    """
    directory = Path(policies_dir)
    if not directory.exists():
        return []
    out: list[Policy] = []
    for path in sorted(directory.glob("*.yaml")):
        out.append(load_policy(path))
    return out
