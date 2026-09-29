"""Validate and summarize the production-readiness matrix."""

import json
import re
import sys
from pathlib import Path

STATUS_VALUES = {"PASS", "FAIL", "NOT APPLICABLE"}
ROW_PATTERN = re.compile(r"^\| (?P<requirement>[^|]+) \| (?P<status>[^|]+) \| (?P<evidence>.+) \|$")


def main() -> int:
    path = Path(__file__).parents[1] / "PRODUCTION_READINESS.md"
    rows: list[dict[str, str]] = []
    errors: list[str] = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if (
            not line.startswith("| ")
            or line.startswith("| Requirement ")
            or line.startswith("|---")
        ):
            continue
        match = ROW_PATTERN.match(line)
        if match is None:
            errors.append(f"line {line_number}: malformed readiness row")
            continue
        status = match.group("status").strip()
        if status not in STATUS_VALUES:
            errors.append(f"line {line_number}: invalid status {status!r}")
        rows.append(
            {
                "requirement": match.group("requirement").strip(),
                "status": status,
                "evidence": match.group("evidence").strip(),
            }
        )

    if not rows:
        errors.append("no readiness rows found")
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    summary = {
        "schema_version": 1,
        "source": str(path.name),
        "status": "PASS"
        if all(row["status"] in {"PASS", "NOT APPLICABLE"} for row in rows)
        else "FAIL",
        "counts": {
            status: sum(row["status"] == status for row in rows) for status in sorted(STATUS_VALUES)
        },
        "requirements": rows,
    }
    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
