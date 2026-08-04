"""Day 7 cost forecast and model-freeze evidence.

This module reads a completed Day 7 development run and builds a reproducible
cost forecast for the planned formal experiment.  It deliberately does not call
the model: all usage numbers come from saved result rows and request-level
traces.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.core.day7_dev_experiment_gate import (
    DEFAULT_DAY7_DEV_MAX_TOKENS,
    DEFAULT_TOKEN_CAP_HIT_RATE_LIMIT,
    refresh_day7_dev_artifact_index,
)


DAY7_COST_FORECAST_SCHEMA_VERSION = "ctp-day7-cost-forecast-v1"
DAY7_COST_FORECAST_JSON_NAME = "day7_cost_forecast.json"
DAY7_COST_FORECAST_REPORT_NAME = "day7_cost_forecast.md"

DEFAULT_DEV_CASE_COUNT = 20
DEFAULT_DEV_TURN_COUNT = 26
DEFAULT_DEV_RAW_RESULT_COUNT = 104
DEFAULT_FORMAL_CASE_COUNT = 100
DEFAULT_FORMAL_TURN_COUNT = 130
DEFAULT_FORMAL_RAW_RESULT_COUNT = 520
DEFAULT_DEV_BUDGET_CNY = 15.0
DEFAULT_FORMAL_BUDGET_CNY = 75.0
DEFAULT_TWO_WEEK_BUDGET_CNY = 150.0
DEFAULT_NETWORK_RETRY_RESERVE_RATE = 0.10
DEFAULT_EXTRA_DEV_RERUNS = 1
DEFAULT_USD_TO_CNY_RATE = 7.30

GPT5_MINI_PRICE_INPUT_USD_PER_1M = 0.25
GPT5_MINI_PRICE_OUTPUT_USD_PER_1M = 2.00
GPT5_MINI_PRICE_SOURCE_URL = "https://api.vectorengine.ai/pricing"
GPT5_MINI_PRICE_SNAPSHOT_DATE = "2026-08-01"

_RUNTIME_FIELDS = (
    "model",
    "temperature",
    "max_tokens",
    "timeout_seconds",
    "retry_max_attempts",
    "reasoning_effort",
)
_DEFAULT_METHOD_ORDER = ("llm_direct", "single_agent", "fixed_multi_agent", "adaptive_multi_agent")


def write_day7_cost_forecast(
    run_dir: str | Path,
    *,
    expected_dev_case_count: int = DEFAULT_DEV_CASE_COUNT,
    expected_dev_turn_count: int = DEFAULT_DEV_TURN_COUNT,
    expected_dev_raw_result_count: int = DEFAULT_DEV_RAW_RESULT_COUNT,
    expected_task_type_count: int = 8,
    formal_case_count: int = DEFAULT_FORMAL_CASE_COUNT,
    formal_turn_count: int = DEFAULT_FORMAL_TURN_COUNT,
    formal_raw_result_count: int = DEFAULT_FORMAL_RAW_RESULT_COUNT,
    dev_budget_cny: float = DEFAULT_DEV_BUDGET_CNY,
    formal_budget_cny: float = DEFAULT_FORMAL_BUDGET_CNY,
    two_week_budget_cny: float = DEFAULT_TWO_WEEK_BUDGET_CNY,
    network_retry_reserve_rate: float = DEFAULT_NETWORK_RETRY_RESERVE_RATE,
    extra_dev_reruns: int = DEFAULT_EXTRA_DEV_RERUNS,
    usd_to_cny_rate: float = DEFAULT_USD_TO_CNY_RATE,
    input_usd_per_1m: Optional[float] = None,
    output_usd_per_1m: Optional[float] = None,
    price_source_url: Optional[str] = None,
    price_snapshot_date: Optional[str] = None,
    expected_max_tokens: int = DEFAULT_DAY7_DEV_MAX_TOKENS,
    token_cap_hit_rate_limit: float = DEFAULT_TOKEN_CAP_HIT_RATE_LIMIT,
    attach_to_manifest: bool = True,
) -> Dict[str, Any]:
    """Write JSON and Markdown cost/model-freeze artifacts for ``run_dir``."""
    root = Path(run_dir)
    forecast = build_day7_cost_forecast(
        root,
        expected_dev_case_count=expected_dev_case_count,
        expected_dev_turn_count=expected_dev_turn_count,
        expected_dev_raw_result_count=expected_dev_raw_result_count,
        expected_task_type_count=expected_task_type_count,
        formal_case_count=formal_case_count,
        formal_turn_count=formal_turn_count,
        formal_raw_result_count=formal_raw_result_count,
        dev_budget_cny=dev_budget_cny,
        formal_budget_cny=formal_budget_cny,
        two_week_budget_cny=two_week_budget_cny,
        network_retry_reserve_rate=network_retry_reserve_rate,
        extra_dev_reruns=extra_dev_reruns,
        usd_to_cny_rate=usd_to_cny_rate,
        input_usd_per_1m=input_usd_per_1m,
        output_usd_per_1m=output_usd_per_1m,
        price_source_url=price_source_url,
        price_snapshot_date=price_snapshot_date,
        expected_max_tokens=expected_max_tokens,
        token_cap_hit_rate_limit=token_cap_hit_rate_limit,
    )
    json_path = root / DAY7_COST_FORECAST_JSON_NAME
    report_path = root / DAY7_COST_FORECAST_REPORT_NAME
    forecast["artifact_paths"]["day7_cost_forecast_json"] = json_path.as_posix()
    forecast["artifact_paths"]["day7_cost_forecast_report"] = report_path.as_posix()
    json_path.write_text(json.dumps(forecast, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(render_day7_cost_forecast_report(forecast), encoding="utf-8")
    if attach_to_manifest:
        _attach_to_manifest(root, forecast=forecast, json_path=json_path, report_path=report_path)
        refresh_day7_dev_artifact_index(root)
    return {
        "status": "completed",
        "forecast": forecast,
        "json": json_path.as_posix(),
        "markdown": report_path.as_posix(),
        "freeze_status": _nested(forecast, "freeze_decision", "status"),
        "budget_status": _nested(forecast, "budget_gate", "status"),
        "failed_checks": forecast.get("failed_checks") or [],
    }


def build_day7_cost_forecast(
    run_dir: str | Path,
    *,
    expected_dev_case_count: int = DEFAULT_DEV_CASE_COUNT,
    expected_dev_turn_count: int = DEFAULT_DEV_TURN_COUNT,
    expected_dev_raw_result_count: int = DEFAULT_DEV_RAW_RESULT_COUNT,
    expected_task_type_count: int = 8,
    formal_case_count: int = DEFAULT_FORMAL_CASE_COUNT,
    formal_turn_count: int = DEFAULT_FORMAL_TURN_COUNT,
    formal_raw_result_count: int = DEFAULT_FORMAL_RAW_RESULT_COUNT,
    dev_budget_cny: float = DEFAULT_DEV_BUDGET_CNY,
    formal_budget_cny: float = DEFAULT_FORMAL_BUDGET_CNY,
    two_week_budget_cny: float = DEFAULT_TWO_WEEK_BUDGET_CNY,
    network_retry_reserve_rate: float = DEFAULT_NETWORK_RETRY_RESERVE_RATE,
    extra_dev_reruns: int = DEFAULT_EXTRA_DEV_RERUNS,
    usd_to_cny_rate: float = DEFAULT_USD_TO_CNY_RATE,
    input_usd_per_1m: Optional[float] = None,
    output_usd_per_1m: Optional[float] = None,
    price_source_url: Optional[str] = None,
    price_snapshot_date: Optional[str] = None,
    expected_max_tokens: int = DEFAULT_DAY7_DEV_MAX_TOKENS,
    token_cap_hit_rate_limit: float = DEFAULT_TOKEN_CAP_HIT_RATE_LIMIT,
) -> Dict[str, Any]:
    """Build the Day 7 cost forecast from persisted artifacts only."""
    root = Path(run_dir)
    results = _read_json_list(root / "benchmark_results.json")
    summary = _read_json_object(root / "evaluation_summary.json")
    manifest = _read_json_object(root / "experiment_manifest.json")
    dev_gate = _read_json_object(root / "day7_dev_gate.json")
    rows = [_row_usage(root, result) for result in results]
    llm_calls = [call for row in rows for call in row["llm_calls"]]
    price_snapshot = _resolve_price_snapshot(
        manifest,
        input_usd_per_1m=input_usd_per_1m,
        output_usd_per_1m=output_usd_per_1m,
        price_source_url=price_source_url,
        price_snapshot_date=price_snapshot_date,
        usd_to_cny_rate=usd_to_cny_rate,
    )
    method_stats = _stats_by(rows, "method", price_snapshot)
    task_type_stats = _stats_by(rows, "task_type", price_snapshot)
    dev_totals = _totals(rows, price_snapshot)
    retry_summary = _retry_summary(llm_calls)
    runtime_freeze = _runtime_freeze_summary(
        manifest,
        llm_calls,
        expected_max_tokens=expected_max_tokens,
    )
    formal_projection = _formal_projection(
        dev_totals,
        formal_case_count=formal_case_count,
        formal_turn_count=formal_turn_count,
        formal_raw_result_count=formal_raw_result_count,
        observed_raw_result_count=len(rows),
    )
    budget_gate = _budget_gate(
        dev_totals,
        formal_projection,
        dev_budget_cny=dev_budget_cny,
        formal_budget_cny=formal_budget_cny,
        two_week_budget_cny=two_week_budget_cny,
        network_retry_reserve_rate=network_retry_reserve_rate,
        observed_retry_overhead_rate=_number(
            retry_summary.get("observed_retry_overhead_rate"),
            default=0.0,
        ),
        extra_dev_reruns=extra_dev_reruns,
    )
    observed = _observed_scope(
        results,
        rows,
        summary,
        manifest,
        expected_dev_case_count=expected_dev_case_count,
        expected_dev_turn_count=expected_dev_turn_count,
        expected_dev_raw_result_count=expected_dev_raw_result_count,
    )
    evidence = _evidence_quality(
        dev_gate,
        rows,
        llm_calls,
        price_snapshot,
        token_cap_hit_rate_limit=token_cap_hit_rate_limit,
    )
    checks = {
        "dev_gate_passed": dev_gate.get("status") == "passed",
        "expected_dev_scope_matches": observed["scope_matches_expected"] is True,
        "raw_result_count_matches": len(rows) == expected_dev_raw_result_count,
        "method_count_complete": all(item.get("row_count", 0) > 0 for item in method_stats),
        "task_type_count_complete": len(task_type_stats) >= int(expected_task_type_count),
        "token_fields_complete": evidence["token_fields_complete"] is True,
        "nonzero_price_snapshot": price_snapshot["input_usd_per_1m"] > 0
        and price_snapshot["output_usd_per_1m"] > 0,
        "trace_standardized_cost_nonzero": (
            evidence["trace_token_positive_call_count"] == 0
            or evidence["trace_standardized_cost_positive_call_count"] > 0
        ),
        "trace_price_source_not_zero_default": evidence[
            "trace_env_or_zero_default_call_count"
        ]
        == 0,
        "runtime_consistent": runtime_freeze["consistent"] is True,
        "runtime_max_tokens_matches_day7_protocol": runtime_freeze[
            "matches_day7_max_tokens_protocol"
        ]
        is True,
        "deterministic_research_final_answer_recorded": runtime_freeze[
            "deterministic_research_final_answer"
        ]
        is True,
        "completion_token_cap_hit_rate_below_limit": _nested(
            evidence,
            "output_length_risk",
            "completion_token_cap_hit_rate_below_limit",
        )
        is True,
        "no_empty_outputs_at_token_cap": _nested(
            evidence,
            "output_length_risk",
            "empty_and_token_capped_call_count",
        )
        == 0,
        "no_mock_fallback_cache": evidence["mock_call_count"] == 0
        and evidence["fallback_call_count"] == 0
        and evidence["cache_hit_count"] == 0,
        "dev_budget_within_15_cny": _nested(budget_gate, "checks", "dev_under_budget") is True,
        "formal_budget_within_75_cny": _nested(budget_gate, "checks", "formal_under_budget") is True,
        "two_week_budget_within_150_cny": _nested(budget_gate, "checks", "two_week_under_budget") is True,
    }
    cost_runtime_check_names = {
        "expected_dev_scope_matches",
        "raw_result_count_matches",
        "method_count_complete",
        "task_type_count_complete",
        "token_fields_complete",
        "nonzero_price_snapshot",
        "trace_standardized_cost_nonzero",
        "trace_price_source_not_zero_default",
        "runtime_consistent",
        "runtime_max_tokens_matches_day7_protocol",
        "deterministic_research_final_answer_recorded",
        "completion_token_cap_hit_rate_below_limit",
        "no_mock_fallback_cache",
        "dev_budget_within_15_cny",
        "formal_budget_within_75_cny",
        "two_week_budget_within_150_cny",
    }
    quality_advisory_check_names = {
        "dev_gate_passed",
        "no_empty_outputs_at_token_cap",
    }
    failed_checks = [
        name
        for name, value in checks.items()
        if not value and name in cost_runtime_check_names
    ]
    quality_advisory_failed_checks = [
        name
        for name, value in checks.items()
        if not value and name in quality_advisory_check_names
    ]
    freeze_allowed = not failed_checks
    return {
        "schema_version": DAY7_COST_FORECAST_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if freeze_allowed else "failed",
        "paper_claims_allowed": False,
        "run_dir": root.as_posix(),
        "run_id": manifest.get("run_id") or dev_gate.get("run_id"),
        "dataset_id": manifest.get("dataset_id") or _nested(manifest, "dataset", "id"),
        "dataset_version": manifest.get("dataset_version") or _nested(manifest, "dataset", "version"),
        "observed_development_run": observed,
        "price_snapshot": price_snapshot,
        "method_costs": method_stats,
        "task_type_costs": task_type_stats,
        "development_totals": dev_totals,
        "formal_projection": formal_projection,
        "retry_and_network_reserve": {
            **retry_summary,
            "reserve_rate_used": network_retry_reserve_rate,
            "reserve_policy": (
                "Use observed retry overhead when it is larger; otherwise keep a fixed "
                "network/retry cushion for API instability."
            ),
        },
        "budget_gate": budget_gate,
        "runtime_freeze": runtime_freeze,
        "evidence_quality": evidence,
        "checks": checks,
        "failed_checks": failed_checks,
        "quality_advisory_failed_checks": quality_advisory_failed_checks,
        "quality_advisory": {
            "development_gate_status": dev_gate.get("status"),
            "cost_freeze_independent_from_quality_gate": True,
            "quality_rerun_recommended": bool(quality_advisory_failed_checks),
            "failed_checks": quality_advisory_failed_checks,
            "policy": (
                "Cost/runtime freeze is based on scope, token, price, runtime, budget, "
                "and mock/fallback evidence. Development output-quality failures remain "
                "visible here but do not by themselves block budget freezing."
            ),
        },
        "freeze_decision": _freeze_decision(
            freeze_allowed=freeze_allowed,
            runtime_freeze=runtime_freeze,
            budget_gate=budget_gate,
            failed_checks=failed_checks,
            quality_advisory_failed_checks=quality_advisory_failed_checks,
        ),
        "artifact_paths": {
            "run_dir": root.as_posix(),
            "benchmark_results_json": (root / "benchmark_results.json").as_posix(),
            "benchmark_results_csv": (root / "benchmark_results.csv").as_posix(),
            "evaluation_summary": (root / "evaluation_summary.json").as_posix(),
            "experiment_manifest": (root / "experiment_manifest.json").as_posix(),
            "day7_dev_gate": (root / "day7_dev_gate.json").as_posix(),
        },
        "paper_use_policy": {
            "summary": (
                "Development-run cost evidence may be used to choose model/runtime "
                "settings and estimate budget. It must not be used as final paper "
                "quality evidence."
            ),
            "allowed_uses": [
                "model and runtime cost freeze",
                "formal experiment budget forecast",
                "token/latency table drafting before final run",
            ],
            "forbidden_uses": [
                "final academic effectiveness conclusion",
                "claiming method superiority from development data",
            ],
        },
    }


def render_day7_cost_forecast_report(forecast: Dict[str, Any]) -> str:
    """Render a Chinese Markdown report for the cost/model freeze."""
    price = _dict(forecast.get("price_snapshot"))
    dev = _dict(forecast.get("development_totals"))
    formal = _dict(forecast.get("formal_projection"))
    budget = _dict(forecast.get("budget_gate"))
    freeze = _dict(forecast.get("freeze_decision"))
    runtime = _dict(forecast.get("runtime_freeze"))
    evidence = _dict(forecast.get("evidence_quality"))
    advisory = _dict(forecast.get("quality_advisory"))
    output_risk = _dict(evidence.get("output_length_risk"))
    lines = [
        "# Day 7 成本预测与模型冻结报告",
        "",
        "## 结论",
        "",
        f"- status: `{forecast.get('status')}`",
        f"- freeze_status: `{freeze.get('status')}`",
        f"- run_id: `{forecast.get('run_id')}`",
        f"- 冻结模型: `{freeze.get('model')}`",
        f"- 冻结参数: temperature=`{freeze.get('temperature')}`, max_tokens=`{freeze.get('max_tokens')}`, "
        f"timeout=`{freeze.get('timeout_seconds')}`, retry_max_attempts=`{freeze.get('retry_max_attempts')}`, "
        f"reasoning_effort=`{freeze.get('reasoning_effort')}`",
        f"- 开发集真实估算费用: `{_money(dev.get('cost_cny'))} CNY` / `{_money(dev.get('cost_usd'))} USD`",
        f"- 正式主实验外推费用: `{_money(formal.get('cost_cny'))} CNY` / `{_money(formal.get('cost_usd'))} USD`",
        f"- 两周保守总费用: `{_money(budget.get('two_week_total_cny'))} CNY`",
        f"- failed_checks: `{forecast.get('failed_checks') or []}`",
        f"- quality_advisory_failed_checks: `{forecast.get('quality_advisory_failed_checks') or []}`",
        f"- quality_rerun_recommended: `{freeze.get('quality_rerun_recommended')}`",
        "",
        "说明：这是成本与运行参数冻结证据，不代表方法质量已经达到投稿水平；开发集质量问题会保留在 quality_advisory 中。",
        "",
        "## 质量边界",
        "",
        f"- development_gate_status: `{advisory.get('development_gate_status')}`",
        f"- cost_freeze_independent_from_quality_gate: `{advisory.get('cost_freeze_independent_from_quality_gate')}`",
        f"- quality_rerun_recommended: `{advisory.get('quality_rerun_recommended')}`",
        f"- advisory_failed_checks: `{advisory.get('failed_checks') or []}`",
        "",
        "## Trace 成本证据",
        "",
        f"- trace_standardized_cost_sum: `{_money(evidence.get('trace_standardized_cost_sum'))}`",
        f"- trace_standardized_cost_positive_call_count: `{evidence.get('trace_standardized_cost_positive_call_count')}`",
        f"- trace_token_positive_call_count: `{evidence.get('trace_token_positive_call_count')}`",
        f"- trace_env_or_zero_default_call_count: `{evidence.get('trace_env_or_zero_default_call_count')}`",
        f"- completion_token_cap_hit_count: `{output_risk.get('completion_token_cap_hit_count')}`",
        f"- completion_token_cap_hit_rate: `{_fmt(output_risk.get('completion_token_cap_hit_rate'))}`",
        f"- empty_and_token_capped_call_count: `{output_risk.get('empty_and_token_capped_call_count')}`",
        f"- actual_cost_statuses: `{evidence.get('actual_cost_statuses') or []}`",
        "",
        "## 价格快照",
        "",
        "| 字段 | 值 |",
        "|---|---:|",
        f"| source | `{price.get('source_url')}` |",
        f"| snapshot_date | `{price.get('snapshot_date')}` |",
        f"| input USD / 1M tokens | {_money(price.get('input_usd_per_1m'))} |",
        f"| output USD / 1M tokens | {_money(price.get('output_usd_per_1m'))} |",
        f"| USD→CNY 汇率 | {_fmt(price.get('usd_to_cny_rate'))} |",
        "",
        "## 四种方法平均成本",
        "",
        "| Method | Rows | LLM calls | Avg input tok | Avg output tok | Avg total tok | Avg cost CNY | Avg latency ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in forecast.get("method_costs") or []:
        if not isinstance(row, dict):
            continue
        lines.append(
            f"| {row.get('name')} | {row.get('row_count')} | {row.get('llm_call_count')} "
            f"| {_fmt(row.get('mean_prompt_tokens_per_result'))} "
            f"| {_fmt(row.get('mean_completion_tokens_per_result'))} "
            f"| {_fmt(row.get('mean_total_tokens_per_result'))} "
            f"| {_money(row.get('mean_cost_cny_per_result'))} "
            f"| {_fmt(row.get('mean_latency_ms_per_result'))} |"
        )
    lines.extend(
        [
            "",
            "## 八类任务平均成本",
            "",
            "| Task type | Rows | Avg input tok | Avg output tok | Avg total tok | Avg cost CNY | Avg latency ms |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in forecast.get("task_type_costs") or []:
        if not isinstance(row, dict):
            continue
        lines.append(
            f"| {row.get('name')} | {row.get('row_count')} "
            f"| {_fmt(row.get('mean_prompt_tokens_per_result'))} "
            f"| {_fmt(row.get('mean_completion_tokens_per_result'))} "
            f"| {_fmt(row.get('mean_total_tokens_per_result'))} "
            f"| {_money(row.get('mean_cost_cny_per_result'))} "
            f"| {_fmt(row.get('mean_latency_ms_per_result'))} |"
        )
    lines.extend(
        [
            "",
            "## 预算门禁",
            "",
            "| 项目 | 估算 CNY | 阈值 CNY | Passed |",
            "|---|---:|---:|---:|",
            f"| 开发试跑（含重试储备） | {_money(budget.get('dev_with_reserve_cny'))} "
            f"| {_money(budget.get('dev_budget_cny'))} | `{_nested(budget, 'checks', 'dev_under_budget')}` |",
            f"| 正式主实验（含重试储备） | {_money(budget.get('formal_with_reserve_cny'))} "
            f"| {_money(budget.get('formal_budget_cny'))} | `{_nested(budget, 'checks', 'formal_under_budget')}` |",
            f"| 两周总成本 | {_money(budget.get('two_week_total_cny'))} "
            f"| {_money(budget.get('two_week_budget_cny'))} | `{_nested(budget, 'checks', 'two_week_under_budget')}` |",
            "",
            "## 重试与网络储备",
            "",
        ]
    )
    retry = _dict(forecast.get("retry_and_network_reserve"))
    lines.extend(
        [
            f"- llm_call_count: `{retry.get('llm_call_count')}`",
            f"- retry_count: `{retry.get('retry_count')}`",
            f"- retry_error_count: `{retry.get('retry_error_count')}`",
            f"- observed_retry_overhead_rate: `{_fmt(retry.get('observed_retry_overhead_rate'))}`",
            f"- reserve_rate_used: `{_fmt(retry.get('reserve_rate_used'))}`",
            "",
            "## 冻结检查",
            "",
            "| Check | Passed |",
            "|---|---:|",
        ]
    )
    for key, value in _dict(forecast.get("checks")).items():
        lines.append(f"| {key} | `{value}` |")
    lines.extend(
        [
            "",
            "## 运行时冻结值",
            "",
            "| Field | Manifest value | Observed request values | Consistent |",
            "|---|---:|---:|---:|",
        ]
    )
    observed_values = _dict(runtime.get("observed_request_values"))
    manifest_values = _dict(runtime.get("manifest_values"))
    for field in _RUNTIME_FIELDS:
        lines.append(
            f"| {field} | `{manifest_values.get(field)}` | `{observed_values.get(field)}` "
            f"| `{field not in runtime.get('mismatch_fields', [])}` |"
        )
    lines.extend(
        [
            "",
            "## 实验控制冻结值",
            "",
            f"- deterministic_research_final_answer: `{runtime.get('deterministic_research_final_answer')}`",
            f"- final_answer_generation_mode: `{runtime.get('final_answer_generation_mode')}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _row_usage(run_dir: Path, result: Dict[str, Any]) -> Dict[str, Any]:
    trace = _read_jsonl_first(_trace_path(run_dir, result.get("trace_file")))
    if not trace:
        trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
    calls = _as_dict_list(trace.get("llm_calls"))
    prompt_tokens = 0.0
    completion_tokens = 0.0
    total_tokens = 0.0
    call_duration_ms = 0.0
    for call in calls:
        usage = _usage(call)
        prompt_tokens += usage["prompt_tokens"]
        completion_tokens += usage["completion_tokens"]
        total_tokens += usage["total_tokens"]
        call_duration_ms += _number(call.get("duration_ms"), default=0.0)
    task_type = (
        _nested(result, "evaluation", "task_type")
        or _nested(result, "expected", "task_type")
        or _nested(result, "output", "task_type")
        or _nested(result, "raw_output", "task_type")
        or "unknown"
    )
    return {
        "case_id": result.get("case_id"),
        "scenario_id": result.get("scenario_id"),
        "turn_id": result.get("turn_id"),
        "method": str(result.get("method") or "unknown"),
        "task_type": str(task_type),
        "status": result.get("status"),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "latency_ms": _number(result.get("latency_ms"), trace.get("total_duration_ms"), default=0.0),
        "llm_duration_ms": call_duration_ms,
        "llm_call_count": len(calls),
        "llm_calls": calls,
        "trace_loaded": bool(trace),
    }


def _stats_by(rows: Sequence[Dict[str, Any]], key: str, price: Dict[str, Any]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "unknown")].append(row)
    order = list(_DEFAULT_METHOD_ORDER) if key == "method" else []
    order += sorted(name for name in grouped if name not in order)
    return [
        {
            "name": name,
            **_aggregate_rows(grouped[name], price),
        }
        for name in order
        if name in grouped
    ]


def _totals(rows: Sequence[Dict[str, Any]], price: Dict[str, Any]) -> Dict[str, Any]:
    return _aggregate_rows(rows, price)


def _aggregate_rows(rows: Sequence[Dict[str, Any]], price: Dict[str, Any]) -> Dict[str, Any]:
    row_count = len(rows)
    llm_call_count = int(sum(_number(row.get("llm_call_count"), default=0.0) for row in rows))
    prompt_tokens = sum(_number(row.get("prompt_tokens"), default=0.0) for row in rows)
    completion_tokens = sum(_number(row.get("completion_tokens"), default=0.0) for row in rows)
    total_tokens = sum(_number(row.get("total_tokens"), default=0.0) for row in rows)
    cost_usd = _cost_usd(prompt_tokens, completion_tokens, price)
    cost_cny = _usd_to_cny(cost_usd, price)
    latency_total = sum(_number(row.get("latency_ms"), default=0.0) for row in rows)
    llm_duration_total = sum(_number(row.get("llm_duration_ms"), default=0.0) for row in rows)
    return {
        "row_count": row_count,
        "llm_row_count": sum(1 for row in rows if _number(row.get("llm_call_count"), default=0.0) > 0),
        "llm_call_count": llm_call_count,
        "prompt_tokens": round(prompt_tokens, 4),
        "completion_tokens": round(completion_tokens, 4),
        "total_tokens": round(total_tokens, 4),
        "cost_usd": round(cost_usd, 8),
        "cost_cny": round(cost_cny, 6),
        "mean_prompt_tokens_per_result": _safe_div(prompt_tokens, row_count),
        "mean_completion_tokens_per_result": _safe_div(completion_tokens, row_count),
        "mean_total_tokens_per_result": _safe_div(total_tokens, row_count),
        "mean_cost_usd_per_result": _safe_div(cost_usd, row_count, digits=8),
        "mean_cost_cny_per_result": _safe_div(cost_cny, row_count, digits=6),
        "mean_latency_ms_per_result": _safe_div(latency_total, row_count),
        "mean_llm_duration_ms_per_result": _safe_div(llm_duration_total, row_count),
        "mean_prompt_tokens_per_llm_call": _safe_div(prompt_tokens, llm_call_count),
        "mean_completion_tokens_per_llm_call": _safe_div(completion_tokens, llm_call_count),
        "mean_total_tokens_per_llm_call": _safe_div(total_tokens, llm_call_count),
    }


def _formal_projection(
    dev_totals: Dict[str, Any],
    *,
    formal_case_count: int,
    formal_turn_count: int,
    formal_raw_result_count: int,
    observed_raw_result_count: int,
) -> Dict[str, Any]:
    scale = _safe_div(formal_raw_result_count, observed_raw_result_count, digits=8) or 0.0
    fields = ("prompt_tokens", "completion_tokens", "total_tokens", "cost_usd", "cost_cny", "llm_call_count")
    projection = {
        field: round((_number(dev_totals.get(field), default=0.0) * scale), 8)
        for field in fields
    }
    return {
        "case_count": formal_case_count,
        "turn_count": formal_turn_count,
        "raw_result_count": formal_raw_result_count,
        "scale_factor_from_development_raw_rows": scale,
        **projection,
        "mean_cost_cny_per_result": dev_totals.get("mean_cost_cny_per_result"),
        "mean_total_tokens_per_result": dev_totals.get("mean_total_tokens_per_result"),
        "estimation_method": (
            "Linear extrapolation from the completed 20-case development run "
            "to 100 cases / about 130 turns / 520 method-turn rows."
        ),
    }


def _budget_gate(
    dev_totals: Dict[str, Any],
    formal_projection: Dict[str, Any],
    *,
    dev_budget_cny: float,
    formal_budget_cny: float,
    two_week_budget_cny: float,
    network_retry_reserve_rate: float,
    observed_retry_overhead_rate: float,
    extra_dev_reruns: int,
) -> Dict[str, Any]:
    dev_cost = _number(dev_totals.get("cost_cny"), default=0.0)
    formal_cost = _number(formal_projection.get("cost_cny"), default=0.0)
    configured_reserve = max(0.0, float(network_retry_reserve_rate))
    observed_reserve = max(0.0, float(observed_retry_overhead_rate))
    reserve = max(configured_reserve, observed_reserve)
    dev_with_reserve = dev_cost * (1.0 + reserve)
    formal_with_reserve = formal_cost * (1.0 + reserve)
    two_week_total = dev_with_reserve * (1 + max(0, int(extra_dev_reruns))) + formal_with_reserve
    checks = {
        "dev_under_budget": dev_with_reserve <= float(dev_budget_cny),
        "formal_under_budget": formal_with_reserve <= float(formal_budget_cny),
        "two_week_under_budget": two_week_total <= float(two_week_budget_cny),
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "dev_budget_cny": float(dev_budget_cny),
        "formal_budget_cny": float(formal_budget_cny),
        "two_week_budget_cny": float(two_week_budget_cny),
        "configured_network_retry_reserve_rate": configured_reserve,
        "observed_retry_overhead_rate": observed_reserve,
        "network_retry_reserve_rate": reserve,
        "extra_dev_reruns": max(0, int(extra_dev_reruns)),
        "dev_with_reserve_cny": round(dev_with_reserve, 6),
        "formal_with_reserve_cny": round(formal_with_reserve, 6),
        "two_week_total_cny": round(two_week_total, 6),
        "checks": checks,
    }


def _retry_summary(calls: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    attempt_count = 0.0
    retry_count = 0.0
    retry_error_count = 0.0
    failed_call_count = 0
    errors: Counter[str] = Counter()
    for call in calls:
        retry = _dict(call.get("retry"))
        call_attempts = _number(retry.get("attempt_count"), call.get("retry_attempt_count"), default=1.0)
        call_retries = _number(retry.get("retry_count"), call.get("retry_count"), default=max(0.0, call_attempts - 1.0))
        attempt_count += call_attempts
        retry_count += call_retries
        retry_error_count += _number(retry.get("error_count"), call.get("retry_error_count"), default=0.0)
        if call.get("success") is False or call.get("error"):
            failed_call_count += 1
        for attempt in _as_dict_list(retry.get("attempts")):
            error_type = attempt.get("error_type") or attempt.get("error") or attempt.get("status_code")
            if error_type:
                errors[str(error_type)] += 1
    llm_call_count = len(calls)
    observed_overhead = _safe_div(max(0.0, attempt_count - llm_call_count), llm_call_count, digits=6) or 0.0
    return {
        "llm_call_count": llm_call_count,
        "attempt_count": round(attempt_count, 4),
        "retry_count": round(retry_count, 4),
        "retry_error_count": round(retry_error_count, 4),
        "failed_llm_call_count": failed_call_count,
        "observed_retry_overhead_rate": observed_overhead,
        "top_retry_errors": [{"error": key, "count": value} for key, value in errors.most_common(10)],
    }


def _runtime_freeze_summary(
    manifest: Dict[str, Any],
    calls: Sequence[Dict[str, Any]],
    *,
    expected_max_tokens: int,
) -> Dict[str, Any]:
    runtime = _dict(manifest.get("runtime_config")) or _dict(manifest.get("model_config"))
    manifest_values = {field: runtime.get(field) for field in _RUNTIME_FIELDS}
    observed: Dict[str, List[Any]] = {field: [] for field in _RUNTIME_FIELDS}
    for call in calls:
        options = _dict(call.get("request_options"))
        for field in _RUNTIME_FIELDS:
            value = call.get(field)
            if value is None:
                value = options.get(field)
            observed[field].append(value)
    observed_unique = {field: _unique_values(values) for field, values in observed.items()}
    mismatch_fields = []
    for field in _RUNTIME_FIELDS:
        expected = _normalize_runtime_value(manifest_values.get(field))
        values = {_normalize_runtime_value(value) for value in observed_unique[field]}
        if not values:
            mismatch_fields.append(field)
        elif values != {expected}:
            mismatch_fields.append(field)
    expected_max_tokens_normalized = _normalize_runtime_value(expected_max_tokens)
    observed_max_token_values = {
        _normalize_runtime_value(value)
        for value in observed_unique.get("max_tokens", [])
    }
    manifest_matches_protocol = (
        _normalize_runtime_value(manifest_values.get("max_tokens"))
        == expected_max_tokens_normalized
    )
    observed_matches_protocol = observed_max_token_values == {expected_max_tokens_normalized}
    return {
        "consistent": not mismatch_fields,
        "manifest_values": manifest_values,
        "observed_request_values": observed_unique,
        "mismatch_fields": mismatch_fields,
        "strict_mode": runtime.get("strict_mode"),
        "cache_disabled": runtime.get("cache_disabled"),
        "trace_save_user_message": runtime.get("trace_save_user_message"),
        "deterministic_research_final_answer": runtime.get(
            "deterministic_research_final_answer"
        ),
        "final_answer_generation_mode": runtime.get("final_answer_generation_mode"),
        "day7_max_tokens_protocol": {
            "expected_max_tokens": int(expected_max_tokens),
            "manifest_matches_protocol": manifest_matches_protocol,
            "observed_matches_protocol": observed_matches_protocol,
            "observed_max_token_values": observed_unique.get("max_tokens", []),
        },
        "matches_day7_max_tokens_protocol": bool(calls)
        and manifest_matches_protocol
        and observed_matches_protocol,
    }


def _observed_scope(
    results: Sequence[Dict[str, Any]],
    rows: Sequence[Dict[str, Any]],
    summary: Dict[str, Any],
    manifest: Dict[str, Any],
    *,
    expected_dev_case_count: int,
    expected_dev_turn_count: int,
    expected_dev_raw_result_count: int,
) -> Dict[str, Any]:
    structure = _dict(manifest.get("benchmark_structure"))
    case_count = _int(
        structure.get("case_count"),
        summary.get("independent_case_count"),
        len({row.get("case_id") for row in rows if row.get("case_id")}),
        default=0,
    )
    turn_count = _int(
        structure.get("total_turn_count"),
        len({
            (
                row.get("case_id"),
                row.get("scenario_id"),
                row.get("turn_id"),
            )
            for row in rows
        }),
        default=0,
    )
    methods = sorted({str(result.get("method")) for result in results if result.get("method")})
    task_counts = Counter(str(row.get("task_type") or "unknown") for row in rows)
    return {
        "case_count": case_count,
        "turn_count": turn_count,
        "raw_result_count": len(rows),
        "method_count": len(methods),
        "methods": methods,
        "task_type_count": len(task_counts),
        "task_type_counts": dict(sorted(task_counts.items())),
        "expected": {
            "case_count": expected_dev_case_count,
            "turn_count": expected_dev_turn_count,
            "raw_result_count": expected_dev_raw_result_count,
        },
        "scope_matches_expected": (
            case_count == expected_dev_case_count
            and turn_count == expected_dev_turn_count
            and len(rows) == expected_dev_raw_result_count
        ),
    }


def _evidence_quality(
    dev_gate: Dict[str, Any],
    rows: Sequence[Dict[str, Any]],
    calls: Sequence[Dict[str, Any]],
    price: Dict[str, Any],
    *,
    token_cap_hit_rate_limit: float,
) -> Dict[str, Any]:
    token_complete_rows = sum(
        1
        for row in rows
        if row.get("prompt_tokens") is not None
        and row.get("completion_tokens") is not None
        and row.get("total_tokens") is not None
    )
    trace_loaded_rows = sum(1 for row in rows if row.get("trace_loaded") is True)
    trace_standardized_cost_values = [
        _number(call.get("standardized_estimated_cost"))
        for call in calls
        if call.get("standardized_estimated_cost") is not None
    ]
    token_positive_calls = [
        call
        for call in calls
        if _number(_nested(call, "usage", "total_tokens"), call.get("total_tokens"), default=0.0)
        > 0
    ]
    env_or_zero_calls = [
        call
        for call in calls
        if str(call.get("price_source_url") or "").strip() == "env_or_zero_default"
    ]
    output_length_risk = _output_length_risk_summary(
        calls,
        token_cap_hit_rate_limit=token_cap_hit_rate_limit,
    )
    return {
        "dev_gate_status": dev_gate.get("status"),
        "token_fields_complete": token_complete_rows == len(rows),
        "token_complete_rows": token_complete_rows,
        "trace_loaded_rows": trace_loaded_rows,
        "row_count": len(rows),
        "llm_call_count": len(calls),
        "mock_call_count": sum(_bool(call.get("mock")) or _bool(call.get("mock_used")) for call in calls),
        "fallback_call_count": sum(_bool(call.get("fallback")) or _bool(call.get("fallback_used")) for call in calls),
        "cache_hit_count": sum(_bool(call.get("cache_hit")) for call in calls),
        "price_snapshot_nonzero": price["input_usd_per_1m"] > 0 and price["output_usd_per_1m"] > 0,
        "trace_standardized_cost_sum": round(
            sum(value for value in trace_standardized_cost_values if value is not None),
            8,
        ),
        "trace_standardized_cost_positive_call_count": sum(
            1 for value in trace_standardized_cost_values if value is not None and value > 0
        ),
        "trace_token_positive_call_count": len(token_positive_calls),
        "trace_env_or_zero_default_call_count": len(env_or_zero_calls),
        "output_length_risk": output_length_risk,
        "completion_token_cap_hit_count": output_length_risk[
            "completion_token_cap_hit_count"
        ],
        "empty_and_token_capped_call_count": output_length_risk[
            "empty_and_token_capped_call_count"
        ],
        "trace_price_source_urls": sorted(
            {
                str(call.get("price_source_url") or "")
                for call in calls
                if str(call.get("price_source_url") or "").strip()
            }
        ),
        "actual_cost_available_call_count": sum(
            1 for call in calls if _number(call.get("actual_cost")) is not None
        ),
        "actual_cost_statuses": sorted(
            {
                str(call.get("actual_cost_status") or "")
                for call in calls
                if str(call.get("actual_cost_status") or "").strip()
            }
        ),
    }


def _output_length_risk_summary(
    calls: Sequence[Dict[str, Any]],
    *,
    token_cap_hit_rate_limit: float,
) -> Dict[str, Any]:
    capped_calls = []
    empty_calls = []
    empty_and_capped_calls = []
    max_token_values: Counter[str] = Counter()
    for index, call in enumerate(calls):
        max_tokens = _call_max_tokens(call)
        completion_tokens = _call_completion_tokens(call)
        output_chars = _number(call.get("output_chars"))
        if max_tokens is not None:
            max_token_values[str(int(max_tokens) if max_tokens.is_integer() else max_tokens)] += 1
        capped = (
            max_tokens is not None
            and completion_tokens is not None
            and completion_tokens >= max_tokens
        )
        empty = output_chars == 0
        ref = {
            "call_index": index,
            "call_id": call.get("call_id") or call.get("id"),
            "agent_name": call.get("agent_name"),
            "component": call.get("component"),
            "completion_tokens": completion_tokens,
            "max_tokens": max_tokens,
            "output_chars": output_chars,
        }
        if capped:
            capped_calls.append(ref)
        if empty:
            empty_calls.append(ref)
        if capped and empty:
            empty_and_capped_calls.append(ref)
    cap_rate = _safe_div(len(capped_calls), len(calls)) or 0.0
    return {
        "llm_call_count": len(calls),
        "completion_token_cap_hit_count": len(capped_calls),
        "completion_token_cap_hit_rate": cap_rate,
        "completion_token_cap_hit_rate_limit": float(token_cap_hit_rate_limit),
        "completion_token_cap_hit_rate_below_limit": cap_rate
        <= float(token_cap_hit_rate_limit),
        "empty_output_call_count": len(empty_calls),
        "empty_and_token_capped_call_count": len(empty_and_capped_calls),
        "request_max_token_values": dict(sorted(max_token_values.items())),
        "sample_token_capped_calls": capped_calls[:10],
        "sample_empty_and_token_capped_calls": empty_and_capped_calls[:10],
        "interpretation": (
            "High cap-hit or empty-and-capped counts indicate that output-length "
            "limits, not method capability, may be depressing baseline quality."
        ),
    }


def _call_completion_tokens(call: Dict[str, Any]) -> Optional[float]:
    usage = _dict(call.get("usage")) or _dict(call.get("tokens"))
    return _number(usage.get("completion_tokens"), usage.get("output_tokens"))


def _call_max_tokens(call: Dict[str, Any]) -> Optional[float]:
    options = _dict(call.get("request_options"))
    return _number(
        options.get("max_tokens"),
        call.get("max_tokens"),
    )


def _freeze_decision(
    *,
    freeze_allowed: bool,
    runtime_freeze: Dict[str, Any],
    budget_gate: Dict[str, Any],
    failed_checks: Sequence[str],
    quality_advisory_failed_checks: Sequence[str] = (),
) -> Dict[str, Any]:
    manifest_values = _dict(runtime_freeze.get("manifest_values"))
    status = "frozen_for_cost_and_runtime" if freeze_allowed else "not_frozen"
    rerun_required_checks = [
        check
        for check in failed_checks
        if check
        in {
            "trace_standardized_cost_nonzero",
            "trace_price_source_not_zero_default",
            "runtime_consistent",
            "runtime_max_tokens_matches_day7_protocol",
            "completion_token_cap_hit_rate_below_limit",
        }
    ]
    return {
        "status": status,
        "model": manifest_values.get("model"),
        "temperature": manifest_values.get("temperature"),
        "max_tokens": manifest_values.get("max_tokens"),
        "timeout_seconds": manifest_values.get("timeout_seconds"),
        "retry_max_attempts": manifest_values.get("retry_max_attempts"),
        "reasoning_effort": manifest_values.get("reasoning_effort"),
        "deterministic_research_final_answer": runtime_freeze.get(
            "deterministic_research_final_answer"
        ),
        "final_answer_generation_mode": runtime_freeze.get("final_answer_generation_mode"),
        "strict_mode": runtime_freeze.get("strict_mode"),
        "cache_disabled": runtime_freeze.get("cache_disabled"),
        "budget_status": budget_gate.get("status"),
        "failed_checks": list(failed_checks),
        "rerun_required": bool(rerun_required_checks),
        "rerun_required_checks": rerun_required_checks,
        "quality_advisory_failed_checks": list(quality_advisory_failed_checks),
        "quality_rerun_recommended": bool(quality_advisory_failed_checks),
        "quality_scope_note": (
            "This freezes the model/runtime parameters and the development-run "
            "quality advisory checks for the next experimental stage."
            if not quality_advisory_failed_checks
            else (
                "This freezes the model and runtime parameters for cost control only; "
                "method/output quality still requires a repaired development run."
            )
        ),
    }


def _resolve_price_snapshot(
    manifest: Dict[str, Any],
    *,
    input_usd_per_1m: Optional[float],
    output_usd_per_1m: Optional[float],
    price_source_url: Optional[str],
    price_snapshot_date: Optional[str],
    usd_to_cny_rate: float,
) -> Dict[str, Any]:
    model = str(_nested(manifest, "runtime_config", "model") or manifest.get("model") or "")
    manifest_snapshot = _dict(_nested(manifest, "costing", "price_snapshot"))
    manifest_input = _manifest_price_usd_per_1m(manifest_snapshot, "input")
    manifest_output = _manifest_price_usd_per_1m(manifest_snapshot, "output")
    default_input = GPT5_MINI_PRICE_INPUT_USD_PER_1M if model == "gpt-5-mini" else None
    default_output = GPT5_MINI_PRICE_OUTPUT_USD_PER_1M if model == "gpt-5-mini" else None
    input_price = _first_number(input_usd_per_1m, manifest_input, default_input, default=0.0)
    output_price = _first_number(output_usd_per_1m, manifest_output, default_output, default=0.0)
    source = (
        price_source_url
        or _text(manifest_snapshot.get("price_source_url"))
        or (GPT5_MINI_PRICE_SOURCE_URL if model == "gpt-5-mini" else "not_configured")
    )
    if source == "env_or_zero_default" and model == "gpt-5-mini":
        source = GPT5_MINI_PRICE_SOURCE_URL
    snapshot_date = (
        price_snapshot_date
        or _text(manifest_snapshot.get("price_snapshot_date"))
        or (GPT5_MINI_PRICE_SNAPSHOT_DATE if model == "gpt-5-mini" else datetime.utcnow().date().isoformat())
    )
    return {
        "schema_version": "ctp-frozen-price-snapshot-v1",
        "model": model or "unknown",
        "source_url": source,
        "snapshot_date": snapshot_date,
        "input_usd_per_1m": float(input_price),
        "output_usd_per_1m": float(output_price),
        "input_usd_per_1k": round(float(input_price) / 1000.0, 10),
        "output_usd_per_1k": round(float(output_price) / 1000.0, 10),
        "usd_to_cny_rate": float(usd_to_cny_rate),
        "currency": "USD",
        "derived_cny_currency": "CNY",
        "policy": (
            "Use an explicit frozen USD-per-1M-token snapshot for reproducible "
            "budget estimation, even when provider responses do not return billed cost."
        ),
    }


def _manifest_price_usd_per_1m(snapshot: Dict[str, Any], kind: str) -> Optional[float]:
    key = "input_token_unit_price" if kind == "input" else "output_token_unit_price"
    value = _number(snapshot.get(key))
    if value in (None, 0.0):
        return None
    currency = str(snapshot.get("currency") or "").upper()
    if currency and currency != "USD":
        return None
    unit = str(snapshot.get("price_unit") or "per_1k_tokens").lower()
    if unit in {"per_1m_tokens", "per_million_tokens"}:
        return value
    if unit in {"per_1k_tokens", "per_thousand_tokens"}:
        return value * 1000.0
    if unit in {"per_token"}:
        return value * 1_000_000.0
    return None


def _cost_usd(prompt_tokens: float, completion_tokens: float, price: Dict[str, Any]) -> float:
    return (
        prompt_tokens / 1_000_000.0 * _number(price.get("input_usd_per_1m"), default=0.0)
        + completion_tokens / 1_000_000.0 * _number(price.get("output_usd_per_1m"), default=0.0)
    )


def _usd_to_cny(cost_usd: float, price: Dict[str, Any]) -> float:
    return cost_usd * _number(price.get("usd_to_cny_rate"), default=DEFAULT_USD_TO_CNY_RATE)


def _usage(call: Dict[str, Any]) -> Dict[str, float]:
    usage = _dict(call.get("usage")) or _dict(call.get("tokens"))
    prompt = _number(usage.get("prompt_tokens"), usage.get("input_tokens"), default=0.0)
    completion = _number(usage.get("completion_tokens"), usage.get("output_tokens"), default=0.0)
    total = _number(usage.get("total_tokens"), usage.get("tokens_used"), default=prompt + completion)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def _attach_to_manifest(
    run_dir: Path,
    *,
    forecast: Dict[str, Any],
    json_path: Path,
    report_path: Path,
) -> None:
    manifest_path = run_dir / "experiment_manifest.json"
    manifest = _read_json_object(manifest_path)
    if not manifest:
        return
    results = _dict(manifest.get("results"))
    results.update(
        {
            "day7_cost_forecast_json": json_path.as_posix(),
            "day7_cost_forecast_report": report_path.as_posix(),
        }
    )
    manifest["results"] = results
    manifest["day7_cost_forecast"] = {
        "schema_version": DAY7_COST_FORECAST_SCHEMA_VERSION,
        "status": forecast.get("status"),
        "budget_status": _nested(forecast, "budget_gate", "status"),
        "freeze_status": _nested(forecast, "freeze_decision", "status"),
        "failed_checks": forecast.get("failed_checks") or [],
        "json": json_path.as_posix(),
        "markdown": report_path.as_posix(),
        "paper_claims_allowed": forecast.get("paper_claims_allowed"),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _trace_path(run_dir: Path, value: Any) -> Path:
    if not value:
        return run_dir / "__missing_trace__.jsonl"
    path = Path(str(value))
    if path.is_absolute():
        return path
    return run_dir / path


def _read_json_object(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_json_list(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _read_jsonl_first(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def _as_dict_list(value: Any) -> List[Dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _number(*values: Any, default: Optional[float] = None) -> Optional[float]:
    for value in values:
        if isinstance(value, bool) or value is None or value == "":
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                continue
    return default


def _first_number(*values: Any, default: float) -> float:
    value = _number(*values)
    return float(default if value is None else value)


def _int(*values: Any, default: int = 0) -> int:
    value = _number(*values)
    return int(default if value is None else value)


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _unique_values(values: Iterable[Any]) -> List[Any]:
    result: List[Any] = []
    seen = set()
    for value in values:
        key = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _normalize_runtime_value(value: Any) -> str:
    number = _number(value)
    if number is not None:
        return str(round(number, 8))
    return str(value)


def _safe_div(numerator: float, denominator: float, *, digits: int = 4) -> Optional[float]:
    if denominator in (0, 0.0):
        return None
    return round(float(numerator) / float(denominator), digits)


def _fmt(value: Any) -> str:
    number = _number(value)
    if number is not None:
        return str(round(number, 4))
    return "" if value is None else str(value)


def _money(value: Any) -> str:
    number = _number(value)
    if number is None:
        return ""
    return f"{number:.6f}".rstrip("0").rstrip(".")
