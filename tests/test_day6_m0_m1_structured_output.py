import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.experiment_runner import ExperimentRunner
from app.core.experiment_method_input import METHOD_INPUT_SCHEMA_VERSION
from app.core.llm.client import ToolCall
from app.schemas.experiment import EXPERIMENT_OUTPUT_SCHEMA_VERSION
from app.tools.research_tools import GENERATION_TOOL_NAMES


def _structured_llm_json(
    *,
    case_id: str,
    method: str,
    final_answer: str,
    trip_days: int | None = 2,
    attractions: list[dict] | None = None,
    daily_itinerary: list[dict] | None = None,
    budget: dict | None = None,
    weather: dict | None = None,
) -> str:
    return json.dumps(
        {
            "schema_version": EXPERIMENT_OUTPUT_SCHEMA_VERSION,
            "case_id": case_id,
            "method": method,
            "task_type": "trip_planning",
            "planned_agents": [],
            "used_agents": [],
            "planned_tools": [],
            "called_tools": [],
            "tool_results": {},
            "attractions": attractions
            if attractions is not None
            else [{"name": "West Lake", "city": "Hangzhou"}],
            "trip_days": trip_days,
            "daily_itinerary": daily_itinerary
            if daily_itinerary is not None
            else [{"day": 1, "attractions": [{"name": "West Lake"}]}],
            "budget": budget if budget is not None else {"total": 1200},
            "weather": weather if weather is not None else {"condition": "sunny"},
            "weather_adjustments": [],
            "execution_status": "completed",
            "final_answer": final_answer,
            "metadata": {"structured_by_llm": True},
        },
        ensure_ascii=False,
    )


def test_day6_m0_returns_structured_no_tool_output(tmp_path: Path) -> None:
    class FakeLLM:
        async def chat(self, messages, tools=None):
            assert tools is None
            return SimpleNamespace(
                content=_structured_llm_json(
                    case_id="day6-m0-structured",
                    method="llm_direct",
                    final_answer="direct baseline answer",
                ),
                tool_calls=[],
                usage={"total_tokens": 1},
            )

    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=FakeLLM)
    result = runner.run(
        {
            "case_id": "day6-m0-structured",
            "user_input": "Plan a two day Hangzhou trip for two people.",
        },
        method="llm_direct",
    )

    raw = result["raw_output"]
    assert raw["schema_version"] == EXPERIMENT_OUTPUT_SCHEMA_VERSION
    assert raw["method"] == "llm_direct"
    assert raw["planned_agents"] == []
    assert raw["used_agents"] == []
    assert raw["planned_tools"] == []
    assert raw["called_tools"] == []
    assert raw["tool_results"] == {}
    assert raw["trip_days"] == 2
    assert raw["daily_itinerary"] == [{"day": 1, "attractions": [{"name": "West Lake"}]}]
    assert raw["budget"] == {"total": 1200}
    assert raw["weather"] == {"condition": "sunny"}
    assert raw["final_answer"] == "direct baseline answer"
    assert raw["metadata"]["structured_llm_output"]["parse_status"] == "passed"
    assert result["output"]["schema_version"] == EXPERIMENT_OUTPUT_SCHEMA_VERSION
    assert result["output"]["tool_results"] == {}
    assert result["trace"]["tool_call_count"] == 0


def test_day6_m0_invalid_json_is_method_failure(tmp_path: Path) -> None:
    class FakeLLM:
        async def chat(self, messages, tools=None):
            return SimpleNamespace(
                content="direct baseline answer",
                tool_calls=[],
                usage={"total_tokens": 1},
            )

    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=FakeLLM)
    result = runner.run(
        {
            "case_id": "day6-m0-invalid-json",
            "user_input": "Plan a two day Hangzhou trip for two people.",
        },
        method="llm_direct",
    )

    assert result["status"] == "failed"
    assert result["output"]["execution_status"] == "failed"
    assert result["output"]["daily_itinerary"] == []
    assert result["output"]["budget"] is None
    assert result["output"]["weather"] is None
    assert result["output"]["metadata"]["structured_llm_output"]["parse_status"] == "failed"


def test_day6_m1_preserves_real_tool_results_for_evaluation(tmp_path: Path) -> None:
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
                            id="poi-1",
                            name="poi_search",
                            arguments=json.dumps({"city": "Hangzhou", "limit": 4}),
                        ),
                        ToolCall(
                            id="weather-1",
                            name="weather_query",
                            arguments=json.dumps(
                                {
                                    "city": "Hangzhou",
                                    "date": "2026-08-01",
                                    "days": 2,
                                    "scenario_type": "sunny",
                                }
                            ),
                        ),
                        ToolCall(
                            id="budget-1",
                            name="budget_calculator",
                            arguments=json.dumps(
                                {
                                    "city": "Hangzhou",
                                    "people_count": 2,
                                    "days": 2,
                                    "spending_level": "medium",
                                }
                            ),
                        ),
                    ],
                    usage={"total_tokens": 10},
                )
            return SimpleNamespace(
                content=_structured_llm_json(
                    case_id="day6-m1-tool-evidence",
                    method="single_agent",
                    final_answer="tool grounded answer",
                    attractions=[{"name": "LLM selected West Lake"}],
                    daily_itinerary=[
                        {
                            "day": 1,
                            "attractions": [{"name": "LLM selected West Lake"}],
                            "notes": "generated by single Agent",
                        }
                    ],
                    budget={"total": 1800, "source": "single_agent_decision"},
                    weather={"condition": "sunny", "source": "single_agent_decision"},
                ),
                tool_calls=[],
                usage={"total_tokens": 20},
            )

    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=FakeLLM)
    result = runner.run(
        {
            "case_id": "day6-m1-tool-evidence",
            "user_input": "Plan a two day Hangzhou trip on 2026-08-01 for two people.",
            "expected": {"hard_constraints": {"require_tool_evidence": True}},
        },
        method="single_agent",
    )

    raw = result["raw_output"]
    output = result["output"]
    checks = {item["name"]: item for item in result["constraint_report"]["data"]["checks"]}

    assert raw["schema_version"] == EXPERIMENT_OUTPUT_SCHEMA_VERSION
    assert raw["method"] == "single_agent"
    assert raw["metadata"]["method_input_schema_version"] == METHOD_INPUT_SCHEMA_VERSION
    assert raw["planned_agents"] == ["single_agent"]
    assert raw["used_agents"] == ["single_agent"]
    assert raw["planned_tools"] == list(GENERATION_TOOL_NAMES)
    assert raw["tool_results"].keys() >= set(GENERATION_TOOL_NAMES)
    assert output["tool_results"] == raw["tool_results"]
    assert output["daily_itinerary"] == [
        {
            "day": 1,
            "attractions": [{"name": "LLM selected West Lake"}],
            "notes": "generated by single Agent",
        }
    ]
    assert output["budget"] == {"total": 1800, "source": "single_agent_decision"}
    assert output["weather"] == {"condition": "sunny", "source": "single_agent_decision"}
    assert output["called_tools"][0]["tool_name"] == "poi_search"
    assert output["called_tools"][1]["tool_name"] == "weather_query"
    assert output["called_tools"][2]["tool_name"] == "budget_calculator"
    assert raw["tool_results"]["poi_search"]["schema_version"] == "research_tool_result_v1"
    assert raw["tool_results"]["weather_query"]["input"]["city"] == "Hangzhou"
    assert raw["tool_results"]["budget_calculator"]["input"]["people_count"] == 2
    assert checks["tool_evidence"]["status"] == "passed"
    assert checks["tool_evidence"]["details"]["missing_or_failed"] == []
