"""Export the final paper submission archive package for a saved formal run."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.paper_submission_pack import write_paper_submission_pack


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        type=Path,
        required=True,
        help="Formal experiment run directory containing saved Day7 artifacts.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Where to write paper_submission_pack.json/checklist. Defaults to --run-dir.",
    )
    parser.add_argument(
        "--min-cases",
        type=int,
        default=100,
        help="Minimum independent cases required for submission-ready evidence.",
    )
    parser.add_argument(
        "--required-methods",
        type=str,
        default=None,
        help="Comma-separated required method list. Defaults to all four formal methods.",
    )
    parser.add_argument(
        "--allow-mock-llm",
        action="store_true",
        help="Permit mock LLM evidence. Intended only for local/debug runs.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when the archive is not submission-ready.",
    )
    args = parser.parse_args()

    payload = write_paper_submission_pack(
        args.run_dir,
        output_dir=args.output_dir,
        min_cases=args.min_cases,
        required_methods=_parse_methods(args.required_methods),
        allow_mock_llm=args.allow_mock_llm,
    )
    response = {
        "status": payload["status"],
        "submission_status": payload["submission_status"],
        "paper_claims_allowed": payload["paper_claims_allowed"],
        "json": payload["json"],
        "markdown": payload["markdown"],
        "failed_checks": payload["failed_checks"],
    }
    print(json.dumps(response, ensure_ascii=False, indent=2))
    if args.strict and payload["paper_claims_allowed"] is not True:
        return 1
    return 0


def _parse_methods(value: Optional[str]) -> Optional[List[str]]:
    if value is None:
        return None
    methods = [item.strip() for item in str(value).replace(";", ",").split(",") if item.strip()]
    return methods or None


if __name__ == "__main__":
    raise SystemExit(main())
