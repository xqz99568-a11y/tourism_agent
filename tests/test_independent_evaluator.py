from copy import deepcopy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.independent_evaluator import (
    DECISION_NORMALIZATION_DIAGNOSTIC_SCHEMA_VERSION,
    EVALUATION_SCHEMA_VERSION,
    EVALUATION_SUMMARY_SCHEMA_VERSION,
    evaluate_case,
    render_paper_tables,
    summarize_evaluation_results,
)
from app.core.budget_gold import DEFAULT_CTP100_BUDGET_GOLD_PATH, load_budget_gold
from app.core.fixed_data import get_fixed_tourism_data
from app.core.no_date_weather_policy import NO_DATE_WEATHER_REMINDER
from app.core.qweather_snapshot import query_qweather_snapshot
from app.schemas.experiment import EXPERIMENT_OUTPUT_SCHEMA_VERSION
from app.tools.research_tools import GENERATION_TOOL_NAMES


def _tool_result(name: str, success: bool = True, data: dict | None = None, status: str | None = None) -> dict:
    if data is None:
        data = {
            "poi_search": {"attractions": [{"poi_id": "poi_a", "name": "POI A"}, {"poi_id": "poi_b", "name": "POI B"}]},
            "weather_query": {"daily_weather": [{"state": "sunny"}]},
            "budget_calculator": _budget_data(),
        }.get(name, {"value": "ok"})
    return {
        "schema_version": "research_tool_result_v1",
        "tool_name": name,
        "status": status or ("success" if success else "failed"),
        "success": success,
        "data": data,
        "metadata": {"offline": True},
    }


def _intercity_data() -> dict:
    return {
        "status": "success",
        "route_supported": True,
        "intercity_transport_included": True,
        "mandatory_budget_disclaimer": False,
        "budget_scope": "local_plus_round_trip_intercity",
        "route_id": "guangzhou_guilin_rail_second_class",
        "origin": "guangzhou",
        "destination": "guilin",
        "one_way_fare_per_person_cny": 200.0,
        "round_trip_multiplier": 2,
        "people_count": 2,
        "total_intercity_transport_cost_cny": 800.0,
        "fare_evidence": {
            "evidence_id": "rail_ev_010",
            "route_id": "guangzhou_guilin_rail_second_class",
            "departure_station": "Guangzhou South",
            "arrival_station": "Guilin West",
            "query_platform": "China Railway 12306 official website",
            "query_date": "2026-08-12",
            "planned_query_date": "2026-08-13",
            "travel_date": "2026-08-13",
            "fare_selection_rule_id": "visible_fastest_second_class_fare",
            "selected_train_no": "G3722",
            "screenshot_file": "data/intercity_transport/evidence/screenshots/rail_ev_010_guangzhou_guilin_12306_20260813.png",
            "screenshot_sha256": "test_sha256",
            "manual_review_status": "reviewed",
            "reviewed_at": "2026-08-12T23:59:25+08:00",
        },
    }


def _budget_data() -> dict:
    intercity = _intercity_data()
    return {
        "total": 900,
        "final_recommended_total": 900,
        "recommended_preparation_amount": 900,
        "budget_policy_version": "budget_policy_v2_0",
        "budget_scope": "local_plus_round_trip_intercity",
        "requested_budget_scope": "local_plus_round_trip_intercity",
        "computed_budget_scope": "local_plus_round_trip_intercity",
        "scope_complete": True,
        "sufficiency_status": "sufficient",
        "budget_limit": 1000,
        "remaining_budget": 100.0,
        "covered_scope_remaining_budget": 100.0,
        "budget_gap": 0.0,
        "is_over_budget": False,
        "can_judge_budget_sufficiency": True,
        "destination_local_basic_cost": 90.91,
        "local_total_recommended": 100.0,
        "contingency_amount": 9.09,
        "economic_baseline_total": 900,
        "intercity_transport_cost": 800.0,
        "intercity_transport_included": True,
        "mandatory_budget_disclaimer": False,
        "intercity_transport": intercity,
        "breakdown": {
            "transport": {"recommended": 10.0},
            "accommodation": {
                "recommended": 20.0,
                "reference_price_cny": 20.0,
                "room_count": 1,
                "night_count": 1,
                "tier": "economy",
            },
            "food": {"recommended": 30.0, "tier": "economy"},
            "tickets": {
                "recommended": 30.91,
                "selected_poi_ids": ["poi_a", "poi_b"],
                "source": "final_itinerary_pois",
            },
            "other": {"recommended": 0.0},
            "buffer": {"recommended": 9.09},
            "intercity_transport": {"recommended": 800.0},
        },
        "ticket_breakdown": {
            "summary": {
                "source": "final_itinerary_pois",
                "selected_poi_ids": ["poi_a", "poi_b"],
            }
        },
        "budget_policy": {
            "version": "budget_policy_v2_0",
            "economic_baseline_first": True,
            "contingency_ratio": 0.10,
            "budget_limit": 1000,
            "upgrade_decision": "economic_baseline",
            "upgrade_applied": [],
            "selected_scheme_id": "E",
            "hotel_tier": "economy",
            "food_tier": "economy",
        },
    }


def _tool_call(name: str, success: bool = True) -> dict:
    return {
        "tool_name": name,
        "status": "completed" if success else "failed",
        "success": success,
        "arguments": {},
    }


def _case() -> dict:
    return {
        "case_id": "eval-trip-success",
        "user_input": "plan a two day trip",
        "task_type": "trip_planning",
        "expected": {
            "task_type": "trip_planning",
            "duration_days": 2,
            "min_attractions": 2,
            "max_attractions": 4,
            "max_pois_per_day": 2,
            "budget_limit": 1000,
            "origin": "guangzhou",
            "intercity_transport_included": True,
            "budget_scope": "local_plus_round_trip_intercity",
            "requested_budget_scope": "local_plus_round_trip_intercity",
            "computed_budget_scope": "local_plus_round_trip_intercity",
            "scope_complete": True,
            "sufficiency_status": "sufficient",
            "mandatory_budget_disclaimer": False,
            "required_tools": list(GENERATION_TOOL_NAMES),
            "accepted_agent_sets": [["attraction", "weather", "itinerary", "budget"]],
            "accepted_tool_sets": [list(GENERATION_TOOL_NAMES)],
        },
    }


def _output() -> dict:
    calls = [_tool_call(name) for name in GENERATION_TOOL_NAMES]
    return {
        "schema_version": EXPERIMENT_OUTPUT_SCHEMA_VERSION,
        "case_id": "eval-trip-success",
        "method": "fixed_multi_agent",
        "task_type": "trip_planning",
        "planned_agents": ["attraction", "weather", "itinerary", "budget"],
        "used_agents": ["attraction", "weather", "itinerary", "budget"],
        "planned_tools": list(GENERATION_TOOL_NAMES),
        "called_tools": calls,
        "tool_results": {name: _tool_result(name) for name in GENERATION_TOOL_NAMES},
        "attractions": [{"poi_id": "poi_a", "name": "POI A"}, {"poi_id": "poi_b", "name": "POI B"}],
        "trip_days": 2,
        "daily_itinerary": [
            {"day": 1, "attractions": [{"poi_id": "poi_a", "name": "POI A"}]},
            {"day": 2, "attractions": [{"poi_id": "poi_b", "name": "POI B"}]},
        ],
        "budget": _budget_data(),
        "weather": {"daily_weather": [{"state": "sunny"}]},
        "weather_adjustments": [],
        "constraint_report": {
            "data": {
                "checks": [
                    {"name": "poi_existence", "status": "passed", "details": {}},
                    {"name": "rain_attraction_suitability", "status": "NA", "details": {}},
                    {"name": "senior_accessibility", "status": "NA", "details": {}},
                ]
            }
        },
        "execution_status": "completed",
        "final_answer": "Two-day plan: POI A and POI B. Budget total 900. Weather sunny.",
    }


def _formal_case(case_id: str = "ctp100_v2_016") -> dict:
    dataset = json.loads((ROOT / "experiments" / "ctp100_formal_v2.json").read_text(encoding="utf-8-sig"))
    return deepcopy(next(case for case in dataset["cases"] if case["case_id"] == case_id))


def _formal_budget_record(unit_id: str = "ctp100_v2_016") -> dict:
    gold = load_budget_gold(DEFAULT_CTP100_BUDGET_GOLD_PATH)
    return deepcopy(next(record for record in gold["records"] if record["unit_id"] == unit_id))


def _formal_daily_itinerary(poi_ids: list[str], duration: int) -> list[dict]:
    daily: list[dict] = []
    for index in range(duration):
        day_ids = poi_ids[index * 2 : (index + 1) * 2]
        daily.append(
            {
                "day": index + 1,
                "attractions": [
                    {"poi_id": poi_id, "name": poi_id}
                    for poi_id in day_ids
                ],
            }
        )
    return daily


def _formal_budget_output(case_id: str = "ctp100_v2_016") -> dict:
    case = _formal_case(case_id)
    record = _formal_budget_record(case_id)
    slots = record["input_slots"]
    bp = record["budget_policy_v2"]
    poi_ids = list(bp["standard_reference_poi_ids"])
    daily_itinerary = _formal_daily_itinerary(poi_ids, int(bp["duration_days"]))
    budget = get_fixed_tourism_data().calculate_budget(
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
        daily_itinerary=daily_itinerary,
    )
    tools = case["expected"]["required_tools"]
    output = {
        "schema_version": EXPERIMENT_OUTPUT_SCHEMA_VERSION,
        "case_id": case_id,
        "method": "fixed_multi_agent",
        "task_type": case["task_type"],
        "planned_agents": case["expected"]["accepted_agent_sets"][0],
        "used_agents": case["expected"]["accepted_agent_sets"][0],
        "planned_tools": tools,
        "called_tools": [_tool_call(name) for name in tools],
        "tool_results": {
            "poi_search": _tool_result(
                "poi_search",
                data={
                    "attractions": [
                        {"poi_id": poi_id, "name": poi_id}
                        for poi_id in poi_ids
                    ]
                },
            ),
            "budget_calculator": _tool_result("budget_calculator", data=deepcopy(budget)),
        },
        "attractions": [{"poi_id": poi_id, "name": poi_id} for poi_id in poi_ids],
        "trip_days": int(bp["duration_days"]),
        "daily_itinerary": daily_itinerary,
        "budget": budget,
        "weather": {},
        "weather_adjustments": [],
        "constraint_report": {
            "data": {
                "checks": [
                    {"name": "poi_existence", "status": "passed", "details": {}},
                    {"name": "rain_attraction_suitability", "status": "NA", "details": {}},
                    {"name": "senior_accessibility", "status": "NA", "details": {}},
                ]
            }
        },
        "execution_status": "completed",
        "final_answer": "Formal budget output for testing.",
    }
    _sync_formal_budget_tool_result(output)
    return output


def _sync_formal_budget_tool_result(output: dict) -> None:
    output["tool_results"]["budget_calculator"] = _tool_result(
        "budget_calculator",
        data=deepcopy(output["budget"]),
    )


def _recompute_budget_totals(budget: dict, *, contingency_amount: float | None = None) -> None:
    breakdown = budget["breakdown"]
    local_basic = round(
        sum(
            float(breakdown[section]["recommended"])
            for section in ("transport", "accommodation", "food", "tickets", "other")
        ),
        2,
    )
    intercity_cost = float(budget.get("intercity_transport_cost") or 0.0)
    if contingency_amount is None:
        contingency_amount = round(local_basic * 0.10, 2)
    budget["destination_local_basic_cost"] = local_basic
    budget["contingency_amount"] = round(float(contingency_amount), 2)
    budget["breakdown"]["buffer"]["recommended"] = budget["contingency_amount"]
    budget["breakdown"]["intercity_transport"]["recommended"] = intercity_cost
    budget["local_total_recommended"] = round(local_basic + budget["contingency_amount"], 2)
    total = round(budget["local_total_recommended"] + intercity_cost, 2)
    for field in ("total", "final_recommended_total", "recommended_preparation_amount", "economic_baseline_total"):
        budget[field] = total
    limit = budget.get("budget_limit")
    if limit is None:
        budget["sufficiency_status"] = "indeterminate"
        budget["can_judge_budget_sufficiency"] = False
        budget["is_over_budget"] = False
        budget["remaining_budget"] = None
        budget["covered_scope_remaining_budget"] = None
        budget["budget_gap"] = None
        return
    limit = float(limit)
    over_budget = total > limit + 0.02
    budget["sufficiency_status"] = "insufficient" if over_budget else "sufficient"
    budget["can_judge_budget_sufficiency"] = True
    budget["is_over_budget"] = over_budget
    budget["remaining_budget"] = round(limit - total, 2) if not over_budget else 0.0
    budget["covered_scope_remaining_budget"] = budget["remaining_budget"]
    budget["budget_gap"] = round(total - limit, 2) if over_budget else 0.0


def test_independent_evaluator_scores_one_case_against_frozen_rules() -> None:
    report = evaluate_case(case=_case(), output=_output(), trace={})

    assert report["schema_version"] == EVALUATION_SCHEMA_VERSION
    assert report["catalog_id"] == "day8_formal_independent_evaluator_rules"
    assert report["case_id"] == "eval-trip-success"
    assert len(report["rules"]) == 46
    assert report["metrics"]["stsr"] is True
    assert report["metrics"]["evaluation_hcsr"] == 1.0
    assert report["metrics"]["itcsr"] == 1.0
    assert report["metrics"]["bpcr"] == 1.0
    assert report["metrics"]["agent_selection_f1"] == 1.0
    assert report["metrics"]["tool_selection_f1"] == 1.0


def test_independent_evaluator_records_zero_cost_for_explicit_zero_call_trace() -> None:
    report = evaluate_case(
        case=_case(),
        output=_output(),
        trace={
            "llm_call_count": 0,
            "api_call_count": 0,
            "total_tokens": 0,
            "llm_calls": [],
            "api_calls": [],
        },
    )

    assert report["metrics"]["estimated_cost"] == 0.0
    assert report["metrics"]["standardized_estimated_cost"] == 0.0
    assert report["metrics"]["actual_cost"] is None


def test_evaluator_counts_daily_attraction_poi_ids_for_bounds_and_daily_load() -> None:
    case = deepcopy(_case())
    case["expected"]["min_attractions"] = 4
    case["expected"]["max_attractions"] = 4
    case["expected"]["max_pois_per_day"] = 2
    output = deepcopy(_output())
    output["attractions"] = []
    output["daily_itinerary"] = [
        {"day": 1, "attraction_poi_ids": ["poi_a", "poi_b"]},
        {"day": 2, "attraction_poi_ids": ["poi_c", "poi_d"]},
    ]

    report = evaluate_case(case=case, output=output, trace={})
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_ATTRACTION_COUNT_BOUNDS"]["status"] == "passed"
    assert rules["H_DAILY_LOAD_LIMIT"]["status"] == "passed"


def test_independent_evaluator_is_method_blind() -> None:
    output_a = _output()
    output_b = deepcopy(output_a)
    output_a["method"] = "fixed_multi_agent"
    output_b["method"] = "adaptive_multi_agent"

    assert evaluate_case(case=_case(), output=output_a) == evaluate_case(case=_case(), output=output_b)


def test_independent_evaluator_fails_missing_required_tool_evidence() -> None:
    output = _output()
    del output["tool_results"]["budget_calculator"]
    output["called_tools"] = [_tool_call("poi_search"), _tool_call("weather_query")]

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_TOOL_EVIDENCE"]["status"] == "failed"
    assert rules["S_TOOL_SET_MATCH"]["status"] == "failed"
    assert report["metrics"]["stsr"] is False
    assert "H_TOOL_EVIDENCE" in report["metrics"]["evaluation_failed_rule_ids"]


def test_wrong_output_schema_version_fails_schema_gate() -> None:
    output = _output()
    output["schema_version"] = "WRONG-SCHEMA"

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["G_SCHEMA_VALID"]["status"] == "failed"
    assert report["metrics"]["stsr"] is False


def test_invalid_execution_status_fails_schema_and_status_gate() -> None:
    output = _output()
    output["execution_status"] = "banana"

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["G_SCHEMA_VALID"]["status"] == "failed"
    assert rules["G_EXECUTION_STATUS_VALID"]["status"] == "failed"
    assert "invalid_execution_status" in rules["G_EXECUTION_STATUS_VALID"]["details"]["issues"]
    assert report["metrics"]["stsr"] is False


def test_failed_execution_status_is_not_counted_as_task_success() -> None:
    output = _output()
    output["execution_status"] = "failed"

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["G_SCHEMA_VALID"]["status"] == "passed"
    assert rules["G_EXECUTION_STATUS_VALID"]["status"] == "failed"
    assert "execution_failed" in rules["G_EXECUTION_STATUS_VALID"]["details"]["issues"]
    assert report["metrics"]["stsr"] is False


def test_hcsr_uses_gold_task_type_when_output_task_type_is_wrong() -> None:
    output = _output()
    output.update(
        {
            "task_type": "general_chat",
            "planned_agents": [],
            "used_agents": [],
            "planned_tools": [],
            "called_tools": [],
            "tool_results": {},
            "attractions": [],
            "trip_days": None,
            "daily_itinerary": [],
            "budget": None,
            "weather": None,
            "final_answer": "Hello.",
        }
    )

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert report["task_type"] == "trip_planning"
    assert report["output_task_type"] == "general_chat"
    assert rules["G_TASK_TYPE_MATCH"]["status"] == "failed"
    assert report["metrics"]["evaluation_hcsr"] is not None
    assert report["metrics"]["evaluation_hcsr_applicable_count"] > 0
    assert report["metrics"]["stsr"] is False


def test_duplicate_pois_are_detected_before_deduplication() -> None:
    output = _output()
    output["daily_itinerary"] = [
        {"day": 1, "attractions": [{"poi_id": "poi_a", "name": "POI A"}, {"poi_id": "poi_a", "name": "POI A"}]},
        {"day": 2, "attractions": [{"poi_id": "poi_b", "name": "POI B"}]},
    ]

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_NO_DUPLICATE_POIS"]["status"] == "failed"
    assert rules["H_NO_DUPLICATE_POIS"]["details"]["duplicates"] == ["poi_a"]


def test_called_tool_without_verifiable_result_does_not_pass_tool_evidence() -> None:
    output = _output()
    output["tool_results"]["weather_query"] = {"tool_name": "weather_query"}
    output["called_tools"] = [_tool_call("poi_search"), {"tool_name": "weather_query"}, _tool_call("budget_calculator")]

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_WEATHER_EVIDENCE"]["status"] == "failed"
    assert rules["H_TOOL_EVIDENCE"]["status"] == "failed"


def test_success_tool_result_with_empty_data_does_not_pass_tool_evidence() -> None:
    output = _output()
    output["tool_results"]["weather_query"] = _tool_result("weather_query", data={})

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_WEATHER_EVIDENCE"]["status"] == "failed"
    assert rules["H_TOOL_EVIDENCE"]["status"] == "failed"


def test_failed_tool_result_does_not_pass_tool_evidence() -> None:
    output = _output()
    output["tool_results"]["weather_query"] = _tool_result("weather_query", success=False)

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["G_EXECUTION_STATUS_VALID"]["status"] == "failed"
    assert rules["H_WEATHER_EVIDENCE"]["status"] == "failed"
    assert rules["H_TOOL_EVIDENCE"]["status"] == "failed"


def test_weather_output_must_match_weather_tool_result() -> None:
    output = _output()
    output["weather"] = {"daily_weather": [{"state": "sunny"}]}
    output["tool_results"]["weather_query"] = _tool_result(
        "weather_query",
        data={"daily_weather": [{"state": "rain"}]},
    )

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_WEATHER_EVIDENCE"]["status"] == "failed"
    assert rules["H_TOOL_EVIDENCE"]["status"] == "failed"
    assert report["metrics"]["stsr"] is False


def test_weather_evidence_checks_expected_coverage_and_missing_dates() -> None:
    weather = query_qweather_snapshot(city="hangzhou", start_date="2026-09-05", days=3)
    case = _case()
    case["expected"].update(
        {
            "weather_required": True,
            "expected_weather_coverage_status": "partial",
            "expected_weather_missing_dates": ["2026-09-06", "2026-09-07"],
        }
    )
    output = _output()
    output["weather"] = deepcopy(weather)
    output["tool_results"]["weather_query"] = _tool_result("weather_query", data=deepcopy(weather))

    report = evaluate_case(case=case, output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_WEATHER_EVIDENCE"]["status"] == "passed"

    bad_output = deepcopy(output)
    bad_output["weather"]["coverage_status"] = "full"

    bad_report = evaluate_case(case=case, output=bad_output)
    bad_rules = {item["id"]: item for item in bad_report["rules"]}

    assert bad_rules["H_WEATHER_EVIDENCE"]["status"] == "failed"
    assert "output_tool_weather_mismatch" in bad_rules["H_WEATHER_EVIDENCE"]["details"]["issues"]
    assert "coverage_status_mismatch" in bad_rules["H_WEATHER_EVIDENCE"]["details"]["mismatch_issues"]


def test_weather_evidence_checks_frozen_daily_values() -> None:
    weather = query_qweather_snapshot(city="beijing", start_date="2026-08-07", days=2)
    case = _case()
    case["expected"].update(
        {
            "weather_required": True,
            "expected_weather_coverage_status": "full",
            "expected_weather_missing_dates": [],
        }
    )
    output = _output()
    output["weather"] = deepcopy(weather)
    output["tool_results"]["weather_query"] = _tool_result("weather_query", data=deepcopy(weather))

    report = evaluate_case(case=case, output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_WEATHER_EVIDENCE"]["status"] == "passed"

    bad_output = deepcopy(output)
    bad_output["weather"]["daily_weather"][0]["temperature_max_c"] += 1

    bad_report = evaluate_case(case=case, output=bad_output)
    bad_rules = {item["id"]: item for item in bad_report["rules"]}

    assert bad_rules["H_WEATHER_EVIDENCE"]["status"] == "failed"
    assert "daily_weather_value_mismatch" in bad_rules["H_WEATHER_EVIDENCE"]["details"]["mismatch_issues"]


def test_weather_evidence_requeries_snapshot_when_tool_and_output_match_each_other() -> None:
    weather = query_qweather_snapshot(city="beijing", start_date="2026-08-07", days=2)
    fabricated = deepcopy(weather)
    fabricated["daily_weather"][0]["temperature_max_c"] += 1
    fabricated["daily_forecasts"] = fabricated["daily_weather"]
    fabricated["forecast"] = fabricated["daily_weather"]
    case = _case()
    case["expected"].update(
        {
            "weather_required": True,
            "expected_weather_coverage_status": "full",
            "expected_weather_missing_dates": [],
        }
    )
    output = _output()
    output["weather"] = deepcopy(fabricated)
    output["tool_results"]["weather_query"] = _tool_result("weather_query", data=deepcopy(fabricated))

    report = evaluate_case(case=case, output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_WEATHER_EVIDENCE"]["status"] == "failed"
    assert "tool_weather_snapshot_mismatch" in rules["H_WEATHER_EVIDENCE"]["details"]["issues"]
    assert "daily_weather_value_mismatch" in rules["H_WEATHER_EVIDENCE"]["details"]["snapshot_issues"]


def test_no_date_trip_plan_requires_weather_reminder_without_weather_evidence() -> None:
    case = _case()
    case["expected"].update(
        {
            "required_tools": ["poi_search", "budget_calculator"],
            "accepted_agent_sets": [["attraction", "itinerary", "budget"]],
            "accepted_tool_sets": [["poi_search", "budget_calculator"]],
            "forbidden_tools": ["weather_query"],
            "weather_required": False,
            "weather_date_policy": "no_date_no_specific_weather_for_trip_plan",
            "no_date_weather_reminder_required": True,
        }
    )
    output = _output()
    output["planned_agents"] = ["attraction", "itinerary", "budget"]
    output["used_agents"] = ["attraction", "itinerary", "budget"]
    output["planned_tools"] = ["poi_search", "budget_calculator"]
    output["called_tools"] = [_tool_call("poi_search"), _tool_call("budget_calculator")]
    output["tool_results"].pop("weather_query", None)
    output["weather"] = None
    output["final_answer"] = f"Two-day plan: POI A and POI B. Budget total 900.\n\n{NO_DATE_WEATHER_REMINDER}"

    report = evaluate_case(case=case, output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_NO_DATE_WEATHER_REMINDER"]["status"] == "passed"


def test_no_date_trip_plan_fails_when_weather_reminder_is_missing() -> None:
    case = _case()
    case["expected"].update(
        {
            "required_tools": ["poi_search", "budget_calculator"],
            "weather_required": False,
            "weather_date_policy": "no_date_no_specific_weather_for_trip_plan",
            "no_date_weather_reminder_required": True,
        }
    )
    output = _output()
    output["called_tools"] = [_tool_call("poi_search"), _tool_call("budget_calculator")]
    output["tool_results"].pop("weather_query", None)
    output["weather"] = None
    output["final_answer"] = "Two-day plan: POI A and POI B. Budget total 900."

    report = evaluate_case(case=case, output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_NO_DATE_WEATHER_REMINDER"]["status"] == "failed"
    assert "no_date_weather_reminder_missing" in rules["H_NO_DATE_WEATHER_REMINDER"]["details"]["issues"]


def test_no_date_trip_plan_fails_when_weather_evidence_is_fabricated() -> None:
    case = _case()
    case["expected"].update(
        {
            "required_tools": ["poi_search", "budget_calculator"],
            "weather_required": False,
            "weather_date_policy": "no_date_no_specific_weather_for_trip_plan",
            "no_date_weather_reminder_required": True,
        }
    )
    output = _output()
    output["final_answer"] = f"Two-day plan: POI A and POI B. Budget total 900.\n\n{NO_DATE_WEATHER_REMINDER}"

    report = evaluate_case(case=case, output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_NO_DATE_WEATHER_REMINDER"]["status"] == "failed"
    assert "no_date_weather_query_forbidden" in rules["H_NO_DATE_WEATHER_REMINDER"]["details"]["issues"]
    assert "concrete_weather_fabricated" in rules["H_NO_DATE_WEATHER_REMINDER"]["details"]["issues"]


def test_budget_output_must_match_budget_tool_result() -> None:
    output = _output()
    output["budget"] = {"total": 900}
    output["tool_results"]["budget_calculator"] = _tool_result(
        "budget_calculator",
        data={"total": 1200},
    )

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_BUDGET_EVIDENCE"]["status"] == "failed"
    assert rules["H_TOOL_EVIDENCE"]["status"] == "failed"


def test_intercity_scope_rule_fails_when_required_rail_cost_is_omitted() -> None:
    output = _output()
    output["budget"] = {
        "total": 602,
        "budget_scope": "destination_local_only",
        "intercity_transport_cost": 0.0,
        "intercity_transport_included": False,
        "mandatory_budget_disclaimer": True,
        "budget_disclaimer": "origin missing",
        "intercity_transport": {
            "status": "origin_missing",
            "intercity_transport_included": False,
            "mandatory_budget_disclaimer": True,
            "budget_scope": "destination_local_only",
        },
    }
    output["tool_results"]["budget_calculator"] = _tool_result(
        "budget_calculator",
        data=output["budget"],
    )

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_INTERCITY_SCOPE"]["status"] == "failed"
    assert "budget_scope_mismatch" in rules["H_INTERCITY_SCOPE"]["details"]["issues"]
    assert report["metrics"]["itcsr"] < 1.0
    assert report["metrics"]["stsr"] is False


def test_intercity_cost_rule_fails_wrong_round_trip_formula() -> None:
    output = _output()
    output["budget"] = _budget_data()
    output["budget"]["intercity_transport_cost"] = 149.0
    output["tool_results"]["budget_calculator"] = _tool_result(
        "budget_calculator",
        data=output["budget"],
    )

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_INTERCITY_COST"]["status"] == "failed"
    assert rules["H_INTERCITY_COST"]["details"]["expected"] == 800.0
    assert rules["H_INTERCITY_COST"]["details"]["actual"] == 149.0
    assert report["metrics"]["itcsr_failed_count"] >= 1


def test_intercity_evidence_rule_fails_missing_evidence_id() -> None:
    output = _output()
    output["budget"] = _budget_data()
    del output["budget"]["intercity_transport"]["fare_evidence"]["evidence_id"]
    output["tool_results"]["budget_calculator"] = _tool_result(
        "budget_calculator",
        data=output["budget"],
    )

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_INTERCITY_EVIDENCE"]["status"] == "failed"
    assert "evidence_id" in rules["H_INTERCITY_EVIDENCE"]["details"]["missing"]
    assert report["metrics"]["itcsr_failed_count"] >= 1


def test_intercity_scope_rule_fails_when_route_evidence_uses_wrong_origin() -> None:
    case = _case()
    case["expected"]["origin"] = "zhengzhou"
    case["expected"]["destination"] = "xian"
    output = _output()
    output["budget"] = _budget_data()
    output["budget"]["intercity_transport"].update(
        {
            "requested_origin": "zhengzhou",
            "requested_destination": "xian",
            "origin": "guangzhou",
            "destination": "xian",
            "lookup_origin": "guangzhou",
            "lookup_destination": "xian",
            "route_id": "guangzhou_xian_rail_second_class",
        }
    )
    output["tool_results"]["budget_calculator"] = _tool_result(
        "budget_calculator",
        data=output["budget"],
    )

    report = evaluate_case(case=case, output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_INTERCITY_SCOPE"]["status"] == "failed"
    assert "origin_mismatch" in rules["H_INTERCITY_SCOPE"]["details"]["issues"]
    assert "lookup_route_mismatch" in rules["H_INTERCITY_SCOPE"]["details"]["issues"]
    assert report["metrics"]["itcsr"] < 1.0


def test_intercity_evidence_rule_fails_route_id_mismatch() -> None:
    output = _output()
    output["budget"] = _budget_data()
    output["budget"]["intercity_transport"]["fare_evidence"][
        "route_id"
    ] = "zhengzhou_xian_rail_second_class"
    output["tool_results"]["budget_calculator"] = _tool_result(
        "budget_calculator",
        data=output["budget"],
    )

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_INTERCITY_EVIDENCE"]["status"] == "failed"
    assert "evidence_route_id_mismatch" in rules["H_INTERCITY_EVIDENCE"]["details"]["malformed"]
    assert report["metrics"]["itcsr_failed_count"] >= 1


def test_budget_independent_recalculation_passes_formal_case() -> None:
    output = _formal_budget_output()

    report = evaluate_case(case=_formal_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_BUDGET_INDEPENDENT_RECALCULATION"]["status"] == "passed"
    assert rules["H_INTERCITY_COST"]["status"] == "passed"
    assert output["budget"]["intercity_transport"]["one_way_fare_per_person_cny"] == 623.0
    assert output["budget"]["intercity_transport"]["total_intercity_transport_cost_cny"] == 3738.0


def test_budget_independent_recalculation_accepts_local_total_alias() -> None:
    output = _formal_budget_output()
    output["budget"]["local_total"] = output["budget"].pop("local_total_recommended")
    _sync_formal_budget_tool_result(output)

    report = evaluate_case(case=_formal_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_BUDGET_INDEPENDENT_RECALCULATION"]["status"] == "passed"


def test_budget_independent_recalculation_accepts_ticket_source_alias_when_pois_match() -> None:
    output = _formal_budget_output()
    output["budget"]["ticket_breakdown"]["summary"]["source"] = "standard_reference_poi_combo"
    output["budget"]["breakdown"]["tickets"]["source"] = "standard_reference_poi_combo"
    _sync_formal_budget_tool_result(output)

    report = evaluate_case(case=_formal_case(), output=output)
    rule = {item["id"]: item for item in report["rules"]}["H_BUDGET_INDEPENDENT_RECALCULATION"]

    assert rule["status"] == "passed"
    assert "wrong_ticket_source" not in rule["details"]["issues"]


def test_budget_gold_overrides_stale_dataset_disclaimer_for_no_origin_local_budget() -> None:
    output = _formal_budget_output("ctp100_v2_049")

    report = evaluate_case(case=_formal_case("ctp100_v2_049"), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert output["budget"]["mandatory_budget_disclaimer"] is True
    assert rules["H_BUDGET_INDEPENDENT_RECALCULATION"]["status"] == "passed"


def test_budget_independent_recalculation_fails_wrong_hotel_reference_price() -> None:
    output = _formal_budget_output()
    accommodation = output["budget"]["breakdown"]["accommodation"]
    accommodation["reference_price_cny"] += 100
    accommodation["recommended"] = round(
        accommodation["reference_price_cny"]
        * accommodation["room_count"]
        * accommodation["night_count"],
        2,
    )
    _recompute_budget_totals(output["budget"])
    _sync_formal_budget_tool_result(output)

    report = evaluate_case(case=_formal_case(), output=output)
    rule = {item["id"]: item for item in report["rules"]}["H_BUDGET_INDEPENDENT_RECALCULATION"]

    assert rule["status"] == "failed"
    assert "wrong_accommodation_reference_price_cny" in rule["details"]["issues"]


def test_budget_independent_recalculation_fails_wrong_rail_fare_even_if_formula_self_consistent() -> None:
    output = _formal_budget_output()
    intercity = output["budget"]["intercity_transport"]
    intercity["one_way_fare_per_person_cny"] = 600.0
    intercity["total_intercity_transport_cost_cny"] = 600.0 * intercity["round_trip_multiplier"] * intercity["people_count"]
    output["budget"]["intercity_transport_cost"] = intercity["total_intercity_transport_cost_cny"]
    output["budget"]["breakdown"]["intercity_transport"]["recommended"] = intercity["total_intercity_transport_cost_cny"]
    _recompute_budget_totals(output["budget"])
    _sync_formal_budget_tool_result(output)

    report = evaluate_case(case=_formal_case(), output=output)
    rule = {item["id"]: item for item in report["rules"]}["H_BUDGET_INDEPENDENT_RECALCULATION"]

    assert rule["status"] == "failed"
    assert "wrong_intercity_one_way_fare_per_person_cny" in rule["details"]["issues"]
    assert "wrong_intercity_total_intercity_transport_cost_cny" in rule["details"]["issues"]


def test_budget_independent_recalculation_fails_missing_hotel_night() -> None:
    output = _formal_budget_output()
    accommodation = output["budget"]["breakdown"]["accommodation"]
    accommodation["night_count"] -= 1
    accommodation["recommended"] = round(
        accommodation["reference_price_cny"]
        * accommodation["room_count"]
        * accommodation["night_count"],
        2,
    )
    _recompute_budget_totals(output["budget"])
    _sync_formal_budget_tool_result(output)

    report = evaluate_case(case=_formal_case(), output=output)
    rule = {item["id"]: item for item in report["rules"]}["H_BUDGET_INDEPENDENT_RECALCULATION"]

    assert rule["status"] == "failed"
    assert "wrong_accommodation_night_count" in rule["details"]["issues"]


def test_budget_independent_recalculation_fails_buffer_applied_to_intercity() -> None:
    output = _formal_budget_output()
    wrong_buffer = round(
        (output["budget"]["destination_local_basic_cost"] + output["budget"]["intercity_transport_cost"])
        * 0.10,
        2,
    )
    _recompute_budget_totals(output["budget"], contingency_amount=wrong_buffer)
    _sync_formal_budget_tool_result(output)

    report = evaluate_case(case=_formal_case(), output=output)
    rule = {item["id"]: item for item in report["rules"]}["H_BUDGET_INDEPENDENT_RECALCULATION"]

    assert rule["status"] == "failed"
    assert "wrong_contingency_amount" in rule["details"]["issues"]


def test_budget_independent_recalculation_fails_per_person_budget_limit() -> None:
    output = _formal_budget_output()
    output["budget"]["budget_limit"] = 3000
    output["budget"]["budget_policy"]["budget_limit"] = 3000
    _recompute_budget_totals(output["budget"])
    _sync_formal_budget_tool_result(output)

    report = evaluate_case(case=_formal_case(), output=output)
    rule = {item["id"]: item for item in report["rules"]}["H_BUDGET_INDEPENDENT_RECALCULATION"]

    assert rule["status"] == "failed"
    assert "wrong_budget_limit" in rule["details"]["issues"]
    assert "wrong_sufficiency_status" in rule["details"]["issues"]


def test_bpcr_fails_wrong_budget_policy_formula() -> None:
    output = _output()
    output["budget"] = _budget_data()
    output["budget"]["contingency_amount"] = 99.0
    output["budget"]["breakdown"]["buffer"]["recommended"] = 99.0
    output["tool_results"]["budget_calculator"] = _tool_result(
        "budget_calculator",
        data=output["budget"],
    )
    output["final_answer"] = "Two-day plan: POI A and POI B. Budget total 900. Weather sunny."

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_BUDGET_CONTINGENCY_LOCAL_ONLY"]["status"] == "failed"
    assert rules["H_BUDGET_TOTAL_FORMULA"]["status"] == "failed"
    assert report["metrics"]["bpcr"] < 1.0
    assert report["metrics"]["bpcr_failed_count"] >= 2


def test_bpcr_fails_itinerary_budget_poi_mismatch() -> None:
    output = _output()
    output["budget"] = _budget_data()
    output["budget"]["ticket_breakdown"]["summary"]["selected_poi_ids"] = ["poi_a"]
    output["budget"]["breakdown"]["tickets"]["selected_poi_ids"] = ["poi_a"]
    output["tool_results"]["budget_calculator"] = _tool_result(
        "budget_calculator",
        data=output["budget"],
    )

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_BUDGET_ITINERARY_CONSISTENCY"]["status"] == "failed"
    assert "itinerary_budget_poi_mismatch" in rules["H_BUDGET_ITINERARY_CONSISTENCY"]["details"]["issues"]
    assert report["metrics"]["bpcr"] < 1.0


def test_bpcr_accepts_itinerary_budget_same_pois_in_different_order() -> None:
    output = _output()
    output["budget"] = _budget_data()
    output["budget"]["ticket_breakdown"]["summary"]["selected_poi_ids"] = ["poi_b", "poi_a"]
    output["budget"]["breakdown"]["tickets"]["selected_poi_ids"] = ["poi_b", "poi_a"]
    output["tool_results"]["budget_calculator"] = _tool_result(
        "budget_calculator",
        data=output["budget"],
    )

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_BUDGET_ITINERARY_CONSISTENCY"]["status"] == "passed"
    assert rules["H_BUDGET_ITINERARY_CONSISTENCY"]["details"]["issues"] == []


def test_bpcr_accepts_order_insensitive_metadata_audit() -> None:
    output = _output()
    output["budget"] = _budget_data()
    output["tool_results"]["budget_calculator"] = _tool_result(
        "budget_calculator",
        data=output["budget"],
    )
    output["metadata"] = {
        "budget_itinerary_consistency": {
            "schema_version": "budget-itinerary-consistency-audit-v1",
            "status": "mismatched",
            "consistent": False,
            "final_itinerary_unique_poi_ids": ["poi_a", "poi_b"],
            "budget_selected_poi_ids": ["poi_b", "poi_a"],
            "ticket_source": "final_itinerary_pois",
        }
    }

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_BUDGET_ITINERARY_CONSISTENCY"]["status"] == "passed"
    assert rules["H_BUDGET_ITINERARY_CONSISTENCY"]["details"]["issues"] == []


def test_bpcr_fails_forbidden_auto_upgrade() -> None:
    output = _output()
    output["budget"] = _budget_data()
    output["budget"]["budget_policy"].update(
        {
            "upgrade_decision": "auto_upgrade_accommodation",
            "upgrade_applied": ["accommodation"],
            "hotel_tier": "premium",
        }
    )
    output["budget"]["breakdown"]["accommodation"]["tier"] = "premium"
    output["tool_results"]["budget_calculator"] = _tool_result(
        "budget_calculator",
        data=output["budget"],
    )

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_BUDGET_UPGRADE_POLICY"]["status"] == "failed"
    assert "auto_upgrade_forbidden" in rules["H_BUDGET_UPGRADE_POLICY"]["details"]["issues"]
    assert "non_explicit_hotel_tier" in rules["H_BUDGET_UPGRADE_POLICY"]["details"]["issues"]
    assert report["metrics"]["bpcr"] < 1.0


def test_bpcr_tier_policy_is_na_without_explicit_tier_constraint() -> None:
    output = _output()
    output["budget"] = _budget_data()
    output["tool_results"]["budget_calculator"] = _tool_result(
        "budget_calculator",
        data=output["budget"],
    )

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_BUDGET_UPGRADE_POLICY"]["status"] == "na"
    assert rules["H_BUDGET_UPGRADE_POLICY"]["details"]["reason"] == "no_explicit_tier_constraint"


def test_bpcr_passes_explicit_tier_preference_when_respected() -> None:
    case = _case()
    case["expected"]["input_slots"] = {"hotel_level": "comfort", "food_level": "economy"}
    output = _output()
    output["budget"] = _budget_data()
    output["budget"]["budget_policy"].update(
        {
            "upgrade_decision": "explicit_preference_applied",
            "upgrade_applied": ["accommodation"],
            "selected_scheme_id": "PREF",
            "hotel_tier": "comfort",
            "food_tier": "economy",
        }
    )
    output["budget"]["breakdown"]["accommodation"]["tier"] = "comfort"
    output["tool_results"]["budget_calculator"] = _tool_result(
        "budget_calculator",
        data=output["budget"],
    )

    report = evaluate_case(case=case, output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_BUDGET_UPGRADE_POLICY"]["status"] == "passed"


def test_poi_output_must_come_from_poi_tool_result() -> None:
    output = _output()
    output["tool_results"]["poi_search"] = _tool_result(
        "poi_search",
        data={"attractions": [{"poi_id": "poi_c", "name": "POI C"}]},
    )

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_TOOL_EVIDENCE"]["status"] == "failed"


def test_no_result_tool_cannot_support_existing_output_artifact() -> None:
    output = _output()
    output["tool_results"]["weather_query"] = _tool_result(
        "weather_query",
        data={},
        status="no_result",
    )

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["H_WEATHER_EVIDENCE"]["status"] == "failed"
    assert rules["H_TOOL_EVIDENCE"]["status"] == "failed"


def test_clarification_answer_must_ask_missing_fields() -> None:
    case = {
        "case_id": "clarification-text",
        "task_type": "clarification",
        "expected": {
            "task_type": "clarification",
            "missing_slots": ["start_date"],
            "accepted_agent_sets": [[]],
            "accepted_tool_sets": [[]],
        },
    }
    output = _output()
    output.update(
        {
            "task_type": "clarification",
            "planned_agents": [],
            "used_agents": [],
            "planned_tools": [],
            "called_tools": [],
            "tool_results": {},
            "attractions": [],
            "trip_days": None,
            "daily_itinerary": [],
            "budget": None,
            "weather": None,
            "execution_status": "clarification",
            "metadata": {"clarification_fields": ["start_date"]},
            "final_answer": "hello",
        }
    )

    report = evaluate_case(case=case, output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["T_CLARIFICATION_MISSING_FIELDS"]["status"] == "failed"
    assert rules["G_FINAL_ANSWER_CONSISTENT"]["status"] == "failed"
    assert report["metrics"]["stsr"] is False


def test_clarification_budget_amount_accepts_chinese_budget_label() -> None:
    case = {
        "case_id": "clarification-budget-amount",
        "task_type": "clarification",
        "expected": {
            "task_type": "clarification",
            "missing_slots": ["start_date", "duration_days", "budget_amount"],
            "accepted_agent_sets": [[]],
            "accepted_tool_sets": [[]],
        },
    }
    output = _output()
    output.update(
        {
            "task_type": "clarification",
            "planned_agents": [],
            "used_agents": [],
            "planned_tools": [],
            "called_tools": [],
            "tool_results": {},
            "attractions": [],
            "trip_days": None,
            "daily_itinerary": [],
            "budget": None,
            "weather": None,
            "execution_status": "clarification",
            "metadata": {
                "clarification_fields": [
                    "start_date",
                    "duration_days",
                    "budget_amount",
                ]
            },
            "final_answer": "需要先补充：出发日期、旅行天数、预算。",
        }
    )

    report = evaluate_case(case=case, output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["T_CLARIFICATION_MISSING_FIELDS"]["status"] == "passed"
    assert rules["G_FINAL_ANSWER_CONSISTENT"]["status"] == "passed"
    assert report["metrics"]["stsr"] is True


def test_agent_f1_is_zero_when_precision_and_recall_are_zero() -> None:
    output = _output()
    output["used_agents"] = ["single_agent"]

    report = evaluate_case(case=_case(), output=output)

    assert report["metrics"]["agent_selection_precision"] == 0.0
    assert report["metrics"]["agent_selection_recall"] == 0.0
    assert report["metrics"]["agent_selection_f1"] == 0.0


def test_best_accepted_agent_set_is_selected_by_f1_not_intersection_count() -> None:
    case = _case()
    case["expected"]["accepted_agent_sets"] = [
        ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"],
        ["a"],
    ]
    output = _output()
    output["used_agents"] = ["a", "b"]

    report = evaluate_case(case=case, output=output)

    assert report["metrics"]["agent_selection_f1"] == 0.6667


def test_partial_changed_slot_compares_actual_output_value() -> None:
    case = _case()
    case["task_type"] = "partial_replan"
    case["current_slots"] = {"duration_days": 3, "budget_level": "standard"}
    case["previous_state"] = {"slots": {"duration_days": 2, "budget_level": "standard"}}
    case["expected"].update({
        "task_type": "partial_replan",
        "duration_days": 3,
        "changed_slots": ["duration_days"],
        "preserved_slots": ["budget_level"],
    })
    output = _output()
    output["task_type"] = "partial_replan"
    output["trip_days"] = 2
    output["metadata"] = {"scheduler": {"ticket": {"changed_slots": ["duration_days"], "preserved_slots": ["budget_level"]}}}
    output["tool_results"]["budget_calculator"]["input"] = {"spending_level": "standard"}
    output["tool_results"]["budget_calculator"]["data"] = {"spending_level": "standard"}

    report = evaluate_case(case=case, output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["T_PARTIAL_CHANGED_SLOTS_APPLIED"]["status"] == "failed"


def test_partial_preserved_slot_compares_actual_output_value() -> None:
    case = _case()
    case["task_type"] = "partial_replan"
    case["current_slots"] = {"duration_days": 2, "budget_level": "standard"}
    case["previous_state"] = {"slots": {"duration_days": 2, "budget_level": "standard"}}
    case["expected"].update({
        "task_type": "partial_replan",
        "changed_slots": [],
        "preserved_slots": ["budget_level"],
    })
    output = _output()
    output["task_type"] = "partial_replan"
    output["metadata"] = {"scheduler": {"ticket": {"changed_slots": [], "preserved_slots": ["budget_level"]}}}
    output["tool_results"]["budget_calculator"]["input"] = {"spending_level": "luxury"}
    output["tool_results"]["budget_calculator"]["data"] = {"spending_level": "luxury"}

    report = evaluate_case(case=case, output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["T_PARTIAL_PRESERVED_SLOTS_KEPT"]["status"] == "failed"


def test_partial_preserved_slot_accepts_chinese_city_alias_and_budget_amount_metadata() -> None:
    case = _case()
    case["task_type"] = "partial_replan"
    case["previous_state"] = {
        "slots": {
            "destination": "hangzhou",
            "start_date": "2026-08-16",
            "people_count": 2,
            "budget_amount": 5300,
        }
    }
    case["expected"].update({
        "task_type": "partial_replan",
        "changed_slots": ["duration_days"],
        "preserved_slots": [
            "destination",
            "start_date",
            "people_count",
            "budget_amount",
        ],
    })
    output = _output()
    output["task_type"] = "partial_replan"
    output["metadata"] = {
        "goal_state_slots": {
            "destination": "hangzhou",
            "start_date": "2026-08-16",
            "duration_days": 3,
            "people_count": 2,
            "budget_amount": 5300,
        },
        "scheduler": {
            "ticket": {
                "changed_slots": ["duration_days"],
                "preserved_slots": [
                    "destination",
                    "start_date",
                    "people_count",
                    "budget_amount",
                ],
                "current_slots": {"budget_amount": 5300},
            }
        },
    }
    output["tool_results"]["weather_query"]["input"] = {
        "city": "杭州",
        "date": "2026-08-16",
        "days": 3,
    }
    output["tool_results"]["weather_query"]["data"] = {
        "city": "杭州",
        "daily_weather": [{"date": "2026-08-16", "state": "sunny"}],
    }
    output["tool_results"]["budget_calculator"]["input"] = {
        "city": "hangzhou",
        "people_count": 2,
        "days": 3,
    }
    output["tool_results"]["budget_calculator"]["data"] = {
        "city": "hangzhou",
        "people_count": 2,
        "days": 3,
        "total": 900,
    }

    report = evaluate_case(case=case, output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["T_PARTIAL_PRESERVED_SLOTS_KEPT"]["status"] == "passed"


def test_partial_changed_slots_accept_goal_state_preference_metadata() -> None:
    case = _case()
    case["task_type"] = "partial_replan"
    case["current_slots"] = {
        "people_count": 3,
        "traveler_group": "family",
        "preferences": ["family"],
        "special_requirements": ["low_intensity"],
    }
    case["previous_state"] = {
        "slots": {
            "people_count": 2,
            "preferences": ["history_culture"],
        }
    }
    case["expected"].update({
        "task_type": "partial_replan",
        "changed_slots": [
            "people_count",
            "traveler_group",
            "preferences",
            "special_requirements",
        ],
        "preserved_slots": [],
    })
    output = _output()
    output["task_type"] = "partial_replan"
    output["budget"] = {"people_count": 3}
    output["metadata"] = {
        "goal_state_slots": {
            "people_count": 3,
            "traveler_group": "family",
            "preferences": ["family"],
            "special_requirements": ["low_intensity"],
        },
        "scheduler": {
            "ticket": {
                "changed_slots": [
                    "people_count",
                    "traveler_group",
                    "preferences",
                    "special_requirements",
                ],
                "preserved_slots": [],
                "current_slots": {
                    "people_count": 3,
                    "traveler_group": "family",
                    "preferences": ["family"],
                    "special_requirements": ["low_intensity"],
                },
            }
        },
    }

    report = evaluate_case(case=case, output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["T_PARTIAL_CHANGED_SLOTS_APPLIED"]["status"] == "passed"


def test_weather_unaffected_itinerary_content_must_match_previous_state() -> None:
    case = _case()
    case["task_type"] = "weather_adjustment"
    case["current_slots"] = {"weather_scenario": "rainy_day_2"}
    case["previous_state"] = {
        "slots": {"duration_days": 2, "budget_level": "standard"},
        "daily_itinerary": [
            {"day": 1, "attractions": [{"poi_id": "poi_a", "name": "POI A"}]},
            {"day": 2, "attractions": [{"poi_id": "poi_b", "name": "POI B"}]},
        ],
        "budget": {"total": 900},
        "attractions": [{"poi_id": "poi_a", "name": "POI A"}, {"poi_id": "poi_b", "name": "POI B"}],
    }
    case["expected"].update({
        "task_type": "weather_adjustment",
        "changed_slots": ["weather_scenario"],
        "preserved_slots": ["budget_level"],
    })
    output = _output()
    output["task_type"] = "weather_adjustment"
    output["weather_adjustments"] = [{"day": 2, "reason": "rain"}]
    output["daily_itinerary"] = [
        {"day": 1, "attractions": [{"poi_id": "poi_c", "name": "POI C"}]},
        {"day": 2, "attractions": [{"poi_id": "poi_b", "name": "POI B"}]},
    ]
    output["attractions"] = [{"poi_id": "poi_a", "name": "POI A"}, {"poi_id": "poi_b", "name": "POI B"}]
    output["final_answer"] = "Weather rain adjustment keeps POI C and POI B. Budget total 900."

    report = evaluate_case(case=case, output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["T_WEATHER_UNAFFECTED_CONTENT_PRESERVED"]["status"] == "failed"


def test_weather_unaffected_budget_can_change_when_budget_recalculation_is_expected() -> None:
    case = _case()
    case["task_type"] = "weather_adjustment"
    case["current_slots"] = {"weather_scenario": "rainy_day_2"}
    case["previous_state"] = {
        "slots": {"duration_days": 2, "budget_level": "standard"},
        "daily_itinerary": [
            {"day": 1, "attractions": [{"poi_id": "poi_a", "name": "POI A"}]},
            {"day": 2, "attractions": [{"poi_id": "poi_b", "name": "POI B"}]},
        ],
        "budget": {"total": 900},
        "attractions": [{"poi_id": "poi_a", "name": "POI A"}, {"poi_id": "poi_b", "name": "POI B"}],
    }
    case["expected"].update({
        "task_type": "weather_adjustment",
        "required_tools": ["budget_calculator"],
        "accepted_agent_sets": [["itinerary", "budget"]],
        "partial_replan_policy": "weather_adjustment_itinerary_budget",
    })
    output = _output()
    output["task_type"] = "weather_adjustment"
    output["weather_adjustments"] = [{"day": 2, "reason": "rain"}]
    output["daily_itinerary"] = [
        {"day": 1, "attractions": [{"poi_id": "poi_a", "name": "POI A"}]},
        {"day": 2, "attractions": [{"poi_id": "poi_b", "name": "POI B"}]},
    ]
    output["budget"] = {"total": 930}
    output["attractions"] = [{"poi_id": "poi_a", "name": "POI A"}, {"poi_id": "poi_b", "name": "POI B"}]
    output["final_answer"] = "Weather rain adjustment keeps POI A and POI B. Budget total 930."

    report = evaluate_case(case=case, output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["T_WEATHER_UNAFFECTED_CONTENT_PRESERVED"]["status"] == "passed"


def test_weather_unaffected_days_can_be_derived_from_weather_adjustments() -> None:
    case = _case()
    case["task_type"] = "weather_adjustment"
    case["current_slots"] = {"weather_scenario": "high_temperature"}
    case["previous_state"] = {
        "daily_itinerary": [
            {"day": 1, "attractions": [{"poi_id": "poi_a", "name": "POI A"}]},
            {"day": 2, "attractions": [{"poi_id": "poi_b", "name": "POI B"}]},
        ],
        "budget": {"total": 900},
        "attractions": [{"poi_id": "poi_a", "name": "POI A"}, {"poi_id": "poi_b", "name": "POI B"}],
    }
    case["expected"].update({
        "task_type": "weather_adjustment",
        "required_tools": ["budget_calculator"],
        "accepted_agent_sets": [["itinerary", "budget"]],
    })
    output = _output()
    output["task_type"] = "weather_adjustment"
    output["weather_adjustments"] = [{"day": 2, "reason": "high_temperature"}]
    output["daily_itinerary"] = [
        {"day": 1, "attractions": [{"poi_id": "poi_a", "name": "POI A"}]},
        {"day": 2, "attractions": [{"poi_id": "poi_c", "name": "POI C"}]},
    ]
    output["budget"] = {"total": 930}
    output["attractions"] = [{"poi_id": "poi_a", "name": "POI A"}, {"poi_id": "poi_c", "name": "POI C"}]
    output["final_answer"] = "High-temperature adjustment changes day 2 only. Budget total 930."

    report = evaluate_case(case=case, output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["T_WEATHER_UNAFFECTED_CONTENT_PRESERVED"]["status"] == "passed"
    assert rules["T_WEATHER_UNAFFECTED_CONTENT_PRESERVED"]["details"]["affected_days"] == [2]


def test_weather_adjustment_must_cover_affected_day() -> None:
    case = _case()
    case["task_type"] = "weather_adjustment"
    case["current_slots"] = {"weather_scenario": "rainy_day_2"}
    case["expected"].update({"task_type": "weather_adjustment"})
    output = _output()
    output["task_type"] = "weather_adjustment"
    output["weather_adjustments"] = [{"day": 1, "reason": "rain"}]
    output["final_answer"] = "Weather rain adjustment keeps POI A and POI B. Budget total 900."

    report = evaluate_case(case=case, output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["T_WEATHER_AFFECTED_CONTENT_ADJUSTED"]["status"] == "failed"
    assert rules["T_WEATHER_AFFECTED_CONTENT_ADJUSTED"]["details"]["missing_days"] == [2]


def test_final_answer_must_not_be_empty_or_hallucinate_unselected_poi() -> None:
    output = _output()
    output["tool_results"]["poi_search"]["data"] = {
        "attractions": [
            {"poi_id": "poi_a", "name": "POI A"},
            {"poi_id": "poi_b", "name": "POI B"},
            {"poi_id": "poi_c", "name": "POI C"},
        ]
    }
    output["final_answer"] = "POI A, POI B and POI C are planned. Budget total 900. Weather sunny."

    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}

    assert rules["G_FINAL_ANSWER_CONSISTENT"]["status"] == "failed"
    assert "answer_mentions_unselected_poi" in rules["G_FINAL_ANSWER_CONSISTENT"]["details"]["issues"]

    output["final_answer"] = ""
    report = evaluate_case(case=_case(), output=output)
    rules = {item["id"]: item for item in report["rules"]}
    assert rules["G_FINAL_ANSWER_CONSISTENT"]["status"] == "failed"


def test_evaluation_summary_aggregates_methods_and_pairs_m3_vs_m2() -> None:
    base_output = _output()
    m2_eval = evaluate_case(case=_case(), output=base_output)
    m3_eval = evaluate_case(case=_case(), output=base_output)
    results = [
        {
            "case_id": "eval-trip-success",
            "method": "fixed_multi_agent",
            "repeat_index": 0,
            "latency_ms": 100,
            "trace": {"agent_call_count": 4, "tool_call_count": 3},
            "metrics": m2_eval["metrics"],
        },
        {
            "case_id": "eval-trip-success",
            "method": "adaptive_multi_agent",
            "repeat_index": 0,
            "latency_ms": 80,
            "trace": {"agent_call_count": 3, "tool_call_count": 2},
            "metrics": m3_eval["metrics"],
        },
    ]

    summary = summarize_evaluation_results(results)

    assert summary["schema_version"] == EVALUATION_SUMMARY_SCHEMA_VERSION
    assert summary["methods"]["fixed_multi_agent"]["stsr_rate"] == 1.0
    assert summary["methods"]["fixed_multi_agent"]["itcsr_mean"] == 1.0
    assert summary["methods"]["adaptive_multi_agent"]["tool_call_count_mean"] == 2.0
    assert summary["paired_m3_vs_m2"] == {
        "pair_count": 1,
        "stsr_rate_delta": 0.0,
        "evaluation_hcsr_delta_mean": 0.0,
        "itcsr_delta_mean": 0.0,
        "bpcr_delta_mean": 0.0,
        "agent_call_count_delta_mean": -1.0,
        "tool_call_count_delta_mean": -1.0,
    }
    assert summary["paired_statistics"]["pair_count"] == 1
    assert summary["paired_statistics"]["metrics"]["stsr"]["delta"]["bootstrap_ci_95"] == [0.0, 0.0]
    assert summary["methods"]["adaptive_multi_agent"]["descriptive_statistics"]["tool_call_count"]["median"] == 2.0


def test_evaluation_summary_records_decision_normalization_diagnostics() -> None:
    def row(
        method: str,
        *,
        status: str = "completed",
        audit: dict | None = None,
    ) -> dict:
        output = {
            "method": method,
            "execution_status": status,
            "metadata": {},
        }
        if audit is not None:
            output["metadata"]["agent_decision_audit"] = audit
        return {
            "case_id": f"case-{method}",
            "method": method,
            "repeat_index": 0,
            "status": status,
            "latency_ms": 100,
            "output": output,
            "trace": {"agent_call_count": 1, "tool_call_count": 1},
            "metrics": {
                "stsr": True,
                "evaluation_hcsr": 1.0,
                "bpcr": 1.0,
                "agent_selection_f1": 1.0,
                "tool_selection_f1": 1.0,
            },
        }

    m2_audit = {
        "attraction": {
            "reused": False,
            "decision_source": "llm",
            "decision_fallback_used": False,
            "llm_decision_error_count": 0,
        },
        "itinerary": {
            "reused": False,
            "decision_source": "deterministic_evidence_normalizer",
            "decision_fallback_used": True,
            "llm_decision_error_count": 1,
        },
        "weather": {
            "reused": True,
            "decision_source": "llm",
            "decision_fallback_used": False,
            "llm_decision_error_count": 0,
        },
    }
    m3_audit = {
        "budget": {
            "reused": False,
            "decision_source": "llm",
            "decision_fallback_used": False,
            "llm_decision_error_count": 0,
        }
    }
    results = [
        row("llm_direct"),
        row("single_agent", status="failed"),
        row("fixed_multi_agent", audit=m2_audit),
        row("adaptive_multi_agent", audit=m3_audit),
    ]

    summary = summarize_evaluation_results(results)
    diagnostics = summary["decision_normalization"]

    assert diagnostics["schema_version"] == DECISION_NORMALIZATION_DIAGNOSTIC_SCHEMA_VERSION
    assert diagnostics["result_count"] == 4
    assert diagnostics["pipeline_completion_count"] == 3
    assert diagnostics["pipeline_completion_rate"] == 0.75
    assert diagnostics["agent_decision_total"] == 3
    assert diagnostics["raw_decision_success_count"] == 2
    assert diagnostics["raw_decision_success_rate"] == 0.6667
    assert diagnostics["normalizer_recovery_count"] == 1
    assert diagnostics["normalizer_recovery_rate"] == 0.3333
    assert diagnostics["by_method"]["llm_direct"]["agent_decision_total"] == 0
    assert diagnostics["by_method"]["single_agent"]["pipeline_completion_rate"] == 0.0
    assert diagnostics["by_method"]["fixed_multi_agent"]["normalizer_recovery_count"] == 1
    assert summary["methods"]["fixed_multi_agent"]["raw_decision_success_rate"] == 0.5
    assert summary["methods"]["adaptive_multi_agent"]["decision_normalization"][
        "raw_decision_success_count"
    ] == 1


def test_evaluation_summary_can_recompute_task_f_decision_normalizer_counts() -> None:
    path = (
        ROOT
        / "experiments"
        / "results"
        / "task_f_multiturn_real_api"
        / "task_f_multiturn_real_api_full_recheck_20260822T170309Z"
        / "benchmark_results.json"
    )
    if not path.exists():
        return
    results = json.loads(path.read_text(encoding="utf-8"))

    summary = summarize_evaluation_results(results)
    diagnostics = summary["decision_normalization"]

    assert diagnostics["agent_decision_total"] == 76
    assert diagnostics["raw_decision_success_count"] == 37
    assert diagnostics["normalizer_recovery_count"] == 39
    assert diagnostics["raw_decision_success_rate"] == 0.4868
    assert diagnostics["normalizer_recovery_rate"] == 0.5132
    assert diagnostics["pipeline_completion_rate"] == 1.0


def test_evaluation_summary_adds_paper_statistics_for_paired_results() -> None:
    results = []
    rows = [
        ("c1", False, True, 0.7, 0.8, 4, 3),
        ("c2", True, True, 0.9, 0.9, 4, 2),
        ("c3", True, False, 0.8, 0.6, 4, 4),
    ]
    for case_id, m2_stsr, m3_stsr, m2_hcsr, m3_hcsr, m2_agents, m3_agents in rows:
        results.extend(
            [
                {
                    "case_id": case_id,
                    "method": "fixed_multi_agent",
                    "repeat_index": 0,
                    "latency_ms": 100,
                    "trace": {"agent_call_count": m2_agents, "tool_call_count": 3},
                    "metrics": {
                        "stsr": m2_stsr,
                        "evaluation_hcsr": m2_hcsr,
                        "agent_selection_f1": 1.0,
                        "tool_selection_f1": 1.0,
                    },
                },
                {
                    "case_id": case_id,
                    "method": "adaptive_multi_agent",
                    "repeat_index": 0,
                    "latency_ms": 80,
                    "trace": {"agent_call_count": m3_agents, "tool_call_count": 2},
                    "metrics": {
                        "stsr": m3_stsr,
                        "evaluation_hcsr": m3_hcsr,
                        "agent_selection_f1": 1.0,
                        "tool_selection_f1": 1.0,
                    },
                },
            ]
        )

    summary = summarize_evaluation_results(results)
    stats = summary["paired_statistics"]["metrics"]

    assert stats["stsr"]["mcnemar"] == {
        "m3_only_success": 1,
        "m2_only_success": 1,
        "discordant_pairs": 2,
        "p_value": 1.0,
        "method": "exact_binomial_two_sided",
    }
    assert stats["evaluation_hcsr"]["delta"]["mean"] == -0.0333
    assert stats["evaluation_hcsr"]["delta"]["median"] == 0.0
    assert stats["evaluation_hcsr"]["delta"]["iqr"] == [-0.1, 0.05]
    assert stats["evaluation_hcsr"]["wilcoxon_signed_rank"]["method"] == "exact_signed_rank"
    assert stats["agent_call_count"]["delta"]["median"] == -1.0


def test_evaluation_summary_aggregates_repeats_by_case_before_pairing() -> None:
    results = []
    for case_id in ("c1", "c2"):
        for repeat_index in range(3):
            results.extend(
                [
                    {
                        "case_id": case_id,
                        "method": "fixed_multi_agent",
                        "repeat_index": repeat_index,
                        "latency_ms": 100 + repeat_index,
                        "trace": {"agent_call_count": 4, "tool_call_count": 3},
                        "metrics": {
                            "stsr": repeat_index != 2,
                            "evaluation_hcsr": 0.8,
                            "agent_selection_f1": 1.0,
                            "tool_selection_f1": 1.0,
                            "agent_set_exact_match": True,
                            "tool_set_exact_match": True,
                        },
                    },
                    {
                        "case_id": case_id,
                        "method": "adaptive_multi_agent",
                        "repeat_index": repeat_index,
                        "latency_ms": 80 + repeat_index,
                        "trace": {"agent_call_count": 3, "tool_call_count": 2},
                        "metrics": {
                            "stsr": True,
                            "evaluation_hcsr": 0.9,
                            "agent_selection_f1": 1.0,
                            "tool_selection_f1": 1.0,
                            "agent_set_exact_match": True,
                            "tool_set_exact_match": True,
                        },
                    },
                ]
            )

    summary = summarize_evaluation_results(results)

    assert summary["result_count"] == 12
    assert summary["raw_run_count"] == 12
    assert summary["unique_case_count"] == 2
    assert summary["method_case_count"] == 4
    assert summary["independent_case_count"] == 2
    assert summary["methods"]["fixed_multi_agent"]["case_count"] == 2
    assert summary["methods"]["fixed_multi_agent"]["raw_run_count"] == 6
    assert summary["paired_statistics"]["pair_count"] == 2
    assert summary["paired_m3_vs_m2"]["pair_count"] == 2


def test_forbidden_tool_call_count_counts_calls_not_tool_types() -> None:
    case = {
        "case_id": "forbidden-repeat",
        "task_type": "general_chat",
        "expected": {
            "task_type": "general_chat",
            "accepted_agent_sets": [[]],
            "accepted_tool_sets": [[]],
            "forbidden_tools": ["poi_search"],
        },
    }
    output = _output()
    output.update(
        {
            "task_type": "general_chat",
            "planned_agents": [],
            "used_agents": [],
            "planned_tools": [],
            "called_tools": [_tool_call("poi_search"), _tool_call("poi_search"), _tool_call("poi_search")],
            "tool_results": {},
            "attractions": [],
            "trip_days": None,
            "daily_itinerary": [],
            "budget": None,
            "weather": None,
            "final_answer": "Hello.",
        }
    )

    report = evaluate_case(case=case, output=output)

    assert report["metrics"]["forbidden_tool_call_count"] == 3


def test_render_paper_tables_uses_summary_statistics() -> None:
    summary = {
        "methods": {
            "fixed_multi_agent": {
                "case_count": 2,
                "stsr_rate": 0.5,
                "evaluation_hcsr_mean": 0.8,
                "agent_selection_f1_mean": 1.0,
                "tool_selection_f1_mean": 1.0,
                "latency_ms_mean": 120,
                "agent_call_count_mean": 4,
                "tool_call_count_mean": 3,
            },
            "adaptive_multi_agent": {
                "case_count": 2,
                "stsr_rate": 1.0,
                "evaluation_hcsr_mean": 0.9,
                "agent_selection_f1_mean": 1.0,
                "tool_selection_f1_mean": 1.0,
                "latency_ms_mean": 90,
                "agent_call_count_mean": 2,
                "tool_call_count_mean": 2,
            },
        },
        "paired_statistics": {
            "metrics": {
                "stsr": {
                    "pair_count": 2,
                    "m3": {"mean": 1.0},
                    "m2": {"mean": 0.5},
                    "delta": {"mean": 0.5, "median": 0.5, "iqr": [0.0, 1.0], "bootstrap_ci_95": [0.0, 1.0]},
                    "mcnemar": {"p_value": 1.0},
                }
            }
        },
    }

    table = render_paper_tables(summary)

    assert "M2 Fixed Template Multi-Agent" in table
    assert "M3 Proposed" in table
    assert "McNemar" in table
    assert "[0.0, 1.0]" in table
