"""Run CTP30-v2 sealed multi-turn validation for M2/M3 only.

CTP30-v2 is a supplementary post-freeze validation set.  It exists to validate
true two-turn state transfer under the paper's M2/M3 comparison, not to replace
the CTP100 formal experiment and not to tune prompts, tools, agents, or
scheduling rules after observing its result.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.core.experiment_method_contract import method_fairness_contract_hash
from app.core.experiment_runner import ExperimentRunner
from app.core.final_artifact_index import write_final_artifact_index
from app.core.fixed_data import CANONICAL_JSON_SHA256_STRATEGY, canonical_json_sha256
from app.core.formal_experiment_gate import (
    _api_failure_timeout_summary,
    _failure_classification_summary,
    _load_traces,
)
from app.core.formal_experiment_preflight import (
    DEFAULT_FORMAL_METHOD_ORDER_SEED,
    load_benchmark_document,
)
from experiments.run_ctp30_sealed_validation import (
    CTP100_V6_FROZEN_COMMIT,
    DEFAULT_OUTPUT_ROOT,
    _git_commit,
    _git_working_tree_clean,
    _protected_core_hash_audit,
    _raise_preflight_error,
)


CTP30_MT_V2_REPORT_SCHEMA_VERSION = "ctp30-multiturn-v2-sealed-validation-report-v1"
CTP30_MT_V2_PREFLIGHT_SCHEMA_VERSION = (
    "ctp30-multiturn-v2-sealed-validation-preflight-v1"
)
CTP30_MT_V2_DATASET_ID = "ctp30_multiturn_validation_v2"
CTP30_MT_V2_DATASET_ROLE = (
    "sealed_multiturn_validation_after_ctp100_v6_and_ctp30_v1"
)
CTP30_MT_V2_SPLIT = "sealed_multiturn_validation"
CTP30_MT_V2_METHODS = ("fixed_multi_agent", "adaptive_multi_agent")
CTP30_MT_V2_EXPECTED_CASES = 30
CTP30_MT_V2_EXPECTED_TURNS = 60
CTP30_MT_V2_PRIMARY_TURN_ID = "t2"
CTP30_MT_V2_EXPECTED_RESULTS = (
    CTP30_MT_V2_EXPECTED_TURNS * len(CTP30_MT_V2_METHODS)
)
CTP30_MT_V2_EXPECTED_PRIMARY_RESULTS = (
    CTP30_MT_V2_EXPECTED_CASES * len(CTP30_MT_V2_METHODS)
)
DEFAULT_BENCHMARK_PATH = ROOT / "experiments" / "ctp30_multiturn_validation_v2.json"
DEFAULT_FREEZE_MANIFEST_PATH = (
    ROOT / "experiments" / "generated" / "ctp30_multiturn_v2_freeze_manifest.json"
)
DEFAULT_MODEL_CONFIG_NAME = "ctp30-multiturn-v2-sealed-validation"
PREFLIGHT_NAME = "multiturn_sealed_validation_preflight.json"
MANIFEST_NAME = "multiturn_sealed_validation_manifest.json"
GATE_NAME = "multiturn_sealed_validation_gate.json"
REPORT_NAME = "multiturn_sealed_validation_report.md"

_PREVIOUS_STATE_GOLD_FIELDS = {
    "accepted_agent_sets",
    "accepted_tool_sets",
    "changed_slots",
    "current_slots",
    "evaluation",
    "evaluation_rules",
    "expected",
    "expected_goal",
    "forbidden_tools",
    "gold",
    "hard_constraints",
    "metrics",
    "preserved_slots",
    "previous_slots",
    "required_tools",
    "standard_answer",
    "task_type",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict-sealed-readiness", action="store_true")
    parser.add_argument("--base-url", type=str, default=None)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--hard-timeout-seconds", type=int, default=900)
    parser.add_argument("--retry-max-attempts", type=int, default=3)
    parser.add_argument("--reasoning-effort", type=str, default="minimal")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--method-order-seed", type=int, default=DEFAULT_FORMAL_METHOD_ORDER_SEED)
    parser.add_argument("--model-config-name", type=str, default=DEFAULT_MODEL_CONFIG_NAME)
    parser.add_argument("--freeze-manifest", type=Path, default=DEFAULT_FREEZE_MANIFEST_PATH)
    parser.add_argument("--frozen-ctp100-commit", type=str, default=CTP100_V6_FROZEN_COMMIT)
    parser.add_argument(
        "--require-clean-git",
        action="store_true",
        help="Require a clean working tree before the sealed validation run starts.",
    )
    args = parser.parse_args()

    run_id = args.run_id or (
        f"ctp30_multiturn_v2_sealed_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    )
    run_dir = _resolve_run_output_dir(args.output_dir, run_id)
    runtime = _runtime_config(args)
    preflight = build_multiturn_v2_preflight(
        benchmark_path=args.benchmark,
        output_dir=args.output_dir,
        run_id=run_id,
        runtime_config=runtime,
        freeze_manifest_path=args.freeze_manifest,
        resume=args.resume,
        require_clean_git=args.require_clean_git,
        frozen_ctp100_commit=args.frozen_ctp100_commit,
    )
    if args.preflight_only:
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return 0 if preflight["status"] == "passed" else 2
    if preflight["status"] != "passed":
        _raise_preflight_error(preflight)

    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / PREFLIGHT_NAME, preflight)
    benchmark_document, _cases = load_benchmark_document(args.benchmark)

    if args.dry_run:
        report = build_multiturn_v2_report(
            run_id=run_id,
            run_dir=run_dir,
            benchmark_path=args.benchmark,
            benchmark_document=benchmark_document,
            runtime_config=runtime,
            preflight=preflight,
            results=[],
            elapsed_seconds=0.0,
            skipped_reason="dry_run",
        )
        _write_multiturn_v2_report(run_dir, report)
        print(json.dumps(_payload(run_id, run_dir, report), ensure_ascii=False, indent=2))
        return 0

    runner = ExperimentRunner(
        trace_dir=run_dir / "traces",
        output_dir=run_dir,
        repeats=1,
        run_id=run_id,
        model_config_name=args.model_config_name,
        method_order_seed=args.method_order_seed,
    )
    started = time.perf_counter()
    with _temporary_env(_sealed_env_values(runtime)):
        results = runner.run_benchmark(
            args.benchmark,
            methods=CTP30_MT_V2_METHODS,
            repeats=1,
            run_id=run_id,
            model_config_name=args.model_config_name,
            csv_path=run_dir / "benchmark_results.csv",
            json_path=run_dir / "benchmark_results.json",
            summary_path=run_dir / "evaluation_summary.json",
            paper_tables_path=run_dir / "paper_tables.md",
            manifest_path=run_dir / MANIFEST_NAME,
            resume=args.resume,
        )
    elapsed = time.perf_counter() - started
    report = build_multiturn_v2_report(
        run_id=run_id,
        run_dir=run_dir,
        benchmark_path=args.benchmark,
        benchmark_document=benchmark_document,
        runtime_config=runtime,
        preflight=preflight,
        results=results,
        elapsed_seconds=elapsed,
    )
    _attach_multiturn_v2_metadata_to_manifest(
        run_dir,
        report=report,
        preflight=preflight,
        frozen_ctp100_commit=args.frozen_ctp100_commit,
    )
    _write_multiturn_v2_report(run_dir, report)
    final_index = write_final_artifact_index(
        run_dir,
        artifact_files=_multiturn_v2_artifact_files(args.benchmark),
        manifest_name=MANIFEST_NAME,
    )
    payload = _payload(run_id, run_dir, report, final_index=final_index)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.strict_sealed_readiness and (
        report["status"] != "passed" or final_index["index_status"] != "passed"
    ):
        return 1
    return 0


def build_multiturn_v2_preflight(
    *,
    benchmark_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    runtime_config: Mapping[str, Any],
    freeze_manifest_path: str | Path = DEFAULT_FREEZE_MANIFEST_PATH,
    resume: bool = False,
    require_clean_git: bool = False,
    frozen_ctp100_commit: str = CTP100_V6_FROZEN_COMMIT,
) -> Dict[str, Any]:
    """Build a read-only CTP30-v2 sealed multi-turn preflight report."""
    benchmark_file = Path(benchmark_path)
    freeze_manifest_file = Path(freeze_manifest_path)
    run_dir = _resolve_run_output_dir(output_dir, run_id)
    errors: List[str] = []
    warnings: List[str] = []
    document: Any = None
    cases: List[Dict[str, Any]] = []

    if not benchmark_file.exists():
        errors.append(f"benchmark file does not exist: {benchmark_file}")
    else:
        try:
            document, cases = load_benchmark_document(benchmark_file)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"benchmark file is invalid: {exc}")

    freeze_manifest = _read_json_object(freeze_manifest_file)
    output_dir_has_contents = run_dir.exists() and any(run_dir.iterdir())
    if output_dir_has_contents and not resume:
        errors.append(f"output directory is not empty: {run_dir}")
    if not runtime_config.get("api_configured"):
        errors.append("LLM API config is required for CTP30-v2 sealed validation")
    if require_clean_git and not _git_working_tree_clean():
        errors.append("working tree must be clean before CTP30-v2 sealed validation")

    protected_audit = _protected_core_hash_audit(frozen_ctp100_commit)
    if protected_audit["status"] != "passed":
        errors.append("protected core files changed from frozen CTP100 v6 commit")

    document_mapping = document if isinstance(document, Mapping) else {}
    dataset_sha256 = (
        canonical_json_sha256(document) if document is not None else None
    )
    freeze_dataset = (
        freeze_manifest.get("frozen_dataset")
        if isinstance(freeze_manifest.get("frozen_dataset"), Mapping)
        else {}
    )
    shape = _dataset_shape(cases)
    primary_units = _expected_turn_units(
        cases,
        primary_only=True,
    )
    checks = {
        "benchmark_exists": benchmark_file.exists(),
        "freeze_manifest_exists": freeze_manifest_file.exists(),
        "freeze_manifest_status_passed": freeze_manifest.get("status") == "passed",
        "freeze_manifest_matches_dataset": (
            freeze_dataset.get("sha256") == dataset_sha256
            and freeze_dataset.get("path") == "experiments/ctp30_multiturn_validation_v2.json"
        ),
        "dataset_id_matches": (
            document_mapping.get("dataset_id") == CTP30_MT_V2_DATASET_ID
        ),
        "dataset_role_matches": (
            document_mapping.get("dataset_role") == CTP30_MT_V2_DATASET_ROLE
        ),
        "split_matches": document_mapping.get("split") == CTP30_MT_V2_SPLIT,
        "case_count_30": len(cases) == CTP30_MT_V2_EXPECTED_CASES,
        "turn_count_60": shape["turn_count"] == CTP30_MT_V2_EXPECTED_TURNS,
        "every_case_two_turns": shape["bad_turn_count_case_count"] == 0,
        "turn_ids_are_t1_t2": shape["bad_turn_id_case_count"] == 0,
        "every_case_primary_turn_t2": shape["bad_primary_turn_case_count"] == 0,
        "top_level_user_input_absent": shape["top_level_user_input_case_count"] == 0,
        "primary_result_count_expected_60": (
            len(primary_units) * len(CTP30_MT_V2_METHODS)
            == CTP30_MT_V2_EXPECTED_PRIMARY_RESULTS
        ),
        "expected_raw_result_count_120": (
            shape["turn_count"] * len(CTP30_MT_V2_METHODS)
            == CTP30_MT_V2_EXPECTED_RESULTS
        ),
        "freeze_policy_methods_locked_to_m2_m3": tuple(
            (document_mapping.get("freeze_policy") or {}).get("allowed_methods") or ()
        )
        == CTP30_MT_V2_METHODS,
        "freeze_policy_previous_state_runtime_only": (
            (document_mapping.get("freeze_policy") or {}).get(
                "previous_state_injection_allowed"
            )
            is False
        ),
        "freeze_policy_gold_not_visible": (
            (document_mapping.get("freeze_policy") or {}).get("gold_visible_to_generation")
            is False
        ),
        "manual_review_confirmed": (
            (document_mapping.get("manual_review") or {}).get("status") == "confirmed"
            and (document_mapping.get("annotation_policy") or {}).get(
                "human_review_completed"
            )
            is True
        ),
        "methods_are_m2_m3_only": tuple(runtime_config.get("methods") or ())
        == CTP30_MT_V2_METHODS,
        "output_dir_empty_or_resume": not output_dir_has_contents or bool(resume),
        "api_configured": bool(runtime_config.get("api_configured")),
        "protected_core_unchanged_from_ctp100_v6": protected_audit["status"] == "passed",
        "working_tree_clean_if_required": (not require_clean_git) or _git_working_tree_clean(),
    }
    failed_checks = [key for key, passed in checks.items() if not passed]
    errors.extend(key for key in failed_checks if key not in set(errors))
    return {
        "schema_version": CTP30_MT_V2_PREFLIGHT_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "benchmark": {
            "path": benchmark_file.as_posix(),
            "dataset_id": document_mapping.get("dataset_id"),
            "dataset_version": document_mapping.get("dataset_version"),
            "dataset_role": document_mapping.get("dataset_role"),
            "split": document_mapping.get("split"),
            "dataset_sha256": dataset_sha256,
            "hash_strategy": (
                CANONICAL_JSON_SHA256_STRATEGY if document is not None else None
            ),
            "case_count": len(cases),
            "turn_count": shape["turn_count"],
            "primary_turn_count": len(primary_units),
            "expected_raw_result_count": CTP30_MT_V2_EXPECTED_RESULTS,
            "expected_primary_result_count": CTP30_MT_V2_EXPECTED_PRIMARY_RESULTS,
            "shape": shape,
        },
        "freeze_manifest": {
            "path": freeze_manifest_file.as_posix(),
            "status": freeze_manifest.get("status"),
            "dataset_sha256": freeze_dataset.get("sha256"),
            "human_review": freeze_manifest.get("human_review") or {},
            "quality_gate": freeze_manifest.get("quality_gate") or {},
        },
        "run": {
            "run_id": run_id,
            "output_dir": run_dir.as_posix(),
            "methods": list(CTP30_MT_V2_METHODS),
            "method_count": len(CTP30_MT_V2_METHODS),
            "repeats": 1,
            "method_order_seed": runtime_config.get("method_order_seed"),
            "expected_raw_run_count": CTP30_MT_V2_EXPECTED_RESULTS,
            "expected_primary_result_count": CTP30_MT_V2_EXPECTED_PRIMARY_RESULTS,
            "resume_requested": bool(resume),
        },
        "runtime_config": dict(runtime_config),
        "method_fairness_contract": {
            "methods": list(CTP30_MT_V2_METHODS),
            "contract_sha256": method_fairness_contract_hash(CTP30_MT_V2_METHODS),
        },
        "git": {
            "current_commit": _git_commit(),
            "working_tree_clean": _git_working_tree_clean(),
            "require_clean_git": bool(require_clean_git),
            "frozen_ctp100_v6_commit": frozen_ctp100_commit,
        },
        "protected_core_hash_audit": protected_audit,
        "checks": checks,
        "failed_checks": failed_checks,
        "policy": {
            "sealed_validation_no_tuning_after_run": True,
            "methods_locked_to_m2_m3": True,
            "does_not_replace_ctp100_main_experiment": True,
            "primary_evaluation_turn": CTP30_MT_V2_PRIMARY_TURN_ID,
            "turn2_previous_state_source": "same_method_turn1_runtime_output_only",
            "gold_visible_to_generation": False,
            "preflight_consumes_api": False,
        },
    }


def build_multiturn_v2_report(
    *,
    run_id: str,
    run_dir: Path,
    benchmark_path: str | Path,
    benchmark_document: Mapping[str, Any],
    runtime_config: Mapping[str, Any],
    preflight: Mapping[str, Any],
    results: List[Dict[str, Any]],
    elapsed_seconds: float,
    skipped_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the CTP30-v2 sealed multi-turn evidence report."""
    summary = _read_json_object(run_dir / "evaluation_summary.json")
    traces = _load_traces(run_dir, results)
    failure_classification = _failure_classification_summary(run_dir, results)
    api_failure_summary = _api_failure_timeout_summary(traces)
    cases = _cases_from_document(benchmark_document)
    all_units = _expected_turn_units(cases, primary_only=False)
    primary_units = _expected_turn_units(cases, primary_only=True)
    method_counts = Counter(str(result.get("method") or "") for result in results)
    status_counts = Counter(str(result.get("status") or "unknown") for result in results)
    primary_results = _primary_turn_results(results)
    all_grid = _turn_method_grid(
        results,
        expected_units=all_units,
        expected_methods=CTP30_MT_V2_METHODS,
    )
    primary_grid = _turn_method_grid(
        primary_results,
        expected_units=primary_units,
        expected_methods=CTP30_MT_V2_METHODS,
    )
    paired_stsr = _paired_stsr(summary)
    previous_state_audit = _previous_state_audit(results)
    worker_audit = _worker_previous_state_audit(
        run_dir,
        results,
        previous_slots_required_by_case=_previous_slots_required_by_case(
            benchmark_document
        ),
    )
    trace_audit = _trace_audit(run_dir, traces, result_count=len(results))
    api_clean = _api_clean_pair_summary(
        results,
        failure_classification=failure_classification,
        expected_case_ids=[unit["case_id"] for unit in primary_units],
    )
    method_comparison = _method_comparison_summary(
        primary_results,
        summary=summary,
    )

    checks = {
        "not_skipped": skipped_reason is None,
        "preflight_passed": preflight.get("status") == "passed",
        "expected_raw_result_count_120": len(results) == CTP30_MT_V2_EXPECTED_RESULTS,
        "expected_primary_result_count_60": (
            len(primary_results) == CTP30_MT_V2_EXPECTED_PRIMARY_RESULTS
        ),
        "m2_m3_methods_only": set(method_counts) <= set(CTP30_MT_V2_METHODS),
        "turn_method_grid_complete": all_grid["missing_count"] == 0
        and all_grid["duplicate_count"] == 0
        and all_grid["unexpected_count"] == 0,
        "primary_turn_method_grid_complete": primary_grid["missing_count"] == 0
        and primary_grid["duplicate_count"] == 0
        and primary_grid["unexpected_count"] == 0,
        "paired_m3_m2_primary_present": (
            paired_stsr.get("pair_count") == CTP30_MT_V2_EXPECTED_CASES
        ),
        "turn2_previous_state_present": (
            previous_state_audit["missing_previous_state_count"] == 0
        ),
        "turn2_previous_state_method_local": (
            previous_state_audit["wrong_method_count"] == 0
        ),
        "turn2_previous_state_prior_turn": (
            previous_state_audit["wrong_prior_turn_count"] == 0
        ),
        "turn2_previous_state_no_evaluation_or_metrics": (
            previous_state_audit["previous_state_has_evaluation_count"] == 0
            and previous_state_audit["previous_state_has_metrics_count"] == 0
        ),
        "turn2_visible_previous_state_no_evaluation_leak": (
            previous_state_audit["visible_previous_state_leak_count"] == 0
        ),
        "turn2_previous_slots_auditable": (
            worker_audit["missing_previous_slots_count"] == 0
        ),
        "worker_request_count_matches_results": (
            worker_audit["worker_request_count"] == len(results)
        ),
        "worker_response_count_matches_results": (
            worker_audit["worker_response_count"] == len(results)
        ),
        "worker_turn2_previous_state_evidence_present": (
            worker_audit["turn2_previous_state_count"]
            == CTP30_MT_V2_EXPECTED_PRIMARY_RESULTS
        ),
        "worker_turn2_previous_state_is_method_local": (
            worker_audit["method_local_violation_count"] == 0
        ),
        "worker_turn2_previous_state_is_prior_turn": (
            worker_audit["prior_turn_violation_count"] == 0
        ),
        "worker_turn2_previous_state_has_no_gold_fields": (
            worker_audit["raw_previous_state_gold_field_violation_count"] == 0
        ),
        "all_failures_classified": (
            failure_classification.get("unclassified_failure_count") == 0
        ),
        "no_integrity_failures": (
            failure_classification.get("integrity_failure_count") == 0
        ),
        "api_failures_have_retry_evidence": (
            api_failure_summary.get("terminal_without_retry_evidence_count") == 0
        ),
        "api_failures_retained": (
            api_failure_summary.get("terminal_unretained_count") == 0
        ),
        "api_clean_pair_count_at_least_25": (
            api_clean.get("clean_pair_count", 0) >= 25
        ),
        "trace_count_matches_results": trace_audit["trace_file_count"] == len(results),
        "no_mock_or_fallback": trace_audit["mock_call_count"] == 0
        and trace_audit["fallback_call_count"] == 0,
    }
    if skipped_reason:
        checks = {
            key: (key != "not_skipped" and True) or value
            for key, value in checks.items()
        }
        checks["not_skipped"] = False

    failed_checks = [key for key, value in checks.items() if not value]
    status = "skipped" if skipped_reason else ("passed" if not failed_checks else "failed")
    direction_supported = (
        paired_stsr.get("available") is True
        and paired_stsr.get("m3_rate") is not None
        and paired_stsr.get("m2_rate") is not None
        and float(paired_stsr["m3_rate"]) >= float(paired_stsr["m2_rate"])
    )
    return {
        "schema_version": CTP30_MT_V2_REPORT_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "status": status,
        "integrity_status": status,
        "direction_supported": bool(direction_supported),
        "skipped_reason": skipped_reason,
        "benchmark": {
            "path": Path(benchmark_path).as_posix(),
            "dataset_id": benchmark_document.get("dataset_id"),
            "dataset_version": benchmark_document.get("dataset_version"),
            "dataset_role": benchmark_document.get("dataset_role"),
            "split": benchmark_document.get("split"),
            "dataset_sha256": canonical_json_sha256(benchmark_document),
            "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
            "case_count": benchmark_document.get("case_count"),
            "turn_count": benchmark_document.get("turn_count"),
            "primary_turn_id": CTP30_MT_V2_PRIMARY_TURN_ID,
            "primary_result_count": len(primary_results),
        },
        "runtime_config": dict(runtime_config),
        "results": {
            "expected_raw_result_count": CTP30_MT_V2_EXPECTED_RESULTS,
            "actual_raw_result_count": len(results),
            "expected_primary_result_count": CTP30_MT_V2_EXPECTED_PRIMARY_RESULTS,
            "actual_primary_result_count": len(primary_results),
            "status_counts": dict(sorted(status_counts.items())),
            "method_counts": dict(sorted(method_counts.items())),
            "elapsed_seconds": elapsed_seconds,
        },
        "turn_method_grid": all_grid,
        "primary_turn_method_grid": primary_grid,
        "paired_m3_vs_m2_primary_turn": {
            "primary_metric": "stsr",
            **paired_stsr,
            "interpretation": (
                "direction_consistent_with_ctp100"
                if direction_supported
                else "direction_not_consistent_or_unavailable"
            ),
        },
        "method_comparison_summary": method_comparison,
        "previous_state_audit": previous_state_audit,
        "worker_previous_state_audit": worker_audit,
        "api_clean_pair_summary": api_clean,
        "failure_classification_summary": failure_classification,
        "api_failure_summary": api_failure_summary,
        "trace_audit": trace_audit,
        "checks": checks,
        "failed_checks": failed_checks,
        "policy": {
            "sealed_validation_no_tuning_after_run": True,
            "method_failures_retained_and_scored": True,
            "api_infrastructure_failures_retained_and_reported": True,
            "ctp30_v2_is_supplementary_validation_not_ctp100_replacement": True,
            "primary_evaluation_turn": CTP30_MT_V2_PRIMARY_TURN_ID,
            "turn2_previous_state_source": "same_method_turn1_runtime_output_only",
            "gold_visible_to_generation": False,
        },
        "artifacts": _multiturn_v2_artifact_paths(run_dir),
    }


def render_multiturn_v2_report(report: Mapping[str, Any]) -> str:
    results = _mapping(report.get("results"))
    paired = _mapping(report.get("paired_m3_vs_m2_primary_turn"))
    prev = _mapping(report.get("previous_state_audit"))
    worker = _mapping(report.get("worker_previous_state_audit"))
    trace = _mapping(report.get("trace_audit"))
    checks = _mapping(report.get("checks"))
    lines = [
        "# CTP30-v2 Sealed Multi-Turn Validation Report",
        "",
        f"- status: `{report.get('status')}`",
        f"- direction_supported: `{report.get('direction_supported')}`",
        f"- run_id: `{report.get('run_id')}`",
        f"- expected_raw_result_count: `{results.get('expected_raw_result_count')}`",
        f"- actual_raw_result_count: `{results.get('actual_raw_result_count')}`",
        f"- expected_primary_result_count: `{results.get('expected_primary_result_count')}`",
        f"- actual_primary_result_count: `{results.get('actual_primary_result_count')}`",
        f"- method_counts: `{results.get('method_counts')}`",
        f"- status_counts: `{results.get('status_counts')}`",
        f"- trace_file_count: `{trace.get('trace_file_count')}`",
        f"- worker_request_count: `{worker.get('worker_request_count')}`",
        f"- worker_response_count: `{worker.get('worker_response_count')}`",
        "",
        "## Primary-turn M3 vs M2 STSR",
        "",
        f"- pair_count: `{paired.get('pair_count')}`",
        f"- M3 STSR: `{paired.get('m3_rate')}`",
        f"- M2 STSR: `{paired.get('m2_rate')}`",
        f"- delta: `{paired.get('delta_mean')}`",
        f"- 95% paired bootstrap CI: `{paired.get('delta_ci_95')}`",
        f"- McNemar p-value: `{paired.get('mcnemar_p_value')}`",
        "",
        "## Previous-state audit",
        "",
        f"- second_turn_result_count: `{prev.get('second_turn_result_count')}`",
        f"- missing_previous_state_count: `{prev.get('missing_previous_state_count')}`",
        f"- wrong_method_count: `{prev.get('wrong_method_count')}`",
        f"- wrong_prior_turn_count: `{prev.get('wrong_prior_turn_count')}`",
        f"- result_previous_slots_audit_available_count: `{prev.get('result_previous_slots_audit_available_count')}`",
        f"- worker_previous_slots_required_count: `{worker.get('turn2_previous_slots_required_count')}`",
        f"- worker_previous_slots_not_required_count: `{worker.get('turn2_previous_slots_not_required_count')}`",
        f"- worker_missing_previous_slots_count: `{worker.get('missing_previous_slots_count')}`",
        f"- worker_optional_empty_previous_slots_count: `{worker.get('optional_empty_previous_slots_count')}`",
        f"- visible_previous_state_leak_count: `{prev.get('visible_previous_state_leak_count')}`",
        f"- worker_raw_previous_state_gold_field_violation_count: `{worker.get('raw_previous_state_gold_field_violation_count')}`",
        "",
        "## Gate checks",
        "",
        "| check | passed |",
        "| --- | --- |",
    ]
    for key, value in checks.items():
        lines.append(f"| {key} | `{value}` |")
    lines.extend(
        [
            "",
            "## No-tuning policy",
            "",
            (
                "CTP30-v2 is a sealed supplementary multi-turn validation run. "
                "Its observed results must be retained and must not be used to tune "
                "prompts, agents, tools, budget rules, weather data, or scheduling logic."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def _runtime_config(args: argparse.Namespace) -> Dict[str, Any]:
    base_url = args.base_url or os.getenv("LLM_BASE_URL") or settings.llm.base_url
    model = args.model or os.getenv("LLM_MODEL") or settings.llm.model
    return {
        "schema_version": "ctp30-multiturn-v2-runtime-config-v1",
        "provider": _llm_provider_from_base_url(str(base_url)),
        "base_url": str(base_url),
        "model": str(model),
        "api_configured": bool(os.getenv("LLM_API_KEY") or settings.llm.api_key),
        "temperature": float(args.temperature),
        "max_tokens": int(args.max_tokens),
        "timeout_seconds": int(args.timeout_seconds),
        "hard_timeout_seconds": int(args.hard_timeout_seconds),
        "retry_max_attempts": int(args.retry_max_attempts),
        "reasoning_effort": str(args.reasoning_effort),
        "method_order_seed": int(args.method_order_seed),
        "methods": list(CTP30_MT_V2_METHODS),
        "expected_raw_result_count": CTP30_MT_V2_EXPECTED_RESULTS,
        "expected_primary_result_count": CTP30_MT_V2_EXPECTED_PRIMARY_RESULTS,
        "mock_fallback_allowed": False,
    }


def _sealed_env_values(runtime_config: Mapping[str, Any]) -> Dict[str, str]:
    return {
        "EXPERIMENT_STRICT_MODE": "true",
        "EXPERIMENT_DISABLE_CACHE": "true",
        "TRACE_SAVE_USER_MESSAGE": "false",
        "LLM_BASE_URL": str(runtime_config.get("base_url") or ""),
        "LLM_MODEL": str(runtime_config.get("model") or ""),
        "LLM_TEMPERATURE": str(runtime_config.get("temperature")),
        "LLM_MAX_TOKENS": str(runtime_config.get("max_tokens")),
        "LLM_TIMEOUT": str(runtime_config.get("timeout_seconds")),
        "LLM_RETRY_MAX_ATTEMPTS": str(runtime_config.get("retry_max_attempts")),
        "LLM_REASONING_EFFORT": str(runtime_config.get("reasoning_effort") or ""),
        "EXPERIMENT_RESULT_HARD_TIMEOUT_SECONDS": str(
            runtime_config.get("hard_timeout_seconds")
        ),
        "EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER": "true",
    }


def _dataset_shape(cases: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    bad_turn_count = []
    bad_turn_ids = []
    bad_primary = []
    top_level_user_input = []
    turn_count = 0
    for case in cases:
        case_id = _case_id(case)
        turns = case.get("turns") if isinstance(case.get("turns"), list) else []
        turn_count += len(turns)
        if len(turns) != 2:
            bad_turn_count.append(case_id)
        if [str(turn.get("turn_id") or "") for turn in turns] != ["t1", "t2"]:
            bad_turn_ids.append(case_id)
        if str(case.get("primary_turn_id") or CTP30_MT_V2_PRIMARY_TURN_ID) != "t2":
            bad_primary.append(case_id)
        if "user_input" in case:
            top_level_user_input.append(case_id)
    return {
        "turn_count": turn_count,
        "bad_turn_count_case_count": len(bad_turn_count),
        "bad_turn_id_case_count": len(bad_turn_ids),
        "bad_primary_turn_case_count": len(bad_primary),
        "top_level_user_input_case_count": len(top_level_user_input),
        "bad_turn_count_cases": bad_turn_count[:10],
        "bad_turn_id_cases": bad_turn_ids[:10],
        "bad_primary_turn_cases": bad_primary[:10],
        "top_level_user_input_cases": top_level_user_input[:10],
    }


def _expected_turn_units(
    cases: Iterable[Mapping[str, Any]],
    *,
    primary_only: bool,
) -> List[Dict[str, Any]]:
    units: List[Dict[str, Any]] = []
    for case in cases:
        case_id = _case_id(case)
        primary_turn_id = str(case.get("primary_turn_id") or CTP30_MT_V2_PRIMARY_TURN_ID)
        turns = case.get("turns") if isinstance(case.get("turns"), list) else []
        for turn_index, turn in enumerate(turns):
            if not isinstance(turn, Mapping):
                continue
            turn_id = str(turn.get("turn_id") or turn.get("id") or f"t{turn_index + 1}")
            is_primary = _turn_is_primary(
                turn,
                turn_index=turn_index,
                turn_count=len(turns),
                primary_turn_id=primary_turn_id,
            )
            if primary_only and not is_primary:
                continue
            units.append(
                {
                    "case_id": case_id,
                    "turn_id": turn_id,
                    "turn_index": turn_index,
                    "is_primary": is_primary,
                }
            )
    return units


def _turn_method_grid(
    results: Iterable[Mapping[str, Any]],
    *,
    expected_units: Iterable[Mapping[str, Any]],
    expected_methods: Iterable[str],
) -> Dict[str, Any]:
    units = list(expected_units)
    methods = list(expected_methods)
    counts: Dict[tuple[str, str, str], int] = defaultdict(int)
    for result in results:
        case_id = str(result.get("case_id") or result.get("scenario_id") or "")
        turn_id = str(result.get("turn_id") or "")
        method = str(result.get("method") or "")
        counts[(case_id, turn_id, method)] += 1
    expected_turn_ids = {(str(unit["case_id"]), str(unit["turn_id"])) for unit in units}
    expected_case_ids = {case_id for case_id, _turn_id in expected_turn_ids}
    missing = [
        {"case_id": str(unit["case_id"]), "turn_id": str(unit["turn_id"]), "method": method}
        for unit in units
        for method in methods
        if counts[(str(unit["case_id"]), str(unit["turn_id"]), method)] == 0
    ]
    duplicates = [
        {"case_id": case_id, "turn_id": turn_id, "method": method, "count": count}
        for (case_id, turn_id, method), count in sorted(counts.items())
        if (case_id, turn_id) in expected_turn_ids and method in methods and count > 1
    ]
    unexpected = [
        {"case_id": case_id, "turn_id": turn_id, "method": method, "count": count}
        for (case_id, turn_id, method), count in sorted(counts.items())
        if (
            case_id not in expected_case_ids
            or (case_id, turn_id) not in expected_turn_ids
            or method not in methods
        )
    ]
    return {
        "expected_turn_count": len(units),
        "expected_methods": methods,
        "expected_result_count": len(units) * len(methods),
        "missing_count": len(missing),
        "duplicate_count": len(duplicates),
        "unexpected_count": len(unexpected),
        "missing": missing,
        "duplicates": duplicates,
        "unexpected": unexpected,
    }


def _previous_state_audit(results: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    second_turns = [
        result
        for result in results
        if _optional_int(result.get("turn_index")) is not None
        and (_optional_int(result.get("turn_index")) or 0) > 0
    ]
    missing = []
    wrong_method = []
    wrong_prior = []
    previous_state_has_evaluation = []
    previous_state_has_metrics = []
    visible_leaks = []
    missing_previous_slots = []
    result_previous_slots_audit_available_count = 0
    slot_hashes = []
    for result in second_turns:
        label = _result_label(result)
        audit = _mapping(result.get("method_previous_state_audit"))
        if result.get("previous_state_provided") is not True:
            missing.append(label)
        if str(result.get("previous_state_method") or "") != str(result.get("method") or ""):
            wrong_method.append(label)
        if not (
            str(result.get("previous_state_turn_id") or "") == "t1"
            and _optional_int(result.get("previous_state_turn_index")) == 0
            and result.get("previous_state_is_prior_turn") is True
        ):
            wrong_prior.append(label)
        if result.get("previous_state_has_evaluation") is True:
            previous_state_has_evaluation.append(label)
        if result.get("previous_state_has_metrics") is True:
            previous_state_has_metrics.append(label)
        if (
            audit.get("visible_previous_state_has_evaluation") is True
            or audit.get("visible_previous_state_has_metrics") is True
            or audit.get("visible_previous_state_has_constraint_report") is True
        ):
            visible_leaks.append(label)
        if "previous_slots_auditable" in audit:
            result_previous_slots_audit_available_count += 1
            if audit.get("previous_slots_auditable") is not True:
                missing_previous_slots.append(label)
            if audit.get("previous_slots_sha256"):
                slot_hashes.append(str(audit.get("previous_slots_sha256")))
    return {
        "schema_version": "ctp30-multiturn-v2-previous-state-audit-v1",
        "second_turn_result_count": len(second_turns),
        "expected_second_turn_result_count": CTP30_MT_V2_EXPECTED_PRIMARY_RESULTS,
        "missing_previous_state_count": len(missing),
        "wrong_method_count": len(wrong_method),
        "wrong_prior_turn_count": len(wrong_prior),
        "previous_state_has_evaluation_count": len(previous_state_has_evaluation),
        "previous_state_has_metrics_count": len(previous_state_has_metrics),
        "visible_previous_state_leak_count": len(visible_leaks),
        "missing_previous_slots_count": len(missing_previous_slots),
        "result_previous_slots_audit_available_count": result_previous_slots_audit_available_count,
        "previous_slots_auditable_count": (
            result_previous_slots_audit_available_count - len(missing_previous_slots)
        ),
        "unique_previous_slots_sha256_count": len(set(slot_hashes)),
        "sample_missing_previous_state": missing[:10],
        "sample_wrong_method": wrong_method[:10],
        "sample_wrong_prior_turn": wrong_prior[:10],
        "sample_previous_state_has_evaluation": previous_state_has_evaluation[:10],
        "sample_previous_state_has_metrics": previous_state_has_metrics[:10],
        "sample_visible_previous_state_leaks": visible_leaks[:10],
        "sample_missing_previous_slots": missing_previous_slots[:10],
    }


def _previous_slots_required_by_case(
    benchmark_document: Mapping[str, Any],
) -> Dict[str, bool]:
    """Return whether each scenario should have non-empty previous slots on t2.

    Most CTP30-v2 scenarios start with a concrete travel request, so their second
    turn must expose auditable slots copied from the method's own first-turn
    runtime state.  A small number of control scenarios start as general chat or
    clarification and legitimately have no travel slots yet; those still require
    a method-local prior state, but they must not fail only because the prior
    state's slots are empty.
    """
    requirements: Dict[str, bool] = {}
    for case in _cases_from_document(benchmark_document):
        case_id = _case_id(case)
        turns = case.get("turns") if isinstance(case.get("turns"), list) else []
        first_turn = turns[0] if turns and isinstance(turns[0], Mapping) else {}
        slots = first_turn.get("slots") if isinstance(first_turn.get("slots"), Mapping) else {}
        current_slots = (
            first_turn.get("current_slots")
            if isinstance(first_turn.get("current_slots"), Mapping)
            else {}
        )
        requirements[case_id] = bool(slots or current_slots)
    return requirements


def _worker_previous_state_audit(
    run_dir: Path,
    results: Iterable[Mapping[str, Any]],
    *,
    previous_slots_required_by_case: Mapping[str, bool],
) -> Dict[str, Any]:
    worker_dir = run_dir / "worker_io"
    request_paths = sorted(worker_dir.glob("*.request.json")) if worker_dir.exists() else []
    response_paths = sorted(worker_dir.glob("*.response.json")) if worker_dir.exists() else []
    request_by_id: Dict[str, Mapping[str, Any]] = {}
    malformed_request_count = 0
    for path in request_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            malformed_request_count += 1
            continue
        if isinstance(payload, Mapping):
            request_by_id[str(payload.get("request_id") or path.stem)] = payload

    turn2_results = [
        result
        for result in results
        if _optional_int(result.get("turn_index")) is not None
        and (_optional_int(result.get("turn_index")) or 0) > 0
    ]
    missing_request = []
    missing_previous_state = []
    missing_required_previous_slots = []
    empty_optional_previous_slots = []
    method_local_violations = []
    prior_turn_violations = []
    gold_violations = []
    previous_slots_required_count = 0
    previous_slots_not_required_count = 0
    for result in turn2_results:
        label = _result_label(result)
        case_id = str(label.get("case_id") or "")
        previous_slots_required = previous_slots_required_by_case.get(case_id, True)
        if previous_slots_required:
            previous_slots_required_count += 1
        else:
            previous_slots_not_required_count += 1
        request_id = str(result.get("request_id") or "")
        payload = request_by_id.get(request_id)
        if not isinstance(payload, Mapping):
            missing_request.append(label)
            continue
        case = payload.get("case") if isinstance(payload.get("case"), Mapping) else {}
        previous_state = (
            case.get("previous_state")
            if isinstance(case.get("previous_state"), Mapping)
            else None
        )
        if not isinstance(previous_state, Mapping):
            missing_previous_state.append(label)
            continue
        previous_slots = previous_state.get("slots")
        if not isinstance(previous_slots, Mapping) or not previous_slots:
            if previous_slots_required:
                missing_required_previous_slots.append(label)
            else:
                empty_optional_previous_slots.append(label)
        if str(previous_state.get("method") or "") != str(payload.get("method") or ""):
            method_local_violations.append(label)
        if not (
            str(previous_state.get("turn_id") or "") == "t1"
            and _optional_int(previous_state.get("turn_index")) == 0
        ):
            prior_turn_violations.append(label)
        leaked_fields = [
            field
            for field in _PREVIOUS_STATE_GOLD_FIELDS
            if field in previous_state
        ]
        if leaked_fields:
            gold_violations.append({**label, "fields": leaked_fields})
    return {
        "schema_version": "ctp30-multiturn-v2-worker-previous-state-audit-v1",
        "worker_request_count": len(request_paths),
        "worker_response_count": len(response_paths),
        "malformed_worker_request_count": malformed_request_count,
        "turn2_result_count": len(turn2_results),
        "turn2_request_count": len(turn2_results) - len(missing_request),
        "turn2_previous_state_count": len(turn2_results) - len(missing_previous_state) - len(missing_request),
        "turn2_previous_slots_required_count": previous_slots_required_count,
        "turn2_previous_slots_not_required_count": previous_slots_not_required_count,
        "turn2_previous_slots_auditable_count": (
            previous_slots_required_count
            - len(missing_required_previous_slots)
        ),
        "missing_worker_request_count": len(missing_request),
        "missing_previous_state_count": len(missing_previous_state),
        "missing_previous_slots_count": len(missing_required_previous_slots),
        "optional_empty_previous_slots_count": len(empty_optional_previous_slots),
        "method_local_violation_count": len(method_local_violations),
        "prior_turn_violation_count": len(prior_turn_violations),
        "raw_previous_state_gold_field_violation_count": len(gold_violations),
        "sample_missing_worker_request": missing_request[:10],
        "sample_missing_previous_state": missing_previous_state[:10],
        "sample_missing_previous_slots": missing_required_previous_slots[:10],
        "sample_optional_empty_previous_slots": empty_optional_previous_slots[:10],
        "sample_method_local_violations": method_local_violations[:10],
        "sample_prior_turn_violations": prior_turn_violations[:10],
        "sample_raw_previous_state_gold_field_violations": gold_violations[:10],
    }


def _trace_audit(run_dir: Path, traces: List[Dict[str, Any]], *, result_count: int) -> Dict[str, Any]:
    llm_calls = [
        call
        for trace in traces
        for call in (trace.get("llm_calls") or [])
        if isinstance(call, Mapping)
    ]
    return {
        "trace_file_count": len(traces),
        "result_count": result_count,
        "llm_call_count": len(llm_calls),
        "mock_call_count": sum(
            1 for call in llm_calls if call.get("mock") or call.get("mock_used")
        ),
        "fallback_call_count": sum(
            1 for call in llm_calls if call.get("fallback") or call.get("fallback_used")
        ),
    }


def _api_clean_pair_summary(
    results: List[Dict[str, Any]],
    *,
    failure_classification: Mapping[str, Any],
    expected_case_ids: Sequence[str],
) -> Dict[str, Any]:
    api_polluted = set()
    expected_set = set(expected_case_ids)
    for item in failure_classification.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        if item.get("method") not in CTP30_MT_V2_METHODS:
            continue
        if int(item.get("terminal_api_failure_count") or 0) <= 0:
            continue
        case_id = str(item.get("case_id") or item.get("scenario_id") or "")
        if case_id in expected_set:
            api_polluted.add(case_id)
    clean = [case_id for case_id in expected_case_ids if case_id not in api_polluted]
    return {
        "total_pair_count": len(expected_case_ids),
        "api_polluted_pair_count": len(api_polluted),
        "clean_pair_count": len(clean),
        "minimum_clean_pair_count": 25,
        "excluded_api_polluted_pairs": sorted(api_polluted),
    }


def _method_comparison_summary(
    primary_results: Iterable[Mapping[str, Any]],
    *,
    summary: Mapping[str, Any],
) -> Dict[str, Any]:
    rows = list(primary_results)
    by_method: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_method[str(row.get("method") or "")].append(row)
    method_rates = {}
    for method in CTP30_MT_V2_METHODS:
        method_rows = by_method.get(method, [])
        success_values = [
            float((_mapping(row.get("metrics")).get("stsr") or 0.0))
            for row in method_rows
        ]
        method_rates[method] = {
            "primary_result_count": len(method_rows),
            "stsr_mean": _mean(success_values),
            "completed_count": sum(
                1 for row in method_rows if str(row.get("status") or "") == "completed"
            ),
        }
    return {
        "schema_version": "ctp30-multiturn-v2-method-comparison-summary-v1",
        "evaluation_summary_schema_version": summary.get("schema_version"),
        "primary_turn_only": True,
        "methods": method_rates,
    }


def _paired_stsr(summary: Mapping[str, Any]) -> Dict[str, Any]:
    stat = (
        ((summary.get("paired_statistics") or {}).get("metrics") or {}).get("stsr")
        if isinstance(summary.get("paired_statistics"), Mapping)
        else None
    )
    if not isinstance(stat, Mapping):
        return {"available": False}
    mcnemar = stat.get("mcnemar") if isinstance(stat.get("mcnemar"), Mapping) else {}
    return {
        "available": True,
        "pair_count": stat.get("pair_count"),
        "m3_rate": _nested_number(stat, "m3", "mean"),
        "m2_rate": _nested_number(stat, "m2", "mean"),
        "delta_mean": _nested_number(stat, "delta", "mean"),
        "delta_ci_95": _nested_value(stat, "delta", "bootstrap_ci_95"),
        "m3_only_success": mcnemar.get("m3_only_success"),
        "m2_only_success": mcnemar.get("m2_only_success"),
        "discordant_pairs": mcnemar.get("discordant_pairs"),
        "mcnemar_p_value": mcnemar.get("p_value"),
        "mcnemar_method": mcnemar.get("method"),
    }


def _attach_multiturn_v2_metadata_to_manifest(
    run_dir: Path,
    *,
    report: Mapping[str, Any],
    preflight: Mapping[str, Any],
    frozen_ctp100_commit: str,
) -> None:
    manifest_path = run_dir / MANIFEST_NAME
    manifest = _read_json_object(manifest_path)
    manifest["sealed_multiturn_validation"] = {
        "schema_version": CTP30_MT_V2_REPORT_SCHEMA_VERSION,
        "status": report.get("status"),
        "direction_supported": report.get("direction_supported"),
        "gate_path": (run_dir / GATE_NAME).as_posix(),
        "report_path": (run_dir / REPORT_NAME).as_posix(),
        "preflight_path": (run_dir / PREFLIGHT_NAME).as_posix(),
        "primary_evaluation_turn": CTP30_MT_V2_PRIMARY_TURN_ID,
        "turn2_previous_state_source": "same_method_turn1_runtime_output_only",
        "no_tuning_after_run": True,
        "frozen_ctp100_v6_commit": frozen_ctp100_commit,
        "protected_core_hash_audit_status": (
            (preflight.get("protected_core_hash_audit") or {}).get("status")
            if isinstance(preflight.get("protected_core_hash_audit"), Mapping)
            else None
        ),
    }
    results = manifest.get("results") if isinstance(manifest.get("results"), Mapping) else {}
    results = dict(results)
    results.update(
        {
            "multiturn_sealed_validation_preflight": (run_dir / PREFLIGHT_NAME).as_posix(),
            "multiturn_sealed_validation_gate": (run_dir / GATE_NAME).as_posix(),
            "multiturn_sealed_validation_report": (run_dir / REPORT_NAME).as_posix(),
        }
    )
    manifest["results"] = results
    _write_json(manifest_path, manifest)


def _write_multiturn_v2_report(run_dir: Path, report: Mapping[str, Any]) -> None:
    _write_json(run_dir / GATE_NAME, report)
    (run_dir / REPORT_NAME).write_text(
        render_multiturn_v2_report(report),
        encoding="utf-8",
    )


def _multiturn_v2_artifact_files(benchmark_path: str | Path) -> Dict[str, str | Path]:
    return {
        "sealed_multiturn_benchmark_source": Path(benchmark_path),
        "sealed_multiturn_preflight": PREFLIGHT_NAME,
        "benchmark_results_csv": "benchmark_results.csv",
        "benchmark_results_json": "benchmark_results.json",
        "benchmark_results_checkpoint_csv": "benchmark_results.checkpoint.csv",
        "benchmark_results_checkpoint_json": "benchmark_results.checkpoint.json",
        "evaluation_summary": "evaluation_summary.json",
        "paper_tables": "paper_tables.md",
        "sealed_multiturn_manifest": MANIFEST_NAME,
        "benchmark_resume_state": "benchmark_resume_state.json",
        "sealed_multiturn_gate": GATE_NAME,
        "sealed_multiturn_report": REPORT_NAME,
    }


def _multiturn_v2_artifact_paths(run_dir: Path) -> Dict[str, str]:
    return {
        "preflight": (run_dir / PREFLIGHT_NAME).as_posix(),
        "benchmark_results_json": (run_dir / "benchmark_results.json").as_posix(),
        "benchmark_results_csv": (run_dir / "benchmark_results.csv").as_posix(),
        "evaluation_summary": (run_dir / "evaluation_summary.json").as_posix(),
        "paper_tables": (run_dir / "paper_tables.md").as_posix(),
        "manifest": (run_dir / MANIFEST_NAME).as_posix(),
        "checkpoint_json": (run_dir / "benchmark_results.checkpoint.json").as_posix(),
        "checkpoint_csv": (run_dir / "benchmark_results.checkpoint.csv").as_posix(),
        "resume_state": (run_dir / "benchmark_resume_state.json").as_posix(),
        "traces": (run_dir / "traces").as_posix(),
        "worker_io": (run_dir / "worker_io").as_posix(),
        "gate": (run_dir / GATE_NAME).as_posix(),
        "report": (run_dir / REPORT_NAME).as_posix(),
        "final_artifact_index": (run_dir / "final_artifact_index.json").as_posix(),
    }


def _payload(
    run_id: str,
    run_dir: Path,
    report: Mapping[str, Any],
    *,
    final_index: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    results = report.get("results") if isinstance(report.get("results"), Mapping) else {}
    payload = {
        "status": report.get("status"),
        "run_id": run_id,
        "output_dir": run_dir.as_posix(),
        "raw_result_count": results.get("actual_raw_result_count"),
        "expected_raw_result_count": CTP30_MT_V2_EXPECTED_RESULTS,
        "primary_result_count": results.get("actual_primary_result_count"),
        "expected_primary_result_count": CTP30_MT_V2_EXPECTED_PRIMARY_RESULTS,
        "direction_supported": report.get("direction_supported"),
        "sealed_gate": (run_dir / GATE_NAME).as_posix(),
        "sealed_report": (run_dir / REPORT_NAME).as_posix(),
        "manifest": (run_dir / MANIFEST_NAME).as_posix(),
        "checkpoint_json": (run_dir / "benchmark_results.checkpoint.json").as_posix(),
        "checkpoint_csv": (run_dir / "benchmark_results.checkpoint.csv").as_posix(),
        "traces": (run_dir / "traces").as_posix(),
        "worker_io": (run_dir / "worker_io").as_posix(),
        "failed_checks": report.get("failed_checks") or [],
    }
    if final_index:
        payload["final_artifact_index_json"] = final_index.get("json")
        payload["final_artifact_index_status"] = final_index.get("index_status")
    return payload


def _primary_turn_results(results: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    primary: List[Dict[str, Any]] = []
    for result in results:
        if result.get("target_turn") is True:
            primary.append(dict(result))
            continue
        if "target_turn" not in result and str(result.get("turn_id") or "") == "t2":
            primary.append(dict(result))
    return primary


def _turn_is_primary(
    turn: Mapping[str, Any],
    *,
    turn_index: int,
    turn_count: int,
    primary_turn_id: str,
) -> bool:
    for key in ("target_turn", "evaluate_turn", "is_target_turn"):
        if key in turn:
            return _bool_value(turn.get(key))
    turn_id = str(turn.get("turn_id") or turn.get("id") or "")
    if primary_turn_id:
        return turn_id == primary_turn_id
    return turn_count <= 1 or turn_index == turn_count - 1


def _case_id(case: Mapping[str, Any]) -> str:
    return str(case.get("case_id") or case.get("scenario_id") or case.get("id") or "")


def _cases_from_document(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    cases = document.get("cases") if isinstance(document.get("cases"), list) else []
    return [case for case in cases if isinstance(case, dict)]


def _resolve_run_output_dir(output_dir: str | Path, run_id: str) -> Path:
    root = Path(output_dir)
    return root if root.name == run_id else root / run_id


def _read_json_object(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _llm_provider_from_base_url(base_url: str) -> str:
    lowered = base_url.lower()
    if "vectorengine" in lowered:
        return "vectorengine_openai_compatible"
    if "openrouter" in lowered:
        return "openrouter_openai_compatible"
    if "openai" in lowered:
        return "openai"
    return "openai_compatible"


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _nested_value(value: Mapping[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _nested_number(value: Mapping[str, Any], *keys: str) -> Optional[float]:
    target = _nested_value(value, *keys)
    if isinstance(target, bool):
        return None
    if isinstance(target, (int, float)):
        return float(target)
    return None


def _optional_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _mean(values: Iterable[float]) -> Optional[float]:
    numbers = list(values)
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 6)


def _result_label(result: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "case_id": result.get("case_id") or result.get("scenario_id"),
        "turn_id": result.get("turn_id"),
        "method": result.get("method"),
    }


def _bool_value(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


@contextmanager
def _temporary_env(values: Mapping[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
