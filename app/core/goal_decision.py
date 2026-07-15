"""Unified goal-decision data structures.

This module defines the decision contract only. It is intentionally independent
from orchestration and tracing so it can be adopted without changing runtime
behaviour.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any

from app.schemas import IntentType


AGENT_TOOL_MAP: dict[str, list[str]] = {
    "attraction": ["poi_search", "poi_detail"],
    "weather": ["weather_query"],
    "itinerary": ["route_planning"],
    "budget": ["budget_calculator"],
}

_FULL_PLAN_AGENTS = ["attraction", "weather", "itinerary", "budget"]
_BUDGET_SLOTS = frozenset({"budget", "budget_amount", "budget_level"})
_DURATION_SLOTS = frozenset({"duration", "duration_days", "travel_time"})
_PREFERENCE_SLOTS = frozenset(
    {
        "interests",
        "preferences",
        "travel_styles",
        "special_requirements",
        "pace",
        "pace_preference",
    }
)


class GoalRoute(str, Enum):
    """High-level route selected for the current user goal."""

    FULL_NEW_PLAN = "FULL_NEW_PLAN"
    CLARIFICATION_ANSWER = "CLARIFICATION_ANSWER"
    FOLLOW_UP = "FOLLOW_UP"
    DIRECT_TASK = "DIRECT_TASK"
    GENERAL_CHAT = "GENERAL_CHAT"
    INCOMPLETE_PLANNING = "INCOMPLETE_PLANNING"


def select_agents(
    intent: IntentType,
    route: GoalRoute,
    changed_slots: dict[str, Any],
) -> list[str]:
    """Select agents deterministically without invoking runtime components."""

    if route == GoalRoute.GENERAL_CHAT:
        return []

    if route == GoalRoute.FULL_NEW_PLAN:
        return list(_FULL_PLAN_AGENTS)

    if (
        route == GoalRoute.DIRECT_TASK
        and intent == IntentType.ATTRACTION_RECOMMENDATION
    ):
        return ["attraction"]

    if route != GoalRoute.FOLLOW_UP:
        return []

    changed_slot_names = set(changed_slots)

    if intent == IntentType.WEATHER_ADJUSTMENT:
        return ["weather", "itinerary"]

    if changed_slot_names and changed_slot_names <= _BUDGET_SLOTS:
        return ["budget"]

    if changed_slot_names & _DURATION_SLOTS:
        return ["itinerary", "budget"]

    if changed_slot_names & _PREFERENCE_SLOTS:
        return ["attraction", "itinerary"]

    return []


def tools_for_agents(selected_agents: list[str]) -> list[str]:
    """Return the ordered, de-duplicated tools owned by selected agents."""

    selected_tools: list[str] = []
    for agent in selected_agents:
        for tool in AGENT_TOOL_MAP.get(agent, []):
            if tool not in selected_tools:
                selected_tools.append(tool)
    return selected_tools


def _to_json_compatible(value: Any) -> Any:
    """Recursively convert supported contract values to JSON-safe values."""

    if isinstance(value, Enum):
        return _to_json_compatible(value.value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            _to_json_compatible(key): _to_json_compatible(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_to_json_compatible(item) for item in value]
    return value


@dataclass
class GoalDecision:
    """Serializable result of a unified goal decision.

    ``decision_reason`` is reserved for a concise rule label (for example,
    ``"missing_destination"``), never chain-of-thought or free-form reasoning.
    """

    intent: IntentType
    route: GoalRoute
    slots: dict[str, Any] = field(default_factory=dict)
    changed_slots: dict[str, Any] = field(default_factory=dict)
    missing_fields: list[str] = field(default_factory=list)
    selected_agents: list[str] = field(default_factory=list)
    selected_tools: list[str] = field(default_factory=list)
    requires_clarification: bool = False
    decision_reason: str = ""

    def to_trace_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible plain dictionary for trace recording."""

        return _to_json_compatible(asdict(self))
