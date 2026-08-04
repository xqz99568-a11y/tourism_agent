"""Export the final Day7 delivery handoff report for a saved formal run."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.day7_delivery_pack import write_day7_delivery_pack


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
        help="Where to write day7_delivery_pack.json/report. Defaults to --run-dir.",
    )
    parser.add_argument(
        "--min-cases",
        type=int,
        default=100,
        help="Minimum independent cases required for paper-level delivery.",
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
        help="Exit non-zero when Day7 delivery is not ready.",
    )
    args = parser.parse_args()

    payload = write_day7_delivery_pack(
        args.run_dir,
        output_dir=args.output_dir,
        min_cases=args.min_cases,
        required_methods=_parse_methods(args.required_methods),
        allow_mock_llm=args.allow_mock_llm,
    )
    response = {
        "status": payload["status"],
        "delivery_status": payload["delivery_status"],
        "paper_claims_allowed": payload["paper_claims_allowed"],
        "failed_checks": payload["failed_checks"],
        "json": payload["json"],
        "markdown": payload["markdown"],
    }
    print(json.dumps(response, ensure_ascii=False, indent=2))
    if args.strict and payload["delivery_status"] != "delivery_ready":
        return 1
    return 0


def _parse_methods(value: Optional[str]) -> Optional[List[str]]:
    if value is None:
        return None
    methods = [item.strip() for item in str(value).replace(";", ",").split(",") if item.strip()]
    return methods or None


if __name__ == "__main__":
    raise SystemExit(main())
