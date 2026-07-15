"""Tests for the unified goal-decision contract."""

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.goal_decision import (  # noqa: E402
    AGENT_TOOL_MAP,
    GoalDecision,
    GoalRoute,
    select_agents,
    tools_for_agents,
)
from app.schemas import IntentType  # noqa: E402


def test_goal_route_values() -> None:
    assert {route.value for route in GoalRoute} == {
        "FULL_NEW_PLAN",
        "CLARIFICATION_ANSWER",
        "FOLLOW_UP",
        "DIRECT_TASK",
        "GENERAL_CHAT",
        "INCOMPLETE_PLANNING",
    }


def test_goal_decision_field_construction() -> None:
    selected_agents = select_agents(
        IntentType.TRIP_PLANNING,
        GoalRoute.FULL_NEW_PLAN,
        {"destination": "杭州"},
    )
    decision = GoalDecision(
        intent=IntentType.TRIP_PLANNING,
        route=GoalRoute.FULL_NEW_PLAN,
        slots={"destination": "杭州", "duration": 3},
        changed_slots={"duration": 3},
        missing_fields=["budget"],
        selected_agents=selected_agents,
        selected_tools=tools_for_agents(selected_agents),
        requires_clarification=True,
        decision_reason="missing_budget",
    )

    assert decision.intent is IntentType.TRIP_PLANNING
    assert decision.route is GoalRoute.FULL_NEW_PLAN
    assert decision.slots == {"destination": "杭州", "duration": 3}
    assert decision.changed_slots == {"duration": 3}
    assert decision.missing_fields == ["budget"]
    assert decision.selected_agents == [
        "attraction",
        "weather",
        "itinerary",
        "budget",
    ]
    assert decision.selected_tools == [
        "poi_search",
        "poi_detail",
        "weather_query",
        "route_planning",
        "budget_calculator",
    ]
    assert decision.requires_clarification is True
    assert decision.decision_reason == "missing_budget"


def test_to_trace_dict_is_json_serializable() -> None:
    decision = GoalDecision(
        intent=IntentType.WEATHER_ADJUSTMENT,
        route=GoalRoute.FOLLOW_UP,
        slots={"destination": "北京"},
    )

    serialized = json.dumps(decision.to_trace_dict(), ensure_ascii=False)

    assert '"destination": "北京"' in serialized


def test_to_trace_dict_converts_enums_to_strings() -> None:
    trace_dict = GoalDecision(
        intent=IntentType.GENERAL_CHAT,
        route=GoalRoute.GENERAL_CHAT,
    ).to_trace_dict()

    assert trace_dict["intent"] == "general_chat"
    assert type(trace_dict["intent"]) is str
    assert trace_dict["route"] == "GENERAL_CHAT"
    assert type(trace_dict["route"]) is str


def test_to_trace_dict_recursively_serializes_nested_values() -> None:
    decision = GoalDecision(
        intent=IntentType.TRIP_PLANNING,
        route=GoalRoute.FULL_NEW_PLAN,
        slots={
            "travel": {
                "start_date": date(2026, 7, 20),
                "events": [
                    {
                        "at": datetime(
                            2026,
                            7,
                            20,
                            9,
                            30,
                            tzinfo=timezone.utc,
                        ),
                        "intent": IntentType.ATTRACTION_RECOMMENDATION,
                    }
                ],
            }
        },
    )

    trace_dict = decision.to_trace_dict()
    serialized = json.dumps(trace_dict, ensure_ascii=False)

    assert trace_dict["slots"]["travel"]["start_date"] == "2026-07-20"
    assert trace_dict["slots"]["travel"]["events"] == [
        {
            "at": "2026-07-20T09:30:00+00:00",
            "intent": "attraction_recommendation",
        }
    ]
    assert "2026-07-20T09:30:00+00:00" in serialized


def test_agent_tool_map_is_complete() -> None:
    assert AGENT_TOOL_MAP == {
        "attraction": ["poi_search", "poi_detail"],
        "weather": ["weather_query"],
        "itinerary": ["route_planning"],
        "budget": ["budget_calculator"],
    }


def test_tools_for_agents_uses_unified_mapping() -> None:
    assert tools_for_agents(
        ["attraction", "weather", "itinerary", "budget"]
    ) == [
        "poi_search",
        "poi_detail",
        "weather_query",
        "route_planning",
        "budget_calculator",
    ]


@pytest.mark.parametrize(
    ("intent", "route", "changed_slots", "expected_agents"),
    [
        (
            IntentType.TRIP_PLANNING,
            GoalRoute.FULL_NEW_PLAN,
            {},
            ["attraction", "weather", "itinerary", "budget"],
        ),
        (
            IntentType.ATTRACTION_RECOMMENDATION,
            GoalRoute.DIRECT_TASK,
            {},
            ["attraction"],
        ),
        (
            IntentType.TRIP_PLANNING,
            GoalRoute.CLARIFICATION_ANSWER,
            {},
            ["attraction", "weather", "itinerary", "budget"],
        ),
        (
            IntentType.TRIP_PLANNING,
            GoalRoute.INCOMPLETE_PLANNING,
            {},
            ["attraction", "weather", "itinerary", "budget"],
        ),
        (
            IntentType.BUDGET_CONTROL,
            GoalRoute.FOLLOW_UP,
            {"budget_amount": 3000},
            ["budget"],
        ),
        (
            IntentType.TRIP_PLANNING,
            GoalRoute.FOLLOW_UP,
            {"duration_days": 5},
            ["itinerary", "budget"],
        ),
        (
            IntentType.WEATHER_ADJUSTMENT,
            GoalRoute.FOLLOW_UP,
            {},
            ["weather", "itinerary"],
        ),
        (
            IntentType.TRIP_PLANNING,
            GoalRoute.FOLLOW_UP,
            {"interests": ["博物馆"]},
            ["attraction", "itinerary"],
        ),
        (
            IntentType.TRIP_PLANNING,
            GoalRoute.FOLLOW_UP,
            {"preferences": ["轻松"]},
            ["attraction", "itinerary"],
        ),
        (
            IntentType.GENERAL_CHAT,
            GoalRoute.GENERAL_CHAT,
            {},
            [],
        ),
    ],
)
def test_select_agents_policy(
    intent: IntentType,
    route: GoalRoute,
    changed_slots: dict[str, object],
    expected_agents: list[str],
) -> None:
    selected_agents = select_agents(intent, route, changed_slots)

    assert selected_agents == expected_agents
    assert tools_for_agents(selected_agents) == [
        tool
        for agent in expected_agents
        for tool in AGENT_TOOL_MAP[agent]
    ]


@pytest.mark.parametrize(
    ("intent", "expected_agents"),
    [
        (
            IntentType.TRIP_PLANNING,
            ["attraction", "weather", "itinerary", "budget"],
        ),
        (IntentType.ATTRACTION_RECOMMENDATION, ["attraction"]),
        (IntentType.BUDGET_CONTROL, ["budget"]),
        (IntentType.WEATHER_ADJUSTMENT, ["weather", "itinerary"]),
    ],
)
def test_clarification_answer_selects_agents_for_intent(
    intent: IntentType,
    expected_agents: list[str],
) -> None:
    assert select_agents(intent, GoalRoute.CLARIFICATION_ANSWER, {}) == (
        expected_agents
    )


@pytest.mark.parametrize(
    ("intent", "expected_agents"),
    [
        (
            IntentType.TRIP_PLANNING,
            ["attraction", "weather", "itinerary", "budget"],
        ),
        (IntentType.ATTRACTION_RECOMMENDATION, ["attraction"]),
        (IntentType.ROUTE_CONSULTATION, ["attraction"]),
        (IntentType.BUDGET_CONTROL, ["budget"]),
        (IntentType.WEATHER_ADJUSTMENT, ["weather", "itinerary"]),
        (
            IntentType.ITINERARY_PLANNING,
            ["attraction", "itinerary"],
        ),
    ],
)
def test_incomplete_planning_preserves_planned_agents_for_intent(
    intent: IntentType,
    expected_agents: list[str],
) -> None:
    assert select_agents(intent, GoalRoute.INCOMPLETE_PLANNING, {}) == (
        expected_agents
    )


@pytest.mark.parametrize(
    ("intent", "expected_agents"),
    [
        (IntentType.ATTRACTION_RECOMMENDATION, ["attraction"]),
        (IntentType.ROUTE_CONSULTATION, ["attraction"]),
        (IntentType.BUDGET_CONTROL, ["budget"]),
        (IntentType.WEATHER_ADJUSTMENT, ["weather", "itinerary"]),
        (
            IntentType.ITINERARY_PLANNING,
            ["attraction", "itinerary"],
        ),
    ],
)
def test_direct_task_selects_agents_for_intent(
    intent: IntentType,
    expected_agents: list[str],
) -> None:
    assert select_agents(intent, GoalRoute.DIRECT_TASK, {}) == expected_agents


@pytest.mark.parametrize(
    ("changed_slots", "expected_agents"),
    [
        (
            {"budget_amount": 3000, "interests": ["博物馆"]},
            ["attraction", "itinerary", "budget"],
        ),
        (
            {"duration_days": 5, "preferences": ["轻松"]},
            ["attraction", "itinerary", "budget"],
        ),
        (
            {"start_date": "2026-08-01", "end_date": "2026-08-05"},
            ["weather", "itinerary"],
        ),
        (
            {"destination": "杭州"},
            ["attraction", "weather", "itinerary", "budget"],
        ),
    ],
)
def test_follow_up_unions_agents_for_multiple_changed_slots(
    changed_slots: dict[str, object],
    expected_agents: list[str],
) -> None:
    assert select_agents(
        IntentType.TRIP_PLANNING,
        GoalRoute.FOLLOW_UP,
        changed_slots,
    ) == expected_agents


def test_mutable_defaults_are_not_shared() -> None:
    first = GoalDecision(IntentType.UNKNOWN, GoalRoute.DIRECT_TASK)
    second = GoalDecision(IntentType.UNKNOWN, GoalRoute.DIRECT_TASK)

    first.slots["topic"] = "food"
    first.changed_slots["topic"] = "food"
    first.missing_fields.append("destination")
    first.selected_agents.append("planner")
    first.selected_tools.append("search")

    assert second.slots == {}
    assert second.changed_slots == {}
    assert second.missing_fields == []
    assert second.selected_agents == []
    assert second.selected_tools == []
