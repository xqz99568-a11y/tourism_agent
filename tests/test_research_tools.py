import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.experiment_runner import ExperimentRunner
from app.core.fixed_data import get_fixed_tourism_data
from app.core.llm.client import ToolCall
from app.tools.research_tools import (
    GENERATION_TOOL_NAMES,
    ResearchBudgetCalculatorTool,
    ResearchConstraintCheckerTool,
    ResearchPOISearchTool,
    ResearchWeatherTool,
    build_research_tool_catalog,
    generation_tools,
)


def test_unified_research_tool_catalog_names_are_frozen() -> None:
    catalog = build_research_tool_catalog()

    assert list(catalog) == [
        "poi_search",
        "weather_query",
        "budget_calculator",
        "constraint_checker",
    ]
    assert [tool.name for tool in generation_tools()] == list(GENERATION_TOOL_NAMES)


def test_research_tools_return_standard_envelopes_and_fixed_data() -> None:
    poi_result = asyncio.run(
        ResearchPOISearchTool().execute(
            city="Hangzhou",
            preferences=["景点"],
            people="couple",
            limit=2,
        )
    )
    assert poi_result.success is True
    assert poi_result.api_calls == []
    assert poi_result.data["schema_version"] == "research_tool_result_v1"
    assert poi_result.data["tool_name"] == "poi_search"
    assert poi_result.data["status"] == "success"
    assert len(poi_result.data["data"]["attractions"]) == 2
    assert poi_result.data["data"]["attractions"][0]["evidence"]["offline"] is True

    weather_result = asyncio.run(
        ResearchWeatherTool().execute(
            city="Hangzhou",
            date="2026-08-01",
            days=2,
            scenario_type="rain",
        )
    )
    assert weather_result.success is True
    assert weather_result.api_calls == []
    assert weather_result.data["tool_name"] == "weather_query"
    assert [item["date"] for item in weather_result.data["data"]["daily_weather"]] == [
        "2026-08-01",
        "2026-08-02",
    ]

    budget_result = asyncio.run(
        ResearchBudgetCalculatorTool().execute(
            city="Hangzhou",
            people_count=2,
            days=2,
            attractions=["hz001"],
            spending_level="medium",
        )
    )
    assert budget_result.success is True
    assert budget_result.api_calls == []
    assert budget_result.data["tool_name"] == "budget_calculator"
    assert budget_result.data["data"]["total"] > 0
    assert budget_result.data["metadata"]["calculation_source"] == "fixed_offline_dataset"


def test_research_tools_are_deterministic_across_repeated_calls() -> None:
    poi_args = {"city": "Hangzhou", "preferences": ["景点"], "people": "couple", "limit": 3}
    weather_args = {"city": "Hangzhou", "date": "2026-08-01", "days": 2}
    budget_args = {"city": "Hangzhou", "people_count": 2, "days": 2, "attractions": ["hz002"]}

    first = [
        asyncio.run(ResearchPOISearchTool().execute(**poi_args)).data,
        asyncio.run(ResearchWeatherTool().execute(**weather_args)).data,
        asyncio.run(ResearchBudgetCalculatorTool().execute(**budget_args)).data,
    ]
    second = [
        asyncio.run(ResearchPOISearchTool().execute(**poi_args)).data,
        asyncio.run(ResearchWeatherTool().execute(**weather_args)).data,
        asyncio.run(ResearchBudgetCalculatorTool().execute(**budget_args)).data,
    ]

    assert first == second


def test_weather_is_uniquely_determined_by_city_and_date() -> None:
    sunny_request = asyncio.run(
        ResearchWeatherTool().execute(
            city="Hangzhou",
            date="2026-08-01",
            days=2,
            scenario_type="sunny",
        )
    )
    rain_request = asyncio.run(
        ResearchWeatherTool().execute(
            city="Hangzhou",
            date="2026-08-01",
            days=2,
            scenario_type="rain",
        )
    )

    assert sunny_request.success is True
    assert rain_request.success is True
    assert sunny_request.data["data"]["scenario_type"] == rain_request.data["data"]["scenario_type"]
    assert sunny_request.data["data"]["daily_weather"] == rain_request.data["data"]["daily_weather"]
    assert sunny_request.data["data"]["scenario_selection"] == "city_date_hash"


def test_unknown_ticket_prices_use_explicit_experiment_estimates() -> None:
    result = get_fixed_tourism_data().calculate_budget(
        destination="Hangzhou",
        duration=1,
        num_travelers=2,
        budget_level="medium",
        poi_ids=["hz002"],
    )
    ticket = result["ticket_breakdown"]

    assert ticket["ticket_cost"] > 0
    assert ticket["summary"]["estimated_ticket_count"] == 1
    assert ticket["details"][0]["status"] == "estimated"
    assert ticket["details"][0]["counted_amount_yuan"] > 0
    assert "experiment_ticket_estimate_v1" in ticket["details"][0]["estimation_rule"]


def test_research_tool_failures_have_standard_error_payload() -> None:
    result = asyncio.run(ResearchWeatherTool().execute(city="Hangzhou", date="bad-date"))

    assert result.success is False
    assert result.data["status"] == "failed"
    assert result.data["error"]["code"] == "invalid_arguments"
    assert result.data["error"]["retryable"] is False


def test_constraint_checker_reports_applicable_constraints() -> None:
    result = asyncio.run(
        ResearchConstraintCheckerTool().execute(
            request={"days": 2, "budget": 3000},
            plan={
                "daily_itinerary": [{"day": 1}, {"day": 2}],
                "budget": {"total": 2500},
                "weather": {"scenario_type": "rain"},
                "weather_adjustments": [{"action": "indoor"}],
            },
            constraints={"min_attractions": 0},
        )
    )

    assert result.success is True
    assert result.data["data"]["all_passed"] is True
    assert result.data["data"]["applicable_count"] >= 3


def test_m2_and_m3_generation_catalogs_are_identical() -> None:
    runner = ExperimentRunner()

    fixed_plan = {
        "agents": ["attraction", "weather", "itinerary", "budget"],
        "tools": list(GENERATION_TOOL_NAMES),
    }
    adaptive_plan = runner._select_adaptive_research_plan(
        {
            "case_id": "case",
            "user_input": "帮我规划杭州两天旅游",
            "slots": {"destination": "杭州", "duration": 2},
            "constraints": [],
        }
    )

    assert fixed_plan["tools"] == list(GENERATION_TOOL_NAMES)
    assert adaptive_plan["tools"] == fixed_plan["tools"]


def test_constraint_checker_runs_after_method_output(tmp_path: Path) -> None:
    async def handler(case):
        return {
            "daily_itinerary": [{"day": 1}, {"day": 2}],
            "budget": {"total": 1800},
            "weather": {"scenario_type": "sunny"},
            "weather_adjustments": [],
            "final_answer": "ok",
        }

    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        method_handlers={"adaptive_multi_agent": handler},
    )
    result = runner.run(
        {
            "case_id": "constraint-auto",
            "user_input": "帮我规划杭州两天旅游，预算2000",
            "slots": {"destination": "杭州", "duration": 2, "budget": 2000},
        },
        method="adaptive_multi_agent",
    )

    assert result["constraint_report"]["tool_name"] == "constraint_checker"
    assert result["hard_constraint_applicable_count"] >= 2
    assert result["hard_constraint_failed_count"] == 0
    assert result["hcsr"] == 1.0
    assert result["metrics"]["hcsr"] == 1.0
    assert result["output"]["constraint_report"]["tool_name"] == "constraint_checker"


def test_m0_llm_direct_has_zero_tool_calls(tmp_path: Path) -> None:
    class FakeLLM:
        async def chat(self, messages, tools=None):
            return SimpleNamespace(content="direct answer", tool_calls=[], usage={"total_tokens": 1})

    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=FakeLLM)
    result = runner.run(
        {"case_id": "m0-zero-tools", "user_input": "杭州两天怎么玩？"},
        method="llm_direct",
    )

    assert result["trace"]["tool_call_count"] == 0
    assert result["trace"]["tool_calls"] == []
    assert result["trace"]["executed_tools"] == []


def test_invalid_json_tool_arguments_are_recorded_as_failed_tool_calls(tmp_path: Path) -> None:
    class FakeLLM:
        def __init__(self):
            self.calls = 0

        async def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    content="",
                    tool_calls=[ToolCall(id="bad-json", name="poi_search", arguments="{bad")],
                    usage={"total_tokens": 1},
                )
            return SimpleNamespace(content="recovered", tool_calls=[], usage={"total_tokens": 1})

    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=FakeLLM)
    result = runner.run(
        {"case_id": "bad-json", "user_input": "推荐杭州景点"},
        method="single_agent",
    )

    assert result["trace"]["tool_call_count"] == 1
    assert result["trace"]["failed_tool_call_count"] == 1
    assert result["trace"]["tool_calls"][0]["tool_name"] == "poi_search"
    assert result["trace"]["tool_calls"][0]["success"] is False


def test_real_m2_and_m3_use_same_unified_tool_results(tmp_path: Path) -> None:
    class FakeLLM:
        async def chat(self, messages, tools=None):
            return SimpleNamespace(content="tool based answer", tool_calls=[], usage={"total_tokens": 1})

    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=FakeLLM)
    case = {
        "case_id": "m2-m3-tools",
        "user_input": "帮我规划杭州两天旅游",
        "slots": {"destination": "杭州", "duration": 2},
    }

    m2 = runner.run(case, method="fixed_multi_agent")
    m3 = runner.run(case, method="adaptive_multi_agent")

    assert m2["trace"]["executed_tools"] == list(GENERATION_TOOL_NAMES)
    assert m3["trace"]["executed_tools"] == list(GENERATION_TOOL_NAMES)
    assert m2["output"]["budget"]["total"] == m3["output"]["budget"]["total"]
    assert m2["output"]["weather"]["daily_weather"] == m3["output"]["weather"]["daily_weather"]
    assert m2["output"]["daily_itinerary"] == m3["output"]["daily_itinerary"]
    assert m2["result_hash"]
    assert m2["offline_data"]["combined_sha256"] == m3["offline_data"]["combined_sha256"]
