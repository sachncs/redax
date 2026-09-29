"""Emit machine-readable provenance metadata for a Redax release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one release input file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project_version() -> str:
    """Read the package version without importing the application."""
    with (ROOT / "pyproject.toml").open("rb") as stream:
        return str(tomllib.load(stream)["project"]["version"])


def git_commit() -> str:
    """Return the CI commit, falling back to the local checkout revision."""
    configured = os.environ.get("GITHUB_SHA", "").strip()
    if configured:
        return configured
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def model_revisions(path: Path) -> list[dict[str, str]]:
    """Parse the checked-in model digest manifest."""
    models: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) == 3 and not line.startswith("#"):
            digest, repo_id, revision = fields
            models.append({"sha256": digest, "repo_id": repo_id, "revision": revision})
    return models


def build_metadata() -> dict[str, Any]:
    """Build deterministic release metadata from repository inputs."""
    lockfile = ROOT / "requirements.lock"
    model_manifest = ROOT / "MODEL_HASHES.txt"
    return {
        "metadata_schema_version": 1,
        "project_version": project_version(),
        "git_commit": git_commit(),
        "requirements_lock_sha256": sha256_file(lockfile),
        "model_manifest_sha256": sha256_file(model_manifest),
        "models": model_revisions(model_manifest),
        "persisted_schema_versions": {
            "audit_event": 1,
            "cache_envelope": 1,
            "durable_job": 1,
            "idempotency": 3,
        },
    }


def main() -> None:
    """Write release metadata as stable, reviewable JSON."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(build_metadata(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
