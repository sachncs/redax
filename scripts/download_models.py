#!/usr/bin/env python3
"""Download Redax models pinned to an exact revision and verify integrity.

The snapshot is downloaded with ``snapshot_download(..., revision=...)``
(never a moving tag), then a deterministic digest of the local snapshot is
compared against the committed manifest (MODEL_HASHES.txt). Failures are
loud: any drift or an unknown revision aborts with a non-zero exit so a
component can never boot on an unverified model.

Usage:
    python scripts/download_models.py                 # verify against manifest
    python scripts/download_models.py --record        # record entry after download
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

DEFAULT_MANIFEST = Path(__file__).resolve().parent.parent / "MODEL_HASHES.txt"


def snapshot_digest(root: Path) -> str:
    """Deterministic sha256 over all files under root.

    Combines the relative path and each file's sha256 (ordered by path) so
    any content or layout change alters the digest.
    """
    files = sorted(
        (p.relative_to(root) for p in root.rglob("*") if p.is_file()),
        key=lambda p: os.fsencode(p.as_posix()),
    )
    h = hashlib.sha256()
    for rel in files:
        h.update(os.fsencode(rel.as_posix()))
        h.update(b"\n")
        h.update(bytes.fromhex(_sha256_file(root / rel)))
        h.update(b"\n")
    return h.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest(path: Path = DEFAULT_MANIFEST) -> dict[tuple[str, str], str]:
    """Parse MODEL_HASHES.txt -> {(repo_id, revision): digest}."""
    entries: dict[tuple[str, str], str] = {}
    if not path.exists():
        return entries
    for line_no, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"{path}:{line_no}: expected '<sha256> <repo_id> <revision>'")
        digest, repo, revision = parts
        entries[(repo, revision)] = digest
    return entries


def record_manifest(
    repo_id: str,
    revision: str,
    digest: str,
    path: Path = DEFAULT_MANIFEST,
) -> None:
    """Upsert one entry into the manifest, keeping entries sorted."""
    entries = read_manifest(path)
    entries[(repo_id, revision)] = digest
    body = "".join(f"{d} {r} {rev}\n" for (r, rev), d in sorted(entries.items()))
    header = (
        "# sha256 digests of pinned model snapshots.\n"
        "# Format: <sha256> <repo_id> <revision>\n"
        "# Regenerate with: python scripts/download_models.py --record\n"
    )
    path.write_text(header + body)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download and verify Redax models")
    parser.add_argument("--model", default=None, help="repo_id (default: REDAX_MODEL_NAME)")
    parser.add_argument(
        "--revision", default=None, help="git revision (default: REDAX_MODEL_REVISION)"
    )
    parser.add_argument(
        "--cache", default=None, help="cache root (default: REDAX_MODEL_CACHE or ./models_cache)"
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="manifest path (default: MODEL_HASHES.txt)",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="write a manifest entry after download (maintainer action)",
    )
    args = parser.parse_args(argv)

    from app.config import Settings

    settings = Settings()
    cache = Path(args.cache or settings.model_cache)
    manifest = Path(args.manifest)
    name = args.model or settings.model_name
    revision = args.revision or settings.model_revision

    cache.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(cache)
    print(f"downloading {name}@{revision} -> {cache}", file=sys.stderr)
    try:
        from huggingface_hub import snapshot_download

        resolved = snapshot_download(repo_id=name, revision=revision, cache_dir=str(cache))
        root = Path(resolved)
        digest = snapshot_digest(root)
        manifest_entries = read_manifest(manifest)
        expected = manifest_entries.get((name, revision))
        if expected is None:
            if not args.record:
                print(
                    f"error: no manifest entry for {name}@{revision}; "
                    f"run with --record to trust this snapshot (digest={digest})",
                    file=sys.stderr,
                )
                return 1
            record_manifest(name, revision, digest, manifest)
            print(f"recorded digest for {name}@{revision}: {digest}", file=sys.stderr)
            return 0
        if expected == digest:
            print(f"verified {name}@{revision} digest {digest}", file=sys.stderr)
            return 0
        if args.record:
            record_manifest(name, revision, digest, manifest)
            print(
                f"re-recorded digest for {name}@{revision}: {digest} "
                f"(was {expected})",
                file=sys.stderr,
            )
            return 0
        print(
            f"error: model digest mismatch for {name}@{revision}\n"
            f"  expected: {expected}\n"
            f"  actual:   {digest}\n"
            f"The pinned revision content differs from the manifest; refusing to proceed.",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"download failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
