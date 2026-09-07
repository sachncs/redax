"""Deterministic filesystem hashing helpers.

The only public function is :func:`snapshot_digest`, which produces a
SHA-256 over a directory tree in a stable, layout-sensitive way: each
file's relative path and its own SHA-256 are hashed in sorted order, so
any change to a file or a rename moves the digest.

This module is intentionally tiny and dependency-free so it can be
imported by the model-download script, the runtime, and the tests
without pulling in heavy transitive packages.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def sha256_file(path: Path) -> str:
    """Compute the SHA-256 hex digest of a single file.

    Reads the file in 1 MiB chunks so very large model snapshots do not
    have to fit in memory.

    Args:
        path: The file to hash.

    Returns:
        The 64-character hex SHA-256 digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_digest(root: Path) -> str:
    """Deterministic sha256 over all files under ``root``.

    Combines the relative path and each file's sha256 (ordered by path)
    so any content or layout change alters the digest. A directory with
    no files hashes the empty string.

    Args:
        root: The directory to hash. The hash is taken over the
            relative paths of every regular file beneath it, plus each
            file's content hash.

    Returns:
        The 64-character hex SHA-256 digest.
    """
    files = sorted(
        (p.relative_to(root) for p in root.rglob("*") if p.is_file()),
        key=lambda p: os.fsencode(p.as_posix()),
    )
    h = hashlib.sha256()
    for rel in files:
        h.update(os.fsencode(rel.as_posix()))
        h.update(b"\n")
        h.update(bytes.fromhex(sha256_file(root / rel)))
        h.update(b"\n")
    return h.hexdigest()
