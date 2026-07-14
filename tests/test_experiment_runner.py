import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.experiment_runner import ExperimentRunner
from app.core.llm.client import ToolCall
from app.core.tracing import get_current_trace, record_selected_tool, set_trace_selected_agents


def test_runner_runs_same_case_through_three_methods_and_exports_csv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def fake_handler(case):
        set_trace_selected_agents(case["expected"]["selected_agents"])
        record_selected_tool("weather")
        trace = get_current_trace()
        assert trace is not None
        trace.mark_first_body_token()
        return f"output for {case['case_id']}"

    benchmark = {
        "cases": [
            {
                "case_id": "case001",
                "user_input": "五一去桂林天气怎么样？",
                "slots": {"destination": "桂林"},
                "constraints": ["五一天气"],
                "expected": {
                    "intent": "weather_adjustment",
                    "route": "FULL_NEW_PLAN",
                    "selected_agents": ["weather"],
                    "selected_tools": ["weather"],
                },
            }
        ]
    }
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(json.dumps(benchmark, ensure_ascii=False), encoding="utf-8")

    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        output_dir=tmp_path / "results",
        method_handlers={
            "llm_direct": fake_handler,
            "single_agent": fake_handler,
            "full_system": fake_handler,
        },
    )

    results = runner.run_benchmark(benchmark_path)

    assert [(item["case_id"], item["method"]) for item in results] == [
        ("case001", "llm_direct"),
        ("case001", "single_agent"),
        ("case001", "full_system"),
    ]
    for result in results:
        assert set(result) >= {"case_id", "method", "output", "latency", "trace"}
        assert result["evaluation_mode"] == "end_to_end"
        assert result["trace"]["experiment_case_id"] == "case001"
        assert result["trace"]["method"] == result["method"]
        assert result["trace"]["evaluation_mode"] == "end_to_end"
        assert result["trace"]["intent"] == "general_chat"
        assert result["trace"]["route"] == "GENERAL_CHAT"
        assert result["trace"]["selected_agents"] == ["weather"]
        assert result["trace"]["selected_tools"] == ["weather"]
        assert result["ttft_ms"] == result["trace"]["first_body_token_ms"]
        assert result["metrics"]["tool_selection_accuracy"] == 1.0
        assert result["metrics"]["intent_correct"] is False
        assert result["metrics"]["route_correct"] is False

    csv_path = tmp_path / "results" / "benchmark_results.csv"
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    assert [row["method"] for row in rows] == ["llm_direct", "single_agent", "full_system"]
    assert all(row["case_id"] == "case001" for row in rows)
    assert all(row["evaluation_mode"] == "end_to_end" for row in rows)
    assert all(row["tool_selection_accuracy"] == "1.0" for row in rows)
    assert all(float(row["ttft_ms"]) >= 0 for row in rows)


def test_llm_baselines_do_not_write_expected_intent_or_route_to_end_to_end_trace(
    tmp_path: Path,
) -> None:
    class FakeLLM:
        async def chat(self, messages, tools=None):
            return SimpleNamespace(
                content="baseline output",
                tool_calls=[],
                usage={"total_tokens": 1},
            )

    case = {
        "case_id": "case001",
        "user_input": "plan Hangzhou for three days",
        "slots": {"destination": "Hangzhou", "duration": 3},
        "expected": {
            "intent": "trip_planning",
            "route": "FULL_NEW_PLAN",
            "selected_agents": ["PlannerAgent"],
        },
    }
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=FakeLLM)

    llm_direct = runner.run(case, method="llm_direct")
    single_agent = runner.run(case, method="single_agent")

    for result in (llm_direct, single_agent):
        trace = result["trace"]
        assert result["evaluation_mode"] == "end_to_end"
        assert trace["evaluation_mode"] == "end_to_end"
        assert trace["intent"] == "general_chat"
        assert trace["route"] == "GENERAL_CHAT"
        assert trace["extracted_info"] == {}
        assert result["metrics"]["intent_correct"] is False
        assert result["metrics"]["route_correct"] is False


def test_oracle_slots_mode_marks_trace_and_may_use_gold_intent_route_and_slots(
    tmp_path: Path,
) -> None:
    class FakeLLM:
        async def chat(self, messages, tools=None):
            return SimpleNamespace(
                content="oracle output",
                tool_calls=[],
                usage={"total_tokens": 1},
            )

    case = {
        "case_id": "case001",
        "evaluation_mode": "oracle_slots",
        "user_input": "plan Hangzhou for three days",
        "slots": {"destination": "Hangzhou", "duration": 3},
        "constraints": ["three day itinerary"],
        "expected": {
            "intent": "trip_planning",
            "route": "FULL_NEW_PLAN",
        },
    }
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=FakeLLM)

    result = runner.run(case, method="llm_direct")

    assert result["evaluation_mode"] == "oracle_slots"
    assert result["trace"]["evaluation_mode"] == "oracle_slots"
    assert result["trace"]["intent"] == "trip_planning"
    assert result["trace"]["route"] == "FULL_NEW_PLAN"
    assert result["trace"]["extracted_info"] == {"destination": "Hangzhou", "duration": 3}
    assert result["metrics"]["intent_correct"] is True
    assert result["metrics"]["route_correct"] is True


def test_single_agent_uses_tourism_tools_and_separates_planned_from_executed(
    tmp_path: Path,
) -> None:
    class FakeLLM:
        def __init__(self):
            self.calls = []

        async def chat(self, messages, tools=None):
            self.calls.append((list(messages), list(tools or [])))
            if len(self.calls) == 1:
                return SimpleNamespace(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="budget-1",
                            name="budget_calculator",
                            arguments=json.dumps(
                                {
                                    "destination": "Hangzhou",
                                    "duration": 3,
                                    "num_travelers": 2,
                                    "budget_level": "medium",
                                }
                            ),
                        )
                    ],
                    usage={"total_tokens": 10},
                )
            return SimpleNamespace(
                content="tool-backed plan",
                tool_calls=[],
                usage={"total_tokens": 20},
            )

    fake_llm = FakeLLM()
    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        llm_factory=lambda: fake_llm,
    )

    result = runner.run(
        {
            "case_id": "single-tools",
            "user_input": "Plan a three-day Hangzhou trip for two people.",
        },
        method="single_agent",
    )

    assert result["output"] == "tool-backed plan"
    assert len(fake_llm.calls) == 2
    assert {tool.name for tool in fake_llm.calls[0][1]} == {
        "poi_search",
        "poi_detail",
        "weather_query",
        "route_planning",
        "budget_calculator",
        "budget_optimizer",
    }
    second_messages = fake_llm.calls[1][0]
    assert second_messages[-2].role == "assistant"
    assert second_messages[-2].tool_calls[0].name == "budget_calculator"
    assert second_messages[-2].to_dict()["tool_calls"][0]["function"]["name"] == "budget_calculator"
    assert second_messages[-1].role == "tool"
    assert second_messages[-1].tool_call_id == "budget-1"

    trace = result["trace"]
    assert trace["planned_agents"] == ["single_agent"]
    assert trace["executed_agents"] == ["single_agent"]
    assert trace["planned_tools"] == ["budget_calculator"]
    assert trace["executed_tools"] == ["budget_calculator"]
    assert trace["tool_calls"][0]["tool_name"] == "budget_calculator"
    assert trace["tool_calls"][0]["status"] == "completed"


def test_runner_loads_default_benchmark_shape(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "dataset_id": "demo",
                "cases": [
                    {
                        "case_id": "case001",
                        "user_input": "帮我规划杭州3天旅游",
                        "expected": {"intent": "trip_planning"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    cases = runner.load_benchmark(benchmark_path)

    assert cases[0]["case_id"] == "case001"
    assert cases[0]["user_input"] == "帮我规划杭州3天旅游"
