"""Run-level audit metrics for formal paper experiments.

The audit is intentionally derived only from persisted method output and trace
records. It does not look at gold labels and it does not repair method output.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Optional


RUN_AUDIT_SCHEMA_VERSION = "ctp-run-audit-v1"

_FAILED_STATUSES = {
    "failed",
    "error",
    "timeout",
    "cancelled",
    "canceled",
    "aborted",
    "expired",
    "stale",
}
_SUCCESS_STATUSES = {"completed", "success", "ok"}


def build_run_audit(
    *,
    method: str,
    output: Dict[str, Any],
    trace: Optional[Dict[str, Any]],
    latency_ms: Optional[float],
    ttft_ms: Optional[float],
) -> Dict[str, Any]:
    """Build one method-blind execution audit block for a benchmark row."""
    trace_record = trace or {}
    method_output = output if isinstance(output, dict) else {}

    planned_agents = _unique(
        _list(method_output.get("planned_agents") or trace_record.get("planned_agents"))
    )
    used_agents = _unique(
        _list(method_output.get("used_agents") or trace_record.get("executed_agents"))
    )
    executed_agents = _unique(
        _list(trace_record.get("executed_agents") or used_agents)
    )
    planned_tools = _unique(
        _list(method_output.get("planned_tools") or trace_record.get("planned_tools"))
    )

    raw_agent_calls = _agent_call_names(trace_record)
    raw_tool_calls = _tool_call_names(_tool_call_records(method_output, trace_record))
    called_tools = _unique(raw_tool_calls)
    executed_tools = _unique(
        _list(trace_record.get("executed_tools") or called_tools)
    )

    agent_success = _agent_success_counts(trace_record)
    tool_success = _tool_success_counts(_tool_call_records(method_output, trace_record))
    llm_calls = _dict_items(trace_record.get("llm_calls"))
    api_calls = _dict_items(trace_record.get("api_calls"))
    tokens = _token_totals(llm_calls)
    agent_llm_records = _agent_llm_records(method_output, trace_record)
    agent_tokens = _token_totals(agent_llm_records)
    cost_totals = _cost_totals(trace_record)

    metrics = {
        "planned_agent_count": len(planned_agents),
        "used_agent_count": len(used_agents),
        "executed_agent_count": len(executed_agents),
        "agent_call_count": _first_int(trace_record.get("agent_call_count"), len(raw_agent_calls)),
        "successful_agent_call_count": agent_success["successful"],
        "failed_agent_call_count": agent_success["failed"],
        "duplicate_agent_call_count": _duplicate_count(raw_agent_calls),
        "planned_executed_agent_coverage": _coverage(planned_agents, executed_agents),
        "planned_actual_agent_consistency": _set_exact(planned_agents, executed_agents),
        "agent_execution_success_rate": _rate(
            agent_success["successful"],
            agent_success["total"],
        ),
        "planned_tool_count": len(planned_tools),
        "called_tool_count": len(raw_tool_calls),
        "executed_tool_count": len(executed_tools),
        "successful_tool_call_count": tool_success["successful"],
        "failed_tool_call_count": tool_success["failed"],
        "duplicate_tool_call_count": _duplicate_count(raw_tool_calls),
        "planned_executed_tool_coverage": _coverage(planned_tools, executed_tools),
        "planned_actual_tool_consistency": _set_exact(planned_tools, executed_tools),
        "tool_call_success_rate": _rate(tool_success["successful"], tool_success["total"]),
        "llm_call_count": _first_int(trace_record.get("llm_call_count"), len(llm_calls)),
        "agent_llm_call_count": _agent_llm_call_count(agent_llm_records),
        "api_call_count": _first_int(trace_record.get("api_call_count"), len(api_calls)),
        "prompt_tokens": tokens["prompt_tokens"],
        "completion_tokens": tokens["completion_tokens"],
        "total_tokens": tokens["total_tokens"],
        "agent_prompt_tokens": agent_tokens["prompt_tokens"],
        "agent_completion_tokens": agent_tokens["completion_tokens"],
        "agent_total_tokens": agent_tokens["total_tokens"],
        "estimated_cost": cost_totals["estimated_cost"],
        "standardized_estimated_cost": cost_totals["standardized_estimated_cost"],
        "actual_cost": cost_totals["actual_cost"],
        "latency_ms": latency_ms,
        "ttft_ms": ttft_ms,
        "trace_total_duration_ms": _first_float(trace_record.get("total_duration_ms")),
        "llm_total_duration_ms": _sum_field(llm_calls, "duration_ms"),
        "agent_total_duration_ms": _agent_total_duration(trace_record),
        "tool_total_duration_ms": _sum_field(
            _tool_call_records(method_output, trace_record),
            "duration_ms",
        ),
        "api_total_duration_ms": _sum_field(api_calls, "duration_ms"),
        "stage_total_duration_ms": _sum_mapping_values(trace_record.get("stage_timings")),
    }

    return {
        "schema_version": RUN_AUDIT_SCHEMA_VERSION,
        "method": str(method or ""),
        "planned_agents": planned_agents,
        "used_agents": used_agents,
        "executed_agents": executed_agents,
        "planned_tools": planned_tools,
        "called_tools": called_tools,
        "executed_tools": executed_tools,
        "cost": _cost_audit(trace_record),
        "metrics": _drop_none(metrics),
    }


def _tool_call_records(
    output: Dict[str, Any],
    trace: Dict[str, Any],
) -> List[Dict[str, Any]]:
    trace_calls = _dict_items(trace.get("tool_calls"))
    if trace_calls:
        return trace_calls
    return _dict_items(output.get("called_tools"))


def _agent_call_names(trace: Dict[str, Any]) -> List[str]:
    runs = _dict_items(trace.get("agent_runs"))
    if runs:
        return [
            str(run.get("agent_name") or run.get("agent") or "")
            for run in runs
            if run.get("agent_name") or run.get("agent")
        ]
    timings = trace.get("agent_timings")
    if isinstance(timings, dict) and timings:
        return [str(name) for name in timings if name]
    return _list(trace.get("executed_agents"))


def _tool_call_names(calls: List[Dict[str, Any]]) -> List[str]:
    return [
        str(call.get("tool_name") or call.get("name") or "")
        for call in calls
        if call.get("tool_name") or call.get("name")
    ]


def _agent_success_counts(trace: Dict[str, Any]) -> Dict[str, int]:
    runs = _dict_items(trace.get("agent_runs"))
    if not runs:
        total = _first_int(trace.get("agent_call_count"), len(_agent_call_names(trace))) or 0
        failed = _first_int(trace.get("failed_agent_count"), 0) or 0
        return {"total": total, "successful": max(0, total - failed), "failed": failed}
    failed = sum(1 for run in runs if _failed(run))
    successful = sum(1 for run in runs if _successful(run))
    return {"total": len(runs), "successful": successful, "failed": failed}


def _agent_llm_records(
    output: Dict[str, Any],
    trace: Dict[str, Any],
) -> List[Dict[str, Any]]:
    runs = [
        run
        for run in _dict_items(trace.get("agent_runs"))
        if _first_int(run.get("llm_call_count")) or isinstance(run.get("usage"), dict)
    ]
    if runs:
        return runs

    agent_outputs = output.get("agent_outputs")
    if isinstance(agent_outputs, dict):
        return [
            value
            for value in agent_outputs.values()
            if isinstance(value, dict)
            and (_first_int(value.get("llm_call_count")) or isinstance(value.get("usage"), dict))
        ]
    return []


def _agent_llm_call_count(records: List[Dict[str, Any]]) -> Optional[int]:
    if not records:
        return None
    count = 0
    saw_count = False
    for record in records:
        value = _first_int(record.get("llm_call_count"))
        if value is not None:
            count += value
            saw_count = True
        elif isinstance(record.get("usage"), dict):
            count += 1
            saw_count = True
    return count if saw_count else None


def _tool_success_counts(calls: List[Dict[str, Any]]) -> Dict[str, int]:
    failed = sum(1 for call in calls if _failed(call))
    successful = sum(1 for call in calls if _successful(call))
    return {"total": len(calls), "successful": successful, "failed": failed}


def _failed(item: Dict[str, Any]) -> bool:
    if item.get("success") is False:
        return True
    status = str(item.get("status") or "").lower()
    return status in _FAILED_STATUSES or bool(item.get("error"))


def _successful(item: Dict[str, Any]) -> bool:
    if _failed(item):
        return False
    if item.get("success") is True:
        return True
    status = str(item.get("status") or "").lower()
    return status in _SUCCESS_STATUSES


def _token_totals(llm_calls: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    prompt_tokens = 0.0
    completion_tokens = 0.0
    total_tokens = 0.0
    saw_prompt = saw_completion = saw_total = False
    for call in llm_calls:
        usage = call.get("usage") if isinstance(call.get("usage"), dict) else call.get("tokens")
        usage = usage if isinstance(usage, dict) else {}
        prompt = _first_float(usage.get("prompt_tokens"), usage.get("input_tokens"))
        completion = _first_float(
            usage.get("completion_tokens"),
            usage.get("output_tokens"),
        )
        total = _first_float(usage.get("total_tokens"), usage.get("tokens_used"))
        if prompt is not None:
            prompt_tokens += prompt
            saw_prompt = True
        if completion is not None:
            completion_tokens += completion
            saw_completion = True
        if total is not None:
            total_tokens += total
            saw_total = True
        elif prompt is not None or completion is not None:
            total_tokens += (prompt or 0.0) + (completion or 0.0)
            saw_total = True
    return {
        "prompt_tokens": _round4(prompt_tokens) if saw_prompt else None,
        "completion_tokens": _round4(completion_tokens) if saw_completion else None,
        "total_tokens": _round4(total_tokens) if saw_total else None,
    }


def _estimated_cost(trace: Dict[str, Any]) -> Optional[float]:
    values: List[float] = []
    for call in [*_dict_items(trace.get("llm_calls")), *_dict_items(trace.get("api_calls"))]:
        cost = _first_float(
            call.get("estimated_cost"),
            call.get("estimated_cost_cny"),
            call.get("cost"),
            call.get("cost_cny"),
            _nested(call, "usage", "estimated_cost"),
            _nested(call, "usage", "cost"),
        )
        if cost is not None:
            values.append(cost)
    return _round4(sum(values)) if values else None


def _cost_totals(trace: Dict[str, Any]) -> Dict[str, Optional[float]]:
    estimated_values: List[float] = []
    standardized_values: List[float] = []
    actual_values: List[float] = []
    saw_actual_field = False
    for call in [*_dict_items(trace.get("llm_calls")), *_dict_items(trace.get("api_calls"))]:
        estimated = _first_float(
            call.get("estimated_cost"),
            call.get("estimated_cost_cny"),
            call.get("cost"),
            call.get("cost_cny"),
            _nested(call, "usage", "estimated_cost"),
            _nested(call, "usage", "cost"),
        )
        standardized = _first_float(
            call.get("standardized_estimated_cost"),
            call.get("standardized_estimated_cost_cny"),
            estimated,
        )
        if estimated is not None:
            estimated_values.append(estimated)
        if standardized is not None:
            standardized_values.append(standardized)
        if "actual_cost" in call or "actual_cost_cny" in call:
            saw_actual_field = True
            actual = _first_float(call.get("actual_cost"), call.get("actual_cost_cny"))
            if actual is not None:
                actual_values.append(actual)
    return {
        "estimated_cost": _round4(sum(estimated_values)) if estimated_values else None,
        "standardized_estimated_cost": (
            _round4(sum(standardized_values)) if standardized_values else None
        ),
        "actual_cost": _round4(sum(actual_values)) if saw_actual_field and actual_values else None,
    }


def _cost_audit(trace: Dict[str, Any]) -> Dict[str, Any]:
    calls = [*_dict_items(trace.get("llm_calls")), *_dict_items(trace.get("api_calls"))]
    totals = _cost_totals(trace)
    snapshots: List[Dict[str, Any]] = []
    seen_snapshots: set[str] = set()
    actual_statuses: List[str] = []
    for call in calls:
        snapshot = call.get("price_snapshot")
        if isinstance(snapshot, dict):
            key = str(sorted(snapshot.items()))
            if key not in seen_snapshots:
                seen_snapshots.add(key)
                snapshots.append(snapshot)
        if call.get("actual_cost_status"):
            actual_statuses.append(str(call["actual_cost_status"]))
    return {
        "estimated_cost": totals["estimated_cost"],
        "standardized_estimated_cost": totals["standardized_estimated_cost"],
        "actual_cost": totals["actual_cost"],
        "actual_cost_available": totals["actual_cost"] is not None,
        "actual_cost_statuses": _unique(actual_statuses),
        "price_snapshots": snapshots,
    }


def _agent_total_duration(trace: Dict[str, Any]) -> Optional[float]:
    runs = _dict_items(trace.get("agent_runs"))
    if runs:
        return _sum_field(runs, "duration_ms")
    timings = trace.get("agent_timings")
    if isinstance(timings, dict):
        return _sum_field(
            [value for value in timings.values() if isinstance(value, dict)],
            "duration_ms",
        )
    return None


def _sum_field(items: List[Dict[str, Any]], key: str) -> Optional[float]:
    values = [_first_float(item.get(key)) for item in items]
    values = [value for value in values if value is not None]
    return _round4(sum(values)) if values else None


def _sum_mapping_values(value: Any) -> Optional[float]:
    if not isinstance(value, dict):
        return None
    values = [_first_float(item) for item in value.values()]
    values = [item for item in values if item is not None]
    return _round4(sum(values)) if values else None


def _coverage(planned: List[str], executed: List[str]) -> Optional[float]:
    if not planned:
        return None
    return _rate(len(set(planned) & set(executed)), len(set(planned)))


def _set_exact(left: List[str], right: List[str]) -> float:
    return 1.0 if set(left) == set(right) else 0.0


def _rate(numerator: int, denominator: int) -> Optional[float]:
    return None if denominator <= 0 else round(numerator / denominator, 4)


def _duplicate_count(values: List[str]) -> int:
    counts = Counter(str(value).lower() for value in values if value)
    return sum(count - 1 for count in counts.values() if count > 1)


def _dict_items(value: Any) -> List[Dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Iterable) and not isinstance(value, dict):
        return [str(item) for item in value if item]
    return [str(value)]


def _unique(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _first_int(*values: Any) -> Optional[int]:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _first_float(*values: Any) -> Optional[float]:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _round4(value: float) -> float:
    rounded = round(float(value), 4)
    return 0.0 if rounded == 0 else rounded


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _drop_none(values: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}
