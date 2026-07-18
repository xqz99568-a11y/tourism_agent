"""Goal-state task ticket and scheduler decisions for research experiments."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping


TICKET_SCHEMA_VERSION = "ctp-goal-state-ticket-v1"
DECISION_SCHEMA_VERSION = "ctp-scheduler-decision-v1"

CANONICAL_AGENT_ORDER = ("attraction", "weather", "itinerary", "budget")
CANONICAL_TOOL_ORDER = ("poi_search", "weather_query", "budget_calculator")

TOOLS_BY_AGENT = {
    "attraction": ("poi_search",),
    "weather": ("weather_query",),
    "itinerary": (),
    "budget": ("budget_calculator",),
}

AGENT_FINGERPRINT_SLOTS = {
    "attraction": ("destination", "traveler_group", "preferences"),
    "weather": ("destination", "start_date", "duration_days", "weather_scenario"),
    "itinerary": (
        "destination",
        "start_date",
        "duration_days",
        "traveler_group",
        "preferences",
        "budget_amount",
        "budget_level",
        "weather_scenario",
    ),
    "budget": (
        "destination",
        "duration_days",
        "people_count",
        "traveler_group",
        "preferences",
        "budget_amount",
        "budget_level",
    ),
}

DEPENDENT_AGENTS = {
    "attraction": ("itinerary", "budget"),
    "weather": ("itinerary",),
}

RESULT_DEPENDENCIES = {
    "itinerary": ("attraction", "weather"),
    "budget": ("attraction",),
}

CANONICAL_SLOT_ORDER = (
    "destination",
    "start_date",
    "duration_days",
    "people_count",
    "traveler_group",
    "budget_amount",
    "budget_level",
    "preferences",
    "special_requirements",
    "weather_scenario",
)

CAPABILITY_ORDER = (
    "poi_evidence",
    "weather_evidence",
    "itinerary_generation",
    "budget_estimation",
    "clarification",
    "chat_response",
)

SLOT_ALIASES = {
    "city": "destination",
    "destination_city": "destination",
    "date": "start_date",
    "travel_date": "start_date",
    "departure_date": "start_date",
    "days": "duration_days",
    "duration": "duration_days",
    "num_days": "duration_days",
    "travel_days": "duration_days",
    "people": "people_count",
    "num_travelers": "people_count",
    "traveler_count": "people_count",
    "travelers": "people_count",
    "traveler_type": "traveler_group",
    "tourist_type": "traveler_group",
    "group_type": "traveler_group",
    "budget": "budget_amount",
    "budget_limit": "budget_amount",
    "max_budget": "budget_amount",
    "spending_level": "budget_level",
    "interests": "preferences",
    "travel_styles": "preferences",
    "requirements": "special_requirements",
    "special_requirement": "special_requirements",
    "scenario_type": "weather_scenario",
}

CITY_ALIASES = {
    "北京": "beijing",
    "beijing": "beijing",
    "杭州": "hangzhou",
    "hangzhou": "hangzhou",
    "西安": "xian",
    "xian": "xian",
    "xi'an": "xian",
    "深圳": "shenzhen",
    "shenzhen": "shenzhen",
    "桂林": "guilin",
    "guilin": "guilin",
}

TASK_REQUIRED_SLOTS = {
    "trip_planning": ("destination", "duration_days", "people_count", "start_date"),
    "attraction_recommendation": ("destination",),
    "weather_query": ("destination", "start_date"),
}

TASK_CAPABILITIES = {
    "trip_planning": (
        "poi_evidence",
        "weather_evidence",
        "itinerary_generation",
        "budget_estimation",
    ),
    "attraction_recommendation": ("poi_evidence",),
    "weather_query": ("weather_evidence",),
    "budget_query": ("budget_estimation",),
    "weather_adjustment": ("weather_evidence", "itinerary_generation"),
    "clarification": ("clarification",),
    "general_chat": ("chat_response",),
}

WEATHER_TERMS = (
    "天气",
    "下雨",
    "雨天",
    "高温",
    "低温",
    "降温",
    "weather",
    "rain",
    "hot",
    "cold",
)
BUDGET_TERMS = (
    "预算",
    "费用",
    "花费",
    "多少钱",
    "省钱",
    "价格",
    "budget",
    "cost",
    "price",
)
ATTRACTION_TERMS = (
    "景点",
    "推荐",
    "打卡",
    "去哪",
    "博物馆",
    "attraction",
    "poi",
    "museum",
)
TRIP_TERMS = (
    "行程",
    "规划",
    "旅游",
    "旅行",
    "完整",
    "玩",
    "游",
    "trip",
    "plan",
    "itinerary",
)
REPLAN_TERMS = (
    "重新安排",
    "重新做",
    "重新规划",
    "重排",
    "调整",
    "改成",
    "改到",
    "其他不变",
    "不变",
    "replan",
    "adjust",
    "change",
)
REPLAN_ACTION_TERMS = (
    "重新安排",
    "重新做",
    "重新规划",
    "重排",
    "replan",
)
EXPLICIT_REPLAN_TERMS = REPLAN_ACTION_TERMS + (
    "重新做一版",
    "重做",
    "换一版",
    "redo",
    "regenerate",
    "new version",
)
IDENTICAL_REQUEST_TERMS = (
    "同样",
    "一样",
    "再给我一遍",
    "照旧",
    "就按这个方案",
    "不用改",
    "不修改",
    "same",
    "again",
)
ATTRACTION_EXPANSION_TERMS = (
    "再推荐",
    "更多景点",
    "再来几个",
    "还有哪些",
    "几个景点",
    "more attractions",
    "more poi",
)
GENERAL_CHAT_TERMS = (
    "谢谢",
    "你好",
    "心情",
    "不错",
    "thanks",
    "thank you",
    "hello",
    "good mood",
)


@dataclass(frozen=True)
class GoalStateTaskTicket:
    """Structured task ticket used before adaptive agent scheduling."""

    schema_version: str = TICKET_SCHEMA_VERSION
    task_type: str = "general_chat"
    current_slots: dict[str, Any] = field(default_factory=dict)
    previous_slots: dict[str, Any] = field(default_factory=dict)
    changed_slots: list[str] = field(default_factory=list)
    preserved_slots: list[str] = field(default_factory=list)
    missing_slots: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    clarification_required: bool = False
    clarification_fields: list[str] = field(default_factory=list)
    goal_change_type: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SchedulerDecision:
    """Pure scheduler output before any agent or tool execution."""

    schema_version: str = DECISION_SCHEMA_VERSION
    planned_agents: list[str] = field(default_factory=list)
    planned_tools: list[str] = field(default_factory=list)
    reused_agents: list[str] = field(default_factory=list)
    invalidated_agents: list[str] = field(default_factory=list)
    clarification_required: bool = False
    clarification_fields: list[str] = field(default_factory=list)
    decision_reasons: list[str] = field(default_factory=list)
    reuse_validation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GoalStateTicketBuilder:
    """Build a deterministic goal-state task ticket from normalized slots."""

    def build_ticket(
        self,
        *,
        user_input: str = "",
        current_slots: Mapping[str, Any] | None = None,
        previous_state: Mapping[str, Any] | None = None,
    ) -> GoalStateTaskTicket:
        previous_slots = normalize_slots(_previous_slots_from_state(previous_state))
        cancellable_empty_slots = {
            "preferences",
            "budget_amount",
            "budget_level",
            "special_requirements",
        }
        current_delta = normalize_slots(
            current_slots or {},
            keep_empty_slots=cancellable_empty_slots & set(previous_slots),
        )
        effective_current = _merge_slots(previous_slots, current_delta)
        changed_slots, preserved_slots = _diff_slots(previous_slots, effective_current)

        goal_change_type = self._infer_goal_change_type(
            user_input=user_input,
            previous_slots=previous_slots,
            changed_slots=changed_slots,
        )
        preliminary_task_type = self._infer_task_type(
            user_input=user_input,
            current_slots=effective_current,
            previous_slots=previous_slots,
            changed_slots=changed_slots,
            goal_change_type=goal_change_type,
        )
        missing_slots = self._missing_slots(
            preliminary_task_type,
            effective_current,
            previous_state,
        )
        task_type = (
            "clarification"
            if missing_slots and preliminary_task_type != "general_chat"
            else preliminary_task_type
        )
        clarification_required = task_type == "clarification"
        clarification_fields = list(missing_slots) if clarification_required else []
        required_capabilities = self._required_capabilities(task_type, changed_slots)

        return GoalStateTaskTicket(
            task_type=task_type,
            current_slots=effective_current,
            previous_slots=previous_slots,
            changed_slots=changed_slots,
            preserved_slots=preserved_slots,
            missing_slots=missing_slots,
            required_capabilities=required_capabilities,
            clarification_required=clarification_required,
            clarification_fields=clarification_fields,
            goal_change_type=goal_change_type,
        )

    def _infer_goal_change_type(
        self,
        *,
        user_input: str,
        previous_slots: Mapping[str, Any],
        changed_slots: list[str],
    ) -> str:
        if not previous_slots:
            return "new_request"
        if changed_slots:
            return "slot_delta"
        text = _normalize_text(user_input)
        if _contains_any(text, EXPLICIT_REPLAN_TERMS):
            return "explicit_replan"
        if _contains_any(text, IDENTICAL_REQUEST_TERMS):
            return "identical_request"
        if _contains_any(text, ATTRACTION_EXPANSION_TERMS):
            return "goal_shift_attraction"
        if _contains_any(text, GENERAL_CHAT_TERMS) and not _contains_any(
            text,
            TRIP_TERMS + ATTRACTION_TERMS + WEATHER_TERMS + BUDGET_TERMS,
        ):
            return "goal_shift_chat"
        return "goal_shift_unspecified"

    def _infer_task_type(
        self,
        *,
        user_input: str,
        current_slots: Mapping[str, Any],
        previous_slots: Mapping[str, Any],
        changed_slots: list[str],
        goal_change_type: str,
    ) -> str:
        text = _normalize_text(user_input)
        has_previous = bool(previous_slots)

        if _contains_any(text, WEATHER_TERMS):
            if has_previous and (_contains_any(text, REPLAN_TERMS) or "weather_scenario" in changed_slots):
                return "weather_adjustment"
            return "weather_query"

        if not current_slots and not has_previous and not _contains_any(text, TRIP_TERMS + ATTRACTION_TERMS + BUDGET_TERMS):
            return "general_chat"

        if has_previous:
            if goal_change_type == "goal_shift_chat":
                return "general_chat"
            if goal_change_type == "goal_shift_attraction":
                return "attraction_recommendation"
            if goal_change_type == "goal_shift_unspecified" and not _contains_any(
                text,
                TRIP_TERMS + ATTRACTION_TERMS + WEATHER_TERMS + BUDGET_TERMS + REPLAN_TERMS,
            ):
                return "general_chat"
            if goal_change_type == "explicit_replan":
                return "partial_replan"
            if goal_change_type == "identical_request":
                return "partial_replan"
            if set(changed_slots) & {"preferences", "budget_amount", "budget_level"}:
                return "partial_replan"
            if _contains_any(text, BUDGET_TERMS) and not _contains_any(text, REPLAN_ACTION_TERMS):
                return "budget_query"
            if changed_slots:
                return "partial_replan"
            if _contains_any(text, ATTRACTION_TERMS):
                return "attraction_recommendation"
            if _contains_any(text, TRIP_TERMS + REPLAN_TERMS):
                return "partial_replan"
            return "general_chat"

        has_trip_signal = _contains_any(text, TRIP_TERMS)
        has_attraction_signal = _contains_any(text, ATTRACTION_TERMS)
        if has_trip_signal and any(
            slot in current_slots for slot in ("start_date", "duration_days", "people_count")
        ):
            return "trip_planning"
        if _contains_any(text, BUDGET_TERMS):
            return "budget_query"
        if has_attraction_signal and not any(slot in current_slots for slot in ("start_date", "duration_days", "people_count")):
            return "attraction_recommendation"
        if has_trip_signal or any(slot in current_slots for slot in ("start_date", "duration_days", "people_count")):
            return "trip_planning"
        if current_slots.get("destination"):
            return "attraction_recommendation"
        return "general_chat"

    def _missing_slots(
        self,
        task_type: str,
        current_slots: Mapping[str, Any],
        previous_state: Mapping[str, Any] | None,
    ) -> list[str]:
        if task_type == "budget_query":
            if _has_available_result(previous_state, "attraction", current_slots):
                required = ("people_count", "duration_days")
            else:
                required = ("destination", "duration_days", "people_count")
            return [slot for slot in required if slot not in current_slots]

        if task_type == "partial_replan":
            return [] if previous_state else ["previous_state"]

        if task_type == "weather_adjustment":
            if _has_available_result(
                previous_state,
                "weather",
                current_slots,
            ) or _has_available_result(previous_state, "itinerary", current_slots):
                return []
            required = ("destination", "start_date")
            return [slot for slot in required if slot not in current_slots]

        required = TASK_REQUIRED_SLOTS.get(task_type, ())
        return [slot for slot in required if slot not in current_slots]

    def _required_capabilities(self, task_type: str, changed_slots: list[str]) -> list[str]:
        if task_type != "partial_replan":
            return list(TASK_CAPABILITIES.get(task_type, ()))

        capabilities: list[str] = []
        if "destination" in changed_slots:
            capabilities.extend(TASK_CAPABILITIES["trip_planning"])
        if "duration_days" in changed_slots:
            capabilities.extend(("weather_evidence", "itinerary_generation", "budget_estimation"))
        if "start_date" in changed_slots:
            capabilities.extend(("weather_evidence", "itinerary_generation"))
        if "people_count" in changed_slots:
            capabilities.append("budget_estimation")
        if any(slot in changed_slots for slot in ("traveler_group", "preferences")):
            capabilities.extend(("poi_evidence", "itinerary_generation", "budget_estimation"))
        if any(slot in changed_slots for slot in ("budget_amount", "budget_level")):
            capabilities.extend(("poi_evidence", "itinerary_generation", "budget_estimation"))
        if "weather_scenario" in changed_slots:
            capabilities.extend(("weather_evidence", "itinerary_generation"))
        return _ordered_unique_capabilities(capabilities)


class GoalStateScheduler:
    """Select the minimal required agents/tools from a goal-state ticket."""

    def schedule(
        self,
        ticket: GoalStateTaskTicket,
        *,
        previous_state: Mapping[str, Any] | None = None,
    ) -> SchedulerDecision:
        if ticket.clarification_required or ticket.task_type == "clarification":
            return self._decision(
                clarification_required=True,
                clarification_fields=ticket.clarification_fields,
                decision_reasons=["missing_required_slots"],
            )

        if ticket.task_type == "general_chat":
            return self._decision(decision_reasons=["general_chat_no_agents"])

        if ticket.task_type == "trip_planning":
            return self._decision(
                planned_agents=list(CANONICAL_AGENT_ORDER),
                decision_reasons=["new_full_plan"],
            )

        if ticket.task_type == "attraction_recommendation":
            return self._decision(
                planned_agents=["attraction"],
                decision_reasons=["single_capability_request"],
            )

        if ticket.task_type == "weather_query":
            return self._decision(
                planned_agents=["weather"],
                decision_reasons=["single_capability_request"],
            )

        if ticket.task_type == "budget_query":
            return self._schedule_budget_query(ticket, previous_state)

        if ticket.task_type == "weather_adjustment":
            return self._decision_with_reuse_validation(
                ticket=ticket,
                previous_state=previous_state,
                planned_agents=["weather", "itinerary"],
                invalidated_agents=["weather", "itinerary"],
                decision_reasons=["weather_changed_itinerary_adjustment"],
                reuse_scope_agents=["attraction"],
            )

        if ticket.task_type == "partial_replan":
            return self._schedule_partial_replan(ticket, previous_state)

        return self._decision(decision_reasons=["general_chat_no_agents"])

    def _schedule_budget_query(
        self,
        ticket: GoalStateTaskTicket,
        previous_state: Mapping[str, Any] | None,
    ) -> SchedulerDecision:
        if "people_count" in ticket.changed_slots and _has_available_result(
            previous_state,
            "attraction",
            ticket.current_slots,
        ):
            return self._decision_with_reuse_validation(
                ticket=ticket,
                previous_state=previous_state,
                planned_agents=["budget"],
                invalidated_agents=["budget"],
                decision_reasons=["people_count_changed_budget_only"],
                reuse_scope_agents=["attraction"],
            )

        if _has_available_result(previous_state, "attraction", ticket.current_slots):
            return self._decision_with_reuse_validation(
                ticket=ticket,
                previous_state=previous_state,
                planned_agents=["budget"],
                decision_reasons=["single_capability_request"],
                reuse_scope_agents=["attraction"],
            )

        return self._decision_with_reuse_validation(
            ticket=ticket,
            previous_state=previous_state,
            planned_agents=["attraction", "budget"],
            decision_reasons=["single_capability_request"],
            reuse_scope_agents=["attraction"],
        )

    def _schedule_partial_replan(
        self,
        ticket: GoalStateTaskTicket,
        previous_state: Mapping[str, Any] | None,
    ) -> SchedulerDecision:
        changed = set(ticket.changed_slots)

        if not changed:
            if ticket.goal_change_type == "explicit_replan":
                return self._decision_with_reuse_validation(
                    ticket=ticket,
                    previous_state=previous_state,
                    planned_agents=list(CANONICAL_AGENT_ORDER),
                    invalidated_agents=list(CANONICAL_AGENT_ORDER),
                    decision_reasons=["explicit_replan_requested"],
                )
            reusable_agents = set(self._available_agents(ticket, previous_state))
            if reusable_agents != set(CANONICAL_AGENT_ORDER):
                raw_available = set(_raw_available_agents(previous_state))
                return self._decision_with_reuse_validation(
                    ticket=ticket,
                    previous_state=previous_state,
                    planned_agents=[
                        agent
                        for agent in CANONICAL_AGENT_ORDER
                        if agent not in reusable_agents
                    ],
                    invalidated_agents=[
                        agent
                        for agent in CANONICAL_AGENT_ORDER
                        if agent in raw_available and agent not in reusable_agents
                    ],
                    decision_reasons=["identical_request_incomplete_previous_state_replan"],
                )
            return self._decision_with_reuse_validation(
                ticket=ticket,
                previous_state=previous_state,
                decision_reasons=["identical_request_reuse_all"],
            )

        if "destination" in changed:
            return self._decision_with_reuse_validation(
                ticket=ticket,
                previous_state=previous_state,
                planned_agents=list(CANONICAL_AGENT_ORDER),
                invalidated_agents=list(CANONICAL_AGENT_ORDER),
                decision_reasons=["destination_changed_invalidate_all"],
            )

        planned_agents: list[str] = []
        invalidated_agents: list[str] = []
        decision_reasons: list[str] = []

        if "duration_days" in changed:
            planned_agents.extend(["weather", "itinerary", "budget"])
            invalidated_agents.extend(["weather", "itinerary", "budget"])
            decision_reasons.append("duration_changed_partial_replan")

        if "start_date" in changed:
            planned_agents.extend(["weather", "itinerary"])
            invalidated_agents.extend(["weather", "itinerary"])
            decision_reasons.append("date_changed_weather_replan")

        if "people_count" in changed:
            planned_agents.append("budget")
            invalidated_agents.append("budget")
            decision_reasons.append("people_count_changed_budget_only")

        if "traveler_group" in changed:
            planned_agents.extend(["attraction", "itinerary", "budget"])
            invalidated_agents.extend(["attraction", "itinerary", "budget"])
            decision_reasons.append("traveler_group_changed_replan")

        if "preferences" in changed:
            planned_agents.extend(["attraction", "itinerary", "budget"])
            invalidated_agents.extend(["attraction", "itinerary", "budget"])
            decision_reasons.append("preferences_changed_replan")

        if changed & {"budget_amount", "budget_level"}:
            planned_agents.extend(["attraction", "itinerary", "budget"])
            invalidated_agents.extend(["attraction", "itinerary", "budget"])
            decision_reasons.append("budget_changed_replan")

        if "weather_scenario" in changed:
            planned_agents.extend(["weather", "itinerary"])
            invalidated_agents.extend(["weather", "itinerary"])
            decision_reasons.append("weather_changed_itinerary_adjustment")

        if planned_agents or invalidated_agents:
            return self._decision_with_reuse_validation(
                ticket=ticket,
                previous_state=previous_state,
                planned_agents=planned_agents,
                invalidated_agents=invalidated_agents,
                decision_reasons=decision_reasons,
            )

        return self._decision_with_reuse_validation(
            ticket=ticket,
            previous_state=previous_state,
            planned_agents=list(CANONICAL_AGENT_ORDER),
            invalidated_agents=list(CANONICAL_AGENT_ORDER),
            decision_reasons=["new_full_plan"],
        )

    def _decision(
        self,
        *,
        planned_agents: list[str] | None = None,
        reused_agents: list[str] | None = None,
        invalidated_agents: list[str] | None = None,
        clarification_required: bool = False,
        clarification_fields: list[str] | None = None,
        decision_reasons: list[str] | None = None,
        reuse_validation: dict[str, Any] | None = None,
    ) -> SchedulerDecision:
        ordered_planned_agents = _ordered_agents(planned_agents or [])
        return SchedulerDecision(
            planned_agents=ordered_planned_agents,
            planned_tools=_tools_for_agents(ordered_planned_agents),
            reused_agents=_ordered_agents(reused_agents or []),
            invalidated_agents=_ordered_agents(invalidated_agents or []),
            clarification_required=clarification_required,
            clarification_fields=clarification_fields or [],
            decision_reasons=decision_reasons or [],
            reuse_validation=reuse_validation or {},
        )

    def _decision_with_reuse_validation(
        self,
        *,
        ticket: GoalStateTaskTicket,
        previous_state: Mapping[str, Any] | None,
        planned_agents: list[str] | None = None,
        invalidated_agents: list[str] | None = None,
        decision_reasons: list[str] | None = None,
        reuse_scope_agents: list[str] | None = None,
    ) -> SchedulerDecision:
        planned = list(planned_agents or [])
        invalidated = list(invalidated_agents or [])
        scope = tuple(_ordered_agents(reuse_scope_agents or list(CANONICAL_AGENT_ORDER)))
        excluded = tuple(_ordered_agents([*planned, *invalidated]))
        reusable_agents = self._available_agents(
            ticket,
            previous_state,
            exclude=excluded,
            scope=scope,
        )
        unusable_agents = self._unusable_agents(
            ticket,
            previous_state,
            exclude=excluded,
            scope=scope,
        )
        cascaded_unusable = self._cascade_unusable_agents(unusable_agents, previous_state)
        if cascaded_unusable:
            planned.extend(cascaded_unusable)
            invalidated.extend(cascaded_unusable)
            if decision_reasons is None:
                decision_reasons = []
            if "previous_result_unusable_replan" not in decision_reasons:
                decision_reasons = [*decision_reasons, "previous_result_unusable_replan"]

        planned, invalidated, reusable_agents, dependency_reasons = self._enforce_dependencies(
            planned_agents=planned,
            invalidated_agents=invalidated,
            reusable_agents=reusable_agents,
        )
        if dependency_reasons:
            existing_reasons = list(decision_reasons or [])
            for reason in dependency_reasons:
                if reason not in existing_reasons:
                    existing_reasons.append(reason)
            decision_reasons = existing_reasons

        return self._decision(
            planned_agents=planned,
            reused_agents=reusable_agents,
            invalidated_agents=invalidated,
            decision_reasons=decision_reasons,
            reuse_validation=self._reuse_validation(
                ticket,
                previous_state,
                final_reused_agents=reusable_agents,
                final_invalidated_agents=invalidated,
                final_planned_agents=planned,
            ),
        )

    def _available_agents(
        self,
        ticket: GoalStateTaskTicket,
        previous_state: Mapping[str, Any] | None,
        *,
        exclude: tuple[str, ...] = (),
        scope: tuple[str, ...] | None = None,
    ) -> list[str]:
        excluded = set(exclude)
        scoped_agents = scope or CANONICAL_AGENT_ORDER
        return [
            agent
            for agent in scoped_agents
            if agent not in excluded
            and _is_agent_reusable(
                agent,
                current_slots=ticket.current_slots,
                previous_state=previous_state,
            )
        ]

    def _unusable_agents(
        self,
        ticket: GoalStateTaskTicket,
        previous_state: Mapping[str, Any] | None,
        *,
        exclude: tuple[str, ...] = (),
        scope: tuple[str, ...] | None = None,
    ) -> list[str]:
        excluded = set(exclude)
        scoped_agents = set(scope or CANONICAL_AGENT_ORDER)
        return [
            agent
            for agent in _raw_available_agents(previous_state)
            if agent not in excluded
            and agent in scoped_agents
            and not _is_agent_reusable(
                agent,
                current_slots=ticket.current_slots,
                previous_state=previous_state,
            )
        ]

    def _has_any_reusable_result(
        self,
        ticket: GoalStateTaskTicket,
        previous_state: Mapping[str, Any] | None,
    ) -> bool:
        return bool(self._available_agents(ticket, previous_state))

    def _reuse_validation(
        self,
        ticket: GoalStateTaskTicket,
        previous_state: Mapping[str, Any] | None,
        *,
        final_reused_agents: list[str] | None = None,
        final_invalidated_agents: list[str] | None = None,
        final_planned_agents: list[str] | None = None,
    ) -> dict[str, Any]:
        raw_available = _raw_available_agents(previous_state)
        final_reused = _ordered_agents(final_reused_agents or [])
        final_invalidated = set(_ordered_agents(final_invalidated_agents or []))
        final_planned = set(_ordered_agents(final_planned_agents or []))
        unusable = [
            agent
            for agent in raw_available
            if agent not in final_reused
        ]
        unusable_reasons: dict[str, str] = {}
        for agent in unusable:
            reason = _agent_unusable_reason(
                agent,
                current_slots=ticket.current_slots,
                previous_state=previous_state,
            )
            if reason == "reusable":
                if agent in final_invalidated:
                    reason = "scheduled_for_reexecution"
                elif agent in final_planned:
                    reason = "scheduled_for_execution"
            unusable_reasons[agent] = reason
        return {
            "raw_available_agents": raw_available,
            "reusable_agents": final_reused,
            "unusable_agents": unusable,
            "unusable_reasons": unusable_reasons,
        }

    def _cascade_unusable_agents(
        self,
        unusable_agents: list[str],
        previous_state: Mapping[str, Any] | None,
    ) -> list[str]:
        raw_available = set(_raw_available_agents(previous_state))
        cascaded = set(unusable_agents)
        for agent in list(unusable_agents):
            cascaded.update(
                dependent
                for dependent in DEPENDENT_AGENTS.get(agent, ())
                if dependent in raw_available
            )
        return _ordered_agents(list(cascaded))

    def _enforce_dependencies(
        self,
        *,
        planned_agents: list[str],
        invalidated_agents: list[str],
        reusable_agents: list[str],
    ) -> tuple[list[str], list[str], list[str], list[str]]:
        planned = set(_ordered_agents(planned_agents))
        invalidated = set(_ordered_agents(invalidated_agents))
        reusable = set(_ordered_agents(reusable_agents))
        reasons: list[str] = []

        changed = True
        while changed:
            changed = False
            active_agents = planned | reusable
            for dependent, upstream_agents in RESULT_DEPENDENCIES.items():
                if dependent not in active_agents:
                    continue

                upstream_changed = False
                for upstream in upstream_agents:
                    if upstream in planned:
                        upstream_changed = True
                        continue
                    if upstream not in reusable:
                        planned.add(upstream)
                        upstream_changed = True
                        changed = True
                        if "missing_upstream_result_replan" not in reasons:
                            reasons.append("missing_upstream_result_replan")

                if dependent in reusable and upstream_changed:
                    reusable.remove(dependent)
                    planned.add(dependent)
                    invalidated.add(dependent)
                    changed = True
                    if "dependent_result_invalidated" not in reasons:
                        reasons.append("dependent_result_invalidated")

        return (
            _ordered_agents(list(planned)),
            _ordered_agents(list(invalidated)),
            _ordered_agents(list(reusable)),
            reasons,
        )


def build_goal_state_ticket(
    *,
    user_input: str = "",
    current_slots: Mapping[str, Any] | None = None,
    previous_state: Mapping[str, Any] | None = None,
) -> GoalStateTaskTicket:
    return GoalStateTicketBuilder().build_ticket(
        user_input=user_input,
        current_slots=current_slots,
        previous_state=previous_state,
    )


def schedule_goal_state_ticket(
    ticket: GoalStateTaskTicket,
    *,
    previous_state: Mapping[str, Any] | None = None,
) -> SchedulerDecision:
    return GoalStateScheduler().schedule(ticket, previous_state=previous_state)


def normalize_slots(
    slots: Mapping[str, Any] | None,
    *,
    keep_empty_slots: Iterable[str] = (),
) -> dict[str, Any]:
    if not isinstance(slots, Mapping):
        return {}

    preserved_empty = set(keep_empty_slots)
    normalized: dict[str, Any] = {}
    for raw_key, raw_value in slots.items():
        key = SLOT_ALIASES.get(str(raw_key), str(raw_key))
        if key not in CANONICAL_SLOT_ORDER:
            continue
        value = _normalize_slot_value(key, raw_value)
        if _is_empty_value(value) and key not in preserved_empty:
            continue
        normalized[key] = value
    return {slot: normalized[slot] for slot in CANONICAL_SLOT_ORDER if slot in normalized}


def _previous_slots_from_state(previous_state: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(previous_state, Mapping):
        return {}
    slots = previous_state.get("slots")
    return slots if isinstance(slots, Mapping) else previous_state


def _merge_slots(previous_slots: Mapping[str, Any], current_delta: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(previous_slots)
    merged.update(current_delta)
    return {slot: merged[slot] for slot in CANONICAL_SLOT_ORDER if slot in merged}


def _diff_slots(
    previous_slots: Mapping[str, Any],
    current_slots: Mapping[str, Any],
) -> tuple[list[str], list[str]]:
    changed: list[str] = []
    preserved: list[str] = []
    for slot in CANONICAL_SLOT_ORDER:
        if slot not in current_slots:
            continue
        if slot not in previous_slots:
            changed.append(slot)
        elif current_slots[slot] == previous_slots[slot]:
            preserved.append(slot)
        else:
            changed.append(slot)
    return changed, preserved


def _normalize_slot_value(key: str, value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if key == "destination":
            return CITY_ALIASES.get(stripped.casefold(), stripped)
        if key in {"duration_days", "people_count"} and stripped.isdigit():
            return int(stripped)
        if key == "budget_amount":
            return _number_or_text(stripped)
        return stripped

    if isinstance(value, list | tuple | set):
        return _normalize_list(value)

    return value


def _normalize_list(value: list[Any] | tuple[Any, ...] | set[Any]) -> list[Any]:
    items: list[Any] = []
    for item in value:
        normalized = item.strip() if isinstance(item, str) else item
        if _is_empty_value(normalized) or normalized in items:
            continue
        items.append(normalized)
    return items


def _number_or_text(value: str) -> int | float | str:
    try:
        number = float(value)
    except ValueError:
        return value
    return int(number) if number.is_integer() else number


def _is_empty_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _normalize_text(text: str) -> str:
    return str(text or "").casefold()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term.casefold() in text for term in terms)


def is_goal_state_agent_reusable(
    agent_name: str,
    *,
    current_slots: Mapping[str, Any] | None,
    previous_state: Mapping[str, Any] | None,
) -> bool:
    """Public helper used by execution code before injecting reused results."""
    return _is_agent_reusable(
        agent_name,
        current_slots=current_slots,
        previous_state=previous_state,
    )


def build_goal_state_result_fingerprints(
    *,
    slots: Mapping[str, Any] | None,
    tool_results: Mapping[str, Any] | None = None,
    daily_itinerary: Any = None,
    result_agents: Iterable[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build semantic result fingerprints for paper-trace reuse validation."""
    canonical_slots = normalize_slots(slots)
    concrete_results = tool_results if isinstance(tool_results, Mapping) else {}
    result_agent_set = (
        set(_ordered_agents([str(agent) for agent in result_agents]))
        if result_agents is not None
        else set(CANONICAL_AGENT_ORDER)
    )
    available_results = {
        "attraction": "attraction" in result_agent_set and "poi_search" in concrete_results,
        "weather": "weather" in result_agent_set and "weather_query" in concrete_results,
        "budget": "budget" in result_agent_set and "budget_calculator" in concrete_results,
        "itinerary": "itinerary" in result_agent_set and bool(daily_itinerary),
    }
    fingerprints: dict[str, dict[str, Any]] = {}
    for agent in CANONICAL_AGENT_ORDER:
        if any(
            not available_results.get(upstream)
            for upstream in RESULT_DEPENDENCIES.get(agent, ())
        ):
            continue
        if not _agent_has_successful_artifact(
            agent,
            previous_state={
                "tool_results": concrete_results,
                "daily_itinerary": daily_itinerary,
                "available_results": available_results,
            },
        ):
            continue
        fingerprints[agent] = _agent_fingerprint_from_slots(agent, canonical_slots)
    return fingerprints


def _has_available_result(
    previous_state: Mapping[str, Any] | None,
    agent_name: str,
    current_slots: Mapping[str, Any] | None = None,
) -> bool:
    return _is_agent_reusable(
        agent_name,
        current_slots=current_slots,
        previous_state=previous_state,
    )


def _is_agent_reusable(
    agent_name: str,
    *,
    current_slots: Mapping[str, Any] | None,
    previous_state: Mapping[str, Any] | None,
) -> bool:
    if agent_name not in CANONICAL_AGENT_ORDER:
        return False
    if not _agent_has_successful_artifact(agent_name, previous_state=previous_state):
        return False
    return _agent_fingerprint_matches(
        agent_name,
        current_slots=current_slots,
        previous_state=previous_state,
    )


def _agent_unusable_reason(
    agent_name: str,
    *,
    current_slots: Mapping[str, Any] | None,
    previous_state: Mapping[str, Any] | None,
) -> str:
    if not _raw_agent_available(previous_state, agent_name):
        return "not_available"
    if not _agent_has_successful_artifact(agent_name, previous_state=previous_state):
        return "previous_result_failed"
    if not _agent_fingerprint_matches(
        agent_name,
        current_slots=current_slots,
        previous_state=previous_state,
    ):
        return "input_fingerprint_mismatch"
    return "reusable"


def _raw_available_agents(previous_state: Mapping[str, Any] | None) -> list[str]:
    return [
        agent
        for agent in CANONICAL_AGENT_ORDER
        if _raw_agent_available(previous_state, agent)
    ]


def _raw_agent_available(
    previous_state: Mapping[str, Any] | None,
    agent_name: str,
) -> bool:
    if not isinstance(previous_state, Mapping):
        return False
    available_results = previous_state.get("available_results")
    if isinstance(available_results, Mapping) and agent_name in available_results:
        if not bool(available_results.get(agent_name)):
            return False
    tool_results = _previous_tool_results_from_state(previous_state)
    if any(tool in tool_results for tool in TOOLS_BY_AGENT.get(agent_name, ())):
        return True
    if agent_name == "itinerary":
        return bool(_previous_daily_itinerary_from_state(previous_state))
    return False


def _agent_has_successful_artifact(
    agent_name: str,
    *,
    previous_state: Mapping[str, Any] | None,
) -> bool:
    if not _raw_agent_available(previous_state, agent_name):
        return False
    tool_results = _previous_tool_results_from_state(previous_state)
    agent_tools = TOOLS_BY_AGENT.get(agent_name, ())
    concrete_results = [
        tool_results[tool]
        for tool in agent_tools
        if tool in tool_results
    ]
    if concrete_results:
        return all(_tool_result_success(result) for result in concrete_results)
    if agent_name == "itinerary":
        if _previous_state_failed(previous_state):
            return False
        return bool(_previous_daily_itinerary_from_state(previous_state)) or _raw_agent_available(
            previous_state,
            agent_name,
        )
    return not _previous_state_failed(previous_state)


def _previous_state_failed(previous_state: Mapping[str, Any] | None) -> bool:
    if not isinstance(previous_state, Mapping):
        return False
    candidates = [
        previous_state.get("status"),
        previous_state.get("execution_status"),
        _nested_mapping(previous_state, "trace", "status"),
        _nested_mapping(previous_state, "output", "execution_status"),
        _nested_mapping(previous_state, "raw_output", "execution_status"),
    ]
    return any(
        str(value or "").lower() in {"failed", "error", "timeout", "expired", "stale"}
        for value in candidates
    )


def _tool_result_success(result: Any) -> bool:
    if not isinstance(result, Mapping):
        return False
    status = str(result.get("status") or "").lower()
    if status in {
        "failed",
        "error",
        "timeout",
        "cancelled",
        "canceled",
        "aborted",
        "expired",
        "stale",
    }:
        return False
    success = result.get("success")
    if success is False:
        return False
    error = result.get("error")
    return not bool(error and status != "no_result")


def _agent_fingerprint_matches(
    agent_name: str,
    *,
    current_slots: Mapping[str, Any] | None,
    previous_state: Mapping[str, Any] | None,
) -> bool:
    if not isinstance(previous_state, Mapping):
        return False
    expected = _agent_fingerprint_from_slots(agent_name, normalize_slots(current_slots))
    candidates = _agent_previous_fingerprint_candidates(agent_name, previous_state)
    if not candidates:
        return not _previous_tool_results_from_state(previous_state)
    return all(
        _fingerprint_candidate_matches(agent_name, expected, candidate)
        for candidate in candidates
    )


def _agent_previous_fingerprint_candidates(
    agent_name: str,
    previous_state: Mapping[str, Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for candidate in _previous_result_fingerprint_candidates(previous_state):
        agent_fingerprint = candidate.get(agent_name) if isinstance(candidate, Mapping) else None
        if isinstance(agent_fingerprint, Mapping):
            candidates.append(_normalize_fingerprint(agent_fingerprint))

    tool_results = _previous_tool_results_from_state(previous_state)
    for tool_name in TOOLS_BY_AGENT.get(agent_name, ()):
        tool_result = tool_results.get(tool_name)
        tool_input = tool_result.get("input") if isinstance(tool_result, Mapping) else None
        if isinstance(tool_input, Mapping):
            candidates.append(
                _agent_fingerprint_from_slots(
                    agent_name,
                    _slots_from_tool_input(tool_name, tool_input),
                )
            )

    previous_slots = normalize_slots(_previous_slots_from_state(previous_state))
    if previous_slots:
        candidates.append(_agent_fingerprint_from_slots(agent_name, previous_slots))
    return [candidate for candidate in candidates if candidate]


def _previous_result_fingerprint_candidates(
    previous_state: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    candidates = [
        previous_state.get("result_fingerprints"),
        previous_state.get("input_fingerprints"),
        _nested_mapping(previous_state, "metadata", "adaptive_scheduler", "result_fingerprints"),
        _nested_mapping(previous_state, "raw_output", "metadata", "adaptive_scheduler", "result_fingerprints"),
        _nested_mapping(previous_state, "output", "metadata", "adaptive_scheduler", "result_fingerprints"),
        _nested_mapping(
            previous_state,
            "output",
            "raw_output",
            "metadata",
            "adaptive_scheduler",
            "result_fingerprints",
        ),
    ]
    return [candidate for candidate in candidates if isinstance(candidate, Mapping)]


def _agent_fingerprint_from_slots(
    agent_name: str,
    slots: Mapping[str, Any] | None,
) -> dict[str, Any]:
    normalized = normalize_slots(slots)
    fingerprint: dict[str, Any] = {}
    for slot in AGENT_FINGERPRINT_SLOTS.get(agent_name, ()):
        value = normalized.get(slot)
        if _is_empty_value(value):
            continue
        fingerprint[slot] = _fingerprint_value(value)
    return fingerprint


def _slots_from_tool_input(tool_name: str, tool_input: Mapping[str, Any]) -> dict[str, Any]:
    if tool_name == "poi_search":
        return normalize_slots(
            {
                "destination": tool_input.get("city") or tool_input.get("destination"),
                "preferences": tool_input.get("preferences"),
                "traveler_group": tool_input.get("people"),
            }
        )
    if tool_name == "weather_query":
        return normalize_slots(
            {
                "destination": tool_input.get("city") or tool_input.get("destination"),
                "start_date": tool_input.get("date") or tool_input.get("start_date"),
                "duration_days": tool_input.get("days") or tool_input.get("duration"),
                "weather_scenario": (
                    tool_input.get("weather_scenario") or tool_input.get("scenario_type")
                ),
            }
        )
    if tool_name == "budget_calculator":
        return normalize_slots(
            {
                "destination": tool_input.get("city") or tool_input.get("destination"),
                "duration_days": tool_input.get("days") or tool_input.get("duration"),
                "people_count": (
                    tool_input.get("people_count") or tool_input.get("num_travelers")
                ),
                "budget_level": (
                    tool_input.get("spending_level") or tool_input.get("budget_level")
                ),
            }
        )
    return normalize_slots(tool_input)


def _fingerprint_candidate_matches(
    agent_name: str,
    expected: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> bool:
    comparable_slots = set(AGENT_FINGERPRINT_SLOTS.get(agent_name, ()))
    for slot, candidate_value in candidate.items():
        if slot not in comparable_slots:
            continue
        if slot not in expected:
            continue
        if _fingerprint_value(expected.get(slot)) != _fingerprint_value(candidate_value):
            return False
    for slot, expected_value in expected.items():
        if slot not in candidate and not _fingerprint_missing_is_allowed(agent_name, slot):
            if not _is_empty_value(expected_value):
                return False
    return True


def _fingerprint_missing_is_allowed(agent_name: str, slot: str) -> bool:
    return slot in {
        "budget_amount",
        "weather_scenario",
    } or (
        agent_name == "budget" and slot in {"preferences", "traveler_group"}
    )


def _normalize_fingerprint(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): _fingerprint_value(raw_value)
        for key, raw_value in value.items()
        if str(key) in CANONICAL_SLOT_ORDER and not _is_empty_value(raw_value)
    }


def _fingerprint_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _fingerprint_value(raw)
            for key, raw in sorted(value.items(), key=lambda item: str(item[0]))
            if not _is_empty_value(raw)
        }
    if isinstance(value, list | tuple | set):
        return sorted(str(item).strip().casefold() for item in value if not _is_empty_value(item))
    if isinstance(value, str):
        return value.strip().casefold()
    return value


def _previous_tool_results_from_state(
    previous_state: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(previous_state, Mapping):
        return {}
    candidates = [
        previous_state.get("tool_results"),
        _nested_mapping(previous_state, "raw_output", "tool_results"),
        _nested_mapping(previous_state, "output", "tool_results"),
        _nested_mapping(previous_state, "output", "raw_output", "tool_results"),
    ]
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            return {
                str(tool_name): result
                for tool_name, result in candidate.items()
                if isinstance(result, Mapping)
            }
    return {}


def _previous_daily_itinerary_from_state(previous_state: Mapping[str, Any] | None) -> Any:
    if not isinstance(previous_state, Mapping):
        return None
    return (
        previous_state.get("daily_itinerary")
        or _nested_mapping(previous_state, "raw_output", "daily_itinerary")
        or _nested_mapping(previous_state, "output", "daily_itinerary")
        or _nested_mapping(previous_state, "output", "raw_output", "daily_itinerary")
    )


def _nested_mapping(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _ordered_unique_capabilities(capabilities: list[str]) -> list[str]:
    capability_set = set(capabilities)
    return [capability for capability in CAPABILITY_ORDER if capability in capability_set]


def _ordered_agents(agents: list[str]) -> list[str]:
    agent_set = set(agents)
    return [agent for agent in CANONICAL_AGENT_ORDER if agent in agent_set]


def _tools_for_agents(agents: list[str]) -> list[str]:
    tool_set: set[str] = set()
    for agent in agents:
        tool_set.update(TOOLS_BY_AGENT.get(agent, ()))
    return [tool for tool in CANONICAL_TOOL_ORDER if tool in tool_set]
