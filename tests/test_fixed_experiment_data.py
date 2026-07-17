import asyncio
import os
import sys
from pathlib import Path

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
from app.core.fixed_data import FIXED_CITY_IDS, FixedTourismData, get_fixed_tourism_data
from app.tools.budget_calc import BudgetCalculatorTool
from app.tools.poi_search import POIDetailTool, POISearchTool
from app.tools.route_plan import RoutePlanningTool
from app.tools.weather import WeatherTool


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
    assert get_fixed_tourism_data().resolve_city_id("上海") is None


def test_formal_offline_tools_use_fixed_data(monkeypatch) -> None:
    monkeypatch.setenv("TOURISM_FORMAL_EXPERIMENT_OFFLINE", "true")

    search_result = asyncio.run(POISearchTool().execute("景点", "杭州", limit=3))
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
        WeatherTool().execute("北京", scenario_type="rain", days=3)
    )
    assert weather_result.success is True
    assert weather_result.data["provider"] == "fixed_weather_dataset"
    assert weather_result.data["scenario_type"] == "rain"
    assert [day["day_index"] for day in weather_result.data["daily_forecasts"]] == [1, 2, 3]
    assert weather_result.api_calls == []

    route_result = asyncio.run(
        RoutePlanningTool().execute(
            origin=poi_id,
            destination="hz_da001",
            city="杭州",
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
            destination="北京",
            duration=3,
            num_travelers=2,
            budget_level="medium",
        )
    )
    assert budget_result.success is True
    assert budget_result.data["calculation_source"] == "fixed_offline_dataset"
    assert budget_result.data["breakdown"]["food"]["calculation_rule"] == (
        "total_cost = reference_price_cny * diner_count * meal_count"
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
        {"case_id": "offline-env", "user_input": "北京三日游"},
        method="full_system",
    )

    assert result["method"] == "adaptive_multi_agent"
    assert result["raw_output"] == {"case_id": "offline-env", "offline": True}
    assert result["output"]["schema_version"] == "ctp-experiment-output-v1"
    assert result["output"]["raw_output"] == {"case_id": "offline-env", "offline": True}


def test_invalid_weather_scenario_fails_without_sunny_fallback(monkeypatch) -> None:
    monkeypatch.setenv("TOURISM_FORMAL_EXPERIMENT_OFFLINE", "true")

    default_result = asyncio.run(WeatherTool().execute("北京", scenario_type="", days=1))
    assert default_result.success is True
    assert default_result.data["scenario_type"] == "sunny"

    invalid_result = asyncio.run(
        WeatherTool().execute("北京", scenario_type="not_a_valid_scenario", days=1)
    )
    assert invalid_result.success is False
    assert invalid_result.metadata["offline"] is True
    assert "unsupported fixed weather scenario" in invalid_result.error


def test_concrete_missing_poi_search_returns_empty(monkeypatch) -> None:
    monkeypatch.setenv("TOURISM_FORMAL_EXPERIMENT_OFFLINE", "true")

    result = asyncio.run(
        POISearchTool().execute("完全不存在的具体景点XYZ", "北京", limit=3)
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
            city="桂林",
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
            city="桂林",
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
            "destination": "上海",
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
    assert response.data["calculation_source"] == "fixed_offline_dataset"
    assert "unsupported fixed experiment city" in response.error


def test_formal_offline_tourism_tools_do_not_use_network(monkeypatch) -> None:
    monkeypatch.setenv("TOURISM_FORMAL_EXPERIMENT_OFFLINE", "true")

    async def forbidden_poi_client():
        raise AssertionError("network access is forbidden in formal offline mode")

    class ForbiddenAsyncClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("network access is forbidden in formal offline mode")

    monkeypatch.setattr(poi_search_module, "_get_poi_http_client", forbidden_poi_client)
    monkeypatch.setattr(weather_module.httpx, "AsyncClient", ForbiddenAsyncClient)
    monkeypatch.setattr(route_plan_module.httpx, "AsyncClient", ForbiddenAsyncClient)

    search_result = asyncio.run(POISearchTool().execute("景点", "北京", limit=1))
    weather_result = asyncio.run(WeatherTool().execute("北京", scenario_type="sunny", days=1))
    route_result = asyncio.run(
        RoutePlanningTool().execute(
            origin="bj001",
            destination="bj_da001",
            city="北京",
            mode="public_transit",
        )
    )
    budget_result = asyncio.run(
        BudgetCalculatorTool().execute(
            destination="北京",
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
