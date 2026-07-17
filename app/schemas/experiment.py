"""Schemas for formal experiment method outputs."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


EXPERIMENT_OUTPUT_SCHEMA_VERSION = "ctp-experiment-output-v1"


class ExperimentToolCallSummary(BaseModel):
    """Compact tool-call record copied from the trace."""

    tool_name: str
    status: str = "unknown"
    success: Optional[bool] = None
    arguments: Dict[str, Any] = Field(default_factory=dict)
    duration_ms: Optional[float] = None
    error: Optional[str] = None


class ExperimentMethodOutput(BaseModel):
    """Unified output shape required by the paper experiment pipeline."""

    schema_version: str = EXPERIMENT_OUTPUT_SCHEMA_VERSION
    case_id: str
    method: str
    task_type: str = "unknown"
    used_agents: List[str] = Field(default_factory=list)
    called_tools: List[ExperimentToolCallSummary] = Field(default_factory=list)
    trip_days: Optional[int] = None
    daily_itinerary: List[Dict[str, Any]] = Field(default_factory=list)
    budget: Optional[Dict[str, Any]] = None
    weather: Optional[Dict[str, Any]] = None
    weather_adjustments: List[Dict[str, Any]] = Field(default_factory=list)
    constraint_report: Dict[str, Any] = Field(default_factory=dict)
    hard_constraint_passed_count: int = 0
    hard_constraint_failed_count: int = 0
    hard_constraint_applicable_count: int = 0
    hard_constraints_all_satisfied: Optional[bool] = None
    hcsr: Optional[float] = None
    execution_status: str = "completed"
    final_answer: str = ""
    raw_output: Any = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


def normalize_experiment_output(
    *,
    case: Dict[str, Any],
    method: str,
    raw_output: Any,
    trace: Optional[Dict[str, Any]],
    error: Optional[str] = None,
    constraint_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Normalize any method output into the experiment output contract."""
    trace_record = trace or {}
    if _already_normalized(raw_output):
        payload = dict(raw_output)
        if error or _has_failed_tool_calls(payload.get("called_tools")) or _has_failed_tool_results(payload.get("tool_results")):
            payload["execution_status"] = "failed"
        if constraint_report is not None:
            payload.update(
                {
                    "constraint_report": constraint_report,
                    "hard_constraint_passed_count": _constraint_count(constraint_report, "passed_count"),
                    "hard_constraint_failed_count": _constraint_count(constraint_report, "failed_count"),
                    "hard_constraint_applicable_count": _constraint_count(constraint_report, "applicable_count"),
                    "hard_constraints_all_satisfied": _constraint_all_passed(constraint_report),
                    "hcsr": _constraint_hcsr(constraint_report),
                }
            )
        model = ExperimentMethodOutput.model_validate(payload)
        return model.model_dump(mode="json")

    raw_mapping = raw_output if isinstance(raw_output, dict) else {}
    tool_calls = [
        ExperimentToolCallSummary(
            tool_name=str(call.get("tool_name") or call.get("name") or ""),
            status=str(call.get("status") or "unknown"),
            success=call.get("success"),
            arguments=call.get("params") or call.get("arguments") or {},
            duration_ms=call.get("duration_ms") if isinstance(call.get("duration_ms"), (int, float)) else None,
            error=call.get("error"),
        )
        for call in trace_record.get("tool_calls") or []
        if call.get("tool_name") or call.get("name")
    ]
    used_agents = _as_text_list(
        trace_record.get("executed_agents")
        or trace_record.get("planned_agents")
        or trace_record.get("selected_agents")
    )
    status = _execution_status(error, trace_record, raw_mapping, tool_calls)
    final_answer = _final_answer(raw_output)
    model = ExperimentMethodOutput(
        case_id=str(case.get("case_id") or ""),
        method=method,
        task_type=_infer_task_type(case, trace_record, raw_mapping),
        used_agents=used_agents,
        called_tools=tool_calls,
        trip_days=_first_int(
            raw_mapping.get("trip_days"),
            raw_mapping.get("days"),
            (raw_mapping.get("trip") or {}).get("days") if isinstance(raw_mapping.get("trip"), dict) else None,
            (case.get("slots") or {}).get("duration") if isinstance(case.get("slots"), dict) else None,
            case.get("days"),
            case.get("duration"),
        ),
        daily_itinerary=_as_dict_list(
            raw_mapping.get("daily_itinerary")
            or raw_mapping.get("itinerary")
            or ((raw_mapping.get("trip") or {}).get("daily_itinerary") if isinstance(raw_mapping.get("trip"), dict) else None)
        ),
        budget=_first_mapping(raw_mapping.get("budget"), raw_mapping.get("budget_result")),
        weather=_first_mapping(raw_mapping.get("weather"), raw_mapping.get("weather_result")),
        weather_adjustments=_as_dict_list(raw_mapping.get("weather_adjustments")),
        constraint_report=constraint_report or {},
        hard_constraint_passed_count=_constraint_count(constraint_report, "passed_count"),
        hard_constraint_failed_count=_constraint_count(constraint_report, "failed_count"),
        hard_constraint_applicable_count=_constraint_count(constraint_report, "applicable_count"),
        hard_constraints_all_satisfied=_constraint_all_passed(constraint_report),
        hcsr=_constraint_hcsr(constraint_report),
        execution_status=status,
        final_answer=final_answer,
        raw_output=raw_output,
        metadata={
            "output_contract": EXPERIMENT_OUTPUT_SCHEMA_VERSION,
            "trace_schema_version": trace_record.get("schema_version"),
            "tool_call_count": len(tool_calls),
        },
    )
    return model.model_dump(mode="json")


def _already_normalized(value: Any) -> bool:
    return isinstance(value, dict) and value.get("schema_version") == EXPERIMENT_OUTPUT_SCHEMA_VERSION


def _execution_status(
    error: Optional[str],
    trace_record: Dict[str, Any],
    raw_mapping: Dict[str, Any],
    tool_calls: List[ExperimentToolCallSummary],
) -> str:
    if error:
        return "failed"
    if _has_failed_tool_calls([item.model_dump(mode="json") for item in tool_calls]):
        return "failed"
    if _has_failed_tool_results(raw_mapping.get("tool_results")):
        return "failed"
    trace_status = str(trace_record.get("status") or "").lower()
    if trace_status in {"failed", "error", "timeout", "cancelled", "canceled", "aborted"}:
        return "failed"
    raw_status = str(raw_mapping.get("execution_status") or "").lower()
    if raw_status in {"failed", "error", "timeout", "cancelled", "canceled", "aborted"}:
        return "failed"
    return "completed"


def _has_failed_tool_calls(calls: Any) -> bool:
    if not isinstance(calls, list):
        return False
    for call in calls:
        if isinstance(call, ExperimentToolCallSummary):
            call = call.model_dump(mode="json")
        if not isinstance(call, dict):
            continue
        if call.get("success") is False:
            return True
        status = str(call.get("status") or "").lower()
        if status in {"failed", "error", "timeout", "cancelled", "canceled", "aborted"}:
            return True
        if call.get("error"):
            return True
    return False


def _has_failed_tool_results(results: Any) -> bool:
    if isinstance(results, dict):
        iterable = results.values()
    elif isinstance(results, list):
        iterable = results
    else:
        return False
    for result in iterable:
        if not isinstance(result, dict):
            continue
        if result.get("success") is False:
            return True
        status = str(result.get("status") or "").lower()
        if status in {"failed", "error", "timeout", "cancelled", "canceled", "aborted"}:
            return True
    return False


def _final_answer(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("final_answer", "answer", "content", "text", "message"):
            if value.get(key):
                return str(value[key])
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except TypeError:
            return str(value)
    return str(value)


def _infer_task_type(
    case: Dict[str, Any],
    trace: Dict[str, Any],
    raw_mapping: Dict[str, Any],
) -> str:
    for candidate in (
        raw_mapping.get("task_type"),
        case.get("task_type"),
        case.get("intent"),
        trace.get("intent") if trace.get("intent") != "general_chat" else None,
    ):
        if candidate:
            return str(candidate)
    text = str(case.get("user_input") or "")
    slots = case.get("slots") if isinstance(case.get("slots"), dict) else {}
    if any(word in text for word in ("天气", "下雨", "高温", "雨天")):
        return "weather_adjustment"
    if any(word in text for word in ("预算", "费用", "多少钱")) or slots.get("budget"):
        return "budget_control"
    if any(word in text for word in ("景点", "推荐", "打卡")):
        return "attraction_recommendation"
    if any(word in text for word in ("规划", "行程", "旅游", "游")) or slots.get("destination"):
        return "trip_planning"
    return "general_chat"


def _as_text_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item]
    return [str(value)]


def _as_dict_list(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, dict):
        if isinstance(value.get("days"), list):
            return [item for item in value["days"] if isinstance(item, dict)]
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _first_mapping(*values: Any) -> Optional[Dict[str, Any]]:
    for value in values:
        if isinstance(value, dict):
            return value
    return None


def _first_int(*values: Any) -> Optional[int]:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _constraint_data(report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    data = report.get("data")
    return data if isinstance(data, dict) else report


def _constraint_count(report: Optional[Dict[str, Any]], key: str) -> int:
    try:
        return int(_constraint_data(report).get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _constraint_all_passed(report: Optional[Dict[str, Any]]) -> Optional[bool]:
    data = _constraint_data(report)
    if not data or int(data.get("applicable_count") or 0) == 0:
        return None
    return bool(data.get("all_passed"))


def _constraint_hcsr(report: Optional[Dict[str, Any]]) -> Optional[float]:
    applicable = _constraint_count(report, "applicable_count")
    if applicable == 0:
        return None
    return round(_constraint_count(report, "passed_count") / applicable, 4)
