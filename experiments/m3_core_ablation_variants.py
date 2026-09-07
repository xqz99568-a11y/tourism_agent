"""Execution-only M3 core-ablation variants.

The formal benchmark runner and paper gates are intentionally kept out of this
module.  This module only defines the two frozen method variants so they can be
unit-tested before any model-backed experiment is allowed to run.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.experiment_method_contract import EVALUATOR_ONLY_FIELDS
from app.core.experiment_method_input import (
    METHOD_INPUT_SCHEMA_VERSION,
    parse_visible_request_slots,
)
from app.core.experiment_runner import ExperimentMethod, ExperimentRunner

M3_NO_STATE_METHOD = "adaptive_multi_agent_no_state"
M3_NO_PROPAGATION_METHOD = "adaptive_multi_agent_no_propagation"
M3_CORE_ABLATION_METHODS = (M3_NO_STATE_METHOD, M3_NO_PROPAGATION_METHOD)
STATELESS_ROUTER_SCHEMA_VERSION = "ctp-stateless-capability-router-v1"
M3_NO_STATE_EXECUTION_SCHEMA_VERSION = "ctp-m3-no-state-execution-v1"
M3_NO_PROPAGATION_EXECUTION_SCHEMA_VERSION = "ctp-m3-no-propagation-execution-v1"

_AGENT_ORDER = ("attraction", "weather", "itinerary", "budget")
_TOOLS_BY_AGENT = {
    "attraction": ("poi_search",),
    "weather": ("weather_query",),
    "itinerary": (),
    "budget": ("budget_calculator",),
}
_WEATHER_ADJUSTMENT_TERMS = (
    "天气",
    "降雨",
    "下雨",
    "高温",
    "weather",
    "rain",
    "temperature",
)
_ITINERARY_ACTION_TERMS = (
    "行程",
    "路线",
    "顺序",
    "重新安排",
    "重新规划",
    "调整",
    "室内",
    "户外",
    "休息",
    "itinerary",
    "route",
    "replan",
    "adjust",
)
_TRIP_TERMS = (
    "玩",
    "旅游",
    "旅行",
    "行程",
    "规划",
    "安排",
    "trip",
    "travel",
    "plan",
    "itinerary",
)
_ATTRACTION_TERMS = (
    "景点",
    "场馆",
    "博物馆",
    "attraction",
    "museum",
)
_WEATHER_QUERY_TERMS = (
    "天气",
    "气温",
    "下雨",
    "降雨",
    "高温",
    "weather",
    "temperature",
    "rain",
)


class M3CoreAblationRunner(ExperimentRunner):
    """Experiment runner exposing only the two frozen M3 core variants."""

    METHOD_ALIASES = {
        **ExperimentRunner.METHOD_ALIASES,
        "m3_no_state": M3_NO_STATE_METHOD,
        "m3-no-state": M3_NO_STATE_METHOD,
        "m3_no_propagation": M3_NO_PROPAGATION_METHOD,
        "m3-no-propagation": M3_NO_PROPAGATION_METHOD,
    }

    def _normalize_method(self, method: str) -> str:
        normalized = str(method or "").strip().lower()
        normalized = self.METHOD_ALIASES.get(normalized, normalized)
        if normalized in M3_CORE_ABLATION_METHODS:
            return normalized
        return super()._normalize_method(normalized)

    def _case_visible_to_generation(
        self,
        case: dict[str, Any],
        method: ExperimentMethod,
    ) -> dict[str, Any]:
        if method == M3_NO_STATE_METHOD:
            return self._stateless_generation_case(case)
        return super()._case_visible_to_generation(case, method)

    def _case_visible_to_result_worker(
        self,
        case: dict[str, Any],
        method: ExperimentMethod,
    ) -> dict[str, Any]:
        if method == M3_NO_STATE_METHOD:
            # The isolated worker also performs evaluation, so evaluator-only
            # labels must remain in its outer envelope.  Cross-turn structured
            # state and structured assistant history are removed before the
            # process boundary; `_case_visible_to_generation` independently
            # strips all evaluator-only fields before method execution.
            worker_case = dict(case)
            worker_case.pop("previous_state", None)
            worker_case.pop("method_previous_state", None)
            worker_case["dialogue_history"] = _role_content_history(
                case.get("dialogue_history")
            )
            return worker_case
        return super()._case_visible_to_result_worker(case, method)

    async def _dispatch_method(
        self,
        case: dict[str, Any],
        method: str,
        request_id: str,
    ) -> Any:
        if method == M3_NO_STATE_METHOD:
            return await self._run_adaptive_multi_agent_no_state(case, request_id)
        if method == M3_NO_PROPAGATION_METHOD:
            return await self._run_adaptive_multi_agent_no_propagation(
                case,
                request_id,
            )
        return await super()._dispatch_method(case, method, request_id)

    async def _run_adaptive_multi_agent_no_state(
        self,
        case: dict[str, Any],
        request_id: str,
    ) -> dict[str, Any]:
        stateless_case = self._stateless_generation_case(case)
        scheduler_metadata = self._stateless_scheduler_metadata(stateless_case)
        decision = self._scheduler_decision(scheduler_metadata)
        return await self._run_research_multi_agent(
            case=stateless_case,
            request_id=request_id,
            method=M3_NO_STATE_METHOD,
            planned_agents=list(decision.get("planned_agents") or []),
            planned_tools=list(decision.get("planned_tools") or []),
            scheduler_metadata=scheduler_metadata,
            initial_tool_results={},
        )

    async def _run_adaptive_multi_agent_no_propagation(
        self,
        case: dict[str, Any],
        request_id: str,
    ) -> dict[str, Any]:
        plan = self._select_adaptive_research_plan(
            case,
            invalidation_propagation_enabled=False,
        )
        previous_state = self._goal_state_previous_state(case)
        scheduler_metadata = self._no_propagation_scheduler_metadata(plan.get("scheduler"))
        reused_tool_results = self._reused_research_tool_results(
            previous_state=previous_state,
            scheduler_metadata=scheduler_metadata,
        )
        scheduler_metadata = self._scheduler_metadata_with_reuse_execution(
            scheduler_metadata=scheduler_metadata,
            previous_state=previous_state,
            reused_tool_results=reused_tool_results,
        )
        execution_case = self._case_with_goal_state_slots(
            case,
            scheduler_metadata=scheduler_metadata,
        )
        return await self._run_research_multi_agent(
            case=execution_case,
            request_id=request_id,
            method=M3_NO_PROPAGATION_METHOD,
            planned_agents=plan["agents"],
            planned_tools=plan["tools"],
            scheduler_metadata=scheduler_metadata,
            initial_tool_results=reused_tool_results,
        )

    def _stateless_generation_case(self, case: Mapping[str, Any]) -> dict[str, Any]:
        user_input = str(case.get("user_input") or "").strip()
        dialogue_history = _role_content_history(case.get("dialogue_history"))
        current_turn_slots = parse_visible_request_slots(user_input)
        removed_evaluator_fields = [field for field in EVALUATOR_ONLY_FIELDS if field in case]
        method_input = {
            "schema_version": METHOD_INPUT_SCHEMA_VERSION,
            "method": M3_NO_STATE_METHOD,
            "case_id": str(case.get("case_id") or ""),
            "user_input": user_input,
            "dialogue_history": dialogue_history,
            "parsed_slots": dict(current_turn_slots),
            "current_turn_slots": dict(current_turn_slots),
            "parser": {
                "name": "visible_text_rule_parser",
                "version": "2026-09-07-m3-no-state-v1",
                "source": "current_user_utterance_only",
            },
            "visibility": {
                "gold_visible": False,
                "evaluator_only_fields_removed": removed_evaluator_fields,
                "structured_previous_state_visible": False,
                "dialogue_history_policy": "role_content_only",
            },
        }
        generation_case: dict[str, Any] = {
            "case_id": str(case.get("case_id") or ""),
            "user_input": user_input,
            "dialogue_history": dialogue_history,
            "method_input": method_input,
            "method_input_schema_version": METHOD_INPUT_SCHEMA_VERSION,
            "parsed_slots": dict(current_turn_slots),
            "current_turn_slots": dict(current_turn_slots),
            "constraints": [],
            "evaluation_mode": str(case.get("evaluation_mode") or "end_to_end"),
            "stateless_ablation_method": M3_NO_STATE_METHOD,
        }
        for key in ("session_id", "conversation_id", "thread_id"):
            if case.get(key):
                generation_case[key] = case[key]
        return generation_case

    def _stateless_scheduler_metadata(
        self,
        case: Mapping[str, Any],
    ) -> dict[str, Any]:
        user_input = str(case.get("user_input") or "")
        current_turn_slots = (
            dict(case.get("current_turn_slots") or {})
            if isinstance(case.get("current_turn_slots"), Mapping)
            else parse_visible_request_slots(user_input)
        )
        history = _role_content_history(case.get("dialogue_history"))
        plan = _stateless_current_request_plan(
            user_input=user_input,
            current_turn_slots=current_turn_slots,
            dialogue_history=history,
        )
        return {
            "name": "stateless_current_request_capability_router",
            "schema_version": STATELESS_ROUTER_SCHEMA_VERSION,
            "policy": "current_request_capability_routing_no_goal_state_v1",
            "stateless_understanding": {
                "task_type": plan["task_type"],
                "current_turn_slots": dict(current_turn_slots),
                "capability_signals": list(plan["capability_signals"]),
                "source": "current_user_utterance_and_role_content_history",
            },
            "decision": {
                "schema_version": "ctp-stateless-capability-decision-v1",
                "planned_agents": list(plan["planned_agents"]),
                "planned_tools": list(plan["planned_tools"]),
                "reused_agents": [],
                "invalidated_agents": [],
                "decision_reasons": list(plan["decision_reasons"]),
                "reuse_validation": {},
            },
            "requires_weather_for_itinerary": bool(plan["requires_weather_for_itinerary"]),
            "requires_itinerary_for_budget": bool(plan["requires_itinerary_for_budget"]),
            "requires_attraction_for_budget": bool(plan["requires_attraction_for_budget"]),
            "ablation": {
                "schema_version": M3_NO_STATE_EXECUTION_SCHEMA_VERSION,
                "source_method": "adaptive_multi_agent_no_reuse",
                "ablation_method": M3_NO_STATE_METHOD,
                "structured_goal_state_ticket_used": False,
                "method_previous_state_visible": False,
                "previous_slots_visible": False,
                "changed_slots_available": False,
                "preserved_slots_available": False,
                "previous_agent_result_reuse_enabled": False,
                "previous_tool_result_reuse_enabled": False,
                "dialogue_history_policy": "role_content_only",
                "current_turn_slot_source": "current_user_utterance_only",
            },
        }

    def _no_propagation_scheduler_metadata(
        self,
        scheduler_metadata: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if scheduler_metadata is None:
            return None
        decision = self._scheduler_decision(scheduler_metadata)
        if decision.get("invalidation_propagation_enabled") is not False:
            raise ValueError("M3-no-propagation requires propagation to be disabled")
        return {
            **scheduler_metadata,
            "name": "goal_state_scheduler_no_propagation_ablation",
            "ablation": {
                "schema_version": M3_NO_PROPAGATION_EXECUTION_SCHEMA_VERSION,
                "source_method": "adaptive_multi_agent",
                "ablation_method": M3_NO_PROPAGATION_METHOD,
                "structured_goal_state_ticket_used": True,
                "result_reuse_enabled": True,
                "dependency_completion_enabled": True,
                "downstream_invalidation_propagation_enabled": False,
            },
        }

    def _records_adaptive_scheduler(self, method: ExperimentMethod) -> bool:
        return method in M3_CORE_ABLATION_METHODS or super()._records_adaptive_scheduler(method)

    def _infer_research_task_type(self, case: dict[str, Any]) -> str:
        if case.get("stateless_ablation_method") == M3_NO_STATE_METHOD:
            scheduler = self._stateless_scheduler_metadata(case)
            understanding = scheduler["stateless_understanding"]
            return self._canonical_research_task_type(understanding["task_type"])
        return super()._infer_research_task_type(case)

    def _research_method_metadata(
        self,
        *,
        method: ExperimentMethod,
        scheduler_metadata: dict[str, Any] | None,
        case: dict[str, Any] | None = None,
        result_agents: list[str] | None = None,
        agent_outputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = super()._research_method_metadata(
            method=method,
            scheduler_metadata=scheduler_metadata,
            case=case,
            result_agents=result_agents,
            agent_outputs=agent_outputs,
        )
        if method == M3_NO_STATE_METHOD:
            metadata.pop("goal_state_slots", None)
            metadata["structured_goal_state_used"] = False
            metadata["stateless_current_turn_slots"] = (
                dict(case.get("current_turn_slots") or {})
                if isinstance(case, dict) and isinstance(case.get("current_turn_slots"), Mapping)
                else {}
            )
        return metadata

    def _attach_scenario_result_metadata(
        self,
        result: dict[str, Any],
        *,
        scenario_id: str,
        turn_id: str,
        turn_index: int,
        turn_count: int,
        target_turn: bool,
        previous_state: dict[str, Any] | None,
        method: ExperimentMethod,
    ) -> None:
        super()._attach_scenario_result_metadata(
            result,
            scenario_id=scenario_id,
            turn_id=turn_id,
            turn_index=turn_index,
            turn_count=turn_count,
            target_turn=target_turn,
            previous_state=previous_state,
            method=method,
        )
        if method != M3_NO_STATE_METHOD:
            return
        prior_result_available = isinstance(previous_state, dict)
        history_is_method_local = (
            not prior_result_available
            or str(previous_state.get("method") or "") == M3_NO_STATE_METHOD
        )
        prior_turn_index = _optional_int(
            previous_state.get("turn_index") if prior_result_available else None
        )
        prior_result_is_prior_turn = (
            turn_index == 0 if not prior_result_available else prior_turn_index == turn_index - 1
        )
        audit = {
            "previous_state_provided": False,
            "structured_previous_state_visible": False,
            "orchestrator_prior_result_available_for_history": prior_result_available,
            "orchestrator_prior_result_is_prior_turn": prior_result_is_prior_turn,
            "dialogue_history_is_method_local": history_is_method_local,
            "dialogue_history_policy": "role_content_only",
            "has_evaluation": False,
            "has_metrics": False,
        }
        result["method_previous_state_policy"] = (
            "role_content_dialogue_history_only_no_structured_state"
        )
        result["method_previous_state_audit"] = audit
        result["previous_state_provided"] = False
        result["previous_state_schema_version"] = None
        result["previous_state_method"] = None
        result["previous_state_turn_id"] = None
        result["previous_state_turn_index"] = None
        result["previous_state_is_method_local"] = history_is_method_local
        result["previous_state_is_prior_turn"] = prior_result_is_prior_turn
        result["previous_state_has_evaluation"] = False
        result["previous_state_has_metrics"] = False


def _role_content_history(dialogue_history: Any) -> list[dict[str, str]]:
    sanitized: list[dict[str, str]] = []
    if not isinstance(dialogue_history, list):
        return sanitized
    for item in dialogue_history:
        if isinstance(item, Mapping):
            content = str(item.get("content") or item.get("text") or "").strip()
            role = str(item.get("role") or "user").strip().lower()
        else:
            content = str(item or "").strip()
            role = "user"
        if not content:
            continue
        if role not in {"user", "assistant", "system"}:
            role = "user"
        sanitized.append({"role": role, "content": content})
    return sanitized


def _stateless_current_request_plan(  # noqa: C901 - explicit frozen routing branches
    *,
    user_input: str,
    current_turn_slots: Mapping[str, Any],
    dialogue_history: list[dict[str, str]],
) -> dict[str, Any]:
    text = str(user_input or "").casefold()
    history_text = " ".join(item.get("content", "") for item in dialogue_history)
    history_slots = parse_visible_request_slots(history_text) if history_text else {}
    slots = dict(current_turn_slots)
    slot_keys = set(slots)
    has_history = bool(dialogue_history)
    weather_adjustment = _contains_any(text, _WEATHER_ADJUSTMENT_TERMS) and (
        _contains_any(text, _ITINERARY_ACTION_TERMS) or "weather_scenario" in slot_keys
    )
    full_trip_request = bool(slots.get("destination")) and (
        _contains_any(text, _TRIP_TERMS)
        or bool(slot_keys & {"duration_days", "people_count", "budget_amount"})
    )

    agents: list[str]
    task_type: str
    capability_signals: list[str] = []
    decision_reasons: list[str] = []
    requires_weather = False
    requires_itinerary_for_budget = False
    requires_attraction_for_budget = False

    if weather_adjustment:
        task_type = "weather_adjustment"
        agents = ["attraction", "weather", "itinerary", "budget"]
        capability_signals.extend(["weather_evidence", "itinerary_generation"])
        decision_reasons.append("stateless_weather_adjustment_full_dependency_chain")
        requires_weather = True
        requires_itinerary_for_budget = True
        requires_attraction_for_budget = True
    elif full_trip_request:
        task_type = "trip_planning"
        agents = ["attraction", "itinerary", "budget"]
        requires_weather = bool(slots.get("start_date") or slots.get("weather_scenario"))
        if requires_weather:
            agents.append("weather")
        capability_signals.extend(["poi_evidence", "itinerary_generation", "budget_estimation"])
        if requires_weather:
            capability_signals.append("weather_evidence")
        decision_reasons.append("stateless_full_trip_request")
        requires_itinerary_for_budget = True
        requires_attraction_for_budget = True
    elif has_history and (slot_keys or _contains_any(text, _ITINERARY_ACTION_TERMS)):
        task_type = "partial_replan"
        if slot_keys and slot_keys <= {"budget_amount", "budget_basis", "budget_level"}:
            agents = ["budget"]
            capability_signals.append("budget_estimation")
            decision_reasons.append("stateless_budget_change")
        elif (
            slot_keys
            and slot_keys <= {"origin"}
            and not _contains_any(
                text,
                ("重新安排", "重新规划", "重排", "replan"),
            )
        ):
            agents = ["budget"]
            capability_signals.append("budget_estimation")
            decision_reasons.append("stateless_origin_change")
        else:
            agents = ["attraction", "itinerary", "budget"]
            capability_signals.extend(["poi_evidence", "itinerary_generation", "budget_estimation"])
            decision_reasons.append("stateless_current_request_replan")
            requires_itinerary_for_budget = True
            requires_attraction_for_budget = True
            requires_weather = bool(
                slots.get("start_date")
                or slots.get("weather_scenario")
                or history_slots.get("start_date")
            )
            if requires_weather:
                agents.append("weather")
                capability_signals.append("weather_evidence")
    elif _contains_any(text, _WEATHER_QUERY_TERMS):
        task_type = "weather_query"
        agents = ["weather"]
        capability_signals.append("weather_evidence")
        decision_reasons.append("stateless_weather_query")
    elif _contains_any(text, _ATTRACTION_TERMS):
        task_type = "attraction_recommendation"
        agents = ["attraction"]
        capability_signals.append("poi_evidence")
        decision_reasons.append("stateless_attraction_query")
    else:
        task_type = "general_chat"
        agents = []
        decision_reasons.append("stateless_general_chat")

    planned_agents = _ordered_agents(agents)
    planned_tools = _tools_for_agents(planned_agents)
    return {
        "task_type": task_type,
        "planned_agents": planned_agents,
        "planned_tools": planned_tools,
        "capability_signals": list(dict.fromkeys(capability_signals)),
        "decision_reasons": decision_reasons,
        "requires_weather_for_itinerary": requires_weather,
        "requires_itinerary_for_budget": requires_itinerary_for_budget,
        "requires_attraction_for_budget": requires_attraction_for_budget,
    }


def _ordered_agents(agents: list[str]) -> list[str]:
    selected = set(agents)
    return [agent for agent in _AGENT_ORDER if agent in selected]


def _tools_for_agents(agents: list[str]) -> list[str]:
    tools: list[str] = []
    for agent in agents:
        for tool in _TOOLS_BY_AGENT.get(agent, ()):
            if tool not in tools:
                tools.append(tool)
    return tools


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term.casefold() in text for term in terms)


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
