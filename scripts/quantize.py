#!/usr/bin/env python3
"""Quantize an ONNX model to INT8 (dynamic quantization).

Reads wasm/model.onnx and writes wasm/model.int8.onnx.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="src", default="wasm/model.onnx")
    parser.add_argument("--out", default="wasm/model.int8.onnx")
    args = parser.parse_args()

    src = Path(args.src)
    dst = Path(args.out)
    if not src.exists():
        print(f"not found: {src}", file=sys.stderr)
        return 1
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        from onnxruntime.quantization import (  # type: ignore[import-not-found]
            QuantType,
            quantize_dynamic,
        )

        quantize_dynamic(
            model_input=str(src),
            model_output=str(dst),
            weight_type=QuantType.QInt8,
        )
        print(f"wrote {dst} ({dst.stat().st_size // 1024} KiB)", file=sys.stderr)
    except Exception as exc:
        print(f"quantize failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
