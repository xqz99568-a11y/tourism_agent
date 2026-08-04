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
_BOOTSTRAP_SAMPLES = 2000
_BOOTSTRAP_SEED = 20260725
_DESCRIPTIVE_METRICS = (
    ("stsr", ("metrics", "stsr")),
    ("evaluation_hcsr", ("metrics", "evaluation_hcsr")),
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
    "fixed_multi_agent": "M2 Fixed Multi-Agent",
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
        "| Method | Cases | STSR | HCSR | Agent F1 | Tool F1 | Latency ms | Agent calls | Tool calls |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for method in _method_order(methods):
        row = methods.get(method) or {}
        lines.append(
            f"| {_method_label(method)} | {row.get('case_count', 0)} | {_fmt(row.get('stsr_rate'))} "
            f"| {_fmt(row.get('evaluation_hcsr_mean'))} | {_fmt(row.get('agent_selection_f1_mean'))} "
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
        return _tool_rule(output, trace, ["weather_query"]) if output.get("weather") or "weather_query" in _list(gold.get("required_tools")) else ("na", {})
    if rule_id == "H_BUDGET_EVIDENCE":
        return _tool_rule(output, trace, ["budget_calculator"]) if output.get("budget") or "budget_calculator" in _list(gold.get("required_tools")) else ("na", {})
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
    h_pass = sum(item["status"] == "passed" for item in hcsr)
    h_fail = sum(item["status"] == "failed" for item in hcsr)
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


def _tool_rule(output: Dict[str, Any], trace: Dict[str, Any], required: List[str]) -> tuple[str, Dict[str, Any]]:
    missing = [name for name in required if not _tool_ok(name, output, trace)]
    return "passed" if not missing else "failed", {"required_tools": required, "missing_or_failed": missing}


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
    output_terms = set(_weather_terms(weather))
    evidence_terms = set(_weather_terms(data))
    return bool(evidence_terms) and (not output_terms or output_terms <= evidence_terms)


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
    actual = _list(_nested(output, "metadata", "scheduler", "ticket", key) or _nested(output, "metadata", "scheduler", "decision", key))
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
            poi_data.get("preferences"),
            poi_input.get("preferences"),
        )
    if slot in {"traveler_group", "people_type"}:
        return _first_existing(
            _nested(output, "metadata", "goal_state_slots", "traveler_group"),
            _nested(output, "metadata", "scheduler", "ticket", "current_slots", "traveler_group"),
            poi_data.get("traveler_group"),
            poi_input.get("traveler_group"),
            poi_data.get("people"),
            poi_input.get("people"),
        )
    if slot in {"special_requirements", "requirements"}:
        return _first_existing(
            _nested(output, "metadata", "goal_state_slots", "special_requirements"),
            _nested(output, "metadata", "scheduler", "ticket", "current_slots", "special_requirements"),
            poi_data.get("special_requirements"),
            poi_input.get("special_requirements"),
        )
    if slot in {"weather_scenario", "scenario_type"}:
        return _first_existing(weather.get("scenario_type"), weather.get("weather_type"), weather_data.get("scenario_type"), weather_data.get("requested_scenario_type"), weather_input.get("scenario_type"), weather_input.get("weather_scenario"))
    return _MISSING


def _slot_from_mapping(mapping: Dict[str, Any], slot: str) -> Any:
    aliases = {
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
    affected_days = _affected_days(case, gold)
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
    if previous.get("budget") and not _budget_matches(previous.get("budget"), output.get("budget")):
        issues.append({"field": "budget"})
    if previous.get("attractions") and set(_refs_from_items(previous.get("attractions"))) != set(_refs_from_items(output.get("attractions") or [])):
        issues.append({"field": "attractions"})
    return ("passed" if not issues else "failed"), {"affected_days": sorted(affected_days), "issues": issues}


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
