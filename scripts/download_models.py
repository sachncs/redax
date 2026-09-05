#!/usr/bin/env python3
"""Pre-download Redax models into the local cache.

Usage:
    python scripts/download_models.py [--model fastino/gliner2-privacy-filter-PII-multi]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        default="fastino/gliner2-privacy-filter-PII-multi",
    )
    parser.add_argument(
        "--cache",
        default=os.environ.get("REDAX_MODEL_CACHE", "./models_cache"),
    )
    args = parser.parse_args()

    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(cache)

    print(f"downloading {args.model} -> {cache}", file=sys.stderr)
    try:
        from transformers import AutoTokenizer  # type: ignore[import-not-found]

        AutoTokenizer.from_pretrained(args.model)
        print("tokenizer cached", file=sys.stderr)
    except Exception as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
