"""Unified goal-decision data structures.

This module defines the decision contract only. It is intentionally independent
from orchestration and tracing so it can be adopted without changing runtime
behaviour.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from app.schemas import IntentType


class GoalRoute(str, Enum):
    """High-level route selected for the current user goal."""

    FULL_NEW_PLAN = "FULL_NEW_PLAN"
    CLARIFICATION_ANSWER = "CLARIFICATION_ANSWER"
    FOLLOW_UP = "FOLLOW_UP"
    DIRECT_TASK = "DIRECT_TASK"
    GENERAL_CHAT = "GENERAL_CHAT"
    INCOMPLETE_PLANNING = "INCOMPLETE_PLANNING"


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

        result = asdict(self)
        result["intent"] = self.intent.value
        result["route"] = self.route.value
        return result
