"""Run Task F: small multi-turn real-API validation for M2/M3.

Task F is a pre-formal engineering gate focused on the paper's core
multi-agent scheduling mechanism.  It does not replace the full CTP100
formal run and must not be reported as a formal comparison result.

The default validation set contains five existing CTP100 two-turn scenarios
plus one synthetic Task-F-only destination-change scenario:

* budget-only update;
* people-count update;
* preference update;
* weather adjustment;
* start-date update;
* destination update.

Only M2 and M3 are run:

* M2: ``fixed_multi_agent``
* M3: ``adaptive_multi_agent``
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
    _cost_summary,
    _float_or_none,
    _latency_summary,
    _llm_calls,
    _load_trace_records,
    _retry_attempts,
    _temporary_env,
    _token_totals,
)
from experiments.run_task_e_four_method_real_api_validation import (
    _agent_runs_by_method,
    _llm_calls_by_method,
    _tool_calls_by_method,
)


TASK_F_SCHEMA_VERSION = "ctp-task-f-multiturn-real-api-report-v1"
TASK_F_BENCHMARK_SCHEMA_VERSION = "ctp-task-f-multiturn-real-api-benchmark-v1"
TASK_F_RUNTIME_SCHEMA_VERSION = "ctp-task-f-runtime-config-v1"
TASK_F_DATASET_ID = "task_f_multiturn_real_api_m2_m3"
TASK_F_METHODS = ("fixed_multi_agent", "adaptive_multi_agent")
TASK_F_SUCCESS_STATUSES = {"completed"}
TASK_F_CUSTOM_DESTINATION_SCENARIO_ID = "task_f_custom_001_destination_change"
TASK_F_DEFAULT_SCENARIO_IDS = (
    "ctp100_v2_051",
    "ctp100_v2_055",
    "ctp100_v2_066",
    "ctp100_v2_070",
    "ctp100_v2_077",
    TASK_F_CUSTOM_DESTINATION_SCENARIO_ID,
)
DEFAULT_SOURCE_BENCHMARK = ROOT / "experiments" / "ctp100_formal_v2.json"
DEFAULT_OUTPUT_ROOT = ROOT / "experiments" / "results" / "task_f_multiturn_real_api"
TASK_F_REPORT_JSON_NAME = "task_f_multiturn_real_api_report.json"
TASK_F_REPORT_MD_NAME = "task_f_multiturn_real_api_report.md"
TASK_F_BENCHMARK_FILE_NAME = "task_f_multiturn_real_api_benchmark.json"
DEFAULT_METHOD_ORDER_SEED = 20260718

TASK_F_M3_SECOND_TURN_EXPECTATIONS: Dict[str, Dict[str, List[str]]] = {
    "ctp100_v2_051": {
        "required_reused_agents": ["attraction", "itinerary"],
        "required_invalidated_agents": ["budget"],
        "forbidden_reused_agents": ["budget"],
        "required_decision_reasons": ["budget_changed_budget_only"],
    },
    "ctp100_v2_055": {
        "required_reused_agents": ["attraction", "weather"],
        "required_invalidated_agents": ["itinerary", "budget"],
        "forbidden_reused_agents": ["itinerary", "budget"],
        "required_decision_reasons": ["people_count_changed_itinerary_budget_replan"],
    },
    "ctp100_v2_066": {
        "required_reused_agents": ["weather"],
        "required_invalidated_agents": ["attraction", "itinerary", "budget"],
        "forbidden_reused_agents": ["attraction", "itinerary", "budget"],
        "required_decision_reasons": ["preferences_changed_replan"],
    },
    "ctp100_v2_070": {
        "required_reused_agents": ["attraction", "weather"],
        "required_invalidated_agents": ["itinerary", "budget"],
        "forbidden_reused_agents": ["itinerary", "budget"],
        "required_decision_reasons": ["weather_adjustment_reuses_previous_weather"],
    },
    "ctp100_v2_077": {
        "required_reused_agents": ["attraction"],
        "required_invalidated_agents": ["weather", "itinerary", "budget"],
        "forbidden_reused_agents": ["weather", "itinerary", "budget"],
        "required_decision_reasons": ["date_changed_weather_itinerary_budget_replan"],
    },
    TASK_F_CUSTOM_DESTINATION_SCENARIO_ID: {
        "required_reused_agents": [],
        "required_invalidated_agents": ["attraction", "weather", "itinerary", "budget"],
        "forbidden_reused_agents": ["attraction", "weather", "itinerary", "budget"],
        "required_decision_reasons": ["destination_changed_invalidate_all"],
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-benchmark", type=Path, default=DEFAULT_SOURCE_BENCHMARK)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument(
        "--scenario-ids",
        nargs="*",
        default=None,
        help=(
            "Optional scenario ids to run. Omit to run the fixed Task F set. "
            f"Use {TASK_F_CUSTOM_DESTINATION_SCENARIO_ID} for the synthetic destination-change case."
        ),
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--base-url", type=str, default=None)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--hard-timeout-seconds", type=int, default=900)
    parser.add_argument("--retry-max-attempts", type=int, default=3)
    parser.add_argument("--reasoning-effort", type=str, default="minimal")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--method-order-seed", type=int, default=DEFAULT_METHOD_ORDER_SEED)
    args = parser.parse_args()

    run_id = args.run_id or f"task_f_multiturn_real_api_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = args.output_root / run_id
    if run_dir.exists() and any(run_dir.iterdir()) and not args.resume:
        raise RuntimeError(f"Task F output directory is not empty: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)

    benchmark_document = build_task_f_benchmark(
        args.source_benchmark,
        scenario_ids=args.scenario_ids or TASK_F_DEFAULT_SCENARIO_IDS,
    )
    benchmark_path = run_dir / TASK_F_BENCHMARK_FILE_NAME
    _write_json(benchmark_path, benchmark_document)
    runtime = _runtime_config(
        base_url=args.base_url,
        model=args.model,
        max_tokens=args.max_tokens,
        timeout_seconds=args.timeout_seconds,
        hard_timeout_seconds=args.hard_timeout_seconds,
        retry_max_attempts=args.retry_max_attempts,
        reasoning_effort=args.reasoning_effort,
        temperature=args.temperature,
        method_order_seed=args.method_order_seed,
        expected_raw_result_count=int(benchmark_document["expected_raw_result_count"]),
    )

    if args.dry_run:
        report = build_task_f_report(
            run_id=run_id,
            run_dir=run_dir,
            benchmark_path=benchmark_path,
            benchmark_document=benchmark_document,
            runtime_config=runtime,
            results=[],
            elapsed_seconds=0.0,
            skipped_reason="dry_run",
        )
        _write_task_f_report(run_dir, report)
        print(json.dumps(_payload(run_id, run_dir, benchmark_path, report), ensure_ascii=False, indent=2))
        return 0

    env = _task_f_env_values(runtime)
    runner = ExperimentRunner(
        trace_dir=run_dir / "traces",
        output_dir=run_dir,
        repeats=1,
        run_id=run_id,
        model_config_name="task-f-multiturn-real-api",
        method_order_seed=args.method_order_seed,
    )
    started = time.perf_counter()
    with _temporary_env(env):
        results = runner.run_benchmark(
            benchmark_path,
            methods=TASK_F_METHODS,
            repeats=1,
            run_id=run_id,
            model_config_name="task-f-multiturn-real-api",
            resume=args.resume,
        )
    elapsed = time.perf_counter() - started
    report = build_task_f_report(
        run_id=run_id,
        run_dir=run_dir,
        benchmark_path=benchmark_path,
        benchmark_document=benchmark_document,
        runtime_config=runtime,
        results=results,
        elapsed_seconds=elapsed,
    )
    _write_task_f_report(run_dir, report)
    print(json.dumps(_payload(run_id, run_dir, benchmark_path, report), ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


def build_task_f_benchmark(
    source_benchmark_path: str | Path,
    *,
    scenario_ids: Iterable[str] = TASK_F_DEFAULT_SCENARIO_IDS,
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
    not_multiturn: List[str] = []
    selected_ids = tuple(str(scenario_id).strip() for scenario_id in scenario_ids if str(scenario_id).strip())
    if not selected_ids:
        raise ValueError("Task F scenario_ids must not be empty")
    for scenario_id in selected_ids:
        if scenario_id == TASK_F_CUSTOM_DESTINATION_SCENARIO_ID:
            selected.append(_custom_destination_change_scenario())
            continue
        case = source_case_map.get(scenario_id)
        if case is None:
            missing.append(scenario_id)
            continue
        if not (isinstance(case.get("turns"), list) and len(case.get("turns") or []) >= 2):
            not_multiturn.append(scenario_id)
            continue
        selected.append(json.loads(json.dumps(case, ensure_ascii=False)))
    if missing:
        raise ValueError(f"Task F source benchmark missing scenario ids: {', '.join(missing)}")
    if not_multiturn:
        raise ValueError(
            "Task F requires multi-turn scenarios; non-scenario ids: "
            + ", ".join(not_multiturn)
        )

    scenario_turns = [
        {
            "scenario_id": str(case.get("scenario_id") or case.get("case_id")),
            "turn_ids": [
                str(turn.get("turn_id") or turn.get("id") or f"t{index + 1}")
                for index, turn in enumerate(case.get("turns") or [])
            ],
        }
        for case in selected
    ]
    task_type_counts: Counter[str] = Counter()
    changed_slot_counts: Counter[str] = Counter()
    for case in selected:
        for turn in case.get("turns") or []:
            expected = turn.get("expected") if isinstance(turn.get("expected"), Mapping) else {}
            task_type_counts.update([str(expected.get("task_type") or turn.get("task_type") or "unknown")])
            for slot in expected.get("changed_slots") or []:
                changed_slot_counts.update([str(slot)])

    turn_count = sum(len(case.get("turns") or []) for case in selected)
    source_metadata = source_document if isinstance(source_document, Mapping) else {}
    return {
        "schema_version": TASK_F_BENCHMARK_SCHEMA_VERSION,
        "dataset_id": TASK_F_DATASET_ID,
        "dataset_version": "2026-08-21-task-f-multiturn-real-api-validation-v1",
        "dataset_role": "pre_formal_multiturn_real_api_reuse_validation",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "source_benchmark": {
            "path": source_path.as_posix(),
            "dataset_id": source_metadata.get("dataset_id"),
            "dataset_version": source_metadata.get("dataset_version"),
            "dataset_sha256": canonical_json_sha256(source_document),
            "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
        },
        "case_count": len(selected),
        "turn_count": turn_count,
        "scenario_count": len(selected),
        "method_scope": list(TASK_F_METHODS),
        "expected_raw_result_count": turn_count * len(TASK_F_METHODS),
        "selection_policy": {
            "fixed_scenario_ids": selected_ids,
            "scenario_turns": scenario_turns,
            "custom_destination_change_scenario_id": TASK_F_CUSTOM_DESTINATION_SCENARIO_ID,
            "coverage": {
                "task_type_counts": dict(sorted(task_type_counts.items())),
                "changed_slot_counts": dict(sorted(changed_slot_counts.items())),
            },
            "m3_second_turn_expectations": {
                scenario_id: TASK_F_M3_SECOND_TURN_EXPECTATIONS[scenario_id]
                for scenario_id in selected_ids
                if scenario_id in TASK_F_M3_SECOND_TURN_EXPECTATIONS
            },
        },
        "paper_claim_policy": (
            "Task F is a pre-formal runtime validation gate for multi-turn M2/M3 "
            "reuse behavior. It must not be reported as the paper's formal result."
        ),
        "cases": selected,
    }


def build_task_f_report(
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
    expected_methods = list(benchmark_document.get("method_scope") or TASK_F_METHODS)
    expected_units = _expected_turn_units(benchmark_document)
    expected_result_count = int(
        benchmark_document.get("expected_raw_result_count")
        or len(expected_units) * len(expected_methods)
    )
    status_counts = Counter(str(result.get("status") or "unknown") for result in results)
    method_counts = Counter(str(result.get("method") or "unknown") for result in results)
    failed_results = _task_f_failed_results(results)
    grid = _turn_method_grid(
        results,
        expected_units=expected_units,
        expected_methods=expected_methods,
    )
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
    second_turn_audit = _second_turn_reuse_audit(
        results,
        expectations=(
            (benchmark_document.get("selection_policy") or {}).get("m3_second_turn_expectations")
            or {}
        ),
    )
    decision_normalizer = _decision_normalizer_summary(results)
    warnings = []
    if failed_llm_call_count:
        warnings.append(
            {
                "code": "failed_llm_calls_recorded",
                "count": failed_llm_call_count,
                "meaning": (
                    "At least one internal LLM call failed after retries. "
                    "Task F treats this as a provider-stability warning only "
                    "when the result grid has no failed result and no hard timeout."
                ),
            }
        )
    if retry_error_count:
        warnings.append(
            {
                "code": "llm_retry_errors_recorded",
                "count": retry_error_count,
                "meaning": "Retryable API errors or network timeouts were recorded.",
            }
        )

    checks = {
        "not_skipped": skipped_reason is None,
        "expected_result_count": len(results) == expected_result_count,
        "m2_m3_methods_only": set(method_counts) <= set(TASK_F_METHODS)
        and set(expected_methods) == set(TASK_F_METHODS),
        "turn_method_grid_complete": grid["missing_count"] == 0 and grid["duplicate_count"] == 0,
        "all_results_completed": len(results) == expected_result_count and not failed_results,
        "trace_count_matches_results": len(traces) == len(results) if results else skipped_reason is not None,
        "llm_calls_recorded": bool(llm_calls) if results else skipped_reason is not None,
        "agent_or_tool_evidence_recorded": all(
            agent_runs_by_method.get(method, 0) > 0 or tool_calls_by_method.get(method, 0) > 0
            for method in TASK_F_METHODS
        )
        if results
        else skipped_reason is not None,
        "second_turn_previous_state_present": second_turn_audit["missing_previous_state_count"] == 0,
        "m2_second_turn_no_reuse": second_turn_audit["m2_reuse_violation_count"] == 0,
        "m3_second_turn_reuse_expectations_met": second_turn_audit["m3_expectation_violation_count"] == 0,
        "m3_destination_change_invalidates_all": second_turn_audit[
            "destination_change_invalidation_passed"
        ]
        is True,
        "no_mock_calls": mock_call_count == 0,
        "no_mock_or_model_fallback": fallback_call_count == 0,
        "no_hard_timeout": hard_timeout_triggered_count == 0,
        "provider_is_vectorengine_openai_compatible": (
            set(provider_counts) <= {"vectorengine_openai_compatible"}
            and bool(provider_counts)
        )
        if results
        else skipped_reason is not None,
        "token_usage_recorded": token_totals["total_tokens"] is not None if results else skipped_reason is not None,
        "latency_recorded": latency["result_latency_ms_total"] is not None if results else skipped_reason is not None,
        "cost_accounting_recorded": cost["standardized_estimated_cost_total"] is not None if results else skipped_reason is not None,
        "no_length_finish_reason": length_finish_count == 0,
    }
    failed_checks = [key for key, passed in checks.items() if not passed]
    status = "skipped" if skipped_reason else ("passed" if not failed_checks else "failed")
    return {
        "schema_version": TASK_F_SCHEMA_VERSION,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "run_id": run_id,
        "task": "Task F - multi-turn M2/M3 real API reuse validation",
        "status": status,
        "skipped_reason": skipped_reason,
        "gate": {
            "status": status,
            "checks": checks,
            "failed_checks": failed_checks,
            "warnings": warnings,
            "paper_claim_policy": (
                "This run is a pre-formal multi-turn runtime validation gate only. "
                "It must not be reported as the paper's formal M2/M3 comparison result."
            ),
        },
        "benchmark": {
            "path": benchmark_path.as_posix(),
            "dataset_id": benchmark_document.get("dataset_id"),
            "dataset_version": benchmark_document.get("dataset_version"),
            "case_count": benchmark_document.get("case_count"),
            "turn_count": benchmark_document.get("turn_count"),
            "expected_raw_result_count": expected_result_count,
            "selected_scenario_ids": list(
                ((benchmark_document.get("selection_policy") or {}).get("fixed_scenario_ids"))
                or []
            ),
            "coverage": ((benchmark_document.get("selection_policy") or {}).get("coverage") or {}),
        },
        "runtime_config": dict(runtime_config),
        "results": {
            "expected_result_count": expected_result_count,
            "actual_result_count": len(results),
            "status_counts": dict(sorted(status_counts.items())),
            "method_counts": dict(sorted(method_counts.items())),
            "failed_results": failed_results,
            "hard_timeout_triggered_count": hard_timeout_triggered_count,
            "elapsed_seconds": elapsed_seconds,
        },
        "turn_method_grid": grid,
        "second_turn_reuse_audit": second_turn_audit,
        "decision_normalizer": decision_normalizer,
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
        },
        "warnings": warnings,
        "token_usage": token_totals,
        "latency": latency,
        "cost": cost,
        "artifacts": _task_f_artifact_paths(run_dir),
    }


def render_task_f_report(report: Mapping[str, Any]) -> str:
    gate = report.get("gate") if isinstance(report.get("gate"), Mapping) else {}
    checks = gate.get("checks") if isinstance(gate.get("checks"), Mapping) else {}
    results = report.get("results") if isinstance(report.get("results"), Mapping) else {}
    trace = report.get("trace_audit") if isinstance(report.get("trace_audit"), Mapping) else {}
    reuse = report.get("second_turn_reuse_audit") if isinstance(report.get("second_turn_reuse_audit"), Mapping) else {}
    normalizer = report.get("decision_normalizer") if isinstance(report.get("decision_normalizer"), Mapping) else {}
    lines = [
        "# Task F Multi-Turn Real API Validation Report",
        "",
        f"- status: `{report.get('status')}`",
        f"- run_id: `{report.get('run_id')}`",
        f"- expected_result_count: `{results.get('expected_result_count')}`",
        f"- actual_result_count: `{results.get('actual_result_count')}`",
        f"- status_counts: `{results.get('status_counts')}`",
        f"- trace_file_count: `{trace.get('trace_file_count')}`",
        f"- llm_call_count: `{trace.get('llm_call_count')}`",
        f"- provider_counts: `{trace.get('provider_counts')}`",
        f"- mock_call_count: `{trace.get('mock_call_count')}`",
        f"- fallback_call_count: `{trace.get('fallback_call_count')}`",
        f"- hard_timeout_triggered_count: `{results.get('hard_timeout_triggered_count')}`",
        f"- m3_expectation_violation_count: `{reuse.get('m3_expectation_violation_count')}`",
        f"- decision_normalizer_recovery_rate: `{normalizer.get('decision_normalizer_recovery_rate')}`",
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
            "## M3 second-turn reuse audit",
            "",
            f"- destination_change_invalidation_passed: `{reuse.get('destination_change_invalidation_passed')}`",
            f"- missing_previous_state_count: `{reuse.get('missing_previous_state_count')}`",
            f"- m2_reuse_violation_count: `{reuse.get('m2_reuse_violation_count')}`",
            f"- m3_expectation_violation_count: `{reuse.get('m3_expectation_violation_count')}`",
            f"- violations: `{reuse.get('violations') or []}`",
            "",
            "## Decision normalizer diagnostics",
            "",
            f"- agent_decision_total: `{normalizer.get('agent_decision_total')}`",
            f"- raw_llm_decision_success_rate: `{normalizer.get('raw_llm_decision_success_rate')}`",
            f"- decision_normalizer_recovery_count: `{normalizer.get('decision_normalizer_recovery_count')}`",
            f"- decision_normalizer_recovery_rate: `{normalizer.get('decision_normalizer_recovery_rate')}`",
            f"- recovery_by_method: `{normalizer.get('recovery_by_method')}`",
            f"- recovery_by_agent: `{normalizer.get('recovery_by_agent')}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _custom_destination_change_scenario() -> Dict[str, Any]:
    return {
        "case_id": TASK_F_CUSTOM_DESTINATION_SCENARIO_ID,
        "scenario_id": TASK_F_CUSTOM_DESTINATION_SCENARIO_ID,
        "title": "Task F自定义多轮验证｜杭州改西安｜目的地变更",
        "check": "目的地变更后，M3必须废弃旧景点、旧天气、旧行程和旧预算，重新执行完整链路。",
        "task_f_only": True,
        "turns": [
            {
                "turn_id": "t1",
                "user_input": "明天去杭州玩3天，两个人，总预算上限5000元，先帮我安排一版。",
                "task_type": "trip_planning",
                "current_slots": {
                    "destination": "hangzhou",
                    "start_date": "2026-08-07",
                    "duration_days": 3,
                    "people_count": 2,
                    "budget_amount": 5000,
                },
                "slots": {
                    "destination": "hangzhou",
                    "start_date": "2026-08-07",
                    "duration_days": 3,
                    "people_count": 2,
                    "budget_amount": 5000,
                },
                "expected": {
                    "task_type": "trip_planning",
                    "required_tools": ["poi_search", "weather_query", "budget_calculator"],
                    "accepted_agent_sets": [["attraction", "weather", "itinerary", "budget"]],
                    "accepted_tool_sets": [["poi_search", "weather_query", "budget_calculator"]],
                    "forbidden_tools": [],
                    "hard_constraints": {
                        "destination": "hangzhou",
                        "start_date": "2026-08-07",
                        "duration_days": 3,
                        "people_count": 2,
                        "budget_limit": 5000,
                        "min_attractions": 4,
                        "max_pois_per_day": 2,
                    },
                    "destination": "hangzhou",
                    "start_date": "2026-08-07",
                    "duration_days": 3,
                    "people_count": 2,
                    "budget_amount": 5000,
                    "origin": None,
                    "intercity_transport_included": False,
                    "budget_scope": "destination_local_only",
                    "mandatory_budget_disclaimer": True,
                    "weather_required": True,
                    "weather_date_policy": "explicit_date_use_qweather_snapshot",
                    "expected_weather_coverage_status": "full",
                    "expected_weather_covered_dates": [
                        "2026-08-07",
                        "2026-08-08",
                        "2026-08-09",
                    ],
                    "expected_weather_missing_dates": [],
                    "weather_snapshot_id": "ctp_qweather_20260807_v1",
                },
            },
            {
                "turn_id": "t2",
                "user_input": "目的地改成西安，日期、人数和预算不变，重新规划。",
                "task_type": "partial_replan",
                "current_slots": {
                    "destination": "xian",
                },
                "slots": {
                    "destination": "xian",
                    "start_date": "2026-08-07",
                    "duration_days": 3,
                    "people_count": 2,
                    "budget_amount": 5000,
                },
                "expected": {
                    "task_type": "partial_replan",
                    "required_tools": ["poi_search", "weather_query", "budget_calculator"],
                    "accepted_agent_sets": [["attraction", "weather", "itinerary", "budget"]],
                    "accepted_tool_sets": [["poi_search", "weather_query", "budget_calculator"]],
                    "forbidden_tools": [],
                    "hard_constraints": {
                        "destination": "xian",
                        "start_date": "2026-08-07",
                        "duration_days": 3,
                        "people_count": 2,
                        "budget_limit": 5000,
                        "min_attractions": 4,
                        "max_pois_per_day": 2,
                    },
                    "destination": "xian",
                    "start_date": "2026-08-07",
                    "duration_days": 3,
                    "people_count": 2,
                    "budget_amount": 5000,
                    "origin": None,
                    "intercity_transport_included": False,
                    "budget_scope": "destination_local_only",
                    "mandatory_budget_disclaimer": True,
                    "changed_slots": ["destination"],
                    "preserved_slots": ["start_date", "duration_days", "people_count", "budget_amount"],
                    "partial_replan_policy": "destination_change_full_replan",
                    "weather_required": True,
                    "weather_date_policy": "explicit_date_use_qweather_snapshot",
                    "expected_weather_coverage_status": "full",
                    "expected_weather_covered_dates": [
                        "2026-08-07",
                        "2026-08-08",
                        "2026-08-09",
                    ],
                    "expected_weather_missing_dates": [],
                    "weather_snapshot_id": "ctp_qweather_20260807_v1",
                },
            },
        ],
    }


def _runtime_config(
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
    expected_raw_result_count: int,
) -> Dict[str, Any]:
    resolved_base_url = str(base_url or os.getenv("LLM_BASE_URL") or settings.llm.base_url)
    resolved_model = str(model or os.getenv("LLM_MODEL") or settings.llm.model)
    return {
        "schema_version": TASK_F_RUNTIME_SCHEMA_VERSION,
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
        "methods": list(TASK_F_METHODS),
        "method_order_seed": int(method_order_seed),
        "expected_raw_result_count": int(expected_raw_result_count),
    }


def _task_f_env_values(runtime_config: Mapping[str, Any]) -> Dict[str, str]:
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


def _expected_turn_units(benchmark_document: Mapping[str, Any]) -> List[Dict[str, str]]:
    units: List[Dict[str, str]] = []
    selection = benchmark_document.get("selection_policy")
    scenario_turns = (
        selection.get("scenario_turns")
        if isinstance(selection, Mapping)
        and isinstance(selection.get("scenario_turns"), list)
        else []
    )
    for scenario in scenario_turns:
        if not isinstance(scenario, Mapping):
            continue
        scenario_id = str(scenario.get("scenario_id") or "")
        for turn_id in scenario.get("turn_ids") or []:
            if scenario_id and str(turn_id):
                units.append({"case_id": scenario_id, "turn_id": str(turn_id)})
    return units


def _turn_method_grid(
    results: Iterable[Mapping[str, Any]],
    *,
    expected_units: Iterable[Mapping[str, str]],
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
    missing = [
        {"case_id": unit["case_id"], "turn_id": unit["turn_id"], "method": method}
        for unit in units
        for method in methods
        if counts[(unit["case_id"], unit["turn_id"], method)] == 0
    ]
    expected_case_ids = {unit["case_id"] for unit in units}
    expected_turn_ids = {(unit["case_id"], unit["turn_id"]) for unit in units}
    duplicates = [
        {"case_id": case_id, "turn_id": turn_id, "method": method, "count": count}
        for (case_id, turn_id, method), count in sorted(counts.items())
        if (case_id, turn_id) in expected_turn_ids and method in methods and count > 1
    ]
    unexpected = [
        {"case_id": case_id, "turn_id": turn_id, "method": method, "count": count}
        for (case_id, turn_id, method), count in sorted(counts.items())
        if case_id not in expected_case_ids or (case_id, turn_id) not in expected_turn_ids or method not in methods
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


def _task_f_failed_results(results: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    failed: List[Dict[str, Any]] = []
    for result in results:
        if (
            str(result.get("status") or "").lower() in TASK_F_SUCCESS_STATUSES
            and not result.get("error")
            and not bool(result.get("hard_timeout_triggered"))
        ):
            continue
        failed.append(
            {
                "case_id": result.get("case_id"),
                "turn_id": result.get("turn_id"),
                "method": result.get("method"),
                "status": result.get("status"),
                "error": result.get("error"),
                "hard_timeout_triggered": bool(result.get("hard_timeout_triggered")),
            }
        )
    return failed


def _second_turn_reuse_audit(
    results: Iterable[Mapping[str, Any]],
    *,
    expectations: Mapping[str, Any],
) -> Dict[str, Any]:
    violations: List[Dict[str, Any]] = []
    second_turns = [
        result
        for result in results
        if _optional_int(result.get("turn_index")) is not None
        and (_optional_int(result.get("turn_index")) or 0) > 0
    ]
    missing_previous_state = [
        _result_label(result)
        for result in second_turns
        if result.get("previous_state_provided") is not True
    ]
    m2_violations: List[Dict[str, Any]] = []
    for result in second_turns:
        if str(result.get("method") or "") != "fixed_multi_agent":
            continue
        scheduler = _nested_mapping(result, "output", "metadata", "fixed_template_scheduler")
        decision = scheduler.get("decision") if isinstance(scheduler.get("decision"), Mapping) else {}
        reused = _as_list(decision.get("reused_agents"))
        if scheduler.get("state_reuse") is not False or reused:
            m2_violations.append(
                {
                    "result": _result_label(result),
                    "state_reuse": scheduler.get("state_reuse"),
                    "reused_agents": reused,
                }
            )

    m3_expectation_violations: List[Dict[str, Any]] = []
    custom_destination_passed: Optional[bool] = None
    for result in second_turns:
        if str(result.get("method") or "") != "adaptive_multi_agent":
            continue
        scenario_id = str(result.get("scenario_id") or result.get("case_id") or "")
        expectation = expectations.get(scenario_id)
        if not isinstance(expectation, Mapping):
            continue
        metrics = result.get("metrics") if isinstance(result.get("metrics"), Mapping) else {}
        reused = set(_as_list(metrics.get("m3_reused_agents")))
        invalidated = set(_as_list(metrics.get("m3_invalidated_agents")))
        reasons = set(_as_list(metrics.get("m3_decision_reasons")))
        required_reused = set(_as_list(expectation.get("required_reused_agents")))
        required_invalidated = set(_as_list(expectation.get("required_invalidated_agents")))
        forbidden_reused = set(_as_list(expectation.get("forbidden_reused_agents")))
        required_reasons = set(_as_list(expectation.get("required_decision_reasons")))
        issues: List[str] = []
        if not required_reused <= reused:
            issues.append("missing_required_reused_agents")
        if not required_invalidated <= invalidated:
            issues.append("missing_required_invalidated_agents")
        if forbidden_reused & reused:
            issues.append("forbidden_reused_agents_present")
        if required_reasons and not required_reasons <= reasons:
            issues.append("missing_required_decision_reasons")
        if issues:
            m3_expectation_violations.append(
                {
                    "result": _result_label(result),
                    "scenario_id": scenario_id,
                    "issues": issues,
                    "observed": {
                        "reused_agents": sorted(reused),
                        "invalidated_agents": sorted(invalidated),
                        "decision_reasons": sorted(reasons),
                    },
                    "expected": dict(expectation),
                }
            )
        if scenario_id == TASK_F_CUSTOM_DESTINATION_SCENARIO_ID:
            custom_destination_passed = not issues

    violations.extend({"type": "missing_previous_state", **item} for item in missing_previous_state)
    violations.extend({"type": "m2_reuse_violation", **item} for item in m2_violations)
    violations.extend(
        {"type": "m3_expectation_violation", **item}
        for item in m3_expectation_violations
    )
    return {
        "second_turn_result_count": len(second_turns),
        "missing_previous_state_count": len(missing_previous_state),
        "missing_previous_state": missing_previous_state,
        "m2_reuse_violation_count": len(m2_violations),
        "m2_reuse_violations": m2_violations,
        "m3_expectation_violation_count": len(m3_expectation_violations),
        "m3_expectation_violations": m3_expectation_violations,
        "destination_change_invalidation_passed": custom_destination_passed,
        "violations": violations,
    }


def _decision_normalizer_summary(results: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    total = 0
    raw_success = 0
    recovered = 0
    by_method: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "raw_success": 0, "recovered": 0})
    by_agent: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "raw_success": 0, "recovered": 0})
    reason_counts: Counter[str] = Counter()
    recovered_result_labels: List[Dict[str, Any]] = []
    for result in results:
        audit = _nested_mapping(result, "output", "metadata", "agent_decision_audit")
        method = str(result.get("method") or "unknown")
        for agent_name, item in audit.items():
            if not isinstance(item, Mapping) or bool(item.get("reused")):
                continue
            total += 1
            agent = str(agent_name)
            by_method[method]["total"] += 1
            by_agent[agent]["total"] += 1
            source = str(item.get("decision_source") or "")
            is_recovered = bool(item.get("decision_fallback_used")) or source == "deterministic_evidence_normalizer"
            llm_error_count = int(_float_or_none(item.get("llm_decision_error_count")) or 0)
            if not is_recovered and llm_error_count == 0:
                raw_success += 1
                by_method[method]["raw_success"] += 1
                by_agent[agent]["raw_success"] += 1
            if is_recovered:
                recovered += 1
                by_method[method]["recovered"] += 1
                by_agent[agent]["recovered"] += 1
                reason_counts.update([source or "unknown"])
                recovered_result_labels.append(
                    {
                        **_result_label(result),
                        "agent": agent,
                        "decision_source": source,
                    }
                )
    return {
        "agent_decision_total": total,
        "raw_llm_decision_success_count": raw_success,
        "raw_llm_decision_success_rate": _safe_ratio(raw_success, total),
        "decision_normalizer_recovery_count": recovered,
        "decision_normalizer_recovery_rate": _safe_ratio(recovered, total),
        "pipeline_completion_rate": _safe_ratio(
            sum(1 for result in results if str(result.get("status") or "") == "completed"),
            len(list(results)) if not isinstance(results, list) else len(results),
        ),
        "recovery_by_method": dict(sorted(by_method.items())),
        "recovery_by_agent": dict(sorted(by_agent.items())),
        "recovery_reason_counts": dict(sorted(reason_counts.items())),
        "recovered_result_labels": recovered_result_labels,
    }


def _result_label(result: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "case_id": result.get("case_id") or result.get("scenario_id"),
        "turn_id": result.get("turn_id"),
        "method": result.get("method"),
    }


def _optional_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_ratio(numerator: int | float, denominator: int | float) -> Optional[float]:
    if not denominator:
        return None
    return round(float(numerator) / float(denominator), 6)


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    if value in (None, ""):
        return []
    return [value]


def _nested_mapping(value: Mapping[str, Any], *keys: str) -> Dict[str, Any]:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            return {}
        current = current.get(key)
    return dict(current) if isinstance(current, Mapping) else {}


def _write_task_f_report(run_dir: Path, report: Dict[str, Any]) -> None:
    _write_json(run_dir / TASK_F_REPORT_JSON_NAME, report)
    (run_dir / TASK_F_REPORT_MD_NAME).write_text(
        render_task_f_report(report),
        encoding="utf-8",
    )


def _task_f_artifact_paths(run_dir: Path) -> Dict[str, str]:
    return {
        "benchmark": (run_dir / TASK_F_BENCHMARK_FILE_NAME).as_posix(),
        "benchmark_results_json": (run_dir / "benchmark_results.json").as_posix(),
        "benchmark_results_csv": (run_dir / "benchmark_results.csv").as_posix(),
        "evaluation_summary": (run_dir / "evaluation_summary.json").as_posix(),
        "paper_tables": (run_dir / "paper_tables.md").as_posix(),
        "manifest": (run_dir / "experiment_manifest.json").as_posix(),
        "checkpoint_json": (run_dir / "benchmark_results.checkpoint.json").as_posix(),
        "checkpoint_csv": (run_dir / "benchmark_results.checkpoint.csv").as_posix(),
        "resume_state": (run_dir / "benchmark_resume_state.json").as_posix(),
        "traces": (run_dir / "traces").as_posix(),
        "report_json": (run_dir / TASK_F_REPORT_JSON_NAME).as_posix(),
        "report_md": (run_dir / TASK_F_REPORT_MD_NAME).as_posix(),
    }


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
        "report_json": (run_dir / TASK_F_REPORT_JSON_NAME).as_posix(),
        "report_md": (run_dir / TASK_F_REPORT_MD_NAME).as_posix(),
        "benchmark_results_json": (run_dir / "benchmark_results.json").as_posix(),
        "benchmark_results_csv": (run_dir / "benchmark_results.csv").as_posix(),
        "evaluation_summary": (run_dir / "evaluation_summary.json").as_posix(),
        "manifest": (run_dir / "experiment_manifest.json").as_posix(),
        "traces": (run_dir / "traces").as_posix(),
        "gate_failed_checks": (report.get("gate") or {}).get("failed_checks") or [],
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@contextmanager
def task_f_env(runtime_config: Mapping[str, Any]) -> Iterator[None]:
    """Temporarily apply the strict Task F real-API runtime environment."""
    with _temporary_env(_task_f_env_values(runtime_config)):
        yield


if __name__ == "__main__":
    raise SystemExit(main())
