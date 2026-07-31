"""Quality gate for paper-level tourism benchmark datasets.

The formal preflight checks whether an experiment can run.  This module checks
whether the benchmark is actually evaluable for the paper: every unit needs
method-blind gold labels, valid agent/tool targets, fixed-data city support,
and enough metadata for the independent evaluator to score it.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping

from app.core.experiment_method_input import parse_visible_request_slots
from app.core.fixed_data import FIXED_CITY_IDS, get_fixed_tourism_data
from app.core.goal_state_scheduler import CANONICAL_AGENT_ORDER, normalize_slots
from app.core.independent_evaluator import load_rule_catalog
from app.tools.research_tools import GENERATION_TOOL_NAMES


BENCHMARK_DATASET_QUALITY_SCHEMA_VERSION = "ctp-benchmark-dataset-quality-v1"

NO_TOOL_TASK_TYPES = {"general_chat", "clarification"}
TOURISM_TASK_TYPES = {
    "trip_planning",
    "attraction_recommendation",
    "weather_query",
    "budget_query",
    "partial_replan",
    "weather_adjustment",
}
RECOMMENDED_FORMAL_TASK_TYPES = (
    "trip_planning",
    "attraction_recommendation",
    "weather_query",
    "budget_query",
    "partial_replan",
    "weather_adjustment",
    "clarification",
    "general_chat",
)
DEVELOPMENT_COVERAGE_GATE_CASE_COUNT = 20
TASK_REQUIRED_TOOLS = {
    "trip_planning": {"poi_search", "weather_query", "budget_calculator"},
    "attraction_recommendation": {"poi_search"},
    "weather_query": {"weather_query"},
    "budget_query": {"budget_calculator"},
    "weather_adjustment": {"weather_query"},
}
TASK_REQUIRED_AGENTS = {
    "trip_planning": {"attraction", "weather", "itinerary", "budget"},
    "attraction_recommendation": {"attraction"},
    "weather_query": {"weather"},
    "budget_query": {"budget"},
    "weather_adjustment": {"weather", "itinerary"},
}
HARD_CONSTRAINT_KEYS = {
    "duration_days",
    "duration",
    "days",
    "trip_days",
    "min_attractions",
    "max_attractions",
    "max_pois_per_day",
    "budget_limit",
    "max_budget",
    "must_include_pois",
    "required_pois",
    "forbidden_pois",
    "avoid_pois",
    "weather_adjustment_required",
    "traveler_group",
    "changed_slots",
    "preserved_slots",
    "missing_slots",
}


def build_benchmark_dataset_quality_report(
    *,
    document: Any,
    cases: Iterable[Mapping[str, Any]],
    expected_case_count: int | None = None,
    strict_formal: bool = True,
) -> dict[str, Any]:
    """Return a read-only benchmark quality report.

    ``case_count`` follows the paper's statistical unit: a multi-turn scenario
    counts as one case.  ``total_unit_count`` counts actual generation/evaluation
    turns.
    """
    errors: list[str] = []
    warnings: list[str] = []
    raw_cases = [case for case in cases if isinstance(case, Mapping)]
    units = _flatten_units(raw_cases)
    task_types = _allowed_task_types(errors)
    task_distribution: Counter[str] = Counter()
    city_distribution: Counter[str] = Counter()
    label_counts: Counter[str] = Counter()
    unit_reports: list[dict[str, Any]] = []

    if expected_case_count is not None and len(raw_cases) != expected_case_count:
        errors.append(
            f"case_count mismatch: expected {expected_case_count}, got {len(raw_cases)}"
        )

    if not raw_cases:
        errors.append("benchmark must contain at least one case")
    if not units:
        errors.append("benchmark must contain at least one evaluable unit")

    _validate_case_ids(raw_cases, errors)
    duplicate_inputs = _duplicate_visible_inputs(units)
    if duplicate_inputs:
        message = (
            "duplicate visible user inputs found: "
            + ", ".join(item["example_labels"][0] for item in duplicate_inputs[:5])
        )
        if strict_formal:
            errors.append(message)
        else:
            warnings.append(message)

    for unit in units:
        unit_report = _validate_unit(
            unit,
            task_types=task_types,
            strict_formal=strict_formal,
            errors=errors,
            warnings=warnings,
        )
        unit_reports.append(unit_report)
        task_distribution.update([unit_report["task_type"]])
        if unit_report.get("city_id"):
            city_distribution.update([str(unit_report["city_id"])])
        label_counts.update(unit_report.get("present_labels") or [])

    _validate_distribution(
        task_distribution=task_distribution,
        city_distribution=city_distribution,
        expected_case_count=expected_case_count,
        strict_formal=strict_formal,
        errors=errors,
        warnings=warnings,
    )

    return {
        "schema_version": BENCHMARK_DATASET_QUALITY_SCHEMA_VERSION,
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "dataset": {
            "dataset_id": _document_value(document, "dataset_id"),
            "dataset_version": _document_value(document, "dataset_version"),
            "schema_version": _document_value(document, "schema_version"),
            "expected_case_count": expected_case_count,
            "case_count": len(raw_cases),
            "scenario_case_count": sum(1 for case in raw_cases if _is_scenario_case(case)),
            "total_unit_count": len(units),
            "fixed_city_ids": list(FIXED_CITY_IDS),
        },
        "coverage": {
            "task_distribution": dict(sorted(task_distribution.items())),
            "city_distribution": dict(sorted(city_distribution.items())),
            "label_field_counts": dict(sorted(label_counts.items())),
            "duplicate_visible_input_groups": duplicate_inputs,
            "recommended_task_types": list(RECOMMENDED_FORMAL_TASK_TYPES),
        },
        "policy": {
            "strict_formal": strict_formal,
            "gold_labels_required": strict_formal,
            "required_agent_sets": True,
            "required_tool_sets": True,
            "fixed_offline_city_only": True,
            "generation_tools": list(GENERATION_TOOL_NAMES),
            "business_agents": list(CANONICAL_AGENT_ORDER),
        },
        "units": unit_reports,
    }


def assert_benchmark_dataset_quality_passed(report: Mapping[str, Any]) -> None:
    if report.get("status") == "passed":
        return
    errors = report.get("errors") if isinstance(report.get("errors"), list) else []
    details = "\n".join(f"- {error}" for error in errors) or "- unknown benchmark quality error"
    raise RuntimeError(f"benchmark dataset quality check failed:\n{details}")


def _allowed_task_types(errors: list[str]) -> set[str]:
    try:
        catalog = load_rule_catalog()
    except Exception as exc:
        errors.append(f"evaluation rule catalog unavailable: {exc}")
        return set(RECOMMENDED_FORMAL_TASK_TYPES)
    return {str(item) for item in catalog.get("task_types") or []}


def _validate_case_ids(cases: list[Mapping[str, Any]], errors: list[str]) -> None:
    seen: set[str] = set()
    for index, case in enumerate(cases, start=1):
        case_id = _case_id(case)
        label = case_id or f"case#{index}"
        if not case_id:
            errors.append(f"{label}: case_id is required")
            continue
        if case_id in seen:
            errors.append(f"{label}: duplicate case_id")
        seen.add(case_id)
        if _is_scenario_case(case):
            _validate_turn_ids(case, label, errors)


def _validate_turn_ids(case: Mapping[str, Any], label: str, errors: list[str]) -> None:
    seen: set[str] = set()
    for index, turn in enumerate(case.get("turns") or [], start=1):
        if not isinstance(turn, Mapping):
            errors.append(f"{label}/turn#{index}: turn must be an object")
            continue
        turn_id = str(turn.get("turn_id") or turn.get("id") or f"turn_{index:02d}")
        if turn_id in seen:
            errors.append(f"{label}/{turn_id}: duplicate turn_id")
        seen.add(turn_id)


def _validate_unit(
    unit: Mapping[str, Any],
    *,
    task_types: set[str],
    strict_formal: bool,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    label = _unit_label(unit)
    gold = _gold_payload(unit)
    task_type = _normalized_task_type(gold.get("task_type") or unit.get("task_type"))
    present_labels = _present_label_fields(unit, gold)
    visible_slots = parse_visible_request_slots(
        str(unit.get("user_input") or ""),
        dialogue_history=unit.get("dialogue_history"),
    )
    gold_slots = _gold_slots(unit, gold)
    city_id = _resolve_city(gold_slots.get("destination") or visible_slots.get("destination"))

    _require_visible_input(unit, label, errors)
    if not gold:
        _label_issue(
            f"{label}: missing expected/gold labels; formal results would not be independently scorable",
            strict_formal,
            errors,
            warnings,
        )
    if task_type == "unknown":
        _label_issue(f"{label}: missing gold task_type", strict_formal, errors, warnings)
    elif task_type not in task_types:
        errors.append(f"{label}: unknown task_type '{task_type}'")

    accepted_agent_sets = _sets(gold.get("accepted_agent_sets"))
    accepted_tool_sets = _sets(gold.get("accepted_tool_sets"))
    required_tools = _text_set(gold.get("required_tools"))
    forbidden_tools = _text_set(gold.get("forbidden_tools"))

    _validate_agent_sets(
        accepted_agent_sets,
        task_type=task_type,
        label=label,
        strict_formal=strict_formal,
        errors=errors,
        warnings=warnings,
    )
    _validate_tool_sets(
        accepted_tool_sets,
        required_tools,
        forbidden_tools,
        task_type=task_type,
        label=label,
        strict_formal=strict_formal,
        errors=errors,
        warnings=warnings,
    )
    _validate_task_specific_labels(
        gold,
        task_type=task_type,
        label=label,
        strict_formal=strict_formal,
        errors=errors,
        warnings=warnings,
    )
    _validate_city_support(
        city_id,
        task_type=task_type,
        label=label,
        strict_formal=strict_formal,
        errors=errors,
        warnings=warnings,
    )

    return {
        "label": label,
        "case_id": str(unit.get("case_id") or ""),
        "scenario_id": str(unit.get("scenario_id") or ""),
        "turn_id": str(unit.get("turn_id") or ""),
        "task_type": task_type,
        "city_id": city_id,
        "visible_slots": visible_slots,
        "present_labels": present_labels,
        "accepted_agent_sets": accepted_agent_sets,
        "accepted_tool_sets": accepted_tool_sets,
        "required_tools": sorted(required_tools),
        "forbidden_tools": sorted(forbidden_tools),
    }


def _validate_agent_sets(
    accepted_agent_sets: list[list[str]],
    *,
    task_type: str,
    label: str,
    strict_formal: bool,
    errors: list[str],
    warnings: list[str],
) -> None:
    if not accepted_agent_sets:
        _label_issue(f"{label}: accepted_agent_sets is required", strict_formal, errors, warnings)
        return
    allowed = set(CANONICAL_AGENT_ORDER)
    unknown = sorted({agent for group in accepted_agent_sets for agent in group} - allowed)
    if unknown:
        errors.append(f"{label}: unknown agents in accepted_agent_sets: {unknown}")

    if task_type in NO_TOOL_TASK_TYPES:
        non_empty = [group for group in accepted_agent_sets if group]
        if non_empty:
            errors.append(f"{label}: {task_type} must use empty accepted_agent_sets")
        return

    required = TASK_REQUIRED_AGENTS.get(task_type)
    if required and not any(required <= set(group) for group in accepted_agent_sets):
        _label_issue(
            f"{label}: accepted_agent_sets should include required agents {sorted(required)}",
            strict_formal,
            errors,
            warnings,
        )


def _validate_tool_sets(
    accepted_tool_sets: list[list[str]],
    required_tools: set[str],
    forbidden_tools: set[str],
    *,
    task_type: str,
    label: str,
    strict_formal: bool,
    errors: list[str],
    warnings: list[str],
) -> None:
    if not accepted_tool_sets:
        _label_issue(f"{label}: accepted_tool_sets is required", strict_formal, errors, warnings)
    allowed = set(GENERATION_TOOL_NAMES)
    unknown = sorted(
        ({tool for group in accepted_tool_sets for tool in group} | required_tools | forbidden_tools)
        - allowed
    )
    if unknown:
        errors.append(f"{label}: unknown generation tools in labels: {unknown}")

    if task_type in NO_TOOL_TASK_TYPES:
        non_empty = [group for group in accepted_tool_sets if group]
        if non_empty:
            errors.append(f"{label}: {task_type} must use empty accepted_tool_sets")
        missing_forbidden = allowed - forbidden_tools
        if missing_forbidden:
            _label_issue(
                f"{label}: {task_type} should forbid all generation tools {sorted(missing_forbidden)}",
                strict_formal,
                errors,
                warnings,
            )
        return

    if not required_tools and any(accepted_tool_sets):
        warnings.append(f"{label}: required_tools omitted; evaluator will derive it from accepted_tool_sets")
        required_tools = set(accepted_tool_sets[0])
    required_by_task = TASK_REQUIRED_TOOLS.get(task_type)
    if required_by_task and not required_by_task <= required_tools:
        _label_issue(
            f"{label}: required_tools should include {sorted(required_by_task)}",
            strict_formal,
            errors,
            warnings,
        )
    if forbidden_tools & required_tools:
        errors.append(f"{label}: required_tools and forbidden_tools overlap")


def _validate_task_specific_labels(
    gold: Mapping[str, Any],
    *,
    task_type: str,
    label: str,
    strict_formal: bool,
    errors: list[str],
    warnings: list[str],
) -> None:
    if task_type == "clarification":
        if not _text_set(gold.get("missing_slots") or gold.get("clarification_fields")):
            _label_issue(f"{label}: clarification requires missing_slots", strict_formal, errors, warnings)
        return

    if task_type == "partial_replan":
        if "changed_slots" not in gold:
            _label_issue(f"{label}: partial_replan requires changed_slots", strict_formal, errors, warnings)
        elif not _text_set(gold.get("changed_slots")) and not _is_no_change_reuse_partial(gold):
            _label_issue(
                f"{label}: partial_replan with empty changed_slots must be labeled as a no-change reuse request",
                strict_formal,
                errors,
                warnings,
            )
        if not _text_set(gold.get("preserved_slots")):
            warnings.append(f"{label}: partial_replan has no preserved_slots label")
        return

    if task_type == "weather_adjustment":
        if not (
            gold.get("weather_change")
            or gold.get("weather_adjustment_required")
            or "weather_scenario" in _text_set(gold.get("changed_slots"))
        ):
            _label_issue(
                f"{label}: weather_adjustment requires weather_change or weather_adjustment_required",
                strict_formal,
                errors,
                warnings,
            )
        return

    if task_type == "trip_planning":
        if _first_int(gold.get("duration_days"), gold.get("duration"), gold.get("days")) is None:
            _label_issue(f"{label}: trip_planning requires duration_days", strict_formal, errors, warnings)
        if not any(key in gold for key in HARD_CONSTRAINT_KEYS):
            _label_issue(
                f"{label}: trip_planning requires at least one hard-constraint label",
                strict_formal,
                errors,
                warnings,
            )
        return

    if task_type == "attraction_recommendation" and not (
        gold.get("min_attractions") or gold.get("max_attractions")
    ):
        _label_issue(
            f"{label}: attraction_recommendation requires min_attractions or max_attractions",
            strict_formal,
            errors,
            warnings,
        )


def _validate_city_support(
    city_id: str | None,
    *,
    task_type: str,
    label: str,
    strict_formal: bool,
    errors: list[str],
    warnings: list[str],
) -> None:
    if task_type not in TOURISM_TASK_TYPES:
        return
    if city_id is None:
        _label_issue(
            f"{label}: tourism task has no resolvable destination city in visible text or gold slots",
            strict_formal,
            errors,
            warnings,
        )
        return
    if city_id not in FIXED_CITY_IDS:
        errors.append(f"{label}: destination city '{city_id}' is outside fixed offline data")


def _is_no_change_reuse_partial(gold: Mapping[str, Any]) -> bool:
    """Return whether a partial_replan label explicitly means "same request again"."""
    if _text_set(gold.get("changed_slots")):
        return False
    if str(gold.get("replan_policy") or "").strip().lower() != "no_change_reuse":
        return False
    return _sets(gold.get("accepted_agent_sets")) == [[]] and _sets(gold.get("accepted_tool_sets")) == [[]]


def _validate_distribution(
    *,
    task_distribution: Counter[str],
    city_distribution: Counter[str],
    expected_case_count: int | None,
    strict_formal: bool,
    errors: list[str],
    warnings: list[str],
) -> None:
    missing = [
        task_type for task_type in RECOMMENDED_FORMAL_TASK_TYPES if task_distribution.get(task_type, 0) == 0
    ]
    if missing:
        message = f"dataset task coverage is incomplete; missing task types: {missing}"
        if strict_formal and _requires_development_coverage(expected_case_count):
            errors.append(message)
        else:
            warnings.append(message)

    missing_cities = [
        city_id for city_id in FIXED_CITY_IDS if city_distribution.get(city_id, 0) == 0
    ]
    if not missing_cities:
        return
    message = f"dataset fixed-city coverage is incomplete; missing city ids: {missing_cities}"
    if strict_formal and _requires_development_coverage(expected_case_count):
        errors.append(message)
    else:
        warnings.append(message)


def _requires_development_coverage(expected_case_count: int | None) -> bool:
    return (
        expected_case_count is not None
        and expected_case_count >= DEVELOPMENT_COVERAGE_GATE_CASE_COUNT
    )


def _flatten_units(cases: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for case in cases:
        if not _is_scenario_case(case):
            units.append(dict(case))
            continue
        scenario_id = _case_id(case)
        base = {key: value for key, value in case.items() if key != "turns"}
        dialogue_history = _history(case)
        for index, turn in enumerate(case.get("turns") or [], start=1):
            if not isinstance(turn, Mapping):
                continue
            turn_case = {**base, **dict(turn)}
            turn_id = str(turn_case.get("turn_id") or turn_case.get("id") or f"turn_{index:02d}")
            turn_history = [*dialogue_history, *_history(turn)]
            turn_case.update(
                {
                    "case_id": scenario_id,
                    "scenario_id": scenario_id,
                    "turn_id": turn_id,
                    "turn_index": index - 1,
                    "scenario_turn_count": len(case.get("turns") or []),
                    "dialogue_history": turn_history,
                }
            )
            units.append(turn_case)
            dialogue_history = [
                *dialogue_history,
                {
                    "role": "user",
                    "turn_id": turn_id,
                    "content": str(turn.get("user_input") or ""),
                },
            ]
    return units


def _duplicate_visible_inputs(units: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for unit in units:
        text = _normalized_visible_text(unit)
        if text:
            groups[text].append(_unit_label(unit))
    return [
        {"normalized_input": text, "count": len(labels), "example_labels": labels[:5]}
        for text, labels in sorted(groups.items())
        if len(labels) > 1
    ]


def _normalized_visible_text(unit: Mapping[str, Any]) -> str:
    parts = [str(unit.get("user_input") or "")]
    for item in _history(unit):
        if isinstance(item, Mapping):
            parts.append(str(item.get("content") or item.get("text") or ""))
        else:
            parts.append(str(item))
    return re.sub(r"\s+", " ", " ".join(parts)).strip().casefold()


def _gold_payload(unit: Mapping[str, Any]) -> dict[str, Any]:
    gold: dict[str, Any] = {}
    for key in ("gold", "expected"):
        value = unit.get(key)
        if isinstance(value, Mapping):
            gold.update(dict(value))
    ticket = unit.get("expected_ticket")
    if isinstance(ticket, Mapping):
        gold.setdefault("task_type", ticket.get("task_type") or unit.get("task_type"))
        for key in ("missing_slots", "changed_slots", "preserved_slots"):
            if key in ticket:
                gold.setdefault(key, ticket[key])
    decision = unit.get("expected_decision")
    if isinstance(decision, Mapping):
        if "planned_agents" in decision:
            gold.setdefault("accepted_agent_sets", [decision.get("planned_agents") or []])
        if "planned_tools" in decision:
            gold.setdefault("accepted_tool_sets", [decision.get("planned_tools") or []])
            gold.setdefault("required_tools", decision.get("planned_tools") or [])
    if "task_type" in unit:
        gold.setdefault("task_type", unit.get("task_type"))
    if isinstance(gold.get("hard_constraints"), Mapping):
        for key, value in gold["hard_constraints"].items():
            gold.setdefault(str(key), value)
    slots = unit.get("slots") if isinstance(unit.get("slots"), Mapping) else {}
    current_slots = unit.get("current_slots") if isinstance(unit.get("current_slots"), Mapping) else {}
    for target, aliases in {
        "duration_days": ("duration_days", "duration", "days", "trip_days"),
        "budget_limit": ("budget_limit", "budget", "budget_amount", "max_budget"),
        "traveler_group": ("traveler_group", "people", "people_type"),
    }.items():
        if target not in gold:
            gold[target] = next(
                (
                    source[key]
                    for source in (slots, current_slots)
                    for key in aliases
                    if key in source and source[key] is not None
                ),
                None,
            )
    if not gold.get("required_tools") and gold.get("accepted_tool_sets"):
        sets = _sets(gold.get("accepted_tool_sets"))
        if sets:
            gold["required_tools"] = sets[0]
    return {key: value for key, value in gold.items() if value is not None}


def _present_label_fields(unit: Mapping[str, Any], gold: Mapping[str, Any]) -> list[str]:
    fields = []
    for key in ("expected", "gold", "expected_ticket", "expected_decision"):
        if isinstance(unit.get(key), Mapping):
            fields.append(key)
    for key in (
        "task_type",
        "accepted_agent_sets",
        "accepted_tool_sets",
        "required_tools",
        "forbidden_tools",
        "hard_constraints",
        "duration_days",
        "missing_slots",
        "changed_slots",
        "preserved_slots",
    ):
        if key in gold:
            fields.append(key)
    return sorted(set(fields))


def _gold_slots(unit: Mapping[str, Any], gold: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for source in (unit.get("slots"), unit.get("current_slots"), gold):
        if isinstance(source, Mapping):
            merged.update(source)
    return normalize_slots(merged)


def _resolve_city(value: Any) -> str | None:
    if not value:
        return None
    return get_fixed_tourism_data().resolve_city_id(value)


def _sets(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    if not value:
        return []
    if all(not isinstance(item, list) for item in value):
        return [_text_list(value)]
    return [_text_list(item) for item in value if isinstance(item, list)]


def _text_set(value: Any) -> set[str]:
    return set(_text_list(value))


def _text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Mapping):
        return [str(item) for item in value.values() if item]
    if isinstance(value, Iterable):
        return [str(item) for item in value if item is not None and str(item) != ""]
    return [str(value)]


def _first_int(*values: Any) -> int | None:
    for value in values:
        try:
            if value is not None and value != "":
                return int(value)
        except (TypeError, ValueError):
            pass
    return None


def _history(value: Mapping[str, Any]) -> list[Any]:
    for key in ("dialogue_history", "history"):
        history = value.get(key)
        if isinstance(history, list):
            return list(history)
    return []


def _case_id(case: Mapping[str, Any]) -> str:
    return str(case.get("case_id") or case.get("scenario_id") or case.get("id") or "").strip()


def _unit_label(unit: Mapping[str, Any]) -> str:
    case_id = _case_id(unit) or "case"
    turn_id = str(unit.get("turn_id") or "").strip()
    return f"{case_id}/{turn_id}" if turn_id else case_id


def _is_scenario_case(case: Mapping[str, Any]) -> bool:
    return isinstance(case.get("turns"), list) and bool(case.get("turns"))


def _normalized_task_type(value: Any) -> str:
    text = str(value or "").strip()
    return text or "unknown"


def _require_visible_input(unit: Mapping[str, Any], label: str, errors: list[str]) -> None:
    value = unit.get("user_input") or unit.get("query") or unit.get("prompt") or unit.get("message") or unit.get("input")
    if isinstance(value, str) and value.strip():
        return
    if isinstance(value, Mapping) and value:
        return
    errors.append(f"{label}: user_input/query/prompt/message/input is required")


def _label_issue(
    message: str,
    strict_formal: bool,
    errors: list[str],
    warnings: list[str],
) -> None:
    if strict_formal:
        errors.append(message)
    else:
        warnings.append(message)


def _document_value(document: Any, key: str) -> Any:
    return document.get(key) if isinstance(document, Mapping) else None
