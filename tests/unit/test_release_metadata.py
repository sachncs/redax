from __future__ import annotations

import hashlib

from app.schema_versions import (
    AUDIT_EVENT_SCHEMA_VERSION,
    CACHE_ENVELOPE_SCHEMA_VERSION,
    DURABLE_JOB_SCHEMA_VERSION,
    IDEMPOTENCY_SCHEMA_VERSION,
)
from scripts.release_metadata import ROOT, build_metadata


def test_release_metadata_binds_release_inputs(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)

    metadata = build_metadata()

    assert metadata["metadata_schema_version"] == 1
    assert metadata["git_commit"] == "a" * 40
    assert (
        metadata["requirements_lock_sha256"]
        == hashlib.sha256((ROOT / "requirements.lock").read_bytes()).hexdigest()
    )
    assert (
        metadata["model_manifest_sha256"]
        == hashlib.sha256((ROOT / "MODEL_HASHES.txt").read_bytes()).hexdigest()
    )
    assert metadata["models"] == [
        {
            "sha256": "4be4139db04aea39c21395ce8eeb0210ae4849fe226af2ef31a42698fb832323",
            "repo_id": "OpenMed/OpenMed-PII-SuperClinical-Large-434M-v1",
            "revision": "df7af994d39d358e52f929ff1b3a40d894adf022",
        },
        {
            "sha256": "e1cd8966e7a56c2fa543f43a521edde8426c701509420d2d08c57a06ead7f33e",
            "repo_id": "fastino/GLiNER2-Guardrails-PII-Multi",
            "revision": "aad696b2f6815e3dfc2d95908129eea5ed598562",
        },
    ]
    assert metadata["persisted_schema_versions"] == {
        "audit_event": AUDIT_EVENT_SCHEMA_VERSION,
        "cache_envelope": CACHE_ENVELOPE_SCHEMA_VERSION,
        "durable_job": DURABLE_JOB_SCHEMA_VERSION,
        "idempotency": IDEMPOTENCY_SCHEMA_VERSION,
    }


def test_release_metadata_can_bind_published_image_digest() -> None:
    digest = "sha256:" + "a" * 64

    metadata = build_metadata(digest)

    assert metadata["container_image_digest"] == digest
