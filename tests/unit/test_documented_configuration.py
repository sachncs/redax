from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings

ROOT = Path(__file__).parents[2]


def test_deployment_docs_list_every_settings_environment_variable() -> None:
    """Keep the operator configuration table aligned with ``Settings``."""
    documented = set(
        re.findall(
            r"`(REDAX_[A-Z0-9_]+)`",
            (ROOT / "docs" / "deployment.md").read_text(encoding="utf-8"),
        )
    )
    configured = {f"REDAX_{name.upper()}" for name in Settings.model_fields}

    assert documented == configured
