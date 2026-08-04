import asyncio
import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.core.experiment_runner as experiment_runner_module
from app.core.experiment_method_input import build_generation_case
from app.core.experiment_runner import (
    RESEARCH_AGENT_DECISION_SCHEMA_VERSION,
    ExperimentRunner,
)
from app.core.fixed_data import get_fixed_tourism_data
from app.core.goal_state_scheduler import DECISION_SCHEMA_VERSION, TICKET_SCHEMA_VERSION
from app.core.llm.client import ToolCall
from app.core.tool_executor import ToolExecutor
from app.tools.base import ToolResult
from app.tools.research_tools import (
    GENERATION_TOOL_NAMES,
    ResearchBudgetCalculatorTool,
    ResearchConstraintCheckerTool,
    ResearchPOISearchTool,
    ResearchWeatherTool,
    build_research_tool_catalog,
    generation_tools,
)


class _AgentJSONLLM:
    async def chat(self, messages, tools=None):
        payload = self._agent_payload(messages)
        content = self._agent_decision_content(payload) if payload else "tool based answer"
        return SimpleNamespace(content=content, tool_calls=[], usage={"total_tokens": 1})

    def _agent_payload(self, messages):
        try:
            payload = json.loads(messages[-1].content)
        except (json.JSONDecodeError, TypeError, AttributeError, IndexError):
            return {}
        return payload if isinstance(payload, dict) and payload.get("agent_name") else {}

    def _agent_decision_content(self, payload):
        agent_name = str(payload.get("agent_name") or "")
        tool_evidence = payload.get("tool_evidence") if isinstance(payload.get("tool_evidence"), dict) else {}
        attractions = self._attractions(tool_evidence)
        selected_ids = [str(item.get("poi_id")) for item in attractions[:4] if item.get("poi_id")]
        task_slots = payload.get("task_slots") if isinstance(payload.get("task_slots"), dict) else {}
        days = int(task_slots.get("duration_days") or 2)

        if agent_name == "attraction":
            decisions = {"selected_poi_ids": selected_ids, "ranking_reason": "test evidence order"}
        elif agent_name == "weather":
            decisions = {"risk_days": [], "adjustment_required": False}
        elif agent_name == "itinerary":
            decisions = {
                "daily_itinerary": [
                    {
                        "day": day,
                        "attraction_poi_ids": selected_ids[(day - 1) * 2 : day * 2] or selected_ids[:1],
                        "notes": f"test itinerary day {day}",
                    }
                    for day in range(1, days + 1)
                ]
            }
        elif agent_name == "budget":
            budget_data = self._tool_data(tool_evidence.get("budget_calculator"))
            decisions = {
                "feasibility": "feasible",
                "budget_notes": "test budget decision",
                "recommended_total": budget_data.get("total"),
            }
        else:
            decisions = {}
        return json.dumps(
            {
                "schema_version": RESEARCH_AGENT_DECISION_SCHEMA_VERSION,
                "agent_name": agent_name,
                "summary": f"{agent_name} test decision",
                "decisions": decisions,
                "risks": [],
                "confidence": 1.0,
            },
            ensure_ascii=False,
        )

    def _tool_data(self, result):
        if not isinstance(result, dict):
            return {}
        data = result.get("data")
        return data if isinstance(data, dict) else {}

    def _attractions(self, tool_evidence):
        data = self._tool_data(tool_evidence.get("poi_search"))
        attractions = data.get("attractions") if isinstance(data, dict) else []
        return [item for item in attractions or [] if isinstance(item, dict)]


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
    first_attraction = poi_result.data["data"]["attractions"][0]
    assert "rain_suitability" in first_attraction
    assert "outdoor_ratio" in first_attraction
    assert "visit_intensity" in first_attraction
    assert "walking_level" in first_attraction

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


def test_weather_city_aliases_share_same_city_date_mapping() -> None:
    chinese_request = asyncio.run(
        ResearchWeatherTool().execute(city="杭州", date="2026-08-01", days=2)
    )
    english_request = asyncio.run(
        ResearchWeatherTool().execute(city="Hangzhou", date="2026-08-01", days=2)
    )

    assert chinese_request.success is True
    assert english_request.success is True
    assert chinese_request.data["data"]["scenario_type"] == english_request.data["data"]["scenario_type"]
    assert chinese_request.data["data"]["daily_weather"] == english_request.data["data"]["daily_weather"]
    assert chinese_request.data["metadata"]["canonical_city_id"] == "hangzhou"
    assert english_request.data["metadata"]["canonical_city_id"] == "hangzhou"


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


def test_invalid_numeric_tool_arguments_fail_instead_of_being_corrected() -> None:
    cases = [
        (ResearchPOISearchTool(), {"city": "Hangzhou", "limit": 999}),
        (ResearchPOISearchTool(), {"city": "Hangzhou", "limit": "abc"}),
        (ResearchWeatherTool(), {"city": "Hangzhou", "days": "abc"}),
        (ResearchWeatherTool(), {"city": "Hangzhou", "days": -3}),
        (ResearchBudgetCalculatorTool(), {"city": "Hangzhou", "days": "abc"}),
        (ResearchBudgetCalculatorTool(), {"city": "Hangzhou", "days": -3}),
        (ResearchBudgetCalculatorTool(), {"city": "Hangzhou", "days": 2, "people_count": "abc"}),
    ]

    for tool, arguments in cases:
        result = asyncio.run(tool.execute(**arguments))
        assert result.success is False
        assert result.data["status"] == "failed"
        assert result.data["error"]["code"] == "invalid_arguments"


def test_tool_executor_invalid_arguments_return_standard_error_payload() -> None:
    executor = ToolExecutor(tools={"budget_calculator": ResearchBudgetCalculatorTool()})

    call = asyncio.run(
        executor.execute("budget_calculator", {"city": "Hangzhou"}, call_id="missing-days")
    )

    assert call.is_failed
    assert call.result["schema_version"] == "research_tool_result_v1"
    assert call.result["tool_contract_version"] == "ctp-research-tools-v1.0"
    assert call.result["tool_name"] == "budget_calculator"
    assert call.result["status"] == "failed"
    assert call.result["success"] is False
    assert call.result["error"]["code"] == "invalid_arguments"
    assert call.result["metadata"]["offline"] is True


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


def test_constraint_checker_detects_fictional_duplicate_required_and_forbidden_pois() -> None:
    result = asyncio.run(
        ResearchConstraintCheckerTool().execute(
            request={"city": "Hangzhou"},
            plan={
                "daily_itinerary": [
                    {
                        "day": 1,
                        "attractions": [
                            {"poi_id": "hz001", "name": "西湖风景名胜区"},
                            {"poi_id": "hz001", "name": "西湖风景名胜区"},
                            {"name": "不存在的幻想景点XYZ"},
                        ],
                    }
                ],
            },
            constraints={
                "must_include_pois": ["hz002"],
                "forbidden_pois": ["hz001"],
            },
        )
    )

    checks = {item["name"]: item for item in result.data["data"]["checks"]}
    assert checks["poi_existence"]["status"] == "failed"
    assert checks["duplicate_attractions"]["status"] == "failed"
    assert checks["must_include_pois"]["status"] == "failed"
    assert checks["forbidden_pois"]["status"] == "failed"
    assert "不存在的幻想景点XYZ" in checks["poi_existence"]["details"]["unresolved"]
    assert checks["must_include_pois"]["details"]["missing"] == ["hz002"]
    assert checks["forbidden_pois"]["details"]["violations"] == ["hz001"]


def test_constraint_checker_detects_rain_senior_and_tool_evidence_risks() -> None:
    result = asyncio.run(
        ResearchConstraintCheckerTool().execute(
            request={"city": "Beijing", "people": "senior travelers"},
            plan={
                "daily_itinerary": [{"day": 1, "attractions": [{"poi_id": "bj003"}]}],
                "weather": {"scenario_type": "rain"},
                "weather_adjustments": [{"action": "prepare umbrellas"}],
                "tool_results": {
                    "poi_search": {"status": "success", "success": True},
                },
            },
            constraints={"require_tool_evidence": True},
        )
    )

    checks = {item["name"]: item for item in result.data["data"]["checks"]}
    assert checks["poi_existence"]["status"] == "passed"
    assert checks["rain_attraction_suitability"]["status"] == "failed"
    assert checks["senior_accessibility"]["status"] == "failed"
    assert checks["tool_evidence"]["status"] == "failed"
    assert checks["tool_evidence"]["details"]["missing_or_failed"] == ["weather_query"]


def test_constraint_checker_passes_supported_indoor_senior_rain_plan_with_tool_evidence() -> None:
    result = asyncio.run(
        ResearchConstraintCheckerTool().execute(
            request={"city": "Hangzhou", "people": "senior travelers"},
            plan={
                "daily_itinerary": [{"day": 1, "attractions": [{"poi_id": "hz005"}]}],
                "weather": {"scenario_type": "rain"},
                "weather_adjustments": [{"action": "prefer indoor museum visit"}],
                "tool_results": {
                    "poi_search": {"status": "success", "success": True},
                    "weather_query": {"status": "success", "success": True},
                },
            },
            constraints={
                "must_include_pois": ["hz005"],
                "forbidden_pois": ["hz001"],
                "require_tool_evidence": True,
            },
        )
    )

    checks = {item["name"]: item for item in result.data["data"]["checks"]}
    assert result.data["data"]["all_passed"] is True
    assert checks["poi_existence"]["status"] == "passed"
    assert checks["rain_attraction_suitability"]["status"] == "passed"
    assert checks["senior_accessibility"]["status"] == "passed"
    assert checks["tool_evidence"]["status"] == "passed"


def test_constraint_checker_accepts_explicit_rain_suitable_mixed_poi() -> None:
    result = asyncio.run(
        ResearchConstraintCheckerTool().execute(
            request={"city": "Xian"},
            plan={
                "daily_itinerary": [{"day": 1, "attractions": [{"poi_id": "xa004"}]}],
                "weather": {"scenario_type": "rain"},
                "weather_adjustments": [{"action": "prefer rain-suitable mixed POI"}],
            },
        )
    )

    checks = {item["name"]: item for item in result.data["data"]["checks"]}

    assert checks["poi_existence"]["status"] == "passed"
    assert checks["rain_attraction_suitability"]["status"] == "passed"


def test_constraint_checker_does_not_treat_planning_constraints_as_rain() -> None:
    result = asyncio.run(
        ResearchConstraintCheckerTool().execute(
            request={"city": "Hangzhou"},
            plan={
                "daily_itinerary": [{"day": 1, "attractions": [{"poi_id": "hz001"}]}],
                "weather": {
                    "scenario_type": "sunny",
                    "daily_weather": [
                        {
                            "day_index": 1,
                            "state": "sunny",
                            "weather": "晴天",
                            "precipitation_mm": 0,
                            "risk_tags": [],
                        }
                    ],
                    "planning_constraints": {
                        "dynamic_adjustment_required": False,
                    },
                    "weather_adjustment_required": False,
                },
                "weather_adjustments": [],
                "tool_results": {
                    "poi_search": {"status": "success", "success": True},
                    "weather_query": {"status": "success", "success": True},
                },
            },
            constraints={"require_tool_evidence": True},
        )
    )

    checks = {item["name"]: item for item in result.data["data"]["checks"]}
    assert checks["weather_adjustment"]["status"] == "NA"
    assert checks["rain_attraction_suitability"]["status"] == "NA"
    assert checks["rain_attraction_suitability"]["details"] == {"rain_detected": False}


def test_m3_uses_goal_state_scheduler_for_plan_selection() -> None:
    runner = ExperimentRunner()

    full_plan = runner._select_adaptive_research_plan(
        {
            "case_id": "full-plan",
            "user_input": (
                "请为两人规划杭州2天旅游，2026-08-01出发，"
                "预算5000元，需要景点、天气和预算。"
            ),
            "slots": {
                "destination": "杭州",
                "duration": 2,
                "num_travelers": 2,
                "start_date": "2026-08-01",
                "budget": 5000,
            },
            "constraints": [],
        }
    )
    attraction_plan = runner._select_adaptive_research_plan(
        {
            "case_id": "attractions",
            "user_input": "推荐杭州景点",
            "slots": {"destination": "杭州"},
            "constraints": [],
        }
    )
    general_plan = runner._select_adaptive_research_plan(
        {
            "case_id": "chat",
            "user_input": "你好，介绍一下你自己",
            "slots": {},
            "constraints": [],
        }
    )

    assert full_plan["agents"] == ["attraction", "weather", "itinerary", "budget"]
    assert full_plan["tools"] == list(GENERATION_TOOL_NAMES)
    assert full_plan["scheduler"]["ticket"]["schema_version"] == TICKET_SCHEMA_VERSION
    assert full_plan["scheduler"]["ticket"]["task_type"] == "trip_planning"
    assert full_plan["scheduler"]["decision"]["schema_version"] == DECISION_SCHEMA_VERSION

    assert attraction_plan["agents"] == ["attraction"]
    assert attraction_plan["tools"] == ["poi_search"]
    assert attraction_plan["scheduler"]["ticket"]["task_type"] == "attraction_recommendation"

    assert general_plan["agents"] == []
    assert general_plan["tools"] == []
    assert general_plan["scheduler"]["decision"]["decision_reasons"] == ["general_chat_no_agents"]


def test_m3_chinese_attraction_only_keeps_requested_poi_count(tmp_path: Path) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=_AgentJSONLLM)

    result = runner.run(
        build_generation_case(
            {
                "case_id": "m3-chinese-two-attractions",
                "user_input": "只帮我挑深圳2个适合室内参观的景点，不要天气、行程和预算。",
            },
            "adaptive_multi_agent",
        ),
        method="adaptive_multi_agent",
    )

    scheduler = result["output"]["metadata"]["adaptive_scheduler"]
    assert scheduler["ticket"]["task_type"] == "attraction_recommendation"
    assert scheduler["decision"]["planned_agents"] == ["attraction"]
    assert scheduler["decision"]["planned_tools"] == ["poi_search"]
    assert result["trace"]["executed_tools"] == ["poi_search"]
    assert len(result["output"]["attractions"]) == 2
    assert result["output"]["weather"] is None
    assert result["output"]["budget"] is None


def test_m3_current_turn_slots_do_not_invalidate_reuse_from_history_text(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=_AgentJSONLLM)
    first = runner.run(
        build_generation_case(
            {
                "case_id": "m3-history-slot-turn1",
                "user_input": "先做杭州2026年8月16日出发的两天游，2个人，预算5300元，要包含景点、天气、行程和预算。",
            },
            "adaptive_multi_agent",
        ),
        method="adaptive_multi_agent",
    )
    second_case = build_generation_case(
        {
            "case_id": "m3-history-slot-turn2",
            "user_input": "把杭州这趟旅行改成3天，2026年8月16日、2个人和5300元预算都保持不变。",
            "dialogue_history": [
                {
                    "role": "assistant",
                    "content": "上一轮答案提到了历史文化、自然、室内偏好和高温天气风险。",
                }
            ],
            "previous_state": first,
        },
        "adaptive_multi_agent",
    )

    assert "preferences" in second_case["parsed_slots"]
    assert "preferences" not in second_case["current_turn_slots"]
    second = runner.run(second_case, method="adaptive_multi_agent")

    scheduler = second["output"]["metadata"]["adaptive_scheduler"]
    assert scheduler["ticket"]["changed_slots"] == ["duration_days"]
    assert scheduler["ticket"]["preserved_slots"] == [
        "destination",
        "start_date",
        "people_count",
        "budget_amount",
    ]
    assert scheduler["decision"]["planned_agents"] == ["weather", "itinerary", "budget"]
    assert scheduler["decision"]["planned_tools"] == ["weather_query", "budget_calculator"]
    assert scheduler["decision"]["reused_agents"] == ["attraction"]


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
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "schema_version": "ctp-experiment-output-v1",
                        "case_id": "m0-zero-tools",
                        "method": "llm_direct",
                        "task_type": "trip_planning",
                        "planned_agents": [],
                        "used_agents": [],
                        "planned_tools": [],
                        "called_tools": [],
                        "tool_results": {},
                        "attractions": [{"name": "西湖"}],
                        "trip_days": 2,
                        "daily_itinerary": [{"day": 1, "attractions": [{"name": "西湖"}]}],
                        "budget": {"total": 1000},
                        "weather": {"condition": "sunny"},
                        "weather_adjustments": [],
                        "execution_status": "completed",
                        "final_answer": "direct answer",
                        "metadata": {"structured_by_llm": True},
                    },
                    ensure_ascii=False,
                ),
                tool_calls=[],
                usage={"total_tokens": 1},
            )

    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=FakeLLM)
    result = runner.run(
        {"case_id": "m0-zero-tools", "user_input": "杭州两天怎么玩？"},
        method="llm_direct",
    )

    assert result["raw_output"]["schema_version"] == "ctp-experiment-output-v1"
    assert result["raw_output"]["method"] == "llm_direct"
    assert result["raw_output"]["planned_agents"] == []
    assert result["raw_output"]["used_agents"] == []
    assert result["raw_output"]["planned_tools"] == []
    assert result["raw_output"]["tool_results"] == {}
    assert result["raw_output"]["final_answer"] == "direct answer"
    assert result["output"]["tool_results"] == {}
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
    assert result["trace"]["status"] == "failed"
    assert result["status"] == "failed"
    assert result["output"]["execution_status"] == "failed"
    assert result["trace"]["tool_calls"][0]["tool_name"] == "poi_search"
    assert result["trace"]["tool_calls"][0]["success"] is False
    assert result["raw_output"]["execution_status"] == "failed"
    assert result["raw_output"]["tool_results"]["poi_search"]["status"] == "failed"
    assert result["raw_output"]["tool_results"]["poi_search"]["error"]["code"] == "invalid_tool_arguments"


def test_failed_tool_call_marks_method_output_and_result_failed(tmp_path: Path) -> None:
    class FakeLLM:
        def __init__(self):
            self.calls = 0

        async def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="missing-days",
                            name="budget_calculator",
                            arguments=json.dumps({"city": "Hangzhou"}),
                        )
                    ],
                    usage={"total_tokens": 1},
                )
            return SimpleNamespace(content="recovered", tool_calls=[], usage={"total_tokens": 1})

    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=FakeLLM)
    result = runner.run(
        {"case_id": "failed-tool-status", "user_input": "Calculate Hangzhou budget"},
        method="single_agent",
    )

    assert result["trace"]["failed_tool_call_count"] == 1
    assert result["trace"]["status"] == "failed"
    assert result["output"]["called_tools"][0]["status"] == "failed"
    assert result["output"]["called_tools"][0]["success"] is False
    assert result["output"]["execution_status"] == "failed"
    assert result["status"] == "failed"
    assert result["raw_output"]["tool_results"]["budget_calculator"]["status"] == "failed"
    assert result["output"]["tool_results"]["budget_calculator"]["status"] == "failed"


def test_real_m2_and_m3_use_same_unified_tool_results(tmp_path: Path) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=_AgentJSONLLM)
    case = {
        "case_id": "m2-m3-tools",
        "user_input": "帮我规划杭州两天2人旅游，2026-08-01出发",
        "slots": {
            "destination": "杭州",
            "duration": 2,
            "num_travelers": 2,
            "start_date": "2026-08-01",
        },
    }

    m2 = runner.run(case, method="fixed_multi_agent")
    m3 = runner.run(case, method="adaptive_multi_agent")

    assert m2["trace"]["executed_tools"] == list(GENERATION_TOOL_NAMES)
    assert m3["trace"]["executed_tools"] == list(GENERATION_TOOL_NAMES)
    assert m2["output"]["budget"]["total"] == m3["output"]["budget"]["total"]
    assert m2["output"]["weather"]["daily_weather"] == m3["output"]["weather"]["daily_weather"]
    assert m2["output"]["daily_itinerary"] == m3["output"]["daily_itinerary"]
    assert m3["output"]["metadata"]["adaptive_scheduler"]["ticket"]["task_type"] == "trip_planning"
    assert m3["output"]["metadata"]["adaptive_scheduler"]["decision"]["planned_tools"] == list(GENERATION_TOOL_NAMES)
    assert m3["output"]["metadata"]["scheduler"] == m3["output"]["metadata"]["adaptive_scheduler"]
    assert m3["trace"]["scheduler"] == m3["trace"]["adaptive_scheduler"]
    assert m3["output"]["planned_agents"] == ["attraction", "weather", "itinerary", "budget"]
    assert m3["output"]["used_agents"] == m3["trace"]["executed_agents"]
    assert m3["output"]["planned_tools"] == list(GENERATION_TOOL_NAMES)
    assert [call["tool_name"] for call in m3["output"]["called_tools"]] == list(GENERATION_TOOL_NAMES)
    assert m3["output"]["tool_results"].keys() >= set(GENERATION_TOOL_NAMES)
    assert m3["output"]["attractions"]
    assert m2["result_hash"]
    assert m2["offline_data"]["combined_sha256"] == m3["offline_data"]["combined_sha256"]


def test_real_m3_executes_only_goal_state_selected_tools(tmp_path: Path) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=_AgentJSONLLM)
    result = runner.run(
        {
            "case_id": "m3-attractions-only",
            "user_input": "推荐杭州景点",
            "slots": {"destination": "杭州"},
        },
        method="adaptive_multi_agent",
    )

    assert result["trace"]["planned_agents"] == ["attraction"]
    assert result["trace"]["executed_agents"] == ["attraction"]
    assert result["trace"]["planned_tools"] == ["poi_search"]
    assert result["trace"]["executed_tools"] == ["poi_search"]
    assert result["output"]["budget"] is None
    assert result["output"]["weather"] is None
    assert result["output"]["metadata"]["adaptive_scheduler"]["ticket"]["task_type"] == "attraction_recommendation"


def test_real_m3_reuses_previous_attractions_when_duration_changes(tmp_path: Path) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=_AgentJSONLLM)
    first = runner.run(
        {
            "case_id": "m3-turn1-full",
            "user_input": "帮我规划杭州两天2人旅游，2026-08-01出发",
            "slots": {
                "destination": "杭州",
                "duration": 2,
                "num_travelers": 2,
                "start_date": "2026-08-01",
            },
        },
        method="adaptive_multi_agent",
    )

    second = runner.run(
        {
            "case_id": "m3-turn2-duration",
            "user_input": "把行程改成3天，其他条件不变",
            "slots": {"duration": 3},
            "previous_state": first,
        },
        method="adaptive_multi_agent",
    )

    scheduler = second["output"]["metadata"]["adaptive_scheduler"]
    assert scheduler["ticket"]["task_type"] == "partial_replan"
    assert scheduler["ticket"]["current_slots"]["destination"] == "hangzhou"
    assert scheduler["ticket"]["current_slots"]["duration_days"] == 3
    assert scheduler["decision"]["reused_agents"] == ["attraction"]
    assert scheduler["decision"]["invalidated_agents"] == ["weather", "itinerary", "budget"]
    assert scheduler["reuse_execution"]["reused_tool_results"] == ["poi_search"]
    assert scheduler["reuse_execution"]["missing_reused_tool_results"] == []
    assert scheduler["reuse_execution"]["reuse_hit_rate"] == 1.0
    assert scheduler["result_fingerprints"]["attraction"]["destination"] == "hangzhou"
    assert second["trace"]["adaptive_scheduler"]["ticket"]["task_type"] == "partial_replan"
    assert second["trace"]["adaptive_scheduler"]["decision"]["reused_agents"] == ["attraction"]
    assert second["trace"]["adaptive_scheduler"]["reuse_execution"]["reuse_hit_rate"] == 1.0
    assert second["output"]["metadata"]["scheduler"] == scheduler
    assert second["output"]["metadata"]["reuse_execution"] == scheduler["reuse_execution"]

    assert second["trace"]["planned_agents"] == ["weather", "itinerary", "budget"]
    assert second["trace"]["executed_agents"] == ["weather", "itinerary", "budget"]
    assert second["trace"]["planned_tools"] == ["weather_query", "budget_calculator"]
    assert second["trace"]["executed_tools"] == ["weather_query", "budget_calculator"]
    assert second["output"]["planned_agents"] == ["weather", "itinerary", "budget"]
    assert second["output"]["used_agents"] == second["trace"]["executed_agents"]
    assert second["output"]["planned_tools"] == ["weather_query", "budget_calculator"]
    assert "poi_search" in second["raw_output"]["tool_results"]
    assert "poi_search" in second["output"]["tool_results"]
    assert second["raw_output"]["tool_results"]["poi_search"] == first["raw_output"]["tool_results"]["poi_search"]
    assert second["output"]["tool_results"]["poi_search"] == first["raw_output"]["tool_results"]["poi_search"]
    assert len(second["output"]["daily_itinerary"]) == 3
    assert second["output"]["budget"]["days"] == 3

    metrics = second["metrics"]
    assert metrics["m3_scheduler_name"] == "goal_state_scheduler"
    assert metrics["m3_task_type"] == "partial_replan"
    assert metrics["m3_decision_reasons"] == ["duration_changed_partial_replan"]
    assert metrics["m3_planned_agent_count"] == 3
    assert metrics["m3_executed_agent_count"] == 3
    assert metrics["m3_reused_agent_count"] == 1
    assert metrics["m3_invalidated_agent_count"] == 3
    assert metrics["m3_planned_tool_count"] == 2
    assert metrics["m3_executed_tool_count"] == 2
    assert metrics["m3_expected_reused_tool_count"] == 1
    assert metrics["m3_reused_tool_result_count"] == 1
    assert metrics["m3_missing_reused_tool_result_count"] == 0
    assert metrics["m3_agent_reuse_rate"] == 0.25
    assert metrics["m3_tool_reuse_rate"] == 0.3333
    assert metrics["m3_reuse_hit_rate"] == 1.0
    assert metrics["m3_agent_call_savings_vs_m2"] == 1
    assert metrics["m3_tool_call_savings_vs_m2"] == 1
    assert metrics["m3_agent_call_reduction_rate_vs_m2"] == 0.25
    assert metrics["m3_tool_call_reduction_rate_vs_m2"] == 0.3333
    assert second["output"]["metadata"]["adaptive_scheduler_metrics"]["m3_reused_agents"] == ["attraction"]

    csv_path = tmp_path / "m3_scheduler_metrics.csv"
    runner.export_csv([second], csv_path)
    row = next(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    assert row["m3_task_type"] == "partial_replan"
    assert row["m3_decision_reasons"] == "duration_changed_partial_replan"
    assert row["m3_reused_agents"] == "attraction"
    assert row["m3_invalidated_agents"] == "weather|itinerary|budget"
    assert row["m3_reused_tool_results"] == "poi_search"
    assert row["m3_planned_agent_count"] == "3"
    assert row["m3_reused_agent_count"] == "1"
    assert row["m3_agent_reuse_rate"] == "0.25"
    assert row["m3_tool_call_savings_vs_m2"] == "1"


def test_real_m3_reuses_all_results_for_identical_followup(tmp_path: Path) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=_AgentJSONLLM)
    first = runner.run(
        {
            "case_id": "m3-identical-turn1",
            "user_input": "帮我规划桂林两天2人旅游，2026-08-01出发",
            "slots": {
                "destination": "桂林",
                "duration": 2,
                "num_travelers": 2,
                "start_date": "2026-08-01",
            },
        },
        method="adaptive_multi_agent",
    )
    first["raw_output"]["daily_itinerary"][0]["reuse_marker"] = "old-itinerary-marker"
    first["output"]["daily_itinerary"][0]["reuse_marker"] = "old-itinerary-marker"
    first["output"]["raw_output"]["daily_itinerary"][0]["reuse_marker"] = "old-itinerary-marker"

    second = runner.run(
        {
            "case_id": "m3-identical-turn2",
            "user_input": "同样的安排再给我一遍",
            "slots": {},
            "previous_state": first,
        },
        method="adaptive_multi_agent",
    )

    scheduler = second["output"]["metadata"]["adaptive_scheduler"]
    assert scheduler["decision"]["decision_reasons"] == ["identical_request_reuse_all"]
    assert scheduler["decision"]["reused_agents"] == ["attraction", "weather", "itinerary", "budget"]
    assert scheduler["reuse_execution"]["reused_tool_results"] == list(GENERATION_TOOL_NAMES)
    assert scheduler["reuse_execution"]["missing_reused_tool_results"] == []

    assert second["trace"]["planned_agents"] == []
    assert second["trace"]["executed_agents"] == []
    assert second["trace"]["planned_tools"] == []
    assert second["trace"]["executed_tools"] == []
    assert second["trace"]["tool_call_count"] == 0
    assert second["output"]["daily_itinerary"] == first["output"]["daily_itinerary"]
    assert second["output"]["daily_itinerary"][0]["reuse_marker"] == "old-itinerary-marker"
    assert second["output"]["budget"] == first["output"]["budget"]
    assert second["output"]["weather"] == first["output"]["weather"]

    metrics = second["metrics"]
    assert metrics["m3_planned_agent_count"] == 0
    assert metrics["m3_executed_agent_count"] == 0
    assert metrics["m3_reused_agent_count"] == 4
    assert metrics["m3_reused_tool_result_count"] == 3
    assert metrics["m3_agent_reuse_rate"] == 1.0
    assert metrics["m3_tool_reuse_rate"] == 1.0
    assert metrics["m3_reuse_hit_rate"] == 1.0
    assert metrics["m3_agent_call_savings_vs_m2"] == 4
    assert metrics["m3_tool_call_savings_vs_m2"] == 3
    assert metrics["m3_agent_call_reduction_rate_vs_m2"] == 1.0
    assert metrics["m3_tool_call_reduction_rate_vs_m2"] == 1.0


def test_m3_does_not_count_available_markers_without_artifacts_as_call_savings(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=_AgentJSONLLM)
    result = runner.run(
        {
            "case_id": "m3-marker-only-history",
            "user_input": "same plan again",
            "slots": {},
            "previous_state": {
                "slots": {
                    "destination": "hangzhou",
                    "start_date": "2026-08-01",
                    "duration_days": 2,
                    "people_count": 2,
                },
                "available_results": {
                    "attraction": True,
                    "weather": True,
                    "itinerary": True,
                    "budget": True,
                },
            },
        },
        method="adaptive_multi_agent",
    )

    scheduler = result["output"]["metadata"]["adaptive_scheduler"]
    assert scheduler["decision"]["planned_agents"] == [
        "attraction",
        "weather",
        "itinerary",
        "budget",
    ]
    assert scheduler["decision"]["reused_agents"] == []
    assert scheduler["reuse_execution"]["reused_agent_results"] == []
    assert scheduler["reuse_execution"]["missing_reused_agent_results"] == []
    assert result["metrics"]["m3_reused_agent_count"] == 0
    assert result["metrics"]["m3_reused_tool_result_count"] == 0
    assert result["metrics"]["m3_agent_call_savings_vs_m2"] == 0
    assert result["metrics"]["m3_tool_call_savings_vs_m2"] == 0
    assert result["metrics"]["m3_agent_call_reduction_rate_vs_m2"] == 0.0
    assert result["metrics"]["m3_tool_call_reduction_rate_vs_m2"] == 0.0


def test_m3_stops_downstream_agents_after_upstream_tool_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FailingPOITool(ResearchPOISearchTool):
        async def execute(self, **kwargs):
            payload = {
                "schema_version": "research_tool_result_v1",
                "tool_name": "poi_search",
                "status": "failed",
                "success": False,
                "input": kwargs,
                "data": {},
                "error": {"code": "forced_failure", "message": "forced poi failure"},
                "metadata": {"offline": True},
            }
            return ToolResult(success=False, data=payload, error="forced poi failure")

    monkeypatch.setattr(
        experiment_runner_module,
        "generation_tools",
        lambda: [FailingPOITool(), ResearchWeatherTool(), ResearchBudgetCalculatorTool()],
    )

    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=_AgentJSONLLM)
    result = runner.run(
        {
            "case_id": "m3-upstream-poi-failure",
            "user_input": "plan a two day Hangzhou trip on 2026-08-01 for two people",
            "slots": {
                "destination": "hangzhou",
                "duration": 2,
                "people_count": 2,
                "start_date": "2026-08-01",
            },
        },
        method="adaptive_multi_agent",
    )

    assert result["status"] == "failed"
    assert result["raw_output"]["execution_status"] == "failed"
    assert result["trace"]["planned_agents"] == ["attraction", "weather", "itinerary", "budget"]
    assert result["trace"]["executed_agents"] == ["attraction", "weather"]
    assert result["trace"]["executed_tools"] == ["poi_search", "weather_query"]
    assert "budget_calculator" not in result["raw_output"]["tool_results"]
    assert result["raw_output"]["daily_itinerary"] == []
    assert result["raw_output"]["metadata"]["result_agents"] == ["weather"]
    scheduler = result["output"]["metadata"]["adaptive_scheduler"]
    assert set(scheduler["result_fingerprints"]) == {"weather"}


def test_m3_metrics_survive_llm_answer_timeout_via_trace_scheduler(
    tmp_path: Path,
) -> None:
    class TimeoutLLM:
        async def chat(self, messages, tools=None):
            raise TimeoutError("forced answer timeout")

    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=TimeoutLLM)
    result = runner.run(
        {
            "case_id": "m3-timeout-keeps-scheduler-metrics",
            "user_input": "plan a two day Hangzhou trip on 2026-08-01 for two people",
            "slots": {
                "destination": "hangzhou",
                "duration": 2,
                "people_count": 2,
                "start_date": "2026-08-01",
            },
        },
        method="adaptive_multi_agent",
    )

    assert result["status"] == "completed"
    assert result["trace"]["status"] == "completed"
    assert "最终答案整理模型调用超时" in result["output"]["final_answer"]
    assert all(
        output["decision_fallback_used"]
        for output in result["output"]["agent_outputs"].values()
    )
    assert result["trace"]["adaptive_scheduler"]["name"] == "goal_state_scheduler"
    assert result["metrics"]["m3_scheduler_name"] == "goal_state_scheduler"
    assert result["metrics"]["m3_planned_agent_count"] == 4
    assert result["metrics"]["m3_planned_tool_count"] == 3
    assert result["metrics"]["m3_reused_agent_count"] == 0


def test_experiment_session_id_is_isolated_by_repeat_index(tmp_path: Path) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=_AgentJSONLLM)
    case = {
        "case_id": "repeat-session-isolation",
        "user_input": "recommend attractions in Hangzhou",
        "slots": {"destination": "hangzhou"},
    }

    first = runner.run(case, method="adaptive_multi_agent", repeat_index=0)
    second = runner.run(case, method="adaptive_multi_agent", repeat_index=1)

    assert first["trace"]["session_id"].endswith("-r0")
    assert second["trace"]["session_id"].endswith("-r1")
    assert first["trace"]["session_id"] != second["trace"]["session_id"]


def test_experiment_session_id_is_isolated_by_run_id(tmp_path: Path) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=_AgentJSONLLM)
    case = {
        "case_id": "run-session-isolation",
        "user_input": "recommend attractions in Hangzhou",
        "slots": {"destination": "hangzhou"},
    }

    first = runner.run(
        case,
        method="adaptive_multi_agent",
        run_id="run-A",
        repeat_index=0,
    )
    second = runner.run(
        case,
        method="adaptive_multi_agent",
        run_id="run-B",
        repeat_index=0,
    )

    assert "-run-run-A-r0" in first["trace"]["session_id"]
    assert "-run-run-B-r0" in second["trace"]["session_id"]
    assert first["trace"]["session_id"] != second["trace"]["session_id"]


def test_real_m3_rejects_reuse_when_previous_tool_input_fingerprint_mismatches(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=_AgentJSONLLM)
    beijing = runner.run(
        {
            "case_id": "m3-wrong-fingerprint-source",
            "user_input": "帮我规划北京两天2人旅游，2026-08-01出发",
            "slots": {
                "destination": "beijing",
                "duration": 2,
                "num_travelers": 2,
                "start_date": "2026-08-01",
            },
        },
        method="adaptive_multi_agent",
    )
    previous_state = {
        "slots": {
            "destination": "hangzhou",
            "duration_days": 2,
            "people_count": 2,
            "start_date": "2026-08-01",
        },
        "available_results": {"attraction": True},
        "tool_results": {
            "poi_search": beijing["raw_output"]["tool_results"]["poi_search"],
        },
    }

    result = runner.run(
        {
            "case_id": "m3-wrong-fingerprint-current",
            "user_input": "改成三天，其他不变",
            "slots": {"duration": 3},
            "previous_state": previous_state,
        },
        method="adaptive_multi_agent",
    )

    scheduler = result["output"]["metadata"]["adaptive_scheduler"]
    assert "attraction" not in scheduler["decision"]["reused_agents"]
    assert "attraction" in scheduler["decision"]["invalidated_agents"]
    assert scheduler["decision"]["reuse_validation"]["unusable_reasons"]["attraction"] == (
        "input_fingerprint_mismatch"
    )
    assert result["trace"]["planned_agents"] == ["attraction", "weather", "itinerary", "budget"]
    assert result["trace"]["executed_tools"] == list(GENERATION_TOOL_NAMES)
    assert result["raw_output"]["tool_results"]["poi_search"]["input"]["city"] == "hangzhou"
    assert result["metrics"]["m3_reused_tool_result_count"] == 0


def test_real_m3_rejects_failed_previous_tool_result_for_reuse(tmp_path: Path) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=_AgentJSONLLM)
    failed_poi = {
        "schema_version": "research_tool_result_v1",
        "tool_name": "poi_search",
        "status": "failed",
        "success": False,
        "input": {
            "city": "hangzhou",
            "preferences": [],
            "people": "general",
            "limit": 4,
        },
        "data": {},
        "error": {"code": "forced_failure", "message": "previous call failed"},
        "metadata": {"offline": True},
    }

    result = runner.run(
        {
            "case_id": "m3-failed-reuse",
            "user_input": "改成三天，其他不变",
            "slots": {"duration": 3},
            "previous_state": {
                "slots": {
                    "destination": "hangzhou",
                    "duration_days": 2,
                    "people_count": 2,
                    "start_date": "2026-08-01",
                },
                "available_results": {"attraction": True},
                "tool_results": {"poi_search": failed_poi},
            },
        },
        method="adaptive_multi_agent",
    )

    scheduler = result["output"]["metadata"]["adaptive_scheduler"]
    assert scheduler["decision"]["reused_agents"] == []
    assert scheduler["decision"]["reuse_validation"]["unusable_reasons"]["attraction"] == (
        "previous_result_failed"
    )
    assert result["trace"]["planned_agents"] == ["attraction", "weather", "itinerary", "budget"]
    assert result["raw_output"]["tool_results"]["poi_search"]["status"] == "success"
    assert result["metrics"]["m3_reused_tool_result_count"] == 0


def test_fixed_m2_and_adaptive_m3_receive_same_previous_slots_for_followup(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=_AgentJSONLLM)
    first = runner.run(
        {
            "case_id": "fair-turn1",
            "user_input": "帮我规划杭州两天2人旅游，2026-08-01出发",
            "slots": {
                "destination": "hangzhou",
                "duration": 2,
                "num_travelers": 2,
                "start_date": "2026-08-01",
            },
        },
        method="adaptive_multi_agent",
    )
    followup = {
        "case_id": "fair-turn2",
        "user_input": "把两天改成三天，其他不变",
        "slots": {"duration": 3},
        "previous_state": first,
    }

    m2 = runner.run(followup, method="fixed_multi_agent")
    m3 = runner.run(followup, method="adaptive_multi_agent")

    assert m2["trace"]["planned_agents"] == ["attraction", "weather", "itinerary", "budget"]
    assert m2["trace"]["executed_tools"] == list(GENERATION_TOOL_NAMES)
    assert m2["raw_output"]["tool_results"]["poi_search"]["input"]["city"] == "hangzhou"
    assert m2["raw_output"]["tool_results"]["weather_query"]["input"]["city"] == "hangzhou"
    assert m2["raw_output"]["tool_results"]["budget_calculator"]["input"]["city"] == "hangzhou"
    assert m2["output"]["execution_status"] == "completed"

    assert m3["output"]["metadata"]["adaptive_scheduler"]["ticket"]["current_slots"]["destination"] == (
        "hangzhou"
    )
    assert m3["trace"]["planned_agents"] == ["weather", "itinerary", "budget"]
    assert m3["metrics"]["m3_m2_reference_agent_count"] == 4
    assert m3["metrics"]["m3_agent_call_savings_vs_m2"] == 1


def test_m3_general_chat_followup_has_zero_m2_reference_savings_and_trace_scheduler(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=_AgentJSONLLM)
    first = runner.run(
        {
            "case_id": "chat-savings-turn1",
            "user_input": "帮我规划杭州两天2人旅游，2026-08-01出发",
            "slots": {
                "destination": "hangzhou",
                "duration": 2,
                "num_travelers": 2,
                "start_date": "2026-08-01",
            },
        },
        method="adaptive_multi_agent",
    )

    second = runner.run(
        {
            "case_id": "chat-savings-turn2",
            "user_input": "谢谢，今天心情不错。",
            "slots": {},
            "previous_state": first,
        },
        method="adaptive_multi_agent",
    )

    scheduler = second["output"]["metadata"]["adaptive_scheduler"]
    trace_scheduler = second["trace"]["adaptive_scheduler"]

    assert scheduler["ticket"]["task_type"] == "general_chat"
    assert second["trace"]["planned_agents"] == []
    assert second["trace"]["executed_tools"] == []
    assert second["metrics"]["m3_m2_reference_agent_count"] == 0
    assert second["metrics"]["m3_m2_reference_tool_count"] == 0
    assert second["metrics"]["m3_agent_call_savings_vs_m2"] == 0
    assert second["metrics"]["m3_tool_call_savings_vs_m2"] == 0
    assert second["metrics"]["m3_agent_call_reduction_rate_vs_m2"] is None
    assert trace_scheduler["ticket"]["task_type"] == "general_chat"
    assert trace_scheduler["decision"]["decision_reasons"] == ["general_chat_no_agents"]


def test_single_capability_and_clarification_do_not_create_fake_itinerary_fingerprints(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=_AgentJSONLLM)

    weather = runner.run(
        {
            "case_id": "fingerprint-weather-only",
            "user_input": "weather in Hangzhou on 2026-08-01 for two days",
            "slots": {
                "destination": "hangzhou",
                "start_date": "2026-08-01",
                "duration": 2,
            },
        },
        method="adaptive_multi_agent",
    )
    weather_scheduler = weather["output"]["metadata"]["adaptive_scheduler"]
    assert weather["trace"]["planned_agents"] == ["weather"]
    assert weather["output"]["daily_itinerary"] == []
    assert set(weather_scheduler["result_fingerprints"]) == {"weather"}

    attraction = runner.run(
        {
            "case_id": "fingerprint-attraction-only",
            "user_input": "recommend attractions in Hangzhou",
            "slots": {"destination": "hangzhou"},
        },
        method="adaptive_multi_agent",
    )
    attraction_scheduler = attraction["output"]["metadata"]["adaptive_scheduler"]
    assert attraction["trace"]["planned_agents"] == ["attraction"]
    assert attraction["output"]["daily_itinerary"] == []
    assert set(attraction_scheduler["result_fingerprints"]) == {"attraction"}


def test_m3_clarification_outputs_clarification_without_agents_or_fake_results(
    tmp_path: Path,
) -> None:
    class CountingLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def chat(self, messages, tools=None):
            self.calls += 1
            return SimpleNamespace(content="should not be called", tool_calls=[], usage={"total_tokens": 1})

    llm = CountingLLM()
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=lambda: llm)
    result = runner.run(
        {
            "case_id": "clarification-no-destination",
            "user_input": "plan a 3 day trip on 2026-08-01 for two people",
            "slots": {
                "start_date": "2026-08-01",
                "duration": 3,
                "people_count": 2,
            },
        },
        method="adaptive_multi_agent",
    )

    scheduler = result["output"]["metadata"]["adaptive_scheduler"]
    assert result["status"] == "clarification"
    assert result["trace"]["status"] == "clarification"
    assert result["trace"]["planned_agents"] == []
    assert result["trace"]["executed_agents"] == []
    assert result["trace"]["planned_tools"] == []
    assert result["trace"]["executed_tools"] == []
    assert result["output"]["daily_itinerary"] == []
    assert scheduler["decision"]["clarification_fields"] == ["destination"]
    assert scheduler["result_fingerprints"] == {}
    assert "目的地城市" in result["output"]["final_answer"]
    assert result["metrics"]["m3_m2_reference_agent_count"] == 4
    assert result["metrics"]["m3_m2_reference_tool_count"] == 3
    assert result["metrics"]["m3_agent_call_savings_vs_m2"] == 4
    assert result["metrics"]["m3_tool_call_savings_vs_m2"] == 3
    assert llm.calls == 0


def test_m3_budget_query_with_only_weather_history_replans_attraction_before_budget(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=_AgentJSONLLM)
    first = runner.run(
        {
            "case_id": "budget-after-weather-turn1",
            "user_input": "weather in Hangzhou on 2026-08-01 for two days",
            "slots": {
                "destination": "hangzhou",
                "start_date": "2026-08-01",
                "duration": 2,
            },
        },
        method="adaptive_multi_agent",
    )

    second = runner.run(
        {
            "case_id": "budget-after-weather-turn2",
            "user_input": "how much will attraction tickets and admission cost for four people",
            "slots": {"people_count": 4},
            "previous_state": first,
        },
        method="adaptive_multi_agent",
    )

    scheduler = second["output"]["metadata"]["adaptive_scheduler"]
    assert scheduler["ticket"]["task_type"] == "budget_query"
    assert scheduler["decision"]["planned_agents"] == ["attraction", "budget"]
    assert scheduler["decision"]["reused_agents"] == []
    assert second["trace"]["executed_tools"] == ["poi_search", "budget_calculator"]
    budget_input = second["raw_output"]["tool_results"]["budget_calculator"]["input"]
    assert budget_input["city"] == "hangzhou"
    assert budget_input["people_count"] == 4
    assert budget_input["attractions"]
    assert set(scheduler["result_fingerprints"]) == {"attraction", "budget"}


def test_m3_rough_budget_query_without_ticket_terms_uses_budget_only(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=_AgentJSONLLM)
    result = runner.run(
        {
            "case_id": "rough-budget-only",
            "user_input": "rough budget estimate for a two day Hangzhou trip for two people",
            "slots": {
                "destination": "hangzhou",
                "duration": 2,
                "people_count": 2,
            },
        },
        method="adaptive_multi_agent",
    )

    scheduler = result["output"]["metadata"]["adaptive_scheduler"]
    assert scheduler["ticket"]["task_type"] == "budget_query"
    assert scheduler["ticket"]["dependency_policy"] == {
        "budget_scope": "rough_budget_without_ticket_dependency",
        "requires_attraction_evidence": False,
    }
    assert scheduler["decision"]["planned_agents"] == ["budget"]
    assert scheduler["decision"]["planned_tools"] == ["budget_calculator"]
    assert result["trace"]["executed_tools"] == ["budget_calculator"]
    assert "poi_search" not in result["raw_output"]["tool_results"]
    assert result["raw_output"]["tool_results"]["budget_calculator"]["input"]["attractions"] == []
    assert result["output"]["execution_status"] == "completed"


def test_fixed_m2_can_continue_from_its_own_previous_state(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=_AgentJSONLLM)
    first = runner.run(
        {
            "case_id": "m2-own-state-turn1",
            "user_input": "plan a two day Hangzhou trip on 2026-08-01 for two people",
            "slots": {
                "destination": "hangzhou",
                "duration": 2,
                "people_count": 2,
                "start_date": "2026-08-01",
            },
        },
        method="fixed_multi_agent",
    )

    second = runner.run(
        {
            "case_id": "m2-own-state-turn2",
            "user_input": "change it to three days, keep the other conditions",
            "slots": {"duration": 3},
            "previous_state": first,
        },
        method="fixed_multi_agent",
    )

    assert second["trace"]["planned_agents"] == ["attraction", "weather", "itinerary", "budget"]
    assert second["trace"]["executed_tools"] == list(GENERATION_TOOL_NAMES)
    assert second["raw_output"]["tool_results"]["poi_search"]["input"]["city"] == "hangzhou"
    assert second["raw_output"]["tool_results"]["weather_query"]["input"]["city"] == "hangzhou"
    assert second["raw_output"]["tool_results"]["budget_calculator"]["input"]["city"] == "hangzhou"
    assert second["raw_output"]["tool_results"]["weather_query"]["input"]["days"] == 3
    assert second["raw_output"]["tool_results"]["budget_calculator"]["input"]["days"] == 3
    assert second["output"]["execution_status"] == "completed"


def test_m3_weather_adjustment_output_includes_affected_day_index(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=_AgentJSONLLM)
    first = runner.run(
        {
            "case_id": "weather-adjust-day-turn1",
            "user_input": "plan a two day Hangzhou trip on 2026-08-01 for two people with attractions weather and budget",
            "slots": {
                "destination": "hangzhou",
                "duration": 2,
                "people_count": 2,
                "start_date": "2026-08-01",
                "budget": 5000,
            },
        },
        method="adaptive_multi_agent",
    )

    second = runner.run(
        {
            "case_id": "weather-adjust-day-turn2",
            "user_input": "The second day becomes rain. Adjust the itinerary for rainy weather.",
            "previous_state": first,
            "weather_change": {"scenario_type": "rain", "affected_days": [2]},
        },
        method="adaptive_multi_agent",
    )

    scheduler = second["output"]["metadata"]["adaptive_scheduler"]
    assert scheduler["ticket"]["task_type"] == "weather_adjustment"
    assert scheduler["decision"]["planned_agents"] == ["weather", "itinerary"]
    assert any(
        item.get("day") == 2 and item.get("day_index") == 2
        for item in second["output"]["weather_adjustments"]
    )


def test_research_answer_organizer_prompt_does_not_expose_method_name(
    tmp_path: Path,
) -> None:
    class CapturingLLM(_AgentJSONLLM):
        def __init__(self) -> None:
            self.calls = []

        async def chat(self, messages, tools=None):
            self.calls.append(messages)
            return await super().chat(messages, tools=tools)

    llm = CapturingLLM()
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=lambda: llm)
    runner.run(
        {
            "case_id": "organizer-method-hidden",
            "user_input": "plan a two day Hangzhou trip on 2026-08-01 for two people with attractions weather and budget",
            "slots": {
                "destination": "hangzhou",
                "duration": 2,
                "people_count": 2,
                "start_date": "2026-08-01",
                "budget": 5000,
            },
        },
        method="fixed_multi_agent",
    )

    final_prompts = [
        str(getattr(message, "content", "") or "")
        for messages in llm.calls
        for message in messages
        if "planned_agents" in str(getattr(message, "content", "") or "")
        and "weather_adjustments" in str(getattr(message, "content", "") or "")
    ]
    assert final_prompts
    assert all('"method": "fixed_multi_agent"' not in prompt for prompt in final_prompts)


def test_beijing_accommodation_sources_do_not_reference_wrong_xian_source() -> None:
    data = json.loads((ROOT / "data" / "accommodation" / "beijing.json").read_text(encoding="utf-8"))
    bad_sources = [
        source
        for area in data.get("accommodation_areas", [])
        for source in area.get("sources", [])
        if "西安旅游网" in source.get("source_name", "")
        or str(source.get("url") or "").startswith("https://www.tang.org.cn/")
    ]

    assert bad_sources == []
