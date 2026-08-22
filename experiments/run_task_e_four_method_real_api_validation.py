"""Run Task E: 20-case real-API joint validation for all four methods.

This is a pre-formal engineering gate.  It runs the same fixed 20 single-turn
cases used by Task D, but expands the method scope to M0-M3:

* M0: ``llm_direct``
* M1: ``single_agent``
* M2: ``fixed_multi_agent``
* M3: ``adaptive_multi_agent``

The output is intentionally separate from the formal CTP100 run.  A passed
Task E report means the four-method pipeline can run with the real
OpenAI-compatible middleman API, save traces, record token/latency/cost
evidence, and keep the M0-M3 result grid complete on a small controlled subset.
It must not be reported as the paper's formal comparison result.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.core.experiment_runner import ExperimentRunner
from app.core.fixed_data import CANONICAL_JSON_SHA256_STRATEGY, canonical_json_sha256
from app.core.formal_experiment_preflight import load_benchmark_document
from app.core.llm.client import llm_provider_from_base_url
from experiments.run_task_d_m0_real_api_validation import (
    TASK_D_CASE_IDS,
    _cost_summary,
    _float_or_none,
    _latency_summary,
    _llm_calls,
    _load_trace_records,
    _parse_case_ids,
    _resolve_run_output_dir,
    _retry_attempts,
    _temporary_env,
    _token_totals,
    _write_json,
)


TASK_E_SCHEMA_VERSION = "ctp-task-e-four-method-real-api-validation-v1"
TASK_E_BENCHMARK_SCHEMA_VERSION = "ctp-task-e-four-method-real-api-benchmark-v1"
TASK_E_DATASET_ID = "task_e_four_method_real_api_20"
TASK_E_DATASET_VERSION = "2026-08-21-task-e-four-method-real-api-v1"
TASK_E_METHODS = (
    "llm_direct",
    "single_agent",
    "fixed_multi_agent",
    "adaptive_multi_agent",
)
TASK_E_METHOD_LABELS = {
    "llm_direct": "M0",
    "single_agent": "M1",
    "fixed_multi_agent": "M2",
    "adaptive_multi_agent": "M3",
}
TASK_E_SUCCESS_STATUSES = {"completed", "clarification"}
DEFAULT_SOURCE_BENCHMARK_PATH = ROOT / "experiments" / "ctp100_formal_v2.json"
DEFAULT_OUTPUT_ROOT = ROOT / "experiments" / "results" / "task_e_four_method_real_api"
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_HARD_TIMEOUT_SECONDS = 600
DEFAULT_MAX_TOKENS = 4096
DEFAULT_RETRY_MAX_ATTEMPTS = 3
DEFAULT_REASONING_EFFORT = "minimal"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_METHOD_ORDER_SEED = 20260821
TASK_E_REPORT_JSON_NAME = "task_e_four_method_real_api_report.json"
TASK_E_REPORT_MD_NAME = "task_e_four_method_real_api_report.md"
TASK_E_BENCHMARK_FILE_NAME = "task_e_four_method_real_api_20_benchmark.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-benchmark", type=Path, default=DEFAULT_SOURCE_BENCHMARK_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--base-url", type=str, default=None)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--hard-timeout", type=int, default=DEFAULT_HARD_TIMEOUT_SECONDS)
    parser.add_argument("--retry-max-attempts", type=int, default=DEFAULT_RETRY_MAX_ATTEMPTS)
    parser.add_argument("--reasoning-effort", type=str, default=DEFAULT_REASONING_EFFORT)
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--method-order-seed", type=int, default=DEFAULT_METHOD_ORDER_SEED)
    parser.add_argument(
        "--case-ids",
        type=str,
        default=None,
        help=(
            "Optional comma-separated case ids for targeted reruns. "
            "Omit to run the fixed 20-case Task E subset."
        ),
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--allow-missing-config",
        action="store_true",
        help="Write the 20-case benchmark and a skipped report when no LLM API key is configured.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only write the 20-case benchmark and skipped report; do not call the LLM.",
    )
    args = parser.parse_args()

    run_id = args.run_id or f"task_e_four_method_real_api_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = _resolve_run_output_dir(args.output_dir, run_id)
    if run_dir.exists() and any(run_dir.iterdir()) and not args.resume:
        raise RuntimeError(f"Task E output directory is not empty: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)

    case_ids = _parse_case_ids(args.case_ids) or TASK_D_CASE_IDS
    benchmark_document = build_task_e_benchmark(args.source_benchmark, case_ids=case_ids)
    benchmark_path = run_dir / TASK_E_BENCHMARK_FILE_NAME
    _write_json(benchmark_path, benchmark_document)

    runtime = _resolve_runtime_config(
        base_url=args.base_url,
        model=args.model,
        max_tokens=args.max_tokens,
        timeout_seconds=args.timeout,
        hard_timeout_seconds=args.hard_timeout,
        retry_max_attempts=args.retry_max_attempts,
        reasoning_effort=args.reasoning_effort,
        temperature=args.temperature,
        method_order_seed=args.method_order_seed,
    )
    if not runtime["api_key_configured"] or args.dry_run:
        report = build_task_e_report(
            run_id=run_id,
            run_dir=run_dir,
            benchmark_path=benchmark_path,
            benchmark_document=benchmark_document,
            runtime_config=runtime,
            results=[],
            elapsed_seconds=0.0,
            skipped_reason=(
                "dry_run_requested" if args.dry_run else "missing_llm_api_key"
            ),
        )
        _write_task_e_report(run_dir, report)
        print(json.dumps(_payload(run_id, run_dir, benchmark_path, report), ensure_ascii=False, indent=2))
        return 0 if args.dry_run or args.allow_missing_config else 2

    started = time.perf_counter()
    env = _task_e_env_values(runtime)
    with _temporary_env(env):
        runner = ExperimentRunner(
            trace_dir=run_dir / "traces",
            output_dir=run_dir,
            repeats=1,
            run_id=run_id,
            model_config_name="task-e-four-method-real-api",
            method_order_seed=args.method_order_seed,
        )
        results = runner.run_benchmark(
            benchmark_path,
            methods=TASK_E_METHODS,
            repeats=1,
            run_id=run_id,
            model_config_name="task-e-four-method-real-api",
            resume=args.resume,
        )
    elapsed_seconds = round(time.perf_counter() - started, 3)
    report = build_task_e_report(
        run_id=run_id,
        run_dir=run_dir,
        benchmark_path=benchmark_path,
        benchmark_document=benchmark_document,
        runtime_config=runtime,
        results=results,
        elapsed_seconds=elapsed_seconds,
    )
    _write_task_e_report(run_dir, report)
    print(json.dumps(_payload(run_id, run_dir, benchmark_path, report), ensure_ascii=False, indent=2))
    return 0 if report["gate"]["status"] == "passed" else 1


def build_task_e_benchmark(
    source_benchmark_path: str | Path,
    *,
    case_ids: Iterable[str] = TASK_D_CASE_IDS,
) -> Dict[str, Any]:
    source_path = Path(source_benchmark_path)
    source_document, source_cases = load_benchmark_document(source_path)
    source_case_map = {
        str(case.get("case_id") or case.get("scenario_id") or case.get("id") or ""): case
        for case in source_cases
        if isinstance(case, Mapping)
    }
    selected: List[Dict[str, Any]] = []
    missing: List[str] = []
    scenario_ids: List[str] = []
    selected_case_ids = tuple(str(case_id).strip() for case_id in case_ids if str(case_id).strip())
    if not selected_case_ids:
        raise ValueError("Task E case_ids must not be empty")
    for case_id in selected_case_ids:
        case = source_case_map.get(case_id)
        if case is None:
            missing.append(case_id)
            continue
        if isinstance(case.get("turns"), list) and case.get("turns"):
            scenario_ids.append(case_id)
            continue
        selected.append(json.loads(json.dumps(case, ensure_ascii=False)))
    if missing:
        raise ValueError(f"Task E source benchmark missing case ids: {', '.join(missing)}")
    if scenario_ids:
        raise ValueError(
            "Task E four-method validation uses single-turn cases only; scenario ids: "
            + ", ".join(scenario_ids)
        )
    if len(selected) != len(selected_case_ids):
        raise ValueError(
            f"Task E selected {len(selected)} cases, expected {len(selected_case_ids)}"
        )
    task_type_counts = Counter(str(case.get("task_type") or "unknown") for case in selected)
    source_metadata = source_document if isinstance(source_document, Mapping) else {}
    return {
        "schema_version": TASK_E_BENCHMARK_SCHEMA_VERSION,
        "dataset_id": TASK_E_DATASET_ID,
        "dataset_version": TASK_E_DATASET_VERSION,
        "dataset_role": "pre_formal_four_method_real_api_joint_validation",
        "language": "zh-CN",
        "method_scope": list(TASK_E_METHODS),
        "case_count": len(selected),
        "turn_count": len(selected),
        "expected_raw_result_count": len(selected) * len(TASK_E_METHODS),
        "source_benchmark": {
            "path": source_path.as_posix(),
            "dataset_id": source_metadata.get("dataset_id"),
            "dataset_version": source_metadata.get("dataset_version"),
            "dataset_sha256": canonical_json_sha256(source_document),
            "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
        },
        "selection_policy": {
            "fixed_case_ids": list(selected_case_ids),
            "random_sampling": False,
            "single_turn_only": True,
            "method_scope": list(TASK_E_METHODS),
            "purpose": (
                "Real-API joint validation for M0-M3 before the formal run; "
                "not used as a paper-level method comparison result."
            ),
            "coverage": {
                "task_type_counts": dict(sorted(task_type_counts.items())),
                "weather_scope": ["full", "partial", "out_of_range", "no_date"],
                "budget_scope": ["destination_local_only", "supported_intercity", "unsupported_intercity"],
                "method_grid": "20 cases x 4 methods = 80 raw method results",
            },
        },
        "cases": selected,
    }


def build_task_e_report(
    *,
    run_id: str,
    run_dir: Path,
    benchmark_path: Path,
    benchmark_document: Mapping[str, Any],
    runtime_config: Mapping[str, Any],
    results: List[Dict[str, Any]],
    elapsed_seconds: float,
    skipped_reason: Optional[str] = None,
) -> Dict[str, Any]:
    traces = _load_trace_records(run_dir / "traces")
    llm_calls = _llm_calls(traces)
    expected_methods = list(benchmark_document.get("method_scope") or TASK_E_METHODS)
    expected_case_ids = list(
        ((benchmark_document.get("selection_policy") or {}).get("fixed_case_ids"))
        or TASK_D_CASE_IDS
    )
    expected_result_count = int(
        benchmark_document.get("expected_raw_result_count")
        or len(expected_case_ids) * len(expected_methods)
    )
    status_counts = Counter(str(result.get("status") or "unknown") for result in results)
    method_counts = Counter(str(result.get("method") or "unknown") for result in results)
    result_methods = sorted({str(result.get("method") or "") for result in results})
    failed_results = _failed_results(results)
    grid = _method_grid(results, expected_case_ids=expected_case_ids, expected_methods=expected_methods)
    provider_counts = Counter(str(call.get("provider") or "unknown") for call in llm_calls)
    prompt_version_counts = Counter(str(call.get("prompt_version") or "unknown") for call in llm_calls)
    llm_calls_by_method = _llm_calls_by_method(traces)
    tool_calls_by_method = _tool_calls_by_method(traces)
    agent_runs_by_method = _agent_runs_by_method(traces)
    mock_call_count = sum(1 for call in llm_calls if call.get("mock") or call.get("mock_used"))
    fallback_call_count = sum(1 for call in llm_calls if call.get("fallback") or call.get("fallback_used"))
    failed_llm_call_count = sum(1 for call in llm_calls if call.get("success") is False)
    retry_error_count = sum(
        int(_float_or_none(call.get("retry_error_count")) or 0) for call in llm_calls
    )
    hard_timeout_triggered_count = sum(
        1 for result in results if bool(result.get("hard_timeout_triggered"))
    )
    length_finish_count = sum(
        1
        for attempt in _retry_attempts(llm_calls)
        if str(attempt.get("finish_reason") or "").lower() in {"length", "max_tokens"}
    )
    token_totals = _token_totals(llm_calls)
    latency = _latency_summary(results, llm_calls)
    cost = _cost_summary(llm_calls)
    all_m0_traces_have_no_tools = all(
        not trace.get("tool_calls")
        and int(_float_or_none(trace.get("tool_call_count")) or 0) == 0
        for trace in traces
        if trace.get("method") == "llm_direct"
    )
    multi_agent_evidence = {
        method: {
            "agent_run_count": agent_runs_by_method.get(method, 0),
            "tool_call_count": tool_calls_by_method.get(method, 0),
            "llm_call_count": llm_calls_by_method.get(method, 0),
        }
        for method in ("single_agent", "fixed_multi_agent", "adaptive_multi_agent")
    }
    warnings = []
    if failed_llm_call_count:
        warnings.append(
            {
                "code": "failed_llm_calls_recorded",
                "count": failed_llm_call_count,
                "meaning": (
                    "At least one internal LLM call failed after retries, but "
                    "Task E treats this as a provider-stability warning when "
                    "the result grid has no failed result and no hard timeout."
                ),
            }
        )
    if retry_error_count:
        warnings.append(
            {
                "code": "llm_retry_errors_recorded",
                "count": retry_error_count,
                "meaning": (
                    "Retryable API errors or network timeouts occurred and were "
                    "recorded in trace evidence."
                ),
            }
        )
    checks = {
        "not_skipped": skipped_reason is None,
        "expected_result_count": len(results) == expected_result_count,
        "all_four_methods_present": set(result_methods) == set(expected_methods),
        "method_grid_complete": grid["missing_count"] == 0 and grid["duplicate_count"] == 0,
        "all_results_completed": len(results) == expected_result_count and not failed_results,
        "trace_count_matches_results": len(traces) == len(results) if results else skipped_reason is not None,
        "llm_calls_recorded": bool(llm_calls) if results else skipped_reason is not None,
        "llm_calls_cover_all_methods": all(
            llm_calls_by_method.get(method, 0) > 0 for method in expected_methods
        )
        if results
        else skipped_reason is not None,
        "m0_zero_tool_calls": all_m0_traces_have_no_tools if results else skipped_reason is not None,
        "m1_m2_m3_have_agent_or_tool_evidence": all(
            multi_agent_evidence[method]["agent_run_count"] > 0
            or multi_agent_evidence[method]["tool_call_count"] > 0
            for method in ("single_agent", "fixed_multi_agent", "adaptive_multi_agent")
        )
        if results
        else skipped_reason is not None,
        "no_mock_calls": mock_call_count == 0,
        "no_fallback_calls": fallback_call_count == 0,
        "no_hard_timeout": hard_timeout_triggered_count == 0,
        "provider_recorded": bool(provider_counts) if results else skipped_reason is not None,
        "token_usage_recorded": token_totals["total_tokens"] is not None if results else skipped_reason is not None,
        "latency_recorded": latency["result_latency_ms_total"] is not None if results else skipped_reason is not None,
        "cost_accounting_recorded": cost["standardized_estimated_cost_total"] is not None if results else skipped_reason is not None,
        "no_length_finish_reason": length_finish_count == 0,
    }
    failed_checks = [key for key, passed in checks.items() if not passed]
    status = "skipped" if skipped_reason else ("passed" if not failed_checks else "failed")
    return {
        "schema_version": TASK_E_SCHEMA_VERSION,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "run_id": run_id,
        "task": "Task E - four-method 20-case real API joint validation",
        "status": status,
        "skipped_reason": skipped_reason,
        "gate": {
            "status": status,
            "checks": checks,
            "failed_checks": failed_checks,
            "warnings": warnings,
            "paper_claim_policy": (
                "This run is a pre-formal runtime validation gate only. It must not "
                "be reported as the paper's formal M0-M3 comparison result."
            ),
        },
        "benchmark": {
            "path": benchmark_path.as_posix(),
            "dataset_id": benchmark_document.get("dataset_id"),
            "dataset_version": benchmark_document.get("dataset_version"),
            "case_count": benchmark_document.get("case_count"),
            "turn_count": benchmark_document.get("turn_count"),
            "expected_raw_result_count": expected_result_count,
            "selected_case_ids": expected_case_ids,
            "task_type_counts": (
                ((benchmark_document.get("selection_policy") or {}).get("coverage") or {})
                .get("task_type_counts", {})
            ),
        },
        "runtime_config": dict(runtime_config),
        "results": {
            "expected_result_count": expected_result_count,
            "actual_result_count": len(results),
            "status_counts": dict(sorted(status_counts.items())),
            "method_counts": dict(sorted(method_counts.items())),
            "methods": result_methods,
            "failed_results": failed_results,
            "hard_timeout_triggered_count": hard_timeout_triggered_count,
            "elapsed_seconds": elapsed_seconds,
        },
        "method_grid": grid,
        "trace_audit": {
            "trace_file_count": len(traces),
            "llm_call_count": len(llm_calls),
            "llm_calls_by_method": dict(sorted(llm_calls_by_method.items())),
            "tool_calls_by_method": dict(sorted(tool_calls_by_method.items())),
            "agent_runs_by_method": dict(sorted(agent_runs_by_method.items())),
            "provider_counts": dict(sorted(provider_counts.items())),
            "prompt_version_counts": dict(sorted(prompt_version_counts.items())),
            "mock_call_count": mock_call_count,
            "fallback_call_count": fallback_call_count,
            "failed_llm_call_count": failed_llm_call_count,
            "retry_error_count": retry_error_count,
            "length_finish_reason_attempt_count": length_finish_count,
            "multi_agent_evidence": multi_agent_evidence,
        },
        "warnings": warnings,
        "token_usage": token_totals,
        "latency": latency,
        "cost": cost,
        "artifacts": _task_e_artifact_paths(run_dir),
    }


def render_task_e_report(report: Mapping[str, Any]) -> str:
    gate = report.get("gate") if isinstance(report.get("gate"), Mapping) else {}
    results = report.get("results") if isinstance(report.get("results"), Mapping) else {}
    trace = report.get("trace_audit") if isinstance(report.get("trace_audit"), Mapping) else {}
    runtime = report.get("runtime_config") if isinstance(report.get("runtime_config"), Mapping) else {}
    artifacts = report.get("artifacts") if isinstance(report.get("artifacts"), Mapping) else {}
    warnings = report.get("warnings") if isinstance(report.get("warnings"), list) else []
    lines = [
        "# Task E Four-Method Real API Validation Report",
        "",
        f"- status: `{report.get('status')}`",
        f"- run_id: `{report.get('run_id')}`",
        f"- expected_result_count: `{results.get('expected_result_count')}`",
        f"- actual_result_count: `{results.get('actual_result_count')}`",
        f"- result_status_counts: `{results.get('status_counts')}`",
        f"- method_counts: `{results.get('method_counts')}`",
        f"- provider: `{runtime.get('provider')}`",
        f"- model: `{runtime.get('model')}`",
        f"- max_tokens: `{runtime.get('max_tokens')}`",
        f"- timeout_seconds: `{runtime.get('timeout_seconds')}`",
        f"- hard_timeout_seconds: `{runtime.get('hard_timeout_seconds')}`",
        f"- llm_call_count: `{trace.get('llm_call_count')}`",
        f"- llm_calls_by_method: `{trace.get('llm_calls_by_method')}`",
        f"- tool_calls_by_method: `{trace.get('tool_calls_by_method')}`",
        f"- agent_runs_by_method: `{trace.get('agent_runs_by_method')}`",
        f"- mock_call_count: `{trace.get('mock_call_count')}`",
        f"- fallback_call_count: `{trace.get('fallback_call_count')}`",
        f"- failed_llm_call_count: `{trace.get('failed_llm_call_count')}`",
        f"- retry_error_count: `{trace.get('retry_error_count')}`",
        f"- hard_timeout_triggered_count: `{results.get('hard_timeout_triggered_count')}`",
        "",
        "## Gate checks",
        "",
        "| check | passed |",
        "|---|---:|",
    ]
    checks = gate.get("checks") if isinstance(gate.get("checks"), Mapping) else {}
    for key, passed in checks.items():
        lines.append(f"| {key} | `{passed}` |")
    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            if not isinstance(warning, Mapping):
                continue
            lines.append(
                f"- `{warning.get('code')}` count=`{warning.get('count')}`: "
                f"{warning.get('meaning')}"
            )
    failed_results = results.get("failed_results") if isinstance(results.get("failed_results"), list) else []
    if failed_results:
        lines.extend(["", "## Failed results", ""])
        for item in failed_results:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                f"- `{item.get('case_id')}` / `{item.get('method')}` "
                f"status=`{item.get('status')}`, hard_timeout=`{item.get('hard_timeout_triggered')}`, "
                f"error=`{item.get('error')}`"
            )
    grid = report.get("method_grid") if isinstance(report.get("method_grid"), Mapping) else {}
    if grid.get("missing") or grid.get("duplicates"):
        lines.extend(
            [
                "",
                "## Method-grid issues",
                "",
                f"- missing: `{grid.get('missing') or []}`",
                f"- duplicates: `{grid.get('duplicates') or []}`",
            ]
        )
    lines.extend(["", "## Artifacts", "", "| artifact | path |", "|---|---|"])
    for key, path in artifacts.items():
        lines.append(f"| {key} | `{path}` |")
    return "\n".join(lines) + "\n"


def _resolve_runtime_config(
    *,
    base_url: Optional[str],
    model: Optional[str],
    max_tokens: int,
    timeout_seconds: int,
    hard_timeout_seconds: int,
    retry_max_attempts: int,
    reasoning_effort: str,
    temperature: float,
    method_order_seed: int,
) -> Dict[str, Any]:
    resolved_base_url = str(base_url or os.getenv("LLM_BASE_URL") or settings.llm.base_url)
    resolved_model = str(model or os.getenv("LLM_MODEL") or settings.llm.model)
    return {
        "schema_version": "ctp-task-e-runtime-config-v1",
        "provider": llm_provider_from_base_url(resolved_base_url),
        "base_url": resolved_base_url,
        "model": resolved_model,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "timeout_seconds": int(timeout_seconds),
        "hard_timeout_seconds": int(hard_timeout_seconds),
        "retry_max_attempts": int(retry_max_attempts),
        "reasoning_effort": str(reasoning_effort or "").strip().lower() or None,
        "strict_mode": True,
        "cache_disabled": True,
        "trace_save_user_message": False,
        "api_key_configured": bool(os.getenv("LLM_API_KEY") or settings.llm.api_key),
        "mock_fallback_allowed": False,
        "methods": list(TASK_E_METHODS),
        "method_order_seed": int(method_order_seed),
        "expected_raw_result_count": len(TASK_D_CASE_IDS) * len(TASK_E_METHODS),
    }


def _task_e_env_values(runtime_config: Mapping[str, Any]) -> Dict[str, str]:
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


def _failed_results(results: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    failed: List[Dict[str, Any]] = []
    for result in results:
        if (
            str(result.get("status") or "").lower() in TASK_E_SUCCESS_STATUSES
            and not result.get("error")
            and not bool(result.get("hard_timeout_triggered"))
        ):
            continue
        failed.append(
            {
                "case_id": result.get("case_id"),
                "method": result.get("method"),
                "status": result.get("status"),
                "error": result.get("error"),
                "hard_timeout_triggered": bool(result.get("hard_timeout_triggered")),
            }
        )
    return failed


def _method_grid(
    results: Iterable[Mapping[str, Any]],
    *,
    expected_case_ids: Iterable[str],
    expected_methods: Iterable[str],
) -> Dict[str, Any]:
    expected_cases = list(expected_case_ids)
    methods = list(expected_methods)
    counts: Dict[tuple[str, str], int] = defaultdict(int)
    for result in results:
        case_id = str(result.get("case_id") or result.get("scenario_id") or "")
        method = str(result.get("method") or "")
        counts[(case_id, method)] += 1
    missing = [
        {"case_id": case_id, "method": method}
        for case_id in expected_cases
        for method in methods
        if counts[(case_id, method)] == 0
    ]
    duplicates = [
        {"case_id": case_id, "method": method, "count": count}
        for (case_id, method), count in sorted(counts.items())
        if case_id in expected_cases and method in methods and count > 1
    ]
    return {
        "expected_case_count": len(expected_cases),
        "expected_methods": methods,
        "expected_result_count": len(expected_cases) * len(methods),
        "missing_count": len(missing),
        "duplicate_count": len(duplicates),
        "missing": missing,
        "duplicates": duplicates,
    }


def _llm_calls_by_method(traces: Iterable[Mapping[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for trace in traces:
        method = str(trace.get("method") or "unknown")
        counts[method] += len([call for call in trace.get("llm_calls") or [] if isinstance(call, dict)])
    return counts


def _tool_calls_by_method(traces: Iterable[Mapping[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for trace in traces:
        method = str(trace.get("method") or "unknown")
        counts[method] += len([call for call in trace.get("tool_calls") or [] if isinstance(call, dict)])
    return counts


def _agent_runs_by_method(traces: Iterable[Mapping[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for trace in traces:
        method = str(trace.get("method") or "unknown")
        counts[method] += len([run for run in trace.get("agent_runs") or [] if isinstance(run, dict)])
    return counts


def _write_task_e_report(run_dir: Path, report: Dict[str, Any]) -> None:
    _write_json(run_dir / TASK_E_REPORT_JSON_NAME, report)
    (run_dir / TASK_E_REPORT_MD_NAME).write_text(
        render_task_e_report(report),
        encoding="utf-8",
    )


def _payload(
    run_id: str,
    run_dir: Path,
    benchmark_path: Path,
    report: Mapping[str, Any],
) -> Dict[str, Any]:
    return {
        "status": report.get("status"),
        "run_id": run_id,
        "output_dir": run_dir.as_posix(),
        "benchmark": benchmark_path.as_posix(),
        "report_json": (run_dir / TASK_E_REPORT_JSON_NAME).as_posix(),
        "report_md": (run_dir / TASK_E_REPORT_MD_NAME).as_posix(),
        "benchmark_results_json": (run_dir / "benchmark_results.json").as_posix(),
        "benchmark_results_csv": (run_dir / "benchmark_results.csv").as_posix(),
        "evaluation_summary": (run_dir / "evaluation_summary.json").as_posix(),
        "manifest": (run_dir / "experiment_manifest.json").as_posix(),
        "traces": (run_dir / "traces").as_posix(),
        "failed_checks": (report.get("gate") or {}).get("failed_checks") or [],
    }


def _task_e_artifact_paths(run_dir: Path) -> Dict[str, str]:
    return {
        "benchmark": (run_dir / TASK_E_BENCHMARK_FILE_NAME).as_posix(),
        "benchmark_results_json": (run_dir / "benchmark_results.json").as_posix(),
        "benchmark_results_csv": (run_dir / "benchmark_results.csv").as_posix(),
        "evaluation_summary": (run_dir / "evaluation_summary.json").as_posix(),
        "paper_tables": (run_dir / "paper_tables.md").as_posix(),
        "manifest": (run_dir / "experiment_manifest.json").as_posix(),
        "checkpoint_json": (run_dir / "benchmark_results.checkpoint.json").as_posix(),
        "checkpoint_csv": (run_dir / "benchmark_results.checkpoint.csv").as_posix(),
        "resume_state": (run_dir / "benchmark_resume_state.json").as_posix(),
        "traces": (run_dir / "traces").as_posix(),
        "report_json": (run_dir / TASK_E_REPORT_JSON_NAME).as_posix(),
        "report_md": (run_dir / TASK_E_REPORT_MD_NAME).as_posix(),
    }


@contextmanager
def task_e_env(runtime_config: Mapping[str, Any]) -> Iterator[None]:
    """Temporarily apply the strict Task E real-API runtime environment."""
    with _temporary_env(_task_e_env_values(runtime_config)):
        yield


if __name__ == "__main__":
    raise SystemExit(main())
