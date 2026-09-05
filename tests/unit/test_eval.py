from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FIXTURE = Path(__file__).parent.parent / "fixtures" / "synthetic_pii.jsonl"


def test_eval_runs_against_fixture() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/eval.py", "--fixture", str(FIXTURE)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "OVERALL" in result.stdout
    assert "1.000" in result.stdout


def test_fixture_is_valid_jsonl() -> None:
    lines = [ln for ln in FIXTURE.read_text().splitlines() if ln.strip()]
    assert len(lines) > 0
    for line in lines:
        obj = json.loads(line)
        assert "text" in obj
        assert "entities" in obj
        for ent in obj["entities"]:
            assert all(k in ent for k in ("start", "end", "type", "confidence"))
