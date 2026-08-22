"""Run Task D: 20-case real-API stability validation for M0 only.

This is a pre-formal engineering gate.  It is intentionally lighter than the
paper-level four-method run: it runs only ``llm_direct`` on a fixed 20-case
subset, but it preserves the same ExperimentRunner result/trace/export path so
API failures, timeouts, token usage, latency, cost accounting, and provider
recording can be inspected before spending on the full benchmark.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
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


TASK_D_SCHEMA_VERSION = "ctp-task-d-m0-real-api-validation-v1"
TASK_D_BENCHMARK_SCHEMA_VERSION = "ctp-task-d-m0-real-api-benchmark-v1"
TASK_D_DATASET_ID = "task_d_m0_real_api_20"
TASK_D_DATASET_VERSION = "2026-08-21-task-d-m0-real-api-v1"
TASK_D_METHOD = "llm_direct"
DEFAULT_SOURCE_BENCHMARK_PATH = ROOT / "experiments" / "ctp100_formal_v2.json"
DEFAULT_OUTPUT_ROOT = ROOT / "experiments" / "results" / "task_d_m0_real_api"
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_HARD_TIMEOUT_SECONDS = 300
DEFAULT_MAX_TOKENS = 4096
DEFAULT_RETRY_MAX_ATTEMPTS = 3
DEFAULT_REASONING_EFFORT = "minimal"
DEFAULT_TEMPERATURE = 0.0
TASK_D_REPORT_JSON_NAME = "task_d_m0_real_api_report.json"
TASK_D_REPORT_MD_NAME = "task_d_m0_real_api_report.md"
TASK_D_BENCHMARK_FILE_NAME = "task_d_m0_real_api_20_benchmark.json"


TASK_D_CASE_IDS = (
    # Trip planning: no-date/no-origin, full weather, out-of-range weather.
    "ctp100_v2_001",
    "ctp100_v2_002",
    "ctp100_v2_014",
    "ctp100_v2_020",
    # Attraction recommendation.
    "ctp100_v2_021",
    "ctp100_v2_024",
    "ctp100_v2_030",
    # Weather query: full, partial, out-of-range.
    "ctp100_v2_031",
    "ctp100_v2_034",
    "ctp100_v2_037",
    # Budget query: no origin, supported rail, unsupported rail.
    "ctp100_v2_041",
    "ctp100_v2_042",
    "ctp100_v2_048",
    "ctp100_v2_050",
    # Clarification.
    "ctp100_v2_084",
    "ctp100_v2_088",
    "ctp100_v2_091",
    # General chat / non-tool requests.
    "ctp100_v2_038",
    "ctp100_v2_080",
    "ctp100_v2_093",
)


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
    parser.add_argument(
        "--case-ids",
        type=str,
        default=None,
        help=(
            "Optional comma-separated case ids for targeted reruns. "
            "Omit to run the fixed 20-case Task D subset."
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

    run_id = args.run_id or f"task_d_m0_real_api_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = _resolve_run_output_dir(args.output_dir, run_id)
    if run_dir.exists() and any(run_dir.iterdir()) and not args.resume:
        raise RuntimeError(f"Task D output directory is not empty: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)

    case_ids = _parse_case_ids(args.case_ids) or TASK_D_CASE_IDS
    benchmark_document = build_task_d_benchmark(args.source_benchmark, case_ids=case_ids)
    benchmark_path = run_dir / TASK_D_BENCHMARK_FILE_NAME
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
    )
    if not runtime["api_key_configured"] or args.dry_run:
        report = build_task_d_report(
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
        _write_task_d_report(run_dir, report)
        payload = _payload(run_id=run_id, run_dir=run_dir, benchmark_path=benchmark_path, report=report)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if args.dry_run or args.allow_missing_config else 2

    started = time.perf_counter()
    env = _task_d_env_values(runtime)
    with _temporary_env(env):
        runner = ExperimentRunner(
            trace_dir=run_dir / "traces",
            output_dir=run_dir,
            repeats=1,
            run_id=run_id,
            model_config_name="task-d-m0-real-api",
            method_order_seed=20260821,
        )
        results = runner.run_benchmark(
            benchmark_path,
            methods=[TASK_D_METHOD],
            repeats=1,
            run_id=run_id,
            model_config_name="task-d-m0-real-api",
            resume=args.resume,
        )
    elapsed_seconds = round(time.perf_counter() - started, 3)
    report = build_task_d_report(
        run_id=run_id,
        run_dir=run_dir,
        benchmark_path=benchmark_path,
        benchmark_document=benchmark_document,
        runtime_config=runtime,
        results=results,
        elapsed_seconds=elapsed_seconds,
    )
    _write_task_d_report(run_dir, report)
    payload = _payload(run_id=run_id, run_dir=run_dir, benchmark_path=benchmark_path, report=report)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if report["gate"]["status"] == "passed" else 1


def build_task_d_benchmark(
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
        raise ValueError("Task D case_ids must not be empty")
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
        raise ValueError(f"Task D source benchmark missing case ids: {', '.join(missing)}")
    if scenario_ids:
        raise ValueError(
            "Task D M0 validation must use single-turn cases only; scenario ids: "
            + ", ".join(scenario_ids)
        )
    if len(selected) != len(selected_case_ids):
        raise ValueError(
            f"Task D selected {len(selected)} cases, expected {len(selected_case_ids)}"
        )
    task_type_counts = Counter(str(case.get("task_type") or "unknown") for case in selected)
    source_metadata = source_document if isinstance(source_document, Mapping) else {}
    return {
        "schema_version": TASK_D_BENCHMARK_SCHEMA_VERSION,
        "dataset_id": TASK_D_DATASET_ID,
        "dataset_version": TASK_D_DATASET_VERSION,
        "dataset_role": "pre_formal_real_api_stability_validation",
        "language": "zh-CN",
        "method_scope": [TASK_D_METHOD],
        "case_count": len(selected),
        "turn_count": len(selected),
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
            "purpose": (
                "Real-API stability validation for M0 before the formal run; "
                "not used as a paper-level method comparison result."
            ),
            "coverage": {
                "task_type_counts": dict(sorted(task_type_counts.items())),
                "weather_scope": ["full", "partial", "out_of_range", "no_date"],
                "budget_scope": ["destination_local_only", "supported_intercity", "unsupported_intercity"],
            },
        },
        "cases": selected,
    }


def build_task_d_report(
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
    selection_policy = (
        benchmark_document.get("selection_policy")
        if isinstance(benchmark_document.get("selection_policy"), Mapping)
        else {}
    )
    selected_case_ids = list(selection_policy.get("fixed_case_ids") or TASK_D_CASE_IDS)
    llm_calls = _llm_calls(traces)
    result_count = len(results)
    expected_result_count = int(benchmark_document.get("turn_count") or len(TASK_D_CASE_IDS))
    status_counts = Counter(str(result.get("status") or "unknown") for result in results)
    result_methods = sorted({str(result.get("method") or "") for result in results})
    failed_results = [
        {
            "case_id": result.get("case_id"),
            "status": result.get("status"),
            "error": result.get("error"),
            "hard_timeout_triggered": bool(result.get("hard_timeout_triggered")),
        }
        for result in results
        if str(result.get("status") or "").lower() != "completed"
        or result.get("error")
        or bool(result.get("hard_timeout_triggered"))
    ]
    provider_counts = Counter(str(call.get("provider") or "unknown") for call in llm_calls)
    prompt_version_counts = Counter(str(call.get("prompt_version") or "unknown") for call in llm_calls)
    mock_call_count = sum(1 for call in llm_calls if call.get("mock") or call.get("mock_used"))
    fallback_call_count = sum(1 for call in llm_calls if call.get("fallback") or call.get("fallback_used"))
    failed_llm_call_count = sum(1 for call in llm_calls if call.get("success") is False)
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
    checks = {
        "not_skipped": skipped_reason is None,
        "expected_result_count": result_count == expected_result_count,
        "m0_only": result_methods in ([], [TASK_D_METHOD]),
        "all_results_completed": result_count == expected_result_count and not failed_results,
        "trace_count_sufficient": len(traces) >= result_count if result_count else skipped_reason is not None,
        "llm_calls_recorded": len(llm_calls) >= result_count if result_count else skipped_reason is not None,
        "no_mock_calls": mock_call_count == 0,
        "no_fallback_calls": fallback_call_count == 0,
        "no_failed_llm_calls": failed_llm_call_count == 0,
        "no_hard_timeout": hard_timeout_triggered_count == 0,
        "provider_recorded": bool(provider_counts) if result_count else skipped_reason is not None,
        "token_usage_recorded": token_totals["total_tokens"] is not None if result_count else skipped_reason is not None,
        "latency_recorded": latency["result_latency_ms_total"] is not None if result_count else skipped_reason is not None,
        "cost_accounting_recorded": cost["standardized_estimated_cost_total"] is not None if result_count else skipped_reason is not None,
        "no_length_finish_reason": length_finish_count == 0,
    }
    failed_checks = [key for key, passed in checks.items() if not passed]
    status = "skipped" if skipped_reason else ("passed" if not failed_checks else "failed")
    return {
        "schema_version": TASK_D_SCHEMA_VERSION,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "run_id": run_id,
        "task": "Task D - M0 20-case real API stability validation",
        "status": status,
        "skipped_reason": skipped_reason,
        "gate": {
            "status": status,
            "checks": checks,
            "failed_checks": failed_checks,
            "paper_claim_policy": (
                "This run is an API/runtime validation gate only. It must not be "
                "reported as the paper's formal M0-M3 comparison result."
            ),
        },
        "benchmark": {
            "path": benchmark_path.as_posix(),
            "dataset_id": benchmark_document.get("dataset_id"),
            "dataset_version": benchmark_document.get("dataset_version"),
            "case_count": benchmark_document.get("case_count"),
            "turn_count": benchmark_document.get("turn_count"),
            "selected_case_ids": selected_case_ids,
            "task_type_counts": (
                (selection_policy.get("coverage") or {})
                .get("task_type_counts", {})
            ),
        },
        "runtime_config": dict(runtime_config),
        "results": {
            "expected_result_count": expected_result_count,
            "actual_result_count": result_count,
            "status_counts": dict(sorted(status_counts.items())),
            "methods": result_methods,
            "failed_results": failed_results,
            "hard_timeout_triggered_count": hard_timeout_triggered_count,
            "elapsed_seconds": elapsed_seconds,
        },
        "trace_audit": {
            "trace_file_count": len(traces),
            "llm_call_count": len(llm_calls),
            "provider_counts": dict(sorted(provider_counts.items())),
            "prompt_version_counts": dict(sorted(prompt_version_counts.items())),
            "mock_call_count": mock_call_count,
            "fallback_call_count": fallback_call_count,
            "failed_llm_call_count": failed_llm_call_count,
            "length_finish_reason_attempt_count": length_finish_count,
        },
        "token_usage": token_totals,
        "latency": latency,
        "cost": cost,
        "artifacts": _task_d_artifact_paths(run_dir),
    }


def render_task_d_report(report: Mapping[str, Any]) -> str:
    gate = report.get("gate") if isinstance(report.get("gate"), Mapping) else {}
    results = report.get("results") if isinstance(report.get("results"), Mapping) else {}
    trace = report.get("trace_audit") if isinstance(report.get("trace_audit"), Mapping) else {}
    runtime = report.get("runtime_config") if isinstance(report.get("runtime_config"), Mapping) else {}
    artifacts = report.get("artifacts") if isinstance(report.get("artifacts"), Mapping) else {}
    lines = [
        "# Task D M0 Real API Validation Report",
        "",
        f"- status: `{report.get('status')}`",
        f"- run_id: `{report.get('run_id')}`",
        f"- expected_result_count: `{results.get('expected_result_count')}`",
        f"- actual_result_count: `{results.get('actual_result_count')}`",
        f"- result_status_counts: `{results.get('status_counts')}`",
        f"- provider: `{runtime.get('provider')}`",
        f"- model: `{runtime.get('model')}`",
        f"- max_tokens: `{runtime.get('max_tokens')}`",
        f"- timeout_seconds: `{runtime.get('timeout_seconds')}`",
        f"- hard_timeout_seconds: `{runtime.get('hard_timeout_seconds')}`",
        f"- llm_call_count: `{trace.get('llm_call_count')}`",
        f"- mock_call_count: `{trace.get('mock_call_count')}`",
        f"- fallback_call_count: `{trace.get('fallback_call_count')}`",
        f"- failed_llm_call_count: `{trace.get('failed_llm_call_count')}`",
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
    failed_results = results.get("failed_results") if isinstance(results.get("failed_results"), list) else []
    if failed_results:
        lines.extend(["", "## Failed results", ""])
        for item in failed_results:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                f"- `{item.get('case_id')}` status=`{item.get('status')}`, "
                f"hard_timeout=`{item.get('hard_timeout_triggered')}`, error=`{item.get('error')}`"
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
) -> Dict[str, Any]:
    resolved_base_url = str(base_url or os.getenv("LLM_BASE_URL") or settings.llm.base_url)
    resolved_model = str(model or os.getenv("LLM_MODEL") or settings.llm.model)
    return {
        "schema_version": "ctp-task-d-runtime-config-v1",
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
        "method": TASK_D_METHOD,
    }


def _parse_case_ids(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        raw_items = value
    else:
        raw_items = str(value).replace(";", ",").split(",")
    return tuple(str(item).strip() for item in raw_items if str(item).strip())


def _task_d_env_values(runtime_config: Mapping[str, Any]) -> Dict[str, str]:
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


def _write_task_d_report(run_dir: Path, report: Dict[str, Any]) -> None:
    _write_json(run_dir / TASK_D_REPORT_JSON_NAME, report)
    (run_dir / TASK_D_REPORT_MD_NAME).write_text(
        render_task_d_report(report),
        encoding="utf-8",
    )


def _payload(
    *,
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
        "report_json": (run_dir / TASK_D_REPORT_JSON_NAME).as_posix(),
        "report_md": (run_dir / TASK_D_REPORT_MD_NAME).as_posix(),
        "benchmark_results_json": (run_dir / "benchmark_results.json").as_posix(),
        "benchmark_results_csv": (run_dir / "benchmark_results.csv").as_posix(),
        "evaluation_summary": (run_dir / "evaluation_summary.json").as_posix(),
        "manifest": (run_dir / "experiment_manifest.json").as_posix(),
        "traces": (run_dir / "traces").as_posix(),
        "failed_checks": (report.get("gate") or {}).get("failed_checks") or [],
    }


def _task_d_artifact_paths(run_dir: Path) -> Dict[str, str]:
    return {
        "benchmark": (run_dir / TASK_D_BENCHMARK_FILE_NAME).as_posix(),
        "benchmark_results_json": (run_dir / "benchmark_results.json").as_posix(),
        "benchmark_results_csv": (run_dir / "benchmark_results.csv").as_posix(),
        "evaluation_summary": (run_dir / "evaluation_summary.json").as_posix(),
        "paper_tables": (run_dir / "paper_tables.md").as_posix(),
        "manifest": (run_dir / "experiment_manifest.json").as_posix(),
        "checkpoint_json": (run_dir / "benchmark_results.checkpoint.json").as_posix(),
        "checkpoint_csv": (run_dir / "benchmark_results.checkpoint.csv").as_posix(),
        "resume_state": (run_dir / "benchmark_resume_state.json").as_posix(),
        "traces": (run_dir / "traces").as_posix(),
        "report_json": (run_dir / TASK_D_REPORT_JSON_NAME).as_posix(),
        "report_md": (run_dir / TASK_D_REPORT_MD_NAME).as_posix(),
    }


def _load_trace_records(trace_dir: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if not trace_dir.exists():
        return records
    for path in sorted(trace_dir.glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            if not lines:
                continue
            record = json.loads(lines[0])
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict):
            record["trace_file"] = path.as_posix()
            records.append(record)
    return records


def _llm_calls(traces: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []
    for trace in traces:
        for call in trace.get("llm_calls") or []:
            if isinstance(call, dict):
                calls.append(call)
    return calls


def _retry_attempts(llm_calls: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    attempts: List[Dict[str, Any]] = []
    for call in llm_calls:
        retry = call.get("retry") if isinstance(call.get("retry"), Mapping) else {}
        for attempt in retry.get("attempts") or []:
            if isinstance(attempt, dict):
                attempts.append(attempt)
    return attempts


def _token_totals(llm_calls: Iterable[Mapping[str, Any]]) -> Dict[str, Optional[float]]:
    prompt = _sum_optional(_usage_value(call, "prompt_tokens", "input_tokens") for call in llm_calls)
    completion = _sum_optional(
        _usage_value(call, "completion_tokens", "output_tokens") for call in llm_calls
    )
    total = _sum_optional(_usage_value(call, "total_tokens") for call in llm_calls)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def _latency_summary(
    results: Iterable[Mapping[str, Any]],
    llm_calls: Iterable[Mapping[str, Any]],
) -> Dict[str, Optional[float]]:
    result_latencies = [_float_or_none(result.get("latency_ms")) for result in results]
    llm_durations = [_float_or_none(call.get("duration_ms")) for call in llm_calls]
    return {
        "result_latency_ms_total": _sum_optional(result_latencies),
        "result_latency_ms_mean": _mean_optional(result_latencies),
        "llm_duration_ms_total": _sum_optional(llm_durations),
        "llm_duration_ms_mean": _mean_optional(llm_durations),
    }


def _cost_summary(llm_calls: Iterable[Mapping[str, Any]]) -> Dict[str, Optional[float]]:
    calls = list(llm_calls)
    return {
        "estimated_cost_total": _sum_optional(
            _float_or_none(call.get("estimated_cost")) for call in calls
        ),
        "standardized_estimated_cost_total": _sum_optional(
            _float_or_none(call.get("standardized_estimated_cost")) for call in calls
        ),
        "actual_cost_total": _sum_optional(_float_or_none(call.get("actual_cost")) for call in calls),
    }


def _usage_value(call: Mapping[str, Any], *keys: str) -> Optional[float]:
    usage = call.get("usage") if isinstance(call.get("usage"), Mapping) else call.get("tokens")
    usage = usage if isinstance(usage, Mapping) else {}
    for key in keys:
        value = _float_or_none(usage.get(key))
        if value is not None:
            return value
    return None


def _sum_optional(values: Iterable[Optional[float]]) -> Optional[float]:
    present = [float(value) for value in values if value is not None]
    return None if not present else round(sum(present), 8)


def _mean_optional(values: Iterable[Optional[float]]) -> Optional[float]:
    present = [float(value) for value in values if value is not None]
    return None if not present else round(sum(present) / len(present), 8)


def _float_or_none(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_run_output_dir(output_root: Path, run_id: str) -> Path:
    root = Path(output_root)
    return root if root.name == run_id else root / run_id


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@contextmanager
def _temporary_env(values: Mapping[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            os.environ[key] = str(value)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
