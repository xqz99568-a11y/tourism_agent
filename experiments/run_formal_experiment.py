"""Run the paper-level four-method benchmark with a formal preflight gate."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.experiment_runner import ExperimentRunner
from app.core.formal_experiment_gate import write_formal_experiment_gate
from app.core.formal_experiment_preflight import (
    DEFAULT_FORMAL_METHOD_ORDER_SEED,
    assert_formal_preflight_passed,
    build_formal_preflight_report,
    resolve_run_output_dir,
    write_preflight_report,
)
from app.core.paper_draft_pack import write_paper_draft_pack
from app.core.paper_result_pack import write_paper_result_pack
from app.core.paper_submission_pack import write_paper_submission_pack


DEFAULT_BENCHMARK_PATH = ROOT / "experiments" / "benchmark.json"
DEFAULT_OUTPUT_ROOT = ROOT / "experiments" / "results" / "formal_runs"
PREFLIGHT_REPORT_NAME = "formal_preflight_report.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--expected-cases", type=int, default=None)
    parser.add_argument("--method-order-seed", type=int, default=DEFAULT_FORMAL_METHOD_ORDER_SEED)
    parser.add_argument("--model-config-name", type=str, default="formal-four-method")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Only print the preflight report; do not create result files or call an LLM.",
    )
    parser.add_argument(
        "--skip-llm-config-check",
        action="store_true",
        help="Allow dataset/environment preflight without configured LLM credentials.",
    )
    parser.add_argument(
        "--strict-paper-readiness",
        action="store_true",
        help="Exit non-zero if the final formal evidence gate does not pass.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Resume an interrupted formal run from benchmark_results.checkpoint.json "
            "after validating the saved resume contract."
        ),
    )
    args = parser.parse_args()

    run_id = args.run_id or f"formal_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    run_output_dir = resolve_run_output_dir(args.output_dir, run_id)
    _apply_formal_env_defaults()

    report = build_formal_preflight_report(
        benchmark_path=args.benchmark,
        output_dir=args.output_dir,
        run_id=run_id,
        methods=ExperimentRunner.METHODS,
        repeats=args.repeats,
        method_order_seed=args.method_order_seed,
        model_config_name=args.model_config_name,
        expected_case_count=args.expected_cases,
        require_llm_config=not args.skip_llm_config_check,
        strict_formal=True,
        resume=args.resume,
    )
    if args.preflight_only:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "passed" else 2

    assert_formal_preflight_passed(report)
    run_output_dir.mkdir(parents=True, exist_ok=True)
    runner = ExperimentRunner(
        trace_dir=run_output_dir / "traces",
        output_dir=run_output_dir,
        repeats=args.repeats,
        run_id=run_id,
        model_config_name=args.model_config_name,
        method_order_seed=args.method_order_seed,
    )
    preflight_path = write_preflight_report(
        report,
        run_output_dir / PREFLIGHT_REPORT_NAME,
    )
    results = runner.run_benchmark(
        args.benchmark,
        methods=ExperimentRunner.METHODS,
        repeats=args.repeats,
        run_id=run_id,
        model_config_name=args.model_config_name,
        resume=args.resume,
    )
    formal_gate = write_formal_experiment_gate(
        run_output_dir,
        min_cases=args.expected_cases,
    )
    paper_result_pack = write_paper_result_pack(
        run_output_dir,
        profile="formal",
        min_cases=args.expected_cases,
    )
    paper_draft_pack = write_paper_draft_pack(
        run_output_dir,
        profile="formal",
        min_cases=args.expected_cases,
    )
    paper_submission_pack = write_paper_submission_pack(
        run_output_dir,
        min_cases=args.expected_cases,
    )
    payload = _build_payload(
        run_id=run_id,
        run_output_dir=run_output_dir,
        preflight_path=preflight_path,
        result_count=len(results),
        expected_count=int(report["run"]["expected_raw_run_count"]),
        formal_gate=formal_gate,
        paper_result_pack=paper_result_pack,
        paper_draft_pack=paper_draft_pack,
        paper_submission_pack=paper_submission_pack,
        day8_delivery_pack=report.get("day8_delivery_pack"),
        resume_report=report.get("resume"),
    )
    _validate_payload_files(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.strict_paper_readiness and (
        formal_gate["gate_status"] != "passed"
        or paper_submission_pack["submission_status"] != "submission_ready"
    ):
        return 1
    return 0


def _apply_formal_env_defaults() -> None:
    defaults = {
        "EXPERIMENT_STRICT_MODE": "true",
        "EXPERIMENT_DISABLE_CACHE": "true",
        "TRACE_SAVE_USER_MESSAGE": "false",
        "LLM_TEMPERATURE": "0",
        "LLM_MAX_TOKENS": "4096",
        "LLM_TIMEOUT": "60",
        "LLM_RETRY_MAX_ATTEMPTS": "3",
        "LLM_REASONING_EFFORT": "minimal",
        "EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER": "true",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def _build_payload(
    *,
    run_id: str,
    run_output_dir: Path,
    preflight_path: Path,
    result_count: int,
    expected_count: int,
    formal_gate: Dict[str, Any] | None = None,
    paper_result_pack: Dict[str, Any] | None = None,
    paper_draft_pack: Dict[str, Any] | None = None,
    paper_submission_pack: Dict[str, Any] | None = None,
    day8_delivery_pack: Dict[str, Any] | None = None,
    resume_report: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    payload = {
        "status": "completed",
        "run_id": run_id,
        "output_dir": run_output_dir.as_posix(),
        "result_count": result_count,
        "expected_count": expected_count,
        "preflight": preflight_path.as_posix(),
        "csv": (run_output_dir / "benchmark_results.csv").as_posix(),
        "json": (run_output_dir / "benchmark_results.json").as_posix(),
        "summary": (run_output_dir / "evaluation_summary.json").as_posix(),
        "paper_tables": (run_output_dir / "paper_tables.md").as_posix(),
        "manifest": (run_output_dir / "experiment_manifest.json").as_posix(),
        "resume_state": (run_output_dir / "benchmark_resume_state.json").as_posix(),
        "checkpoint_json": (run_output_dir / "benchmark_results.checkpoint.json").as_posix(),
        "checkpoint_csv": (run_output_dir / "benchmark_results.checkpoint.csv").as_posix(),
        "traces": (run_output_dir / "traces").as_posix(),
    }
    if formal_gate:
        payload.update(
            {
                "paper_analysis_json": formal_gate["paper_analysis_json"],
                "paper_analysis_md": formal_gate["paper_analysis_md"],
                "paper_readiness_status": formal_gate["paper_readiness_status"],
                "formal_gate": formal_gate["json"],
                "formal_report": formal_gate["markdown"],
                "formal_gate_status": formal_gate["gate_status"],
                "paper_claims_allowed": formal_gate["paper_claims_allowed"],
            }
        )
    if paper_result_pack:
        payload.update(
            {
                "paper_result_pack_json": paper_result_pack["json"],
                "paper_result_pack_md": paper_result_pack["markdown"],
                "paper_result_pack_claims_allowed": paper_result_pack["paper_claims_allowed"],
            }
        )
    if paper_draft_pack:
        payload.update(
            {
                "paper_draft_pack_json": paper_draft_pack["json"],
                "paper_draft_md": paper_draft_pack["markdown"],
                "paper_draft_claims_allowed": paper_draft_pack["paper_claims_allowed"],
            }
        )
    if paper_submission_pack:
        payload.update(
            {
                "paper_submission_pack_json": paper_submission_pack["json"],
                "paper_submission_checklist_md": paper_submission_pack["markdown"],
                "paper_submission_status": paper_submission_pack["submission_status"],
                "paper_submission_claims_allowed": paper_submission_pack["paper_claims_allowed"],
            }
        )
    if day8_delivery_pack:
        payload.update(
            {
                "day8_delivery_pack_json": day8_delivery_pack.get("path"),
                "day8_delivery_status": day8_delivery_pack.get("status"),
                "day8_delivery_ready_for_formal_experiment": day8_delivery_pack.get(
                    "ready_for_formal_experiment"
                ),
                "day8_delivery_failed_checks": day8_delivery_pack.get("failed_checks") or [],
            }
        )
    if resume_report:
        payload.update(
            {
                "resume_requested": resume_report.get("requested"),
                "resume_status": resume_report.get("status"),
                "resume_completed_result_count": resume_report.get(
                    "completed_result_count"
                ),
                "resume_completed_unique_key_count": resume_report.get(
                    "completed_unique_key_count"
                ),
            }
        )
    return payload


def _validate_payload_files(payload: Dict[str, Any]) -> None:
    for key in (
        "preflight",
        "csv",
        "json",
        "summary",
        "paper_tables",
        "manifest",
        "resume_state",
        "checkpoint_json",
        "checkpoint_csv",
        "paper_analysis_json",
        "paper_analysis_md",
        "formal_gate",
        "formal_report",
        "paper_result_pack_json",
        "paper_result_pack_md",
        "paper_draft_pack_json",
        "paper_draft_md",
        "paper_submission_pack_json",
        "paper_submission_checklist_md",
        "day8_delivery_pack_json",
    ):
        if key not in payload:
            continue
        path = Path(str(payload[key]))
        if not path.exists():
            raise RuntimeError(f"formal experiment missing output file: {key}")
    if payload["result_count"] != payload["expected_count"]:
        raise RuntimeError(
            f"formal experiment result count mismatch: "
            f"{payload['result_count']} != {payload['expected_count']}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
