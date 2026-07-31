"""Frozen method-level fairness contract for paper experiments.

This module is intentionally declarative.  It is the single code source for
the Day 6 method comparison contract; execution code and manifests can refer
to it without duplicating method definitions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from app.core.fixed_data import canonical_json_sha256
from app.core.goal_state_scheduler import (
    CANONICAL_AGENT_ORDER,
    CANONICAL_TOOL_ORDER,
    RESULT_DEPENDENCIES,
    TOOLS_BY_AGENT,
)
from app.schemas.experiment import EXPERIMENT_OUTPUT_SCHEMA_VERSION
from app.tools.research_tools import GENERATION_TOOL_NAMES, TOOL_CONTRACT_VERSION


METHOD_FAIRNESS_CONTRACT_SCHEMA_VERSION = "ctp-method-fairness-contract-v1"
METHOD_FAIRNESS_CONTRACT_ID = "day6_four_method_fairness_20260728"

EXPERIMENT_METHODS = (
    "llm_direct",
    "single_agent",
    "fixed_multi_agent",
    "adaptive_multi_agent",
)

COMMON_GENERATION_VISIBLE_FIELDS = (
    "case_id",
    "user_input",
    "dialogue_history",
    "method_input",
    "method_previous_state",
    "parsed_slots",
)

EVALUATOR_ONLY_FIELDS = (
    "task_type",
    "slots",
    "current_slots",
    "previous_slots",
    "changed_slots",
    "preserved_slots",
    "expected",
    "expected_goal",
    "standard_answer",
    "gold",
    "accepted_agent_sets",
    "required_tools",
    "forbidden_tools",
    "hard_constraints",
    "evaluation_rules",
)

PRIMARY_COMPARISON = {
    "baseline": "fixed_multi_agent",
    "proposed": "adaptive_multi_agent",
    "comparison_unit": "paired_case",
    "claim_boundary": (
        "M3 may claim efficiency gains over M2 only when task quality is not lower "
        "under the frozen evaluator."
    ),
}

RUNTIME_CONTROLS = {
    "model_config": "same model, temperature, max tokens, timeout, and retry policy",
    "offline_data": "same frozen local tourism data snapshot",
    "output_schema": EXPERIMENT_OUTPUT_SCHEMA_VERSION,
    "evaluator": "method-blind independent evaluator after generation",
    "method_order": "deterministic per-case seeded randomization",
    "formal_run_policy": "no mocks, no silent fallback, no rerun-to-success",
}

DEPENDENCY_POLICY = {
    "agent_order": list(CANONICAL_AGENT_ORDER),
    "tool_order": list(CANONICAL_TOOL_ORDER),
    "agent_tool_map": {
        agent: list(TOOLS_BY_AGENT.get(agent, ())) for agent in CANONICAL_AGENT_ORDER
    },
    "result_dependencies": {
        agent: list(dependencies) for agent, dependencies in RESULT_DEPENDENCIES.items()
    },
    "budget_agent_dependencies": [
        "attraction_result_for_existing_plan_or_ticket_budget",
        "duration_days",
        "people_count",
        "budget_level",
    ],
    "budget_query_scope_policy": {
        "rough_budget_without_history_or_ticket_terms": ["budget"],
        "existing_plan_budget_query": ["reused_attraction", "budget"],
        "ticket_or_admission_budget_without_reusable_attractions": [
            "attraction",
            "budget",
        ],
    },
    "slot_change_invalidation": {
        "destination": list(CANONICAL_AGENT_ORDER),
        "duration_days": ["weather", "itinerary", "budget"],
        "start_date": ["weather", "itinerary"],
        "people_count": ["budget"],
        "traveler_group": ["attraction", "itinerary", "budget"],
        "preferences": ["attraction", "itinerary", "budget"],
        "budget_amount": ["attraction", "itinerary", "budget"],
        "budget_level": ["attraction", "itinerary", "budget"],
        "weather_scenario": ["weather", "itinerary"],
    },
    "multi_turn_counting": {
        "state_scope": "per method, per case, per repeat",
        "previous_state_source": "only the same method's own previous turn output",
        "scenario_unit": "one multi-turn scenario is one paired statistical unit",
        "warm_start": "no oracle or handcrafted previous_state in formal test runs",
        "initial_turn_failure": "the scenario remains failed; do not repair with gold state",
    },
}

M2_M3_FAIRNESS = {
    "must_match": [
        "business_agents",
        "available_generation_tools",
        "tool_contract_version",
        "output_schema_version",
        "model_config_policy",
        "offline_data_policy",
        "evaluator_policy",
    ],
    "only_allowed_differences": [
        "scheduler_policy",
        "state_reuse_policy",
        "planned_agent_subset",
        "planned_tool_subset",
    ],
}


@dataclass(frozen=True)
class MethodContract:
    """Static contract for one benchmark method."""

    method: str
    paper_label: str
    experimental_role: str
    agent_topology: str
    business_agents: tuple[str, ...]
    available_generation_tools: tuple[str, ...]
    scheduler_policy: str
    state_reuse_policy: str
    can_call_generation_tools: bool
    can_reuse_previous_results: bool
    output_schema_version: str = EXPERIMENT_OUTPUT_SCHEMA_VERSION
    tool_contract_version: str = TOOL_CONTRACT_VERSION
    model_config_policy: str = "shared_frozen_model_config"
    offline_data_policy: str = "shared_fixed_offline_data"
    evaluator_policy: str = "method_blind_independent_evaluator"


METHOD_CONTRACTS: dict[str, MethodContract] = {
    "llm_direct": MethodContract(
        method="llm_direct",
        paper_label="M0 Direct LLM",
        experimental_role="no-agent/no-tool lower bound",
        agent_topology="none",
        business_agents=(),
        available_generation_tools=(),
        scheduler_policy="no scheduler",
        state_reuse_policy="no structured result reuse",
        can_call_generation_tools=False,
        can_reuse_previous_results=False,
    ),
    "single_agent": MethodContract(
        method="single_agent",
        paper_label="M1 Single Agent",
        experimental_role="single general agent baseline",
        agent_topology="one general tourism agent",
        business_agents=("single_agent",),
        available_generation_tools=tuple(GENERATION_TOOL_NAMES),
        scheduler_policy="single agent decides tool use internally",
        state_reuse_policy="no structured result reuse",
        can_call_generation_tools=True,
        can_reuse_previous_results=False,
    ),
    "fixed_multi_agent": MethodContract(
        method="fixed_multi_agent",
        paper_label="M2 Fixed Multi-Agent",
        experimental_role="fixed multi-agent baseline",
        agent_topology="four shared business agents",
        business_agents=tuple(CANONICAL_AGENT_ORDER),
        available_generation_tools=tuple(GENERATION_TOOL_NAMES),
        scheduler_policy="full business chain for every executable tourism task",
        state_reuse_policy="no local result reuse; rerun the fixed chain",
        can_call_generation_tools=True,
        can_reuse_previous_results=False,
    ),
    "adaptive_multi_agent": MethodContract(
        method="adaptive_multi_agent",
        paper_label="M3 Proposed Method",
        experimental_role="goal-state adaptive scheduling method",
        agent_topology="four shared business agents",
        business_agents=tuple(CANONICAL_AGENT_ORDER),
        available_generation_tools=tuple(GENERATION_TOOL_NAMES),
        scheduler_policy="goal-state scheduler selects the minimal valid subset",
        state_reuse_policy="reuse only same-method valid previous artifacts",
        can_call_generation_tools=True,
        can_reuse_previous_results=True,
    ),
}


def build_method_fairness_contract(
    active_methods: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return the machine-readable Day 6 fairness contract."""
    normalized_methods = _normalize_active_methods(active_methods)
    return {
        "schema_version": METHOD_FAIRNESS_CONTRACT_SCHEMA_VERSION,
        "contract_id": METHOD_FAIRNESS_CONTRACT_ID,
        "active_methods": list(normalized_methods),
        "primary_comparison": dict(PRIMARY_COMPARISON),
        "generation_visibility": {
            "generation_visible_fields": list(COMMON_GENERATION_VISIBLE_FIELDS),
            "evaluator_only_fields": list(EVALUATOR_ONLY_FIELDS),
            "gold_visible_to_generation": False,
            "policy": (
                "Generation methods may only use the visible request/history/state fields; "
                "gold labels and accepted sets are reserved for the evaluator."
            ),
        },
        "runtime_controls": dict(RUNTIME_CONTROLS),
        "dependency_policy": _jsonable(DEPENDENCY_POLICY),
        "m2_m3_fairness": _jsonable(M2_M3_FAIRNESS),
        "methods": {
            method: _jsonable(asdict(METHOD_CONTRACTS[method]))
            for method in EXPERIMENT_METHODS
        },
        "source_documents": [
            "Phase0_实验协议.md",
            "docs/Day4_goal_state_scheduler_rules.md",
            "docs/Day5_evaluation_rule_catalog.md",
            "docs/Day6_four_method_fairness.md",
        ],
    }


def method_fairness_contract_hash(
    active_methods: Iterable[str] | None = None,
) -> str:
    """Hash the contract using the repository's canonical JSON strategy."""
    return canonical_json_sha256(build_method_fairness_contract(active_methods))


def validate_method_fairness_contract(
    active_methods: Iterable[str] | None = None,
) -> None:
    """Raise ValueError if the frozen method contract drifts from Day 6 rules."""
    normalized_methods = _normalize_active_methods(active_methods)
    if any(method not in METHOD_CONTRACTS for method in normalized_methods):
        raise ValueError("active_methods contains an unknown experiment method")

    m0 = METHOD_CONTRACTS["llm_direct"]
    if m0.business_agents or m0.available_generation_tools or m0.can_call_generation_tools:
        raise ValueError("M0 must remain no-agent and no-tool")

    m1 = METHOD_CONTRACTS["single_agent"]
    if m1.business_agents != ("single_agent",):
        raise ValueError("M1 must remain a single general agent baseline")
    if tuple(m1.available_generation_tools) != tuple(GENERATION_TOOL_NAMES):
        raise ValueError("M1 must use the shared generation tool catalog")
    if m1.can_reuse_previous_results:
        raise ValueError("M1 must not declare structured result reuse")

    m2 = METHOD_CONTRACTS["fixed_multi_agent"]
    m3 = METHOD_CONTRACTS["adaptive_multi_agent"]
    for field_name in M2_M3_FAIRNESS["must_match"]:
        if getattr(m2, field_name) != getattr(m3, field_name):
            raise ValueError(f"M2 and M3 must match on {field_name}")
    if m2.can_reuse_previous_results:
        raise ValueError("M2 must not declare local result reuse")
    if not m3.can_reuse_previous_results:
        raise ValueError("M3 must declare state-aware result reuse")

    if set(COMMON_GENERATION_VISIBLE_FIELDS) & set(EVALUATOR_ONLY_FIELDS):
        raise ValueError("generation-visible and evaluator-only fields must be disjoint")

    contract_agent_tools = DEPENDENCY_POLICY["agent_tool_map"]
    for agent in CANONICAL_AGENT_ORDER:
        if tuple(contract_agent_tools[agent]) != tuple(TOOLS_BY_AGENT.get(agent, ())):
            raise ValueError(f"agent tool dependency mismatch for {agent}")
    if tuple(DEPENDENCY_POLICY["tool_order"]) != tuple(GENERATION_TOOL_NAMES):
        raise ValueError("generation tool order must match the shared tool catalog")


def _normalize_active_methods(active_methods: Iterable[str] | None) -> tuple[str, ...]:
    if active_methods is None:
        return EXPERIMENT_METHODS
    normalized = tuple(str(method).strip().lower() for method in active_methods)
    if not normalized:
        raise ValueError("active_methods must not be empty")
    unknown = sorted(set(normalized) - set(EXPERIMENT_METHODS))
    if unknown:
        raise ValueError(f"unknown experiment methods: {', '.join(unknown)}")
    return normalized


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value
