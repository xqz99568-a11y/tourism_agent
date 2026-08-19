"""Validate the frozen academic experiment design for Day8 task 4."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.academic_experiment_design import (  # noqa: E402
    build_academic_experiment_design_report,
    render_academic_experiment_design_report,
)


DEFAULT_JSON_OUTPUT = ROOT / "experiments" / "generated" / "academic_experiment_design_validation_v1.json"
DEFAULT_MD_OUTPUT = ROOT / "experiments" / "generated" / "academic_experiment_design_validation_v1.md"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-output", default=str(DEFAULT_JSON_OUTPUT))
    parser.add_argument("--md-output", default=str(DEFAULT_MD_OUTPUT))
    args = parser.parse_args()

    report = build_academic_experiment_design_report()
    json_path = Path(args.json_output)
    md_path = Path(args.md_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_academic_experiment_design_report(report), encoding="utf-8")

    print(
        json.dumps(
            {
                "status": report.get("status"),
                "json": json_path.as_posix(),
                "markdown": md_path.as_posix(),
                "errors": report.get("errors") or [],
                "warnings": report.get("warnings") or [],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
