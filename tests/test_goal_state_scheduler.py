import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.goal_state_scheduler import (
    DECISION_SCHEMA_VERSION,
    TICKET_SCHEMA_VERSION,
    build_goal_state_ticket,
    normalize_slots,
    schedule_goal_state_ticket,
)


def _successful_previous_state(
    slots: dict,
    *,
    agents: tuple[str, ...] = ("attraction", "weather", "itinerary", "budget"),
) -> dict:
    city = slots.get("destination") or "hangzhou"
    start_date = slots.get("start_date") or "2026-08-01"
    days = slots.get("duration_days") or 2
    people_count = slots.get("people_count") or 2
    preferences = slots.get("preferences") or []
    traveler_group = slots.get("traveler_group") or "general"
    state = {
        "slots": dict(slots),
        "available_results": {agent: True for agent in agents},
        "tool_results": {},
    }
    if "attraction" in agents:
        state["tool_results"]["poi_search"] = {
            "tool_name": "poi_search",
            "status": "success",
            "success": True,
            "input": {
                "city": city,
                "preferences": preferences,
                "people": traveler_group,
                "limit": 4,
            },
            "data": {
                "attractions": [
                    {"poi_id": f"{city}-poi-1", "name": "POI 1", "city": city}
                ]
            },
        }
    if "weather" in agents:
        state["tool_results"]["weather_query"] = {
            "tool_name": "weather_query",
            "status": "success",
            "success": True,
            "input": {"city": city, "date": start_date, "days": days},
            "data": {"daily_weather": [{"date": start_date, "condition": "sunny"}]},
        }
    if "budget" in agents:
        state["tool_results"]["budget_calculator"] = {
            "tool_name": "budget_calculator",
            "status": "success",
            "success": True,
            "input": {
                "city": city,
                "days": days,
                "people_count": people_count,
                "attractions": [f"{city}-poi-1"],
            },
            "data": {"total": 1000},
        }
    if "itinerary" in agents:
        state["daily_itinerary"] = [
            {"day": 1, "attractions": [{"poi_id": f"{city}-poi-1"}]}
        ]
    return state


def test_goal_state_ticket_matches_day4_acceptance_cases() -> None:
    acceptance_path = ROOT / "experiments" / "day4_scheduler_acceptance_cases.json"
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))

    assert acceptance["ticket_schema_version"] == TICKET_SCHEMA_VERSION

    for case in acceptance["cases"]:
        ticket = build_goal_state_ticket(
            user_input=case["user_input"],
            current_slots=case.get("current_slots"),
            previous_state=case.get("previous_state"),
        ).to_dict()
        expected = case["expected_ticket"]

        for field, expected_value in expected.items():
            assert ticket[field] == expected_value, f"{case['case_id']} {field}"


def test_goal_state_scheduler_matches_day4_acceptance_cases() -> None:
    acceptance_path = ROOT / "experiments" / "day4_scheduler_acceptance_cases.json"
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))

    assert acceptance["decision_schema_version"] == DECISION_SCHEMA_VERSION

    for case in acceptance["cases"]:
        ticket = build_goal_state_ticket(
            user_input=case["user_input"],
            current_slots=case.get("current_slots"),
            previous_state=case.get("previous_state"),
        )
        decision = schedule_goal_state_ticket(
            ticket,
            previous_state=case.get("previous_state"),
        ).to_dict()
        expected = case["expected_decision"]

        for field, expected_value in expected.items():
            assert decision[field] == expected_value, f"{case['case_id']} {field}"


def test_goal_state_ticket_merges_previous_state_when_current_turn_only_has_changes() -> None:
    ticket = build_goal_state_ticket(
        user_input="目的地改成桂林，其他条件不变，重新做完整计划。",
        current_slots={"city": "桂林"},
        previous_state={
            "slots": {
                "destination": "杭州",
                "date": "2026-09-01",
                "days": "3",
                "people": "2",
                "traveler_type": "adult",
                "spending_level": "standard",
                "interests": ["classic"],
            }
        },
    )

    assert ticket.current_slots == {
        "destination": "guilin",
        "start_date": "2026-09-01",
        "duration_days": 3,
        "people_count": 2,
        "traveler_group": "adult",
        "budget_level": "standard",
        "preferences": ["classic"],
    }
    assert ticket.changed_slots == ["destination"]
    assert ticket.preserved_slots == [
        "start_date",
        "duration_days",
        "people_count",
        "traveler_group",
        "budget_level",
        "preferences",
    ]
    assert ticket.task_type == "partial_replan"


def test_partial_replan_combines_date_and_people_changes() -> None:
    previous_state = _successful_previous_state(
        {
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
            "preferences": ["classic"],
        }
    )

    ticket = build_goal_state_ticket(
        user_input="日期和人数都改一下，其他不变",
        current_slots={"start_date": "2026-08-05", "people_count": 3},
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert ticket.changed_slots == ["start_date", "people_count"]
    assert decision.planned_agents == ["weather", "itinerary", "budget"]
    assert decision.reused_agents == ["attraction"]
    assert decision.invalidated_agents == ["weather", "itinerary", "budget"]
    assert decision.decision_reasons == [
        "date_changed_weather_replan",
        "people_count_changed_budget_only",
    ]


def test_partial_replan_combines_duration_and_preference_changes() -> None:
    previous_state = _successful_previous_state(
        {
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
            "preferences": ["classic"],
        }
    )

    ticket = build_goal_state_ticket(
        user_input="改成三天，并且多安排自然风光景点",
        current_slots={"duration_days": 3, "preferences": ["nature"]},
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert ticket.changed_slots == ["duration_days", "preferences"]
    assert decision.planned_agents == ["attraction", "weather", "itinerary", "budget"]
    assert decision.reused_agents == []
    assert decision.invalidated_agents == ["attraction", "weather", "itinerary", "budget"]
    assert decision.decision_reasons == [
        "duration_changed_partial_replan",
        "preferences_changed_replan",
    ]


def test_goal_shift_without_slot_change_is_not_identical_reuse() -> None:
    previous_state = _successful_previous_state(
        {
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
        }
    )

    chat_ticket = build_goal_state_ticket(
        user_input="谢谢，今天心情不错。",
        current_slots={},
        previous_state=previous_state,
    )
    chat_decision = schedule_goal_state_ticket(chat_ticket, previous_state=previous_state)
    assert chat_ticket.task_type == "general_chat"
    assert chat_decision.planned_agents == []
    assert chat_decision.reused_agents == []

    more_poi_ticket = build_goal_state_ticket(
        user_input="再推荐几个景点。",
        current_slots={},
        previous_state=previous_state,
    )
    more_poi_decision = schedule_goal_state_ticket(
        more_poi_ticket,
        previous_state=previous_state,
    )
    assert more_poi_ticket.task_type == "attraction_recommendation"
    assert more_poi_decision.planned_agents == ["attraction"]
    assert more_poi_decision.reused_agents == []

    redo_ticket = build_goal_state_ticket(
        user_input="重新做一版。",
        current_slots={},
        previous_state=previous_state,
    )
    redo_decision = schedule_goal_state_ticket(redo_ticket, previous_state=previous_state)
    assert redo_ticket.task_type == "partial_replan"
    assert redo_decision.planned_agents == ["attraction", "weather", "itinerary", "budget"]
    assert redo_decision.reused_agents == []
    assert redo_decision.decision_reasons == ["explicit_replan_requested"]


def test_dependency_cascade_removes_agents_from_reuse_set() -> None:
    failed_poi = {
        "tool_name": "poi_search",
        "status": "failed",
        "success": False,
        "input": {"city": "hangzhou", "preferences": ["classic"], "people": "adult"},
        "data": {},
        "error": {"message": "previous attraction failed"},
    }
    previous_state = {
        "slots": {
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
            "traveler_group": "adult",
            "preferences": ["classic"],
        },
        "available_results": {
            "attraction": True,
            "weather": True,
            "itinerary": True,
            "budget": True,
        },
        "tool_results": {
            "poi_search": failed_poi,
            "weather_query": {
                "tool_name": "weather_query",
                "status": "success",
                "success": True,
                "input": {"city": "hangzhou", "date": "2026-08-01", "days": 2},
                "data": {},
            },
            "budget_calculator": {
                "tool_name": "budget_calculator",
                "status": "success",
                "success": True,
                "input": {"city": "hangzhou", "days": 2, "people_count": 2},
                "data": {},
            },
        },
        "daily_itinerary": [{"day": 1, "reuse_marker": "old-itinerary"}],
    }

    ticket = build_goal_state_ticket(
        user_input="same plan again",
        current_slots={},
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert decision.planned_agents == ["attraction", "itinerary", "budget"]
    assert decision.reused_agents == ["weather"]
    assert decision.invalidated_agents == ["attraction", "itinerary", "budget"]
    assert not set(decision.reused_agents) & set(decision.planned_agents)
    assert not set(decision.reused_agents) & set(decision.invalidated_agents)


def test_budget_query_requires_reusable_attraction_upstream() -> None:
    previous_state = _successful_previous_state(
        {
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
        },
        agents=("weather",),
    )

    ticket = build_goal_state_ticket(
        user_input="how much will the budget cost for four people",
        current_slots={"people_count": 4},
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert ticket.task_type == "budget_query"
    assert decision.planned_agents == ["attraction", "budget"]
    assert decision.reused_agents == []


def test_identical_request_with_only_budget_result_replans_full_plan() -> None:
    previous_state = _successful_previous_state(
        {
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
        },
        agents=("budget",),
    )

    ticket = build_goal_state_ticket(
        user_input="same plan again",
        current_slots={},
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert decision.planned_agents == ["attraction", "weather", "itinerary", "budget"]
    assert decision.reused_agents == []
    assert "identical_request_incomplete_previous_state_replan" in decision.decision_reasons
    assert "dependent_result_invalidated" in decision.decision_reasons


def test_available_markers_without_artifacts_are_not_reusable() -> None:
    previous_state = {
        "slots": {
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
        },
        "available_results": {
            "attraction": True,
            "weather": True,
            "itinerary": True,
            "budget": True,
        },
    }

    ticket = build_goal_state_ticket(
        user_input="same plan again",
        current_slots={},
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert decision.planned_agents == ["attraction", "weather", "itinerary", "budget"]
    assert decision.reused_agents == []
    assert decision.reuse_validation["raw_available_agents"] == []


def test_expired_previous_result_is_not_reusable() -> None:
    previous_state = _successful_previous_state(
        {
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
        },
        agents=("attraction",),
    )
    previous_state["tool_results"]["poi_search"]["status"] = "expired"

    ticket = build_goal_state_ticket(
        user_input="change it to three days",
        current_slots={"duration_days": 3},
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert "attraction" not in decision.reused_agents
    assert "attraction" in decision.planned_agents
    assert decision.reuse_validation["unusable_reasons"]["attraction"] == (
        "previous_result_failed"
    )


def test_empty_preferences_and_none_budget_are_explicit_slot_changes() -> None:
    previous_state = _successful_previous_state(
        {
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
            "preferences": ["classic"],
            "budget_amount": 1000,
        }
    )

    ticket = build_goal_state_ticket(
        user_input="remove the preference and budget limit",
        current_slots={"preferences": [], "budget": None},
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert ticket.current_slots["preferences"] == []
    assert ticket.current_slots["budget_amount"] is None
    assert ticket.changed_slots == ["budget_amount", "preferences"]
    assert decision.planned_agents == ["attraction", "itinerary", "budget"]
    assert decision.reused_agents == ["weather"]


def test_regenerate_wins_over_same_condition_terms() -> None:
    previous_state = _successful_previous_state(
        {
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
        }
    )

    ticket = build_goal_state_ticket(
        user_input="same conditions, regenerate a new version",
        current_slots={},
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert ticket.goal_change_type == "explicit_replan"
    assert decision.planned_agents == ["attraction", "weather", "itinerary", "budget"]
    assert decision.reused_agents == []
    assert decision.decision_reasons == ["explicit_replan_requested"]


def test_normalize_slots_ignores_empty_values_and_unknown_fields() -> None:
    assert normalize_slots(
        {
            "destination": " 北京 ",
            "duration": "3",
            "people_count": None,
            "preferences": ["classic", "", "classic"],
            "unknown": "ignored",
        }
    ) == {
        "destination": "beijing",
        "duration_days": 3,
        "preferences": ["classic"],
    }
