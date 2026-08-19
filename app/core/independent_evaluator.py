"""Compact method-blind evaluator for paper experiments."""
from __future__ import annotations

import json
import math
import random
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.schemas.experiment import (
    EXPERIMENT_EXECUTION_STATUSES,
    EXPERIMENT_OUTPUT_SCHEMA_VERSION,
    ExperimentMethodOutput,
)
from app.core.budget_gold import budget_gold_record_for_case
from app.core.fixed_data import FixedDataError, get_fixed_tourism_data
from app.core.no_date_weather_policy import (
    answer_has_no_date_weather_reminder,
    gold_requires_no_date_weather_reminder,
)
from app.core.qweather_snapshot import QWeatherSnapshotError, query_qweather_snapshot


EVALUATION_SCHEMA_VERSION = "ctp-independent-evaluation-v1"
EVALUATION_SUMMARY_SCHEMA_VERSION = "ctp-evaluation-summary-v1"
DEFAULT_RULE_CATALOG_PATH = (
    Path(__file__).resolve().parents[2] / "experiments" / "evaluation_rule_catalog.json"
)

_FAILED_STATUSES = {"failed", "error", "timeout"}
_ALLOWED_EXECUTION_STATUSES = set(EXPERIMENT_EXECUTION_STATUSES)
_OK_TOOL_RESULT_STATUSES = {"success", "no_result"}
_CITY_VALUE_ALIASES = {
    "\u5317\u4eac": "beijing",
    "beijing": "beijing",
    "\u676d\u5dde": "hangzhou",
    "hangzhou": "hangzhou",
    "\u897f\u5b89": "xian",
    "xian": "xian",
    "xi'an": "xian",
    "\u6df1\u5733": "shenzhen",
    "shenzhen": "shenzhen",
    "\u6842\u6797": "guilin",
    "guilin": "guilin",
    "\u4e0a\u6d77": "shanghai",
    "shanghai": "shanghai",
    "\u5e7f\u5dde": "guangzhou",
    "guangzhou": "guangzhou",
    "\u6210\u90fd": "chengdu",
    "chengdu": "chengdu",
    "\u91cd\u5e86": "chongqing",
    "chongqing": "chongqing",
    "\u6b66\u6c49": "wuhan",
    "wuhan": "wuhan",
    "\u957f\u6c99": "changsha",
    "changsha": "changsha",
    "\u5357\u4eac": "nanjing",
    "nanjing": "nanjing",
    "\u90d1\u5dde": "zhengzhou",
    "zhengzhou": "zhengzhou",
    "\u5357\u660c": "nanchang",
    "nanchang": "nanchang",
    "\u8d35\u9633": "guiyang",
    "guiyang": "guiyang",
    "\u62c9\u8428": "lhasa",
    "lhasa": "lhasa",
}
_CONSTRAINT_RULES = {
    "H_POI_GROUNDED": "poi_existence",
    "H_RAIN_SUITABILITY": "rain_attraction_suitability",
    "H_SENIOR_ACCESSIBILITY": "senior_accessibility",
}
_SCOPE_RULES = {
    "T_ATTRACTION_SINGLE_SCOPE": ("poi_search", "attractions", {"attraction"}),
    "T_WEATHER_SINGLE_SCOPE": ("weather_query", "weather", {"weather"}),
    "T_BUDGET_SINGLE_SCOPE": ("budget_calculator", "budget", {"budget"}),
}
_BUDGET_POLICY_VERSION_EXPECTED = "budget_policy_v2_0"
_BUDGET_CONTINGENCY_RATIO_EXPECTED = 0.10
_BUDGET_NUMERIC_TOLERANCE = 0.02
_BPCR_RULE_IDS = frozenset(
    {
        "H_BUDGET_EVIDENCE",
        "H_INTERCITY_SCOPE",
        "H_INTERCITY_COST",
        "H_INTERCITY_EVIDENCE",
        "H_BUDGET_POLICY_VERSION",
        "H_BUDGET_ACCOMMODATION_NIGHTS",
        "H_BUDGET_CONTINGENCY_LOCAL_ONLY",
        "H_BUDGET_TOTAL_FORMULA",
        "H_BUDGET_ITINERARY_CONSISTENCY",
        "H_BUDGET_UPGRADE_POLICY",
        "H_BUDGET_INDEPENDENT_RECALCULATION",
    }
)
_BOOTSTRAP_SAMPLES = 2000
_BOOTSTRAP_SEED = 20260725
_DESCRIPTIVE_METRICS = (
    ("stsr", ("metrics", "stsr")),
    ("evaluation_hcsr", ("metrics", "evaluation_hcsr")),
    ("bpcr", ("metrics", "bpcr")),
    ("agent_selection_f1", ("metrics", "agent_selection_f1")),
    ("tool_selection_f1", ("metrics", "tool_selection_f1")),
    ("agent_set_exact_match", ("metrics", "agent_set_exact_match")),
    ("necessary_agent_coverage", ("metrics", "necessary_agent_coverage")),
    ("extra_agent_count", ("metrics", "extra_agent_count")),
    ("duplicate_agent_count", ("metrics", "duplicate_agent_count")),
    ("planned_actual_agent_consistency", ("metrics", "planned_actual_agent_consistency")),
    ("agent_execution_success_rate", ("metrics", "agent_execution_success_rate")),
    ("tool_set_exact_match", ("metrics", "tool_set_exact_match")),
    ("necessary_tool_coverage", ("metrics", "necessary_tool_coverage")),
    ("extra_tool_count", ("metrics", "extra_tool_count")),
    ("duplicate_tool_count", ("metrics", "duplicate_tool_count")),
    ("forbidden_tool_call_count", ("metrics", "forbidden_tool_call_count")),
    ("planned_actual_tool_consistency", ("metrics", "planned_actual_tool_consistency")),
    ("tool_call_success_rate", ("metrics", "tool_call_success_rate")),
    ("tool_failure_count", ("metrics", "tool_failure_count")),
    ("total_tokens", ("metrics", "total_tokens")),
    ("estimated_cost", ("metrics", "estimated_cost")),
    ("standardized_estimated_cost", ("metrics", "standardized_estimated_cost")),
    ("actual_cost", ("metrics", "actual_cost")),
    ("llm_call_count", ("metrics", "llm_call_count")),
    ("agent_llm_call_count", ("metrics", "agent_llm_call_count")),
    ("api_call_count", ("metrics", "api_call_count")),
    ("prompt_tokens", ("metrics", "prompt_tokens")),
    ("completion_tokens", ("metrics", "completion_tokens")),
    ("agent_prompt_tokens", ("metrics", "agent_prompt_tokens")),
    ("agent_completion_tokens", ("metrics", "agent_completion_tokens")),
    ("agent_total_tokens", ("metrics", "agent_total_tokens")),
    ("successful_agent_call_count", ("metrics", "successful_agent_call_count")),
    ("failed_agent_call_count", ("metrics", "failed_agent_call_count")),
    ("successful_tool_call_count", ("metrics", "successful_tool_call_count")),
    ("failed_tool_call_count", ("metrics", "failed_tool_call_count")),
    ("llm_total_duration_ms", ("metrics", "llm_total_duration_ms")),
    ("agent_total_duration_ms", ("metrics", "agent_total_duration_ms")),
    ("tool_total_duration_ms", ("metrics", "tool_total_duration_ms")),
    ("api_total_duration_ms", ("metrics", "api_total_duration_ms")),
    ("latency_ms", ("latency_ms",)),
    ("agent_call_count", ("trace", "agent_call_count")),
    ("tool_call_count", ("trace", "tool_call_count")),
)
_PAIRED_METRICS = (
    ("stsr", ("metrics", "stsr"), True),
    ("evaluation_hcsr", ("metrics", "evaluation_hcsr"), False),
    ("itcsr", ("metrics", "itcsr"), False),
    ("bpcr", ("metrics", "bpcr"), False),
    ("agent_selection_f1", ("metrics", "agent_selection_f1"), False),
    ("tool_selection_f1", ("metrics", "tool_selection_f1"), False),
    ("agent_set_exact_match", ("metrics", "agent_set_exact_match"), True),
    ("necessary_agent_coverage", ("metrics", "necessary_agent_coverage"), False),
    ("planned_actual_agent_consistency", ("metrics", "planned_actual_agent_consistency"), True),
    ("agent_execution_success_rate", ("metrics", "agent_execution_success_rate"), False),
    ("tool_set_exact_match", ("metrics", "tool_set_exact_match"), True),
    ("necessary_tool_coverage", ("metrics", "necessary_tool_coverage"), False),
    ("planned_actual_tool_consistency", ("metrics", "planned_actual_tool_consistency"), True),
    ("tool_call_success_rate", ("metrics", "tool_call_success_rate"), False),
    ("total_tokens", ("metrics", "total_tokens"), False),
    ("estimated_cost", ("metrics", "estimated_cost"), False),
    ("standardized_estimated_cost", ("metrics", "standardized_estimated_cost"), False),
    ("actual_cost", ("metrics", "actual_cost"), False),
    ("llm_call_count", ("metrics", "llm_call_count"), False),
    ("agent_llm_call_count", ("metrics", "agent_llm_call_count"), False),
    ("api_call_count", ("metrics", "api_call_count"), False),
    ("prompt_tokens", ("metrics", "prompt_tokens"), False),
    ("completion_tokens", ("metrics", "completion_tokens"), False),
    ("agent_prompt_tokens", ("metrics", "agent_prompt_tokens"), False),
    ("agent_completion_tokens", ("metrics", "agent_completion_tokens"), False),
    ("agent_total_tokens", ("metrics", "agent_total_tokens"), False),
    ("llm_total_duration_ms", ("metrics", "llm_total_duration_ms"), False),
    ("agent_total_duration_ms", ("metrics", "agent_total_duration_ms"), False),
    ("tool_total_duration_ms", ("metrics", "tool_total_duration_ms"), False),
    ("api_total_duration_ms", ("metrics", "api_total_duration_ms"), False),
    ("latency_ms", ("latency_ms",), False),
    ("agent_call_count", ("trace", "agent_call_count"), False),
    ("tool_call_count", ("trace", "tool_call_count"), False),
)
_METHOD_SUMMARY_METRICS = (
    "bpcr",
    "bpcr_applicable_count",
    "bpcr_failed_count",
    "agent_set_exact_match",
    "necessary_agent_coverage",
    "extra_agent_count",
    "duplicate_agent_count",
    "planned_actual_agent_consistency",
    "agent_execution_success_rate",
    "tool_set_exact_match",
    "necessary_tool_coverage",
    "extra_tool_count",
    "duplicate_tool_count",
    "forbidden_tool_call_count",
    "planned_actual_tool_consistency",
    "tool_call_success_rate",
    "tool_failure_count",
    "total_tokens",
    "estimated_cost",
    "standardized_estimated_cost",
    "actual_cost",
    "llm_call_count",
    "agent_llm_call_count",
    "api_call_count",
    "prompt_tokens",
    "completion_tokens",
    "agent_prompt_tokens",
    "agent_completion_tokens",
    "agent_total_tokens",
    "planned_agent_count",
    "used_agent_count",
    "executed_agent_count",
    "successful_agent_call_count",
    "failed_agent_call_count",
    "duplicate_agent_call_count",
    "planned_executed_agent_coverage",
    "planned_tool_count",
    "called_tool_count",
    "executed_tool_count",
    "successful_tool_call_count",
    "failed_tool_call_count",
    "duplicate_tool_call_count",
    "planned_executed_tool_coverage",
    "llm_total_duration_ms",
    "agent_total_duration_ms",
    "tool_total_duration_ms",
    "api_total_duration_ms",
    "stage_total_duration_ms",
)
_METHOD_LABELS = {
    "llm_direct": "M0 Direct LLM",
    "single_agent": "M1 Single Agent",
    "fixed_multi_agent": "M2 Fixed Template Multi-Agent",
    "adaptive_multi_agent": "M3 Proposed",
}
_MISSING = object()


def load_rule_catalog(path: str | Path = DEFAULT_RULE_CATALOG_PATH) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def summarize_evaluation_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-case evaluation records into method-level paper metrics."""
    raw_by_method: Dict[str, List[Dict[str, Any]]] = {}
    for result in results:
        raw_by_method.setdefault(str(result.get("method") or "unknown"), []).append(result)
    quality_results = [result for result in results if _is_quality_evaluation_row(result)]
    quality_by_method: Dict[str, List[Dict[str, Any]]] = {}
    for result in quality_results:
        quality_by_method.setdefault(str(result.get("method") or "unknown"), []).append(result)
    by_method = {
        method: _aggregate_repeated_cases(rows)
        for method, rows in quality_by_method.items()
    }
    quality_units = {_evaluation_unit_id(result) for result in quality_results}
    scenario_ids = {
        str(result.get("scenario_id") or result.get("case_id") or "")
        for result in results
        if _is_scenario_row(result)
    }
    return {
        "schema_version": EVALUATION_SUMMARY_SCHEMA_VERSION,
        "result_count": len(results),
        "raw_run_count": len(results),
        "quality_result_count": len(quality_results),
        "unique_case_count": len(quality_units),
        "method_case_count": sum(len(rows) for rows in by_method.values()),
        "independent_case_count": len(quality_units),
        "scenario_case_count": len(scenario_ids),
        "quality_evaluation_scope": {
            "single_turn": "all single-turn cases",
            "multi_turn": "target_turn_only",
            "default_target_turn": "last turn when target_turn is not specified",
        },
        "repeat_aggregation": {
            "enabled": True,
            "unit": "evaluation_unit_id",
            "raw_result_count": len(results),
            "quality_result_count": len(quality_results),
            "scenario_turns_are_repeats": False,
        },
        "scenario_costs": _scenario_cost_summary(raw_by_method),
        "methods": {
            method: _method_summary(rows)
            for method, rows in sorted(by_method.items())
        },
        "paired_m3_vs_m2": _paired_summary(
            by_method.get("adaptive_multi_agent", []),
            by_method.get("fixed_multi_agent", []),
        ),
        "paired_statistics": _paired_statistics(
            by_method.get("adaptive_multi_agent", []),
            by_method.get("fixed_multi_agent", []),
        ),
    }


def render_paper_tables(summary: Dict[str, Any]) -> str:
    """Render compact Markdown tables from evaluation_summary.json."""
    methods = summary.get("methods") if isinstance(summary.get("methods"), dict) else {}
    paired = summary.get("paired_statistics") if isinstance(summary.get("paired_statistics"), dict) else {}
    scenario_cost_methods = _nested(summary, "scenario_costs", "methods")
    scenario_cost_methods = scenario_cost_methods if isinstance(scenario_cost_methods, dict) else {}
    lines = [
        "# Paper Result Tables",
        "",
        "## Method-level results",
        "",
        "| Method | Cases | STSR | HCSR | BPCR | Agent F1 | Tool F1 | Latency ms | Agent calls | Tool calls |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for method in _method_order(methods):
        row = methods.get(method) or {}
        lines.append(
            f"| {_method_label(method)} | {row.get('case_count', 0)} | {_fmt(row.get('stsr_rate'))} "
            f"| {_fmt(row.get('evaluation_hcsr_mean'))} | {_fmt(row.get('bpcr_mean'))} "
            f"| {_fmt(row.get('agent_selection_f1_mean'))} "
            f"| {_fmt(row.get('tool_selection_f1_mean'))} | {_fmt(row.get('latency_ms_mean'))} "
            f"| {_fmt(row.get('agent_call_count_mean'))} | {_fmt(row.get('tool_call_count_mean'))} |"
        )
    lines.extend([
        "",
        "## Agent/tool diagnostics",
        "",
        "| Method | Agent exact | Agent coverage | Extra agents | Dup agents | Plan=Actual agents | Agent success | Tool exact | Tool coverage | Extra tools | Dup tools | Forbidden tools | Tool success |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for method in _method_order(methods):
        row = methods.get(method) or {}
        lines.append(
            f"| {_method_label(method)} | {_fmt(row.get('agent_set_exact_match_mean'))} "
            f"| {_fmt(row.get('necessary_agent_coverage_mean'))} | {_fmt(row.get('extra_agent_count_mean'))} "
            f"| {_fmt(row.get('duplicate_agent_count_mean'))} | {_fmt(row.get('planned_actual_agent_consistency_mean'))} "
            f"| {_fmt(row.get('agent_execution_success_rate_mean'))} | {_fmt(row.get('tool_set_exact_match_mean'))} "
            f"| {_fmt(row.get('necessary_tool_coverage_mean'))} | {_fmt(row.get('extra_tool_count_mean'))} "
            f"| {_fmt(row.get('duplicate_tool_count_mean'))} | {_fmt(row.get('forbidden_tool_call_count_mean'))} "
            f"| {_fmt(row.get('tool_call_success_rate_mean'))} |"
        )
    lines.extend([
        "",
        "## Token and cost",
        "",
        "| Method | LLM calls | Prompt tokens | Completion tokens | Tokens/case | Cost/case | Standardized cost/case | Actual cost/case | Cost/success | Successful cases |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for method in _method_order(methods):
        row = methods.get(method) or {}
        lines.append(
            f"| {_method_label(method)} | {_fmt(row.get('llm_call_count_mean'))} "
            f"| {_fmt(row.get('prompt_tokens_mean'))} | {_fmt(row.get('completion_tokens_mean'))} "
            f"| {_fmt(row.get('total_tokens_mean'))} "
            f"| {_fmt(row.get('estimated_cost_mean'))} | {_fmt(row.get('standardized_estimated_cost_mean'))} "
            f"| {_fmt(row.get('actual_cost_mean'))} | {_fmt(row.get('cost_per_success_mean'))} "
            f"| {_fmt(row.get('successful_case_count'))} |"
        )
    lines.extend([
        "",
        "## Multi-turn scenario costs",
        "",
        "| Method | Scenarios | Target turn incremental LLM calls | Target turn incremental tokens | Target turn incremental tools | Scenario total LLM calls | Scenario total tokens | Scenario total tools | Scenario total latency ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for method in _method_order({**methods, **scenario_cost_methods}):
        row = scenario_cost_methods.get(method) or {}
        lines.append(
            f"| {_method_label(method)} | {row.get('scenario_count', 0)} "
            f"| {_fmt(row.get('target_increment_llm_call_count_mean'))} "
            f"| {_fmt(row.get('target_increment_total_tokens_mean'))} "
            f"| {_fmt(row.get('target_increment_called_tool_count_mean'))} "
            f"| {_fmt(row.get('scenario_total_llm_call_count_mean'))} "
            f"| {_fmt(row.get('scenario_total_total_tokens_mean'))} "
            f"| {_fmt(row.get('scenario_total_called_tool_count_mean'))} "
            f"| {_fmt(row.get('scenario_total_latency_ms_mean'))} |"
        )
    lines.extend([
        "",
        "## Paired M3 vs M2 statistics",
        "",
        "| Metric | Pairs | M3 mean | M2 mean | Delta mean | Delta median | Delta IQR | 95% CI | Test | p-value |",
        "|---|---:|---:|---:|---:|---:|---|---|---|---:|",
    ])
    for metric, stat in ((paired.get("metrics") or {}).items()):
        delta = stat.get("delta") if isinstance(stat, dict) else {}
        test = _test_summary(stat)
        lines.append(
            f"| {metric} | {stat.get('pair_count', 0)} | {_fmt(_nested(stat, 'm3', 'mean'))} "
            f"| {_fmt(_nested(stat, 'm2', 'mean'))} | {_fmt(delta.get('mean'))} "
            f"| {_fmt(delta.get('median'))} | {_fmt_range(delta.get('iqr'))} "
            f"| {_fmt_range(delta.get('bootstrap_ci_95'))} | {test['name']} | {_fmt(test['p_value'])} |"
        )
    return "\n".join(lines) + "\n"


def evaluate_case(
    *,
    case: Dict[str, Any],
    output: Dict[str, Any],
    trace: Optional[Dict[str, Any]] = None,
    catalog: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate one method output after generation. Method name is intentionally ignored."""
    catalog = catalog or load_rule_catalog()
    trace = trace or {}
    gold = _gold(case)
    gold = _merge_formal_budget_gold(case, gold)
    gold_task_type = _canon(gold.get("task_type") or case.get("task_type"), catalog)
    output_task_type = _canon(output.get("task_type") or gold_task_type, catalog)
    scoring_task_type = gold_task_type if gold_task_type != "unknown" else output_task_type
    rules = [_score_rule(rule, scoring_task_type, case, gold, output, trace, catalog) for rule in catalog["rules"]]
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "catalog_id": catalog["catalog_id"],
        "case_id": str(case.get("case_id") or output.get("case_id") or ""),
        "task_type": scoring_task_type,
        "output_task_type": output_task_type,
        "rules": rules,
        "metrics": _metrics(rules, gold, output, trace),
        "guards": list(catalog.get("evaluator_guards") or []),
    }


def _method_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    failed_rules: Counter[str] = Counter()
    tool_failures: Counter[str] = Counter()
    for row in rows:
        failed_rules.update(_list((row.get("metrics") or {}).get("evaluation_failed_rule_ids")))
        tool_failures.update(_list((row.get("metrics") or {}).get("tool_failure_types")))
    summary = {
        "case_count": len(rows),
        "raw_run_count": sum(_first_int(row.get("repeat_count")) or 1 for row in rows),
        "stsr_rate": _mean_metric(rows, "stsr"),
        "evaluation_hcsr_mean": _mean_num((row.get("metrics") or {}).get("evaluation_hcsr") for row in rows),
        "itcsr_mean": _mean_num((row.get("metrics") or {}).get("itcsr") for row in rows),
        "agent_selection_f1_mean": _mean_num((row.get("metrics") or {}).get("agent_selection_f1") for row in rows),
        "tool_selection_f1_mean": _mean_num((row.get("metrics") or {}).get("tool_selection_f1") for row in rows),
        "latency_ms_mean": _mean_num(row.get("latency_ms") for row in rows),
        "agent_call_count_mean": _mean_num((row.get("trace") or {}).get("agent_call_count") for row in rows),
        "tool_call_count_mean": _mean_num((row.get("trace") or {}).get("tool_call_count") for row in rows),
        "successful_case_count": sum((_number((row.get("metrics") or {}).get("stsr")) or 0.0) >= 0.5 for row in rows),
        "cost_per_success_mean": _cost_per_success(rows),
        "descriptive_statistics": _descriptive_statistics(rows),
        "top_failed_rules": [
            {"rule_id": rule_id, "count": count}
            for rule_id, count in failed_rules.most_common(10)
        ],
        "top_tool_failure_types": [
            {"failure_type": failure_type, "count": count}
            for failure_type, count in tool_failures.most_common(10)
        ],
    }
    summary.update({
        f"{metric}_mean": _mean_metric(rows, metric)
        for metric in _METHOD_SUMMARY_METRICS
    })
    return summary


def _paired_summary(m3_rows: List[Dict[str, Any]], m2_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    pairs = _paired_rows(m3_rows, m2_rows)
    return {
        "pair_count": len(pairs),
        "stsr_rate_delta": _mean_num(_num((m3.get("metrics") or {}).get("stsr")) - _num((m2.get("metrics") or {}).get("stsr")) for m3, m2 in pairs),
        "evaluation_hcsr_delta_mean": _mean_delta(pairs, "evaluation_hcsr"),
        "itcsr_delta_mean": _mean_delta(pairs, "itcsr"),
        "bpcr_delta_mean": _mean_delta(pairs, "bpcr"),
        "agent_call_count_delta_mean": _mean_num(_num((m3.get("trace") or {}).get("agent_call_count")) - _num((m2.get("trace") or {}).get("agent_call_count")) for m3, m2 in pairs),
        "tool_call_count_delta_mean": _mean_num(_num((m3.get("trace") or {}).get("tool_call_count")) - _num((m2.get("trace") or {}).get("tool_call_count")) for m3, m2 in pairs),
    }


def _paired_statistics(m3_rows: List[Dict[str, Any]], m2_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    pairs = _paired_rows(m3_rows, m2_rows)
    return {
        "comparison": "adaptive_multi_agent_vs_fixed_multi_agent",
        "pair_count": len(pairs),
        "bootstrap_samples": _BOOTSTRAP_SAMPLES,
        "bootstrap_seed": _BOOTSTRAP_SEED,
        "metrics": {
            name: _paired_metric_statistics(name, pairs, path, binary)
            for name, path, binary in _PAIRED_METRICS
        },
    }


def _score_rule(
    rule: Dict[str, Any],
    task_type: str,
    case: Dict[str, Any],
    gold: Dict[str, Any],
    output: Dict[str, Any],
    trace: Dict[str, Any],
    catalog: Dict[str, Any],
) -> Dict[str, Any]:
    if "*" not in rule["tasks"] and task_type not in rule["tasks"]:
        status, details = "na", {"reason": "task_not_applicable"}
    else:
        status, details = _check(rule["id"], case, gold, output, trace, catalog)
    status = _status(status)
    return {
        "id": rule["id"],
        "usage": rule["usage"],
        "status": status,
        "passed": True if status == "passed" else False if status == "failed" else None,
        "failure_code": rule["failure_code"] if status == "failed" else None,
        "details": details,
    }


def _check(
    rule_id: str,
    case: Dict[str, Any],
    gold: Dict[str, Any],
    output: Dict[str, Any],
    trace: Dict[str, Any],
    catalog: Dict[str, Any],
) -> tuple[str, Dict[str, Any]]:
    if rule_id == "G_SCHEMA_VALID":
        try:
            model = ExperimentMethodOutput.model_validate(output)
        except Exception as exc:
            return "failed", {"error": str(exc)}
        return "passed", {"schema_version": model.schema_version, "expected": EXPERIMENT_OUTPUT_SCHEMA_VERSION}
    if rule_id == "G_EXECUTION_STATUS_VALID":
        status = str(output.get("execution_status") or "").lower()
        trace_status = str(trace.get("status") or "").lower()
        failed = _has_failed_tool_evidence(output) or trace_status in _FAILED_STATUSES
        issues = []
        if status not in _ALLOWED_EXECUTION_STATUSES:
            issues.append("invalid_execution_status")
        if status == "failed":
            issues.append("execution_failed")
        if status == "completed" and failed:
            issues.append("completed_with_failed_evidence")
        if status == "clarification" and _has_trip_artifacts_or_execution(output, trace):
            issues.append("clarification_with_business_execution")
        if status == "failed" and not failed and _has_success_like_output(output):
            issues.append("failed_with_success_like_output")
        return ("passed" if not issues else "failed"), {"execution_status": status, "trace_status": trace_status, "failed_evidence": failed, "issues": issues}
    if rule_id == "G_FINAL_ANSWER_CONSISTENT":
        return _final_answer_rule(case, gold, output)
    if rule_id == "G_TASK_TYPE_MATCH":
        expected = _canon(gold.get("task_type") or case.get("task_type"), catalog)
        actual = _canon(output.get("task_type"), catalog)
        return ("passed" if expected != "unknown" and actual == expected else "failed"), {"expected": expected, "actual": actual}
    if rule_id == "H_TRIP_DAYS":
        expected = _first_int(gold.get("duration_days"), gold.get("duration"), gold.get("days"))
        actual = _first_int(output.get("trip_days"), len(output.get("daily_itinerary") or []))
        if expected is None:
            return "na", {"expected": expected, "actual": actual}
        return "passed" if actual == expected else "failed", {"expected": expected, "actual": actual}
    if rule_id == "H_ATTRACTION_COUNT_BOUNDS":
        minimum, maximum = _first_int(gold.get("min_attractions")), _first_int(gold.get("max_attractions"))
        count = len(_poi_refs(output))
        if minimum is None and maximum is None:
            return "na", {}
        return ("passed" if (minimum is None or count >= minimum) and (maximum is None or count <= maximum) else "failed"), {"minimum": minimum, "maximum": maximum, "actual": count}
    if rule_id == "H_DAILY_LOAD_LIMIT":
        limit = _first_int(gold.get("max_pois_per_day"))
        counts = [len(_refs_from_items(day.get("attractions") or day.get("pois") or day.get("activities") or [])) for day in output.get("daily_itinerary") or [] if isinstance(day, dict)]
        if limit is None:
            return "na", {"limit": limit, "daily_counts": counts}
        return "passed" if bool(counts) and max(counts) <= limit else "failed", {"limit": limit, "daily_counts": counts}
    if rule_id == "H_BUDGET_LIMIT":
        budget = output.get("budget") if isinstance(output.get("budget"), dict) else {}
        limit = _first_float(gold.get("budget_limit"), gold.get("max_budget"))
        actual = _first_float(budget.get("total"), budget.get("total_recommended"), budget.get("estimated_total"), budget.get("per_person"))
        if limit is None:
            return "na", {"limit": limit, "actual": actual}
        if _norm(output.get("task_type")) == "budget_query" and actual is not None and actual > limit:
            answer = str(output.get("final_answer") or "").lower()
            infeasible_terms = (
                "不足",
                "不够",
                "超出",
                "超预算",
                "不可行",
                "over_budget",
                "not enough",
                "insufficient",
            )
            if any(term in answer for term in infeasible_terms):
                return "passed", {
                    "limit": limit,
                    "actual": actual,
                    "budget_query_feasibility": "over_budget_reported",
                }
        return "passed" if actual is not None and actual <= limit else "failed", {"limit": limit, "actual": actual}
    if rule_id in _CONSTRAINT_RULES:
        check = _constraint_checks(output).get(_CONSTRAINT_RULES[rule_id])
        return (_status(check.get("status")), {"details": check.get("details") or {}}) if check else ("na", {"missing": True})
    if rule_id == "H_NO_DUPLICATE_POIS":
        refs = [_norm(item) for item in _planned_poi_refs(output)]
        duplicates = sorted(item for item, count in Counter(refs).items() if count > 1)
        return ("na", {"attraction_count": len(refs)}) if len(refs) < 2 else ("passed" if not duplicates else "failed", {"attraction_count": len(refs), "duplicates": duplicates})
    if rule_id == "H_MUST_INCLUDE_POIS":
        return _required_refs(gold, output, "must_include_pois", "required_pois", fail_on_present=False)
    if rule_id == "H_FORBIDDEN_POIS":
        return _required_refs(gold, output, "forbidden_pois", "avoid_pois", fail_on_present=True)
    if rule_id == "H_WEATHER_ADJUSTMENT_REQUIRED":
        required = bool(gold.get("weather_adjustment_required") or _contains_rain(output.get("weather")))
        return ("na", {}) if not required else ("passed" if output.get("weather_adjustments") else "failed", {"adjustment_count": len(output.get("weather_adjustments") or [])})
    if rule_id == "H_WEATHER_EVIDENCE":
        return _weather_evidence_rule(gold, output, trace)
    if rule_id == "H_NO_DATE_WEATHER_REMINDER":
        return _no_date_weather_reminder_rule(gold, output, trace)
    if rule_id == "H_BUDGET_EVIDENCE":
        return _tool_rule(output, trace, ["budget_calculator"]) if output.get("budget") or "budget_calculator" in _list(gold.get("required_tools")) else ("na", {})
    if rule_id == "H_BUDGET_POLICY_VERSION":
        return _budget_policy_version_rule(gold, output)
    if rule_id == "H_BUDGET_ACCOMMODATION_NIGHTS":
        return _budget_accommodation_nights_rule(gold, output)
    if rule_id == "H_BUDGET_CONTINGENCY_LOCAL_ONLY":
        return _budget_contingency_local_only_rule(gold, output)
    if rule_id == "H_BUDGET_TOTAL_FORMULA":
        return _budget_total_formula_rule(gold, output)
    if rule_id == "H_BUDGET_ITINERARY_CONSISTENCY":
        return _budget_itinerary_consistency_rule(gold, output)
    if rule_id == "H_BUDGET_UPGRADE_POLICY":
        return _budget_upgrade_policy_rule(gold, output)
    if rule_id == "H_BUDGET_INDEPENDENT_RECALCULATION":
        return _budget_independent_recalculation_rule(case, gold, output)
    if rule_id == "H_INTERCITY_SCOPE":
        return _intercity_scope_rule(gold, output)
    if rule_id == "H_INTERCITY_COST":
        return _intercity_cost_rule(output)
    if rule_id == "H_INTERCITY_EVIDENCE":
        return _intercity_evidence_rule(output)
    if rule_id == "H_TOOL_EVIDENCE":
        required = _list(gold.get("required_tools"))
        return _tool_rule(output, trace, required) if required else ("na", {})
    if rule_id == "T_CLARIFICATION_MISSING_FIELDS":
        expected = _list(gold.get("missing_slots") or gold.get("clarification_fields"))
        actual = _list(_nested(output, "metadata", "clarification_fields") or _nested(output, "metadata", "scheduler", "ticket", "clarification_fields") or _nested(output, "metadata", "scheduler", "decision", "clarification_fields"))
        missing_from_answer = [field for field in expected if not _clarification_answer_mentions(output, field)]
        status = "passed" if (set(expected) <= set(actual) and not missing_from_answer if expected else output.get("execution_status") == "clarification") else "failed"
        return status, {"expected": expected, "actual": actual, "missing_from_answer": missing_from_answer}
    if rule_id == "T_CLARIFICATION_NO_PREMATURE_PLAN":
        bad = bool(output.get("daily_itinerary") or output.get("attractions") or output.get("budget") or output.get("weather") or _agents(output, trace) or _called_tools(output, trace))
        return "failed" if bad else "passed", {"premature_output": bad}
    if rule_id == "T_GENERAL_CHAT_NO_BUSINESS_EXECUTION":
        agents, tools = _agents(output, trace), _called_tools(output, trace)
        return "passed" if not agents and not tools else "failed", {"agents": agents, "tools": tools}
    if rule_id == "T_GENERAL_CHAT_NO_TRIP_ARTIFACT":
        fields = [key for key in ("daily_itinerary", "attractions", "budget", "weather") if output.get(key)]
        return "passed" if not fields else "failed", {"artifact_fields": fields}
    if rule_id in _SCOPE_RULES:
        tool, artifact, allowed_agents = _SCOPE_RULES[rule_id]
        tools, agents = set(_called_tools(output, trace)), set(_agents(output, trace))
        present = bool(output.get(artifact)) or (artifact == "attractions" and bool(_poi_refs(output)))
        bad_tools, bad_agents = sorted(tools - {tool}), sorted(agents - allowed_agents - {"single_agent"})
        return ("passed" if present and not bad_tools and not bad_agents else "failed"), {"artifact_present": present, "unrelated_tools": bad_tools, "unrelated_agents": bad_agents}
    if rule_id == "T_PARTIAL_CHANGED_SLOTS_APPLIED":
        return _scheduler_slots(case, gold, output, "changed_slots", _list(gold.get("changed_slots")), changed=True)
    if rule_id == "T_PARTIAL_PRESERVED_SLOTS_KEPT":
        return _scheduler_slots(case, gold, output, "preserved_slots", _list(gold.get("preserved_slots")), changed=False)
    if rule_id == "T_PARTIAL_REUSE_VALIDITY":
        reuse = _nested(output, "metadata", "reuse_execution") or _nested(output, "metadata", "scheduler", "reuse_execution") or {}
        reused = _list(reuse.get("reused_agent_results") if isinstance(reuse, dict) else None) + _list(reuse.get("reused_tool_results") if isinstance(reuse, dict) else None)
        missing = _list(reuse.get("missing_reused_tool_results") if isinstance(reuse, dict) else None)
        return ("na", {}) if not reused else ("passed" if not missing else "failed", {"reused": reused, "missing": missing})
    if rule_id == "T_WEATHER_AFFECTED_CONTENT_ADJUSTED":
        return _weather_affected_adjusted(case, gold, output)
    if rule_id == "T_WEATHER_UNAFFECTED_CONTENT_PRESERVED":
        return _weather_unaffected_preserved(case, gold, output)
    if rule_id == "S_AGENT_SET_MATCH":
        return _set_rule(_agents(output, trace), gold.get("accepted_agent_sets"))
    if rule_id == "S_TOOL_SET_MATCH":
        return _set_rule(_called_tools(output, trace), gold.get("accepted_tool_sets"))
    if rule_id == "S_PLANNED_ACTUAL_AGENT_CONSISTENCY":
        planned = _list(output.get("planned_agents") or trace.get("planned_agents"))
        return ("na", {}) if not planned else ("passed" if set(planned) == set(_agents(output, trace)) else "failed", {"planned": planned, "actual": _agents(output, trace)})
    if rule_id == "S_PLANNED_ACTUAL_TOOL_CONSISTENCY":
        planned = _list(output.get("planned_tools") or trace.get("planned_tools"))
        return ("na", {}) if not planned else ("passed" if set(planned) == set(_called_tools(output, trace)) else "failed", {"planned": planned, "actual": _called_tools(output, trace)})
    if rule_id == "S_FORBIDDEN_GENERATION_TOOLS":
        forbidden, actual = set(_list(gold.get("forbidden_tools"))), set(_called_tools(output, trace))
        used = sorted(forbidden & actual)
        return ("na", {}) if not forbidden else ("passed" if not used else "failed", {"used": used})
    return "na", {"reason": "rule_not_implemented"}


def _metrics(rules: List[Dict[str, Any]], gold: Dict[str, Any], output: Dict[str, Any], trace: Dict[str, Any]) -> Dict[str, Any]:
    gates = [item for item in rules if item["usage"] == "stsr_gate" and item["status"] != "na"]
    hcsr = [item for item in rules if item["usage"] == "hcsr" and item["status"] != "na"]
    intercity_rules = [
        item
        for item in rules
        if item["id"].startswith("H_INTERCITY_") and item["status"] != "na"
    ]
    bpcr_rules = [
        item
        for item in rules
        if item["id"] in _BPCR_RULE_IDS and item["status"] != "na"
    ]
    h_pass = sum(item["status"] == "passed" for item in hcsr)
    h_fail = sum(item["status"] == "failed" for item in hcsr)
    intercity_pass = sum(item["status"] == "passed" for item in intercity_rules)
    intercity_fail = sum(item["status"] == "failed" for item in intercity_rules)
    bpcr_pass = sum(item["status"] == "passed" for item in bpcr_rules)
    bpcr_fail = sum(item["status"] == "failed" for item in bpcr_rules)
    failed_ids = [item["id"] for item in rules if item["status"] == "failed"]
    agents = _agents(output, trace)
    tools = _called_tools(output, trace)
    raw_agents = _agents_raw(output, trace)
    raw_tools = _called_tools_raw(output, trace)
    planned_agents = _list(output.get("planned_agents") or trace.get("planned_agents"))
    planned_tools = _list(output.get("planned_tools") or trace.get("planned_tools"))
    forbidden_tools = set(_list(gold.get("forbidden_tools")))
    agent_scores = _set_scores(agents, _best_set(agents, _sets(gold.get("accepted_agent_sets"))))
    tool_scores = _set_scores(tools, _best_set(tools, _sets(gold.get("accepted_tool_sets"))))
    stsr = bool(gates) and all(item["status"] == "passed" for item in gates) and h_fail == 0
    total_tokens = _trace_total_tokens(trace)
    estimated_cost = _trace_cost(trace)
    standardized_estimated_cost = _trace_standardized_cost(trace)
    actual_cost = _trace_actual_cost(trace)
    tool_failure_types = _tool_failure_types(output, trace)
    return {
        "stsr": stsr,
        "stsr_gate_applicable_count": len(gates),
        "stsr_gate_passed_count": sum(item["status"] == "passed" for item in gates),
        "stsr_gate_failed_count": sum(item["status"] == "failed" for item in gates),
        "evaluation_hcsr": None if not hcsr else round(h_pass / len(hcsr), 4),
        "evaluation_hcsr_applicable_count": len(hcsr),
        "evaluation_hcsr_passed_count": h_pass,
        "evaluation_hcsr_failed_count": h_fail,
        "itcsr": None if not intercity_rules else round(intercity_pass / len(intercity_rules), 4),
        "itcsr_applicable_count": len(intercity_rules),
        "itcsr_passed_count": intercity_pass,
        "itcsr_failed_count": intercity_fail,
        "bpcr": None if not bpcr_rules else round(bpcr_pass / len(bpcr_rules), 4),
        "bpcr_applicable_count": len(bpcr_rules),
        "bpcr_passed_count": bpcr_pass,
        "bpcr_failed_count": bpcr_fail,
        "evaluation_failed_rule_ids": failed_ids,
        "evaluation_failed_rule_count": len(failed_ids),
        "agent_selection_precision": agent_scores["precision"],
        "agent_selection_recall": agent_scores["recall"],
        "agent_selection_f1": agent_scores["f1"],
        "agent_set_exact_match": agent_scores["exact"],
        "necessary_agent_coverage": agent_scores["recall"],
        "extra_agent_count": agent_scores["extra"],
        "missing_agent_count": agent_scores["missing"],
        "duplicate_agent_count": _duplicate_count(raw_agents),
        "planned_actual_agent_consistency": _set_exact_rate(planned_agents, agents),
        "agent_execution_success_rate": _agent_success_rate(trace),
        "tool_selection_precision": tool_scores["precision"],
        "tool_selection_recall": tool_scores["recall"],
        "tool_selection_f1": tool_scores["f1"],
        "tool_set_exact_match": tool_scores["exact"],
        "necessary_tool_coverage": tool_scores["recall"],
        "extra_tool_count": tool_scores["extra"],
        "missing_tool_count": tool_scores["missing"],
        "duplicate_tool_count": _duplicate_count(raw_tools),
        "forbidden_tool_call_count": _forbidden_tool_call_count(raw_tools, forbidden_tools),
        "planned_actual_tool_consistency": _set_exact_rate(planned_tools, tools),
        "tool_call_success_rate": _tool_call_success_rate(output, trace),
        "tool_failure_count": len(tool_failure_types),
        "tool_failure_types": tool_failure_types,
        "total_tokens": total_tokens,
        "estimated_cost": estimated_cost,
        "standardized_estimated_cost": standardized_estimated_cost,
        "actual_cost": actual_cost,
        "cost_per_success": estimated_cost if stsr and estimated_cost is not None else None,
    }


def _has_trip_artifacts_or_execution(output: Dict[str, Any], trace: Dict[str, Any]) -> bool:
    return bool(
        output.get("daily_itinerary")
        or output.get("attractions")
        or output.get("budget")
        or output.get("weather")
        or _agents(output, trace)
        or _called_tools(output, trace)
    )


def _has_success_like_output(output: Dict[str, Any]) -> bool:
    return bool(
        str(output.get("final_answer") or "").strip()
        and (
            output.get("daily_itinerary")
            or output.get("attractions")
            or output.get("budget")
            or output.get("weather")
        )
    )


def _gold(case: Dict[str, Any]) -> Dict[str, Any]:
    gold: Dict[str, Any] = {}
    for key in ("gold", "expected"):
        if isinstance(case.get(key), dict):
            gold.update(case[key])
    ticket = case.get("expected_ticket") if isinstance(case.get("expected_ticket"), dict) else {}
    decision = case.get("expected_decision") if isinstance(case.get("expected_decision"), dict) else {}
    gold.setdefault("task_type", ticket.get("task_type") or case.get("task_type"))
    for key in ("missing_slots", "changed_slots", "preserved_slots"):
        if key in ticket:
            gold.setdefault(key, ticket[key])
    if "planned_agents" in decision:
        gold.setdefault("accepted_agent_sets", [decision.get("planned_agents") or []])
    if "planned_tools" in decision:
        gold.setdefault("accepted_tool_sets", [decision.get("planned_tools") or []])
        gold.setdefault("required_tools", decision.get("planned_tools") or [])
    if isinstance(gold.get("hard_constraints"), dict):
        gold.update({k: v for k, v in gold["hard_constraints"].items() if k not in gold})
    if isinstance(case.get("current_slots"), dict):
        gold.setdefault("current_slots", case["current_slots"])
    previous_state = case.get("previous_state") if isinstance(case.get("previous_state"), dict) else {}
    if isinstance(previous_state.get("slots"), dict):
        gold.setdefault("previous_slots", previous_state["slots"])
    previous_artifacts = _previous_artifacts_from_state(previous_state)
    if previous_artifacts:
        gold.setdefault("previous_artifacts", previous_artifacts)
    slots = {**(case.get("slots") or {}), **(case.get("current_slots") or {})}
    for target, aliases in {
        "duration_days": ("duration_days", "duration", "days", "trip_days"),
        "budget_limit": ("budget_limit", "budget", "budget_amount", "max_budget"),
        "traveler_group": ("traveler_group", "people", "people_type"),
    }.items():
        gold.setdefault(target, next((slots[key] for key in aliases if key in slots and slots[key] is not None), None))
    gold.setdefault("accepted_agent_sets", [_list(gold.get("selected_agents") or gold.get("agents"))] if gold.get("selected_agents") or gold.get("agents") else None)
    gold.setdefault("accepted_tool_sets", [_list(gold.get("selected_tools") or gold.get("tools"))] if gold.get("selected_tools") or gold.get("tools") else None)
    if not gold.get("required_tools") and gold.get("accepted_tool_sets"):
        gold["required_tools"] = gold["accepted_tool_sets"][0]
    return gold


def _merge_formal_budget_gold(case: Dict[str, Any], gold: Dict[str, Any]) -> Dict[str, Any]:
    record = budget_gold_record_for_case(case)
    if not record:
        return gold
    merged = dict(gold)
    merged["budget_gold_record"] = record
    merged.setdefault("input_slots", record.get("input_slots") or {})
    budget_policy = record.get("budget_policy_v2")
    if isinstance(budget_policy, dict):
        merged["budget_policy_v2"] = budget_policy
        for key in (
            "budget_scope",
            "requested_budget_scope",
            "computed_budget_scope",
            "scope_complete",
            "sufficiency_status",
            "intercity_transport_included",
            "mandatory_budget_disclaimer",
            "budget_limit",
            "duration_days",
            "people_count",
            "origin",
            "destination",
        ):
            if key in budget_policy:
                merged.setdefault(key, budget_policy.get(key))
    expected_scope = record.get("expected_scope_from_dataset")
    if isinstance(expected_scope, dict):
        for key, value in expected_scope.items():
            if value is not None:
                merged.setdefault(key, value)
    input_slots = record.get("input_slots")
    if isinstance(input_slots, dict):
        for key, value in input_slots.items():
            if value is not None:
                merged.setdefault(key, value)
    return merged


def _tool_rule(output: Dict[str, Any], trace: Dict[str, Any], required: List[str]) -> tuple[str, Dict[str, Any]]:
    missing = [name for name in required if not _tool_ok(name, output, trace)]
    return "passed" if not missing else "failed", {"required_tools": required, "missing_or_failed": missing}


def _weather_evidence_rule(gold: Dict[str, Any], output: Dict[str, Any], trace: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    if not _weather_evidence_applicable(gold, output):
        return "na", {"reason": "weather_not_required"}
    tool_status, tool_details = _tool_rule(output, trace, ["weather_query"])
    weather = output.get("weather") if isinstance(output.get("weather"), dict) else {}
    tool_data = _tool_result_data(output, "weather_query")
    mismatch_issues = _weather_payload_mismatch_issues(weather, tool_data) if weather and tool_data else []
    snapshot_issues = _weather_snapshot_mismatch_issues(tool_data) if tool_data else []
    expected_issues = _weather_expected_gold_issues(gold, weather or tool_data)
    fabrication_issues = _weather_fabrication_issues(weather or tool_data)
    issues: List[str] = []
    if tool_status != "passed":
        issues.append("weather_tool_evidence_missing_or_invalid")
    if weather and not tool_data:
        issues.append("weather_output_without_tool_data")
    if mismatch_issues:
        issues.append("output_tool_weather_mismatch")
    if snapshot_issues:
        issues.append("tool_weather_snapshot_mismatch")
    issues.extend(expected_issues)
    issues.extend(fabrication_issues)
    return (
        "passed" if not issues else "failed",
        {
            "issues": issues,
            "tool_evidence": tool_details,
            "mismatch_issues": mismatch_issues,
            "snapshot_issues": snapshot_issues,
            "expected_issues": expected_issues,
            "fabrication_issues": fabrication_issues,
            "expected_coverage_status": _expected_weather_coverage_status(gold),
            "actual_coverage_status": (weather or tool_data).get("coverage_status"),
            "expected_missing_dates": _expected_weather_missing_dates(gold),
            "actual_missing_dates": _weather_missing_dates(weather or tool_data),
        },
    )


def _no_date_weather_reminder_rule(
    gold: Dict[str, Any],
    output: Dict[str, Any],
    trace: Dict[str, Any],
) -> tuple[str, Dict[str, Any]]:
    if not gold_requires_no_date_weather_reminder(gold):
        return "na", {"reason": "no_date_weather_reminder_not_required"}

    called_tools = _called_tools(output, trace)
    tool_results = output.get("tool_results") if isinstance(output.get("tool_results"), dict) else {}
    weather_output = output.get("weather") if isinstance(output.get("weather"), dict) else {}
    weather_tool_data = _tool_result_data(output, "weather_query")
    issues: List[str] = []

    if not answer_has_no_date_weather_reminder(output.get("final_answer")):
        issues.append("no_date_weather_reminder_missing")
    if "weather_query" in called_tools:
        issues.append("no_date_weather_query_forbidden")
    if "weather_query" in tool_results:
        issues.append("no_date_weather_tool_result_forbidden")
    if _meaningful_weather_payload(weather_output) or _meaningful_weather_payload(weather_tool_data):
        issues.append("concrete_weather_fabricated")

    return (
        "passed" if not issues else "failed",
        {
            "issues": issues,
            "called_tools": called_tools,
            "weather_output_present": _meaningful_weather_payload(weather_output),
            "weather_tool_result_present": "weather_query" in tool_results,
            "weather_tool_data_present": _meaningful_weather_payload(weather_tool_data),
        },
    )


def _meaningful_weather_payload(value: Any) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    return any(raw not in (None, "", [], {}) for raw in value.values())


def _weather_evidence_applicable(gold: Dict[str, Any], output: Dict[str, Any]) -> bool:
    return bool(
        output.get("weather")
        or "weather_query" in _list(gold.get("required_tools"))
        or gold.get("weather_required") is True
        or _expected_weather_coverage_status(gold)
    )


def _tool_ok(name: str, output: Dict[str, Any], trace: Dict[str, Any]) -> bool:
    result = (output.get("tool_results") or {}).get(name) if isinstance(output.get("tool_results"), dict) else None
    return _valid_research_tool_result(name, result) and _tool_result_matches_output(name, result, output)


def _valid_research_tool_result(name: str, result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("schema_version") != "research_tool_result_v1":
        return False
    if str(result.get("tool_name") or "") != name:
        return False
    status = str(result.get("status") or "").lower()
    if status not in _OK_TOOL_RESULT_STATUSES:
        return False
    if result.get("success") is False or result.get("error"):
        return False
    if status == "success" and not _has_nonempty_data(result):
        return False
    return _has_offline_evidence(result)


def _has_nonempty_data(result: Dict[str, Any]) -> bool:
    data = result.get("data")
    if isinstance(data, dict):
        return any(value not in (None, "", [], {}) for value in data.values())
    if isinstance(data, list):
        return bool(data)
    return data not in (None, "")


def _tool_result_matches_output(name: str, result: Any, output: Dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return False
    status = str(result.get("status") or "").lower()
    if status == "no_result":
        return not _tool_output_present(name, output)
    if name == "poi_search":
        return _poi_tool_matches_output(result, output)
    if name == "weather_query":
        return _weather_tool_matches_output(result, output)
    if name == "budget_calculator":
        return _budget_tool_matches_output(result, output)
    return True


def _tool_output_present(name: str, output: Dict[str, Any]) -> bool:
    if name == "poi_search":
        return bool(_planned_poi_refs(output) or output.get("attractions"))
    if name == "weather_query":
        return bool(output.get("weather"))
    if name == "budget_calculator":
        return bool(output.get("budget"))
    return False


def _poi_tool_matches_output(result: Dict[str, Any], output: Dict[str, Any]) -> bool:
    selected = {_norm(ref) for ref in _planned_poi_refs(output)}
    if not selected:
        return True
    tool_refs = {_norm(label) for record in _tool_result_attractions_from_result(result) for label in _poi_labels(record)}
    return bool(tool_refs) and selected <= tool_refs


def _tool_result_attractions_from_result(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    attractions = data.get("attractions") if isinstance(data, dict) else []
    return [item for item in attractions if isinstance(item, dict)] if isinstance(attractions, list) else []


def _weather_tool_matches_output(result: Dict[str, Any], output: Dict[str, Any]) -> bool:
    weather = output.get("weather")
    if not isinstance(weather, dict) or not weather:
        return True
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    return not _weather_payload_mismatch_issues(weather, data)


def _weather_payload_mismatch_issues(actual: Dict[str, Any], expected: Dict[str, Any]) -> List[str]:
    if not isinstance(actual, dict) or not isinstance(expected, dict) or not expected:
        return ["weather_evidence_missing"]
    issues: List[str] = []
    for key in (
        "provider",
        "city_id",
        "location_id",
        "start_date",
        "end_date",
        "date",
        "requested_days",
        "coverage_days",
        "coverage_status",
        "scenario_type",
        "weather_type",
        "risk_level",
        "snapshot_id",
        "snapshot_combined_sha256",
    ):
        if key in actual and actual.get(key) not in (None, "", [], {}):
            if not _same_value(actual.get(key), expected.get(key)):
                issues.append(f"{key}_mismatch")
    for key in ("covered_dates", "missing_dates", "risk_tags"):
        if key in actual and actual.get(key) not in (None, "", [], {}):
            if _ordered_norm(_list(actual.get(key))) != _ordered_norm(_list(expected.get(key))):
                issues.append(f"{key}_mismatch")
    actual_terms = set(_weather_terms(actual))
    expected_terms = set(_weather_terms(expected))
    if actual_terms and not (expected_terms and actual_terms <= expected_terms):
        issues.append("weather_term_mismatch")
    issues.extend(_daily_weather_mismatch_issues(actual, expected))
    return _unique(issues)


def _daily_weather_mismatch_issues(actual: Dict[str, Any], expected: Dict[str, Any]) -> List[str]:
    actual_days = _weather_daily_items(actual)
    if not actual_days:
        return []
    expected_days = _weather_daily_items(expected)
    if not expected_days:
        return ["daily_weather_fabricated_without_evidence"]
    expected_by_date = {
        str(day.get("date") or ""): day
        for day in expected_days
        if isinstance(day, dict) and day.get("date")
    }
    issues: List[str] = []
    for index, actual_day in enumerate(actual_days):
        expected_day: Dict[str, Any] = {}
        actual_date = str(actual_day.get("date") or "")
        if actual_date and actual_date in expected_by_date:
            expected_day = expected_by_date[actual_date]
        elif index < len(expected_days):
            expected_day = expected_days[index]
        else:
            issues.append("daily_weather_extra_day")
            continue
        for key in (
            "date",
            "day_index",
            "request_day_index",
            "state",
            "weather",
            "day_weather",
            "night_weather",
            "temperature_min_c",
            "temperature_max_c",
            "precipitation_mm",
            "precipitation_probability",
            "wind_scale_day",
            "wind_speed_day_kmh",
            "humidity_percent",
            "uv_index",
            "risk_level",
        ):
            if key in actual_day and actual_day.get(key) not in (None, "", [], {}):
                if not _same_value(actual_day.get(key), expected_day.get(key)):
                    issues.append("daily_weather_value_mismatch")
                    break
        if "risk_tags" in actual_day and actual_day.get("risk_tags") not in (None, "", [], {}):
            if _ordered_norm(_list(actual_day.get("risk_tags"))) != _ordered_norm(_list(expected_day.get("risk_tags"))):
                issues.append("daily_weather_value_mismatch")
    return _unique(issues)


def _weather_snapshot_mismatch_issues(tool_data: Dict[str, Any]) -> List[str]:
    if not isinstance(tool_data, dict) or not tool_data:
        return []
    if str(tool_data.get("provider") or "") != "qweather_snapshot":
        return []
    city = tool_data.get("city_id") or tool_data.get("city")
    start_date = tool_data.get("start_date") or tool_data.get("date")
    days = _first_int(tool_data.get("requested_days"), tool_data.get("days"), len(_weather_daily_items(tool_data)) or None)
    if not city or not start_date or days is None:
        return []
    try:
        expected = query_qweather_snapshot(city=city, start_date=str(start_date), days=days)
    except QWeatherSnapshotError as exc:
        return [f"snapshot_requery_failed:{exc}"]
    return _weather_payload_mismatch_issues(tool_data, expected)


def _weather_expected_gold_issues(gold: Dict[str, Any], weather: Dict[str, Any]) -> List[str]:
    if not isinstance(weather, dict) or not weather:
        return ["weather_missing"] if gold.get("weather_required") is True else []
    issues: List[str] = []
    expected_status = _expected_weather_coverage_status(gold)
    if expected_status and str(weather.get("coverage_status") or "") != expected_status:
        issues.append("expected_coverage_status_mismatch")
    expected_missing = _expected_weather_missing_dates(gold)
    if expected_missing is not None and _ordered_norm(_weather_missing_dates(weather)) != _ordered_norm(expected_missing):
        issues.append("expected_missing_dates_mismatch")
    return issues


def _weather_fabrication_issues(weather: Dict[str, Any]) -> List[str]:
    if not isinstance(weather, dict) or not weather:
        return []
    coverage_status = str(weather.get("coverage_status") or "")
    missing_dates = set(_weather_missing_dates(weather))
    daily_dates = {
        str(day.get("date") or "")
        for day in _weather_daily_items(weather)
        if isinstance(day, dict) and day.get("date")
    }
    issues: List[str] = []
    if coverage_status == "out_of_range" and _weather_daily_items(weather):
        issues.append("out_of_range_daily_weather_fabricated")
    if missing_dates & daily_dates:
        issues.append("missing_date_weather_fabricated")
    return issues


def _expected_weather_coverage_status(gold: Dict[str, Any]) -> str:
    return str(
        gold.get("expected_weather_coverage_status")
        or gold.get("weather_coverage")
        or gold.get("coverage_status")
        or ""
    ).strip()


def _expected_weather_missing_dates(gold: Dict[str, Any]) -> Optional[List[str]]:
    if "expected_weather_missing_dates" not in gold:
        return None
    return _list(gold.get("expected_weather_missing_dates"))


def _weather_missing_dates(weather: Dict[str, Any]) -> List[str]:
    return _list(weather.get("missing_dates")) if isinstance(weather, dict) else []


def _weather_daily_items(weather: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(weather, dict):
        return []
    for key in ("daily_weather", "daily_forecasts", "forecast"):
        value = weather.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _budget_tool_matches_output(result: Dict[str, Any], output: Dict[str, Any]) -> bool:
    budget = output.get("budget")
    if not isinstance(budget, dict) or not budget:
        return True
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    output_total, evidence_total = _budget_total(budget), _budget_total(data)
    if output_total is not None:
        return evidence_total is not None and abs(output_total - evidence_total) <= 1e-9
    common = set(budget) & set(data)
    return bool(common) and all(_same_value(budget[key], data[key]) for key in common)


def _has_offline_evidence(result: Dict[str, Any]) -> bool:
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    data_metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    source_modes = {
        "acceptance_fixture",
        "day5_acceptance_fixture",
        "deterministic_evaluator",
        "fixed_offline_dataset",
        "frozen_offline",
    }
    return (
        metadata.get("offline") is True
        or data.get("offline") is True
        or data_metadata.get("offline") is True
        or str(metadata.get("source_mode") or "") in source_modes
        or str(data_metadata.get("source_mode") or "") in source_modes
    )


def _final_answer_rule(case: Dict[str, Any], gold: Dict[str, Any], output: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    answer = str(output.get("final_answer") or "").strip()
    if not answer:
        return "failed", {"issues": ["empty_final_answer"]}

    issues: List[str] = []
    selected = _poi_records_from_output(output)
    missing_pois = [
        _poi_primary_label(record)
        for record in selected
        if not any(_answer_contains(answer, label) for label in _poi_labels(record))
    ]
    if missing_pois:
        issues.append("structured_poi_missing_from_answer")

    selected_keys = {_norm(label) for record in selected for label in _poi_labels(record)}
    fictional = []
    for record in _poi_records_from_tool_results(output):
        labels = _poi_labels(record)
        if labels and not selected_keys.intersection(_norm(label) for label in labels):
            if any(_answer_contains(answer, label) for label in labels):
                fictional.append(_poi_primary_label(record))
    if fictional:
        issues.append("answer_mentions_unselected_poi")

    budget_total = _budget_total(output.get("budget"))
    if budget_total is not None and not _answer_contains_number(answer, budget_total):
        issues.append("budget_total_missing_from_answer")

    weather_terms = _weather_answer_terms(output.get("weather"))
    if weather_terms and not any(_answer_contains(answer, term) for term in weather_terms):
        issues.append("weather_missing_from_answer")

    missing_clarification_fields: List[str] = []
    if _norm(gold.get("task_type") or case.get("task_type")) == "clarification":
        expected_fields = _list(gold.get("missing_slots") or gold.get("clarification_fields"))
        missing_clarification_fields = [field for field in expected_fields if not _clarification_answer_mentions(output, field)]
        if missing_clarification_fields:
            issues.append("clarification_fields_missing_from_answer")

    details = {
        "issues": issues,
        "missing_pois": missing_pois,
        "unselected_pois_mentioned": fictional,
        "budget_total": budget_total,
        "weather_terms": weather_terms,
        "missing_clarification_fields": missing_clarification_fields,
    }
    return ("passed" if not issues else "failed"), details


def _clarification_answer_mentions(output: Dict[str, Any], field: str) -> bool:
    answer = str(output.get("final_answer") or "").lower()
    aliases = {
        "start_date": ["start_date", "start date", "date", "when", "出发", "日期", "时间"],
        "duration_days": ["duration_days", "duration", "days", "how many days", "几天", "天数", "时长"],
        "destination": ["destination", "city", "where", "目的地", "城市", "去哪"],
        "budget": ["budget", "cost", "费用", "预算", "多少钱"],
        "budget_amount": ["budget_amount", "budget", "cost", "费用", "预算", "多少钱"],
        "people_count": ["people", "traveler", "人数", "几个人"],
    }
    terms = aliases.get(_norm(field), [str(field).lower(), str(field).replace("_", " ").lower()])
    return any(term and term.lower() in answer for term in terms)


def _weather_terms(value: Any) -> List[str]:
    weather = value if isinstance(value, dict) else {}
    labels = _list(weather.get("scenario_type")) + _list(weather.get("weather_type")) + _list(weather.get("condition")) + _list(weather.get("state")) + _list(weather.get("weather"))
    for day in weather.get("daily_weather") or []:
        if isinstance(day, dict):
            labels.extend(_list(day.get("scenario_type")) + _list(day.get("weather_type")) + _list(day.get("condition")) + _list(day.get("state")) + _list(day.get("weather")))
    return [_norm(label) for label in _unique(labels) if _norm(label)]


def _poi_records_from_output(output: Dict[str, Any]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for item in output.get("attractions") or []:
        if isinstance(item, dict):
            records.append(item)
    for day in output.get("daily_itinerary") or []:
        if not isinstance(day, dict):
            continue
        for item in day.get("attractions") or day.get("pois") or day.get("activities") or []:
            if isinstance(item, dict):
                records.append(item)
    return _unique_poi_records(records)


def _poi_records_from_tool_results(output: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = (output.get("tool_results") or {}).get("poi_search") if isinstance(output.get("tool_results"), dict) else None
    data = result.get("data") if isinstance(result, dict) and isinstance(result.get("data"), dict) else {}
    return _unique_poi_records([item for item in data.get("attractions") or [] if isinstance(item, dict)])


def _unique_poi_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, result = set(), []
    for record in records:
        labels = [_norm(label) for label in _poi_labels(record)]
        key = next((label for label in labels if label), "")
        if key and key not in seen:
            seen.add(key)
            result.append(record)
    return result


def _poi_labels(record: Dict[str, Any]) -> List[str]:
    nested = record.get("poi") if isinstance(record.get("poi"), dict) else {}
    return _unique(_list(record.get("poi_id")) + _list(record.get("id")) + _list(record.get("name")) + _list(nested.get("poi_id")) + _list(nested.get("id")) + _list(nested.get("name")))


def _poi_primary_label(record: Dict[str, Any]) -> str:
    labels = _poi_labels(record)
    return labels[-1] if labels else ""


def _answer_contains(answer: str, term: Any) -> bool:
    text = str(term or "").strip()
    return bool(text) and text.lower() in answer.lower()


def _answer_contains_number(answer: str, value: float) -> bool:
    rounded = _round4(value)
    candidates = {
        str(int(rounded)) if float(rounded).is_integer() else str(rounded),
        str(rounded),
        f"{rounded:,.4f}".rstrip("0").rstrip("."),
        f"{rounded:,.2f}",
    }
    normalized_answer = answer.replace(",", "")
    return any(item in answer or item.replace(",", "") in normalized_answer for item in candidates)


def _budget_total(value: Any) -> Optional[float]:
    budget = value if isinstance(value, dict) else {}
    return _first_float(
        budget.get("total"),
        budget.get("total_recommended"),
        budget.get("estimated_total"),
        budget.get("confirmed_total_cost"),
        budget.get("per_person"),
    )


def _budget_policy_version_rule(gold: Dict[str, Any], output: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    if not _budget_policy_applicable(gold, output):
        return "na", {"reason": "budget_policy_not_applicable"}
    budget = _budget_payload(output)
    if not budget:
        return "failed", {"reason": "budget_missing"}
    expected = str(
        _nested(gold, "budget_policy_v2", "budget_policy_version")
        or gold.get("budget_policy_version")
        or _BUDGET_POLICY_VERSION_EXPECTED
    )
    actual = str(
        budget.get("budget_policy_version")
        or _nested(budget, "budget_policy", "version")
        or ""
    )
    return (
        "passed" if actual == expected else "failed",
        {"expected": expected, "actual": actual},
    )


def _budget_accommodation_nights_rule(gold: Dict[str, Any], output: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    if not _budget_policy_applicable(gold, output):
        return "na", {"reason": "budget_policy_not_applicable"}
    budget = _budget_payload(output)
    if not budget:
        return "failed", {"reason": "budget_missing"}
    duration = _first_int(gold.get("duration_days"), output.get("trip_days"), len(output.get("daily_itinerary") or []))
    if duration is None:
        return "failed", {"reason": "duration_missing"}
    people_count = _first_int(
        gold.get("people_count"),
        budget.get("people_count"),
        budget.get("num_travelers"),
        _nested(budget, "intercity_transport", "people_count"),
    )
    expected_nights = max(duration - 1, 0)
    expected_rooms = math.ceil(people_count / 2) if people_count else None
    accommodation = _budget_breakdown_section(budget, "accommodation")
    actual_nights = _first_int(accommodation.get("night_count"), budget.get("nights"))
    actual_rooms = _first_int(accommodation.get("room_count"), budget.get("rooms"))
    reference_price = _first_float(accommodation.get("reference_price_cny"))
    actual_cost = _first_float(accommodation.get("recommended"), accommodation.get("estimated_cost"))
    issues: List[str] = []
    if actual_nights is None or actual_nights != expected_nights:
        issues.append("night_count_mismatch")
    if expected_rooms is not None and actual_rooms is not None and actual_rooms != expected_rooms:
        issues.append("room_count_mismatch")
    expected_accommodation_cost = None
    if reference_price is not None and expected_rooms is not None:
        expected_accommodation_cost = round(reference_price * expected_rooms * expected_nights, 2)
        if actual_cost is None or not _money_close(actual_cost, expected_accommodation_cost):
            issues.append("accommodation_cost_formula_mismatch")
    return (
        "passed" if not issues else "failed",
        {
            "duration_days": duration,
            "people_count": people_count,
            "expected_nights": expected_nights,
            "actual_nights": actual_nights,
            "expected_rooms": expected_rooms,
            "actual_rooms": actual_rooms,
            "reference_price_cny": reference_price,
            "expected_accommodation_cost": expected_accommodation_cost,
            "actual_accommodation_cost": actual_cost,
            "issues": issues,
        },
    )


def _budget_contingency_local_only_rule(gold: Dict[str, Any], output: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    if not _budget_policy_applicable(gold, output):
        return "na", {"reason": "budget_policy_not_applicable"}
    budget = _budget_payload(output)
    if not budget:
        return "failed", {"reason": "budget_missing"}
    local_basic = _budget_local_basic_cost(budget)
    contingency = _budget_contingency_amount(budget)
    ratio = _first_float(_nested(budget, "budget_policy", "contingency_ratio"))
    if local_basic is None or contingency is None:
        return "failed", {
            "reason": "missing_formula_field",
            "local_basic_cost": local_basic,
            "contingency_amount": contingency,
        }
    expected = round(local_basic * _BUDGET_CONTINGENCY_RATIO_EXPECTED, 2)
    issues: List[str] = []
    if not _money_close(contingency, expected):
        issues.append("contingency_formula_mismatch")
    if ratio is not None and not _money_close(ratio, _BUDGET_CONTINGENCY_RATIO_EXPECTED):
        issues.append("contingency_ratio_mismatch")
    return (
        "passed" if not issues else "failed",
        {
            "local_basic_cost": local_basic,
            "expected_contingency": expected,
            "actual_contingency": contingency,
            "expected_ratio": _BUDGET_CONTINGENCY_RATIO_EXPECTED,
            "actual_ratio": ratio,
            "issues": issues,
        },
    )


def _budget_total_formula_rule(gold: Dict[str, Any], output: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    if not _budget_policy_applicable(gold, output):
        return "na", {"reason": "budget_policy_not_applicable"}
    budget = _budget_payload(output)
    if not budget:
        return "failed", {"reason": "budget_missing"}
    local_basic = _budget_local_basic_cost(budget)
    contingency = _budget_contingency_amount(budget)
    intercity_cost = _budget_intercity_cost(budget)
    total = _budget_recommended_total(budget)
    local_total = _first_float(budget.get("local_total_recommended"), budget.get("local_total"))
    if local_basic is None or contingency is None or intercity_cost is None or total is None:
        return "failed", {
            "reason": "missing_formula_field",
            "local_basic_cost": local_basic,
            "contingency_amount": contingency,
            "intercity_transport_cost": intercity_cost,
            "total": total,
        }
    expected_local_total = round(local_basic + contingency, 2)
    expected_total = round(expected_local_total + intercity_cost, 2)
    issues: List[str] = []
    if local_total is not None and not _money_close(local_total, expected_local_total):
        issues.append("local_total_formula_mismatch")
    if not _money_close(total, expected_total):
        issues.append("total_formula_mismatch")
    return (
        "passed" if not issues else "failed",
        {
            "local_basic_cost": local_basic,
            "contingency_amount": contingency,
            "intercity_transport_cost": intercity_cost,
            "expected_local_total": expected_local_total,
            "actual_local_total": local_total,
            "expected_total": expected_total,
            "actual_total": total,
            "issues": issues,
        },
    )


def _budget_itinerary_consistency_rule(gold: Dict[str, Any], output: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    if not _budget_policy_applicable(gold, output):
        return "na", {"reason": "budget_policy_not_applicable"}
    budget = _budget_payload(output)
    if not budget:
        return "failed", {"reason": "budget_missing"}
    audit = _nested(output, "metadata", "budget_itinerary_consistency")
    if isinstance(audit, dict) and "consistent" in audit:
        return (
            "passed" if bool(audit.get("consistent")) else "failed",
            {
                "source": "metadata_audit",
                "audit_status": audit.get("status"),
                "final_itinerary_unique_poi_ids": audit.get("final_itinerary_unique_poi_ids"),
                "budget_selected_poi_ids": audit.get("budget_selected_poi_ids"),
                "ticket_source": audit.get("ticket_source"),
            },
        )
    final_refs = _ordered_norm(_planned_poi_refs(output))
    budget_refs = _ordered_norm(_budget_selected_poi_ids(budget))
    ticket_source = _budget_ticket_source(budget)
    if not final_refs and ticket_source == "standard_reference_poi_combo":
        return "passed", {
            "source": "computed_from_output",
            "reason": "standard_reference_no_final_itinerary",
            "final_itinerary_unique_poi_ids": final_refs,
            "budget_selected_poi_ids": budget_refs,
            "ticket_source": ticket_source,
        }
    if not final_refs and _norm(output.get("task_type")) == "budget_query":
        return "passed", {
            "source": "computed_from_output",
            "reason": "budget_query_without_final_itinerary",
            "final_itinerary_unique_poi_ids": final_refs,
            "budget_selected_poi_ids": budget_refs,
            "ticket_source": ticket_source,
        }
    consistent = bool(final_refs) and final_refs == budget_refs
    return (
        "passed" if consistent else "failed",
        {
            "source": "computed_from_output",
            "final_itinerary_unique_poi_ids": final_refs,
            "budget_selected_poi_ids": budget_refs,
            "ticket_source": ticket_source,
            "issues": [] if consistent else ["itinerary_budget_poi_mismatch"],
        },
    )


def _budget_upgrade_policy_rule(gold: Dict[str, Any], output: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    if not _budget_policy_applicable(gold, output):
        return "na", {"reason": "budget_policy_not_applicable"}
    budget = _budget_payload(output)
    if not budget:
        return "failed", {"reason": "budget_missing"}
    policy = budget.get("budget_policy") if isinstance(budget.get("budget_policy"), dict) else {}
    if not policy:
        return "failed", {"reason": "budget_policy_missing"}
    upgrade_decision = str(policy.get("upgrade_decision") or "")
    upgrade_applied = _list(policy.get("upgrade_applied"))
    hotel_tier = str(policy.get("hotel_tier") or _nested(budget, "breakdown", "accommodation", "tier") or "")
    food_tier = str(policy.get("food_tier") or _nested(budget, "breakdown", "food", "tier") or "")
    gold_slots = gold.get("input_slots") if isinstance(gold.get("input_slots"), dict) else gold
    explicit_hotel_preference = bool(gold_slots.get("hotel_level"))
    explicit_food_preference = bool(gold_slots.get("food_level"))
    explicit_preference = (
        upgrade_decision.startswith("explicit_")
        or explicit_hotel_preference
        or explicit_food_preference
    )
    auto_upgrade = upgrade_decision.startswith("auto_upgrade") or (
        bool(upgrade_applied) and not explicit_preference
    )
    allowed_decisions = {
        "economic_baseline",
        "economic_baseline_over_budget",
        "explicit_preference_applied",
        "explicit_preference_applied_over_budget",
    }
    issues: List[str] = []
    if policy.get("economic_baseline_first") is not True:
        issues.append("economic_baseline_first_missing")
    if auto_upgrade:
        issues.append("auto_upgrade_forbidden")
    if policy.get("auto_upgrade_enabled") is True or policy.get("automatic_upgrade_allowed") is True:
        issues.append("auto_upgrade_enabled_by_policy")
    if upgrade_decision and upgrade_decision not in allowed_decisions:
        issues.append("upgrade_decision_not_allowed")
    if upgrade_decision.startswith("explicit_") and not (
        explicit_hotel_preference or explicit_food_preference
    ):
        issues.append("explicit_preference_without_gold_constraint")
    if not explicit_hotel_preference and hotel_tier in {"comfort", "premium", "luxury"}:
        issues.append("non_explicit_hotel_tier")
    if not explicit_food_preference and food_tier in {"comfort", "premium", "luxury"}:
        issues.append("non_explicit_food_tier")
    if policy.get("selected_scheme_id") == "PREF" and not explicit_preference:
        issues.append("preference_scheme_without_explicit_preference")
    if not issues and not (explicit_hotel_preference or explicit_food_preference):
        return "na", {
            "reason": "no_explicit_tier_constraint",
            "hotel_tier": hotel_tier,
            "food_tier": food_tier,
            "upgrade_decision": upgrade_decision,
        }
    return (
        "passed" if not issues else "failed",
        {
            "upgrade_decision": upgrade_decision,
            "upgrade_applied": upgrade_applied,
            "hotel_tier": hotel_tier,
            "food_tier": food_tier,
            "explicit_hotel_preference": explicit_hotel_preference,
            "explicit_food_preference": explicit_food_preference,
            "auto_upgrade_enabled": policy.get("auto_upgrade_enabled"),
            "automatic_upgrade_allowed": policy.get("automatic_upgrade_allowed"),
            "issues": issues,
        },
    )


def _budget_independent_recalculation_rule(
    case: Dict[str, Any],
    gold: Dict[str, Any],
    output: Dict[str, Any],
) -> tuple[str, Dict[str, Any]]:
    record = gold.get("budget_gold_record") if isinstance(gold.get("budget_gold_record"), dict) else None
    if not record:
        case_id = str(case.get("case_id") or case.get("scenario_id") or "")
        if case_id.startswith("ctp100_v2_") and _budget_policy_applicable(gold, output):
            return "failed", {"reason": "formal_budget_gold_record_missing", "case_id": case_id}
        return "na", {"reason": "formal_budget_gold_not_applicable"}
    if record.get("status") != "generated":
        return "na", {"reason": str(record.get("reason") or "budget_gold_record_skipped")}
    if not _budget_policy_applicable(gold, output):
        return "na", {"reason": "budget_policy_not_applicable"}
    budget = _budget_payload(output)
    if not budget:
        return "failed", {"reason": "budget_missing"}

    expected_budget, source = _recalculate_budget_from_frozen_data(record, output)
    if expected_budget is None:
        return "failed", {
            "reason": "independent_recalculation_failed",
            "source": source,
        }

    issues: List[str] = []
    _compare_recalculated_budget(
        issues=issues,
        actual=budget,
        expected=expected_budget,
    )
    return (
        "passed" if not issues else "failed",
        {
            "source": source,
            "unit_id": record.get("unit_id"),
            "issues": issues,
            "expected": _budget_recalculation_snapshot(expected_budget),
            "actual": _budget_recalculation_snapshot(budget),
        },
    )


def _recalculate_budget_from_frozen_data(
    record: Dict[str, Any],
    output: Dict[str, Any],
) -> tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    slots = record.get("input_slots") if isinstance(record.get("input_slots"), dict) else {}
    bp = record.get("budget_policy_v2") if isinstance(record.get("budget_policy_v2"), dict) else {}
    duration = _first_int(slots.get("duration_days"), bp.get("duration_days"))
    people_count = _first_int(slots.get("people_count"), bp.get("people_count"))
    destination = slots.get("destination")
    if not destination or duration is None or people_count is None:
        return None, {
            "mode": "missing_gold_slots",
            "destination": destination,
            "duration_days": duration,
            "people_count": people_count,
        }
    final_itinerary = output.get("daily_itinerary") if isinstance(output.get("daily_itinerary"), list) else None
    final_refs = _planned_poi_refs(output)
    use_final_itinerary = bool(final_itinerary and final_refs)
    standard_refs = bp.get("standard_reference_poi_ids") if isinstance(bp.get("standard_reference_poi_ids"), list) else []
    try:
        expected = get_fixed_tourism_data().calculate_budget(
            origin=slots.get("origin"),
            destination=destination,
            duration=duration,
            num_travelers=people_count,
            budget_limit=slots.get("budget_amount"),
            budget_level=slots.get("budget_level") or "medium",
            hotel_level=slots.get("hotel_level"),
            food_level=slots.get("food_level"),
            transport_mode=slots.get("transport_mode"),
            requested_budget_scope=slots.get("requested_budget_scope"),
            daily_itinerary=final_itinerary if use_final_itinerary else None,
            poi_ids=None if use_final_itinerary else standard_refs,
        )
    except (FixedDataError, ValueError, TypeError) as exc:
        return None, {
            "mode": "fixed_data_calculation_error",
            "error": str(exc),
            "used_final_itinerary": use_final_itinerary,
            "final_poi_refs": final_refs,
            "standard_reference_poi_ids": standard_refs,
        }
    return expected, {
        "mode": "final_itinerary" if use_final_itinerary else "standard_reference",
        "used_final_itinerary": use_final_itinerary,
        "final_poi_refs": final_refs,
        "standard_reference_poi_ids": standard_refs,
    }


def _compare_recalculated_budget(
    *,
    issues: List[str],
    actual: Dict[str, Any],
    expected: Dict[str, Any],
) -> None:
    for field in (
        "budget_limit",
        "destination_local_basic_cost",
        "contingency_amount",
        "local_total_recommended",
        "intercity_transport_cost",
        "final_recommended_total",
        "recommended_preparation_amount",
        "remaining_budget",
        "covered_scope_remaining_budget",
        "budget_gap",
    ):
        _compare_budget_number(
            issues,
            f"wrong_{field}",
            _budget_number_field(actual, field),
            _budget_number_field(expected, field),
        )

    for field in (
        "budget_policy_version",
        "budget_scope",
        "requested_budget_scope",
        "computed_budget_scope",
        "scope_complete",
        "sufficiency_status",
        "intercity_transport_included",
        "mandatory_budget_disclaimer",
        "can_judge_budget_sufficiency",
        "is_over_budget",
    ):
        _compare_budget_value(
            issues,
            f"wrong_{field}",
            _budget_value_field(actual, field),
            _budget_value_field(expected, field),
        )

    section_specs = {
        "transport": ("recommended",),
        "accommodation": (
            "recommended",
            "reference_price_cny",
            "room_count",
            "night_count",
            "tier",
        ),
        "food": (
            "recommended",
            "reference_price_cny",
            "meal_count_equivalent",
            "tier",
        ),
        "tickets": ("recommended",),
        "other": ("recommended",),
        "buffer": ("recommended",),
        "intercity_transport": ("recommended",),
    }
    for section, fields in section_specs.items():
        actual_section = _budget_breakdown_section(actual, section)
        expected_section = _budget_breakdown_section(expected, section)
        for field in fields:
            code = f"wrong_{section}_{field}"
            if section == "accommodation" and field == "reference_price_cny":
                code = "wrong_accommodation_reference_price_cny"
            elif section == "accommodation" and field == "night_count":
                code = "wrong_accommodation_night_count"
            elif section == "accommodation" and field == "room_count":
                code = "wrong_accommodation_room_count"
            if field in {"recommended", "reference_price_cny", "meal_count_equivalent"}:
                _compare_budget_number(
                    issues,
                    code,
                    _first_float(actual_section.get(field)),
                    _first_float(expected_section.get(field)),
                )
            else:
                _compare_budget_value(
                    issues,
                    code,
                    actual_section.get(field),
                    expected_section.get(field),
                )

    actual_ticket_refs = _ordered_norm(_budget_selected_poi_ids(actual))
    expected_ticket_refs = _ordered_norm(_budget_selected_poi_ids(expected))
    if actual_ticket_refs != expected_ticket_refs:
        issues.append("wrong_ticket_selected_poi_ids")
    _compare_budget_value(
        issues,
        "wrong_ticket_source",
        _budget_ticket_source(actual),
        _budget_ticket_source(expected),
    )

    actual_intercity = actual.get("intercity_transport") if isinstance(actual.get("intercity_transport"), dict) else {}
    expected_intercity = expected.get("intercity_transport") if isinstance(expected.get("intercity_transport"), dict) else {}
    intercity_number_fields = (
        "one_way_fare_per_person_cny",
        "round_trip_multiplier",
        "people_count",
        "total_intercity_transport_cost_cny",
    )
    for field in intercity_number_fields:
        code = f"wrong_intercity_{field}"
        if field == "one_way_fare_per_person_cny":
            code = "wrong_intercity_one_way_fare_per_person_cny"
        _compare_budget_number(
            issues,
            code,
            _first_float(actual_intercity.get(field)),
            _first_float(expected_intercity.get(field)),
        )
    for field in (
        "status",
        "route_id",
        "budget_scope",
        "intercity_transport_included",
        "mandatory_budget_disclaimer",
        "origin",
        "destination",
    ):
        _compare_budget_value(
            issues,
            f"wrong_intercity_{field}",
            actual_intercity.get(field),
            expected_intercity.get(field),
        )


def _budget_number_field(budget: Dict[str, Any], field: str) -> Optional[float]:
    if field == "final_recommended_total":
        return _budget_recommended_total(budget)
    if field == "destination_local_basic_cost":
        return _budget_local_basic_cost(budget)
    if field == "contingency_amount":
        return _budget_contingency_amount(budget)
    if field == "intercity_transport_cost":
        return _budget_intercity_cost(budget)
    return _first_float(budget.get(field))


def _budget_value_field(budget: Dict[str, Any], field: str) -> Any:
    if field == "budget_policy_version":
        return budget.get("budget_policy_version") or _nested(budget, "budget_policy", "version")
    return budget.get(field)


def _compare_budget_number(
    issues: List[str],
    code: str,
    actual: Optional[float],
    expected: Optional[float],
) -> None:
    if expected is None and actual is None:
        return
    if expected is None or actual is None or not _money_close(float(actual), float(expected)):
        issues.append(code)


def _compare_budget_value(
    issues: List[str],
    code: str,
    actual: Any,
    expected: Any,
) -> None:
    if expected is None and actual in (None, ""):
        return
    if actual != expected:
        issues.append(code)


def _budget_recalculation_snapshot(budget: Dict[str, Any]) -> Dict[str, Any]:
    accommodation = _budget_breakdown_section(budget, "accommodation")
    intercity = budget.get("intercity_transport") if isinstance(budget.get("intercity_transport"), dict) else {}
    return {
        "budget_limit": _budget_number_field(budget, "budget_limit"),
        "destination_local_basic_cost": _budget_number_field(budget, "destination_local_basic_cost"),
        "contingency_amount": _budget_number_field(budget, "contingency_amount"),
        "intercity_transport_cost": _budget_number_field(budget, "intercity_transport_cost"),
        "final_recommended_total": _budget_number_field(budget, "final_recommended_total"),
        "sufficiency_status": _budget_value_field(budget, "sufficiency_status"),
        "scope_complete": _budget_value_field(budget, "scope_complete"),
        "accommodation_reference_price_cny": _first_float(accommodation.get("reference_price_cny")),
        "accommodation_night_count": _first_int(accommodation.get("night_count")),
        "accommodation_room_count": _first_int(accommodation.get("room_count")),
        "intercity_one_way_fare_per_person_cny": _first_float(intercity.get("one_way_fare_per_person_cny")),
        "intercity_total": _first_float(intercity.get("total_intercity_transport_cost_cny")),
        "selected_poi_ids": _budget_selected_poi_ids(budget),
    }


def _budget_policy_applicable(gold: Dict[str, Any], output: Dict[str, Any]) -> bool:
    return bool(
        _budget_payload(output)
        or "budget_calculator" in _list(gold.get("required_tools"))
        or isinstance(gold.get("budget_policy_v2"), dict)
    )


def _budget_payload(output: Dict[str, Any]) -> Dict[str, Any]:
    budget = output.get("budget") if isinstance(output.get("budget"), dict) else {}
    if budget:
        return budget
    return _tool_result_data(output, "budget_calculator")


def _budget_breakdown_section(budget: Dict[str, Any], section: str) -> Dict[str, Any]:
    breakdown = budget.get("breakdown") if isinstance(budget.get("breakdown"), dict) else {}
    payload = breakdown.get(section) if isinstance(breakdown.get(section), dict) else {}
    return payload


def _budget_local_basic_cost(budget: Dict[str, Any]) -> Optional[float]:
    explicit = _first_float(
        budget.get("destination_local_basic_cost"),
        budget.get("local_basic_cost"),
        budget.get("local_subtotal"),
    )
    if explicit is not None:
        return explicit
    values = []
    for section in ("transport", "accommodation", "food", "tickets", "other"):
        value = _first_float(
            _budget_breakdown_section(budget, section).get("recommended"),
            _budget_breakdown_section(budget, section).get("estimated_cost"),
        )
        if value is not None:
            values.append(value)
    return round(sum(values), 2) if values else None


def _budget_contingency_amount(budget: Dict[str, Any]) -> Optional[float]:
    return _first_float(
        budget.get("contingency_amount"),
        budget.get("buffer_cost"),
        _budget_breakdown_section(budget, "buffer").get("recommended"),
        _budget_breakdown_section(budget, "contingency").get("recommended"),
    )


def _budget_intercity_cost(budget: Dict[str, Any]) -> Optional[float]:
    return _first_float(
        budget.get("intercity_transport_cost"),
        _budget_breakdown_section(budget, "intercity_transport").get("recommended"),
        _nested(budget, "intercity_transport", "total_intercity_transport_cost_cny"),
        0.0,
    )


def _budget_recommended_total(budget: Dict[str, Any]) -> Optional[float]:
    return _first_float(
        budget.get("total"),
        budget.get("total_recommended"),
        budget.get("final_recommended_total"),
        budget.get("recommended_preparation_amount"),
        budget.get("confirmed_total_cost"),
    )


def _budget_selected_poi_ids(budget: Dict[str, Any]) -> List[str]:
    ticket_breakdown = budget.get("ticket_breakdown") if isinstance(budget.get("ticket_breakdown"), dict) else {}
    summary = ticket_breakdown.get("summary") if isinstance(ticket_breakdown.get("summary"), dict) else {}
    tickets = _budget_breakdown_section(budget, "tickets")
    return [
        str(value)
        for value in (summary.get("selected_poi_ids") or tickets.get("selected_poi_ids") or [])
        if str(value or "").strip()
    ]


def _budget_ticket_source(budget: Dict[str, Any]) -> Optional[str]:
    ticket_breakdown = budget.get("ticket_breakdown") if isinstance(budget.get("ticket_breakdown"), dict) else {}
    summary = ticket_breakdown.get("summary") if isinstance(ticket_breakdown.get("summary"), dict) else {}
    tickets = _budget_breakdown_section(budget, "tickets")
    source = summary.get("source") or tickets.get("source")
    return str(source) if source is not None else None


def _ordered_norm(values: Iterable[Any]) -> List[str]:
    result: List[str] = []
    for value in values:
        text = _norm(value)
        if text and text not in result:
            result.append(text)
    return result


def _money_close(actual: float, expected: float) -> bool:
    return abs(float(actual) - float(expected)) <= _BUDGET_NUMERIC_TOLERANCE


def _budget_expected_sufficiency_status(budget: Dict[str, Any]) -> Optional[str]:
    budget_limit = _first_float(budget.get("budget_limit"))
    total = _first_float(
        budget.get("final_recommended_total"),
        budget.get("recommended_preparation_amount"),
        budget.get("total_recommended"),
        budget.get("total"),
    )
    if budget_limit is None or total is None:
        return "indeterminate" if budget.get("sufficiency_status") else None
    if total > budget_limit + _BUDGET_NUMERIC_TOLERANCE:
        return "insufficient"
    return "sufficient" if budget.get("scope_complete") is True else "indeterminate"


def _intercity_scope_rule(gold: Dict[str, Any], output: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    budget = output.get("budget") if isinstance(output.get("budget"), dict) else {}
    intercity = _intercity_payload(output)
    if not budget and not intercity:
        return "na", {"reason": "budget_missing"}

    expected_scope = gold.get("budget_scope")
    expected_requested_scope = gold.get("requested_budget_scope")
    expected_computed_scope = gold.get("computed_budget_scope")
    expected_scope_complete = gold.get("scope_complete")
    expected_sufficiency_status = gold.get("sufficiency_status")
    expected_included = gold.get("intercity_transport_included")
    expected_disclaimer = gold.get("mandatory_budget_disclaimer")
    if expected_scope is None and expected_included is None and expected_disclaimer is None:
        if intercity.get("status") == "success":
            expected_scope = "local_plus_round_trip_intercity"
            expected_included = True
            expected_disclaimer = False
        elif intercity.get("status") == "origin_missing":
            expected_scope = "destination_local_only"
            expected_included = False
            expected_disclaimer = True
        elif intercity.get("status") == "route_not_supported":
            expected_scope = "local_only_route_uncovered"
            expected_included = False
            expected_disclaimer = True
        else:
            return "na", {
                "reason": "no_gold_or_detectable_intercity_scope",
                "status": intercity.get("status"),
            }

    actual_scope = budget.get("budget_scope") or intercity.get("budget_scope")
    actual_requested_scope = budget.get("requested_budget_scope")
    actual_computed_scope = budget.get("computed_budget_scope") or actual_scope
    actual_scope_complete = budget.get("scope_complete")
    actual_sufficiency_status = budget.get("sufficiency_status")
    actual_included = _first_bool(
        budget.get("intercity_transport_included"),
        intercity.get("intercity_transport_included"),
    )
    actual_disclaimer = _first_bool(
        budget.get("mandatory_budget_disclaimer"),
        intercity.get("mandatory_budget_disclaimer"),
    )
    issues: List[str] = []
    if expected_scope is not None and actual_scope != expected_scope:
        issues.append("budget_scope_mismatch")
    if expected_requested_scope is not None and actual_requested_scope != expected_requested_scope:
        issues.append("requested_budget_scope_mismatch")
    if expected_computed_scope is not None and actual_computed_scope != expected_computed_scope:
        issues.append("computed_budget_scope_mismatch")
    if expected_scope_complete is not None and actual_scope_complete is not bool(expected_scope_complete):
        issues.append("scope_complete_mismatch")
    if expected_sufficiency_status is not None and actual_sufficiency_status != expected_sufficiency_status:
        issues.append("sufficiency_status_mismatch")
    computed_sufficiency = _budget_expected_sufficiency_status(budget)
    if computed_sufficiency and actual_sufficiency_status and actual_sufficiency_status != computed_sufficiency:
        issues.append("sufficiency_status_formula_mismatch")
    if computed_sufficiency and _first_bool(budget.get("is_over_budget")) is not None:
        expected_over = computed_sufficiency == "insufficient"
        if bool(budget.get("is_over_budget")) is not expected_over:
            issues.append("is_over_budget_sufficiency_mismatch")
    if actual_scope_complete is False and actual_sufficiency_status == "indeterminate":
        if budget.get("remaining_budget") is not None:
            issues.append("incomplete_scope_remaining_budget_error")
        if budget.get("covered_scope_remaining_budget") is None:
            issues.append("covered_scope_remaining_budget_missing")
    if expected_included is not None and actual_included is not bool(expected_included):
        issues.append("intercity_inclusion_mismatch")
    if expected_disclaimer is not None and actual_disclaimer is not bool(expected_disclaimer):
        issues.append("mandatory_disclaimer_mismatch")
    if actual_disclaimer and not (
        budget.get("budget_disclaimer") or intercity.get("disclaimer")
    ):
        issues.append("mandatory_disclaimer_text_missing")
    route_consistency = _intercity_route_consistency(gold, intercity)
    issues.extend(route_consistency["issues"])
    return (
        "passed" if not issues else "failed",
        {
            "expected_scope": expected_scope,
            "actual_scope": actual_scope,
            "expected_requested_scope": expected_requested_scope,
            "actual_requested_scope": actual_requested_scope,
            "expected_computed_scope": expected_computed_scope,
            "actual_computed_scope": actual_computed_scope,
            "expected_scope_complete": expected_scope_complete,
            "actual_scope_complete": actual_scope_complete,
            "expected_sufficiency_status": expected_sufficiency_status,
            "actual_sufficiency_status": actual_sufficiency_status,
            "expected_included": expected_included,
            "actual_included": actual_included,
            "expected_disclaimer": expected_disclaimer,
            "actual_disclaimer": actual_disclaimer,
            "status": intercity.get("status"),
            "route_consistency": route_consistency,
            "issues": issues,
        },
    )


def _intercity_cost_rule(output: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    budget = output.get("budget") if isinstance(output.get("budget"), dict) else {}
    intercity = _intercity_payload(output)
    included = _first_bool(
        budget.get("intercity_transport_included"),
        intercity.get("intercity_transport_included"),
    )
    if not included:
        return "na", {"included": included, "status": intercity.get("status")}
    one_way = _first_float(intercity.get("one_way_fare_per_person_cny"))
    multiplier = _first_float(intercity.get("round_trip_multiplier"))
    people_count = _first_int(intercity.get("people_count"))
    actual = _first_float(
        budget.get("intercity_transport_cost"),
        intercity.get("total_intercity_transport_cost_cny"),
    )
    if one_way is None or multiplier is None or people_count is None or actual is None:
        return "failed", {
            "reason": "missing_formula_field",
            "one_way": one_way,
            "round_trip_multiplier": multiplier,
            "people_count": people_count,
            "actual": actual,
        }
    expected = round(one_way * multiplier * people_count, 2)
    return (
        "passed" if abs(actual - expected) <= 1e-9 else "failed",
        {
            "expected": expected,
            "actual": actual,
            "one_way": one_way,
            "round_trip_multiplier": multiplier,
            "people_count": people_count,
        },
    )


def _intercity_evidence_rule(output: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    budget = output.get("budget") if isinstance(output.get("budget"), dict) else {}
    intercity = _intercity_payload(output)
    included = _first_bool(
        budget.get("intercity_transport_included"),
        intercity.get("intercity_transport_included"),
    )
    if not included:
        return "na", {"included": included, "status": intercity.get("status")}
    evidence = intercity.get("fare_evidence")
    if not isinstance(evidence, dict):
        return "failed", {"reason": "fare_evidence_missing"}
    required = (
        "evidence_id",
        "route_id",
        "departure_station",
        "arrival_station",
        "query_platform",
        "travel_date",
        "fare_selection_rule_id",
        "manual_review_status",
    )
    missing = [
        field for field in required if evidence.get(field) in (None, "", [], {})
    ]
    status = str(evidence.get("manual_review_status") or "")
    malformed = []
    if status not in {"pending", "reviewed"}:
        malformed.append("invalid_manual_review_status")
    if evidence.get("route_id") != intercity.get("route_id"):
        malformed.append("evidence_route_id_mismatch")
    if status == "reviewed":
        for field in ("query_date", "reviewed_at"):
            if evidence.get(field) in (None, "", [], {}):
                missing.append(field)
    return (
        "passed" if not missing and not malformed else "failed",
        {
            "evidence_id": evidence.get("evidence_id"),
            "route_id": evidence.get("route_id"),
            "intercity_route_id": intercity.get("route_id"),
            "manual_review_status": status,
            "missing": missing,
            "malformed": malformed,
            "formal_review_complete": status == "reviewed",
        },
    )


def _intercity_route_consistency(gold: Dict[str, Any], intercity: Dict[str, Any]) -> Dict[str, Any]:
    expected_origin = _city_id(gold.get("origin"))
    expected_destination = _city_id(gold.get("destination") or gold.get("city"))
    actual_origin = _city_id(intercity.get("origin"))
    actual_destination = _city_id(intercity.get("destination"))
    requested_origin = _city_id(intercity.get("requested_origin"))
    requested_destination = _city_id(intercity.get("requested_destination"))
    lookup_origin = _city_id(intercity.get("lookup_origin"))
    lookup_destination = _city_id(intercity.get("lookup_destination"))
    lookup_direction = str(intercity.get("lookup_direction") or "")
    status = str(intercity.get("status") or "")
    issues: List[str] = []

    if expected_origin:
        if requested_origin and requested_origin != expected_origin:
            issues.append("requested_origin_mismatch")
        if status != "origin_missing" and actual_origin != expected_origin:
            issues.append("origin_mismatch")
    if expected_destination:
        if requested_destination and requested_destination != expected_destination:
            issues.append("requested_destination_mismatch")
        if actual_destination != expected_destination:
            issues.append("destination_mismatch")
    if status == "success" and expected_origin and expected_destination:
        if lookup_direction == "reverse_symmetric":
            if lookup_origin != expected_destination or lookup_destination != expected_origin:
                issues.append("lookup_route_mismatch")
        elif lookup_origin or lookup_destination:
            if lookup_origin != expected_origin or lookup_destination != expected_destination:
                issues.append("lookup_route_mismatch")

    return {
        "expected_origin": expected_origin,
        "expected_destination": expected_destination,
        "actual_origin": actual_origin,
        "actual_destination": actual_destination,
        "requested_origin": requested_origin,
        "requested_destination": requested_destination,
        "lookup_origin": lookup_origin,
        "lookup_destination": lookup_destination,
        "lookup_direction": lookup_direction,
        "status": status,
        "issues": issues,
    }


def _city_id(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    lowered = text.casefold()
    return _CITY_VALUE_ALIASES.get(lowered, lowered)


def _intercity_payload(output: Dict[str, Any]) -> Dict[str, Any]:
    budget = output.get("budget") if isinstance(output.get("budget"), dict) else {}
    intercity = budget.get("intercity_transport") if isinstance(budget.get("intercity_transport"), dict) else {}
    if intercity:
        return intercity
    tool_data = _tool_result_data(output, "budget_calculator")
    intercity = (
        tool_data.get("intercity_transport")
        if isinstance(tool_data.get("intercity_transport"), dict)
        else {}
    )
    return intercity if isinstance(intercity, dict) else {}


def _first_bool(*values: Any) -> Optional[bool]:
    for value in values:
        if isinstance(value, bool):
            return value
    return None


def _weather_answer_terms(value: Any) -> List[str]:
    weather = value if isinstance(value, dict) else {}
    labels = _unique(
        _list(weather.get("scenario_type"))
        + _list(weather.get("weather_type"))
        + _list(weather.get("condition"))
        + _list(weather.get("state"))
    )
    for day in weather.get("daily_weather") or []:
        if isinstance(day, dict):
            labels.extend(_list(day.get("condition")) + _list(day.get("state")) + _list(day.get("weather")))
    terms: List[str] = []
    for label in _unique(labels):
        lower = label.lower()
        terms.append(label)
        if "sun" in lower or "晴" in label:
            terms.extend(["sunny", "晴"])
        if "rain" in lower or "雨" in label:
            terms.extend(["rain", "雨"])
        if "high_temperature" in lower or "hot" in lower or "高温" in label:
            terms.extend(["hot", "高温"])
        if "low_temperature" in lower or "cold" in lower or "低温" in label:
            terms.extend(["cold", "低温"])
    return _unique(terms)


def _required_refs(gold: Dict[str, Any], output: Dict[str, Any], key: str, alias: str, *, fail_on_present: bool) -> tuple[str, Dict[str, Any]]:
    expected = _list(gold.get(key) or gold.get(alias))
    if not expected:
        return "na", {}
    refs = {_norm(item) for item in _poi_refs(output)}
    matched = [item for item in expected if _norm(item) in refs]
    failed = bool(matched) if fail_on_present else len(matched) != len(expected)
    return ("failed" if failed else "passed"), {"expected": expected, "matched": matched}


def _scheduler_slots(
    case: Dict[str, Any],
    gold: Dict[str, Any],
    output: Dict[str, Any],
    key: str,
    expected: List[str],
    *,
    changed: bool,
) -> tuple[str, Dict[str, Any]]:
    if not expected:
        return "na", {}
    actual = _list(
        _nested(output, "metadata", "scheduler", "ticket", key)
        or _nested(output, "metadata", "scheduler", "decision", key)
        or _nested(output, "metadata", "adaptive_scheduler", "ticket", key)
        or _nested(output, "metadata", "adaptive_scheduler", "decision", key)
    )
    missing_claims = [slot for slot in expected if slot not in actual]
    mismatches = []
    for slot in expected:
        expected_value = _slot_expected_current(case, gold, slot) if changed else _slot_expected_preserved(case, gold, slot)
        actual_value = _slot_actual(output, slot)
        if expected_value is _MISSING or actual_value is _MISSING or not _same_value(actual_value, expected_value):
            mismatches.append(
                {
                    "slot": slot,
                    "expected": None if expected_value is _MISSING else expected_value,
                    "actual": None if actual_value is _MISSING else actual_value,
                }
            )
    return (
        "passed" if not missing_claims and not mismatches else "failed",
        {"expected": expected, "claimed": actual, "missing_claims": missing_claims, "mismatches": mismatches},
    )


def _slot_expected_current(case: Dict[str, Any], gold: Dict[str, Any], slot: str) -> Any:
    for mapping in (
        gold.get("current_slots"),
        case.get("current_slots"),
        case.get("slots"),
        gold,
    ):
        value = _slot_from_mapping(mapping if isinstance(mapping, dict) else {}, slot)
        if value is not _MISSING:
            return value
    return _MISSING


def _slot_expected_preserved(case: Dict[str, Any], gold: Dict[str, Any], slot: str) -> Any:
    for mapping in (
        gold.get("previous_slots"),
        (case.get("previous_state") or {}).get("slots") if isinstance(case.get("previous_state"), dict) else None,
        gold.get("current_slots"),
        case.get("current_slots"),
    ):
        value = _slot_from_mapping(mapping if isinstance(mapping, dict) else {}, slot)
        if value is not _MISSING:
            return value
    return _MISSING


def _slot_actual(output: Dict[str, Any], slot: str) -> Any:
    poi_data, poi_input = _tool_result_data(output, "poi_search"), _tool_result_input(output, "poi_search")
    weather_data, weather_input = _tool_result_data(output, "weather_query"), _tool_result_input(output, "weather_query")
    budget_data, budget_input = _tool_result_data(output, "budget_calculator"), _tool_result_input(output, "budget_calculator")
    budget = output.get("budget") if isinstance(output.get("budget"), dict) else {}
    weather = output.get("weather") if isinstance(output.get("weather"), dict) else {}
    slot = str(slot)
    if slot in {"origin", "departure_city", "from_city"}:
        return _first_existing(
            _nested(output, "metadata", "goal_state_slots", "origin"),
            _nested(output, "metadata", "scheduler", "ticket", "current_slots", "origin"),
            _nested(output, "metadata", "adaptive_scheduler", "ticket", "current_slots", "origin"),
            budget.get("origin"),
            budget_data.get("origin"),
            budget_input.get("origin"),
            budget_input.get("from_city"),
            budget_input.get("departure_city"),
        )
    if slot in {"destination", "city"}:
        return _first_existing(weather.get("city"), budget.get("city"), weather_data.get("city"), budget_data.get("city"), poi_data.get("city"), weather_input.get("city"), budget_input.get("city"), poi_input.get("city"))
    if slot in {"start_date", "date"}:
        first_weather_day = _first_weather_day(weather) or _first_weather_day(weather_data)
        return _first_existing(weather.get("date"), weather_data.get("date"), weather_input.get("date"), weather_input.get("start_date"), first_weather_day.get("date") if isinstance(first_weather_day, dict) else None)
    if slot in {"duration_days", "duration", "days", "trip_days"}:
        return _first_existing(output.get("trip_days"), len(output.get("daily_itinerary") or []) or None, budget.get("days"), budget_data.get("days"), budget_input.get("days"), weather_input.get("days"), len(weather_data.get("daily_weather") or []) or None)
    if slot in {"people_count", "num_travelers", "people"}:
        return _first_existing(budget.get("people_count"), budget_data.get("people_count"), budget_input.get("people_count"), budget_input.get("num_travelers"), poi_data.get("people"), poi_input.get("people"))
    if slot in {"budget_amount", "budget_limit", "max_budget", "budget"}:
        return _first_existing(
            _nested(output, "metadata", "goal_state_slots", "budget_amount"),
            _nested(output, "metadata", "scheduler", "ticket", "current_slots", "budget_amount"),
            _nested(output, "metadata", "adaptive_scheduler", "ticket", "current_slots", "budget_amount"),
            budget.get("budget_amount"),
            budget.get("budget_limit"),
            budget.get("max_budget"),
            budget_data.get("budget_amount"),
            budget_data.get("budget_limit"),
            budget_input.get("budget_amount"),
            budget_input.get("budget_limit"),
        )
    if slot in {"budget_level", "spending_level"}:
        return _first_existing(budget.get("spending_level"), budget.get("budget_level"), budget_data.get("spending_level"), budget_input.get("spending_level"), budget_input.get("budget_level"))
    if slot in {"preferences", "preference"}:
        return _first_existing(
            _nested(output, "metadata", "goal_state_slots", "preferences"),
            _nested(output, "metadata", "scheduler", "ticket", "current_slots", "preferences"),
            _nested(output, "metadata", "adaptive_scheduler", "ticket", "current_slots", "preferences"),
            poi_data.get("preferences"),
            poi_input.get("preferences"),
        )
    if slot in {"traveler_group", "people_type"}:
        return _first_existing(
            _nested(output, "metadata", "goal_state_slots", "traveler_group"),
            _nested(output, "metadata", "scheduler", "ticket", "current_slots", "traveler_group"),
            _nested(output, "metadata", "adaptive_scheduler", "ticket", "current_slots", "traveler_group"),
            poi_data.get("traveler_group"),
            poi_input.get("traveler_group"),
            poi_data.get("people"),
            poi_input.get("people"),
        )
    if slot in {"special_requirements", "requirements"}:
        return _first_existing(
            _nested(output, "metadata", "goal_state_slots", "special_requirements"),
            _nested(output, "metadata", "scheduler", "ticket", "current_slots", "special_requirements"),
            _nested(output, "metadata", "adaptive_scheduler", "ticket", "current_slots", "special_requirements"),
            poi_data.get("special_requirements"),
            poi_input.get("special_requirements"),
        )
    if slot in {"weather_scenario", "scenario_type"}:
        return _first_existing(weather.get("scenario_type"), weather.get("weather_type"), weather_data.get("scenario_type"), weather_data.get("requested_scenario_type"), weather_input.get("scenario_type"), weather_input.get("weather_scenario"))
    return _MISSING


def _slot_from_mapping(mapping: Dict[str, Any], slot: str) -> Any:
    aliases = {
        "origin": ("origin", "departure_city", "from_city"),
        "departure_city": ("departure_city", "origin", "from_city"),
        "from_city": ("from_city", "origin", "departure_city"),
        "destination": ("destination", "city"),
        "city": ("city", "destination"),
        "start_date": ("start_date", "date"),
        "date": ("date", "start_date"),
        "duration_days": ("duration_days", "duration", "days", "trip_days"),
        "duration": ("duration", "duration_days", "days", "trip_days"),
        "days": ("days", "duration_days", "duration", "trip_days"),
        "people_count": ("people_count", "num_travelers", "people"),
        "budget_amount": ("budget_amount", "budget_limit", "max_budget", "budget"),
        "budget": ("budget", "budget_amount", "budget_limit", "max_budget"),
        "budget_limit": ("budget_limit", "budget_amount", "max_budget", "budget"),
        "max_budget": ("max_budget", "budget_limit", "budget_amount", "budget"),
        "budget_level": ("budget_level", "spending_level"),
        "preferences": ("preferences", "preference"),
        "traveler_group": ("traveler_group", "people_type", "people"),
        "special_requirements": ("special_requirements", "requirements"),
        "weather_scenario": ("weather_scenario", "scenario_type"),
    }
    for key in aliases.get(slot, (slot,)):
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return _MISSING


def _tool_result_data(output: Dict[str, Any], name: str) -> Dict[str, Any]:
    result = (output.get("tool_results") or {}).get(name) if isinstance(output.get("tool_results"), dict) else None
    return result.get("data") if isinstance(result, dict) and isinstance(result.get("data"), dict) else {}


def _tool_result_input(output: Dict[str, Any], name: str) -> Dict[str, Any]:
    result = (output.get("tool_results") or {}).get(name) if isinstance(output.get("tool_results"), dict) else None
    return result.get("input") if isinstance(result, dict) and isinstance(result.get("input"), dict) else {}


def _first_weather_day(weather: Dict[str, Any]) -> Dict[str, Any]:
    days = weather.get("daily_weather") if isinstance(weather, dict) else None
    return days[0] if isinstance(days, list) and days and isinstance(days[0], dict) else {}


def _first_existing(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return _MISSING


def _same_value(actual: Any, expected: Any) -> bool:
    if actual is _MISSING or expected is _MISSING:
        return False
    actual_num, expected_num = _first_float(actual), _first_float(expected)
    if actual_num is not None and expected_num is not None:
        return abs(actual_num - expected_num) <= 1e-9
    if isinstance(actual, list) or isinstance(expected, list):
        return sorted(_norm(item) for item in _list(actual)) == sorted(_norm(item) for item in _list(expected))
    return _norm(actual) == _norm(expected)


def _weather_unaffected_preserved(case: Dict[str, Any], gold: Dict[str, Any], output: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    previous = gold.get("previous_artifacts") if isinstance(gold.get("previous_artifacts"), dict) else _previous_artifacts_from_state(case.get("previous_state") if isinstance(case.get("previous_state"), dict) else {})
    if not previous:
        return "na", {}
    affected_days = set(_affected_days(case, gold))
    affected_days.update(_weather_adjustment_days_from_output(output))
    issues = []
    previous_itinerary = previous.get("daily_itinerary")
    if isinstance(previous_itinerary, list) and previous_itinerary:
        current_by_day = _itinerary_by_day(output.get("daily_itinerary") or [])
        for day, previous_day in _itinerary_by_day(previous_itinerary).items():
            if day in affected_days:
                continue
            current_day = current_by_day.get(day)
            if current_day is None or _day_refs(current_day) != _day_refs(previous_day):
                issues.append({"field": "daily_itinerary", "day": day})
    if (
        previous.get("budget")
        and not _weather_adjustment_expects_budget_recalculation(gold)
        and not _budget_matches(previous.get("budget"), output.get("budget"))
    ):
        issues.append({"field": "budget"})
    if (
        previous.get("attractions")
        and not previous_itinerary
        and set(_refs_from_items(previous.get("attractions"))) != set(_refs_from_items(output.get("attractions") or []))
    ):
        issues.append({"field": "attractions"})
    return ("passed" if not issues else "failed"), {"affected_days": sorted(affected_days), "issues": issues}


def _weather_adjustment_days_from_output(output: Dict[str, Any]) -> set[int]:
    adjustments = output.get("weather_adjustments")
    if not isinstance(adjustments, list):
        return set()
    return {
        day
        for day in (
            _first_int(item.get("day"), item.get("day_index"))
            for item in adjustments
            if isinstance(item, dict)
        )
        if day is not None
    }


def _weather_adjustment_expects_budget_recalculation(gold: Dict[str, Any]) -> bool:
    if "budget_calculator" in set(_list(gold.get("required_tools"))):
        return True
    for accepted in gold.get("accepted_agent_sets") or []:
        if "budget" in set(_list(accepted)):
            return True
    for accepted in gold.get("accepted_tool_sets") or []:
        if "budget_calculator" in set(_list(accepted)):
            return True
    policy = str(gold.get("partial_replan_policy") or "").casefold()
    return "budget" in policy


def _weather_affected_adjusted(case: Dict[str, Any], gold: Dict[str, Any], output: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    adjustments = [item for item in output.get("weather_adjustments") or [] if isinstance(item, dict)]
    if not adjustments:
        return "failed", {"adjustment_count": 0}
    affected_days = _affected_days(case, gold)
    adjusted_days = {day for day in (_first_int(item.get("day"), item.get("day_index")) for item in adjustments) if day}
    missing_days = sorted(affected_days - adjusted_days) if affected_days else []
    status = "passed" if not missing_days else "failed"
    return status, {"affected_days": sorted(affected_days), "adjusted_days": sorted(adjusted_days), "missing_days": missing_days}


def _previous_artifacts_from_state(previous_state: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(previous_state, dict):
        return {}
    tool_results = previous_state.get("tool_results") if isinstance(previous_state.get("tool_results"), dict) else {}
    artifacts: Dict[str, Any] = {}
    daily = previous_state.get("daily_itinerary") or _nested(previous_state, "output", "daily_itinerary") or _nested(previous_state, "raw_output", "daily_itinerary")
    if isinstance(daily, list):
        artifacts["daily_itinerary"] = daily
    budget = previous_state.get("budget") or _nested(previous_state, "output", "budget") or _nested(previous_state, "raw_output", "budget") or _nested(tool_results.get("budget_calculator") or {}, "data")
    if isinstance(budget, dict):
        artifacts["budget"] = budget
    attractions = previous_state.get("attractions") or _nested(previous_state, "output", "attractions") or _nested(previous_state, "raw_output", "attractions") or _nested(tool_results.get("poi_search") or {}, "data", "attractions")
    if isinstance(attractions, list):
        artifacts["attractions"] = attractions
    return artifacts


def _affected_days(case: Dict[str, Any], gold: Dict[str, Any]) -> set[int]:
    value = _first_existing(
        _nested(gold, "weather_change", "affected_days"),
        _nested(case, "weather_change", "affected_days"),
        _slot_from_mapping(case.get("current_slots") if isinstance(case.get("current_slots"), dict) else {}, "weather_scenario"),
        _slot_from_mapping(gold.get("current_slots") if isinstance(gold.get("current_slots"), dict) else {}, "weather_scenario"),
    )
    if value is _MISSING:
        return set()
    if isinstance(value, list):
        return {day for day in (_first_int(item) for item in value) if day is not None}
    text = str(value or "")
    return {int(item) for item in text.replace("-", "_").split("_") if item.isdigit()}


def _itinerary_by_day(days: Any) -> Dict[int, Dict[str, Any]]:
    result: Dict[int, Dict[str, Any]] = {}
    for index, day in enumerate(days if isinstance(days, list) else [], start=1):
        if isinstance(day, dict):
            result[_first_int(day.get("day"), day.get("day_index"), index) or index] = day
    return result


def _day_refs(day: Dict[str, Any]) -> List[str]:
    return [_norm(item) for item in _refs_from_items(day.get("attractions") or day.get("pois") or day.get("activities") or [])]


def _budget_matches(previous: Any, current: Any) -> bool:
    previous_budget = previous if isinstance(previous, dict) else {}
    current_budget = current if isinstance(current, dict) else {}
    if not previous_budget or not current_budget:
        return False
    previous_total, current_total = _budget_total(previous_budget), _budget_total(current_budget)
    if previous_total is not None:
        return current_total is not None and abs(previous_total - current_total) <= 1e-9
    common = set(previous_budget) & set(current_budget)
    return bool(common) and all(_same_value(previous_budget[key], current_budget[key]) for key in common)


def _set_rule(actual: List[str], accepted_value: Any) -> tuple[str, Dict[str, Any]]:
    accepted = _sets(accepted_value)
    if not accepted:
        return "na", {}
    return ("passed" if any(set(actual) == set(item) for item in accepted) else "failed"), {"accepted": accepted, "actual": actual}


def _set_scores(actual: List[str], expected: Optional[List[str]]) -> Dict[str, Any]:
    if expected is None:
        return {"precision": None, "recall": None, "f1": None, "exact": None, "extra": None, "missing": None}
    a, e = set(actual), set(expected)
    hit = len(a & e)
    if not a and not e:
        precision = recall = f1 = 1.0
    else:
        precision = _ratio(hit, len(a)) if a else 0.0
        recall = _ratio(hit, len(e)) if e else 0.0
        f1 = 0.0 if precision + recall == 0 else round(2 * precision * recall / (precision + recall), 4)
    return {"precision": precision, "recall": recall, "f1": f1, "exact": a == e, "extra": len(a - e), "missing": len(e - a)}


def _mean_delta(pairs: List[tuple[Dict[str, Any], Dict[str, Any]]], metric: str) -> Optional[float]:
    values = []
    for m3, m2 in pairs:
        left = (m3.get("metrics") or {}).get(metric)
        right = (m2.get("metrics") or {}).get(metric)
        if isinstance(left, bool) or isinstance(right, bool):
            continue
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            values.append(float(left) - float(right))
    return _mean_num(values)


def _is_scenario_row(row: Dict[str, Any]) -> bool:
    return bool(row.get("scenario_id")) or _first_int(row.get("scenario_turn_count")) is not None


def _is_quality_evaluation_row(row: Dict[str, Any]) -> bool:
    if not _is_scenario_row(row):
        return True
    if "target_turn" in row:
        return _bool(row.get("target_turn"))
    turn_index = _first_int(row.get("turn_index"))
    turn_count = _first_int(row.get("scenario_turn_count"))
    if turn_index is None or turn_count is None:
        return True
    return turn_index == turn_count - 1


def _evaluation_unit_id(row: Dict[str, Any]) -> str:
    scenario_id = str(row.get("scenario_id") or "")
    if scenario_id:
        turn_id = str(row.get("turn_id") or row.get("turn_index") or "target")
        return f"{scenario_id}:{turn_id}"
    return str(row.get("case_id") or "")


def _scenario_id(row: Dict[str, Any]) -> str:
    return str(row.get("scenario_id") or row.get("case_id") or "")


def _scenario_run_id(row: Dict[str, Any]) -> str:
    repeat_index = row.get("repeat_index")
    repeat_text = "none" if repeat_index is None else str(repeat_index)
    return f"{_scenario_id(row)}::repeat={repeat_text}"


def _scenario_cost_summary(raw_by_method: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    methods: Dict[str, Dict[str, Any]] = {}
    all_scenario_ids = {
        _scenario_id(row)
        for rows in raw_by_method.values()
        for row in rows
        if _is_scenario_row(row) and _scenario_id(row)
    }
    for method, rows in sorted(raw_by_method.items()):
        scenario_rows = [row for row in rows if _is_scenario_row(row)]
        if not scenario_rows:
            methods[method] = {
                "scenario_count": 0,
                "target_turn_count": 0,
            }
            continue
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for row in scenario_rows:
            groups.setdefault(_scenario_run_id(row), []).append(row)
        methods[method] = _scenario_cost_method_summary(groups)
    return {
        "enabled": True,
        "scope": {
            "target_increment": "target turn only",
            "scenario_total": "sum of all turns in the same scenario and repeat",
        },
        "scenario_count": len(all_scenario_ids),
        "methods": methods,
    }


def _scenario_cost_method_summary(groups: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    total_rows = [_aggregate_scenario_cost(rows) for rows in groups.values()]
    target_rows = [_aggregate_target_increment_cost(rows) for rows in groups.values()]
    metrics = (
        "llm_call_count",
        "agent_llm_call_count",
        "api_call_count",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "agent_total_tokens",
        "estimated_cost",
        "standardized_estimated_cost",
        "actual_cost",
        "called_tool_count",
        "planned_agent_count",
        "successful_tool_call_count",
        "latency_ms",
    )
    result: Dict[str, Any] = {
        "scenario_count": len(groups),
        "target_turn_count": sum(1 for item in target_rows if item),
    }
    for metric in metrics:
        result[f"scenario_total_{metric}_mean"] = _mean_num(
            item.get(metric) for item in total_rows if item.get(metric) is not None
        )
        result[f"target_increment_{metric}_mean"] = _mean_num(
            item.get(metric) for item in target_rows if item.get(metric) is not None
        )
    return result


def _aggregate_scenario_cost(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        metric: _sum_metric(rows, metric)
        for metric in (
            "llm_call_count",
            "agent_llm_call_count",
            "api_call_count",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "agent_total_tokens",
            "estimated_cost",
            "standardized_estimated_cost",
            "actual_cost",
            "called_tool_count",
            "planned_agent_count",
            "successful_tool_call_count",
            "latency_ms",
        )
    }


def _aggregate_target_increment_cost(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    targets = [row for row in rows if _is_quality_evaluation_row(row)]
    if not targets:
        return {}
    return _aggregate_scenario_cost(targets)


def _sum_metric(rows: List[Dict[str, Any]], metric: str) -> Optional[float]:
    values = [_metric_number(row, metric) for row in rows]
    clean = [value for value in values if value is not None]
    return None if not clean else _round4(sum(clean))


def _metric_number(row: Dict[str, Any], metric: str) -> Optional[float]:
    if metric == "latency_ms":
        return _number(row.get("latency_ms") if row.get("latency_ms") is not None else row.get("latency"))
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    value = _number(metrics.get(metric))
    if value is not None:
        return value
    audit_metrics = _nested(row, "run_audit", "metrics")
    if isinstance(audit_metrics, dict):
        return _number(audit_metrics.get(metric))
    return None


def _aggregate_repeated_cases(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(_evaluation_unit_id(row), []).append(row)
    return [_aggregate_case_group(group) for _, group in sorted(groups.items())]


def _aggregate_case_group(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    base = dict(rows[0])
    base["evaluation_unit_id"] = _evaluation_unit_id(base)
    base["repeat_count"] = len(rows)
    base["repeat_indices"] = [row.get("repeat_index") for row in rows]
    base["latency_ms"] = _mean_num(row.get("latency_ms") for row in rows)
    base["latency"] = base["latency_ms"]
    base["metrics"] = _aggregate_metric_dicts([row.get("metrics") or {} for row in rows])
    base["trace"] = _aggregate_trace_dicts([row.get("trace") or {} for row in rows])
    return base


def _aggregate_metric_dicts(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    keys = set().union(*(item.keys() for item in items))
    result: Dict[str, Any] = {}
    failed_ids = sorted({value for item in items for value in _list(item.get("evaluation_failed_rule_ids"))})
    failure_types = sorted({value for item in items for value in _list(item.get("tool_failure_types"))})
    for key in sorted(keys - {"evaluation_failed_rule_ids", "evaluation_failed_rule_count", "tool_failure_types", "tool_failure_count"}):
        values = [item.get(key) for item in items if item.get(key) is not None]
        numbers = [_number(value) for value in values]
        if values and all(value is not None for value in numbers):
            result[key] = _mean_num(value for value in numbers if value is not None)
        elif values and all(isinstance(value, list) for value in values):
            result[key] = sorted({str(entry) for value in values for entry in value})
        elif values:
            result[key] = values[0]
    result["evaluation_failed_rule_ids"] = failed_ids
    result["evaluation_failed_rule_count"] = len(failed_ids)
    result["tool_failure_types"] = failure_types
    result["tool_failure_count"] = len(failure_types)
    return result


def _aggregate_trace_dicts(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    keys = set().union(*(item.keys() for item in items))
    result: Dict[str, Any] = {}
    for key in sorted(keys):
        values = [item.get(key) for item in items if item.get(key) is not None]
        numbers = [_number(value) for value in values]
        if values and all(value is not None for value in numbers):
            result[key] = _mean_num(value for value in numbers if value is not None)
        elif values and all(isinstance(value, list) for value in values):
            result[key] = sorted({str(entry) for value in values for entry in value})
        elif values:
            result[key] = values[0]
    result["repeat_count"] = len(items)
    return result


def _mean_metric(rows: List[Dict[str, Any]], metric: str) -> Optional[float]:
    return _mean_num(
        value
        for value in (_number((row.get("metrics") or {}).get(metric)) for row in rows)
        if value is not None
    )


def _cost_per_success(rows: List[Dict[str, Any]]) -> Optional[float]:
    costs = []
    success_count = 0
    for row in rows:
        metrics = row.get("metrics") or {}
        cost = _number(metrics.get("estimated_cost"))
        success = (_number(metrics.get("stsr")) or 0.0) >= 0.5
        if success:
            success_count += 1
        if cost is not None:
            costs.append(cost)
    return None if not costs or success_count == 0 else _round4(sum(costs) / success_count)


def _descriptive_statistics(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {
        name: _series_statistics(_numeric_values(rows, path))
        for name, path in _DESCRIPTIVE_METRICS
    }


def _paired_rows(
    m3_rows: List[Dict[str, Any]],
    m2_rows: List[Dict[str, Any]],
) -> List[tuple[Dict[str, Any], Dict[str, Any]]]:
    m2_index = {_pair_key(row): row for row in m2_rows}
    return [(row, m2_index[_pair_key(row)]) for row in m3_rows if _pair_key(row) in m2_index]


def _paired_metric_statistics(
    name: str,
    pairs: List[tuple[Dict[str, Any], Dict[str, Any]]],
    path: tuple[str, ...],
    binary: bool,
) -> Dict[str, Any]:
    m3_values, m2_values = [], []
    for m3, m2 in pairs:
        left, right = _number(_path_value(m3, path)), _number(_path_value(m2, path))
        if left is not None and right is not None:
            m3_values.append(left)
            m2_values.append(right)
    deltas = [left - right for left, right in zip(m3_values, m2_values)]
    result = {
        "pair_count": len(deltas),
        "m3": _series_statistics(m3_values),
        "m2": _series_statistics(m2_values),
        "delta": {
            **_series_statistics(deltas),
            "bootstrap_ci_95": _bootstrap_ci(deltas, seed=_BOOTSTRAP_SEED + sum(ord(ch) for ch in name)),
        },
    }
    result["mcnemar"] = _mcnemar(m3_values, m2_values) if binary else None
    result["wilcoxon_signed_rank"] = None if binary else _wilcoxon_signed_rank(deltas)
    return result


def _method_order(methods: Dict[str, Any]) -> List[str]:
    preferred = [method for method in _METHOD_LABELS if method in methods]
    return preferred + sorted(method for method in methods if method not in _METHOD_LABELS)


def _method_label(method: str) -> str:
    return _METHOD_LABELS.get(method, method)


def _test_summary(stat: Dict[str, Any]) -> Dict[str, Any]:
    mcnemar = stat.get("mcnemar") if isinstance(stat.get("mcnemar"), dict) else None
    wilcoxon = (
        stat.get("wilcoxon_signed_rank")
        if isinstance(stat.get("wilcoxon_signed_rank"), dict)
        else None
    )
    if mcnemar:
        return {"name": "McNemar", "p_value": mcnemar.get("p_value")}
    if wilcoxon:
        return {"name": "Wilcoxon", "p_value": wilcoxon.get("p_value")}
    return {"name": "", "p_value": None}


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(_round4(value))
    return str(value)


def _fmt_range(value: Any) -> str:
    items = value if isinstance(value, list) else []
    return "" if len(items) != 2 else f"[{_fmt(items[0])}, {_fmt(items[1])}]"


def _numeric_values(rows: List[Dict[str, Any]], path: tuple[str, ...]) -> List[float]:
    values = []
    for row in rows:
        value = _number(_path_value(row, path))
        if value is not None:
            values.append(value)
    return values


def _series_statistics(values: List[float]) -> Dict[str, Any]:
    clean = [float(value) for value in values]
    if not clean:
        return {"n": 0, "mean": None, "median": None, "iqr": None, "min": None, "max": None}
    ordered = sorted(clean)
    return {
        "n": len(ordered),
        "mean": _round4(sum(ordered) / len(ordered)),
        "median": _round4(_quantile(ordered, 0.5)),
        "iqr": [_round4(_quantile(ordered, 0.25)), _round4(_quantile(ordered, 0.75))],
        "min": _round4(ordered[0]),
        "max": _round4(ordered[-1]),
    }


def _bootstrap_ci(values: List[float], *, seed: int) -> Optional[List[float]]:
    if not values:
        return None
    if len(values) == 1:
        value = _round4(values[0])
        return [value, value]
    rng = random.Random(seed)
    means = [
        sum(rng.choice(values) for _ in values) / len(values)
        for _ in range(_BOOTSTRAP_SAMPLES)
    ]
    means.sort()
    return [_round4(_quantile(means, 0.025)), _round4(_quantile(means, 0.975))]


def _mcnemar(m3_values: List[float], m2_values: List[float]) -> Dict[str, Any]:
    m3_binary = [value >= 0.5 for value in m3_values]
    m2_binary = [value >= 0.5 for value in m2_values]
    m3_only = sum(left and not right for left, right in zip(m3_binary, m2_binary))
    m2_only = sum((not left) and right for left, right in zip(m3_binary, m2_binary))
    discordant = m3_only + m2_only
    if discordant == 0:
        p_value = 1.0
    else:
        tail = sum(math.comb(discordant, i) for i in range(min(m3_only, m2_only) + 1))
        p_value = min(1.0, 2 * tail / (2**discordant))
    return {
        "m3_only_success": m3_only,
        "m2_only_success": m2_only,
        "discordant_pairs": discordant,
        "p_value": _round4(p_value),
        "method": "exact_binomial_two_sided",
    }


def _wilcoxon_signed_rank(deltas: List[float]) -> Dict[str, Any]:
    nonzero = [delta for delta in deltas if abs(delta) > 1e-12]
    if not nonzero:
        return {"n_nonzero": 0, "w_plus": 0.0, "w_minus": 0.0, "statistic": 0.0, "p_value": 1.0, "method": "no_nonzero_deltas"}
    ranks = _signed_ranks(nonzero)
    w_plus = sum(rank for delta, rank in ranks if delta > 0)
    w_minus = sum(rank for delta, rank in ranks if delta < 0)
    statistic = min(w_plus, w_minus)
    p_value, method = _wilcoxon_p_value([rank for _, rank in ranks], statistic)
    return {
        "n_nonzero": len(nonzero),
        "w_plus": _round4(w_plus),
        "w_minus": _round4(w_minus),
        "statistic": _round4(statistic),
        "p_value": _round4(p_value),
        "method": method,
    }


def _signed_ranks(values: List[float]) -> List[tuple[float, float]]:
    indexed = sorted(enumerate(values), key=lambda item: abs(item[1]))
    ranks = [0.0] * len(values)
    start = 0
    while start < len(indexed):
        end = start + 1
        while end < len(indexed) and abs(abs(indexed[end][1]) - abs(indexed[start][1])) <= 1e-12:
            end += 1
        rank = (start + 1 + end) / 2
        for index, _ in indexed[start:end]:
            ranks[index] = rank
        start = end
    return list(zip(values, ranks))


def _wilcoxon_p_value(ranks: List[float], statistic: float) -> tuple[float, str]:
    total = sum(ranks)
    if len(ranks) <= 20:
        distribution: Counter[float] = Counter({0.0: 1})
        for rank in ranks:
            distribution.update({value + rank: count for value, count in list(distribution.items())})
        extreme = sum(
            count
            for value, count in distribution.items()
            if min(value, total - value) <= statistic + 1e-12
        )
        return extreme / (2 ** len(ranks)), "exact_signed_rank"
    variance = sum(rank * rank for rank in ranks) / 4
    if variance <= 0:
        return 1.0, "normal_approximation"
    z = max(0.0, (abs(sum(ranks) / 2 - statistic) - 0.5) / math.sqrt(variance))
    return math.erfc(z / math.sqrt(2)), "normal_approximation"


def _mean_bool(values: Iterable[Any]) -> Optional[float]:
    clean = [1.0 if value is True else 0.0 for value in values if isinstance(value, bool)]
    return _mean_num(clean)


def _mean_num(values: Iterable[Any]) -> Optional[float]:
    clean = [float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
    return None if not clean else round(sum(clean) / len(clean), 4)


def _num(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return float(value) if isinstance(value, (int, float)) else 0.0


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _path_value(row: Dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = row
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _quantile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    position = (len(values) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _round4(value: float) -> float:
    rounded = round(float(value), 4)
    return 0.0 if rounded == 0 else rounded


def _pair_key(row: Dict[str, Any]) -> tuple[str]:
    return (_evaluation_unit_id(row),)


def _best_set(actual: List[str], accepted: List[List[str]]) -> Optional[List[str]]:
    if not accepted:
        return None
    return max(
        accepted,
        key=lambda item: (
            _set_scores(actual, item)["f1"] or 0.0,
            len(set(actual) & set(item)),
            -abs(len(set(actual)) - len(set(item))),
        ),
    )


def _sets(value: Any) -> List[List[str]]:
    if not isinstance(value, list) or not value:
        return []
    return [_list(value)] if all(not isinstance(item, list) for item in value) else [_list(item) for item in value if isinstance(item, list)]


def _constraint_checks(output: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    report = output.get("constraint_report") if isinstance(output.get("constraint_report"), dict) else {}
    data = report.get("data") if isinstance(report.get("data"), dict) else report
    return {item.get("name"): item for item in (data.get("checks") if isinstance(data, dict) else []) or [] if isinstance(item, dict) and item.get("name")}


def _poi_refs(output: Dict[str, Any]) -> List[str]:
    return _unique(_poi_refs_all(output))


def _poi_refs_all(output: Dict[str, Any]) -> List[str]:
    refs = _refs_from_items(output.get("attractions") or [])
    for day in output.get("daily_itinerary") or []:
        if isinstance(day, dict):
            refs.extend(_refs_from_items(day.get("attractions") or day.get("pois") or day.get("activities") or []))
    return refs


def _planned_poi_refs(output: Dict[str, Any]) -> List[str]:
    itinerary_refs: List[str] = []
    for day in output.get("daily_itinerary") or []:
        if isinstance(day, dict):
            itinerary_refs.extend(_refs_from_items(day.get("attractions") or day.get("pois") or day.get("activities") or []))
    return itinerary_refs or _refs_from_items(output.get("attractions") or [])


def _refs_from_items(items: Any) -> List[str]:
    refs: List[str] = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, str):
            refs.append(item)
        elif isinstance(item, dict):
            nested = item.get("poi") if isinstance(item.get("poi"), dict) else {}
            ref = item.get("poi_id") or item.get("id") or item.get("name") or nested.get("poi_id") or nested.get("id") or nested.get("name")
            if ref:
                refs.append(str(ref))
    return refs


def _agents(output: Dict[str, Any], trace: Dict[str, Any]) -> List[str]:
    return _unique(_list(output.get("used_agents") or trace.get("executed_agents")))


def _agents_raw(output: Dict[str, Any], trace: Dict[str, Any]) -> List[str]:
    return _list(output.get("used_agents") or trace.get("executed_agents"))


def _called_tools(output: Dict[str, Any], trace: Dict[str, Any]) -> List[str]:
    names = []
    for call in output.get("called_tools") or trace.get("tool_calls") or []:
        names.append(str((call.get("tool_name") or call.get("name")) if isinstance(call, dict) else call))
    return _unique(names or _list(trace.get("executed_tools")))


def _called_tools_raw(output: Dict[str, Any], trace: Dict[str, Any]) -> List[str]:
    names = []
    for call in output.get("called_tools") or trace.get("tool_calls") or []:
        names.append(str((call.get("tool_name") or call.get("name")) if isinstance(call, dict) else call))
    return names or _list(trace.get("executed_tools"))


def _duplicate_count(values: List[str]) -> int:
    normalized = [_norm(value) for value in values if _norm(value)]
    return len(normalized) - len(set(normalized))


def _forbidden_tool_call_count(raw_tools: List[str], forbidden_tools: set[str]) -> int:
    forbidden = {_norm(tool) for tool in forbidden_tools}
    return sum(1 for tool in raw_tools if _norm(tool) in forbidden)


def _set_exact_rate(left: List[str], right: List[str]) -> float:
    return 1.0 if set(left) == set(right) else 0.0


def _agent_success_rate(trace: Dict[str, Any]) -> Optional[float]:
    runs = trace.get("agent_runs") if isinstance(trace.get("agent_runs"), list) else []
    if not runs:
        return None
    successful = sum(
        1
        for run in runs
        if isinstance(run, dict)
        and str(run.get("status") or "").lower() not in _FAILED_STATUSES
        and not run.get("error")
    )
    return _ratio(successful, len(runs))


def _tool_call_success_rate(output: Dict[str, Any], trace: Dict[str, Any]) -> Optional[float]:
    calls = trace.get("tool_calls") if isinstance(trace.get("tool_calls"), list) else output.get("called_tools")
    calls = calls if isinstance(calls, list) else []
    if not calls:
        return None
    successful = sum(1 for call in calls if _tool_call_success(call))
    return _ratio(successful, len(calls))


def _tool_call_success(call: Any) -> bool:
    if not isinstance(call, dict):
        return False
    status = str(call.get("status") or "").lower()
    return (
        status in {"completed", "success"}
        and call.get("success") is not False
        and not call.get("error")
    )


def _tool_failure_types(output: Dict[str, Any], trace: Dict[str, Any]) -> List[str]:
    calls = trace.get("tool_calls") if isinstance(trace.get("tool_calls"), list) else output.get("called_tools")
    failures = []
    for call in calls if isinstance(calls, list) else []:
        if _tool_call_success(call):
            continue
        name = str((call.get("tool_name") or call.get("name") or "unknown") if isinstance(call, dict) else "unknown")
        status = str(call.get("status") or "unknown").lower() if isinstance(call, dict) else "unknown"
        failures.append(f"{name}:{status}")
    return _unique(failures)


def _trace_total_tokens(trace: Dict[str, Any]) -> Optional[float]:
    calls = trace.get("llm_calls") if isinstance(trace.get("llm_calls"), list) else None
    if calls is None:
        return None
    total = 0.0
    for call in calls:
        usage = call.get("usage") or call.get("tokens") if isinstance(call, dict) else {}
        if isinstance(usage, dict):
            total += _number(usage.get("total_tokens")) or 0.0
    return _round4(total)


def _trace_cost(trace: Dict[str, Any]) -> Optional[float]:
    values = []
    for call_type in ("llm_calls", "api_calls"):
        for call in trace.get(call_type) or []:
            if isinstance(call, dict):
                value = _first_float(
                    call.get("estimated_cost"),
                    call.get("estimated_cost_cny"),
                    call.get("cost"),
                    call.get("cost_cny"),
                    _nested(call, "usage", "estimated_cost"),
                    _nested(call, "usage", "cost"),
                )
                if value is not None:
                    values.append(value)
    return None if not values else _round4(sum(values))


def _trace_standardized_cost(trace: Dict[str, Any]) -> Optional[float]:
    values = []
    for call_type in ("llm_calls", "api_calls"):
        for call in trace.get(call_type) or []:
            if isinstance(call, dict):
                value = _first_float(
                    call.get("standardized_estimated_cost"),
                    call.get("standardized_estimated_cost_cny"),
                    call.get("estimated_cost"),
                    call.get("estimated_cost_cny"),
                )
                if value is not None:
                    values.append(value)
    return None if not values else _round4(sum(values))


def _trace_actual_cost(trace: Dict[str, Any]) -> Optional[float]:
    values = []
    saw_actual_field = False
    for call_type in ("llm_calls", "api_calls"):
        for call in trace.get(call_type) or []:
            if isinstance(call, dict) and (
                "actual_cost" in call or "actual_cost_cny" in call
            ):
                saw_actual_field = True
                value = _first_float(call.get("actual_cost"), call.get("actual_cost_cny"))
                if value is not None:
                    values.append(value)
    return None if not saw_actual_field or not values else _round4(sum(values))


def _has_failed_tool_evidence(output: Dict[str, Any]) -> bool:
    calls = output.get("called_tools") if isinstance(output.get("called_tools"), list) else []
    results = (output.get("tool_results") or {}).values() if isinstance(output.get("tool_results"), dict) else []
    bad_call = any(isinstance(item, dict) and (item.get("success") is False or item.get("error") or str(item.get("status") or "").lower() in _FAILED_STATUSES) for item in calls)
    bad_result = any(isinstance(item, dict) and (item.get("success") is False or str(item.get("status") or "").lower() in _FAILED_STATUSES) for item in results)
    return bad_call or bad_result


def _nested(value: Dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _canon(value: Any, catalog: Dict[str, Any]) -> str:
    text = str(value or "unknown").strip()
    return str((catalog.get("task_aliases") or {}).get(text, text))


def _list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Iterable) and not isinstance(value, dict):
        return [str(item) for item in value if item]
    return [str(value)]


def _unique(values: Iterable[str]) -> List[str]:
    seen, result = set(), []
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _first_int(*values: Any) -> Optional[int]:
    for value in values:
        try:
            if value is not None and value != "":
                return int(value)
        except (TypeError, ValueError):
            pass
    return None


def _first_float(*values: Any) -> Optional[float]:
    for value in values:
        try:
            if value is not None and value != "":
                return float(value)
        except (TypeError, ValueError):
            pass
    return None


def _contains_rain(value: Any) -> bool:
    return bool(_rainy_day_indexes(value))


def _rainy_day_indexes(value: Any) -> List[int]:
    weather = value if isinstance(value, dict) else {}
    rainy_days: List[int] = []
    for index, day in enumerate(weather.get("daily_weather") or [], start=1):
        if not isinstance(day, dict):
            continue
        if _weather_day_has_rain(day):
            day_index = _first_int(day.get("day_index"), day.get("day"), index)
            if day_index is not None:
                rainy_days.append(day_index)
    if rainy_days:
        seen: set[int] = set()
        unique_days: List[int] = []
        for day in rainy_days:
            if day in seen:
                continue
            seen.add(day)
            unique_days.append(day)
        return unique_days
    scenario = str(
        weather.get("scenario_type")
        or weather.get("requested_scenario_type")
        or ""
    ).lower()
    if scenario == "rain" or "雨" in scenario:
        days = len(weather.get("daily_weather") or []) or 1
        return list(range(1, days + 1))
    return []


def _weather_day_has_rain(day: Dict[str, Any]) -> bool:
    labels = [
        str(day.get(key) or "").lower()
        for key in ("state", "condition", "weather", "scenario_type", "weather_type")
    ]
    labels.extend(str(item or "").lower() for item in day.get("risk_tags") or [])
    if any(label == "rain" or "rainy" in label or "雨" in label for label in labels):
        return True
    precipitation = _first_float(day.get("precipitation_mm"))
    return precipitation is not None and precipitation > 0


def _norm(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return _CITY_VALUE_ALIASES.get(normalized, normalized)


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    return None if denominator == 0 else round(numerator / denominator, 4)


def _status(value: Any) -> str:
    text = str(value or "na").lower()
    return "na" if text == "na" else "passed" if text == "passed" else "failed"
