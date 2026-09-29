from __future__ import annotations

import hashlib

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
            "sha256": "69a9cad2465548b4f5ee12f4e0a45a181827d1aa82dd6d2eb26fe04bf64cd8a0",
            "repo_id": "fastino/gliner2-privacy-filter-PII-multi",
            "revision": "c153999da5f4c509df4322b0c6a1baf3d2c284d7",
        },
    ]
    assert metadata["persisted_schema_versions"] == {
        "audit_event": 1,
        "cache_envelope": 1,
        "durable_job": 1,
        "idempotency": 3,
    }
