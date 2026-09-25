from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_repository_surfaces_use_the_project_version() -> None:
    """Prevent a release from publishing mismatched version labels."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    site_content = (ROOT / "site/src/content/site.ts").read_text(encoding="utf-8")
    site_package = json.loads((ROOT / "site/package.json").read_text(encoding="utf-8"))
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    api_docs = (ROOT / "docs/api.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert f'version: "{version}"' in site_content
    assert site_package["version"] == version
    assert "version=PROJECT_VERSION" in main
    assert f'"version": "{version}"' in api_docs
    assert re.search(rf"early-stage software \(`{re.escape(version)}`\)", readme)
