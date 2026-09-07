"""Goal-state task ticket and scheduler decisions for research experiments."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping


TICKET_SCHEMA_VERSION = "ctp-goal-state-ticket-v1"
DECISION_SCHEMA_VERSION = "ctp-scheduler-decision-v1"
INVALIDATION_PROPAGATION_DEFAULT_ENABLED = True

CANONICAL_AGENT_ORDER = ("attraction", "weather", "itinerary", "budget")
CANONICAL_TOOL_ORDER = ("poi_search", "weather_query", "budget_calculator")

TOOLS_BY_AGENT = {
    "attraction": ("poi_search",),
    "weather": ("weather_query",),
    "itinerary": (),
    "budget": ("budget_calculator",),
}

AGENT_FINGERPRINT_SLOTS = {
    "attraction": (
        "destination",
        "traveler_group",
        "preferences",
        "special_requirements",
    ),
    "weather": ("destination", "start_date", "duration_days", "weather_scenario"),
    "itinerary": (
        "destination",
        "start_date",
        "duration_days",
        "traveler_group",
        "preferences",
        "special_requirements",
        "weather_scenario",
    ),
    "budget": (
        "origin",
        "destination",
        "duration_days",
        "people_count",
        "traveler_group",
        "preferences",
        "special_requirements",
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
    "origin",
    "destination",
    "start_date",
    "end_date",
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
    "departure_city": "origin",
    "departure_place": "origin",
    "from_city": "origin",
    "city": "destination",
    "destination_city": "destination",
    "date": "start_date",
    "travel_date": "start_date",
    "departure_date": "start_date",
    "return_date": "end_date",
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
    "拉萨": "lhasa",
    "lhasa": "lhasa",
    "广州": "guangzhou",
    "guangzhou": "guangzhou",
    "上海": "shanghai",
    "shanghai": "shanghai",
    "成都": "chengdu",
    "chengdu": "chengdu",
    "重庆": "chongqing",
    "chongqing": "chongqing",
    "武汉": "wuhan",
    "wuhan": "wuhan",
    "长沙": "changsha",
    "changsha": "changsha",
    "南京": "nanjing",
    "nanjing": "nanjing",
    "郑州": "zhengzhou",
    "zhengzhou": "zhengzhou",
    "南昌": "nanchang",
    "nanchang": "nanchang",
    "贵阳": "guiyang",
    "guiyang": "guiyang",
}

TASK_REQUIRED_SLOTS = {
    "trip_planning": ("destination", "duration_days", "people_count", "start_date"),
    "trip_plan": ("destination", "duration_days", "people_count"),
    "weather_aware_trip_plan": ("destination", "start_date", "duration_days", "people_count"),
    "attraction_recommendation": ("destination",),
    "weather_query": ("destination",),
    "weather_forecast_query": ("destination",),
    "weather_climate_question": ("destination",),
}

TASK_CAPABILITIES = {
    "trip_planning": (
        "poi_evidence",
        "weather_evidence",
        "itinerary_generation",
        "budget_estimation",
    ),
    "trip_plan": (
        "poi_evidence",
        "itinerary_generation",
        "budget_estimation",
    ),
    "weather_aware_trip_plan": (
        "poi_evidence",
        "weather_evidence",
        "itinerary_generation",
        "budget_estimation",
    ),
    "attraction_recommendation": ("poi_evidence",),
    "destination_recommendation": ("chat_response",),
    "weather_query": ("weather_evidence",),
    "weather_forecast_query": ("weather_evidence",),
    "weather_climate_question": ("chat_response",),
    "budget_query": ("budget_estimation",),
    "weather_adjustment": (
        "weather_evidence",
        "itinerary_generation",
        "budget_estimation",
    ),
    "clarification": ("clarification",),
    "general_chat": ("chat_response",),
}

WEATHER_TERMS = (
    "天气",
    "下雨",
    "雨天",
    "有雨",
    "雨",
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
BUDGET_ATTRACTION_DEPENDENCY_TERMS = (
    "ticket",
    "tickets",
    "admission",
    "entry fee",
    "entrance fee",
    "attraction ticket",
    "attraction tickets",
    "poi ticket",
    "poi tickets",
    "scenic ticket",
    "scenic tickets",
    "门票",
    "票价",
    "景点票",
    "景区票",
)
ATTRACTION_TERMS = (
    "景点",
    "推荐",
    "打卡",
    "去哪",
    "博物馆",
    "地标",
    "城市地标",
    "attraction",
    "poi",
    "museum",
    "landmark",
)
TRIP_TERMS = (
    "行程",
    "规划",
    "旅游",
    "旅行",
    "完整",
    "玩",
    "游",
    "路线",
    "线路",
    "安排",
    "trip",
    "plan",
    "itinerary",
    "route",
)
FULL_TRIP_PLAN_TERMS = (
    "完整旅行计划",
    "完整旅游计划",
    "完整旅行方案",
    "完整旅游方案",
    "完整行程",
    "完整计划",
    "旅行计划",
    "旅游计划",
    "旅行方案",
    "旅游方案",
    "同时给天气、路线和预算",
    "同时给天气、行程和预算",
    "包含景点、天气、行程和预算",
    "包含景点天气行程预算",
    "景点、天气、行程和预算",
    "景点天气行程预算",
    "full travel plan",
    "full trip plan",
    "complete travel plan",
    "complete trip plan",
)
TEXT_BUDGET_SIGNAL_TERMS = (
    "控制在",
    "元内",
    "够用",
    "够不够",
    "是否能控制",
    "估算",
    "粗略估算",
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
    "完全按上一轮",
    "按上一轮",
    "上一轮",
    "不改变",
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
    "随便看看",
    "暂时不用",
    "暂时不用啦",
    "暂时不规划",
    "没打算出去",
    "晚安",
    "道个晚安",
    "能做什么",
    "助手能做什么",
    "哪些建议",
    "哪些旅游问题",
    "帮我解决哪些旅游问题",
    "心情",
    "不错",
    "thanks",
    "thank you",
    "hello",
    "good mood",
)
NEGATED_TRAVEL_PLANNING_TERMS = (
    "没打算出去玩",
    "最近没打算出去玩",
    "暂时不用",
    "暂时不用啦",
    "暂时不规划",
    "随便看看",
    "不需要任何旅行规划",
    "不需要任何旅游规划",
    "不需要旅行规划",
    "不需要旅游规划",
    "不需要旅游方案",
    "不需要行程规划",
    "不需要行程",
    "不需要景点",
    "不需要天气",
    "不需要路线",
    "不需要预算",
    "今天不需要景点",
    "暂时不要制定旅行计划",
    "暂时不要制定旅游计划",
    "不要制定旅行计划",
    "不要制定旅游计划",
    "只是想了解",
    "只是来道个晚安",
    "不用旅行规划",
    "不用旅游规划",
    "不用行程规划",
    "只是测试一下对话",
    "只是测试对话",
    "只测试对话",
    "do not need travel planning",
    "don't need travel planning",
    "dont need travel planning",
    "no need for travel planning",
    "no travel planning",
    "not need travel planning",
    "do not need trip planning",
    "don't need trip planning",
    "dont need trip planning",
    "no need for trip planning",
    "no trip planning",
    "do not need a plan",
    "don't need a plan",
    "dont need a plan",
    "no need for a plan",
    "do not plan",
    "no more planning",
    "no more trip planning",
    "no more travel planning",
    "no planning for now",
    "no more planning for now",
    "don't plan",
    "dont plan",
    "only saying hi",
    "just saying hi",
    "just greeting",
)
ATTRACTION_SINGLE_SCOPE_TERMS = (
    "只帮我挑",
    "只推荐",
    "只要景点",
    "只看景点",
    "只挑",
    "不要生成完整行程",
    "不要完整行程",
    "不需要完整行程",
    "不要天气",
    "不需要天气",
    "别查天气",
    "不要行程",
    "不需要行程",
    "不要预算",
    "不需要预算",
    "only attractions",
    "attractions only",
    "only poi",
    "poi only",
)
NEGATED_FULL_TRIP_PLAN_TERMS = (
    "不要生成完整行程",
    "不要生成完整计划",
    "不要生成完整旅游计划",
    "不要生成完整旅行计划",
    "不要生成完整旅游方案",
    "不要生成完整旅行方案",
    "不要完整行程",
    "不需要完整行程",
    "不用完整行程",
    "别生成完整行程",
)
WEATHER_SINGLE_SCOPE_TERMS = (
    "只查天气",
    "仅查天气",
    "只看天气",
    "只要天气",
    "查询天气",
    "查天气",
    "查一下",
    "天气怎么样",
    "天气如何",
    "天气风险",
    "weather only",
    "only weather",
    "weather forecast",
    "check weather",
    "what is the weather",
)
BUDGET_PLANNING_ACTION_TERMS = (
    "plan",
    "itinerary",
    "schedule",
    "route",
    "规划",
    "行程",
    "安排",
)
BUDGET_SINGLE_SCOPE_TERMS = (
    "只估算",
    "只算",
    "估算",
    "是否够用",
    "够不够",
    "不要生成景点",
    "不要景点清单",
    "不需要景点清单",
    "不要推荐景点",
    "不要天气",
    "不需要天气",
    "不要行程",
    "不需要行程",
    "budget only",
    "only budget",
    "rough budget",
)
DESTINATION_RECOMMENDATION_TERMS = (
    "去哪",
    "哪里",
    "去哪儿",
    "有什么合适",
    "合适的安排",
    "推荐目的地",
    "推荐去哪",
    "适合去哪",
)
WEATHER_CLIMATE_TERMS = (
    "月份天气",
    "月天气",
    "十一月份",
    "十一月",
    "11月份",
    "11月",
    "季节",
    "全年",
    "一般天气",
    "climate",
    "seasonal weather",
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
    dependency_policy: dict[str, Any] = field(default_factory=dict)
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
    invalidation_propagation_enabled: bool = True
    initial_invalidated_agents: list[str] = field(default_factory=list)
    propagated_invalidated_agents: list[str] = field(default_factory=list)
    final_invalidated_agents: list[str] = field(default_factory=list)
    propagation_candidates: list[str] = field(default_factory=list)
    propagation_reasons: list[str] = field(default_factory=list)

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
        explicit_missing_slots = [
            slot
            for slot in self._explicit_clarification_missing_slots(user_input)
            if slot not in effective_current or _is_empty_value(effective_current.get(slot))
        ]
        missing_slots = (
            explicit_missing_slots
            or self._missing_slots(
                preliminary_task_type,
                effective_current,
                previous_state,
            )
        )
        task_type = (
            "clarification"
            if (
                missing_slots
                and preliminary_task_type != "general_chat"
            )
            or explicit_missing_slots
            else preliminary_task_type
        )
        clarification_required = task_type == "clarification"
        clarification_fields = list(missing_slots) if clarification_required else []
        required_capabilities = self._required_capabilities(
            task_type,
            changed_slots,
            goal_change_type=goal_change_type,
        )
        dependency_policy = self._dependency_policy(
            task_type=task_type,
            user_input=user_input,
            changed_slots=changed_slots,
        )

        return GoalStateTaskTicket(
            task_type=task_type,
            current_slots=effective_current,
            previous_slots=previous_slots,
            changed_slots=changed_slots,
            preserved_slots=preserved_slots,
            missing_slots=missing_slots,
            required_capabilities=required_capabilities,
            dependency_policy=dependency_policy,
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
        text = _normalize_text(user_input)
        explicit_replan_requested = _contains_any(
            text,
            EXPLICIT_REPLAN_TERMS,
        ) and not _has_negated_replan_request(text)
        if changed_slots and explicit_replan_requested:
            return "explicit_replan"
        if changed_slots:
            return "slot_delta"
        if explicit_replan_requested:
            return "explicit_replan"
        if _contains_any(text, ATTRACTION_EXPANSION_TERMS):
            return "goal_shift_attraction"
        if _contains_any(text, IDENTICAL_REQUEST_TERMS):
            return "identical_request"
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
        has_weather_signal = _has_weather_text(text)
        has_weather_signal = has_weather_signal or "weather_scenario" in current_slots
        has_trip_signal = _has_trip_text(text)
        has_attraction_signal = _has_attraction_text(text)
        has_budget_signal = _has_budget_text(text)
        budget_single_scope = _is_budget_single_scope_request(text)
        ticket_budget_single_scope = _is_ticket_budget_single_scope_request(text)
        strict_budget_single_scope = (
            ticket_budget_single_scope or _is_strict_budget_single_scope_request(text)
        )
        budget_query_requested = (
            strict_budget_single_scope
            or ticket_budget_single_scope
            or (budget_single_scope and not _is_preserved_budget_statement(text))
        )
        full_planning_priority = _is_multi_capability_trip_planning_request(
            text,
            current_slots=current_slots,
        )
        explicit_full_plan = _is_explicit_full_trip_planning_request(
            text,
            current_slots=current_slots,
        )
        explicit_weather_only = _is_weather_single_scope_request(text)
        complete_trip_slots = all(
            slot in current_slots
            for slot in ("destination", "duration_days", "people_count")
        )
        has_start_date = "start_date" in current_slots

        if _is_general_chat_only_request(text):
            return "general_chat"

        if not has_previous and not current_slots and _is_general_chat_only_request(text):
            return "general_chat"

        if not current_slots and not has_previous and not _contains_any(
            text,
            TRIP_TERMS + ATTRACTION_TERMS + WEATHER_TERMS + BUDGET_TERMS,
        ):
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
            if has_weather_signal and (
                _contains_any(text, REPLAN_TERMS) or "weather_scenario" in changed_slots
            ):
                return "weather_adjustment"
            if explicit_full_plan or full_planning_priority:
                return "partial_replan"
            if set(changed_slots) & {
                "preferences",
                "budget_amount",
                "budget_level",
                "special_requirements",
            }:
                return "partial_replan"
            if "people_count" in changed_slots and not budget_query_requested:
                return "partial_replan"
            budget_query_delta_slots = {"people_count", "budget_amount", "budget_level"}
            if (
                has_budget_signal
                and not _contains_any(text, REPLAN_ACTION_TERMS)
                and budget_query_requested
                and set(changed_slots) <= budget_query_delta_slots
            ):
                return "budget_query"
            if changed_slots:
                return "partial_replan"
            if has_attraction_signal:
                return "attraction_recommendation"
            if has_weather_signal:
                return "weather_query"
            if _contains_any(text, TRIP_TERMS + REPLAN_TERMS):
                return "partial_replan"
            return "general_chat"

        if _is_weather_climate_question(text):
            return "weather_climate_question"
        if _is_destination_recommendation_request(text, current_slots=current_slots):
            return "destination_recommendation"
        if explicit_weather_only:
            return "weather_forecast_query" if "未来" in text else "weather_query"
        if has_attraction_signal and _is_attraction_single_scope_request(text):
            return "attraction_recommendation"
        if strict_budget_single_scope:
            return "budget_query"
        if (explicit_full_plan or full_planning_priority) and complete_trip_slots:
            return "weather_aware_trip_plan" if has_start_date else "trip_plan"
        if explicit_full_plan:
            return "trip_planning"
        if ticket_budget_single_scope or budget_single_scope:
            return "budget_query"
        if has_trip_signal and complete_trip_slots:
            return "weather_aware_trip_plan" if has_start_date else "trip_plan"
        if has_weather_signal and _is_weather_single_scope_request(text):
            return "weather_query"
        if has_trip_signal and any(
            slot in current_slots for slot in ("start_date", "duration_days", "people_count")
        ):
            return "weather_aware_trip_plan" if has_start_date else "trip_plan"
        if has_budget_signal:
            return "budget_query"
        if has_attraction_signal and not any(slot in current_slots for slot in ("start_date", "duration_days", "people_count")):
            return "attraction_recommendation"
        if has_weather_signal:
            return "weather_query"
        if has_trip_signal or any(slot in current_slots for slot in ("start_date", "duration_days", "people_count")):
            return "weather_aware_trip_plan" if has_start_date else "trip_plan"
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
            required = ("destination",)
            return [slot for slot in required if slot not in current_slots]

        required = TASK_REQUIRED_SLOTS.get(task_type, ())
        return [slot for slot in required if slot not in current_slots]

    def _required_capabilities(
        self,
        task_type: str,
        changed_slots: list[str],
        *,
        goal_change_type: str = "none",
    ) -> list[str]:
        if task_type != "partial_replan":
            return list(TASK_CAPABILITIES.get(task_type, ()))

        capabilities: list[str] = []
        if "destination" in changed_slots:
            capabilities.extend(TASK_CAPABILITIES["trip_planning"])
        if "duration_days" in changed_slots:
            capabilities.extend(("weather_evidence", "itinerary_generation", "budget_estimation"))
        if "start_date" in changed_slots:
            capabilities.extend(("weather_evidence", "itinerary_generation", "budget_estimation"))
        if "people_count" in changed_slots:
            capabilities.extend(("itinerary_generation", "budget_estimation"))
        if "origin" in changed_slots:
            capabilities.append("budget_estimation")
        if any(
            slot in changed_slots
            for slot in ("traveler_group", "preferences", "special_requirements")
        ):
            capabilities.extend(("poi_evidence", "itinerary_generation", "budget_estimation"))
        if any(slot in changed_slots for slot in ("budget_amount", "budget_level")):
            if goal_change_type == "explicit_replan":
                capabilities.extend(("itinerary_generation", "budget_estimation"))
            else:
                capabilities.append("budget_estimation")
        if "weather_scenario" in changed_slots:
            capabilities.extend(("weather_evidence", "itinerary_generation"))
        return _ordered_unique_capabilities(capabilities)

    def _dependency_policy(
        self,
        *,
        task_type: str,
        user_input: str,
        changed_slots: list[str],
    ) -> dict[str, Any]:
        if task_type == "partial_replan" and set(changed_slots) == {"origin"}:
            return {
                "origin_change_scope": (
                    "itinerary_budget"
                    if _origin_change_requests_itinerary_replan(user_input)
                    else "budget_only"
                )
            }

        if task_type != "budget_query":
            return {}

        requires_attraction = _budget_query_requires_attraction_evidence(user_input)
        return {
            "budget_scope": (
                "ticket_budget_requires_attraction_evidence"
                if requires_attraction
                else "rough_budget_without_ticket_dependency"
            ),
            "requires_attraction_evidence": requires_attraction,
        }

    def _explicit_clarification_missing_slots(self, user_input: str) -> list[str]:
        text = _normalize_text(user_input)
        if _budget_query_needs_budget_amount(text):
            return ["budget_amount"]
        explicit_clarification_request = _is_explicit_clarification_request(text)
        if not explicit_clarification_request and not _contains_any(
            text,
            (
                "缺失",
                "没说",
                "未说",
                "没有说",
                "还没确定",
                "没确定",
                "未确定",
                "请先向我确认",
                "先确认",
                "补充什么",
                "missing",
                "clarify",
            ),
        ):
            return []
        slots: list[str] = []
        if _contains_any(text, ("目的地", "城市", "去哪", "destination", "city")):
            slots.append("destination")
        if _contains_any(text, ("出发日期", "日期", "时间", "什么时候", "什么时候走", "何时", "start_date", "start date", "date")):
            slots.append("start_date")
        if _contains_any(text, ("旅行天数", "旅游天数", "天数", "几天", "duration", "days")):
            slots.append("duration_days")
        if _contains_any(text, ("出行人数", "人数", "几个人", "people", "traveler")):
            slots.append("people_count")
        if _contains_any(text, ("预算", "费用", "多少钱", "花多少钱", "budget", "cost")):
            slots.append("budget_amount")
        if not slots and explicit_clarification_request:
            slots.extend(["destination", "duration_days", "people_count"])
        return [slot for slot in CANONICAL_SLOT_ORDER if slot in set(slots)]


class GoalStateScheduler:
    """Select the minimal required agents/tools from a goal-state ticket."""

    def __init__(
        self,
        *,
        invalidation_propagation_enabled: bool = (
            INVALIDATION_PROPAGATION_DEFAULT_ENABLED
        ),
    ) -> None:
        self.invalidation_propagation_enabled = bool(
            invalidation_propagation_enabled
        )

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

        if ticket.task_type == "weather_aware_trip_plan":
            return self._decision(
                planned_agents=list(CANONICAL_AGENT_ORDER),
                decision_reasons=["new_weather_aware_plan"],
            )

        if ticket.task_type == "trip_plan":
            return self._decision(
                planned_agents=["attraction", "itinerary", "budget"],
                decision_reasons=["new_trip_plan_without_weather"],
            )

        if ticket.task_type == "destination_recommendation":
            return self._decision(decision_reasons=["destination_recommendation_no_tools"])

        if ticket.task_type == "attraction_recommendation":
            return self._decision(
                planned_agents=["attraction"],
                decision_reasons=["single_capability_request"],
            )

        if ticket.task_type == "weather_climate_question":
            return self._decision(decision_reasons=["weather_climate_no_forecast_tool"])

        if ticket.task_type == "weather_forecast_query":
            return self._decision(
                planned_agents=["weather"],
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
            if _has_available_result(
                previous_state,
                "weather",
                _reuse_slots_for_ticket_agent(ticket, "weather"),
            ):
                return self._decision_with_reuse_validation(
                    ticket=ticket,
                    previous_state=previous_state,
                    planned_agents=["itinerary", "budget"],
                    invalidated_agents=["itinerary", "budget"],
                    decision_reasons=["weather_adjustment_reuses_previous_weather"],
                    reuse_scope_agents=["attraction", "weather"],
                )
            return self._decision_with_reuse_validation(
                ticket=ticket,
                previous_state=previous_state,
                planned_agents=["weather", "itinerary", "budget"],
                invalidated_agents=["weather", "itinerary", "budget"],
                initial_invalidated_agents=["weather", "budget"],
                propagated_invalidated_agents=["itinerary"],
                decision_reasons=["weather_changed_itinerary_adjustment"],
                reuse_scope_agents=["attraction", "itinerary"],
            )

        if ticket.task_type == "partial_replan":
            return self._schedule_partial_replan(ticket, previous_state)

        return self._decision(decision_reasons=["general_chat_no_agents"])

    def _schedule_budget_query(
        self,
        ticket: GoalStateTaskTicket,
        previous_state: Mapping[str, Any] | None,
    ) -> SchedulerDecision:
        requires_attraction_evidence = bool(
            (ticket.dependency_policy or {}).get("requires_attraction_evidence")
        )
        if "people_count" in ticket.changed_slots and _has_available_result(
            previous_state,
            "attraction",
            ticket.current_slots,
        ):
            return self._decision_with_reuse_validation(
                ticket=ticket,
                previous_state=previous_state,
                planned_agents=["itinerary", "budget"],
                invalidated_agents=["itinerary", "budget"],
                decision_reasons=["people_count_changed_itinerary_budget_replan"],
                reuse_scope_agents=["attraction", "weather"],
            )

        if _has_available_result(
            previous_state,
            "attraction",
            ticket.current_slots,
        ):
            return self._decision_with_reuse_validation(
                ticket=ticket,
                previous_state=previous_state,
                planned_agents=["budget"],
                decision_reasons=[
                    "ticket_budget_uses_reused_attraction"
                    if requires_attraction_evidence
                    else "single_capability_request"
                ],
                reuse_scope_agents=["attraction"],
            )

        if not requires_attraction_evidence:
            return self._decision(
                planned_agents=["budget"],
                decision_reasons=["rough_budget_without_ticket_dependency"],
                reuse_validation=self._reuse_validation(
                    ticket,
                    previous_state,
                    final_reused_agents=[],
                    final_invalidated_agents=[],
                    final_planned_agents=["budget"],
                ),
            )

        return self._decision_with_reuse_validation(
            ticket=ticket,
            previous_state=previous_state,
            planned_agents=["attraction", "budget"],
            decision_reasons=["ticket_budget_requires_attraction_evidence"],
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

        if changed == {"origin"}:
            if (ticket.dependency_policy or {}).get("origin_change_scope") == "itinerary_budget":
                return self._decision_with_reuse_validation(
                    ticket=ticket,
                    previous_state=previous_state,
                    planned_agents=["itinerary", "budget"],
                    invalidated_agents=["itinerary", "budget"],
                    decision_reasons=["origin_changed_itinerary_budget_replan"],
                    reuse_scope_agents=["attraction", "weather"],
                )
            return self._decision_with_reuse_validation(
                ticket=ticket,
                previous_state=previous_state,
                planned_agents=["budget"],
                invalidated_agents=["budget"],
                decision_reasons=["origin_changed_budget_only"],
                reuse_scope_agents=["attraction", "weather", "itinerary"],
            )

        planned_agents: list[str] = []
        invalidated_agents: list[str] = []
        initial_invalidated_agents: list[str] = []
        decision_reasons: list[str] = []

        if "duration_days" in changed:
            weather_required = _slots_require_weather_for_itinerary(ticket.current_slots)
            duration_agents = (
                ["weather", "itinerary", "budget"]
                if weather_required
                else ["itinerary", "budget"]
            )
            planned_agents.extend(duration_agents)
            invalidated_agents.extend(duration_agents)
            initial_invalidated_agents.extend(
                ["weather", "budget"]
                if weather_required
                else ["itinerary", "budget"]
            )
            decision_reasons.append("duration_changed_partial_replan")

        if "start_date" in changed:
            planned_agents.extend(["weather", "itinerary", "budget"])
            invalidated_agents.extend(["weather", "itinerary", "budget"])
            initial_invalidated_agents.extend(["weather", "budget"])
            decision_reasons.append("date_changed_weather_itinerary_budget_replan")

        if "people_count" in changed:
            planned_agents.extend(["itinerary", "budget"])
            invalidated_agents.extend(["itinerary", "budget"])
            initial_invalidated_agents.extend(["itinerary", "budget"])
            decision_reasons.append("people_count_changed_itinerary_budget_replan")

        if "traveler_group" in changed:
            planned_agents.extend(["attraction", "itinerary", "budget"])
            invalidated_agents.extend(["attraction", "itinerary", "budget"])
            initial_invalidated_agents.append("attraction")
            decision_reasons.append("traveler_group_changed_replan")

        if "preferences" in changed:
            planned_agents.extend(["attraction", "itinerary", "budget"])
            invalidated_agents.extend(["attraction", "itinerary", "budget"])
            initial_invalidated_agents.append("attraction")
            decision_reasons.append("preferences_changed_replan")

        if "special_requirements" in changed:
            planned_agents.extend(["attraction", "itinerary", "budget"])
            invalidated_agents.extend(["attraction", "itinerary", "budget"])
            initial_invalidated_agents.append("attraction")
            decision_reasons.append("special_requirements_changed_replan")

        if changed & {"budget_amount", "budget_level"}:
            if ticket.goal_change_type == "explicit_replan":
                planned_agents.extend(["itinerary", "budget"])
                invalidated_agents.extend(["itinerary", "budget"])
                initial_invalidated_agents.extend(["itinerary", "budget"])
                decision_reasons.append("budget_changed_itinerary_budget_replan")
            else:
                planned_agents.append("budget")
                invalidated_agents.append("budget")
                initial_invalidated_agents.append("budget")
                decision_reasons.append("budget_changed_budget_only")

        if "weather_scenario" in changed:
            planned_agents.extend(["weather", "itinerary"])
            invalidated_agents.extend(["weather", "itinerary"])
            initial_invalidated_agents.append("weather")
            decision_reasons.append("weather_changed_itinerary_adjustment")

        if planned_agents or invalidated_agents:
            initial_set = set(_ordered_agents(initial_invalidated_agents))
            propagated_invalidated_agents = [
                agent
                for agent in _ordered_agents(invalidated_agents)
                if agent not in initial_set
            ]
            return self._decision_with_reuse_validation(
                ticket=ticket,
                previous_state=previous_state,
                planned_agents=planned_agents,
                invalidated_agents=invalidated_agents,
                initial_invalidated_agents=initial_invalidated_agents,
                propagated_invalidated_agents=propagated_invalidated_agents,
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
        initial_invalidated_agents: list[str] | None = None,
        propagated_invalidated_agents: list[str] | None = None,
        propagation_candidates: list[str] | None = None,
        propagation_reasons: list[str] | None = None,
        clarification_required: bool = False,
        clarification_fields: list[str] | None = None,
        decision_reasons: list[str] | None = None,
        reuse_validation: dict[str, Any] | None = None,
    ) -> SchedulerDecision:
        ordered_planned_agents = _ordered_agents(planned_agents or [])
        ordered_invalidated_agents = _ordered_agents(invalidated_agents or [])
        ordered_initial_invalidated_agents = _ordered_agents(
            ordered_invalidated_agents
            if initial_invalidated_agents is None
            else initial_invalidated_agents
        )
        ordered_propagated_invalidated_agents = _ordered_agents(
            propagated_invalidated_agents or []
        )
        ordered_propagation_candidates = _ordered_agents(
            propagation_candidates
            if propagation_candidates is not None
            else ordered_propagated_invalidated_agents
        )
        return SchedulerDecision(
            planned_agents=ordered_planned_agents,
            planned_tools=_tools_for_agents(ordered_planned_agents),
            reused_agents=_ordered_agents(reused_agents or []),
            invalidated_agents=ordered_invalidated_agents,
            clarification_required=clarification_required,
            clarification_fields=clarification_fields or [],
            decision_reasons=decision_reasons or [],
            reuse_validation=reuse_validation or {},
            invalidation_propagation_enabled=self.invalidation_propagation_enabled,
            initial_invalidated_agents=ordered_initial_invalidated_agents,
            propagated_invalidated_agents=ordered_propagated_invalidated_agents,
            final_invalidated_agents=ordered_invalidated_agents,
            propagation_candidates=ordered_propagation_candidates,
            propagation_reasons=list(dict.fromkeys(propagation_reasons or [])),
        )

    def _decision_with_reuse_validation(
        self,
        *,
        ticket: GoalStateTaskTicket,
        previous_state: Mapping[str, Any] | None,
        planned_agents: list[str] | None = None,
        invalidated_agents: list[str] | None = None,
        initial_invalidated_agents: list[str] | None = None,
        propagated_invalidated_agents: list[str] | None = None,
        decision_reasons: list[str] | None = None,
        reuse_scope_agents: list[str] | None = None,
    ) -> SchedulerDecision:
        planned = list(planned_agents or [])
        invalidated = list(invalidated_agents or [])
        initial_invalidated = list(
            invalidated
            if initial_invalidated_agents is None
            else initial_invalidated_agents
        )
        declared_propagation_candidates = list(propagated_invalidated_agents or [])
        propagation_candidates = list(declared_propagation_candidates)
        applied_propagation = (
            list(declared_propagation_candidates)
            if self.invalidation_propagation_enabled
            else []
        )
        propagation_reasons: list[str] = []
        if declared_propagation_candidates:
            propagation_reasons.append("slot_change_downstream_invalidation")

        if not self.invalidation_propagation_enabled:
            suppressed = set(_ordered_agents(declared_propagation_candidates))
            planned = [agent for agent in planned if agent not in suppressed]
            invalidated = [agent for agent in invalidated if agent not in suppressed]

        ignored_fingerprint_slots_by_agent: dict[str, tuple[str, ...]] = {}
        if not self.invalidation_propagation_enabled:
            ignored_changed_slots = tuple(ticket.changed_slots or [])
            ignored_fingerprint_slots_by_agent = dict.fromkeys(
                _ordered_agents(declared_propagation_candidates),
                ignored_changed_slots,
            )

        scope = tuple(_ordered_agents(reuse_scope_agents or list(CANONICAL_AGENT_ORDER)))
        excluded = tuple(_ordered_agents([*planned, *invalidated]))
        reusable_agents = self._available_agents(
            ticket,
            previous_state,
            exclude=excluded,
            scope=scope,
            ignored_fingerprint_slots_by_agent=ignored_fingerprint_slots_by_agent,
        )
        unusable_agents = self._unusable_agents(
            ticket,
            previous_state,
            exclude=excluded,
            scope=scope,
            ignored_fingerprint_slots_by_agent=ignored_fingerprint_slots_by_agent,
        )
        if not self.invalidation_propagation_enabled:
            for agent in _ordered_agents(declared_propagation_candidates):
                if agent not in reusable_agents and agent not in unusable_agents:
                    planned.append(agent)
        cascaded_unusable = self._cascade_unusable_agents(
            unusable_agents,
            previous_state,
            ticket=ticket,
        )
        unusable_set = set(unusable_agents)
        unusable_propagation_candidates = [
            agent for agent in cascaded_unusable if agent not in unusable_set
        ]
        if unusable_propagation_candidates:
            propagation_candidates.extend(unusable_propagation_candidates)
            propagation_reasons.append("unusable_upstream_downstream_invalidation")
            if self.invalidation_propagation_enabled:
                applied_propagation.extend(unusable_propagation_candidates)

        if unusable_agents or (
            self.invalidation_propagation_enabled and unusable_propagation_candidates
        ):
            initial_invalidated.extend(unusable_agents)
            planned.extend(unusable_agents)
            invalidated.extend(unusable_agents)
            if self.invalidation_propagation_enabled:
                planned.extend(unusable_propagation_candidates)
                invalidated.extend(unusable_propagation_candidates)
            if decision_reasons is None:
                decision_reasons = []
            if "previous_result_unusable_replan" not in decision_reasons:
                decision_reasons = [*decision_reasons, "previous_result_unusable_replan"]

        (
            planned,
            invalidated,
            reusable_agents,
            dependency_reasons,
            dependency_propagation,
            dependency_propagation_candidates,
        ) = self._enforce_dependencies(
            ticket=ticket,
            planned_agents=planned,
            invalidated_agents=invalidated,
            reusable_agents=reusable_agents,
        )
        if dependency_propagation_candidates:
            propagation_candidates.extend(dependency_propagation_candidates)
            propagation_reasons.append("planned_upstream_downstream_invalidation")
        if dependency_propagation:
            applied_propagation.extend(dependency_propagation)
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
            initial_invalidated_agents=initial_invalidated,
            propagated_invalidated_agents=applied_propagation,
            propagation_candidates=propagation_candidates,
            propagation_reasons=propagation_reasons,
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
        ignored_fingerprint_slots_by_agent: Mapping[str, Iterable[str]] | None = None,
    ) -> list[str]:
        excluded = set(exclude)
        scoped_agents = scope or CANONICAL_AGENT_ORDER
        return [
            agent
            for agent in scoped_agents
            if agent not in excluded
            and _is_agent_reusable_for_ticket(
                agent,
                ticket=ticket,
                previous_state=previous_state,
                ignored_fingerprint_slots=(
                    ignored_fingerprint_slots_by_agent or {}
                ).get(agent, ()),
            )
        ]

    def _unusable_agents(
        self,
        ticket: GoalStateTaskTicket,
        previous_state: Mapping[str, Any] | None,
        *,
        exclude: tuple[str, ...] = (),
        scope: tuple[str, ...] | None = None,
        ignored_fingerprint_slots_by_agent: Mapping[str, Iterable[str]] | None = None,
    ) -> list[str]:
        excluded = set(exclude)
        scoped_agents = set(scope or CANONICAL_AGENT_ORDER)
        return [
            agent
            for agent in _raw_available_agents(previous_state)
            if agent not in excluded
            and agent in scoped_agents
            and not _is_agent_reusable_for_ticket(
                agent,
                ticket=ticket,
                previous_state=previous_state,
                ignored_fingerprint_slots=(
                    ignored_fingerprint_slots_by_agent or {}
                ).get(agent, ()),
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
                current_slots=_reuse_slots_for_ticket_agent(ticket, agent),
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
        *,
        ticket: GoalStateTaskTicket | None = None,
    ) -> list[str]:
        raw_available = set(_raw_available_agents(previous_state))
        cascaded = set(unusable_agents)
        for agent in list(unusable_agents):
            cascaded.update(
                dependent
                for dependent in DEPENDENT_AGENTS.get(agent, ())
                if dependent in raw_available
                and agent in _result_dependencies_for_ticket(dependent, ticket)
            )
        return _ordered_agents(list(cascaded))

    def _enforce_dependencies(
        self,
        *,
        ticket: GoalStateTaskTicket | None = None,
        planned_agents: list[str],
        invalidated_agents: list[str],
        reusable_agents: list[str],
    ) -> tuple[
        list[str],
        list[str],
        list[str],
        list[str],
        list[str],
        list[str],
    ]:
        planned = set(_ordered_agents(planned_agents))
        invalidated = set(_ordered_agents(invalidated_agents))
        reusable = set(_ordered_agents(reusable_agents))
        reasons: list[str] = []
        propagated: set[str] = set()
        propagation_candidates: set[str] = set()

        changed = True
        while changed:
            changed = False
            active_agents = planned | reusable
            for dependent in RESULT_DEPENDENCIES:
                upstream_agents = _result_dependencies_for_ticket(dependent, ticket)
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
                    propagation_candidates.add(dependent)
                    if self.invalidation_propagation_enabled:
                        reusable.remove(dependent)
                        planned.add(dependent)
                        invalidated.add(dependent)
                        propagated.add(dependent)
                        changed = True
                        if "dependent_result_invalidated" not in reasons:
                            reasons.append("dependent_result_invalidated")

        return (
            _ordered_agents(list(planned)),
            _ordered_agents(list(invalidated)),
            _ordered_agents(list(reusable)),
            reasons,
            _ordered_agents(list(propagated)),
            _ordered_agents(list(propagation_candidates)),
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
    invalidation_propagation_enabled: bool = INVALIDATION_PROPAGATION_DEFAULT_ENABLED,
) -> SchedulerDecision:
    return GoalStateScheduler(
        invalidation_propagation_enabled=invalidation_propagation_enabled
    ).schedule(ticket, previous_state=previous_state)


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


def _result_dependencies_for_ticket(
    agent_name: str,
    ticket: GoalStateTaskTicket | None,
) -> tuple[str, ...]:
    dependencies = list(RESULT_DEPENDENCIES.get(agent_name, ()))
    if agent_name == "itinerary" and "weather" in dependencies:
        if not _ticket_requires_weather_for_itinerary(ticket):
            dependencies.remove("weather")
    if (
        agent_name == "budget"
        and "itinerary" not in dependencies
        and _ticket_requires_itinerary_for_budget(ticket)
    ):
        dependencies.append("itinerary")
    return tuple(dependencies)


def _result_dependencies_for_slots(
    agent_name: str,
    slots: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    dependencies = list(RESULT_DEPENDENCIES.get(agent_name, ()))
    if agent_name == "itinerary" and "weather" in dependencies:
        if not _slots_require_weather_for_itinerary(slots):
            dependencies.remove("weather")
    return tuple(dependencies)


def _ticket_requires_weather_for_itinerary(
    ticket: GoalStateTaskTicket | None,
) -> bool:
    if ticket is None:
        return True
    if ticket.task_type == "trip_plan":
        return False
    if ticket.task_type == "partial_replan" and not _slots_require_weather_for_itinerary(
        ticket.current_slots
    ):
        return False
    if "weather_evidence" in set(ticket.required_capabilities or []):
        return True
    return _slots_require_weather_for_itinerary(ticket.current_slots)


def _ticket_requires_itinerary_for_budget(
    ticket: GoalStateTaskTicket | None,
) -> bool:
    if ticket is None:
        return False
    if ticket.task_type == "budget_query":
        return False
    if ticket.task_type in {
        "trip_planning",
        "trip_plan",
        "weather_aware_trip_plan",
        "partial_replan",
        "weather_adjustment",
    }:
        return True
    return "itinerary_generation" in set(ticket.required_capabilities or [])


def _slots_require_weather_for_itinerary(slots: Mapping[str, Any] | None) -> bool:
    normalized = normalize_slots(slots)
    return bool(normalized.get("start_date") or normalized.get("weather_scenario"))


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
        if key in {"destination", "origin"}:
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


def _has_negated_replan_request(text: str) -> bool:
    """Return True when replan words are explicitly negated by the user.

    This keeps requests such as "不用重新安排行程" from being interpreted as an
    explicit itinerary rerun merely because they contain "重新安排".
    """
    return _has_any(
        text,
        (
            "\u4e0d\u7528\u91cd\u65b0\u5b89\u6392",
            "\u4e0d\u7528\u91cd\u65b0\u89c4\u5212",
            "\u4e0d\u8981\u91cd\u65b0\u5b89\u6392",
            "\u4e0d\u8981\u91cd\u65b0\u89c4\u5212",
            "\u4e0d\u91cd\u65b0\u5b89\u6392",
            "\u4e0d\u91cd\u65b0\u89c4\u5212",
            "\u65e0\u9700\u91cd\u65b0\u5b89\u6392",
            "\u65e0\u9700\u91cd\u65b0\u89c4\u5212",
            "\u4e0d\u7528\u91cd\u6392",
            "\u4e0d\u8981\u91cd\u6392",
            "\u4e0d\u91cd\u6392",
            "\u4e0d\u6362\u8def\u7ebf",
            "\u8def\u7ebf\u4e0d\u7528\u6539",
            "\u884c\u7a0b\u4e0d\u7528\u6539",
            "\u4e0d\u7528\u6539\u8def\u7ebf",
            "\u4e0d\u7528\u6539\u884c\u7a0b",
            "\u4e0d\u8c03\u6574\u884c\u7a0b",
            "\u4e0d\u7528\u8c03\u6574\u884c\u7a0b",
            "do not replan",
            "don't replan",
            "dont replan",
            "no need to replan",
            "do not redo",
            "don't redo",
            "keep the route unchanged",
            "keep the itinerary unchanged",
            "do not change the itinerary",
            "do not change the route",
        ),
    )


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _has_weather_text(text: str) -> bool:
    return _contains_any(text, WEATHER_TERMS) or _has_any(
        text,
        (
            "\u5929\u6c14",
            "\u5929\u6c14\u9884\u62a5",
            "\u9884\u62a5",
            "\u4e0b\u96e8",
            "\u964d\u96e8",
            "\u96e8",
            "\u9ad8\u6e29",
            "\u4f4e\u6e29",
            "\u51b7\u4e0d\u51b7",
            "\u70ed\u4e0d\u70ed",
        ),
    )


def _has_budget_text(text: str) -> bool:
    return _contains_any(text, BUDGET_TERMS) or _contains_any(
        text,
        TEXT_BUDGET_SIGNAL_TERMS,
    ) or _has_any(
        text,
        (
            "\u9884\u7b97",
            "\u8d39\u7528",
            "\u82b1\u8d39",
            "\u591a\u5c11\u94b1",
            "\u94b1\u591f\u5417",
            "\u591f\u5417",
            "\u591f\u4e0d\u591f",
            "\u80fd\u4e0d\u80fd\u8986\u76d6",
            "\u5269\u591a\u5c11",
            "\u7b97\u7b97",
            "\u5403\u4f4f\u884c",
            "\u63a7\u5236\u4f4f",
        ),
    )


def _has_attraction_text(text: str) -> bool:
    return _contains_any(text, ATTRACTION_TERMS) or _has_any(
        text,
        (
            "\u666f\u70b9",
            "\u666f\u533a",
            "\u573a\u9986",
            "\u535a\u7269\u9986",
            "\u5730\u6807",
            "\u6587\u5316\u8857\u533a",
            "\u5ba4\u5185\u573a\u9986",
            "\u503c\u5f97\u770b",
            "\u503c\u5f97\u53bb",
        ),
    )


def _has_trip_text(text: str) -> bool:
    return _contains_any(text, TRIP_TERMS) or _has_any(
        text,
        (
            "\u884c\u7a0b",
            "\u8def\u7ebf",
            "\u7ebf\u8def",
            "\u89c4\u5212",
            "\u8ba1\u5212",
            "\u5b89\u6392",
            "\u653b\u7565",
            "\u65c5\u6e38",
            "\u65c5\u884c",
            "\u51fa\u6e38",
        ),
    )


def _has_explicit_trip_plan_text(text: str) -> bool:
    return _has_any(
        text,
        (
            "\u5b8c\u6574\u884c\u7a0b",
            "\u5b8c\u6574\u89c4\u5212",
            "\u5b8c\u6574\u65c5\u6e38\u8ba1\u5212",
            "\u5b8c\u6574\u65c5\u884c\u8ba1\u5212",
            "\u5e2e\u6211\u5b89\u6392",
            "\u5e2e\u6211\u89c4\u5212",
            "\u505a\u4e2a\u884c\u7a0b",
            "\u505a\u4e00\u4efd\u884c\u7a0b",
            "\u6392\u4e2a\u884c\u7a0b",
            "\u6392\u4e00\u4e0b",
        ),
    ) or _contains_any(text, FULL_TRIP_PLAN_TERMS)


def _negates_non_attraction_work(text: str) -> bool:
    return _has_any(
        text,
        (
            "\u4e0d\u7528\u505a\u5b8c\u6574\u884c\u7a0b",
            "\u4e0d\u8981\u5b8c\u6574\u884c\u7a0b",
            "\u4e0d\u7528\u5b89\u6392\u884c\u7a0b",
            "\u4e0d\u8981\u884c\u7a0b",
            "\u5148\u522b\u7b97\u8d39\u7528\u548c\u8def\u7ebf",
            "\u4e0d\u7528\u7b97\u8d39\u7528",
            "\u4e0d\u7528\u7b97\u9884\u7b97",
            "\u4e0d\u7528\u6392\u8def\u7ebf",
            "\u5148\u4e0d\u8003\u8651",
            "\u53ea\u63a8\u8350\u666f\u70b9",
            "\u53ea\u9700\u8981\u51e0\u4e2a\u9009\u62e9",
        ),
    )


def _has_budget_only_text(text: str) -> bool:
    return _has_any(
        text,
        (
            "\u53ea\u7b97\u8d39\u7528",
            "\u53ea\u7b97",
            "\u53ea\u4f30\u7b97",
            "\u53ea\u60f3\u77e5\u9053",
            "\u5927\u6982\u9700\u8981\u591a\u5c11\u94b1",
            "\u5927\u6982\u8981\u591a\u5c11",
            "\u5e2e\u6211\u7b97\u7b97",
            "\u5e2e\u6211\u770b\u770b\u5927\u6982\u9700\u8981\u591a\u5c11\u94b1",
            "\u4e0d\u7528\u6392\u8def\u7ebf",
            "\u94b1\u591f\u5417",
            "\u591f\u5417",
            "\u591f\u4e0d\u591f",
            "\u80fd\u4e0d\u80fd\u8986\u76d6\u65c5\u884c\u8d39\u7528",
            "\u4f1a\u5269\u591a\u5c11",
            "\u5f53\u5730\u5403\u4f4f\u884c",
            "\u65c5\u884c\u8d39\u7528\u80fd\u4e0d\u80fd\u63a7\u5236\u4f4f",
            "\u80fd\u4e0d\u80fd\u63a7\u5236\u4f4f",
        ),
    )


def _is_explicit_clarification_request(text: str) -> bool:
    """Return True when the user explicitly asks the system to ask follow-up questions."""
    return _contains_any(
        text,
        (
            "请先问我",
            "先问我",
            "先追问我",
            "先跟我确认",
            "先向我确认",
            "请先向我确认",
            "请先确认",
            "都没想好",
            "都还没想好",
            "还没想好",
            "没想好",
            "没有想好",
            "不知道去哪",
            "不知道去哪里",
            "clarify first",
            "ask me first",
        ),
    )


def _is_weather_single_scope_request(text: str) -> bool:
    """Return True only for requests that clearly ask for weather evidence alone."""
    if not _has_weather_text(text):
        return False
    if re.search(r"(\u80fd\u67e5\u5230|\u80fd\u4e0d\u80fd\u67e5|\u67e5\u5f97\u5230).{0,12}\u5929\u6c14", text):
        return True
    if re.search(r"\u5929\u6c14.{0,8}(\u600e\u4e48\u6837|\u5982\u4f55|\u80fd\u4e0d\u80fd\u67e5|\u80fd\u67e5\u5230|\u80fd\u63d0\u524d\u67e5\u5230)", text):
        return True
    if _has_any(
        text,
        (
            "\u53ea\u770b\u5929\u6c14",
            "\u53ea\u67e5\u5929\u6c14",
            "\u4ec5\u67e5\u5929\u6c14",
            "\u53ea\u8981\u5929\u6c14",
            "\u4f1a\u4e0d\u4f1a\u4e0b\u96e8",
            "\u9002\u4e0d\u9002\u5408\u5b89\u6392\u6237\u5916",
            "\u51fa\u95e8\u9700\u8981\u51c6\u5907\u4ec0\u4e48",
        ),
    ):
        return True
    if _contains_any(text, WEATHER_SINGLE_SCOPE_TERMS):
        return True
    if any(term in text for term in ("只看", "只查", "仅查", "只要", "仅看")) and (
        "天气" in text or "weather" in text
    ):
        return True
    return not _contains_any(
        text,
        TRIP_TERMS + ATTRACTION_TERMS + BUDGET_TERMS,
    ) and not (_has_trip_text(text) or _has_attraction_text(text) or _has_budget_text(text))


def _is_weather_climate_question(text: str) -> bool:
    if _contains_any(text, WEATHER_TERMS) and _contains_any(text, WEATHER_CLIMATE_TERMS):
        return True
    if not _has_weather_text(text):
        return False
    climate_terms = (
        "\u901a\u5e38",
        "\u4e00\u822c",
        "\u5168\u5e74",
        "\u5b63\u8282",
        "\u6708\u4efd",
        "\u51b7\u4e0d\u51b7",
        "\u70ed\u4e0d\u70ed",
        "\u9700\u8981\u51c6\u5907\u4ec0\u4e48\u8863\u670d",
    )
    month_pattern = r"(?:\d{1,2}|\u5341\u4e00|\u5341\u4e8c|\u5341[\u4e00\u4e8c]?)\u6708(?:\u4efd)?"
    return _has_any(text, climate_terms) and bool(re.search(month_pattern, text))


def _is_destination_recommendation_request(
    text: str,
    *,
    current_slots: Mapping[str, Any],
) -> bool:
    if current_slots.get("destination"):
        return False
    if _has_any(
        text,
        (
            "\u63a8\u8350\u51e0\u4e2a\u76ee\u7684\u5730",
            "\u63a8\u8350\u51e0\u4e2a\u57ce\u5e02",
            "\u63a8\u8350\u51e0\u4e2a\u5730\u65b9",
            "\u5148\u63a8\u8350\u51e0\u4e2a\u5730\u65b9",
            "\u9002\u5408\u7684\u57ce\u5e02",
            "\u9002\u5408\u7684\u76ee\u7684\u5730",
            "\u53bb\u54ea\u91cc",
            "\u53bb\u54ea",
            "\u6709\u4ec0\u4e48\u5efa\u8bae",
        ),
    ):
        return True
    if not _contains_any(text, TRIP_TERMS + DESTINATION_RECOMMENDATION_TERMS):
        return False
    return _contains_any(text, DESTINATION_RECOMMENDATION_TERMS) or (
        _contains_any(text, BUDGET_TERMS)
        and _contains_any(text, ("旅游", "旅行", "出游", "出去玩", "出去旅游"))
    )


def _is_general_chat_only_request(text: str) -> bool:
    if _has_positive_single_scope_request(text):
        return False
    if _has_any(
        text,
        (
            "\u4eca\u5929\u4e0d\u505a\u65c5\u6e38\u653b\u7565",
            "\u4eca\u5929\u4e0d\u505a\u653b\u7565",
            "\u6682\u65f6\u6ca1\u6709\u51fa\u6e38\u8ba1\u5212",
            "\u6682\u65f6\u6ca1\u6709\u65c5\u884c\u8ba1\u5212",
            "\u6ca1\u6709\u51fa\u6e38\u8ba1\u5212",
            "\u53ea\u662f\u8fdb\u6765\u770b\u770b",
            "\u968f\u4fbf\u804a",
            "\u5148\u505c\u4e00\u4e0b",
            "\u4e0d\u7528\u7ee7\u7eed\u505a\u884c\u7a0b",
            "\u518d\u89c1",
            "\u6253\u4e2a\u62db\u547c",
            "\u8bb2\u4e00\u4e2a\u7b80\u77ed\u7684\u7b11\u8bdd",
            "\u600e\u4e48\u751f\u6210\u7684",
            "\u600e\u6837\u751f\u6210\u7684",
        ),
    ):
        return True
    if _contains_any(text, NEGATED_TRAVEL_PLANNING_TERMS):
        return True
    if not _contains_any(text, GENERAL_CHAT_TERMS):
        return False
    capability_question_terms = (
        "能做什么",
        "哪些建议",
        "哪些旅游问题",
        "帮我解决哪些旅游问题",
        "能帮我解决哪些",
    )
    return _contains_any(text, capability_question_terms)


def _has_positive_single_scope_request(text: str) -> bool:
    """Return True when a concrete domain request should override negated planning terms."""
    if _is_weather_single_scope_request(text):
        return True
    if (_contains_any(text, ATTRACTION_TERMS) or _has_attraction_text(text)) and _is_attraction_single_scope_request(text):
        return True
    if _is_strict_budget_single_scope_request(text) or _is_ticket_budget_single_scope_request(text):
        return True
    return False


def _is_attraction_single_scope_request(text: str) -> bool:
    if not (_contains_any(text, ATTRACTION_TERMS) or _has_attraction_text(text)):
        return False
    if _negates_non_attraction_work(text):
        return True
    if _contains_any(text, ATTRACTION_SINGLE_SCOPE_TERMS):
        return True
    if _has_any(text, ("\u6709\u54ea\u4e9b", "\u54ea\u4e9b", "\u503c\u5f97\u770b", "\u503c\u5f97\u53bb")) and not _has_explicit_trip_plan_text(text):
        return True
    return not _contains_any(text, TRIP_TERMS + WEATHER_TERMS + BUDGET_TERMS) and not (
        _has_trip_text(text) or _has_weather_text(text) or _has_budget_text(text)
    )


def _is_budget_single_scope_request(text: str) -> bool:
    has_budget_signal = _has_budget_text(text)
    if not has_budget_signal:
        return False
    if _is_local_budget_scope_modifier(text) and _has_explicit_trip_plan_text(text):
        return False
    if _has_budget_only_text(text):
        return True
    if _contains_any(text, BUDGET_SINGLE_SCOPE_TERMS):
        return True
    if "粗略估算" in text or ("估算" in text and ("控制在" in text or "元内" in text)):
        return True
    if _contains_any(text, WEATHER_TERMS + ATTRACTION_TERMS + TRIP_TERMS):
        return False
    return not _contains_any(text, BUDGET_PLANNING_ACTION_TERMS)


def _is_strict_budget_single_scope_request(text: str) -> bool:
    has_budget_signal = _has_budget_text(text)
    if not has_budget_signal:
        return False
    if _is_local_budget_scope_modifier(text) and _has_explicit_trip_plan_text(text):
        return False
    if _has_budget_only_text(text):
        return True
    strict_terms = (
        "\u53ea\u4f30\u7b97",
        "\u53ea\u7b97",
        "\u7c97\u7565\u4f30\u7b97",
        "\u662f\u5426\u591f\u7528",
        "\u591f\u4e0d\u591f",
        "\u662f\u5426\u80fd\u63a7\u5236",
        "\u63a7\u5236\u5728",
        "\u5143\u5185",
        "budget only",
        "only budget",
        "rough budget",
    )
    return _contains_any(text, strict_terms)


def _is_preserved_budget_statement(text: str) -> bool:
    if not _has_budget_text(text):
        return False
    return _has_any(
        text,
        (
            "\u9884\u7b97\u4e0d\u53d8",
            "\u9884\u7b97\u4e0a\u9650\u4e0d\u53d8",
            "\u603b\u9884\u7b97\u4e0d\u53d8",
            "\u4e0a\u9650\u4e0d\u53d8",
            "\u8d39\u7528\u4e0a\u9650\u4e0d\u53d8",
            "\u9884\u7b97\u4fdd\u6301\u4e0d\u53d8",
            "\u603b\u9884\u7b97\u4fdd\u6301\u4e0d\u53d8",
            "budget unchanged",
            "budget stays the same",
            "same budget",
            "keep the same budget",
        ),
    )


def _is_local_budget_scope_modifier(text: str) -> bool:
    return _has_any(
        text,
        (
            "\u53ea\u7b97\u5f53\u5730",
            "\u53ea\u8ba1\u7b97\u5f53\u5730",
            "\u53ea\u770b\u5f53\u5730",
            "\u5f53\u5730\u8d39\u7528",
            "\u5f53\u5730\u65c5\u884c\u8d39\u7528",
            "\u5f53\u5730\u5403\u4f4f\u884c",
            "\u76ee\u7684\u5730\u5f53\u5730",
            "\u4e0d\u542b\u5927\u4ea4\u901a",
            "\u4e0d\u5305\u542b\u5927\u4ea4\u901a",
            "\u4e0d\u7b97\u5927\u4ea4\u901a",
            "\u4e0d\u5305\u62ec\u5927\u4ea4\u901a",
            "\u4e0d\u542b\u57ce\u9645",
            "\u4e0d\u5305\u542b\u57ce\u9645",
            "\u4e0d\u7b97\u57ce\u9645",
            "\u4e0d\u5305\u62ec\u57ce\u9645",
        ),
    )


def _budget_query_needs_budget_amount(text: str) -> bool:
    if not _has_budget_text(text):
        return False
    return _has_any(
        text,
        (
            "\u591f\u4e0d\u591f",
            "\u591f\u5417",
            "\u80fd\u4e0d\u80fd\u591f",
            "\u63a7\u5236\u5728",
            "\u4e0d\u8d85\u8fc7",
            "\u4e0a\u9650",
            "\u603b\u9884\u7b97",
        ),
    )


def _is_ticket_budget_single_scope_request(text: str) -> bool:
    return (
        _contains_any(text, BUDGET_TERMS)
        and _budget_query_requires_attraction_evidence(text)
        and not _contains_any(text, BUDGET_PLANNING_ACTION_TERMS)
    )


def _is_multi_capability_trip_planning_request(
    text: str,
    *,
    current_slots: Mapping[str, Any],
) -> bool:
    """Prioritize full trip planning before single weather/budget/POI routing.

    A complete planning request must contain a planning signal and explicitly ask
    for at least two business capabilities among attraction, weather and budget.
    Budget also counts when it is provided as a parsed numeric slot from visible
    text, because users often write "5000元" without repeating "预算".
    """
    if not _has_trip_text(text):
        return False

    capability_count = 0
    if _has_attraction_text(text):
        capability_count += 1
    if _has_weather_text(text):
        capability_count += 1
    if (
        _has_budget_text(text)
        or "budget_amount" in current_slots
        or "budget_level" in current_slots
    ):
        capability_count += 1
    return capability_count >= 2


def _is_explicit_full_trip_planning_request(
    text: str,
    *,
    current_slots: Mapping[str, Any],
) -> bool:
    if not _contains_any(text, FULL_TRIP_PLAN_TERMS):
        return False
    if _is_general_chat_only_request(text):
        return False
    if _contains_any(text, NEGATED_FULL_TRIP_PLAN_TERMS):
        return False
    return _contains_any(text, TRIP_TERMS) or any(
        slot in current_slots for slot in ("start_date", "duration_days", "people_count")
    )


def _budget_query_requires_attraction_evidence(user_input: str) -> bool:
    text = _normalize_text(user_input)
    if _negates_attraction_ticket_cost(text):
        return False
    return _contains_any(text, BUDGET_ATTRACTION_DEPENDENCY_TERMS)


def _origin_change_requests_itinerary_replan(user_input: str) -> bool:
    text = _normalize_text(user_input)
    if not text:
        return False
    budget_only_terms = (
        "\u9884\u7b97",
        "\u8d39\u7528",
        "\u82b1\u8d39",
        "\u591a\u5c11\u94b1",
        "\u7b97\u94b1",
        "budget",
        "cost",
    )
    itinerary_terms = (
        "\u884c\u7a0b",
        "\u8def\u7ebf",
        "\u7ebf\u8def",
        "\u6bcf\u5929",
        "\u7b2c\u4e00\u5929",
        "\u7b2c1\u5929",
        "itinerary",
        "route",
    )
    explicit_itinerary_replan_terms = (
        "\u91cd\u65b0\u5b89\u6392",
        "\u91cd\u65b0\u89c4\u5212",
        "\u91cd\u6392",
        "\u8c03\u6574\u884c\u7a0b",
        "\u8c03\u6574\u8def\u7ebf",
        "\u8c03\u6574\u7ebf\u8def",
        "\u884c\u7a0b\u4e5f\u8c03",
        "\u8def\u7ebf\u4e5f\u8c03",
        "replan itinerary",
        "replan route",
        "adjust itinerary",
        "adjust route",
        "redo itinerary",
    )
    if (
        _contains_any(text, budget_only_terms)
        and not _contains_any(text, itinerary_terms)
    ):
        return False
    return _contains_any(text, explicit_itinerary_replan_terms)


def _negates_attraction_ticket_cost(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "不要计算具体景点门票",
            "不计算具体景点门票",
            "不要景点门票",
            "不需要景点门票",
            "不算景点门票",
            "不要计算门票",
            "不计算门票",
            "do not calculate attraction tickets",
            "do not include attraction tickets",
            "without attraction tickets",
        )
    )


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


def is_goal_state_agent_reusable_for_ticket(
    agent_name: str,
    *,
    ticket: GoalStateTaskTicket | Mapping[str, Any] | None,
    previous_state: Mapping[str, Any] | None,
    ignored_fingerprint_slots: Iterable[str] = (),
) -> bool:
    """Return whether a previous result is reusable under a concrete ticket.

    This keeps execution-time reuse aligned with scheduler-time reuse.  The
    distinction matters for weather-adjustment turns where newly mentioned
    preferences such as "indoor" describe how to rearrange the old itinerary,
    not a request to rerun the attraction search.
    """
    normalized_ticket = _ticket_from_mapping(ticket)
    if normalized_ticket is None:
        current_slots = (
            ticket.get("current_slots")
            if isinstance(ticket, Mapping)
            and isinstance(ticket.get("current_slots"), Mapping)
            else None
        )
        return _is_agent_reusable(
            agent_name,
            current_slots=current_slots,
            previous_state=previous_state,
            ignored_fingerprint_slots=ignored_fingerprint_slots,
        )
    return _is_agent_reusable_for_ticket(
        agent_name,
        ticket=normalized_ticket,
        previous_state=previous_state,
        ignored_fingerprint_slots=ignored_fingerprint_slots,
    )


def _ticket_from_mapping(
    ticket: GoalStateTaskTicket | Mapping[str, Any] | None,
) -> GoalStateTaskTicket | None:
    if isinstance(ticket, GoalStateTaskTicket):
        return ticket
    if not isinstance(ticket, Mapping):
        return None
    return GoalStateTaskTicket(
        task_type=str(ticket.get("task_type") or "general_chat"),
        current_slots=dict(ticket.get("current_slots") or {}),
        previous_slots=dict(ticket.get("previous_slots") or {}),
        changed_slots=[str(slot) for slot in ticket.get("changed_slots") or []],
        preserved_slots=[str(slot) for slot in ticket.get("preserved_slots") or []],
        missing_slots=[str(slot) for slot in ticket.get("missing_slots") or []],
        required_capabilities=[
            str(capability) for capability in ticket.get("required_capabilities") or []
        ],
        dependency_policy=dict(ticket.get("dependency_policy") or {}),
        clarification_required=bool(ticket.get("clarification_required")),
        clarification_fields=[
            str(field) for field in ticket.get("clarification_fields") or []
        ],
        goal_change_type=str(ticket.get("goal_change_type") or "none"),
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
            for upstream in _result_dependencies_for_slots(agent, canonical_slots)
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


def _is_agent_reusable_for_ticket(
    agent_name: str,
    *,
    ticket: GoalStateTaskTicket,
    previous_state: Mapping[str, Any] | None,
    ignored_fingerprint_slots: Iterable[str] = (),
) -> bool:
    return _is_agent_reusable(
        agent_name,
        current_slots=_reuse_slots_for_ticket_agent(ticket, agent_name),
        previous_state=previous_state,
        ignored_fingerprint_slots=ignored_fingerprint_slots,
    )


def _reuse_slots_for_ticket_agent(
    ticket: GoalStateTaskTicket,
    agent_name: str,
) -> Mapping[str, Any]:
    slots = dict(ticket.current_slots or {})
    if ticket.task_type == "weather_adjustment":
        if agent_name == "attraction":
            for slot in ("traveler_group", "preferences", "special_requirements"):
                if slot in set(ticket.changed_slots or []):
                    slots.pop(slot, None)
        if agent_name == "weather":
            slots.pop("weather_scenario", None)
    return slots


def _is_agent_reusable(
    agent_name: str,
    *,
    current_slots: Mapping[str, Any] | None,
    previous_state: Mapping[str, Any] | None,
    ignored_fingerprint_slots: Iterable[str] = (),
) -> bool:
    if agent_name not in CANONICAL_AGENT_ORDER:
        return False
    if not _agent_has_successful_artifact(agent_name, previous_state=previous_state):
        return False
    return _agent_fingerprint_matches(
        agent_name,
        current_slots=current_slots,
        previous_state=previous_state,
        ignored_fingerprint_slots=ignored_fingerprint_slots,
    )


def _agent_unusable_reason(
    agent_name: str,
    *,
    current_slots: Mapping[str, Any] | None,
    previous_state: Mapping[str, Any] | None,
    ignored_fingerprint_slots: Iterable[str] = (),
) -> str:
    if not _raw_agent_available(previous_state, agent_name):
        return "not_available"
    if not _agent_has_successful_artifact(agent_name, previous_state=previous_state):
        return "previous_result_failed"
    if not _agent_fingerprint_matches(
        agent_name,
        current_slots=current_slots,
        previous_state=previous_state,
        ignored_fingerprint_slots=ignored_fingerprint_slots,
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
    if _previous_state_failed(previous_state):
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
    if _previous_state_failed(previous_state):
        return False
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
    if any(
        _truthy_expired_flag(value)
        for value in (
            previous_state.get("expired"),
            previous_state.get("stale"),
            _nested_mapping(previous_state, "trace", "expired"),
            _nested_mapping(previous_state, "output", "expired"),
            _nested_mapping(previous_state, "raw_output", "expired"),
        )
    ):
        return True
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
    if _truthy_expired_flag(result.get("expired")) or _truthy_expired_flag(result.get("stale")):
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
    ignored_fingerprint_slots: Iterable[str] = (),
) -> bool:
    if not isinstance(previous_state, Mapping):
        return False
    expected = _agent_fingerprint_from_slots(agent_name, normalize_slots(current_slots))
    ignored_slots = set(ignored_fingerprint_slots)
    result_candidates = _agent_previous_result_fingerprint_candidates(
        agent_name,
        previous_state,
    )
    if result_candidates:
        return any(
            _fingerprint_candidate_matches(
                agent_name,
                expected,
                candidate,
                ignored_slots=ignored_slots,
            )
            for candidate in result_candidates
        )
    candidates = _agent_previous_fingerprint_candidates(agent_name, previous_state)
    if not candidates:
        return not _previous_tool_results_from_state(previous_state)
    return all(
        _fingerprint_candidate_matches(
            agent_name,
            expected,
            candidate,
            ignored_slots=ignored_slots,
        )
        for candidate in candidates
    )


def _agent_previous_fingerprint_candidates(
    agent_name: str,
    previous_state: Mapping[str, Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = _agent_previous_result_fingerprint_candidates(
        agent_name,
        previous_state,
    )

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


def _agent_previous_result_fingerprint_candidates(
    agent_name: str,
    previous_state: Mapping[str, Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in _previous_result_fingerprint_candidates(previous_state):
        agent_fingerprint = candidate.get(agent_name) if isinstance(candidate, Mapping) else None
        if not isinstance(agent_fingerprint, Mapping):
            continue
        normalized = _normalize_fingerprint(agent_fingerprint)
        if not normalized:
            continue
        key = repr(sorted(normalized.items(), key=lambda item: item[0]))
        if key in seen:
            continue
        seen.add(key)
        candidates.append(normalized)
    return candidates


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
                "origin": (
                    tool_input.get("origin")
                    or tool_input.get("from_city")
                    or tool_input.get("departure_city")
                ),
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
    *,
    ignored_slots: set[str] | None = None,
) -> bool:
    ignored = ignored_slots or set()
    comparable_slots = set(AGENT_FINGERPRINT_SLOTS.get(agent_name, ())) - ignored
    for slot, candidate_value in candidate.items():
        if slot in ignored or slot not in comparable_slots:
            continue
        if slot not in expected:
            if not _fingerprint_extra_missing_is_allowed(agent_name, slot, candidate_value):
                return False
            continue
        if _fingerprint_value(expected.get(slot)) != _fingerprint_value(candidate_value):
            return False
    for slot, expected_value in expected.items():
        if slot in ignored:
            continue
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


def _fingerprint_extra_missing_is_allowed(agent_name: str, slot: str, value: Any) -> bool:
    normalized = _fingerprint_value(value)
    if _is_empty_value(normalized):
        return True
    if slot == "traveler_group" and normalized == "general":
        return True
    if slot == "weather_scenario" and normalized == "sunny":
        return True
    if slot == "budget_level" and normalized == "medium":
        return True
    return False


def _truthy_expired_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "expired", "stale"}


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
