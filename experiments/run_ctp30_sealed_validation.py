"""Run the CTP30 sealed validation set for M2/M3 only.

CTP30 is a post-freeze validation run.  It must not be used for tuning and it
must not run M0/M1.  The script adds experiment infrastructure only; it reuses
the frozen system methods, prompts, tools, evaluator, weather snapshot, budget
rules, and intercity data.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
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


CTP30_SEALED_SCHEMA_VERSION = "ctp30-sealed-validation-report-v1"
CTP30_SEALED_PREFLIGHT_SCHEMA_VERSION = "ctp30-sealed-validation-preflight-v1"
CTP30_SEALED_DATASET_ID = "ctp30_sealed_validation_v1"
CTP30_SEALED_DATASET_ROLE = "sealed_validation_after_main_design_freeze"
CTP30_SEALED_METHODS = ("fixed_multi_agent", "adaptive_multi_agent")
CTP30_EXPECTED_CASES = 30
CTP30_EXPECTED_TURNS = 30
CTP30_EXPECTED_RESULTS = CTP30_EXPECTED_TURNS * len(CTP30_SEALED_METHODS)
CTP100_V6_FROZEN_COMMIT = "0b925c93e2edf88e2dfb4346b11bc24faaae24a7"
DEFAULT_BENCHMARK_PATH = ROOT / "experiments" / "ctp30_sealed_validation_v1.json"
DEFAULT_OUTPUT_ROOT = Path(r"D:\Tourism_Agent_Formal_Runs")
SEALED_PREFLIGHT_NAME = "sealed_validation_preflight.json"
SEALED_MANIFEST_NAME = "sealed_validation_manifest.json"
SEALED_GATE_NAME = "sealed_validation_gate.json"
SEALED_REPORT_NAME = "sealed_validation_report.md"
DEFAULT_MODEL_CONFIG_NAME = "ctp30-sealed-validation"

PROTECTED_CORE_PATHS = (
    "app/agents",
    "app/tools",
    "app/core/goal_state_scheduler.py",
    "app/core/fixed_data.py",
    "app/core/independent_evaluator.py",
    "experiments/ctp100_formal_v2.json",
    "experiments/ctp30_sealed_validation_v1.json",
    "data/weather_snapshot",
    "data/intercity_transport",
)


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
    parser.add_argument("--frozen-ctp100-commit", type=str, default=CTP100_V6_FROZEN_COMMIT)
    parser.add_argument(
        "--require-clean-git",
        action="store_true",
        help="Require a clean working tree before the sealed validation run starts.",
    )
    args = parser.parse_args()

    run_id = args.run_id or f"ctp30_sealed_validation_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = _resolve_run_output_dir(args.output_dir, run_id)
    runtime = _runtime_config(args)
    preflight = build_sealed_validation_preflight(
        benchmark_path=args.benchmark,
        output_dir=args.output_dir,
        run_id=run_id,
        runtime_config=runtime,
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
    _write_json(run_dir / SEALED_PREFLIGHT_NAME, preflight)
    benchmark_document, cases = load_benchmark_document(args.benchmark)

    if args.dry_run:
        report = build_sealed_validation_report(
            run_id=run_id,
            run_dir=run_dir,
            benchmark_path=args.benchmark,
            benchmark_document=benchmark_document,
            runtime_config=runtime,
            results=[],
            elapsed_seconds=0.0,
            skipped_reason="dry_run",
        )
        _write_sealed_report(run_dir, report)
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
            methods=CTP30_SEALED_METHODS,
            repeats=1,
            run_id=run_id,
            model_config_name=args.model_config_name,
            csv_path=run_dir / "benchmark_results.csv",
            json_path=run_dir / "benchmark_results.json",
            summary_path=run_dir / "evaluation_summary.json",
            paper_tables_path=run_dir / "paper_tables.md",
            manifest_path=run_dir / SEALED_MANIFEST_NAME,
            resume=args.resume,
        )
    elapsed = time.perf_counter() - started
    report = build_sealed_validation_report(
        run_id=run_id,
        run_dir=run_dir,
        benchmark_path=args.benchmark,
        benchmark_document=benchmark_document,
        runtime_config=runtime,
        results=results,
        elapsed_seconds=elapsed,
    )
    _attach_sealed_metadata_to_manifest(
        run_dir,
        report=report,
        preflight=preflight,
        frozen_ctp100_commit=args.frozen_ctp100_commit,
    )
    _write_sealed_report(run_dir, report)
    final_index = write_final_artifact_index(
        run_dir,
        artifact_files=_sealed_artifact_files(run_dir, args.benchmark),
        manifest_name=SEALED_MANIFEST_NAME,
    )
    payload = _payload(run_id, run_dir, report, final_index=final_index)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.strict_sealed_readiness and (
        report["status"] != "passed" or final_index["index_status"] != "passed"
    ):
        return 1
    return 0


def build_sealed_validation_preflight(
    *,
    benchmark_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    runtime_config: Mapping[str, Any],
    resume: bool = False,
    require_clean_git: bool = False,
    frozen_ctp100_commit: str = CTP100_V6_FROZEN_COMMIT,
) -> Dict[str, Any]:
    """Build a read-only CTP30 sealed validation preflight report."""
    benchmark_file = Path(benchmark_path)
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
    output_dir_has_contents = run_dir.exists() and any(run_dir.iterdir())
    if output_dir_has_contents and not resume:
        errors.append(f"output directory is not empty: {run_dir}")

    case_ids = _case_ids(cases)
    turn_count = _turn_count(cases)
    dataset_id = document.get("dataset_id") if isinstance(document, Mapping) else None
    dataset_role = document.get("dataset_role") if isinstance(document, Mapping) else None
    protected_audit = _protected_core_hash_audit(frozen_ctp100_commit)
    if protected_audit["status"] != "passed":
        errors.append("protected core files changed from frozen CTP100 v6 commit")
    if require_clean_git and not _git_working_tree_clean():
        errors.append("working tree must be clean before CTP30 sealed validation")
    if not runtime_config.get("api_configured"):
        errors.append("LLM API config is required for CTP30 sealed validation")

    checks = {
        "benchmark_exists": benchmark_file.exists(),
        "dataset_id_matches": dataset_id == CTP30_SEALED_DATASET_ID,
        "dataset_role_matches": dataset_role == CTP30_SEALED_DATASET_ROLE,
        "case_count_30": len(cases) == CTP30_EXPECTED_CASES,
        "turn_count_30": turn_count == CTP30_EXPECTED_TURNS,
        "case_ids_unique": len(case_ids) == len(set(case_ids)),
        "methods_are_m2_m3_only": tuple(runtime_config.get("methods") or ())
        == CTP30_SEALED_METHODS,
        "expected_result_count_60": turn_count * len(CTP30_SEALED_METHODS)
        == CTP30_EXPECTED_RESULTS,
        "output_dir_empty_or_resume": not output_dir_has_contents or bool(resume),
        "api_configured": bool(runtime_config.get("api_configured")),
        "protected_core_unchanged_from_ctp100_v6": protected_audit["status"] == "passed",
        "working_tree_clean_if_required": (not require_clean_git) or _git_working_tree_clean(),
    }
    errors.extend(key for key, passed in checks.items() if not passed and key not in {
        "api_configured",
        "output_dir_empty_or_resume",
        "protected_core_unchanged_from_ctp100_v6",
        "working_tree_clean_if_required",
    })
    return {
        "schema_version": CTP30_SEALED_PREFLIGHT_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "benchmark": {
            "path": benchmark_file.as_posix(),
            "dataset_id": dataset_id,
            "dataset_role": dataset_role,
            "dataset_sha256": canonical_json_sha256(document) if document is not None else None,
            "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY if document is not None else None,
            "case_count": len(cases),
            "turn_count": turn_count,
            "expected_result_count": CTP30_EXPECTED_RESULTS,
        },
        "run": {
            "run_id": run_id,
            "output_dir": run_dir.as_posix(),
            "methods": list(CTP30_SEALED_METHODS),
            "method_count": len(CTP30_SEALED_METHODS),
            "repeats": 1,
            "method_order_seed": runtime_config.get("method_order_seed"),
            "expected_raw_run_count": CTP30_EXPECTED_RESULTS,
            "resume_requested": bool(resume),
        },
        "runtime_config": dict(runtime_config),
        "method_fairness_contract": {
            "methods": list(CTP30_SEALED_METHODS),
            "contract_sha256": method_fairness_contract_hash(CTP30_SEALED_METHODS),
        },
        "git": {
            "current_commit": _git_commit(),
            "working_tree_clean": _git_working_tree_clean(),
            "require_clean_git": bool(require_clean_git),
            "frozen_ctp100_v6_commit": frozen_ctp100_commit,
        },
        "protected_core_hash_audit": protected_audit,
        "checks": checks,
        "failed_checks": [key for key, passed in checks.items() if not passed],
        "policy": {
            "sealed_validation_no_tuning_after_run": True,
            "methods_locked_to_m2_m3": True,
            "does_not_replace_ctp100_main_experiment": True,
            "preflight_consumes_api": False,
        },
    }


def build_sealed_validation_report(
    *,
    run_id: str,
    run_dir: Path,
    benchmark_path: str | Path,
    benchmark_document: Mapping[str, Any],
    runtime_config: Mapping[str, Any],
    results: List[Dict[str, Any]],
    elapsed_seconds: float,
    skipped_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the CTP30 sealed validation evidence report."""
    summary = _read_json_object(run_dir / "evaluation_summary.json")
    traces = _load_traces(run_dir, results)
    failure_classification = _failure_classification_summary(run_dir, results)
    api_failure_summary = _api_failure_timeout_summary(traces)
    method_counts = Counter(str(result.get("method") or "") for result in results)
    status_counts = Counter(str(result.get("status") or "unknown") for result in results)
    expected_case_ids = _case_ids(_cases_from_document(benchmark_document))
    grid = _case_method_grid(
        results,
        expected_case_ids=expected_case_ids,
        expected_methods=CTP30_SEALED_METHODS,
    )
    stsr = _paired_stsr(summary)
    api_clean = _api_clean_pair_summary(
        results,
        failure_classification=failure_classification,
        expected_case_ids=expected_case_ids,
    )
    trace_audit = _trace_audit(run_dir, traces, result_count=len(results))
    checks = {
        "not_skipped": skipped_reason is None,
        "expected_result_count_60": len(results) == CTP30_EXPECTED_RESULTS,
        "m2_m3_methods_only": set(method_counts) <= set(CTP30_SEALED_METHODS),
        "method_grid_complete": grid["missing_count"] == 0
        and grid["duplicate_count"] == 0
        and grid["unexpected_count"] == 0,
        "paired_m3_m2_present": stsr.get("pair_count") == CTP30_EXPECTED_CASES,
        "all_failures_classified": failure_classification.get("unclassified_failure_count") == 0,
        "no_integrity_failures": failure_classification.get("integrity_failure_count") == 0,
        "api_failures_have_retry_evidence": api_failure_summary.get(
            "terminal_without_retry_evidence_count"
        )
        == 0,
        "api_failures_retained": api_failure_summary.get("terminal_unretained_count") == 0,
        "api_clean_pair_count_at_least_25": api_clean.get("clean_pair_count", 0) >= 25,
        "trace_count_matches_results": trace_audit["trace_file_count"] == len(results),
        "worker_request_count_matches_results": trace_audit["worker_request_count"] == len(results),
        "worker_response_count_matches_results": trace_audit["worker_response_count"] == len(results),
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
    integrity_status = "skipped" if skipped_reason else ("passed" if not failed_checks else "failed")
    direction_supported = (
        stsr.get("available") is True
        and stsr.get("m3_rate") is not None
        and stsr.get("m2_rate") is not None
        and float(stsr["m3_rate"]) >= float(stsr["m2_rate"])
    )
    return {
        "schema_version": CTP30_SEALED_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "status": integrity_status,
        "integrity_status": integrity_status,
        "direction_supported": bool(direction_supported),
        "skipped_reason": skipped_reason,
        "benchmark": {
            "path": Path(benchmark_path).as_posix(),
            "dataset_id": benchmark_document.get("dataset_id"),
            "dataset_role": benchmark_document.get("dataset_role"),
            "dataset_sha256": canonical_json_sha256(benchmark_document),
            "case_count": benchmark_document.get("case_count"),
            "turn_count": benchmark_document.get("turn_count"),
        },
        "runtime_config": dict(runtime_config),
        "results": {
            "expected_result_count": CTP30_EXPECTED_RESULTS,
            "actual_result_count": len(results),
            "status_counts": dict(sorted(status_counts.items())),
            "method_counts": dict(sorted(method_counts.items())),
            "elapsed_seconds": elapsed_seconds,
        },
        "case_method_grid": grid,
        "paired_m3_vs_m2": {
            "primary_metric": "stsr",
            **stsr,
            "interpretation": (
                "direction_consistent_with_ctp100"
                if direction_supported
                else "direction_not_consistent_or_unavailable"
            ),
        },
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
            "ctp30_is_validation_not_replacement_for_ctp100": True,
        },
        "artifacts": _sealed_artifact_paths(run_dir),
    }


def render_sealed_validation_report(report: Mapping[str, Any]) -> str:
    paired = report.get("paired_m3_vs_m2") if isinstance(report.get("paired_m3_vs_m2"), Mapping) else {}
    results = report.get("results") if isinstance(report.get("results"), Mapping) else {}
    api_clean = report.get("api_clean_pair_summary") if isinstance(report.get("api_clean_pair_summary"), Mapping) else {}
    failure = report.get("failure_classification_summary") if isinstance(report.get("failure_classification_summary"), Mapping) else {}
    trace = report.get("trace_audit") if isinstance(report.get("trace_audit"), Mapping) else {}
    lines = [
        "# CTP30 Sealed Validation Report",
        "",
        f"- status: `{report.get('status')}`",
        f"- direction_supported: `{report.get('direction_supported')}`",
        f"- run_id: `{report.get('run_id')}`",
        f"- expected_result_count: `{results.get('expected_result_count')}`",
        f"- actual_result_count: `{results.get('actual_result_count')}`",
        f"- method_counts: `{results.get('method_counts')}`",
        f"- status_counts: `{results.get('status_counts')}`",
        f"- trace_file_count: `{trace.get('trace_file_count')}`",
        f"- worker_request_count: `{trace.get('worker_request_count')}`",
        f"- worker_response_count: `{trace.get('worker_response_count')}`",
        "",
        "## M3 vs M2 STSR",
        "",
        f"- pair_count: `{paired.get('pair_count')}`",
        f"- M3 STSR: `{paired.get('m3_rate')}`",
        f"- M2 STSR: `{paired.get('m2_rate')}`",
        f"- delta: `{paired.get('delta_mean')}`",
        f"- 95% paired bootstrap CI: `{paired.get('delta_ci_95')}`",
        f"- McNemar p-value: `{paired.get('mcnemar_p_value')}`",
        f"- M3-only success cases: `{paired.get('m3_only_success')}`",
        f"- M2-only success cases: `{paired.get('m2_only_success')}`",
        "",
        "## Failure and API classification",
        "",
        f"- method_failure_count: `{failure.get('method_failure_count')}`",
        f"- api_infrastructure_failure_count: `{failure.get('api_infrastructure_failure_count')}`",
        f"- integrity_failure_count: `{failure.get('integrity_failure_count')}`",
        f"- unclassified_failure_count: `{failure.get('unclassified_failure_count')}`",
        f"- api_clean_pair_count: `{api_clean.get('clean_pair_count')}`",
        "",
        "## Gate checks",
        "",
        "| check | passed |",
        "| --- | --- |",
    ]
    checks = report.get("checks") if isinstance(report.get("checks"), Mapping) else {}
    for key, value in checks.items():
        lines.append(f"| {key} | `{value}` |")
    lines.extend(
        [
            "",
            "## No-tuning policy",
            "",
            "CTP30 is a sealed validation run. Its results must be retained as observed and must not be used to tune prompts, agents, tools, budget rules, weather data, or scheduling logic.",
        ]
    )
    return "\n".join(lines) + "\n"


def _runtime_config(args: argparse.Namespace) -> Dict[str, Any]:
    base_url = args.base_url or os.getenv("LLM_BASE_URL") or settings.llm.base_url
    model = args.model or os.getenv("LLM_MODEL") or settings.llm.model
    api_key_configured = bool(os.getenv("LLM_API_KEY") or settings.llm.api_key)
    return {
        "schema_version": "ctp30-sealed-runtime-config-v1",
        "provider": _llm_provider_from_base_url(str(base_url)),
        "base_url": str(base_url),
        "model": str(model),
        "api_configured": api_key_configured,
        "temperature": float(args.temperature),
        "max_tokens": int(args.max_tokens),
        "timeout_seconds": int(args.timeout_seconds),
        "hard_timeout_seconds": int(args.hard_timeout_seconds),
        "retry_max_attempts": int(args.retry_max_attempts),
        "reasoning_effort": str(args.reasoning_effort),
        "method_order_seed": int(args.method_order_seed),
        "methods": list(CTP30_SEALED_METHODS),
        "expected_raw_result_count": CTP30_EXPECTED_RESULTS,
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
        "EXPERIMENT_RESULT_HARD_TIMEOUT_SECONDS": str(runtime_config.get("hard_timeout_seconds")),
        "EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER": "true",
    }


def _case_method_grid(
    results: Iterable[Mapping[str, Any]],
    *,
    expected_case_ids: Iterable[str],
    expected_methods: Iterable[str],
) -> Dict[str, Any]:
    cases = list(expected_case_ids)
    methods = list(expected_methods)
    counts: Dict[tuple[str, str], int] = defaultdict(int)
    for result in results:
        case_id = str(result.get("case_id") or result.get("scenario_id") or "")
        method = str(result.get("method") or "")
        counts[(case_id, method)] += 1
    missing = [
        {"case_id": case_id, "method": method}
        for case_id in cases
        for method in methods
        if counts[(case_id, method)] == 0
    ]
    duplicates = [
        {"case_id": case_id, "method": method, "count": count}
        for (case_id, method), count in sorted(counts.items())
        if case_id in cases and method in methods and count > 1
    ]
    unexpected = [
        {"case_id": case_id, "method": method, "count": count}
        for (case_id, method), count in sorted(counts.items())
        if case_id not in cases or method not in methods
    ]
    return {
        "expected_case_count": len(cases),
        "expected_methods": methods,
        "expected_result_count": len(cases) * len(methods),
        "missing_count": len(missing),
        "duplicate_count": len(duplicates),
        "unexpected_count": len(unexpected),
        "missing": missing,
        "duplicates": duplicates,
        "unexpected": unexpected,
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


def _api_clean_pair_summary(
    results: List[Dict[str, Any]],
    *,
    failure_classification: Mapping[str, Any],
    expected_case_ids: Sequence[str],
) -> Dict[str, Any]:
    api_polluted = set()
    for item in failure_classification.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        if item.get("method") not in CTP30_SEALED_METHODS:
            continue
        if int(item.get("terminal_api_failure_count") or 0) <= 0:
            continue
        case_id = str(item.get("case_id") or item.get("scenario_id") or "")
        if case_id:
            api_polluted.add(case_id)
    clean = [case_id for case_id in expected_case_ids if case_id not in api_polluted]
    return {
        "total_pair_count": len(expected_case_ids),
        "api_polluted_pair_count": len(api_polluted),
        "clean_pair_count": len(clean),
        "minimum_clean_pair_count": 25,
        "excluded_api_polluted_pairs": sorted(api_polluted),
    }


def _trace_audit(run_dir: Path, traces: List[Dict[str, Any]], *, result_count: int) -> Dict[str, Any]:
    llm_calls = [
        call
        for trace in traces
        for call in (trace.get("llm_calls") or [])
        if isinstance(call, Mapping)
    ]
    worker_dir = run_dir / "worker_io"
    request_count = len(list(worker_dir.glob("*.request.json"))) if worker_dir.exists() else 0
    response_count = len(list(worker_dir.glob("*.response.json"))) if worker_dir.exists() else 0
    return {
        "trace_file_count": len(traces),
        "result_count": result_count,
        "llm_call_count": len(llm_calls),
        "mock_call_count": sum(1 for call in llm_calls if call.get("mock") or call.get("mock_used")),
        "fallback_call_count": sum(
            1 for call in llm_calls if call.get("fallback") or call.get("fallback_used")
        ),
        "worker_request_count": request_count,
        "worker_response_count": response_count,
    }


def _attach_sealed_metadata_to_manifest(
    run_dir: Path,
    *,
    report: Mapping[str, Any],
    preflight: Mapping[str, Any],
    frozen_ctp100_commit: str,
) -> None:
    manifest_path = run_dir / SEALED_MANIFEST_NAME
    manifest = _read_json_object(manifest_path)
    manifest["sealed_validation"] = {
        "schema_version": CTP30_SEALED_SCHEMA_VERSION,
        "status": report.get("status"),
        "direction_supported": report.get("direction_supported"),
        "gate_path": (run_dir / SEALED_GATE_NAME).as_posix(),
        "report_path": (run_dir / SEALED_REPORT_NAME).as_posix(),
        "preflight_path": (run_dir / SEALED_PREFLIGHT_NAME).as_posix(),
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
            "sealed_validation_preflight": (run_dir / SEALED_PREFLIGHT_NAME).as_posix(),
            "sealed_validation_gate": (run_dir / SEALED_GATE_NAME).as_posix(),
            "sealed_validation_report": (run_dir / SEALED_REPORT_NAME).as_posix(),
        }
    )
    manifest["results"] = results
    _write_json(manifest_path, manifest)


def _write_sealed_report(run_dir: Path, report: Mapping[str, Any]) -> None:
    _write_json(run_dir / SEALED_GATE_NAME, report)
    (run_dir / SEALED_REPORT_NAME).write_text(
        render_sealed_validation_report(report),
        encoding="utf-8",
    )


def _sealed_artifact_files(run_dir: Path, benchmark_path: str | Path) -> Dict[str, str | Path]:
    return {
        "sealed_benchmark_source": Path(benchmark_path),
        "sealed_preflight": SEALED_PREFLIGHT_NAME,
        "benchmark_results_csv": "benchmark_results.csv",
        "benchmark_results_json": "benchmark_results.json",
        "benchmark_results_checkpoint_csv": "benchmark_results.checkpoint.csv",
        "benchmark_results_checkpoint_json": "benchmark_results.checkpoint.json",
        "evaluation_summary": "evaluation_summary.json",
        "paper_tables": "paper_tables.md",
        "sealed_validation_manifest": SEALED_MANIFEST_NAME,
        "benchmark_resume_state": "benchmark_resume_state.json",
        "sealed_validation_gate": SEALED_GATE_NAME,
        "sealed_validation_report": SEALED_REPORT_NAME,
    }


def _sealed_artifact_paths(run_dir: Path) -> Dict[str, str]:
    return {
        "preflight": (run_dir / SEALED_PREFLIGHT_NAME).as_posix(),
        "benchmark_results_json": (run_dir / "benchmark_results.json").as_posix(),
        "benchmark_results_csv": (run_dir / "benchmark_results.csv").as_posix(),
        "evaluation_summary": (run_dir / "evaluation_summary.json").as_posix(),
        "paper_tables": (run_dir / "paper_tables.md").as_posix(),
        "manifest": (run_dir / SEALED_MANIFEST_NAME).as_posix(),
        "checkpoint_json": (run_dir / "benchmark_results.checkpoint.json").as_posix(),
        "checkpoint_csv": (run_dir / "benchmark_results.checkpoint.csv").as_posix(),
        "resume_state": (run_dir / "benchmark_resume_state.json").as_posix(),
        "traces": (run_dir / "traces").as_posix(),
        "worker_io": (run_dir / "worker_io").as_posix(),
        "gate": (run_dir / SEALED_GATE_NAME).as_posix(),
        "report": (run_dir / SEALED_REPORT_NAME).as_posix(),
        "final_artifact_index": (run_dir / "final_artifact_index.json").as_posix(),
    }


def _payload(
    run_id: str,
    run_dir: Path,
    report: Mapping[str, Any],
    *,
    final_index: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "status": report.get("status"),
        "run_id": run_id,
        "output_dir": run_dir.as_posix(),
        "result_count": (report.get("results") or {}).get("actual_result_count")
        if isinstance(report.get("results"), Mapping)
        else None,
        "expected_count": CTP30_EXPECTED_RESULTS,
        "direction_supported": report.get("direction_supported"),
        "sealed_gate": (run_dir / SEALED_GATE_NAME).as_posix(),
        "sealed_report": (run_dir / SEALED_REPORT_NAME).as_posix(),
        "manifest": (run_dir / SEALED_MANIFEST_NAME).as_posix(),
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


def _resolve_run_output_dir(output_dir: str | Path, run_id: str) -> Path:
    root = Path(output_dir)
    return root if root.name == run_id else root / run_id


def _cases_from_document(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    cases = document.get("cases") if isinstance(document.get("cases"), list) else []
    return [case for case in cases if isinstance(case, dict)]


def _case_ids(cases: Iterable[Mapping[str, Any]]) -> List[str]:
    return [
        str(case.get("case_id") or case.get("scenario_id") or case.get("id") or "")
        for case in cases
    ]


def _turn_count(cases: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    for case in cases:
        turns = case.get("turns")
        count += len(turns) if isinstance(turns, list) else 1
    return count


def _protected_core_hash_audit(frozen_commit: str) -> Dict[str, Any]:
    if not frozen_commit:
        return {"status": "skipped", "reason": "no frozen commit supplied"}
    paths = _git_ls_tree(frozen_commit, PROTECTED_CORE_PATHS)
    if paths is None:
        return {"status": "failed", "error": f"cannot inspect frozen commit: {frozen_commit}"}
    changed_paths = _git_diff_name_only(frozen_commit, PROTECTED_CORE_PATHS)
    if changed_paths is None:
        return {"status": "failed", "error": f"cannot diff frozen commit: {frozen_commit}"}
    mismatches = []
    missing_current = []
    missing_frozen = []
    compared = 0
    for relative_path in paths:
        current_path = ROOT / relative_path
        frozen_bytes = _git_show_bytes(frozen_commit, relative_path)
        if frozen_bytes is None:
            missing_frozen.append(relative_path)
            continue
        if not current_path.exists():
            missing_current.append(relative_path)
            continue
        current_sha = _bytes_sha256(_canonical_bytes_for_hash(current_path.read_bytes()))
        frozen_sha = _bytes_sha256(_canonical_bytes_for_hash(frozen_bytes))
        compared += 1
        if current_sha != frozen_sha:
            mismatches.append(
                {
                    "path": relative_path,
                    "current_sha256": current_sha,
                    "frozen_sha256": frozen_sha,
                }
            )
    errors = []
    if missing_current:
        errors.append("missing_current_files")
    if missing_frozen:
        errors.append("missing_frozen_files")
    if changed_paths:
        errors.append("git_diff_detected_protected_changes")
    if mismatches:
        errors.append("hash_mismatch")
    return {
        "schema_version": "ctp30-protected-core-hash-audit-v1",
        "status": "passed" if not errors else "failed",
        "frozen_commit": frozen_commit,
        "protected_paths": list(PROTECTED_CORE_PATHS),
        "compared_file_count": compared,
        "git_diff_changed_path_count": len(changed_paths),
        "mismatch_count": len(mismatches),
        "missing_current_count": len(missing_current),
        "missing_frozen_count": len(missing_frozen),
        "errors": errors,
        "sample_git_diff_changed_paths": changed_paths[:10],
        "sample_mismatches": mismatches[:10],
        "sample_missing_current": missing_current[:10],
        "sample_missing_frozen": missing_frozen[:10],
    }


def _git_ls_tree(commit: str, paths: Sequence[str]) -> Optional[List[str]]:
    try:
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", commit, "--", *paths],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _git_show_bytes(commit: str, relative_path: str) -> Optional[bytes]:
    try:
        result = subprocess.run(
            ["git", "show", f"{commit}:{relative_path}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout


def _git_diff_name_only(commit: str, paths: Sequence[str]) -> Optional[List[str]]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", commit, "--", *paths],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _canonical_bytes_for_hash(value: bytes) -> bytes:
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        return value
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _read_json_object(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _raise_preflight_error(preflight: Mapping[str, Any]) -> None:
    errors = preflight.get("errors") if isinstance(preflight.get("errors"), list) else []
    details = "\n".join(f"- {error}" for error in errors) or "- unknown preflight error"
    raise RuntimeError(f"CTP30 sealed validation preflight failed:\n{details}")


def _llm_provider_from_base_url(base_url: str) -> str:
    lowered = base_url.lower()
    if "vectorengine" in lowered:
        return "vectorengine_openai_compatible"
    if "openrouter" in lowered:
        return "openrouter_openai_compatible"
    if "openai" in lowered:
        return "openai"
    return "openai_compatible"


def _git_commit() -> Optional[str]:
    return _git_output(["git", "rev-parse", "HEAD"])


def _git_working_tree_clean() -> Optional[bool]:
    status = _git_output(["git", "status", "--short"])
    return None if status is None else status == ""


def _git_output(args: List[str]) -> Optional[str]:
    try:
        result = subprocess.run(
            args,
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _file_sha256(path: Path) -> str:
    digest = __import__("hashlib").sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bytes_sha256(value: bytes) -> str:
    return __import__("hashlib").sha256(value).hexdigest()


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
