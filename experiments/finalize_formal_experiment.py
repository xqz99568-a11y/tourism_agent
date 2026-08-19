"""Finalize a saved formal experiment run with a paper-readiness gate."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.formal_experiment_gate import write_formal_experiment_gate
from app.core.paper_draft_pack import write_paper_draft_pack
from app.core.paper_result_pack import write_paper_result_pack
from app.core.paper_submission_pack import write_paper_submission_pack


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        type=Path,
        required=True,
        help="Formal run directory containing benchmark_results.json.",
    )
    parser.add_argument(
        "--min-cases",
        type=int,
        default=100,
        help="Minimum independent cases required for paper claims.",
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
        help="Exit non-zero when the formal gate does not pass.",
    )
    args = parser.parse_args()

    required_methods = _parse_methods(args.required_methods)
    payload = write_formal_experiment_gate(
        args.run_dir,
        min_cases=args.min_cases,
        required_methods=required_methods,
        allow_mock_llm=args.allow_mock_llm,
    )
    paper_pack = write_paper_result_pack(
        args.run_dir,
        profile="formal",
        min_cases=args.min_cases,
        required_methods=required_methods,
        allow_mock_llm=args.allow_mock_llm,
    )
    draft_pack = write_paper_draft_pack(
        args.run_dir,
        profile="formal",
        min_cases=args.min_cases,
        required_methods=required_methods,
        allow_mock_llm=args.allow_mock_llm,
    )
    submission_pack = write_paper_submission_pack(
        args.run_dir,
        min_cases=args.min_cases,
        required_methods=required_methods,
        allow_mock_llm=args.allow_mock_llm,
    )
    response = {
        "status": payload["status"],
        "gate_status": payload["gate_status"],
        "paper_claims_allowed": payload["paper_claims_allowed"],
        "gate": payload["json"],
        "report": payload["markdown"],
        "paper_analysis_json": payload["paper_analysis_json"],
        "paper_analysis_md": payload["paper_analysis_md"],
        "paper_result_pack_json": paper_pack["json"],
        "paper_result_pack_md": paper_pack["markdown"],
        "paper_result_pack_claims_allowed": paper_pack["paper_claims_allowed"],
        "paper_draft_pack_json": draft_pack["json"],
        "paper_draft_md": draft_pack["markdown"],
        "paper_draft_claims_allowed": draft_pack["paper_claims_allowed"],
        "paper_submission_pack_json": submission_pack["json"],
        "paper_submission_checklist_md": submission_pack["markdown"],
        "paper_submission_status": submission_pack["submission_status"],
        "paper_submission_claims_allowed": submission_pack["paper_claims_allowed"],
        "failed_checks": payload["gate"]["failed_checks"],
    }
    print(json.dumps(response, ensure_ascii=False, indent=2))
    if args.strict and (
        payload["gate_status"] != "passed"
        or submission_pack["submission_status"] != "submission_ready"
    ):
        return 1
    return 0


def _parse_methods(value: Optional[str]) -> Optional[List[str]]:
    if value is None:
        return None
    methods = [item.strip() for item in str(value).replace(";", ",").split(",") if item.strip()]
    return methods or None


if __name__ == "__main__":
    raise SystemExit(main())
