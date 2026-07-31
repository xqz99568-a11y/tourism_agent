import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.experiment_method_contract import (
    EXPERIMENT_METHODS,
    METHOD_FAIRNESS_CONTRACT_ID,
    METHOD_FAIRNESS_CONTRACT_SCHEMA_VERSION,
    build_method_fairness_contract,
    method_fairness_contract_hash,
    validate_method_fairness_contract,
)
from app.core.experiment_runner import ExperimentRunner
from app.core.goal_state_scheduler import CANONICAL_AGENT_ORDER
from app.schemas.experiment import EXPERIMENT_OUTPUT_SCHEMA_VERSION
from app.tools.research_tools import GENERATION_TOOL_NAMES, TOOL_CONTRACT_VERSION


def test_day6_contract_freezes_four_method_permissions() -> None:
    validate_method_fairness_contract()

    contract = build_method_fairness_contract()
    methods = contract["methods"]

    assert contract["schema_version"] == METHOD_FAIRNESS_CONTRACT_SCHEMA_VERSION
    assert contract["contract_id"] == METHOD_FAIRNESS_CONTRACT_ID
    assert contract["active_methods"] == list(EXPERIMENT_METHODS)
    assert ExperimentRunner.METHODS == EXPERIMENT_METHODS
    assert list(methods) == list(EXPERIMENT_METHODS)

    m0 = methods["llm_direct"]
    assert m0["business_agents"] == []
    assert m0["available_generation_tools"] == []
    assert m0["can_call_generation_tools"] is False
    assert m0["can_reuse_previous_results"] is False

    m1 = methods["single_agent"]
    assert m1["business_agents"] == ["single_agent"]
    assert m1["available_generation_tools"] == list(GENERATION_TOOL_NAMES)
    assert m1["can_call_generation_tools"] is True
    assert m1["can_reuse_previous_results"] is False


def test_day6_contract_keeps_m2_m3_different_only_by_scheduler_and_reuse() -> None:
    contract = build_method_fairness_contract()
    methods = contract["methods"]
    m2 = methods["fixed_multi_agent"]
    m3 = methods["adaptive_multi_agent"]

    assert m2["business_agents"] == list(CANONICAL_AGENT_ORDER)
    assert m3["business_agents"] == list(CANONICAL_AGENT_ORDER)
    assert m2["available_generation_tools"] == list(GENERATION_TOOL_NAMES)
    assert m3["available_generation_tools"] == list(GENERATION_TOOL_NAMES)
    assert m2["tool_contract_version"] == m3["tool_contract_version"] == TOOL_CONTRACT_VERSION
    assert (
        m2["output_schema_version"]
        == m3["output_schema_version"]
        == EXPERIMENT_OUTPUT_SCHEMA_VERSION
    )

    for field_name in contract["m2_m3_fairness"]["must_match"]:
        assert m2[field_name] == m3[field_name]

    assert m2["can_reuse_previous_results"] is False
    assert m3["can_reuse_previous_results"] is True
    assert contract["m2_m3_fairness"]["only_allowed_differences"] == [
        "scheduler_policy",
        "state_reuse_policy",
        "planned_agent_subset",
        "planned_tool_subset",
    ]


def test_day6_contract_freezes_visibility_and_dependency_policies() -> None:
    contract = build_method_fairness_contract()
    visibility = contract["generation_visibility"]
    dependencies = contract["dependency_policy"]

    assert visibility["gold_visible_to_generation"] is False
    assert not set(visibility["generation_visible_fields"]) & set(
        visibility["evaluator_only_fields"]
    )
    assert {"slots", "expected", "gold", "accepted_agent_sets"} <= set(
        visibility["evaluator_only_fields"]
    )

    assert dependencies["agent_order"] == list(CANONICAL_AGENT_ORDER)
    assert dependencies["tool_order"] == list(GENERATION_TOOL_NAMES)
    assert dependencies["agent_tool_map"]["attraction"] == ["poi_search"]
    assert dependencies["agent_tool_map"]["weather"] == ["weather_query"]
    assert dependencies["agent_tool_map"]["itinerary"] == []
    assert dependencies["agent_tool_map"]["budget"] == ["budget_calculator"]
    assert dependencies["slot_change_invalidation"]["people_count"] == ["budget"]
    assert dependencies["slot_change_invalidation"]["budget_level"] == [
        "attraction",
        "itinerary",
        "budget",
    ]
    assert (
        dependencies["multi_turn_counting"]["previous_state_source"]
        == "only the same method's own previous turn output"
    )


def test_day6_contract_rejects_unknown_active_methods() -> None:
    with pytest.raises(ValueError, match="unknown experiment methods"):
        build_method_fairness_contract(["adaptive_multi_agent", "unknown_method"])


def test_experiment_manifest_records_day6_method_contract(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "dataset_id": "day6_contract_smoke",
                "dataset_version": "v1",
                "cases": [{"case_id": "case001", "user_input": "帮我规划杭州3天旅游"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    runner = ExperimentRunner(trace_dir=tmp_path / "traces", output_dir=tmp_path / "results")
    manifest = runner.write_experiment_manifest(
        benchmark_path=benchmark_path,
        output_path=tmp_path / "manifest.json",
    )
    contract = manifest["method_fairness_contract"]

    assert manifest["methods"] == list(EXPERIMENT_METHODS)
    assert contract["schema_version"] == METHOD_FAIRNESS_CONTRACT_SCHEMA_VERSION
    assert contract["contract_id"] == METHOD_FAIRNESS_CONTRACT_ID
    assert contract["contract_sha256"] == method_fairness_contract_hash(EXPERIMENT_METHODS)
    assert contract["primary_comparison"]["baseline"] == "fixed_multi_agent"
    assert contract["primary_comparison"]["proposed"] == "adaptive_multi_agent"
    assert contract["methods"]["adaptive_multi_agent"]["business_agents"] == list(
        CANONICAL_AGENT_ORDER
    )
