"""Export Day 7 first-round review and stage acceptance artifacts.

This command is offline-only: it reads the existing Day 7 dataset, gates,
pilot/dev evidence, and cost forecast.  It does not call an LLM.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.day7_acceptance_review import (  # noqa: E402
    DEFAULT_BENCHMARK_MANIFEST_PATH,
    DEFAULT_DEV_RESULTS_ROOT,
    DEFAULT_DOCS_ACCEPTANCE_REPORT_PATH,
    DEFAULT_FEASIBILITY_REPORT_PATH,
    DEFAULT_PILOT_RESULTS_ROOT,
    DEFAULT_QUOTA_REPORT_PATH,
    DEFAULT_TEST_DRAFT_PATH,
    default_acceptance_output_dir,
    write_day7_acceptance_pack,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-draft", type=Path, default=DEFAULT_TEST_DRAFT_PATH)
    parser.add_argument("--quota-report", type=Path, default=DEFAULT_QUOTA_REPORT_PATH)
    parser.add_argument("--feasibility-report", type=Path, default=DEFAULT_FEASIBILITY_REPORT_PATH)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK_MANIFEST_PATH)
    parser.add_argument(
        "--pilot-run-dir",
        type=Path,
        default=None,
        help=f"Saved Day7 pilot run. Defaults to the latest run under {DEFAULT_PILOT_RESULTS_ROOT}.",
    )
    parser.add_argument(
        "--dev-run-dir",
        type=Path,
        default=None,
        help=f"Saved Day7 dev run. Defaults to the latest run under {DEFAULT_DEV_RESULTS_ROOT}.",
    )
    parser.add_argument(
        "--annotation-review",
        type=Path,
        default=None,
        help=(
            "Optional human-completed review JSON/CSV. If omitted, the exporter writes a "
            "machine-prefilled review sheet and keeps Day7 acceptance blocked."
        ),
    )
    parser.add_argument(
        "--freeze-tag",
        type=str,
        default=None,
        help="Optional Git tag name that proves the accepted Day7 evidence has been frozen.",
    )
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory. Defaults to experiments/results/day7_acceptance/<run_id>.",
    )
    parser.add_argument(
        "--docs-report",
        type=Path,
        default=DEFAULT_DOCS_ACCEPTANCE_REPORT_PATH,
        help="Optional docs copy of Day7_acceptance_report.md.",
    )
    parser.add_argument(
        "--no-docs-report",
        action="store_true",
        help="Do not write a docs copy of the acceptance report.",
    )
    parser.add_argument("--expected-cases", type=int, default=100)
    parser.add_argument("--expected-turns", type=int, default=130)
    parser.add_argument("--expected-scenarios", type=int, default=30)
    parser.add_argument(
        "--required-methods",
        type=str,
        default=None,
        help="Comma-separated method list. Defaults to the four formal methods.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero unless Day7 stage acceptance passes.",
    )
    args = parser.parse_args()

    output_dir = args.output_dir or default_acceptance_output_dir(run_id=args.run_id)
    payload = write_day7_acceptance_pack(
        output_dir=output_dir,
        docs_report_path=None if args.no_docs_report else args.docs_report,
        test_draft_path=args.test_draft,
        quota_report_path=args.quota_report,
        feasibility_report_path=args.feasibility_report,
        benchmark_manifest_path=args.benchmark,
        annotation_review_path=args.annotation_review,
        pilot_run_dir=args.pilot_run_dir,
        dev_run_dir=args.dev_run_dir,
        expected_case_count=args.expected_cases,
        expected_turn_count=args.expected_turns,
        expected_scenario_case_count=args.expected_scenarios,
        required_methods=_parse_methods(args.required_methods),
        run_id=args.run_id,
        freeze_tag_name=args.freeze_tag,
    )
    response = {
        "status": payload["status"],
        "acceptance_status": payload["acceptance_status"],
        "ready_for_day8": payload["ready_for_day8"],
        "prepared_for_manual_review": payload["prepared_for_manual_review"],
        "paper_claims_allowed": payload["paper_claims_allowed"],
        "failed_checks": payload["failed_checks"],
        "run_id": payload["run_id"],
        "output_dir": payload["output_dir"],
        "docs_report": payload["docs_report"],
        "artifacts": payload["artifacts"],
    }
    print(json.dumps(response, ensure_ascii=False, indent=2))
    if args.strict and payload["acceptance_status"] != "accepted_for_day8":
        return 1
    return 0


def _parse_methods(value: Optional[str]) -> Optional[List[str]]:
    if value is None:
        return None
    methods = [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]
    return methods or None


if __name__ == "__main__":
    raise SystemExit(main())
