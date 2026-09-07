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


def test_gliner2_rscore_at_least_matches_regex_baseline() -> None:
    """Approval-test-style assertion: the strongest non-regex detector we
    can score locally must score at least as well as the regex baseline
    on the ReaxionBench fixture. If this ever fails, the regex baseline
    is no longer the floor and the docs/benchmark-results.md comparison
    table needs to be regenerated.
    """
    regex = subprocess.run(
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
    gliner2 = subprocess.run(
        [
            sys.executable,
            "scripts/run_bench.py",
            "--corpus",
            str(FIXTURE_DIR),
            "--detector",
            "gliner2",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    regex_mean = json.loads(regex.stdout)["corpus_mean"]
    gliner2_mean = json.loads(gliner2.stdout)["corpus_mean"]
    assert gliner2_mean >= regex_mean, (
        f"gliner2 mean_R={gliner2_mean:.4f} < regex mean_R={regex_mean:.4f}; "
        "the model has regressed below the regex safety-net floor."
    )
