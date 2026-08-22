import asyncio
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.tools.poi_search as poi_search_module
import app.tools.route_plan as route_plan_module
import app.tools.weather as weather_module
from app.agents.base import AgentStatus
from app.agents.budget import BudgetAgent
from app.core.context import ExecutionContext, SessionContext
from app.core.experiment_runner import ExperimentRunner
from app.core.fixed_data import (
    CANONICAL_JSON_SHA256_STRATEGY,
    DATA_ROOT,
    FIXED_CITY_IDS,
    FIXED_DATA_EXPECTED_COMBINED_SHA256,
    FIXED_DATA_EXPECTED_FILE_COUNT,
    FIXED_DATA_EXPECTED_FILE_HASHES,
    FIXED_DATA_SNAPSHOT_DIRS,
    FixedDataError,
    FixedTourismData,
    get_fixed_tourism_data,
    validate_fixed_data_snapshot,
)
from app.tools.budget_calc import BudgetCalculatorTool
from app.tools.poi_search import POIDetailTool, POISearchTool
from app.tools.route_plan import RoutePlanningTool
from app.tools.weather import WeatherTool


class _BudgetLLM:
    async def chat(self, messages, tools=None, **kwargs):
        from app.core.llm.client import LLMResponse

        return LLMResponse(
            content="budget analysis completed",
            model="fake-budget-llm",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            finish_reason="stop",
        )


REQUIRED_METADATA_FIELDS = {
    "file_id",
    "schema_version",
    "dataset_version",
    "city_id",
    "city_name",
    "created_at",
    "updated_at",
    "snapshot_date",
    "data_mode",
}


def test_fixed_data_snapshot_matches_locked_hashes() -> None:
    manifest = validate_fixed_data_snapshot()

    assert manifest["file_count"] == FIXED_DATA_EXPECTED_FILE_COUNT == 25
    assert manifest["hash_strategy"] == CANONICAL_JSON_SHA256_STRATEGY
    assert manifest["combined_sha256"] == FIXED_DATA_EXPECTED_COMBINED_SHA256
    assert manifest["missing_files"] == []
    assert {item["path"]: item["sha256"] for item in manifest["files"]} == FIXED_DATA_EXPECTED_FILE_HASHES
    assert {item["path"]: item["hash_strategy"] for item in manifest["files"]} == {
        path: CANONICAL_JSON_SHA256_STRATEGY
        for path in FIXED_DATA_EXPECTED_FILE_HASHES
    }


def test_fixed_data_snapshot_validation_ignores_json_formatting(tmp_path: Path) -> None:
    data_root = _copy_fixed_snapshot(tmp_path)
    target = data_root / "pois" / "beijing.json"
    original_raw_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    payload = json.loads(target.read_text(encoding="utf-8-sig"))
    reformatted = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=4)
    target.write_bytes(reformatted.replace("\n", "\r\n").encode("utf-8"))

    assert hashlib.sha256(target.read_bytes()).hexdigest() != original_raw_sha

    manifest = validate_fixed_data_snapshot(data_root)

    assert manifest["combined_sha256"] == FIXED_DATA_EXPECTED_COMBINED_SHA256
    assert {item["path"]: item["sha256"] for item in manifest["files"]} == FIXED_DATA_EXPECTED_FILE_HASHES


def test_fixed_data_snapshot_validation_fails_when_file_missing(tmp_path: Path) -> None:
    data_root = _copy_fixed_snapshot(tmp_path)
    (data_root / "pois" / "beijing.json").unlink()

    with pytest.raises(FixedDataError, match="missing fixed data files"):
        validate_fixed_data_snapshot(data_root)


def test_fixed_data_snapshot_validation_fails_when_file_modified(tmp_path: Path) -> None:
    data_root = _copy_fixed_snapshot(tmp_path)
    target = data_root / "weather" / "hangzhou.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["metadata"]["snapshot_test_mutation"] = True
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with pytest.raises(FixedDataError, match="modified fixed data files"):
        validate_fixed_data_snapshot(data_root)


def _copy_fixed_snapshot(tmp_path: Path) -> Path:
    data_root = tmp_path / "data"
    for directory in FIXED_DATA_SNAPSHOT_DIRS:
        for city_id in FIXED_CITY_IDS:
            source = DATA_ROOT / directory / f"{city_id}.json"
            target = data_root / directory / f"{city_id}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return data_root


def test_fixed_five_city_data_and_transport_matrix_are_complete() -> None:
    dataset = FixedTourismData()

    for city_id in FIXED_CITY_IDS:
        bundle = dataset.city_bundle(city_id)
        for key in ("pois", "restaurants", "accommodation", "weather", "transport"):
            metadata = bundle[key]["metadata"]
            assert REQUIRED_METADATA_FIELDS <= set(metadata)
            assert metadata["city_id"] == city_id
            assert metadata["data_mode"] == "frozen_offline"

        transport = bundle["transport"]
        area_ids = {item["area_id"] for item in transport["area_nodes"]}
        assert len(area_ids) == 6
        assert transport["metadata"]["allowed_modes"] == ["walking", "public_transit", "taxi"]
        expected_pair_count = len(area_ids) * (len(area_ids) + 1) // 2
        assert len(transport["links"]) == expected_pair_count
        assert transport["metadata"]["record_count"] == expected_pair_count

        pairs = {
            frozenset((link["origin_area_id"], link["destination_area_id"]))
            for link in transport["links"]
        }
        assert len(pairs) == expected_pair_count
        for link in transport["links"]:
            assert link["origin_area_id"] in area_ids
            assert link["destination_area_id"] in area_ids
            assert set(link["duration_minutes"]) == {"walking", "public_transit", "taxi"}
            assert set(link["cost_cny"]) == {"walking", "public_transit", "taxi"}

        poi_nodes = [
            item["transport"]["matrix_node_id"]
            for item in bundle["pois"]["pois"]
        ]
        dining_nodes = [
            item["transport"]["matrix_node_id"]
            for item in bundle["restaurants"]["dining_areas"]
        ]
        accommodation_nodes = [
            item["transport"]["matrix_node_id"]
            for item in bundle["accommodation"]["accommodation_areas"]
        ]
        for node_id in [*poi_nodes, *dining_nodes, *accommodation_nodes]:
            assert dataset.resolve_area_id(city_id, node_id) in area_ids


def test_legacy_shanghai_restaurant_file_is_not_part_of_fixed_experiment() -> None:
    assert Path("data/restaurants/shanghai.json").exists()
    assert "shanghai" not in FIXED_CITY_IDS
    assert get_fixed_tourism_data().resolve_city_id("shanghai") is None


def test_formal_offline_tools_use_fixed_data(monkeypatch) -> None:
    monkeypatch.setenv("TOURISM_FORMAL_EXPERIMENT_OFFLINE", "true")

    search_result = asyncio.run(POISearchTool().execute("poi", "hangzhou", limit=3))
    assert search_result.success is True
    assert search_result.metadata["offline"] is True
    assert search_result.api_calls == []
    assert len(search_result.data) == 3
    assert search_result.data[0]["offline"] is True

    poi_id = search_result.data[0]["id"]
    detail_result = asyncio.run(POIDetailTool().execute(poi_id))
    assert detail_result.success is True
    assert detail_result.data["id"] == poi_id
    assert detail_result.metadata["offline"] is True

    weather_result = asyncio.run(
        WeatherTool().execute("beijing", scenario_type="rain", days=3)
    )
    assert weather_result.success is True
    assert weather_result.data["provider"] == "qweather_snapshot"
    assert weather_result.data["coverage_status"] == "full"
    assert [day["day_index"] for day in weather_result.data["daily_forecasts"]] == [1, 2, 3]
    assert weather_result.metadata["data_source"] == "qweather_frozen_snapshot"
    assert weather_result.api_calls == []

    route_result = asyncio.run(
        RoutePlanningTool().execute(
            origin=poi_id,
            destination="hz_da001",
            city="hangzhou",
            mode="public_transit",
        )
    )
    assert route_result.success is True
    assert route_result.data["offline"] is True
    assert route_result.data["mode"] == "public_transit"
    assert route_result.data["duration_minutes"] > 0
    assert route_result.api_calls == []

    budget_result = asyncio.run(
        BudgetCalculatorTool().execute(
            destination="beijing",
            duration=3,
            num_travelers=2,
            budget_level="medium",
        )
    )
    assert budget_result.success is True
    assert budget_result.data["calculation_source"] == "fixed_reference_cost_model"
    assert budget_result.data["budget_policy_version"] == "budget_policy_v2_0"
    assert budget_result.data["breakdown"]["food"]["calculation_rule"] == (
        "meal_count_equivalent = 2 * day_count + 0.5 * night_count; total_cost = reference_price_cny * meal_count_equivalent * diner_count"
    )
    assert "reference_price_cny" in budget_result.data["breakdown"]["accommodation"]["calculation_rule"]
    assert budget_result.api_calls == []


def test_experiment_runner_enables_formal_offline_mode_for_methods(tmp_path) -> None:
    async def handler(case):
        assert os.getenv("TOURISM_FORMAL_EXPERIMENT_OFFLINE") == "true"
        return {"case_id": case["case_id"], "offline": True}

    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        method_handlers={method: handler for method in ExperimentRunner.METHODS},
    )
    result = runner.run(
        {"case_id": "offline-env", "user_input": "beijing three day trip"},
        method="full_system",
    )

    assert result["method"] == "adaptive_multi_agent"
    assert result["raw_output"] == {"case_id": "offline-env", "offline": True}
    assert result["output"]["schema_version"] == "ctp-experiment-output-v1"
    assert result["output"]["raw_output"] == {"case_id": "offline-env", "offline": True}


def test_weather_tool_scenario_no_longer_drives_snapshot_selection(monkeypatch) -> None:
    monkeypatch.setenv("TOURISM_FORMAL_EXPERIMENT_OFFLINE", "true")

    default_result = asyncio.run(WeatherTool().execute("beijing", scenario_type="", days=1))
    assert default_result.success is True
    assert default_result.data["provider"] == "qweather_snapshot"

    invalid_result = asyncio.run(
        WeatherTool().execute("beijing", scenario_type="not_a_valid_scenario", days=1)
    )
    assert invalid_result.success is True
    assert invalid_result.metadata["offline"] is True
    assert invalid_result.data["provider"] == "qweather_snapshot"
    assert invalid_result.data["daily_forecasts"] == default_result.data["daily_forecasts"]


def test_concrete_missing_poi_search_returns_empty(monkeypatch) -> None:
    monkeypatch.setenv("TOURISM_FORMAL_EXPERIMENT_OFFLINE", "true")

    result = asyncio.run(
        POISearchTool().execute("missing concrete POI XYZ", "beijing", limit=3)
    )

    assert result.success is True
    assert result.data == []
    assert result.metadata["count"] == 0
    assert result.api_calls == []


def test_guilin_public_transit_does_not_output_subway(monkeypatch) -> None:
    monkeypatch.setenv("TOURISM_FORMAL_EXPERIMENT_OFFLINE", "true")

    result = asyncio.run(
        RoutePlanningTool().execute(
            origin="gl001",
            destination="gl_da001",
            city="guilin",
            mode="public_transit",
        )
    )

    assert result.success is True
    assert result.data["mode"] == "public_transit"
    assert result.data["mode"] != "subway"
    assert result.data["duration_minutes"] > 0


def test_invalid_transport_mode_fails_without_default_fallback(monkeypatch) -> None:
    monkeypatch.setenv("TOURISM_FORMAL_EXPERIMENT_OFFLINE", "true")

    result = asyncio.run(
        RoutePlanningTool().execute(
            origin="gl001",
            destination="gl_da001",
            city="guilin",
            mode="flying_car",
        )
    )

    assert result.success is False
    assert result.metadata["offline"] is True
    assert "unsupported fixed transport mode" in result.error


def test_formal_offline_budget_agent_fails_when_fixed_budget_missing(monkeypatch) -> None:
    monkeypatch.setenv("TOURISM_FORMAL_EXPERIMENT_OFFLINE", "true")

    session = SessionContext(session_id="fixed-budget-missing-session")
    context = ExecutionContext(
        request_id="fixed-budget-missing-request",
        session_id=session.session_id,
        extracted_info={
            "destination": "shanghai",
            "duration": 3,
            "num_travelers": 2,
            "budget_level": "medium",
        },
    )

    response = asyncio.run(BudgetAgent(llm=None).execute(session, context))

    assert response.status == AgentStatus.FAILED
    assert response.success is False
    assert response.metadata["offline"] is True
    assert response.metadata["legacy_estimator_used"] is False
    assert response.data["calculation_source"] == "fixed_reference_cost_model"
    assert "unsupported fixed experiment city" in response.error


def test_formal_offline_tourism_tools_do_not_use_network(monkeypatch) -> None:
    monkeypatch.setenv("TOURISM_FORMAL_EXPERIMENT_OFFLINE", "true")

    async def forbidden_poi_client():
        raise AssertionError("network access is forbidden in formal offline mode")

    class ForbiddenAsyncClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("network access is forbidden in formal offline mode")

    monkeypatch.setattr(poi_search_module, "_get_poi_http_client", forbidden_poi_client)
    monkeypatch.setattr(route_plan_module.httpx, "AsyncClient", ForbiddenAsyncClient)

    search_result = asyncio.run(POISearchTool().execute("poi", "beijing", limit=1))
    weather_result = asyncio.run(WeatherTool().execute("beijing", scenario_type="sunny", days=1))
    route_result = asyncio.run(
        RoutePlanningTool().execute(
            origin="bj001",
            destination="bj_da001",
            city="beijing",
            mode="public_transit",
        )
    )
    budget_result = asyncio.run(
        BudgetCalculatorTool().execute(
            destination="beijing",
            duration=2,
            num_travelers=1,
            budget_level="medium",
        )
    )

    assert search_result.success is True
    assert weather_result.success is True
    assert route_result.success is True
    assert budget_result.success is True
    assert search_result.api_calls == []
    assert weather_result.api_calls == []
    assert route_result.api_calls == []
    assert budget_result.api_calls == []


def test_fixed_budget_one_day_trip_has_zero_accommodation_nights() -> None:
    result = get_fixed_tourism_data().calculate_budget(
        destination="guilin",
        duration=1,
        num_travelers=2,
        budget_level="medium",
    )

    accommodation = result["breakdown"]["accommodation"]
    assert accommodation["night_count"] == 0
    assert accommodation["recommended"] == 0


def test_fixed_budget_multi_day_trip_uses_duration_minus_one_nights() -> None:
    result = get_fixed_tourism_data().calculate_budget(
        destination="guilin",
        duration=3,
        num_travelers=2,
        budget_level="medium",
    )

    accommodation = result["breakdown"]["accommodation"]
    assert accommodation["night_count"] == 2
    assert accommodation["recommended"] > 0


def test_budget_policy_v2_three_people_use_two_rooms_and_fractional_breakfast() -> None:
    result = get_fixed_tourism_data().calculate_budget(
        destination="guilin",
        duration=3,
        num_travelers=3,
        budget_level="medium",
    )

    accommodation = result["breakdown"]["accommodation"]
    food = result["breakdown"]["food"]
    assert result["budget_policy_version"] == "budget_policy_v2_0"
    assert accommodation["room_count"] == 2
    assert accommodation["night_count"] == 2
    assert food["meal_count_equivalent"] == 7.0
    assert result["breakdown"]["other"]["recommended"] == 0.0


def test_budget_policy_v2_budget_limit_never_changes_hotel_or_food_tier() -> None:
    low = get_fixed_tourism_data().calculate_budget(
        origin="guangzhou",
        destination="guilin",
        duration=3,
        num_travelers=2,
        budget_level="medium",
        budget_limit=3000,
    )
    high = get_fixed_tourism_data().calculate_budget(
        origin="guangzhou",
        destination="guilin",
        duration=3,
        num_travelers=2,
        budget_level="medium",
        budget_limit=10000,
    )

    assert low["economic_baseline_total"] == high["economic_baseline_total"]
    assert low["final_recommended_total"] == high["final_recommended_total"]
    assert low["budget_policy"]["upgrade_applied"] == []
    assert high["budget_policy"]["upgrade_applied"] == []
    assert high["budget_policy"]["hotel_tier"] == "economy"
    assert high["budget_policy"]["food_tier"] == "economy"
    assert high["budget_policy"]["auto_upgrade_enabled"] is False


def test_budget_policy_v2_no_origin_blocks_auto_upgrade_and_disclaims_intercity() -> None:
    result = get_fixed_tourism_data().calculate_budget(
        destination="guilin",
        duration=3,
        num_travelers=2,
        budget_limit=10000,
    )

    assert result["budget_scope"] == "destination_local_only"
    assert result["requested_budget_scope"] == "local_plus_round_trip_intercity"
    assert result["computed_budget_scope"] == "destination_local_only"
    assert result["scope_complete"] is False
    assert result["sufficiency_status"] == "indeterminate"
    assert result["remaining_budget"] is None
    assert result["covered_scope_remaining_budget"] is not None
    assert result["mandatory_budget_disclaimer"] is True
    assert result["budget_policy"]["upgrade_applied"] == []
    assert result["budget_policy"]["hotel_tier"] == "economy"
    assert result["budget_policy"]["food_tier"] == "economy"
    assert "auto_upgrade_disabled_by_budget_policy_v2_0" in result["budget_policy"]["automatic_upgrade_blocked_reasons"]


def test_budget_policy_v2_explicit_local_only_scope_can_judge_without_origin() -> None:
    result = get_fixed_tourism_data().calculate_budget(
        destination="guilin",
        duration=3,
        num_travelers=2,
        budget_limit=3000,
        requested_budget_scope="destination_local_only",
    )

    assert result["requested_budget_scope"] == "destination_local_only"
    assert result["computed_budget_scope"] == "destination_local_only"
    assert result["scope_complete"] is True
    assert result["sufficiency_status"] == "sufficient"
    assert result["can_judge_budget_sufficiency"] is True
    assert result["mandatory_budget_disclaimer"] is True
    assert "未提供出发地" in result["budget_disclaimer"]
    assert result["remaining_budget"] == result["covered_scope_remaining_budget"]


def test_budget_policy_v2_explicit_food_preference_uses_comfort_food_when_affordable() -> None:
    result = get_fixed_tourism_data().calculate_budget(
        origin="guangzhou",
        destination="guilin",
        duration=3,
        num_travelers=2,
        budget_limit=5000,
        food_level="comfort food with local specialties",
    )

    assert result["budget_policy"]["upgrade_decision"] == "explicit_preference_applied"
    assert result["breakdown"]["food"]["tier"] == "comfort"
    assert result["budget_policy"]["upgrade_applied"] == ["food"]


def test_budget_agent_cli_path_uses_fixed_intercity_transport_when_origin_supported() -> None:
    session = SessionContext(session_id="cli-budget-intercity")
    context = ExecutionContext(
        request_id="cli-budget-intercity",
        session_id=session.session_id,
        extracted_info={
            "origin": "guangzhou",
            "destination": "guilin",
            "duration": 3,
            "num_travelers": 2,
            "budget_level": "medium",
        },
    )

    response = asyncio.run(BudgetAgent(llm=_BudgetLLM()).execute(session, context))

    assert response.status == AgentStatus.COMPLETED
    assert response.success is True
    assert response.data["estimated_by"] == "fixed_reference_cost_model"
    assert response.data["budget_policy_version"] == "budget_policy_v2_0"
    assert response.data["intercity_transport_cost"] == 800.0
    assert response.data["intercity_transport_included"] is True
    assert response.data["real_time_api_allowed"] is False
    assert response.data["runtime_online_refresh_allowed"] is False
    assert response.data["real_time_price_claim_allowed"] is False
    assert response.data["intercity_transport"]["runtime_online_refresh_allowed"] is False
    assert response.data["budget_scope"] == "local_plus_round_trip_intercity"


def test_budget_agent_cli_path_disclaims_intercity_transport_when_origin_missing() -> None:
    session = SessionContext(session_id="cli-budget-missing-origin")
    context = ExecutionContext(
        request_id="cli-budget-missing-origin",
        session_id=session.session_id,
        extracted_info={
            "destination": "guilin",
            "duration": 3,
            "num_travelers": 2,
            "budget_level": "medium",
        },
    )

    response = asyncio.run(BudgetAgent(llm=_BudgetLLM()).execute(session, context))

    assert response.status == AgentStatus.COMPLETED
    assert response.success is True
    assert response.data["estimated_by"] == "fixed_reference_cost_model"
    assert response.data["budget_policy_version"] == "budget_policy_v2_0"
    assert response.data["intercity_transport_cost"] == 0.0
    assert response.data["intercity_transport_included"] is False
    assert response.data["runtime_online_refresh_allowed"] is False
    assert response.data["real_time_price_claim_allowed"] is False
    assert response.data["intercity_transport"]["runtime_online_refresh_allowed"] is False
    assert response.data["mandatory_budget_disclaimer"] is True
    assert response.data["budget_scope"] == "destination_local_only"
