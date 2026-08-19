"""Generate human-review materials for CTP-100 Budget Policy v2 gold.

The script reads the formal dataset and formal budget gold JSON, then writes
Markdown/CSV review files. It does not run the formal experiment and does not
mutate the formal dataset.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.generate_ctp100_budget_gold_v2 import (  # noqa: E402
    _expected,
    _explicit_total_people_from_text,
    _iter_units,
    _slots_for_budget,
)
from app.core.budget_gold import DEFAULT_CTP100_BUDGET_GOLD_PATH  # noqa: E402
from app.core.intercity_transport_snapshot import normalize_intercity_city_id  # noqa: E402

DEFAULT_DATASET_PATH = ROOT / "experiments" / "ctp100_formal_v2.json"
DEFAULT_GOLD_PATH = DEFAULT_CTP100_BUDGET_GOLD_PATH
DEFAULT_OUTPUT_MD = ROOT / "experiments" / "generated" / "ctp100_budget_gold_v2_review.md"
DEFAULT_OUTPUT_CSV = ROOT / "experiments" / "generated" / "ctp100_budget_gold_v2_review.csv"

LOCAL_COST_FIELDS = [
    "ticket_cost",
    "accommodation_cost",
    "food_cost",
    "local_transport_cost",
    "other_local_cost",
]
FOCUS_UNITS = [
    "ctp100_v2_001",
    "ctp100_v2_002",
    "ctp100_v2_005",
    "ctp100_v2_046",
    "ctp100_v2_048",
    "ctp100_v2_055::t1",
    "ctp100_v2_055::t2",
    "ctp100_v2_056::t1",
    "ctp100_v2_056::t2",
    "ctp100_v2_067::t1",
    "ctp100_v2_067::t2",
]
ALLOWED_UPGRADE_DECISIONS = {
    "economic_baseline",
    "economic_baseline_over_budget",
    "explicit_preference_applied",
    "explicit_preference_applied_over_budget",
}
CHANGED_SLOT_CHECK_FIELDS = {
    "origin",
    "destination",
    "duration_days",
    "people_count",
    "budget_amount",
    "budget_limit",
    "hotel_level",
    "food_level",
    "transport_mode",
}
SCOPE_CN = {
    "destination_local_only": "仅目的地当地费用",
    "local_plus_round_trip_intercity": "目的地当地费用 + 往返城际高铁/动车二等座",
    "local_only_route_uncovered": "仅目的地当地费用（城际路线未覆盖）",
}
UPGRADE_CN = {
    "economic_baseline": "用户未明确提出住宿或餐饮档次，按经济型基准计算；预算金额不触发升级。",
    "economic_baseline_over_budget": "用户未明确提出住宿或餐饮档次，仍按经济型基准计算；若超预算则如实报告缺口。",
    "explicit_preference_applied": "用户明确提出住宿或餐饮档次，按该偏好计算。",
    "explicit_preference_applied_over_budget": "用户明确提出住宿或餐饮档次，按该偏好计算；若超预算则如实报告缺口，不自动降档。",
}
TOL = 0.05


def generate_budget_review(
    *,
    dataset_path: str | Path = DEFAULT_DATASET_PATH,
    gold_path: str | Path = DEFAULT_GOLD_PATH,
    output_md: str | Path = DEFAULT_OUTPUT_MD,
    output_csv: str | Path = DEFAULT_OUTPUT_CSV,
) -> Dict[str, Any]:
    dataset_path = Path(dataset_path)
    gold_path = Path(gold_path)
    dataset = _read_json(dataset_path)
    draft = _read_json(gold_path)
    units = {unit["unit_id"]: unit for unit in _iter_units(dataset.get("cases") or [])}
    rows = _build_rows(draft, units)
    _write_csv(rows, Path(output_csv))
    _write_md(rows, Path(output_md), dataset_path, gold_path)
    issue_counter: Counter[str] = Counter()
    for row in rows:
        issue_counter.update(row["issue_flags"])
    return {
        "output_md": str(output_md),
        "output_csv": str(output_csv),
        "budget_review_rows": len(rows),
        "issue_units": sum(1 for row in rows if row["issue_flags"]),
        "issue_counts": dict(sorted(issue_counter.items())),
    }


def _build_rows(draft: Dict[str, Any], units: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    previous_by_case: Dict[str, Dict[str, Any]] = {}
    for record in draft.get("records") or []:
        if record.get("status") != "generated":
            continue
        unit = units.get(str(record.get("unit_id") or ""))
        if not unit:
            continue
        row = _row_from_record(record, unit, previous_by_case.get(str(record.get("case_id"))))
        rows.append(row)
        previous_by_case[str(row["case_id"])] = row
    return rows


def _row_from_record(
    record: Dict[str, Any],
    unit: Dict[str, Any],
    previous_row: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    gold = _expected(unit)
    slots = record.get("input_slots") if isinstance(record.get("input_slots"), dict) else {}
    bp = record.get("budget_policy_v2") if isinstance(record.get("budget_policy_v2"), dict) else {}
    costs = bp.get("cost_breakdown") if isinstance(bp.get("cost_breakdown"), dict) else {}
    expected_slots = _slots_for_budget(unit, gold)
    changed_slots_expected = _as_list(gold.get("changed_slots"))
    preserved_slots_expected = _as_list(gold.get("preserved_slots"))
    current_projection = {
        "origin": slots.get("origin"),
        "destination": slots.get("destination"),
        "duration_days": bp.get("duration_days"),
        "people_count": bp.get("people_count"),
        "budget_amount": bp.get("budget_limit"),
        "hotel_tier": bp.get("hotel_tier"),
        "food_tier": bp.get("food_tier"),
    }
    row = {
        "unit_id": record.get("unit_id"),
        "case_id": record.get("case_id"),
        "turn_id": record.get("turn_id"),
        "task_type": record.get("task_type"),
        "user_input": _unit_user_input(unit),
        "origin": slots.get("origin"),
        "destination": slots.get("destination"),
        "duration_days": bp.get("duration_days"),
        "nights": bp.get("nights"),
        "people_count": bp.get("people_count"),
        "rooms": bp.get("rooms"),
        "budget_amount": bp.get("budget_limit"),
        "budget_scope": bp.get("budget_scope"),
        "requested_budget_scope": bp.get("requested_budget_scope"),
        "computed_budget_scope": bp.get("computed_budget_scope"),
        "scope_complete": bp.get("scope_complete"),
        "sufficiency_status": bp.get("sufficiency_status"),
        "hotel_tier": bp.get("hotel_tier"),
        "food_tier": bp.get("food_tier"),
        "ticket_cost": costs.get("ticket_cost"),
        "accommodation_cost": costs.get("accommodation_cost"),
        "food_cost": costs.get("food_cost"),
        "local_transport_cost": costs.get("local_transport_cost"),
        "other_local_cost": costs.get("other_local_cost"),
        "destination_local_basic_cost": bp.get("destination_local_basic_cost"),
        "contingency_amount": bp.get("contingency_amount"),
        "intercity_transport_cost": bp.get("intercity_transport_cost"),
        "intercity_one_way_fare_per_person_cny": bp.get("intercity_one_way_fare_per_person_cny"),
        "intercity_round_trip_cost_cny": bp.get("intercity_round_trip_cost_cny"),
        "final_recommended_total": bp.get("final_recommended_total"),
        "remaining_budget": bp.get("remaining_budget"),
        "covered_scope_remaining_budget": bp.get("covered_scope_remaining_budget"),
        "budget_gap": bp.get("budget_gap"),
        "is_over_budget": bp.get("is_over_budget"),
        "can_judge_budget_sufficiency": bp.get("can_judge_budget_sufficiency"),
        "mandatory_budget_disclaimer": bp.get("mandatory_budget_disclaimer"),
        "budget_disclaimer": bp.get("budget_disclaimer"),
        "upgrade_decision": bp.get("upgrade_decision"),
        "upgrade_applied": bp.get("upgrade_applied") or [],
        "standard_reference_poi_ids": bp.get("standard_reference_poi_ids") or [],
        "source_slot_repairs": record.get("source_slot_repairs") or [],
        "expected_changed_slots": changed_slots_expected,
        "expected_preserved_slots": preserved_slots_expected,
        "actual_changed_slots": _actual_changed_slots(current_projection, previous_row),
    }
    issues, summaries = _issue_checks(
        row=row,
        unit=unit,
        gold=gold,
        expected_slots=expected_slots,
        previous_row=previous_row,
    )
    row["issue_flags"] = issues
    row["issue_summary"] = "；".join(summaries)
    return row


def _issue_checks(
    *,
    row: Dict[str, Any],
    unit: Dict[str, Any],
    gold: Dict[str, Any],
    expected_slots: Dict[str, Any],
    previous_row: Optional[Dict[str, Any]],
) -> tuple[List[str], List[str]]:
    issues: List[str] = []
    summaries: List[str] = []

    for key in ("origin", "destination", "duration_days", "people_count", "budget_amount"):
        actual = row.get(key)
        expected = expected_slots.get(key)
        if key in {"duration_days", "people_count", "budget_amount"}:
            mismatch = not _close(actual, expected)
        else:
            mismatch = actual != expected
        if mismatch:
            issues.append("slot_mismatch")
            summaries.append(f"输入槽位与正式题库预算槽位不一致：{key}={actual}，应为={expected}")

    if row["source_slot_repairs"]:
        issues.append("source_slot_repaired")
        summaries.append(f"正式题库源槽位存在可修正不一致：{_compact(row['source_slot_repairs'])}")

    explicit_people = _explicit_total_people_from_text(row["user_input"])
    if explicit_people is not None and int(row["people_count"] or 0) != explicit_people:
        issues.append("explicit_people_mismatch")
        summaries.append(f"user_input显式人数为{explicit_people}，预算金标为{row['people_count']}")

    explicit_origin = _explicit_complex_origin_from_text(row["user_input"])
    if explicit_origin and row.get("origin") != explicit_origin:
        issues.append("complex_origin_mismatch")
        summaries.append(
            f"复杂出发地表达识别不一致：文本出发地={explicit_origin}，预算金标origin={row.get('origin')}"
        )

    if _has_local_only_scope_text(row["user_input"]) and row.get("requested_budget_scope") != "destination_local_only":
        issues.append("local_only_scope_mismatch")
        summaries.append("用户明确只问当地费用，但requested_budget_scope不是destination_local_only")

    for key in ("requested_budget_scope", "computed_budget_scope", "scope_complete", "sufficiency_status"):
        expected = gold.get(key)
        if expected is not None and row.get(key) != expected:
            issues.append("scope_field_mismatch")
            summaries.append(f"预算范围字段与正式题库不一致：{key}={row.get(key)}，应为{expected}")

    local_sum = sum(_float(row.get(field)) for field in LOCAL_COST_FIELDS)
    if not _close(row["destination_local_basic_cost"], local_sum):
        issues.append("formula_error")
        summaries.append("当地基础费用不等于门票+住宿+餐饮+市内交通+其他当地费用")
    if not _close(row["contingency_amount"], _float(row["destination_local_basic_cost"]) * 0.10):
        issues.append("formula_error")
        summaries.append("机动费用不是当地基础费用的10%")
    expected_final = (
        _float(row["destination_local_basic_cost"])
        + _float(row["contingency_amount"])
        + _float(row["intercity_transport_cost"])
    )
    if not _close(row["final_recommended_total"], expected_final):
        issues.append("formula_error")
        summaries.append("最终推荐金额不等于当地基础费用+机动费用+城际交通")
    expected_nights = max(int(row["duration_days"] or 0) - 1, 0)
    expected_rooms = math.ceil(int(row["people_count"] or 0) / 2) if row["people_count"] else None
    if row["nights"] != expected_nights:
        issues.append("formula_error")
        summaries.append(f"住宿晚数错误：{row['nights']}，应为{expected_nights}")
    if expected_rooms is not None and row["rooms"] != expected_rooms:
        issues.append("formula_error")
        summaries.append(f"房间数错误：{row['rooms']}，应为{expected_rooms}")

    if row["mandatory_budget_disclaimer"] and not row["budget_disclaimer"]:
        issues.append("missing_disclaimer")
        summaries.append("需要免责声明但预算免责声明为空")
    expected_sufficiency = _expected_sufficiency_status(row)
    if row.get("sufficiency_status") != expected_sufficiency:
        issues.append("sufficiency_status_mismatch")
        summaries.append(
            f"三态预算结论错误：sufficiency_status={row.get('sufficiency_status')}，应为{expected_sufficiency}"
        )
    expected_can_judge = expected_sufficiency != "indeterminate"
    if bool(row["can_judge_budget_sufficiency"]) != expected_can_judge:
        issues.append("budget_sufficiency_contradiction")
        summaries.append("can_judge_budget_sufficiency与三态预算结论矛盾")
    expected_over_budget = expected_sufficiency == "insufficient"
    if bool(row["is_over_budget"]) != expected_over_budget:
        issues.append("budget_sufficiency_contradiction")
        summaries.append("is_over_budget与sufficiency_status矛盾")
    if row.get("scope_complete") is False and expected_sufficiency == "indeterminate":
        if row.get("remaining_budget") is not None:
            issues.append("incomplete_scope_remaining_budget_error")
            summaries.append("scope_complete=false且结论不确定时，remaining_budget不得表示完整旅行剩余预算")
        if row.get("covered_scope_remaining_budget") is None:
            issues.append("incomplete_scope_remaining_budget_error")
            summaries.append("scope_complete=false时必须提供covered_scope_remaining_budget表示已覆盖范围剩余")

    per_person_day = (
        _float(row["food_cost"]) / max(int(row["people_count"] or 1), 1) / max(int(row["duration_days"] or 1), 1)
    )
    if per_person_day <= 0:
        issues.append("food_per_person_day_error")
        summaries.append("本行程人均日均餐饮费必须大于0")
    row["food_cost_per_person_day"] = round(per_person_day, 2)

    explicit_hotel = bool(expected_slots.get("hotel_level"))
    explicit_food = bool(expected_slots.get("food_level"))
    if row["upgrade_decision"] not in ALLOWED_UPGRADE_DECISIONS:
        issues.append("upgrade_policy_unclear")
        summaries.append(f"自动升级或未知升级规则不允许：{row['upgrade_decision']}")
    if row["upgrade_applied"] and not (explicit_hotel or explicit_food):
        issues.append("auto_upgrade_forbidden")
        summaries.append("用户未明确消费档次时不得出现upgrade_applied")
    if not explicit_hotel and row["hotel_tier"] in {"comfort", "premium"}:
        issues.append("non_explicit_tier")
        summaries.append("用户未明确住宿档次时不得出现comfort或premium住宿")
    if not explicit_food and row["food_tier"] in {"comfort", "premium"}:
        issues.append("non_explicit_tier")
        summaries.append("用户未明确餐饮档次时不得出现comfort或premium餐饮")

    if previous_row:
        expected_changed = {
            "budget_amount" if str(value) == "budget_limit" else str(value)
            for value in row["expected_changed_slots"]
            if str(value) in CHANGED_SLOT_CHECK_FIELDS
        }
        actual_changed = set(row["actual_changed_slots"])
        if expected_changed and actual_changed != expected_changed:
            issues.append("changed_slots_mismatch")
            summaries.append(f"changed_slots与实际变化不一致：期望={sorted(expected_changed)}，实际={sorted(actual_changed)}")
        for slot in row["expected_preserved_slots"]:
            if _slot_value(row, slot) != _slot_value(previous_row, slot):
                issues.append("preserved_slots_mismatch")
                summaries.append(f"preserved_slots未保持：{slot}")
        if expected_changed == {"budget_amount"}:
            _check_costs_unchanged(
                row=row,
                previous_row=previous_row,
                issues=issues,
                summaries=summaries,
                reason="只改budget时原方案费用不得变化",
                fields=LOCAL_COST_FIELDS + ["destination_local_basic_cost", "contingency_amount", "intercity_transport_cost", "final_recommended_total"],
            )
        if expected_changed == {"origin"}:
            _check_costs_unchanged(
                row=row,
                previous_row=previous_row,
                issues=issues,
                summaries=summaries,
                reason="只补origin时当地费用不得变化",
                fields=LOCAL_COST_FIELDS + ["destination_local_basic_cost", "contingency_amount"],
            )
        if expected_changed & {"people_count", "duration_days"}:
            if row["hotel_tier"] != previous_row["hotel_tier"] or row["food_tier"] != previous_row["food_tier"]:
                issues.append("preserved_tier_mismatch")
                summaries.append("只改人数或天数时应保留上一轮住宿/餐饮档次")

    return sorted(set(issues)), list(dict.fromkeys(summaries))


def _check_costs_unchanged(
    *,
    row: Dict[str, Any],
    previous_row: Dict[str, Any],
    issues: List[str],
    summaries: List[str],
    reason: str,
    fields: List[str],
) -> None:
    changed = [field for field in fields if not _close(row.get(field), previous_row.get(field))]
    if changed:
        issues.append("preserved_cost_mismatch")
        summaries.append(f"{reason}，但这些费用变化了：{changed}")


def _expected_sufficiency_status(row: Dict[str, Any]) -> str:
    if row.get("budget_amount") is None:
        return "indeterminate"
    if _float(row["final_recommended_total"]) > _float(row["budget_amount"]) + TOL:
        return "insufficient"
    return "sufficient" if row.get("scope_complete") is True else "indeterminate"


def _has_local_only_scope_text(text: Any) -> bool:
    compact = str(text or "").replace(" ", "")
    return any(
        marker in compact
        for marker in (
            "当地吃住行",
            "当地旅行费用",
            "当地费用",
            "只想知道当地",
            "只算当地",
            "只看当地",
            "不含大交通",
            "不算大交通",
            "不包含城际",
        )
    )


def _explicit_complex_origin_from_text(text: Any) -> Optional[str]:
    compact = str(text or "").replace(" ", "")
    match = re.search(r"从(?P<origin>[\u4e00-\u9fff]{2,4})(?:出发)?(?:带|和|跟)", compact)
    if not match:
        return None
    return normalize_intercity_city_id(match.group("origin"))


def _actual_changed_slots(row: Dict[str, Any], previous_row: Optional[Dict[str, Any]]) -> List[str]:
    if not previous_row:
        return []
    fields = ["origin", "destination", "duration_days", "people_count", "budget_amount"]
    changed = []
    for field in fields:
        if field in {"duration_days", "people_count", "budget_amount"}:
            if not _close(row.get(field), previous_row.get(field)):
                changed.append(field)
        elif row.get(field) != previous_row.get(field):
            changed.append(field)
    return changed


def _slot_value(row: Dict[str, Any], slot: Any) -> Any:
    slot = str(slot)
    if slot == "budget_limit":
        slot = "budget_amount"
    return row.get(slot)


def _write_csv(rows: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "unit_id",
        "case_id",
        "turn_id",
        "task_type",
        "user_input",
        "origin",
        "destination",
        "duration_days",
        "nights",
        "people_count",
        "rooms",
        "budget_amount",
        "budget_scope",
        "requested_budget_scope",
        "computed_budget_scope",
        "scope_complete",
        "sufficiency_status",
        "hotel_tier",
        "food_tier",
        "ticket_cost",
        "accommodation_cost",
        "food_cost",
        "food_cost_per_person_day",
        "local_transport_cost",
        "other_local_cost",
        "destination_local_basic_cost",
        "contingency_amount",
        "intercity_one_way_fare_per_person_cny",
        "intercity_round_trip_cost_cny",
        "final_recommended_total",
        "remaining_budget",
        "covered_scope_remaining_budget",
        "budget_gap",
        "is_over_budget",
        "can_judge_budget_sufficiency",
        "mandatory_budget_disclaimer",
        "budget_disclaimer",
        "upgrade_decision",
        "upgrade_applied",
        "standard_reference_poi_ids",
        "expected_changed_slots",
        "actual_changed_slots",
        "expected_preserved_slots",
        "source_slot_repairs",
        "issue_flags",
        "issue_summary",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _compact(row.get(key)) for key in fieldnames})


def _write_md(rows: List[Dict[str, Any]], path: Path, dataset_path: Path, gold_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    issue_counter: Counter[str] = Counter()
    for row in rows:
        issue_counter.update(row["issue_flags"])
    issue_rows = [row for row in rows if row["issue_flags"]]
    rows_by_id = {row["unit_id"]: row for row in rows}
    focus_sections = []
    for unit_id in FOCUS_UNITS:
        row = rows_by_id.get(unit_id)
        if not row:
            focus_sections.append(f"#### {unit_id}\n\n- 未找到该预算评价单元。\n")
            continue
        previous = _previous_focus_row(rows, row)
        focus_sections.append(_focus_explanation(row, previous))
    md = "\n".join(
        [
            "# CTP-100 Budget Gold v2 经济型人工审阅材料",
            "",
            "> 本文件用于复核正式预算金标中的 economy 范围。正式确认范围为 `economy`、`intercity_transport`、`budget_policy_v2`；`comfort` / `premium` 不属于本次正式主实验预算金标确认范围。",
            "",
            "## 数据来源",
            "",
            f"- 正式题库：`{_display_path(dataset_path)}`",
            f"- 预算金标文件：`{_display_path(gold_path)}`",
            "- 经济型人工审核账本：`experiments/generated/economy_budget_manual_review_v1.json`",
            "- 成本明细来自预算金标中的 `budget_policy_v2.cost_breakdown`，该字段由固定预算计算器生成。",
            "- 新规则：预算金额只影响预算是否充足，不触发住宿或餐饮自动升级/降级。",
            "- 正式主实验只评价 economy 预算基线；comfort/premium 可作为开发检查或可选升级说明，不作为本次主实验金标。",
            "",
            "## 总览",
            "",
            _markdown_table(
                ["项目", "数量"],
                [
                    ["预算适用评价单元", len(rows)],
                    ["自动检查异常单元", len(issue_rows)],
                    ["无异常单元", len(rows) - len(issue_rows)],
                ],
            ),
            "",
            "## 自动异常报告",
            "",
            _markdown_table(
                ["异常类型", "数量"],
                [[key, value] for key, value in sorted(issue_counter.items())] or [["无", 0]],
            ),
            "",
            "### 异常明细",
            "",
            _markdown_table(
                ["unit_id", "issue_flags", "issue_summary"],
                [[row["unit_id"], row["issue_flags"], row["issue_summary"]] for row in issue_rows] or [["无", "", ""]],
            ),
            "",
            "## 重点案例逐条解释",
            "",
            "".join(focus_sections),
            "## 全量预算适用评价单元审阅表",
            "",
            "> 表中“本行程人均日均餐饮费” = 餐饮总额 ÷ people_count ÷ duration_days，只表示当前行程平均到每天的费用，不等同于固定的完整三餐日参考费用。",
            "",
            _markdown_table(
                [
                    "unit_id",
                    "task_type",
                    "user_input",
                    "origin",
                    "destination",
                    "duration_days",
                    "nights",
                    "people_count",
                    "rooms",
                    "budget_amount",
                    "budget_scope",
                    "requested_budget_scope",
                    "computed_budget_scope",
                    "scope_complete",
                    "sufficiency_status",
                    "hotel_tier",
                    "food_tier",
                    "景点门票",
                    "住宿",
                    "餐饮",
                    "本行程人均日均餐饮费",
                    "市内交通",
                    "其他当地费用",
                    "当地基础费用",
                    "10%机动",
                    "城际单程/人",
                    "城际往返",
                    "最终推荐",
                    "剩余",
                    "已覆盖范围剩余",
                    "缺口",
                    "超预算",
                    "可判断",
                    "升级规则",
                    "POI",
                    "异常",
                ],
                [
                    [
                        row["unit_id"],
                        row["task_type"],
                        row["user_input"],
                        row["origin"],
                        row["destination"],
                        row["duration_days"],
                        row["nights"],
                        row["people_count"],
                        row["rooms"],
                        _fmt(row["budget_amount"]),
                        row["budget_scope"],
                        row["requested_budget_scope"],
                        row["computed_budget_scope"],
                        _bool_cn(row["scope_complete"]),
                        row["sufficiency_status"],
                        row["hotel_tier"],
                        row["food_tier"],
                        _fmt(row["ticket_cost"]),
                        _fmt(row["accommodation_cost"]),
                        _fmt(row["food_cost"]),
                        _fmt(row["food_cost_per_person_day"]),
                        _fmt(row["local_transport_cost"]),
                        _fmt(row["other_local_cost"]),
                        _fmt(row["destination_local_basic_cost"]),
                        _fmt(row["contingency_amount"]),
                        _fmt(row["intercity_one_way_fare_per_person_cny"]),
                        _fmt(row["intercity_round_trip_cost_cny"]),
                        _fmt(row["final_recommended_total"]),
                        _fmt(row["remaining_budget"]),
                        _fmt(row["covered_scope_remaining_budget"]),
                        _fmt(row["budget_gap"]),
                        _bool_cn(row["is_over_budget"]),
                        _bool_cn(row["can_judge_budget_sufficiency"]),
                        row["upgrade_decision"],
                        row["standard_reference_poi_ids"],
                        row["issue_summary"] or "无",
                    ]
                    for row in rows
                ],
            ),
            "",
        ]
    )
    path.write_text(md, encoding="utf-8")


def _focus_explanation(row: Dict[str, Any], previous_row: Optional[Dict[str, Any]]) -> str:
    if row["budget_scope"] == "local_plus_round_trip_intercity":
        intercity = (
            "题目提供了出发地和目的地，冻结铁路快照支持该路线，"
            f"所以加入成人二等座往返费用{_fmt(row['intercity_round_trip_cost_cny'])}元。"
        )
    elif row["budget_scope"] == "destination_local_only":
        if row.get("requested_budget_scope") == "destination_local_only":
            intercity = "用户明确只问目的地当地费用，因此不纳入往返城际交通。"
        else:
            intercity = "题目没有提供出发地，只计算目的地当地费用，并提示不含往返城际交通。"
    else:
        intercity = "冻结铁路快照不支持该路线，不猜票价，只计算目的地当地费用并提示用户查询12306。"
    if previous_row:
        change_text = "；".join(f"{slot}: {previous_row.get(slot)} → {row.get(slot)}" for slot in row["actual_changed_slots"]) or "预算相关槽位未变化"
    else:
        change_text = "单轮题或多轮首轮，无上一轮变化"
    full_remaining_text = (
        "完整旅行剩余预算不表述"
        if row.get("scope_complete") is False and row.get("remaining_budget") in (None, "")
        else f"完整范围剩余{_fmt(row['remaining_budget'])}元"
    )
    return "\n".join(
        [
            f"#### {row['unit_id']}",
            "",
            f"- 用户输入：{row['user_input']}",
            f"- 预算范围：{SCOPE_CN.get(row['budget_scope'], row['budget_scope'])}。",
            f"- 城际交通：{intercity}",
            (
                f"- 当地基础费用：景点门票{_fmt(row['ticket_cost'])}元 + 住宿{_fmt(row['accommodation_cost'])}元 + "
                f"餐饮{_fmt(row['food_cost'])}元 + 市内交通{_fmt(row['local_transport_cost'])}元 + "
                f"其他当地费用{_fmt(row['other_local_cost'])}元 = {_fmt(row['destination_local_basic_cost'])}元。"
            ),
            f"- 酒店和餐饮档次：酒店 {row['hotel_tier']}，餐饮 {row['food_tier']}；{UPGRADE_CN.get(row['upgrade_decision'], '升级规则需要人工复核')}",
            f"- 是否触发自动升级：否。upgrade_applied={_compact(row['upgrade_applied'])}",
            (
                f"- 预算充足性：{'可以判断' if row['can_judge_budget_sufficiency'] else '不能完整判断'}；"
                f"sufficiency_status={row['sufficiency_status']}；scope_complete={_bool_cn(row['scope_complete'])}；"
                f"最终推荐{_fmt(row['final_recommended_total'])}元，{full_remaining_text}，"
                f"已覆盖范围剩余{_fmt(row['covered_scope_remaining_budget'])}元，缺口{_fmt(row['budget_gap'])}元。"
            ),
            f"- 多轮变化：{change_text}。",
            f"- 异常标记：{row['issue_summary'] or '未发现自动检查异常。'}",
            "",
        ]
    )


def _previous_focus_row(rows: List[Dict[str, Any]], row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    same_case = [candidate for candidate in rows if candidate["case_id"] == row["case_id"]]
    for index, candidate in enumerate(same_case):
        if candidate["unit_id"] == row["unit_id"] and index > 0:
            return same_case[index - 1]
    return None


def _markdown_table(headers: List[str], rows: List[List[Any]]) -> str:
    def cell(value: Any) -> str:
        return _compact(value).replace("\n", "<br>").replace("|", "\\|")

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(cell(value) for value in row) + " |")
    return "\n".join(lines)


def _unit_user_input(unit: Dict[str, Any]) -> str:
    turn = unit.get("turn") if isinstance(unit.get("turn"), dict) else None
    case = unit.get("case") if isinstance(unit.get("case"), dict) else {}
    if turn:
        return str(turn.get("user_input") or "")
    return str(case.get("user_input") or "")


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _close(left: Any, right: Any) -> bool:
    return abs(_float(left) - _float(right)) <= TOL


def _fmt(value: Any) -> str:
    parsed = _float(value)
    if value in (None, ""):
        return ""
    if abs(parsed - round(parsed)) <= 1e-9:
        return str(int(round(parsed)))
    return f"{parsed:.2f}".rstrip("0").rstrip(".")


def _bool_cn(value: Any) -> str:
    if value is True:
        return "是"
    if value is False:
        return "否"
    return ""


def _compact(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_PATH))
    parser.add_argument("--gold", default=str(DEFAULT_GOLD_PATH))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV))
    args = parser.parse_args()
    summary = generate_budget_review(
        dataset_path=args.dataset,
        gold_path=args.gold,
        output_md=args.output_md,
        output_csv=args.output_csv,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
