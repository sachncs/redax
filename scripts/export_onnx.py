#!/usr/bin/env python3
"""Export the GLiNER2 PyTorch detector to ONNX.

Reads the cached HF model and writes wasm/model.onnx.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="fastino/gliner2-privacy-filter-PII-multi")
    parser.add_argument(
        "--cache",
        default=os.environ.get("REDAX_MODEL_CACHE", "./models_cache"),
    )
    parser.add_argument("--out", default="wasm/model.onnx")
    args = parser.parse_args()

    os.environ["HF_HOME"] = args.cache
    Path(args.cache).mkdir(parents=True, exist_ok=True)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)

    print(f"loading {args.model}", file=sys.stderr)
    try:
        from optimum.exporters.onnx import main_export  # type: ignore[import-not-found]

        main_export(
            model_name_or_path=args.model,
            output=args.out,
            task="token-classification",
            opset=17,
        )
        print(f"wrote {args.out}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"export failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
