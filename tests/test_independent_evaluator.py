from copy import deepcopy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.independent_evaluator import (
    EVALUATION_SCHEMA_VERSION,
    EVALUATION_SUMMARY_SCHEMA_VERSION,
    evaluate_case,
    render_paper_tables,
    summarize_evaluation_results,
)
from app.schemas.experiment import EXPERIMENT_OUTPUT_SCHEMA_VERSION
from app.tools.research_tools import GENERATION_TOOL_NAMES


def _tool_result(name: str, success: bool = True, data: dict | None = None, status: str | None = None) -> dict:
    if data is None:
        data = {
            "poi_search": {"attractions": [{"poi_id": "poi_a", "name": "POI A"}, {"poi_id": "poi_b", "name": "POI B"}]},
            "weather_query": {"daily_weather": [{"state": "sunny"}]},
            "budget_calculator": {"total": 900},
        }.get(name, {"value": "ok"})
    return {
        "schema_version": "research_tool_result_v1",
        "tool_name": name,
        "status": status or ("success" if success else "failed"),
        "success": success,
        "data": data,
        "metadata": {"offline": True},
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
        "budget": {"total": 900},
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


def test_independent_evaluator_scores_one_case_against_frozen_rules() -> None:
    report = evaluate_case(case=_case(), output=_output(), trace={})

    assert report["schema_version"] == EVALUATION_SCHEMA_VERSION
    assert report["catalog_id"] == "day5_independent_evaluator_rules"
    assert report["case_id"] == "eval-trip-success"
    assert len(report["rules"]) == 35
    assert report["metrics"]["stsr"] is True
    assert report["metrics"]["evaluation_hcsr"] == 1.0
    assert report["metrics"]["agent_selection_f1"] == 1.0
    assert report["metrics"]["tool_selection_f1"] == 1.0


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
    assert summary["methods"]["adaptive_multi_agent"]["tool_call_count_mean"] == 2.0
    assert summary["paired_m3_vs_m2"] == {
        "pair_count": 1,
        "stsr_rate_delta": 0.0,
        "evaluation_hcsr_delta_mean": 0.0,
        "agent_call_count_delta_mean": -1.0,
        "tool_call_count_delta_mean": -1.0,
    }
    assert summary["paired_statistics"]["pair_count"] == 1
    assert summary["paired_statistics"]["metrics"]["stsr"]["delta"]["bootstrap_ci_95"] == [0.0, 0.0]
    assert summary["methods"]["adaptive_multi_agent"]["descriptive_statistics"]["tool_call_count"]["median"] == 2.0


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

    assert "M2 Fixed Multi-Agent" in table
    assert "M3 Proposed" in table
    assert "McNemar" in table
    assert "[0.0, 1.0]" in table
