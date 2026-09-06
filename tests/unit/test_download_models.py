from __future__ import annotations

from pathlib import Path

import pytest

from scripts.download_models import read_manifest, record_manifest, snapshot_digest


def test_snapshot_digest_deterministic(tmp_path: Path) -> None:
    for root in (tmp_path / "a", tmp_path / "b"):
        root.mkdir()
        (root / "model.safetensors").write_bytes(b"bytes-1")
        sub = root / "sub"
        sub.mkdir()
        (sub / "config.json").write_bytes(b'{"x": 1}' + b"\n")
    assert snapshot_digest(tmp_path / "a") == snapshot_digest(tmp_path / "b")


def test_snapshot_digest_changes_when_content_changes(tmp_path: Path) -> None:
    (tmp_path / "model.bin").write_bytes(b"v1")
    before = snapshot_digest(tmp_path)
    (tmp_path / "model.bin").write_bytes(b"v2")
    assert snapshot_digest(tmp_path) != before


def test_snapshot_digest_changes_when_layout_changes(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f").write_bytes(b"x")
    before = snapshot_digest(tmp_path)
    (tmp_path / "a" / "f").rename(tmp_path / "f")
    assert snapshot_digest(tmp_path) != before


def test_read_manifest_parses_lines(tmp_path: Path) -> None:
    manifest = tmp_path / "MODEL_HASHES.txt"
    manifest.write_text(
        "# comment\n"
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa a  r1\n"
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb b  r2\n",
    )
    entries = read_manifest(manifest)
    assert entries == {
        ("a", "r1"): "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        ("b", "r2"): "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    }


def test_read_manifest_rejects_malformed(tmp_path: Path) -> None:
    manifest = tmp_path / "MODEL_HASHES.txt"
    manifest.write_text("only-two-fields\n")
    with pytest.raises(ValueError, match="expected '<sha256> <repo_id> <revision>'"):
        read_manifest(manifest)


def test_record_manifest_upserts_and_sorts(tmp_path: Path) -> None:
    manifest = tmp_path / "MODEL_HASHES.txt"
    record_manifest("zeta", "r1", "z1", manifest)
    record_manifest("alpha", "r2", "a2", manifest)
    record_manifest("zeta", "r1", "z1-new", manifest)
    text = manifest.read_text()
    assert read_manifest(manifest) == {
        ("alpha", "r2"): "a2",
        ("zeta", "r1"): "z1-new",
    }
    assert text.index("alpha") < text.index("zeta")
