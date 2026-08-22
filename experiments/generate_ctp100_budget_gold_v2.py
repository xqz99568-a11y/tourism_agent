"""Generate formal Budget Policy v2.0 gold labels for CTP-100.

The script is intentionally side-effect-light: by default it reads the formal
dataset and writes a separate gold file under ``experiments/generated``.
It does not mutate ``ctp100_formal_v2.json``.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.fixed_data import (
    BUDGET_CONTINGENCY_RATIO,
    BUDGET_POLICY_VERSION,
    canonical_json_sha256,
    get_fixed_tourism_data,
)
from app.core.budget_manual_review import (
    DEFAULT_ECONOMY_BUDGET_MANUAL_REVIEW_MD_PATH,
    DEFAULT_ECONOMY_BUDGET_MANUAL_REVIEW_PATH,
    validate_economy_budget_manual_review,
)
from app.core.budget_gold import (
    BUDGET_GOLD_REVIEW_STATUS,
    BUDGET_GOLD_SCHEMA_VERSION,
    BUDGET_GOLD_STATUS,
    DEFAULT_BUDGET_POLICY_DOC_PATH,
    DEFAULT_CTP100_BUDGET_GOLD_PATH,
    build_budget_gold_artifact_hashes,
)


DEFAULT_DATASET_PATH = ROOT / "experiments" / "ctp100_formal_v2.json"
DEFAULT_OUTPUT_PATH = DEFAULT_CTP100_BUDGET_GOLD_PATH
BUDGET_GOLD_CANDIDATE_SCHEMA_VERSION = "ctp100-budget-gold-v2-candidate-v1"
BUDGET_GOLD_CANDIDATE_STATUS = "candidate_generated"
BUDGET_GOLD_PENDING_REVIEW_STATUS = "pending_human_confirmation"


def generate_budget_gold(
    *,
    dataset_path: str | Path = DEFAULT_DATASET_PATH,
    output_path: str | Path | None = DEFAULT_OUTPUT_PATH,
    write: bool = True,
    manual_review_path: str | Path = DEFAULT_ECONOMY_BUDGET_MANUAL_REVIEW_PATH,
    confirm_reviewed: bool = True,
) -> Dict[str, Any]:
    """Generate deterministic budget gold from the frozen fixed-data layer."""
    dataset_path = Path(dataset_path)
    document = _read_json(dataset_path)
    units = list(_iter_units(document.get("cases") or []))
    fixed_data = get_fixed_tourism_data()

    records: List[Dict[str, Any]] = []
    for unit in units:
        gold = _expected(unit)
        if not _requires_budget(gold):
            records.append(_skip_record(unit, reason="budget_not_required"))
            continue
        slots = _slots_for_budget(unit, gold)
        missing = [
            key
            for key in ("destination", "duration_days", "people_count")
            if slots.get(key) in (None, "", [], {})
        ]
        if missing:
            records.append(_skip_record(unit, reason="missing_budget_slots", missing_slots=missing))
            continue
        try:
            raw_budget = fixed_data.calculate_budget(
                origin=slots.get("origin"),
                destination=slots["destination"],
                duration=int(slots["duration_days"]),
                num_travelers=int(slots["people_count"]),
                budget_limit=slots.get("budget_amount"),
                budget_level=slots.get("budget_level") or "medium",
                hotel_level=slots.get("hotel_level"),
                food_level=slots.get("food_level"),
                transport_mode=slots.get("transport_mode"),
                requested_budget_scope=slots.get("requested_budget_scope"),
            )
        except Exception as exc:  # pragma: no cover - kept visible in generated report
            records.append(_skip_record(unit, reason="budget_generation_failed", error=str(exc)))
            continue
        records.append(_budget_record(unit, slots, raw_budget, gold))

    summary = _summary(records)
    manual_review = (
        _validated_manual_review_payload(manual_review_path)
        if confirm_reviewed
        else _pending_manual_review_payload(manual_review_path)
    )
    result = {
        "schema_version": BUDGET_GOLD_SCHEMA_VERSION if confirm_reviewed else BUDGET_GOLD_CANDIDATE_SCHEMA_VERSION,
        "gold_status": BUDGET_GOLD_STATUS if confirm_reviewed else BUDGET_GOLD_CANDIDATE_STATUS,
        "review_status": BUDGET_GOLD_REVIEW_STATUS if confirm_reviewed else BUDGET_GOLD_PENDING_REVIEW_STATUS,
        "dataset_id": document.get("dataset_id"),
        "dataset_version": document.get("dataset_version"),
        "source_dataset": str(dataset_path.relative_to(ROOT)) if dataset_path.is_relative_to(ROOT) else str(dataset_path),
        "source_dataset_sha256": canonical_json_sha256(document),
        "budget_policy_version": BUDGET_POLICY_VERSION,
        "contingency_ratio": BUDGET_CONTINGENCY_RATIO,
        "artifact_hashes": build_budget_gold_artifact_hashes(
            source_dataset=document,
            source_dataset_path=dataset_path,
            budget_policy_doc_path=DEFAULT_BUDGET_POLICY_DOC_PATH,
        ),
        "manual_review": manual_review,
        "generation_mode": "deterministic_fixed_data_standard_reference_budget",
        "dynamic_evaluation_note": (
            "For trip_planning/partial_replan outputs with final daily_itinerary, "
            "the evaluator should check formula compliance against the actual final itinerary. "
            "The standard_reference_budget below is the frozen fallback gold for budget-only "
            "or no-final-itinerary cases."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "records": records,
    }
    if write and output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return result


def _iter_units(cases: Iterable[Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    for case in cases:
        turns = case.get("turns") if isinstance(case.get("turns"), list) else []
        if not turns:
            yield {
                "case_id": str(case.get("case_id") or ""),
                "unit_id": str(case.get("case_id") or ""),
                "turn_id": None,
                "task_type": case.get("task_type"),
                "title": case.get("title"),
                "case": case,
                "turn": None,
            }
            continue
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            turn_id = str(turn.get("turn_id") or f"turn_{len(turns)}")
            case_id = str(case.get("case_id") or turn.get("case_id") or "")
            yield {
                "case_id": case_id,
                "unit_id": f"{case_id}::{turn_id}",
                "turn_id": turn_id,
                "task_type": turn.get("task_type") or case.get("task_type"),
                "title": turn.get("title") or case.get("title"),
                "case": case,
                "turn": turn,
            }


def _expected(unit: Dict[str, Any]) -> Dict[str, Any]:
    case = unit.get("case") if isinstance(unit.get("case"), dict) else {}
    turn = unit.get("turn") if isinstance(unit.get("turn"), dict) else {}
    expected: Dict[str, Any] = {}
    if isinstance(case.get("expected"), dict):
        expected.update(case["expected"])
    if isinstance(turn.get("expected"), dict):
        expected.update(turn["expected"])
    if isinstance(expected.get("hard_constraints"), dict):
        for key, value in expected["hard_constraints"].items():
            expected.setdefault(key, value)
    expected.setdefault("task_type", unit.get("task_type"))
    return expected


def _requires_budget(gold: Dict[str, Any]) -> bool:
    tools = _as_list(gold.get("required_tools"))
    accepted_sets = gold.get("accepted_tool_sets") if isinstance(gold.get("accepted_tool_sets"), list) else []
    accepted_tools = [tool for tool_set in accepted_sets for tool in _as_list(tool_set)]
    return "budget_calculator" in set(tools + accepted_tools)


def _slots_for_budget(unit: Dict[str, Any], gold: Dict[str, Any]) -> Dict[str, Any]:
    case = unit.get("case") if isinstance(unit.get("case"), dict) else {}
    turn = unit.get("turn") if isinstance(unit.get("turn"), dict) else {}
    merged: Dict[str, Any] = {}
    for source in (
        case.get("slots"),
        case.get("current_slots"),
        turn.get("slots"),
        turn.get("current_slots"),
        gold,
    ):
        if isinstance(source, dict):
            merged.update({key: value for key, value in source.items() if value not in (None, "", [], {})})
    raw_slots = {
        "origin": merged.get("origin"),
        "destination": merged.get("destination") or merged.get("city"),
        "duration_days": merged.get("duration_days") or merged.get("duration") or merged.get("days"),
        "people_count": merged.get("people_count") or merged.get("num_travelers"),
        "budget_amount": merged.get("budget_amount") or merged.get("budget_limit") or merged.get("budget"),
        "budget_level": merged.get("budget_level"),
        "hotel_level": merged.get("hotel_level"),
        "food_level": merged.get("food_level"),
        "transport_mode": merged.get("transport_mode"),
        "requested_budget_scope": _infer_requested_budget_scope(unit, merged),
    }
    return raw_slots


def _infer_requested_budget_scope(unit: Dict[str, Any], merged_slots: Dict[str, Any]) -> str:
    text = _unit_user_input(unit)
    compact = str(text or "").replace(" ", "")
    origin = str(merged_slots.get("origin") or "").strip()
    if not origin:
        return "destination_local_only"

    for key in ("requested_budget_scope", "budget_scope", "computed_budget_scope"):
        explicit = str(merged_slots.get(key) or "").strip()
        if explicit in {"destination_local_only", "local_only", "destination_only", "local"}:
            return "destination_local_only"
        if explicit in {"local_plus_round_trip_intercity", "full_trip", "complete_trip", "full"}:
            return "local_plus_round_trip_intercity"

    local_only_markers = (
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
    if any(marker in compact for marker in local_only_markers):
        return "destination_local_only"
    return "local_plus_round_trip_intercity"


def _budget_record(
    unit: Dict[str, Any],
    slots: Dict[str, Any],
    raw_budget: Dict[str, Any],
    gold: Dict[str, Any],
) -> Dict[str, Any]:
    intercity = raw_budget.get("intercity_transport") if isinstance(raw_budget.get("intercity_transport"), dict) else {}
    breakdown = raw_budget.get("breakdown") if isinstance(raw_budget.get("breakdown"), dict) else {}
    ticket_summary = (
        (raw_budget.get("ticket_breakdown") or {}).get("summary")
        if isinstance(raw_budget.get("ticket_breakdown"), dict)
        else {}
    ) or {}
    return {
        "unit_id": unit.get("unit_id"),
        "case_id": unit.get("case_id"),
        "turn_id": unit.get("turn_id"),
        "task_type": unit.get("task_type"),
        "status": "generated",
        "evaluation_mode": _evaluation_mode(unit),
        "input_slots": slots,
        "expected_scope_from_dataset": {
            "budget_scope": gold.get("budget_scope"),
            "requested_budget_scope": gold.get("requested_budget_scope"),
            "computed_budget_scope": gold.get("computed_budget_scope"),
            "scope_complete": gold.get("scope_complete"),
            "sufficiency_status": gold.get("sufficiency_status"),
            "intercity_transport_included": gold.get("intercity_transport_included"),
            "mandatory_budget_disclaimer": gold.get("mandatory_budget_disclaimer"),
        },
        "budget_policy_v2": {
            "budget_policy_version": raw_budget.get("budget_policy_version"),
            "budget_scope": raw_budget.get("budget_scope"),
            "requested_budget_scope": raw_budget.get("requested_budget_scope"),
            "computed_budget_scope": raw_budget.get("computed_budget_scope"),
            "scope_complete": raw_budget.get("scope_complete"),
            "sufficiency_status": raw_budget.get("sufficiency_status"),
            "people_count": raw_budget.get("num_travelers"),
            "duration_days": raw_budget.get("duration"),
            "nights": _nested(breakdown, "accommodation", "night_count"),
            "rooms": _nested(breakdown, "accommodation", "room_count"),
            "budget_limit": raw_budget.get("budget_limit"),
            "destination_local_basic_cost": raw_budget.get("destination_local_basic_cost"),
            "contingency_amount": raw_budget.get("contingency_amount"),
            "local_total_recommended": raw_budget.get("local_total_recommended"),
            "intercity_transport_cost": raw_budget.get("intercity_transport_cost"),
            "final_recommended_total": raw_budget.get("final_recommended_total"),
            "recommended_preparation_amount": raw_budget.get("recommended_preparation_amount"),
            "is_over_budget": raw_budget.get("is_over_budget"),
            "remaining_budget": raw_budget.get("remaining_budget"),
            "covered_scope_remaining_budget": raw_budget.get("covered_scope_remaining_budget"),
            "budget_gap": raw_budget.get("budget_gap"),
            "can_judge_budget_sufficiency": raw_budget.get("can_judge_budget_sufficiency"),
            "intercity_transport_included": raw_budget.get("intercity_transport_included"),
            "mandatory_budget_disclaimer": raw_budget.get("mandatory_budget_disclaimer"),
            "budget_disclaimer": raw_budget.get("budget_disclaimer"),
            "intercity_status": intercity.get("status"),
            "intercity_route_id": intercity.get("route_id"),
            "intercity_one_way_fare_per_person_cny": intercity.get("one_way_fare_per_person_cny"),
            "intercity_round_trip_cost_cny": intercity.get("total_intercity_transport_cost_cny"),
            "standard_reference_poi_ids": ticket_summary.get("selected_poi_ids") or [],
            "ticket_source": ticket_summary.get("source"),
            "upgrade_decision": _nested(raw_budget, "budget_policy", "upgrade_decision"),
            "upgrade_applied": _nested(raw_budget, "budget_policy", "upgrade_applied") or [],
            "hotel_tier": _nested(raw_budget, "budget_policy", "hotel_tier"),
            "food_tier": _nested(raw_budget, "budget_policy", "food_tier"),
            "cost_breakdown": {
                "ticket_cost": _nested(breakdown, "tickets", "recommended"),
                "accommodation_cost": _nested(breakdown, "accommodation", "recommended"),
                "food_cost": _nested(breakdown, "food", "recommended"),
                "local_transport_cost": _nested(breakdown, "transport", "recommended"),
                "other_local_cost": _nested(breakdown, "other", "recommended"),
            },
            "formula": {
                "final_recommended_total": "destination_local_basic_cost + contingency_amount + intercity_transport_cost",
                "contingency_amount": "destination_local_basic_cost * 0.10",
                "nights": "max(duration_days - 1, 0)",
                "rooms": "ceil(people_count / 2)",
            },
        },
    }


def _evaluation_mode(unit: Dict[str, Any]) -> str:
    task_type = str(unit.get("task_type") or "")
    if task_type in {"trip_planning", "partial_replan"}:
        return "dynamic_final_itinerary_budget_with_standard_reference_fallback"
    return "standard_reference_budget"


def _skip_record(unit: Dict[str, Any], *, reason: str, **extra: Any) -> Dict[str, Any]:
    return {
        "unit_id": unit.get("unit_id"),
        "case_id": unit.get("case_id"),
        "turn_id": unit.get("turn_id"),
        "task_type": unit.get("task_type"),
        "status": "skipped",
        "reason": reason,
        **extra,
    }


def _summary(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    generated = [record for record in records if record.get("status") == "generated"]
    skipped = [record for record in records if record.get("status") == "skipped"]
    return {
        "evaluation_unit_count": len(records),
        "budget_gold_count": len(generated),
        "skipped_count": len(skipped),
        "skipped_by_reason": {
            reason: sum(1 for record in skipped if record.get("reason") == reason)
            for reason in sorted({str(record.get("reason")) for record in skipped})
        },
        "generated_by_task_type": {
            task: sum(1 for record in generated if record.get("task_type") == task)
            for task in sorted({str(record.get("task_type")) for record in generated})
        },
    }


def _validated_manual_review_payload(path: str | Path) -> Dict[str, Any]:
    review = validate_economy_budget_manual_review(path)
    summary = review.get("summary") if isinstance(review.get("summary"), dict) else {}
    return {
        "required": True,
        "status": BUDGET_GOLD_REVIEW_STATUS,
        "status_source": "validated_economy_manual_review_ledger",
        "reviewer": review.get("reviewer"),
        "review_date": review.get("review_date"),
        "review_sha256": review.get("sha256"),
        "confirmed_scope": summary.get("confirmed_scope") or review.get("confirmed_scope") or [],
        "excluded_scope": summary.get("excluded_scope") or review.get("excluded_scope") or [],
        "formal_main_experiment_tiers": summary.get("formal_main_experiment_tiers")
        or review.get("formal_main_experiment_tiers")
        or [],
        "confirmed_city_ids": summary.get("city_ids") or [],
        "comfort_premium_exclusion": review.get("comfort_premium_exclusion") or {},
        "review_artifacts": {
            "economy_manual_review_json": _display_path(Path(path)),
            "economy_manual_review_md": _display_path(DEFAULT_ECONOMY_BUDGET_MANUAL_REVIEW_MD_PATH),
            "budget_gold_review_markdown": "experiments/generated/ctp100_budget_gold_v2_review.md",
            "budget_gold_review_csv": "experiments/generated/ctp100_budget_gold_v2_review.csv",
            "food_reference_policy": "experiments/generated/food_reference_policy_review_v1.md",
        },
    }


def _pending_manual_review_payload(path: str | Path) -> Dict[str, Any]:
    return {
        "required": True,
        "status": BUDGET_GOLD_PENDING_REVIEW_STATUS,
        "status_source": "candidate_generation_without_formal_review_confirmation",
        "reviewer": None,
        "review_date": None,
        "confirmed_scope": [],
        "excluded_scope": [],
        "formal_main_experiment_tiers": [],
        "confirmed_city_ids": [],
        "review_artifacts": {
            "expected_economy_manual_review_json": _display_path(Path(path)),
            "expected_economy_manual_review_md": _display_path(DEFAULT_ECONOMY_BUDGET_MANUAL_REVIEW_MD_PATH),
        },
    }


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


_CN_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _unit_user_input(unit: Dict[str, Any]) -> str:
    turn = unit.get("turn") if isinstance(unit.get("turn"), dict) else None
    case = unit.get("case") if isinstance(unit.get("case"), dict) else {}
    if isinstance(turn, dict):
        return str(turn.get("user_input") or "")
    return str(case.get("user_input") or "")


def _explicit_total_people_from_text(text: str) -> Optional[int]:
    compact_text = str(text or "").replace(" ", "")
    markers = ("现在一共", "一共", "总共")
    suffixes = ("个人", "人")
    for marker in markers:
        if marker not in compact_text:
            continue
        tail = compact_text.split(marker, 1)[1]
        for suffix in suffixes:
            if suffix not in tail:
                continue
            value = tail.split(suffix, 1)[0]
            parsed = _parse_small_int(value)
            if parsed is not None:
                return parsed
    return None


def _parse_small_int(value: Any) -> Optional[int]:
    text = str(value or "").strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        parsed = int(digits)
        return parsed if parsed > 0 else None
    if text in _CN_DIGITS and _CN_DIGITS[text] > 0:
        return _CN_DIGITS[text]
    return None


def _nested(value: Dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_PATH), help="Path to CTP-100 formal dataset.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Output formal budget gold JSON path.")
    parser.add_argument(
        "--manual-review",
        default=str(DEFAULT_ECONOMY_BUDGET_MANUAL_REVIEW_PATH),
        help="Validated economy manual review ledger required for formal confirmation.",
    )
    parser.add_argument(
        "--candidate",
        action="store_true",
        help="Generate a candidate gold file with pending review instead of a formally confirmed gold file.",
    )
    args = parser.parse_args()
    result = generate_budget_gold(
        dataset_path=args.dataset,
        output_path=args.output,
        write=True,
        manual_review_path=args.manual_review,
        confirm_reviewed=not args.candidate,
    )
    print(
        json.dumps(
            {
                "schema_version": result["schema_version"],
                "source_dataset": result["source_dataset"],
                "output": args.output,
                "summary": result["summary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
