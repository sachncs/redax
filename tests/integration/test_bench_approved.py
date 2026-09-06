from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from approvaltests import verify
from approvaltests.reporters.python_native_reporter import PythonNativeReporter

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "redactionbench"


def test_run_bench_cli_emits_approval_snapshot() -> None:
    output = subprocess.run(
        [
            sys.executable,
            "scripts/run_bench.py",
            "--corpus",
            str(FIXTURE_DIR),
            "--detector",
            "regex",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(output.stdout)
    assert "per_document" in payload
    assert "corpus_mean" in payload
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    verify(rendered, reporter=PythonNativeReporter())
