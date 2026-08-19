"""Audit CTP-100 formal v2 dataset consistency after Day8 budget fixes.

This script is read-only with respect to the formal dataset.  It writes a small
JSON/Markdown audit report under ``experiments/generated`` so the dataset hash
and the targeted manual corrections are explicit before any formal run.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.benchmark_dataset_validator import build_benchmark_dataset_quality_report
from app.core.budget_gold import (
    BUDGET_GOLD_REVIEW_STATUS,
    BUDGET_GOLD_SCHEMA_VERSION,
    BUDGET_GOLD_STATUS,
    DEFAULT_CTP100_BUDGET_GOLD_PATH,
)
from app.core.budget_manual_review import (
    ECONOMY_BUDGET_CONFIRMED_SCOPE,
    ECONOMY_BUDGET_EXCLUDED_SCOPE,
    ECONOMY_BUDGET_FORMAL_MAIN_TIERS,
)
from app.core.fixed_data import canonical_json_sha256
from app.core.formal_experiment_preflight import load_benchmark_document


DEFAULT_DATASET_PATH = ROOT / "experiments" / "ctp100_formal_v2.json"
DEFAULT_BUDGET_GOLD_PATH = DEFAULT_CTP100_BUDGET_GOLD_PATH
DEFAULT_OUTPUT_JSON = ROOT / "experiments" / "generated" / "ctp100_formal_v2_dataset_audit.json"
DEFAULT_OUTPUT_MD = ROOT / "experiments" / "generated" / "ctp100_formal_v2_dataset_audit.md"


def generate_ctp100_formal_v2_audit(
    *,
    dataset_path: str | Path = DEFAULT_DATASET_PATH,
    budget_gold_path: str | Path = DEFAULT_BUDGET_GOLD_PATH,
    output_json: str | Path = DEFAULT_OUTPUT_JSON,
    output_md: str | Path = DEFAULT_OUTPUT_MD,
) -> Dict[str, Any]:
    dataset_path = Path(dataset_path)
    budget_gold_path = Path(budget_gold_path)
    document, cases = load_benchmark_document(dataset_path)
    quality_report = build_benchmark_dataset_quality_report(
        document=document,
        cases=cases,
        expected_case_count=100,
        strict_formal=True,
    )
    dataset_sha256 = canonical_json_sha256(document)
    targeted_checks = _targeted_checks(cases)
    budget_gold_audit = _budget_gold_audit(
        budget_gold_path,
        expected_source_dataset_sha256=dataset_sha256,
    )
    issue_counter = Counter(
        check["check_id"] for check in targeted_checks if check["status"] != "passed"
    )
    if budget_gold_audit["source_slot_repair_count"]:
        issue_counter["budget_gold_source_slot_repairs"] += budget_gold_audit[
            "source_slot_repair_count"
        ]
    if budget_gold_audit.get("exists") is False:
        issue_counter["budget_gold_missing"] += 1
    if budget_gold_audit.get("source_dataset_sha256_matches") is False:
        issue_counter["budget_gold_source_dataset_sha256_mismatch"] += 1
    if budget_gold_audit.get("schema_version_matches") is False:
        issue_counter["budget_gold_schema_mismatch"] += 1
    if budget_gold_audit.get("gold_status_matches") is False:
        issue_counter["budget_gold_status_mismatch"] += 1
    if budget_gold_audit.get("review_status_matches") is False:
        issue_counter["budget_gold_review_status_mismatch"] += 1
    if budget_gold_audit.get("manual_review_scope_matches") is False:
        issue_counter["budget_gold_manual_review_scope_mismatch"] += 1
    if budget_gold_audit.get("manual_review_formal_tiers_match") is False:
        issue_counter["budget_gold_manual_review_tier_mismatch"] += 1
    if budget_gold_audit.get("manual_review_excludes_comfort_premium") is False:
        issue_counter["budget_gold_comfort_premium_review_mismatch"] += 1
    result = {
        "schema_version": "ctp100-formal-v2-dataset-audit-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_path": _display_path(dataset_path),
        "dataset_id": document.get("dataset_id") if isinstance(document, dict) else None,
        "dataset_version": document.get("dataset_version") if isinstance(document, dict) else None,
        "dataset_sha256": dataset_sha256,
        "case_count": len(cases),
        "turn_count": sum(len(case.get("turns") or [case]) for case in cases),
        "quality_report_status": quality_report.get("status"),
        "quality_report_error_count": len(quality_report.get("errors") or []),
        "quality_report_warning_count": len(quality_report.get("warnings") or []),
        "targeted_checks": targeted_checks,
        "budget_gold_audit": budget_gold_audit,
        "issue_counts": dict(sorted(issue_counter.items())),
    }
    result["status"] = (
        "passed"
        if quality_report.get("status") == "passed" and not result["issue_counts"]
        else "failed"
    )
    _write_json(result, Path(output_json))
    _write_md(result, Path(output_md))
    return result


def _targeted_checks(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id = {case.get("case_id"): case for case in cases}
    checks: List[Dict[str, Any]] = []
    case_016 = by_id.get("ctp100_v2_016") or {}
    expected_016 = case_016.get("expected") if isinstance(case_016.get("expected"), dict) else {}
    slots_016 = case_016.get("slots") if isinstance(case_016.get("slots"), dict) else {}
    hard_016 = (
        expected_016.get("hard_constraints")
        if isinstance(expected_016.get("hard_constraints"), dict)
        else {}
    )
    checks.extend(
        [
            _check("ctp100_v2_016_origin_slot", slots_016.get("origin") == "wuhan", slots_016.get("origin")),
            _check("ctp100_v2_016_origin_expected", expected_016.get("origin") == "wuhan", expected_016.get("origin")),
            _check("ctp100_v2_016_origin_hard_constraint", hard_016.get("origin") == "wuhan", hard_016.get("origin")),
            _check(
                "ctp100_v2_016_intercity_scope",
                expected_016.get("budget_scope") == "local_plus_round_trip_intercity"
                and expected_016.get("intercity_transport_included") is True,
                {
                    "budget_scope": expected_016.get("budget_scope"),
                    "intercity_transport_included": expected_016.get("intercity_transport_included"),
                },
            ),
        ]
    )
    case_057 = by_id.get("ctp100_v2_057") or {}
    turns_057 = {
        turn.get("turn_id"): turn
        for turn in case_057.get("turns", [])
        if isinstance(turn, dict)
    }
    t2 = turns_057.get("t2") or {}
    expected_057 = t2.get("expected") if isinstance(t2.get("expected"), dict) else {}
    hard_057 = (
        expected_057.get("hard_constraints")
        if isinstance(expected_057.get("hard_constraints"), dict)
        else {}
    )
    checks.extend(
        [
            _check("ctp100_v2_057_t2_current_people", _nested(t2, "current_slots", "people_count") == 3, _nested(t2, "current_slots", "people_count")),
            _check("ctp100_v2_057_t2_slots_people", _nested(t2, "slots", "people_count") == 3, _nested(t2, "slots", "people_count")),
            _check("ctp100_v2_057_t2_expected_people", expected_057.get("people_count") == 3, expected_057.get("people_count")),
            _check("ctp100_v2_057_t2_hard_people", hard_057.get("people_count") == 3, hard_057.get("people_count")),
        ]
    )
    weather_audit = _weather_gold_audit(cases)
    checks.extend(
        [
            _check(
                "day8_explicit_date_trip_planning_requires_weather",
                not weather_audit["explicit_date_trip_planning_violations"]
                and weather_audit["explicit_date_trip_planning_count"] == 32,
                {
                    "count": weather_audit["explicit_date_trip_planning_count"],
                    "violations": weather_audit["explicit_date_trip_planning_violations"],
                },
            ),
            _check(
                "day8_no_date_trip_planning_requires_weather_reminder",
                not weather_audit["no_date_trip_planning_violations"]
                and weather_audit["no_date_trip_planning_count"] == 18,
                {
                    "count": weather_audit["no_date_trip_planning_count"],
                    "violations": weather_audit["no_date_trip_planning_violations"],
                },
            ),
            _check(
                "day8_weather_query_count_and_ctp100_v2_039_fix",
                weather_audit["weather_query_count"] == 8
                and weather_audit["ctp100_v2_039_task_type"] == "weather_query",
                {
                    "weather_query_count": weather_audit["weather_query_count"],
                    "ctp100_v2_039_task_type": weather_audit["ctp100_v2_039_task_type"],
                    "violations": weather_audit["weather_query_violations"],
                },
            ),
            _check(
                "day8_weather_sensitive_partial_replan_requires_weather",
                not weather_audit["weather_sensitive_partial_violations"]
                and weather_audit["weather_sensitive_partial_count"] == 8,
                {
                    "count": weather_audit["weather_sensitive_partial_count"],
                    "violations": weather_audit["weather_sensitive_partial_violations"],
                },
            ),
            _check(
                "day8_weather_adjustment_reuses_first_turn_weather",
                not weather_audit["weather_adjustment_reuse_violations"]
                and weather_audit["weather_adjustment_reuse_count"] == 5,
                {
                    "count": weather_audit["weather_adjustment_reuse_count"],
                    "violations": weather_audit["weather_adjustment_reuse_violations"],
                },
            ),
        ]
    )
    return checks


def _weather_gold_audit(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    explicit_date_trip_count = 0
    no_date_trip_count = 0
    weather_query_count = 0
    weather_sensitive_partial_count = 0
    weather_adjustment_reuse_count = 0
    explicit_date_trip_violations: List[str] = []
    no_date_trip_violations: List[str] = []
    weather_query_violations: List[str] = []
    weather_sensitive_partial_violations: List[str] = []
    weather_adjustment_reuse_violations: List[str] = []
    ctp100_v2_039_task_type = None

    for case in cases:
        for unit in _flatten_case_units(case):
            label = _unit_label(unit)
            expected = unit.get("expected") if isinstance(unit.get("expected"), dict) else {}
            task_type = str(expected.get("task_type") or unit.get("task_type") or "")
            required_tools = set(_list(expected.get("required_tools")))
            forbidden_tools = set(_list(expected.get("forbidden_tools")))
            accepted_agent_sets = [
                set(group) for group in expected.get("accepted_agent_sets") or [] if isinstance(group, list)
            ]
            accepted_tool_sets = [
                set(group) for group in expected.get("accepted_tool_sets") or [] if isinstance(group, list)
            ]
            has_weather_agent = any("weather" in group for group in accepted_agent_sets)
            has_weather_tool = any("weather_query" in group for group in accepted_tool_sets)
            has_start_date = bool(_slot(unit, expected, "start_date"))

            if label == "ctp100_v2_039":
                ctp100_v2_039_task_type = task_type

            if task_type == "trip_planning":
                if has_start_date:
                    explicit_date_trip_count += 1
                    if (
                        "weather_query" not in required_tools
                        or "weather_query" in forbidden_tools
                        or not has_weather_agent
                        or not has_weather_tool
                        or expected.get("weather_required") is not True
                        or expected.get("weather_date_policy") != "explicit_date_use_qweather_snapshot"
                    ):
                        explicit_date_trip_violations.append(label)
                else:
                    no_date_trip_count += 1
                    if (
                        "weather_query" in required_tools
                        or "weather_query" not in forbidden_tools
                        or expected.get("weather_required") is not False
                        or expected.get("weather_date_policy") != "no_date_no_specific_weather_for_trip_plan"
                        or expected.get("no_date_weather_reminder_required") is not True
                    ):
                        no_date_trip_violations.append(label)
            elif task_type == "weather_query":
                weather_query_count += 1
                if (
                    required_tools != {"weather_query"}
                    or forbidden_tools != {"poi_search", "budget_calculator"}
                    or not has_weather_agent
                    or not has_weather_tool
                    or expected.get("weather_required") is not True
                ):
                    weather_query_violations.append(label)
            elif task_type == "partial_replan":
                changed_slots = set(_list(expected.get("changed_slots")))
                if has_start_date and changed_slots & {"start_date", "duration_days"}:
                    weather_sensitive_partial_count += 1
                    if (
                        "weather_query" not in required_tools
                        or "weather_query" in forbidden_tools
                        or not has_weather_agent
                        or not has_weather_tool
                    ):
                        weather_sensitive_partial_violations.append(label)
            elif task_type == "weather_adjustment" and expected.get("weather_reuse_expected"):
                weather_adjustment_reuse_count += 1
                if (
                    required_tools != {"budget_calculator"}
                    or "weather_query" not in forbidden_tools
                    or "poi_search" not in forbidden_tools
                    or has_weather_tool
                    or "budget_calculator" not in set().union(*accepted_tool_sets)
                    or {"itinerary", "budget"} not in accepted_agent_sets
                    or expected.get("weather_query_must_not_rerun") is not True
                ):
                    weather_adjustment_reuse_violations.append(label)

    return {
        "explicit_date_trip_planning_count": explicit_date_trip_count,
        "explicit_date_trip_planning_violations": explicit_date_trip_violations,
        "no_date_trip_planning_count": no_date_trip_count,
        "no_date_trip_planning_violations": no_date_trip_violations,
        "weather_query_count": weather_query_count,
        "weather_query_violations": weather_query_violations,
        "ctp100_v2_039_task_type": ctp100_v2_039_task_type,
        "weather_sensitive_partial_count": weather_sensitive_partial_count,
        "weather_sensitive_partial_violations": weather_sensitive_partial_violations,
        "weather_adjustment_reuse_count": weather_adjustment_reuse_count,
        "weather_adjustment_reuse_violations": weather_adjustment_reuse_violations,
    }


def _flatten_case_units(case: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(case.get("turns"), list):
        return [case]
    units: List[Dict[str, Any]] = []
    base = {key: value for key, value in case.items() if key != "turns"}
    for turn in case.get("turns") or []:
        if not isinstance(turn, dict):
            continue
        merged = dict(base)
        merged.update(turn)
        merged.setdefault("case_id", case.get("case_id"))
        merged.setdefault("scenario_id", case.get("scenario_id") or case.get("case_id"))
        units.append(merged)
    return units


def _unit_label(unit: Dict[str, Any]) -> str:
    case_id = str(unit.get("case_id") or "")
    turn_id = str(unit.get("turn_id") or "")
    return f"{case_id}::{turn_id}" if turn_id else case_id


def _slot(unit: Dict[str, Any], expected: Dict[str, Any], key: str) -> Any:
    slots = unit.get("slots") if isinstance(unit.get("slots"), dict) else {}
    current_slots = unit.get("current_slots") if isinstance(unit.get("current_slots"), dict) else {}
    hard_constraints = (
        expected.get("hard_constraints")
        if isinstance(expected.get("hard_constraints"), dict)
        else {}
    )
    for source in (slots, current_slots, expected, hard_constraints):
        if isinstance(source, dict) and source.get(key) is not None:
            return source.get(key)
    return None


def _list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _budget_gold_audit(
    path: Path,
    *,
    expected_source_dataset_sha256: str,
) -> Dict[str, Any]:
    if not path.exists():
        return {
            "path": _display_path(path),
            "exists": False,
            "expected_source_dataset_sha256": expected_source_dataset_sha256,
            "source_dataset_sha256": None,
            "source_dataset_sha256_matches": False,
            "source_slot_repair_count": None,
            "source_slot_repair_units": [],
        }
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    repaired_units = [
        record.get("unit_id")
        for record in document.get("records", [])
        if record.get("source_slot_repairs")
    ]
    manual_review = document.get("manual_review") if isinstance(document.get("manual_review"), dict) else {}
    confirmed_scope = manual_review.get("confirmed_scope") if isinstance(manual_review.get("confirmed_scope"), list) else []
    formal_tiers = (
        manual_review.get("formal_main_experiment_tiers")
        if isinstance(manual_review.get("formal_main_experiment_tiers"), list)
        else []
    )
    excluded_scope = manual_review.get("excluded_scope") if isinstance(manual_review.get("excluded_scope"), list) else []
    return {
        "path": _display_path(path),
        "exists": True,
        "schema_version": document.get("schema_version"),
        "schema_version_matches": document.get("schema_version") == BUDGET_GOLD_SCHEMA_VERSION,
        "gold_status": document.get("gold_status"),
        "gold_status_matches": document.get("gold_status") == BUDGET_GOLD_STATUS,
        "review_status": document.get("review_status"),
        "review_status_matches": document.get("review_status") == BUDGET_GOLD_REVIEW_STATUS,
        "manual_review_status": manual_review.get("status"),
        "manual_review_scope": confirmed_scope,
        "manual_review_scope_matches": confirmed_scope == list(ECONOMY_BUDGET_CONFIRMED_SCOPE),
        "manual_review_formal_tiers": formal_tiers,
        "manual_review_formal_tiers_match": formal_tiers == list(ECONOMY_BUDGET_FORMAL_MAIN_TIERS),
        "manual_review_excluded_scope": excluded_scope,
        "manual_review_excludes_comfort_premium": set(ECONOMY_BUDGET_EXCLUDED_SCOPE) <= set(excluded_scope)
        and not (set(confirmed_scope) & set(ECONOMY_BUDGET_EXCLUDED_SCOPE)),
        "expected_source_dataset_sha256": expected_source_dataset_sha256,
        "source_dataset_sha256": document.get("source_dataset_sha256"),
        "source_dataset_sha256_matches": document.get("source_dataset_sha256")
        == expected_source_dataset_sha256,
        "source_slot_repair_count": len(repaired_units),
        "source_slot_repair_units": repaired_units,
    }


def _check(check_id: str, passed: bool, actual: Any) -> Dict[str, Any]:
    return {
        "check_id": check_id,
        "status": "passed" if passed else "failed",
        "actual": actual,
    }


def _nested(value: Dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _write_json(value: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_md(value: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# CTP-100 Formal v2 Dataset Audit",
        "",
        "> 本文件审计正式题库、正式预算金标与经济型人工审核账本的一致性，不运行正式100题。",
        "",
        f"- status: `{value.get('status')}`",
        f"- dataset_version: `{value.get('dataset_version')}`",
        f"- dataset_sha256: `{value.get('dataset_sha256')}`",
        f"- case_count: `{value.get('case_count')}`",
        f"- turn_count: `{value.get('turn_count')}`",
        f"- quality_report_status: `{value.get('quality_report_status')}`",
        "",
        "## Targeted checks",
        "",
        "| check_id | status | actual |",
        "| --- | --- | --- |",
    ]
    for check in value.get("targeted_checks") or []:
        lines.append(
            f"| {check.get('check_id')} | {check.get('status')} | "
            f"{json.dumps(check.get('actual'), ensure_ascii=False)} |"
        )
    lines.extend(
        [
            "",
            "## Budget gold audit",
            "",
            f"- path: `{value.get('budget_gold_audit', {}).get('path')}`",
            f"- source_dataset_sha256: `{value.get('budget_gold_audit', {}).get('source_dataset_sha256')}`",
            f"- expected_source_dataset_sha256: `{value.get('budget_gold_audit', {}).get('expected_source_dataset_sha256')}`",
            f"- source_dataset_sha256_matches: `{value.get('budget_gold_audit', {}).get('source_dataset_sha256_matches')}`",
            f"- manual_review_scope: `{value.get('budget_gold_audit', {}).get('manual_review_scope')}`",
            f"- manual_review_scope_matches: `{value.get('budget_gold_audit', {}).get('manual_review_scope_matches')}`",
            f"- manual_review_formal_tiers: `{value.get('budget_gold_audit', {}).get('manual_review_formal_tiers')}`",
            f"- manual_review_excluded_scope: `{value.get('budget_gold_audit', {}).get('manual_review_excluded_scope')}`",
            f"- manual_review_excludes_comfort_premium: `{value.get('budget_gold_audit', {}).get('manual_review_excludes_comfort_premium')}`",
            f"- source_slot_repair_count: `{value.get('budget_gold_audit', {}).get('source_slot_repair_count')}`",
            f"- source_slot_repair_units: `{value.get('budget_gold_audit', {}).get('source_slot_repair_units')}`",
            "",
            "## Issue counts",
            "",
            "```json",
            json.dumps(value.get("issue_counts") or {}, ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_PATH))
    parser.add_argument("--budget-gold", default=str(DEFAULT_BUDGET_GOLD_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()
    result = generate_ctp100_formal_v2_audit(
        dataset_path=args.dataset,
        budget_gold_path=args.budget_gold,
        output_json=args.output_json,
        output_md=args.output_md,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "dataset_sha256": result["dataset_sha256"],
                "issue_counts": result["issue_counts"],
                "output_json": args.output_json,
                "output_md": args.output_md,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
