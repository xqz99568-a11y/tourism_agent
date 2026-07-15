"""Tests for the unified goal-decision contract."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.goal_decision import GoalDecision, GoalRoute  # noqa: E402
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
    decision = GoalDecision(
        intent=IntentType.TRIP_PLANNING,
        route=GoalRoute.FULL_NEW_PLAN,
        slots={"destination": "杭州", "duration": 3},
        changed_slots={"duration": 3},
        missing_fields=["budget"],
        selected_agents=["planner"],
        selected_tools=["weather"],
        requires_clarification=True,
        decision_reason="missing_budget",
    )

    assert decision.intent is IntentType.TRIP_PLANNING
    assert decision.route is GoalRoute.FULL_NEW_PLAN
    assert decision.slots == {"destination": "杭州", "duration": 3}
    assert decision.changed_slots == {"duration": 3}
    assert decision.missing_fields == ["budget"]
    assert decision.selected_agents == ["planner"]
    assert decision.selected_tools == ["weather"]
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
