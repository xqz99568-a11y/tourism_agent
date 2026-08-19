import asyncio
import csv
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.experiment_runner import (
    BENCHMARK_RESUME_STATE_NAME,
    BENCHMARK_CHECKPOINT_JSON_NAME,
    RESEARCH_AGENT_DECISION_SCHEMA_VERSION,
    RESEARCH_AGENT_OUTPUT_SCHEMA_VERSION,
    ExperimentRunner,
    _experiment_llm_call_timeout_seconds,
)
from app.core.fixed_data import (
    CANONICAL_JSON_SHA256_STRATEGY,
    FIXED_DATA_EXPECTED_COMBINED_SHA256,
)
from app.core.independent_evaluator import (
    EVALUATION_SCHEMA_VERSION,
    EVALUATION_SUMMARY_SCHEMA_VERSION,
)
from app.core.llm.client import ToolCall
from app.core.intercity_transport_snapshot import load_intercity_transport_snapshot_manifest
from app.core.no_date_weather_policy import NO_DATE_WEATHER_REMINDER
from app.core.qweather_snapshot import load_qweather_snapshot_manifest
from app.core.tracing import get_current_trace, record_selected_tool, set_trace_selected_agents
from app.tools.research_tools import GENERATION_TOOL_NAMES


def _qweather_snapshot_start_date() -> str:
    return str(load_qweather_snapshot_manifest()["forecast_start_date"])


def test_runner_runs_same_case_through_four_methods_and_exports_csv(
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
            "fixed_multi_agent": fake_handler,
            "adaptive_multi_agent": fake_handler,
        },
    )

    results = runner.run_benchmark(benchmark_path)
    expected_methods = runner._ordered_methods_for_case(
        list(ExperimentRunner.METHODS),
        case_id="case001",
        repeat_index=runner.repeat_index,
    )

    assert [(item["case_id"], item["method"]) for item in results] == [
        ("case001", method) for method in expected_methods
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
        assert result["evaluation"]["schema_version"] == EVALUATION_SCHEMA_VERSION
        assert result["evaluation"]["catalog_id"] == "day8_formal_independent_evaluator_rules"
        assert "stsr" in result["metrics"]

    csv_path = tmp_path / "results" / runner.run_id / "benchmark_results.csv"
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    assert [row["method"] for row in rows] == expected_methods
    assert all(row["case_id"] == "case001" for row in rows)
    assert all(row["evaluation_mode"] == "end_to_end" for row in rows)
    assert all(row["tool_selection_accuracy"] == "1.0" for row in rows)
    assert all(float(row["ttft_ms"]) >= 0 for row in rows)
    assert {"stsr", "evaluation_hcsr", "evaluation_failed_rule_ids", "agent_selection_f1", "tool_selection_f1"} <= set(rows[0])
    checkpoint_json = csv_path.parent / "benchmark_results.checkpoint.json"
    checkpoint_csv = csv_path.parent / "benchmark_results.checkpoint.csv"
    assert checkpoint_json.exists()
    assert checkpoint_csv.exists()
    assert len(json.loads(checkpoint_json.read_text(encoding="utf-8"))) == 4
    summary = json.loads((csv_path.parent / "evaluation_summary.json").read_text(encoding="utf-8"))
    assert summary["schema_version"] == EVALUATION_SUMMARY_SCHEMA_VERSION
    assert summary["result_count"] == 4


def test_result_level_timeout_returns_table_shaped_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def slow_handler(case):
        await asyncio.sleep(1)
        return f"late output for {case['case_id']}"

    monkeypatch.setenv("EXPERIMENT_RESULT_TIMEOUT_SECONDS", "0.01")
    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        output_dir=tmp_path / "results",
        method_handlers={"llm_direct": slow_handler},
    )

    result = runner.run(
        {
            "case_id": "timeout-case",
            "user_input": "hello",
            "expected": {"selected_agents": [], "selected_tools": []},
        },
        method="llm_direct",
    )

    assert result["status"] == "failed"
    assert "experiment result timeout" in result["error"]
    assert result["output"]["execution_status"] == "failed"


def test_benchmark_method_order_is_seeded_independently_per_case(
    tmp_path: Path,
) -> None:
    async def fake_handler(case):
        return f"output for {case['case_id']}"

    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        output_dir=tmp_path / "results",
        method_handlers={method: fake_handler for method in ExperimentRunner.METHODS},
        method_order_seed=20260718,
    )
    methods = list(ExperimentRunner.METHODS)
    candidate_ids = [f"case{i:03d}" for i in range(1, 20)]
    first_case, second_case = next(
        (left, right)
        for left in candidate_ids
        for right in candidate_ids
        if left != right
        and runner._ordered_methods_for_case(
            methods,
            case_id=left,
            repeat_index=runner.repeat_index,
        )
        != runner._ordered_methods_for_case(
            methods,
            case_id=right,
            repeat_index=runner.repeat_index,
        )
    )
    benchmark = {
        "cases": [
            {"case_id": first_case, "user_input": "hello"},
            {"case_id": second_case, "user_input": "hello again"},
        ]
    }
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(json.dumps(benchmark, ensure_ascii=False), encoding="utf-8")

    results = runner.run_benchmark(benchmark_path)
    expected = [
        *[
            (first_case, method)
            for method in runner._ordered_methods_for_case(
                methods,
                case_id=first_case,
                repeat_index=runner.repeat_index,
            )
        ],
        *[
            (second_case, method)
            for method in runner._ordered_methods_for_case(
                methods,
                case_id=second_case,
                repeat_index=runner.repeat_index,
            )
        ],
    ]

    assert [(item["case_id"], item["method"]) for item in results] == expected
    assert [method for case_id, method in expected if case_id == first_case] != [
        method for case_id, method in expected if case_id == second_case
    ]


def test_experiment_manifest_dataset_hash_ignores_json_formatting(tmp_path: Path) -> None:
    lf_path = tmp_path / "benchmark_lf.json"
    crlf_path = tmp_path / "benchmark_crlf.json"
    lf_path.write_bytes(
        b'{\n'
        b'  "dataset_version": "v1",\n'
        b'  "dataset_id": "formatting_cases",\n'
        b'  "cases": [\n'
        b'    {"case_id": "c1", "user_input": "plan"}\n'
        b'  ]\n'
        b'}\n'
    )
    crlf_path.write_bytes(
        b'{\r\n'
        b'  "cases": [\r\n'
        b'    {"user_input": "plan", "case_id": "c1"}\r\n'
        b'  ],\r\n'
        b'  "dataset_id": "formatting_cases",\r\n'
        b'  "dataset_version": "v1"\r\n'
        b'}\r\n'
    )
    assert hashlib.sha256(lf_path.read_bytes()).hexdigest() != hashlib.sha256(
        crlf_path.read_bytes()
    ).hexdigest()

    runner = ExperimentRunner(trace_dir=tmp_path / "traces", output_dir=tmp_path / "results")
    lf_manifest = runner.write_experiment_manifest(
        benchmark_path=lf_path,
        output_path=tmp_path / "manifest_lf.json",
    )
    crlf_manifest = runner.write_experiment_manifest(
        benchmark_path=crlf_path,
        output_path=tmp_path / "manifest_crlf.json",
    )

    assert lf_manifest["dataset_hash_strategy"] == CANONICAL_JSON_SHA256_STRATEGY
    assert lf_manifest["dataset_sha256"] == crlf_manifest["dataset_sha256"]
    assert lf_manifest["dataset"]["sha256"] == crlf_manifest["dataset"]["sha256"]
    assert lf_manifest["dataset"]["hash_strategy"] == CANONICAL_JSON_SHA256_STRATEGY
    assert lf_manifest["evaluation"]["schema_version"] == EVALUATION_SCHEMA_VERSION
    assert lf_manifest["evaluation"]["summary_schema_version"] == EVALUATION_SUMMARY_SCHEMA_VERSION
    assert lf_manifest["evaluation"]["catalog_id"] == "day8_formal_independent_evaluator_rules"
    assert lf_manifest["evaluation"]["catalog_sha256"] == crlf_manifest["evaluation"]["catalog_sha256"]


def test_llm_baselines_do_not_write_expected_intent_or_route_to_end_to_end_trace(
    tmp_path: Path,
) -> None:
    class FakeLLM:
        async def chat(self, messages, tools=None):
            method = "single_agent" if tools else "llm_direct"
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "schema_version": "ctp-experiment-output-v1",
                        "case_id": "case001",
                        "method": method,
                        "task_type": "trip_planning",
                        "planned_agents": ["single_agent"] if method == "single_agent" else [],
                        "used_agents": ["single_agent"] if method == "single_agent" else [],
                        "planned_tools": [],
                        "called_tools": [],
                        "tool_results": {},
                        "attractions": [],
                        "trip_days": 3,
                        "daily_itinerary": [],
                        "budget": None,
                        "weather": None,
                        "weather_adjustments": [],
                        "execution_status": "completed",
                        "final_answer": "baseline output",
                        "metadata": {"structured_by_llm": True},
                    },
                    ensure_ascii=False,
                ),
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
                content=json.dumps(
                    {
                        "schema_version": "ctp-experiment-output-v1",
                        "case_id": "case001",
                        "method": "llm_direct",
                        "task_type": "trip_planning",
                        "planned_agents": [],
                        "used_agents": [],
                        "planned_tools": [],
                        "called_tools": [],
                        "tool_results": {},
                        "attractions": [],
                        "trip_days": 3,
                        "daily_itinerary": [],
                        "budget": None,
                        "weather": None,
                        "weather_adjustments": [],
                        "execution_status": "completed",
                        "final_answer": "oracle output",
                        "metadata": {"structured_by_llm": True},
                    },
                    ensure_ascii=False,
                ),
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
                content=json.dumps(
                    {
                        "schema_version": "ctp-experiment-output-v1",
                        "case_id": "single-tools",
                        "method": "single_agent",
                        "task_type": "trip_planning",
                        "planned_agents": ["single_agent"],
                        "used_agents": ["single_agent"],
                        "planned_tools": [],
                        "called_tools": [],
                        "tool_results": {},
                        "attractions": [{"name": "West Lake"}],
                        "trip_days": 3,
                        "daily_itinerary": [{"day": 1, "attractions": [{"name": "West Lake"}]}],
                        "budget": {"total": 2400},
                        "weather": None,
                        "weather_adjustments": [],
                        "execution_status": "completed",
                        "final_answer": "tool-backed plan",
                        "metadata": {"structured_by_llm": True},
                    },
                    ensure_ascii=False,
                ),
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
            "evaluation_mode": "oracle_slots",
            "user_input": "Plan a three-day Hangzhou trip for two people.",
            "expected": {
                "required_tools": ["budget_calculator"],
            },
        },
        method="single_agent",
    )

    assert result["output"]["schema_version"] == "ctp-experiment-output-v1"
    assert result["output"]["final_answer"] == "tool-backed plan"
    assert result["raw_output"]["schema_version"] == "ctp-experiment-output-v1"
    assert result["raw_output"]["method"] == "single_agent"
    assert result["raw_output"]["planned_agents"] == ["single_agent"]
    assert result["raw_output"]["used_agents"] == ["single_agent"]
    assert result["raw_output"]["planned_tools"] == ["budget_calculator"]
    assert result["raw_output"]["final_answer"] == "tool-backed plan"
    assert result["raw_output"]["raw_output"]["final_answer"] == "tool-backed plan"
    assert result["raw_output"]["daily_itinerary"] == [{"day": 1, "attractions": [{"name": "West Lake"}]}]
    assert result["raw_output"]["budget"] == {"total": 2400}
    budget_result = result["raw_output"]["tool_results"]["budget_calculator"]
    assert budget_result["schema_version"] == "research_tool_result_v1"
    assert budget_result["tool_name"] == "budget_calculator"
    assert budget_result["status"] == "success"
    assert budget_result["input"]["city"] == "Hangzhou"
    assert budget_result["input"]["days"] == 3
    assert budget_result["input"]["people_count"] == 2
    assert result["output"]["tool_results"] == result["raw_output"]["tool_results"]
    assert len(fake_llm.calls) == 2
    assert {tool.name for tool in fake_llm.calls[0][1]} == {
        "poi_search",
        "weather_query",
        "budget_calculator",
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
    assert result["output"]["called_tools"][0]["tool_name"] == "budget_calculator"
    assert result["output"]["called_tools"][0]["status"] == "completed"


def test_runner_appends_no_date_weather_reminder_from_gold_policy(tmp_path: Path) -> None:
    async def fake_handler(case):
        return {
            "task_type": "trip_planning",
            "planned_agents": ["attraction", "itinerary", "budget"],
            "used_agents": ["attraction", "itinerary", "budget"],
            "planned_tools": ["poi_search", "budget_calculator"],
            "called_tools": [
                {"tool_name": "poi_search", "status": "completed", "success": True},
                {"tool_name": "budget_calculator", "status": "completed", "success": True},
            ],
            "tool_results": {},
            "attractions": [{"poi_id": "poi_a", "name": "POI A"}],
            "trip_days": 1,
            "daily_itinerary": [{"day": 1, "attractions": [{"poi_id": "poi_a", "name": "POI A"}]}],
            "budget": {"total": 1000},
            "weather": None,
            "weather_adjustments": [],
            "execution_status": "completed",
            "final_answer": "已安排一版无日期行程，包含 POI A，预算总计 1000 元。",
        }

    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        method_handlers={"adaptive_multi_agent": fake_handler},
    )
    result = runner.run(
        {
            "case_id": "no-date-reminder-runner-policy",
            "user_input": "桂林玩1天，预算1000元，帮我安排一下。",
            "expected": {
                "task_type": "trip_planning",
                "weather_date_policy": "no_date_no_specific_weather_for_trip_plan",
                "no_date_weather_reminder_required": True,
            },
        },
        method="adaptive_multi_agent",
    )

    assert NO_DATE_WEATHER_REMINDER in result["output"]["final_answer"]
    assert NO_DATE_WEATHER_REMINDER in result["output"]["raw_output"]["final_answer"]
    assert result["output"]["metadata"]["no_date_weather_output_policy"]["applied"] is True


def test_single_agent_deterministic_experiment_answer_skips_final_llm_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER", "true")

    class FakeLLM:
        def __init__(self):
            self.calls = []

        async def chat(self, messages, tools=None):
            self.calls.append((list(messages), list(tools or [])))
            if len(self.calls) > 1:
                raise AssertionError("deterministic experiment answer should skip final LLM")
            return SimpleNamespace(
                content="",
                tool_calls=[
                    ToolCall(
                        id="budget-1",
                        name="budget_calculator",
                        arguments=json.dumps(
                            {
                                "destination": "Hangzhou",
                                "duration": 2,
                                "num_travelers": 2,
                                "budget_level": "medium",
                            }
                        ),
                    )
                ],
                usage={"total_tokens": 10},
            )

    fake_llm = FakeLLM()
    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        llm_factory=lambda: fake_llm,
    )

    result = runner.run(
        {
            "case_id": "single-deterministic-final",
            "user_input": "帮我估算杭州两天两人的旅游预算。",
            "expected": {
                "task_type": "budget_query",
                "required_tools": ["budget_calculator"],
            },
        },
        method="single_agent",
    )

    assert len(fake_llm.calls) == 1
    assert result["output"]["execution_status"] == "completed"
    assert result["output"]["budget"]
    assert result["output"]["final_answer"]
    assert result["output"]["metadata"]["single_agent_final_answer_mode"] == (
        "deterministic_after_tool_evidence"
    )
    assert result["trace"]["executed_tools"] == ["budget_calculator"]


def test_budget_amount_does_not_imply_luxury_spending_level(tmp_path: Path) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")

    assert runner._case_budget_level({"slots": {"budget_amount": 6600}}) == "medium"
    assert (
        runner._case_budget_level(
            {"slots": {"budget_amount": 6600, "budget_level": "luxury"}}
        )
        == "luxury"
    )


def test_budget_tool_arguments_forward_natural_language_budget_slots(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    case = {
        "case_id": "budget-policy-slot-forwarding",
        "user_input": "two people per-person budget 3000, Guangzhou to Guilin, local budget only",
        "slots": {
            "origin": "guangzhou",
            "destination": "guilin",
            "duration_days": 3,
            "people_count": 2,
            "budget_amount": 6000,
            "budget_basis": "per_person",
            "requested_budget_scope": "destination_local_only",
            "intercity_transport_included": False,
            "hotel_level": "comfort",
            "food_level": "economy",
        },
    }

    args = runner._research_tool_arguments(
        "budget_calculator",
        case,
        tool_results={},
        agent_outputs={},
    )

    assert args["budget_limit"] == 6000.0
    assert args["budget_basis"] == "per_person"
    assert args["requested_budget_scope"] == "destination_local_only"
    assert args["intercity_transport_included"] is False
    assert args["mandatory_budget_disclaimer"] is False
    assert args["origin"] == "guangzhou"
    assert args["hotel_level"] == "comfort"
    assert args["food_level"] == "economy"


def test_budget_tool_arguments_without_origin_use_local_scope_with_disclaimer(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    case = {
        "case_id": "budget-no-origin-local-disclaimer",
        "user_input": "Guilin 3 days for 2 people, is budget 7130 enough?",
        "slots": {
            "destination": "guilin",
            "duration_days": 3,
            "people_count": 2,
            "budget_amount": 7130,
            "budget_basis": "total",
        },
    }

    args = runner._research_tool_arguments(
        "budget_calculator",
        case,
        tool_results={},
        agent_outputs={},
    )

    assert args["origin"] == ""
    assert args["budget_limit"] == 7130.0
    assert args["budget_basis"] == "total"
    assert args["requested_budget_scope"] == "destination_local_only"
    assert args["intercity_transport_included"] is False
    assert args["mandatory_budget_disclaimer"] is True


def test_previous_budget_can_be_carried_without_budget_reexecution(tmp_path: Path) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    previous_state = {
        "output": {
            "budget": {
                "city": "beijing",
                "people_count": 2,
                "days": 2,
                "total": 3120.0,
            }
        }
    }

    assert runner._previous_budget_from_state(previous_state) == {
        "city": "beijing",
        "people_count": 2,
        "days": 2,
        "total": 3120.0,
    }


def test_weather_adjustment_carries_previous_attractions_without_poi_reexecution(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    case = {
        "case_id": "weather-carry-attractions",
        "expected": {"task_type": "weather_adjustment"},
        "previous_state": {
            "output": {
                "attractions": [
                    {"poi_id": "sz001", "name": "Indoor Museum"},
                    {"poi_id": "sz002", "name": "Covered Mall"},
                ]
            }
        },
    }

    attractions = runner._attractions_for_research_output(
        case=case,
        tool_results={},
        agent_outputs={},
        weather={},
    )

    assert [item["poi_id"] for item in attractions] == ["sz001", "sz002"]


def test_reused_itinerary_carries_previous_daily_plan_without_agent_output(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    previous_state = {
        "output": {
            "daily_itinerary": [
                {"day": 1, "attractions": [{"poi_id": "sz001"}]},
                {"day": 2, "attractions": [{"poi_id": "sz002"}]},
            ]
        }
    }

    daily = runner._daily_itinerary_for_research_output(
        case={"case_id": "reused-daily", "expected": {"task_type": "weather_adjustment"}},
        trip_days=2,
        attractions=[{"poi_id": "sz001"}, {"poi_id": "sz002"}],
        weather={"scenario_type": "high_temperature"},
        planned_agents=["weather", "itinerary"],
        reused_agents=["itinerary"],
        agent_outputs={},
        previous_state=previous_state,
    )

    assert daily == previous_state["output"]["daily_itinerary"]


def test_planned_itinerary_keeps_agent_daily_plan_without_weather(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    attractions = [
        {
            "poi_id": "bj001",
            "name": "Forbidden City",
            "category": "heritage",
            "indoor_outdoor": "outdoor",
        },
        {
            "poi_id": "bj002",
            "name": "National Museum",
            "category": "museum",
            "indoor_outdoor": "indoor",
        },
    ]
    agent_outputs = {
        "itinerary": {
            "status": "completed",
            "success": True,
            "decision_validation_status": "passed",
            "decision": {
                "decisions": {
                    "daily_itinerary": [
                        {"day": 1, "attraction_poi_ids": ["bj001"]},
                        {"day": 2, "attraction_poi_ids": ["bj002"]},
                    ]
                }
            },
        }
    }

    daily = runner._daily_itinerary_for_research_output(
        case={"case_id": "no-date-trip", "expected": {"task_type": "trip_planning"}},
        trip_days=2,
        attractions=attractions,
        weather={},
        planned_agents=["attraction", "itinerary", "budget"],
        reused_agents=[],
        agent_outputs=agent_outputs,
        previous_state=None,
    )

    assert [[item["poi_id"] for item in day["attractions"]] for day in daily] == [
        ["bj001"],
        ["bj002"],
    ]



def test_weather_evidence_summary_explains_missing_dates_and_snapshot_range(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    weather = {
        "provider": "qweather_snapshot",
        "coverage_status": "out_of_range",
        "scenario_type": "out_of_range",
        "start_date": "2026-10-01",
        "end_date": "2026-10-03",
        "requested_days": 3,
        "coverage_days": 0,
        "missing_dates": ["2026-10-01", "2026-10-02", "2026-10-03"],
        "snapshot_forecast_start_date": "2026-08-07",
        "snapshot_forecast_end_date": "2026-09-05",
        "daily_weather": [],
    }

    answer = runner._answer_with_research_evidence_summary(
        "",
        attractions=[],
        budget={},
        weather=weather,
    )

    assert "out_of_range" in answer
    assert "2026-10-01" in answer
    assert "2026-10-02" in answer
    assert "2026-10-03" in answer
    assert "2026-08-07" in answer
    assert "2026-09-05" in answer
    assert "不能提供逐日天气" in answer
    assert "不编造" in answer

def test_weather_adjustment_falls_back_to_previous_daily_plan_when_itinerary_missing(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    previous_state = {
        "output": {
            "daily_itinerary": [
                {"day": 1, "attractions": [{"poi_id": "sz001"}]},
                {"day": 2, "attractions": [{"poi_id": "sz002"}]},
            ]
        }
    }
    case = {
        "case_id": "weather-carry-daily",
        "expected": {"task_type": "weather_adjustment"},
    }

    daily = runner._daily_itinerary_for_research_output(
        case=case,
        trip_days=2,
        attractions=[{"poi_id": "sz001"}, {"poi_id": "sz002"}],
        weather={"scenario_type": "high_temperature"},
        planned_agents=["weather", "itinerary"],
        reused_agents=[],
        agent_outputs={},
        previous_state=previous_state,
    )

    assert daily == previous_state["output"]["daily_itinerary"]


def test_blocked_itinerary_skip_is_allowed_only_for_weather_adjustment_with_previous_plan(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    previous_state = {
        "output": {
            "daily_itinerary": [{"day": 1, "attractions": [{"poi_id": "sz001"}]}]
        }
    }

    assert runner._can_skip_blocked_itinerary_with_previous_state(
        agent_name="itinerary",
        case={"expected": {"task_type": "weather_adjustment"}},
        previous_state=previous_state,
    )
    assert not runner._can_skip_blocked_itinerary_with_previous_state(
        agent_name="itinerary",
        case={"expected": {"task_type": "trip_planning"}},
        previous_state=previous_state,
    )
    assert not runner._can_skip_blocked_itinerary_with_previous_state(
        agent_name="budget",
        case={"expected": {"task_type": "weather_adjustment"}},
        previous_state=previous_state,
    )


def test_normalized_itinerary_prefers_weather_safe_pois_without_duplicates(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    attractions = [
        {"poi_id": "bj001", "name": "A", "indoor_outdoor": "outdoor"},
        {"poi_id": "bj002", "name": "B", "indoor_outdoor": "outdoor"},
        {"poi_id": "bj003", "name": "C", "indoor_outdoor": "mixed"},
        {"poi_id": "bj004", "name": "D", "indoor_outdoor": "indoor"},
    ]

    daily = runner._normalized_decision_daily_itinerary(
        2,
        attractions,
        case={"case_id": "weather-risk", "slots": {"duration_days": 2}},
        weather={"scenario_type": "high_temperature"},
    )
    refs = [
        poi_id
        for item in daily
        for poi_id in item.get("attraction_poi_ids", [])
    ]

    assert refs[0] == "bj004"
    assert len(refs) == len(set(refs))


def test_itinerary_agent_validation_allows_empty_rest_days_after_unique_pois(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    tool_results = {
        "poi_search": {
            "data": {
                "attractions": [
                    {"poi_id": "p1", "name": "A"},
                    {"poi_id": "p2", "name": "B"},
                ]
            }
        }
    }
    decision = {
        "daily_itinerary": [
            {"day": 1, "attraction_poi_ids": ["p1"]},
            {"day": 2, "attraction_poi_ids": ["p2"]},
            {"day": 3, "attraction_poi_ids": []},
        ]
    }

    assert (
        runner._validate_itinerary_agent_decision(
            decision,
            {"slots": {"duration_days": 3}},
            tool_results,
        )
        == []
    )


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


def test_runner_loads_case_file_that_contains_dataset_document(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases_doc.json"
    cases_path.write_text(
        json.dumps(
            {
                "schema_version": "ctp-benchmark-v1",
                "cases": [
                    {"case_id": "doc_case_001", "user_input": "Plan a Hangzhou trip."},
                    {"case_id": "doc_case_002", "user_input": "Check Beijing weather."},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(
        json.dumps({"case_files": [cases_path.name]}, ensure_ascii=False),
        encoding="utf-8",
    )

    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    cases = runner.load_benchmark(benchmark_path)

    assert [case["case_id"] for case in cases] == ["doc_case_001", "doc_case_002"]


def test_offline_acceptance_runs_two_cases_four_methods_and_two_repeats(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def offline_handler(case):
        trace = get_current_trace()
        assert trace is not None
        trace.mark_first_body_token()
        return {"case_id": case["case_id"], "source": "offline-static"}

    benchmark_path = tmp_path / "phase1_offline.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "dataset_id": "phase1_offline_acceptance",
                "dataset_version": "2026-07-14",
                "cases": [
                    {"case_id": "offline_001", "user_input": "杭州三日游"},
                    {"case_id": "offline_002", "user_input": "成都四日游"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EXPERIMENT_STRICT_MODE", "true")
    monkeypatch.setenv("EXPERIMENT_DISABLE_CACHE", "true")
    monkeypatch.setenv("LLM_MODEL", "offline-static-model")
    monkeypatch.setenv("LLM_TEMPERATURE", "0")
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
    monkeypatch.setenv("LLM_TIMEOUT", "60")
    monkeypatch.setenv("LLM_RETRY_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "minimal")

    trace_dir = tmp_path / "traces"
    output_dir = tmp_path / "results"
    runner = ExperimentRunner(
        trace_dir=trace_dir,
        output_dir=output_dir,
        method_handlers={method: offline_handler for method in ExperimentRunner.METHODS},
        repeats=2,
        run_id="phase1-offline-run",
        model_config_name="offline-static",
    )

    results = runner.run_benchmark(benchmark_path)

    assert len(results) == 16
    assert {result["repeat_index"] for result in results} == {0, 1}
    assert {result["method"] for result in results} == set(ExperimentRunner.METHODS)
    assert {result["system_variant"] for result in results} == set(ExperimentRunner.METHODS)
    assert {result["run_id"] for result in results} == {"phase1-offline-run"}
    assert len({result["request_id"] for result in results}) == 16

    trace_records = [
        json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        for path in trace_dir.glob("*.jsonl")
    ]
    assert len(trace_records) == 16
    for trace in trace_records:
        assert trace["case_id"] in {"offline_001", "offline_002"}
        assert trace["experiment_case_id"] == trace["case_id"]
        assert trace["method"] in ExperimentRunner.METHODS
        assert trace["repeat_index"] in {0, 1}
        assert trace["system_variant"] == trace["method"]
        assert trace["run_id"] == "phase1-offline-run"
        assert trace["model_config_name"] == "offline-static"

    run_output_dir = output_dir / "phase1-offline-run"
    manifest = json.loads((run_output_dir / "experiment_manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset_version"] == "2026-07-14"
    assert manifest["dataset"]["id"] == "phase1_offline_acceptance"
    assert manifest["dataset_path"] == benchmark_path.as_posix()
    assert manifest["dataset"]["path"] == benchmark_path.as_posix()
    assert manifest["results"] == {
        "csv": (run_output_dir / "benchmark_results.csv").as_posix(),
        "json": (run_output_dir / "benchmark_results.json").as_posix(),
        "summary": (run_output_dir / "evaluation_summary.json").as_posix(),
        "paper_tables": (run_output_dir / "paper_tables.md").as_posix(),
        "resume_state": (run_output_dir / "benchmark_resume_state.json").as_posix(),
        "checkpoint_csv": (run_output_dir / "benchmark_results.checkpoint.csv").as_posix(),
        "checkpoint_json": (run_output_dir / "benchmark_results.checkpoint.json").as_posix(),
    }
    assert all(
        "\\" not in path
        for path in (
            manifest["dataset_path"],
            manifest["dataset"]["path"],
            *manifest["results"].values(),
        )
    )
    assert len(manifest["dataset_sha256"]) == 64
    assert len(manifest["git_commit"]) == 40
    assert manifest["git"]["commit"] == manifest["git_commit"]
    assert manifest["git"]["working_tree_clean"] == manifest["working_tree_clean"]
    assert manifest["git"]["status_short"] == manifest["git_status_short"]
    assert isinstance(manifest["working_tree_clean"], bool)
    assert isinstance(manifest["git_status_short"], list)
    assert manifest["model"] == "offline-static-model"
    assert manifest["temperature"] == 0.0
    assert manifest["max_tokens"] == 4096
    assert manifest["timeout_seconds"] == 60
    assert manifest["retry_max_attempts"] == 3
    assert manifest["reasoning_effort"] == "minimal"
    assert manifest["deterministic_research_final_answer"] is False
    assert manifest["runtime_config"]["schema_version"] == "ctp-experiment-runtime-config-v1"
    assert manifest["runtime_config"]["temperature"] == 0.0
    assert manifest["runtime_config"]["max_tokens"] == 4096
    assert manifest["runtime_config"]["timeout_seconds"] == 60
    assert manifest["runtime_config"]["retry_max_attempts"] == 3
    assert manifest["runtime_config"]["reasoning_effort"] == "minimal"
    assert manifest["runtime_config"]["deterministic_research_final_answer"] is False
    assert (
        manifest["runtime_config"]["final_answer_generation_mode"]
        == "llm_final_answer_generation"
    )
    assert manifest["cache_enabled"] is False
    assert manifest["strict_mode"] is True
    assert manifest["repeats"] == 2
    assert manifest["model_config_name"] == "offline-static"
    assert manifest["method_order_seed"] == runner.method_order_seed
    assert manifest["resume"]["state_saved"] is True
    assert manifest["resume"]["status"] == "completed"
    assert manifest["resume"]["progress"]["remaining_result_count"] == 0
    assert manifest["prompt_versions"]["structured_llm_output"] == "ctp-structured-llm-output-prompts-v1"
    assert manifest["prompt_versions"]["research_agent"] == "ctp-research-agent-prompts-v1"
    assert manifest["method_controls"]["deterministic_research_final_answer"] is False
    assert manifest["costing"]["schema_version"] == "ctp-llm-costing-v1"
    assert manifest["costing"]["price_snapshot"]["pricing_mode"] == "mock_zero_cost"
    assert manifest["costing"]["input_token_unit_price"] == 0.0
    assert manifest["costing"]["output_token_unit_price"] == 0.0
    assert manifest["offline_data"]["snapshot"]["hash_strategy"] == CANONICAL_JSON_SHA256_STRATEGY
    assert manifest["offline_data"]["snapshot"]["combined_sha256"] == FIXED_DATA_EXPECTED_COMBINED_SHA256
    qweather_manifest = load_qweather_snapshot_manifest()
    assert manifest["offline_data"]["qweather_snapshot"]["snapshot_id"] == qweather_manifest["snapshot_id"]
    assert (
        manifest["offline_data"]["qweather_snapshot"]["combined_sha256"]
        == qweather_manifest["combined_sha256"]
    )
    assert manifest["offline_data"]["qweather_snapshot"]["real_time_api_allowed"] is False
    intercity_manifest = load_intercity_transport_snapshot_manifest()
    assert (
        manifest["offline_data"]["intercity_transport_snapshot"]["snapshot_id"]
        == intercity_manifest["snapshot_id"]
    )
    assert (
        manifest["offline_data"]["intercity_transport_snapshot"]["combined_sha256"]
        == intercity_manifest["combined_sha256"]
    )
    assert (
        manifest["offline_data"]["intercity_transport_snapshot"]["fare_snapshot_date"]
        == intercity_manifest["fare_snapshot_date"]
    )
    assert manifest["offline_data"]["intercity_transport_snapshot"]["route_count"] == 50
    assert manifest["offline_data"]["intercity_transport_snapshot"]["real_time_api_allowed"] is False
    assert (
        manifest["offline_data"]["intercity_transport_snapshot"]["runtime_online_refresh_allowed"]
        is False
    )
    assert (
        manifest["offline_data"]["intercity_transport_snapshot"]["real_time_price_claim_allowed"]
        is False
    )
    assert manifest["evaluation"]["schema_version"] == EVALUATION_SCHEMA_VERSION
    assert manifest["evaluation"]["summary_schema_version"] == EVALUATION_SUMMARY_SCHEMA_VERSION
    assert manifest["evaluation"]["catalog_id"] == "day8_formal_independent_evaluator_rules"
    assert manifest["evaluation"]["catalog_hash_strategy"] == CANONICAL_JSON_SHA256_STRATEGY
    assert len(manifest["evaluation"]["catalog_sha256"]) == 64
    assert "\\" not in manifest["evaluation"]["catalog_path"]
    summary = json.loads((run_output_dir / "evaluation_summary.json").read_text(encoding="utf-8"))
    assert summary["schema_version"] == EVALUATION_SUMMARY_SCHEMA_VERSION
    assert set(summary["methods"]) == set(ExperimentRunner.METHODS)
    assert summary["paired_m3_vs_m2"]["pair_count"] == 2
    assert summary["methods"]["adaptive_multi_agent"]["raw_run_count"] == 4
    paper_tables = (run_output_dir / "paper_tables.md").read_text(encoding="utf-8")
    assert "Method-level results" in paper_tables
    assert "Paired M3 vs M2 statistics" in paper_tables
    csv_rows = list(csv.DictReader((run_output_dir / "benchmark_results.csv").open(encoding="utf-8-sig")))
    assert len(csv_rows) == 16
    assert "standardized_estimated_cost" in csv_rows[0]
    assert "actual_cost" in csv_rows[0]
    assert "audit_standardized_estimated_cost" in csv_rows[0]
    assert "audit_actual_cost" in csv_rows[0]


def test_benchmark_resume_skips_completed_checkpoint_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class IntentionalInterrupt(BaseException):
        pass

    _formal_env_for_runner_resume(monkeypatch)
    first_call_count = {"count": 0}

    async def interrupting_handler(case: dict) -> dict:
        first_call_count["count"] += 1
        if first_call_count["count"] > 20:
            raise IntentionalInterrupt("stop after twenty completed results")
        trace = get_current_trace()
        assert trace is not None
        trace.mark_first_body_token()
        return {
            "task_type": "general_chat",
            "planned_agents": [],
            "used_agents": [],
            "planned_tools": [],
            "called_tools": [],
            "tool_results": {},
            "attractions": [],
            "daily_itinerary": [],
            "budget": None,
            "weather": None,
            "weather_adjustments": [],
            "execution_status": "completed",
            "final_answer": f"done {case['case_id']}",
        }

    benchmark_path = tmp_path / "resume_benchmark.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "dataset_id": "resume-dev",
                "dataset_version": "v1",
                "cases": [
                    {"case_id": f"resume_{index:03d}", "user_input": "你好"}
                    for index in range(1, 7)
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "results"
    first_runner = ExperimentRunner(
        trace_dir=tmp_path / "traces_first",
        output_dir=output_dir,
        method_handlers={method: interrupting_handler for method in ExperimentRunner.METHODS},
        run_id="resume-run",
        model_config_name="offline-static",
    )

    with pytest.raises(IntentionalInterrupt):
        first_runner.run_benchmark(benchmark_path)

    run_output_dir = output_dir / "resume-run"
    checkpoint_path = run_output_dir / BENCHMARK_CHECKPOINT_JSON_NAME
    resume_state_path = run_output_dir / BENCHMARK_RESUME_STATE_NAME
    checkpoint_results = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    first_state = json.loads(resume_state_path.read_text(encoding="utf-8"))
    assert len(checkpoint_results) == 20
    assert first_state["status"] == "running"
    assert first_state["progress"]["completed_result_count"] == 20
    assert first_state["policy"]["failed_results_are_preserved"] is True

    resumed_call_count = {"count": 0}

    async def resuming_handler(case: dict) -> dict:
        resumed_call_count["count"] += 1
        trace = get_current_trace()
        assert trace is not None
        trace.mark_first_body_token()
        return {
            "task_type": "general_chat",
            "planned_agents": [],
            "used_agents": [],
            "planned_tools": [],
            "called_tools": [],
            "tool_results": {},
            "attractions": [],
            "daily_itinerary": [],
            "budget": None,
            "weather": None,
            "weather_adjustments": [],
            "execution_status": "completed",
            "final_answer": f"resumed {case['case_id']}",
        }

    resumed_runner = ExperimentRunner(
        trace_dir=tmp_path / "traces_resumed",
        output_dir=output_dir,
        method_handlers={method: resuming_handler for method in ExperimentRunner.METHODS},
        run_id="resume-run",
        model_config_name="offline-static",
    )
    results = resumed_runner.run_benchmark(benchmark_path, resume=True)

    keys = {
        (
            result["case_id"],
            result.get("turn_id") or "",
            result["method"],
            result["repeat_index"],
        )
        for result in results
    }
    final_state = json.loads(resume_state_path.read_text(encoding="utf-8"))
    manifest = json.loads((run_output_dir / "experiment_manifest.json").read_text(encoding="utf-8"))
    assert len(results) == 24
    assert len(keys) == 24
    assert resumed_call_count["count"] == 4
    assert final_state["status"] == "completed"
    assert final_state["progress"]["remaining_result_count"] == 0
    assert final_state["resume_enabled_for_this_invocation"] is True
    assert final_state["resume_events"][-1]["loaded_result_count"] == 20
    assert manifest["resume"]["state_saved"] is True
    assert manifest["resume"]["status"] == "completed"
    assert manifest["resume"]["progress"]["completed_unique_key_count"] == 24
    assert manifest["results"]["resume_state"] == resume_state_path.as_posix()


def test_scenario_resume_restores_previous_turn_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class IntentionalInterrupt(BaseException):
        pass

    _formal_env_for_runner_resume(monkeypatch)
    seen_after_resume: list[dict[str, object]] = []

    async def interrupting_handler(case: dict) -> dict:
        if case.get("turn_id") == "t2":
            raise IntentionalInterrupt("stop at second turn")
        trace = get_current_trace()
        assert trace is not None
        trace.mark_first_body_token()
        return {
            "task_type": "general_chat",
            "planned_agents": [],
            "used_agents": [],
            "planned_tools": [],
            "called_tools": [],
            "tool_results": {},
            "attractions": [],
            "daily_itinerary": [],
            "budget": None,
            "weather": None,
            "weather_adjustments": [],
            "execution_status": "completed",
            "final_answer": "first turn complete",
        }

    async def resuming_handler(case: dict) -> dict:
        previous_state = case.get("previous_state")
        seen_after_resume.append(
            {
                "turn_id": case.get("turn_id"),
                "previous_turn_id": (
                    previous_state.get("turn_id")
                    if isinstance(previous_state, dict)
                    else None
                ),
                "previous_method": (
                    previous_state.get("method")
                    if isinstance(previous_state, dict)
                    else None
                ),
            }
        )
        trace = get_current_trace()
        assert trace is not None
        trace.mark_first_body_token()
        return {
            "task_type": "general_chat",
            "planned_agents": [],
            "used_agents": [],
            "planned_tools": [],
            "called_tools": [],
            "tool_results": {},
            "attractions": [],
            "daily_itinerary": [],
            "budget": None,
            "weather": None,
            "weather_adjustments": [],
            "execution_status": "completed",
            "final_answer": "second turn resumed",
        }

    benchmark_path = tmp_path / "scenario_resume.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "dataset_id": "scenario-resume-dev",
                "cases": [
                    {
                        "case_id": "scenario_resume_001",
                        "turns": [
                            {"turn_id": "t1", "user_input": "你好"},
                            {"turn_id": "t2", "user_input": "继续刚才的问题"},
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "results"
    first_runner = ExperimentRunner(
        trace_dir=tmp_path / "traces_first",
        output_dir=output_dir,
        method_handlers={"adaptive_multi_agent": interrupting_handler},
        run_id="scenario-resume-run",
        model_config_name="offline-static",
    )
    with pytest.raises(IntentionalInterrupt):
        first_runner.run_benchmark(benchmark_path, methods=["adaptive_multi_agent"])

    checkpoint_path = output_dir / "scenario-resume-run" / BENCHMARK_CHECKPOINT_JSON_NAME
    assert len(json.loads(checkpoint_path.read_text(encoding="utf-8"))) == 1

    resumed_runner = ExperimentRunner(
        trace_dir=tmp_path / "traces_resumed",
        output_dir=output_dir,
        method_handlers={"adaptive_multi_agent": resuming_handler},
        run_id="scenario-resume-run",
        model_config_name="offline-static",
    )
    results = resumed_runner.run_benchmark(
        benchmark_path,
        methods=["adaptive_multi_agent"],
        resume=True,
    )

    assert len(results) == 2
    assert seen_after_resume == [
        {
            "turn_id": "t2",
            "previous_turn_id": "t1",
            "previous_method": "adaptive_multi_agent",
        }
    ]


def test_phase1_offline_acceptance_script_checks_sixteen_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from experiments import run_phase1_offline_acceptance as acceptance

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_phase1_offline_acceptance.py",
            "--output-dir",
            str(tmp_path / "phase1_acceptance"),
        ],
    )

    assert acceptance.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["result_count"] == 16
    assert payload["expected_count"] == 16
    assert Path(payload["output_dir"]).name == payload["run_id"]
    assert Path(payload["manifest"]).parent == Path(payload["output_dir"])


def _formal_env_for_runner_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPERIMENT_STRICT_MODE", "true")
    monkeypatch.setenv("EXPERIMENT_DISABLE_CACHE", "true")
    monkeypatch.setenv("TRACE_SAVE_USER_MESSAGE", "false")
    monkeypatch.setenv("LLM_MODEL", "offline-static-model")
    monkeypatch.setenv("LLM_TEMPERATURE", "0")
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
    monkeypatch.setenv("LLM_TIMEOUT", "60")
    monkeypatch.setenv("LLM_RETRY_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "minimal")
    monkeypatch.setenv("EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER", "true")


def test_real_runner_passes_successful_tool_results_to_constraint_checker(
    tmp_path: Path,
) -> None:
    fake_llm = _CountingResearchLLM()
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=lambda: fake_llm)
    result = runner.run(
        {
            "case_id": "runner-tool-evidence-success",
            "user_input": "Plan a two-day Hangzhou trip on 2026-08-01 for two people with budget 10000",
            "slots": {
                "destination": "hangzhou",
                "duration": 2,
                "num_travelers": 2,
                "budget": 10000,
                "start_date": "2026-08-01",
            },
        },
        method="fixed_multi_agent",
    )

    checks = {
        item["name"]: item
        for item in result["constraint_report"]["data"]["checks"]
    }

    assert result["raw_output"]["tool_results"].keys() >= set(GENERATION_TOOL_NAMES)
    assert checks["tool_evidence"]["status"] == "passed"
    assert checks["tool_evidence"]["details"]["required_tools"] == list(GENERATION_TOOL_NAMES)
    assert checks["tool_evidence"]["details"]["missing_or_failed"] == []


class _CountingResearchLLM:
    def __init__(self) -> None:
        self.calls = []

    async def chat(self, messages, tools=None):
        agent_name = "final"
        try:
            payload = json.loads(messages[-1].content)
        except (json.JSONDecodeError, TypeError, AttributeError):
            payload = {}
        if isinstance(payload, dict) and payload.get("agent_name"):
            agent_name = str(payload["agent_name"])
        self.calls.append(
            {
                "agent_name": agent_name,
                "messages": list(messages),
                "tools": list(tools or []),
            }
        )
        prompt_tokens = {
            "attraction": 11,
            "weather": 13,
            "itinerary": 17,
            "budget": 19,
            "final": 23,
        }[agent_name]
        completion_tokens = 3
        content = (
            self._agent_decision_content(agent_name, payload)
            if agent_name != "final"
            else "final llm output"
        )
        return SimpleNamespace(
            content=content,
            tool_calls=[],
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        )

    def _agent_decision_content(self, agent_name: str, payload: dict) -> str:
        tool_evidence = payload.get("tool_evidence") if isinstance(payload, dict) else {}
        tool_evidence = tool_evidence if isinstance(tool_evidence, dict) else {}
        attractions = self._attractions(tool_evidence)
        selected_ids = [item["poi_id"] for item in attractions[:4] if item.get("poi_id")]
        days = int((payload.get("task_slots") or {}).get("duration_days") or 2)

        if agent_name == "attraction":
            decisions = {"selected_poi_ids": selected_ids, "ranking_reason": "test order"}
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
            budget = self._tool_data(tool_evidence.get("budget_calculator"))
            decisions = {
                "feasibility": "feasible",
                "budget_notes": "test budget decision",
                "recommended_total": budget.get("total"),
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


def test_m2_runs_four_business_agent_llm_steps_and_records_agent_tokens(
    tmp_path: Path,
) -> None:
    snapshot_start = _qweather_snapshot_start_date()
    fake_llm = _CountingResearchLLM()
    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        llm_factory=lambda: fake_llm,
    )

    result = runner.run(
        {
            "case_id": "m2-agent-llm",
            "user_input": f"Plan a two-day Hangzhou trip on {snapshot_start} for two people.",
            "slots": {
                "destination": "hangzhou",
                "duration": 2,
                "people_count": 2,
                "start_date": snapshot_start,
            },
        },
        method="fixed_multi_agent",
    )

    assert [call["agent_name"] for call in fake_llm.calls] == [
        "attraction",
        "weather",
        "itinerary",
        "budget",
        "final",
    ]
    assert all(not call["tools"] for call in fake_llm.calls)

    agent_outputs = result["output"]["agent_outputs"]
    assert set(agent_outputs) == {"attraction", "weather", "itinerary", "budget"}
    for agent_name, output in agent_outputs.items():
        assert output["schema_version"] == RESEARCH_AGENT_OUTPUT_SCHEMA_VERSION
        assert output["agent_name"] == agent_name
        assert output["status"] == "completed"
        assert output["reused"] is False
        assert output["llm_call_count"] == 1
        assert output["total_tokens"] is not None
        assert output["decision_schema_version"] == RESEARCH_AGENT_DECISION_SCHEMA_VERSION
        assert output["decision_parse_status"] == "passed"
        assert output["decision_validation_status"] == "passed"
        assert output["decision_errors"] == []

    assert result["output"]["attractions"][0]["agent_decision_source"] == "attraction"
    assert result["output"]["attractions"][0]["agent_selected"] is True
    assert result["output"]["daily_itinerary"]
    itinerary_normalization = result["output"]["metadata"].get(
        "itinerary_evidence_normalization"
    )
    assert itinerary_normalization["applied"] is True
    assert "weather_risk_day_poi_reordered" in itinerary_normalization["reasons"]
    assert any(
        day["agent_decision_source"] == "evidence_constraint_normalizer"
        for day in result["output"]["daily_itinerary"]
    )
    assert result["output"]["weather"]["agent_weather_decision"]["source"] == "weather"
    assert result["output"]["budget"]["agent_budget_decision"]["feasibility"] == "feasible"
    assert result["output"]["metadata"]["agent_decision_schema_version"] == (
        RESEARCH_AGENT_DECISION_SCHEMA_VERSION
    )
    assert result["output"]["metadata"]["agent_decision_audit"]["itinerary"] == {
        "status": "completed",
        "reused": False,
        "decision_source": "llm",
        "decision_fallback_used": False,
        "decision_normalizer_enabled": True,
        "decision_normalizer_skipped": False,
        "decision_parse_status": "passed",
        "decision_validation_status": "passed",
        "llm_decision_error_count": 0,
        "decision_error_count": 0,
        "has_applicable_decision": True,
    }

    agent_runs = result["trace"]["agent_runs"]
    assert [run["agent_name"] for run in agent_runs] == [
        "attraction",
        "weather",
        "itinerary",
        "budget",
    ]
    assert all(run["llm_call_count"] == 1 for run in agent_runs)
    assert [run["prompt_tokens"] for run in agent_runs] == [11, 13, 17, 19]
    assert [run["completion_tokens"] for run in agent_runs] == [3, 3, 3, 3]
    assert result["metrics"]["agent_llm_call_count"] == 4
    assert result["metrics"]["agent_prompt_tokens"] == 60.0
    assert result["metrics"]["agent_completion_tokens"] == 12.0
    assert result["metrics"]["agent_total_tokens"] == 72.0


def test_research_final_answer_can_use_deterministic_evidence_renderer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_llm = _CountingResearchLLM()
    monkeypatch.setenv("EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER", "true")
    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        llm_factory=lambda: fake_llm,
    )

    result = runner.run(
        {
            "case_id": "m2-deterministic-final-answer",
            "user_input": "Plan a two-day Hangzhou trip on 2026-08-01 for two people.",
            "slots": {
                "destination": "hangzhou",
                "duration": 2,
                "people_count": 2,
                "start_date": "2026-08-01",
            },
        },
        method="fixed_multi_agent",
    )

    assert [call["agent_name"] for call in fake_llm.calls] == [
        "attraction",
        "weather",
        "itinerary",
        "budget",
    ]
    assert result["output"]["execution_status"] == "completed"
    assert "final" not in [call["agent_name"] for call in fake_llm.calls]
    assert result["output"]["final_answer"]


def test_deterministic_research_final_answer_handles_general_chat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_llm = _CountingResearchLLM()
    monkeypatch.setenv("EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER", "true")
    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        llm_factory=lambda: fake_llm,
    )

    result = runner.run(
        {
            "case_id": "m3-general-chat-deterministic-answer",
            "user_input": "晚安。",
            "expected": {
                "task_type": "general_chat",
                "forbidden_tools": list(GENERATION_TOOL_NAMES),
                "accepted_agent_sets": [[]],
                "accepted_tool_sets": [[]],
            },
        },
        method="adaptive_multi_agent",
    )

    assert fake_llm.calls == []
    assert result["status"] == "completed"
    assert result["metrics"]["stsr"] is True
    assert result["output"]["final_answer"]
    assert "晚安" in result["output"]["final_answer"]


def test_m3_reuse_skips_reused_agent_llm_step(
    tmp_path: Path,
) -> None:
    fake_llm = _CountingResearchLLM()
    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        llm_factory=lambda: fake_llm,
    )
    first = runner.run(
        {
            "case_id": "m3-agent-llm-turn1",
            "user_input": "Plan a two-day Hangzhou trip on 2026-08-01 for two people.",
            "slots": {
                "destination": "hangzhou",
                "duration": 2,
                "people_count": 2,
                "start_date": "2026-08-01",
            },
        },
        method="adaptive_multi_agent",
    )
    first_call_count = len(fake_llm.calls)

    second = runner.run(
        {
            "case_id": "m3-agent-llm-turn2",
            "user_input": "Change the trip to three days and keep other conditions unchanged.",
            "slots": {"duration": 3},
            "previous_state": first,
        },
        method="adaptive_multi_agent",
    )

    assert [call["agent_name"] for call in fake_llm.calls[:first_call_count]] == [
        "attraction",
        "weather",
        "itinerary",
        "budget",
        "final",
    ]
    assert [call["agent_name"] for call in fake_llm.calls[first_call_count:]] == [
        "weather",
        "itinerary",
        "budget",
        "final",
    ]
    assert "attraction" not in [
        call["agent_name"] for call in fake_llm.calls[first_call_count:]
    ]

    scheduler = second["output"]["metadata"]["adaptive_scheduler"]
    assert scheduler["decision"]["reused_agents"] == ["attraction"]
    assert scheduler["reuse_execution"]["reused_agent_results"] == ["attraction"]

    agent_outputs = second["output"]["agent_outputs"]
    assert agent_outputs["attraction"]["status"] == "reused"
    assert agent_outputs["attraction"]["reused"] is True
    assert agent_outputs["attraction"]["llm_call_count"] == 0
    assert agent_outputs["attraction"]["usage"] == {}
    assert set(agent_outputs) == {"attraction", "weather", "itinerary", "budget"}
    assert [run["agent_name"] for run in second["trace"]["agent_runs"]] == [
        "weather",
        "itinerary",
        "budget",
    ]
    assert second["metrics"]["agent_llm_call_count"] == 3
    assert second["metrics"]["agent_prompt_tokens"] == 49.0
    assert second["metrics"]["agent_completion_tokens"] == 9.0
    assert second["metrics"]["agent_total_tokens"] == 58.0


def test_m3_origin_delta_reuses_trip_artifacts_and_executes_budget_only(
    tmp_path: Path,
) -> None:
    snapshot_start = _qweather_snapshot_start_date()
    fake_llm = _CountingResearchLLM()
    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        llm_factory=lambda: fake_llm,
    )
    first = runner.run(
        {
            "case_id": "m3-origin-turn1",
            "user_input": f"Plan a three-day Guilin trip on {snapshot_start} for two people with a 5000 yuan budget.",
            "slots": {
                "destination": "guilin",
                "duration": 3,
                "people_count": 2,
                "start_date": snapshot_start,
                "budget_amount": 5000,
            },
        },
        method="adaptive_multi_agent",
    )
    first_call_count = len(fake_llm.calls)

    second = runner.run(
        {
            "case_id": "m3-origin-turn2",
            "user_input": "从广州出发",
            "slots": {"origin": "guangzhou"},
            "previous_state": first,
        },
        method="adaptive_multi_agent",
    )

    assert [call["agent_name"] for call in fake_llm.calls[first_call_count:]] == [
        "budget",
        "final",
    ]
    assert second["trace"]["planned_agents"] == ["budget"]
    assert second["trace"]["executed_agents"] == ["budget"]
    assert second["trace"]["planned_tools"] == ["budget_calculator"]
    assert second["trace"]["executed_tools"] == ["budget_calculator"]
    assert [call["tool_name"] for call in second["trace"]["tool_calls"]] == [
        "budget_calculator"
    ]
    assert "poi_search" not in second["trace"]["executed_tools"]
    assert "weather_query" not in second["trace"]["executed_tools"]

    scheduler = second["output"]["metadata"]["adaptive_scheduler"]
    assert scheduler["ticket"]["changed_slots"] == ["origin"]
    assert scheduler["decision"]["decision_reasons"] == ["origin_changed_budget_only"]
    assert scheduler["decision"]["planned_agents"] == ["budget"]
    assert scheduler["decision"]["planned_tools"] == ["budget_calculator"]
    assert scheduler["decision"]["reused_agents"] == [
        "attraction",
        "weather",
        "itinerary",
    ]
    assert scheduler["decision"]["invalidated_agents"] == ["budget"]
    assert scheduler["reuse_execution"]["reused_agent_results"] == [
        "attraction",
        "weather",
        "itinerary",
    ]
    assert scheduler["reuse_execution"]["reused_tool_results"] == [
        "poi_search",
        "weather_query",
    ]

    agent_outputs = second["output"]["agent_outputs"]
    assert agent_outputs["attraction"]["status"] == "reused"
    assert agent_outputs["weather"]["status"] == "reused"
    assert agent_outputs["itinerary"]["status"] == "reused"
    assert agent_outputs["budget"]["status"] == "completed"


def test_m3_weather_adjustment_reuses_weather_and_recomputes_budget(
    tmp_path: Path,
) -> None:
    snapshot_start = _qweather_snapshot_start_date()
    fake_llm = _CountingResearchLLM()
    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        llm_factory=lambda: fake_llm,
    )
    first = runner.run(
        {
            "case_id": "m3-weather-adjust-turn1",
            "user_input": f"Plan a three-day Shenzhen trip on {snapshot_start} for two people with a 6000 yuan budget and outdoor activities.",
            "slots": {
                "destination": "shenzhen",
                "duration": 3,
                "people_count": 2,
                "start_date": snapshot_start,
                "budget_amount": 6000,
                "preferences": ["nature"],
            },
        },
        method="adaptive_multi_agent",
    )
    first_call_count = len(fake_llm.calls)

    second = runner.run(
        {
            "case_id": "m3-weather-adjust-turn2",
            "user_input": "It will be hot; reduce midday outdoor activities and keep the other conditions unchanged.",
            "previous_state": first,
        },
        method="adaptive_multi_agent",
    )

    assert [call["agent_name"] for call in fake_llm.calls[first_call_count:]] == [
        "itinerary",
        "budget",
        "final",
    ]
    assert second["trace"]["planned_agents"] == ["itinerary", "budget"]
    assert second["trace"]["executed_agents"] == ["itinerary", "budget"]
    assert second["trace"]["planned_tools"] == ["budget_calculator"]
    assert second["trace"]["executed_tools"] == ["budget_calculator"]
    assert [call["tool_name"] for call in second["trace"]["tool_calls"]] == [
        "budget_calculator"
    ]
    assert "poi_search" not in second["trace"]["executed_tools"]
    assert "weather_query" not in second["trace"]["executed_tools"]

    scheduler = second["output"]["metadata"]["adaptive_scheduler"]
    assert scheduler["ticket"]["task_type"] == "weather_adjustment"
    assert scheduler["decision"]["decision_reasons"] == [
        "weather_adjustment_reuses_previous_weather"
    ]
    assert scheduler["decision"]["reused_agents"] == ["attraction", "weather"]
    assert scheduler["decision"]["invalidated_agents"] == ["itinerary", "budget"]
    assert scheduler["reuse_execution"]["reused_agent_results"] == [
        "attraction",
        "weather",
    ]
    assert scheduler["reuse_execution"]["reused_tool_results"] == [
        "poi_search",
        "weather_query",
    ]

    agent_outputs = second["output"]["agent_outputs"]
    assert agent_outputs["attraction"]["status"] == "reused"
    assert agent_outputs["weather"]["status"] == "reused"
    assert agent_outputs["itinerary"]["status"] == "completed"
    assert agent_outputs["budget"]["status"] == "completed"
    assert second["output"]["used_agents"] == ["itinerary", "budget"]
    assert set(second["output"]["metadata"]["result_agents"]) == {
        "attraction",
        "weather",
        "itinerary",
        "budget",
    }


def test_m3_complete_plan_without_date_executes_itinerary_without_weather(
    tmp_path: Path,
) -> None:
    fake_llm = _CountingResearchLLM()
    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        llm_factory=lambda: fake_llm,
    )

    result = runner.run(
        {
            "case_id": "m3-no-date-trip-plan",
            "user_input": "Plan a three-day Guilin trip for two people with a 5000 yuan budget.",
            "slots": {
                "destination": "guilin",
                "duration_days": 3,
                "people_count": 2,
                "budget_amount": 5000,
            },
        },
        method="adaptive_multi_agent",
    )

    assert result["status"] == "completed"
    assert result["output"]["execution_status"] == "completed"

    scheduler = result["output"]["metadata"]["adaptive_scheduler"]
    assert scheduler["ticket"]["task_type"] == "trip_plan"
    assert scheduler["decision"]["planned_agents"] == ["attraction", "itinerary", "budget"]
    assert scheduler["decision"]["planned_tools"] == ["poi_search", "budget_calculator"]
    assert scheduler["result_fingerprints"].keys() >= {"attraction", "itinerary", "budget"}
    assert "weather" not in scheduler["result_fingerprints"]

    assert result["trace"]["planned_agents"] == ["attraction", "itinerary", "budget"]
    assert result["trace"]["executed_agents"] == ["attraction", "itinerary", "budget"]
    assert result["trace"]["planned_tools"] == ["poi_search", "budget_calculator"]
    assert result["trace"]["executed_tools"] == ["poi_search", "budget_calculator"]
    assert [call["tool_name"] for call in result["trace"]["tool_calls"]] == [
        "poi_search",
        "budget_calculator",
    ]

    assert result["output"]["planned_agents"] == ["attraction", "itinerary", "budget"]
    assert result["output"]["used_agents"] == result["trace"]["executed_agents"]
    assert result["output"]["weather"] is None
    assert "weather_query" not in result["output"]["tool_results"]
    assert len(result["output"]["daily_itinerary"]) == 3

    itinerary_output = result["output"]["agent_outputs"]["itinerary"]
    assert itinerary_output["status"] == "completed"
    assert itinerary_output["evidence_tools"] == ["poi_search"]
    assert itinerary_output["upstream_agents"] == ["attraction"]


def test_business_agent_invalid_json_uses_evidence_normalizer(tmp_path: Path) -> None:
    class InvalidAgentLLM:
        async def chat(self, messages, tools=None):
            return SimpleNamespace(
                content="not json",
                tool_calls=[],
                usage={
                    "prompt_tokens": 5,
                    "completion_tokens": 2,
                    "total_tokens": 7,
                },
            )

    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        llm_factory=InvalidAgentLLM,
    )

    result = runner.run(
        {
            "case_id": "m2-invalid-agent-json",
            "user_input": "Plan a two-day Hangzhou trip on 2026-08-01 for two people.",
            "slots": {
                "destination": "hangzhou",
                "duration": 2,
                "people_count": 2,
                "start_date": "2026-08-01",
            },
        },
        method="fixed_multi_agent",
    )

    attraction_output = result["output"]["agent_outputs"]["attraction"]
    assert attraction_output["status"] == "completed"
    assert attraction_output["decision_source"] == "deterministic_evidence_normalizer"
    assert attraction_output["decision_fallback_used"] is True
    assert attraction_output["decision_parse_status"] == "passed"
    assert attraction_output["llm_decision_parse_status"] == "failed"
    assert "not strict JSON" in attraction_output["decision_fallback_reason"]
    assert result["output"]["execution_status"] == "completed"
    assert result["status"] == "completed"
    assert all(
        output["decision_fallback_used"]
        for output in result["output"]["agent_outputs"].values()
    )
    assert len(result["output"]["daily_itinerary"]) == 2
    assert all(day["attractions"] for day in result["output"]["daily_itinerary"])


def test_business_agent_invalid_json_keeps_failure_when_normalizer_disabled(
    tmp_path: Path,
) -> None:
    class InvalidAgentLLM:
        async def chat(self, messages, tools=None):
            return SimpleNamespace(
                content="not json",
                tool_calls=[],
                usage={
                    "prompt_tokens": 5,
                    "completion_tokens": 2,
                    "total_tokens": 7,
                },
            )

    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        llm_factory=InvalidAgentLLM,
        enable_research_agent_decision_normalizer=False,
    )

    result = runner.run(
        {
            "case_id": "m2-invalid-agent-json-no-normalizer",
            "user_input": "Plan a two-day Hangzhou trip on 2026-08-01 for two people.",
            "slots": {
                "destination": "hangzhou",
                "duration": 2,
                "people_count": 2,
                "start_date": "2026-08-01",
            },
        },
        method="fixed_multi_agent",
    )

    attraction_output = result["output"]["agent_outputs"]["attraction"]
    assert attraction_output["status"] == "failed"
    assert attraction_output["decision_source"] == "llm"
    assert attraction_output["decision_fallback_used"] is False
    assert attraction_output["decision_normalizer_enabled"] is False
    assert attraction_output["decision_normalizer_skipped"] is True
    assert "not strict JSON" in attraction_output["decision_errors"][0]
    assert result["output"]["execution_status"] == "failed"
    assert result["status"] == "failed"


def test_business_agent_watchdog_timeout_uses_evidence_normalizer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class HangingLLM:
        async def chat(self, messages, tools=None):
            await asyncio.sleep(3600)

    monkeypatch.setenv("EXPERIMENT_LLM_CALL_TIMEOUT_SECONDS", "0.01")
    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        llm_factory=HangingLLM,
    )

    result = runner.run(
        {
            "case_id": "m2-agent-timeout-fallback",
            "user_input": "Plan a two-day Hangzhou trip on 2026-08-01 for two people.",
            "slots": {
                "destination": "hangzhou",
                "duration": 2,
                "people_count": 2,
                "start_date": "2026-08-01",
            },
        },
        method="fixed_multi_agent",
    )

    assert result["status"] == "completed"
    assert result["output"]["execution_status"] == "completed"
    assert "最终答案整理模型调用超时" in result["output"]["final_answer"]
    for output in result["output"]["agent_outputs"].values():
        assert output["decision_source"] == "deterministic_evidence_normalizer"
        assert output["decision_fallback_used"] is True
        assert "watchdog timeout" in output["decision_fallback_reason"]


def test_business_agent_transport_error_uses_evidence_normalizer(tmp_path: Path) -> None:
    class APIConnectionError(Exception):
        pass

    class ConnectionFailingLLM:
        async def chat(self, messages, tools=None):
            raise APIConnectionError("Connection error.")

    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        llm_factory=ConnectionFailingLLM,
    )

    result = runner.run(
        {
            "case_id": "m2-agent-transport-error-fallback",
            "user_input": "Plan a two-day Hangzhou trip on 2026-08-01 for two people.",
            "slots": {
                "destination": "hangzhou",
                "duration": 2,
                "people_count": 2,
                "start_date": "2026-08-01",
            },
        },
        method="fixed_multi_agent",
    )

    assert result["status"] == "completed"
    assert result["output"]["execution_status"] == "completed"
    for output in result["output"]["agent_outputs"].values():
        assert output["decision_source"] == "deterministic_evidence_normalizer"
        assert output["decision_fallback_used"] is True
        assert "network_connection" in output["decision_fallback_reason"]


def test_business_agent_program_error_does_not_use_evidence_normalizer(
    tmp_path: Path,
) -> None:
    class BuggyLLM:
        async def chat(self, messages, tools=None):
            raise RuntimeError("program bug while building request")

    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        llm_factory=BuggyLLM,
    )

    result = runner.run(
        {
            "case_id": "m2-agent-program-error-no-fallback",
            "user_input": "Plan a two-day Hangzhou trip on 2026-08-01 for two people.",
            "slots": {
                "destination": "hangzhou",
                "duration": 2,
                "people_count": 2,
                "start_date": "2026-08-01",
            },
        },
        method="fixed_multi_agent",
    )

    assert "program bug while building request" in result["error"]
    assert result["output"]["agent_outputs"] == {}
    assert result["output"]["execution_status"] == "failed"
    assert result["status"] == "failed"


def test_default_llm_watchdog_covers_all_retry_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EXPERIMENT_LLM_CALL_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("LLM_TIMEOUT", "60")
    monkeypatch.setenv("LLM_RETRY_MAX_ATTEMPTS", "3")

    assert _experiment_llm_call_timeout_seconds() == 185.0


def test_clarification_answer_uses_chinese_budget_label(tmp_path: Path) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")

    answer = runner._compose_clarification_answer(
        ["start_date", "duration_days", "budget_amount"]
    )

    assert "出发日期" in answer
    assert "旅行天数" in answer
    assert "预算" in answer
    assert "budget_amount" not in answer


def test_real_runner_constraint_checker_fails_when_tool_evidence_missing(
    tmp_path: Path,
) -> None:
    async def handler(case):
        return {
            "task_type": "trip_planning",
            "used_agents": ["attraction", "weather", "itinerary", "budget"],
            "planned_tools": list(GENERATION_TOOL_NAMES),
            "trip_days": 1,
            "daily_itinerary": [
                {
                    "day": 1,
                    "attractions": [
                        {"poi_id": "hz005", "name": "中国茶叶博物馆"},
                    ],
                }
            ],
            "weather": {"scenario_type": "sunny", "daily_weather": []},
            "budget": {"total": 500},
            "weather_adjustments": [],
            "tool_results": {
                "poi_search": {
                    "tool_name": "poi_search",
                    "status": "success",
                    "success": True,
                    "data": {},
                }
            },
            "final_answer": "缺少天气和预算工具证据的方案",
        }

    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        method_handlers={"adaptive_multi_agent": handler},
    )
    result = runner.run(
        {
            "case_id": "runner-tool-evidence-missing",
            "user_input": "帮我规划杭州一天旅游，预算1000",
            "slots": {
                "destination": "杭州",
                "duration": 1,
                "budget": 1000,
            },
        },
        method="adaptive_multi_agent",
    )

    checks = {
        item["name"]: item
        for item in result["constraint_report"]["data"]["checks"]
    }

    assert checks["tool_evidence"]["status"] == "failed"
    assert checks["tool_evidence"]["details"]["missing_or_failed"] == [
        "weather_query",
        "budget_calculator",
    ]
    assert result["hard_constraints_all_satisfied"] is False
    assert result["hcsr"] < 1.0


def test_research_output_completes_minimum_attractions_from_tool_evidence(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    tool_results = {
        "poi_search": {
            "tool_name": "poi_search",
            "status": "success",
            "success": True,
            "data": {
                "attractions": [
                    {"poi_id": "hz001", "name": "A", "indoor_outdoor": "outdoor"},
                    {"poi_id": "hz002", "name": "B", "indoor_outdoor": "indoor"},
                    {"poi_id": "hz003", "name": "C", "indoor_outdoor": "indoor"},
                    {"poi_id": "hz004", "name": "D", "indoor_outdoor": "outdoor"},
                ]
            },
        }
    }
    agent_outputs = {
        "attraction": {
            "decision_validation_status": "passed",
            "decision": {
                "decisions": {
                    "selected_poi_ids": ["hz001"],
                }
            },
        }
    }
    case = {
        "case_id": "complete-min-attractions",
        "expected": {
            "hard_constraints": {
                "min_attractions": 3,
                "max_attractions": 4,
            }
        },
    }

    attractions = runner._attractions_for_research_output(
        case=case,
        tool_results=tool_results,
        agent_outputs=agent_outputs,
    )

    assert [item["poi_id"] for item in attractions] == ["hz001", "hz002", "hz003"]
    assert attractions[0]["agent_selected"] is True
    assert attractions[1]["agent_decision_source"] == "evidence_minimum_completion"


def test_research_itinerary_evidence_normalizer_reorders_rain_day_to_safe_pois(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    attractions = [
        {"poi_id": "hz001", "name": "Outdoor A", "indoor_outdoor": "outdoor"},
        {"poi_id": "hz002", "name": "Indoor B", "indoor_outdoor": "indoor"},
        {"poi_id": "hz003", "name": "Outdoor C", "indoor_outdoor": "outdoor"},
        {"poi_id": "hz004", "name": "Indoor D", "indoor_outdoor": "indoor"},
    ]
    weather = {
        "scenario_type": "rain",
        "daily_weather": [
            {"day_index": 1, "state": "rain"},
            {"day_index": 2, "state": "sunny"},
        ],
    }
    daily_itinerary = [
        {
            "day": 1,
            "attractions": [
                {"poi_id": "hz001", "name": "Outdoor A", "indoor_outdoor": "outdoor"},
                {"poi_id": "hz003", "name": "Outdoor C", "indoor_outdoor": "outdoor"},
            ],
        },
        {
            "day": 2,
            "attractions": [
                {"poi_id": "hz002", "name": "Indoor B", "indoor_outdoor": "indoor"},
            ],
        },
    ]
    case = {
        "case_id": "rain-normalize",
        "weather_change": {"affected_days": [1], "scenario_type": "rain"},
        "expected": {
            "hard_constraints": {
                "min_attractions": 3,
                "max_attractions": 4,
                "max_pois_per_day": 2,
                "weather_adjustment_required": True,
            }
        },
    }

    normalized, audit = runner._normalize_daily_itinerary_for_evidence_constraints(
        trip_days=2,
        attractions=attractions,
        weather=weather,
        case=case,
        daily_itinerary=daily_itinerary,
    )

    assert audit["applied"] is True
    assert "weather_risk_day_poi_reordered" in audit["reasons"]
    assert [item["poi_id"] for item in normalized[0]["attractions"]] == ["hz002", "hz004"]
    assert all(item["indoor_outdoor"] == "indoor" for item in normalized[0]["attractions"])
    assert len({poi_id for day in normalized for poi_id in runner._day_itinerary_poi_ids(day)}) >= 3


def test_research_itinerary_evidence_normalizer_reserves_safe_pois_for_later_rain_day(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    attractions = [
        {
            "poi_id": "hz002",
            "name": "Mixed Safe A",
            "indoor_outdoor": "mixed",
            "rain_suitability": "suitable",
            "outdoor_ratio": 0.5,
        },
        {
            "poi_id": "hz004",
            "name": "Mixed Safe B",
            "indoor_outdoor": "mixed",
            "rain_suitability": "suitable",
            "outdoor_ratio": 0.5,
        },
        {
            "poi_id": "hz001",
            "name": "Outdoor A",
            "indoor_outdoor": "outdoor",
            "rain_suitability": "conditional",
            "outdoor_ratio": 0.9,
        },
        {
            "poi_id": "hz003",
            "name": "Outdoor B",
            "indoor_outdoor": "outdoor",
            "rain_suitability": "conditional",
            "outdoor_ratio": 0.9,
        },
    ]
    weather = {
        "scenario_type": "continuous_change",
        "weather_adjustment_required": True,
        "daily_weather": [
            {"day_index": 1, "state": "sunny"},
            {"day_index": 2, "state": "rain"},
        ],
    }
    daily_itinerary = [
        {"day": 1, "attractions": [{"poi_id": "hz002"}, {"poi_id": "hz004"}]},
        {"day": 2, "attractions": [{"poi_id": "hz001"}, {"poi_id": "hz003"}]},
    ]

    normalized, audit = runner._normalize_daily_itinerary_for_evidence_constraints(
        trip_days=2,
        attractions=attractions,
        weather=weather,
        case={"case_id": "later-rain", "user_input": "杭州两天旅行，需要天气和行程。"},
        daily_itinerary=daily_itinerary,
    )

    assert audit["applied"] is True
    assert [item["poi_id"] for item in normalized[1]["attractions"]] == ["hz002", "hz004"]


def test_itinerary_evidence_normalizer_enforces_daily_load_and_deduplicates(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    attractions = [
        {"poi_id": "hz001", "name": "West Lake"},
        {"poi_id": "hz002", "name": "Lingyin Temple"},
        {"poi_id": "hz003", "name": "Xixi Wetland"},
        {"poi_id": "hz004", "name": "Grand Canal"},
    ]
    daily_itinerary = [
        {
            "day": 1,
            "attractions": [
                {"poi_id": "hz001"},
                {"poi_id": "hz002"},
                {"poi_id": "hz004"},
            ],
        },
        {"day": 2, "attractions": [{"poi_id": "hz004"}]},
    ]
    case = {
        "case_id": "daily-load-duplicate-normalize",
        "expected": {
            "hard_constraints": {
                "min_attractions": 4,
                "max_attractions": 4,
                "max_pois_per_day": 2,
            }
        },
    }

    normalized, audit = runner._normalize_daily_itinerary_for_evidence_constraints(
        trip_days=2,
        attractions=attractions,
        weather={},
        case=case,
        daily_itinerary=daily_itinerary,
    )
    day_refs = [runner._day_itinerary_poi_ids(day) for day in normalized]
    flat_refs = [poi_id for refs in day_refs for poi_id in refs]

    assert audit["applied"] is True
    assert "daily_load_limit_enforced" in audit["reasons"]
    assert "duplicate_pois_removed" in audit["reasons"]
    assert all(len(refs) <= 2 for refs in day_refs)
    assert len(flat_refs) == len(set(flat_refs))
    assert set(flat_refs) == {"hz001", "hz002", "hz003", "hz004"}


def test_normalize_case_parses_visible_chinese_slots_for_runtime_arguments(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    case = runner._normalize_case(
        {
            "case_id": "visible-slots",
            "user_input": "请为杭州规划一个2026年8月1日出发的两天情侣旅行，共2人，预算5000元。",
        }
    )

    assert case["slots"]["destination"] == "hangzhou"
    assert case["slots"]["duration_days"] == 2
    assert runner._case_duration(case) == 2


def test_chinese_nature_attraction_request_parses_requested_poi_count(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    case = runner._normalize_case(
        {
            "case_id": "guilin-nature-count",
            "user_input": "只推荐桂林3个自然山水类景点，不要生成完整行程、天气报告或预算。",
        }
    )

    assert runner._case_requested_poi_count(case) == 3


def test_attraction_single_scope_constraint_payload_omits_itinerary_requirements(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    case = runner._normalize_case(
        {
            "case_id": "guilin-attraction-only",
            "user_input": "只推荐桂林3个自然山水类景点，不要生成完整行程、天气报告或预算。",
            "expected": {
                "task_type": "attraction_recommendation",
                "min_attractions": 3,
                "max_attractions": 3,
            },
        }
    )

    request = runner._constraint_request_payload(case)
    constraints = runner._constraint_payload(case)

    assert "days" not in request
    assert "days" not in constraints
    assert "weather_adjustment_required" not in constraints
    assert constraints["min_attractions"] == 3
    assert constraints["max_attractions"] == 3


def test_research_budget_arguments_use_constraint_aware_selected_pois(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    tool_results = {
        "poi_search": {
            "tool_name": "poi_search",
            "status": "success",
            "success": True,
            "data": {
                "attractions": [
                    {
                        "poi_id": "bj001",
                        "name": "High Outdoor",
                        "indoor_outdoor": "outdoor",
                        "visit_intensity": "high",
                        "walking_level": "high",
                    },
                    {
                        "poi_id": "bj002",
                        "name": "Indoor Medium",
                        "indoor_outdoor": "indoor",
                        "visit_intensity": "medium",
                        "walking_level": "medium",
                    },
                    {
                        "poi_id": "bj003",
                        "name": "Indoor Low",
                        "indoor_outdoor": "indoor",
                        "visit_intensity": "low",
                        "walking_level": "low",
                    },
                    {
                        "poi_id": "bj004",
                        "name": "Outdoor Medium",
                        "indoor_outdoor": "outdoor",
                        "visit_intensity": "medium",
                        "walking_level": "medium",
                    },
                    {
                        "poi_id": "bj005",
                        "name": "Indoor Backup",
                        "indoor_outdoor": "indoor",
                        "visit_intensity": "low",
                        "walking_level": "low",
                    },
                ],
            },
        },
        "weather_query": {
            "tool_name": "weather_query",
            "status": "success",
            "success": True,
            "data": {
                "scenario_type": "rain",
                "daily_weather": [{"day_index": 1, "state": "rain"}],
            },
        },
    }
    agent_outputs = {
        "attraction": {
            "decision_validation_status": "passed",
            "decision": {
                "decisions": {
                    "selected_poi_ids": ["bj001", "bj002", "bj003", "bj004"],
                }
            },
        }
    }
    case = {
        "case_id": "senior-budget-pois",
        "user_input": "帮4位老人做北京三天轻松行程，预算8000元。",
        "slots": {
            "destination": "beijing",
            "duration_days": 3,
            "people_count": 4,
            "traveler_group": "senior",
        },
        "expected": {
            "hard_constraints": {
                "min_attractions": 3,
                "max_attractions": 3,
                "max_pois_per_day": 2,
            }
        },
    }

    args = runner._research_tool_arguments(
        "budget_calculator",
        case,
        tool_results,
        agent_outputs=agent_outputs,
    )

    assert args["attractions"] == ["bj002", "bj003", "bj005"]


def test_senior_visible_request_limits_selected_pois_without_gold_constraints(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    attractions = [
        {"poi_id": "bj004", "name": "Indoor", "indoor_outdoor": "indoor", "visit_intensity": "medium", "walking_level": "medium"},
        {"poi_id": "bj001", "name": "High Mixed", "indoor_outdoor": "mixed", "visit_intensity": "high", "walking_level": "high"},
        {"poi_id": "bj002", "name": "Outdoor Medium", "indoor_outdoor": "outdoor", "visit_intensity": "medium", "walking_level": "medium"},
        {"poi_id": "bj005", "name": "Outdoor Medium 2", "indoor_outdoor": "outdoor", "visit_intensity": "medium", "walking_level": "medium"},
        {"poi_id": "bj006", "name": "Outdoor Low", "indoor_outdoor": "outdoor", "visit_intensity": "low", "walking_level": "low"},
        {"poi_id": "bj003", "name": "High Outdoor", "indoor_outdoor": "outdoor", "visit_intensity": "high", "walking_level": "high"},
    ]
    case = runner._normalize_case(
        {
            "case_id": "senior-visible",
            "user_input": "帮4位老人做北京三天轻松行程，预算8000元。",
        }
    )

    selected = runner._select_constraint_aware_attractions(
        attractions,
        case=case,
        weather={},
        preferred_ids=["bj004", "bj001", "bj002", "bj005", "bj006", "bj003"],
    )

    assert [item["poi_id"] for item in selected] == ["bj004", "bj002", "bj005", "bj006"]
    assert all(item["visit_intensity"] != "high" for item in selected)


def test_budget_level_for_research_tool_does_not_auto_downgrade_for_budget_limit(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    case = runner._normalize_case(
        {
            "case_id": "senior-budget-level",
            "user_input": "帮4位老人做北京三天轻松行程，预算8000元。",
        }
    )

    level = runner._budget_level_for_research_tool(
        case=case,
        city="beijing",
        people_count=4,
        duration_days=3,
        selected_poi_ids=["bj004", "bj002", "bj005", "bj006"],
    )

    assert level == "medium"


def test_budget_tool_arguments_use_normalized_final_itinerary(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    tool_results = {
        "poi_search": {
            "tool_name": "poi_search",
            "status": "success",
            "success": True,
            "data": {
                "city": "beijing",
                "attractions": [
                    {"poi_id": "bj001", "name": "A", "indoor_outdoor": "outdoor"},
                    {"poi_id": "bj002", "name": "B", "indoor_outdoor": "indoor"},
                    {"poi_id": "bj003", "name": "C", "indoor_outdoor": "mixed"},
                    {"poi_id": "bj004", "name": "D", "indoor_outdoor": "outdoor"},
                ],
            },
        },
        "weather_query": {
            "tool_name": "weather_query",
            "status": "success",
            "success": True,
            "data": {
                "daily_weather": [{"day_index": 1, "condition": "sunny"}],
            },
        },
    }
    agent_outputs = {
        "itinerary": {
            "status": "completed",
            "success": True,
            "decision_validation_status": "passed",
            "decision": {
                "decisions": {
                    "daily_itinerary": [
                        {"day": 1, "attraction_poi_ids": ["bj001", "bj002", "bj003"]},
                        {"day": 2, "attraction_poi_ids": ["bj003", "bj004"]},
                    ]
                }
            },
        }
    }
    case = {
        "case_id": "budget-final-itinerary-consistency",
        "user_input": "北京两天，最多每天两个景点，预算5000。",
        "slots": {
            "destination": "beijing",
            "duration_days": 2,
            "people_count": 2,
            "budget_amount": 5000,
        },
        "expected": {
            "hard_constraints": {
                "max_pois_per_day": 2,
                "max_attractions": 3,
            }
        },
    }
    weather = runner._tool_data(tool_results["weather_query"])
    attractions = runner._attractions_for_research_output(
        case=case,
        tool_results=tool_results,
        agent_outputs=agent_outputs,
        weather=weather,
    )
    final_itinerary = runner._daily_itinerary_for_research_output(
        case=case,
        trip_days=2,
        attractions=attractions,
        weather=weather,
        planned_agents=["itinerary", "budget"],
        reused_agents=[],
        agent_outputs=agent_outputs,
        previous_state=None,
    )
    final_itinerary, _audit = runner._normalize_daily_itinerary_for_evidence_constraints(
        trip_days=2,
        attractions=attractions,
        weather=weather,
        case=case,
        daily_itinerary=final_itinerary,
    )

    args = runner._research_tool_arguments(
        "budget_calculator",
        case,
        tool_results,
        agent_outputs=agent_outputs,
    )

    assert runner._daily_itinerary_day_poi_ids(args["daily_itinerary"]) == (
        runner._daily_itinerary_day_poi_ids(final_itinerary)
    )
    assert args["attractions"] == runner._daily_itinerary_poi_ids(final_itinerary)


def test_research_answer_summary_filters_unselected_poi_mentions(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    tool_results = {
        "poi_search": {
            "tool_name": "poi_search",
            "status": "success",
            "success": True,
            "data": {
                "attractions": [
                    {"poi_id": "bj001", "name": "Unselected"},
                    {"poi_id": "bj004", "name": "Selected"},
                ]
            },
        }
    }

    answer = runner._answer_with_research_evidence_summary(
        "模型正文误提到了 Unselected。",
        attractions=[{"poi_id": "bj004", "name": "Selected"}],
        budget={"total": 500},
        weather={"scenario_type": "sunny"},
        tool_results=tool_results,
    )

    assert "Selected(bj004)" in answer
    assert "Unselected" not in answer
    assert "500" in answer
    assert "sunny" in answer


def test_constraint_checker_plan_drops_top_level_attractions_when_itinerary_carries_pois(
    tmp_path: Path,
) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces")
    attractions = [{"poi_id": "hz001", "name": "A"}, {"poi_id": "hz002", "name": "B"}]
    daily_itinerary = [
        {"day": 1, "attractions": [{"poi_id": "hz001", "name": "A"}]},
        {"day": 2, "attractions": [{"poi_id": "hz002", "name": "B"}]},
    ]

    output_attractions, audit = runner._canonical_attractions_for_constraint_plan(
        task_type="trip_planning",
        attractions=attractions,
        daily_itinerary=daily_itinerary,
    )

    assert output_attractions == []
    assert audit["applied"] is True
    assert audit["reason"] == "constraint_checker_uses_itinerary_pois_to_avoid_duplicate_counting"


def test_real_runner_constraint_checker_fails_when_tool_evidence_failed(
    tmp_path: Path,
) -> None:
    async def handler(case):
        return {
            "task_type": "trip_planning",
            "used_agents": ["attraction", "weather", "itinerary", "budget"],
            "planned_tools": list(GENERATION_TOOL_NAMES),
            "trip_days": 1,
            "daily_itinerary": [
                {
                    "day": 1,
                    "attractions": [
                        {"poi_id": "hz005", "name": "中国茶叶博物馆"},
                    ],
                }
            ],
            "weather": {"scenario_type": "sunny", "daily_weather": []},
            "budget": {"total": 500},
            "weather_adjustments": [],
            "tool_results": {
                "poi_search": {
                    "tool_name": "poi_search",
                    "status": "success",
                    "success": True,
                    "data": {},
                },
                "weather_query": {
                    "tool_name": "weather_query",
                    "status": "failed",
                    "success": False,
                    "data": {},
                    "error": {"code": "forced_failure"},
                },
                "budget_calculator": {
                    "tool_name": "budget_calculator",
                    "status": "success",
                    "success": True,
                    "data": {},
                },
            },
            "final_answer": "包含失败天气工具证据的方案",
        }

    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        method_handlers={"adaptive_multi_agent": handler},
    )
    result = runner.run(
        {
            "case_id": "runner-tool-evidence-failed",
            "user_input": "帮我规划杭州一天旅游，预算1000",
            "slots": {
                "destination": "杭州",
                "duration": 1,
                "budget": 1000,
            },
        },
        method="adaptive_multi_agent",
    )

    checks = {
        item["name"]: item
        for item in result["constraint_report"]["data"]["checks"]
    }

    assert checks["tool_evidence"]["status"] == "failed"
    assert checks["tool_evidence"]["details"]["missing_or_failed"] == ["weather_query"]
    assert result["hard_constraints_all_satisfied"] is False
    assert result["output"]["execution_status"] == "failed"
    assert result["status"] == "failed"


def test_runner_loads_trace_by_exact_request_id_not_newest_file(tmp_path: Path) -> None:
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    expected_path = trace_dir / "001_expected.jsonl"
    expected_path.write_text(
        json.dumps({"request_id": "expected-request", "status": "completed"}) + "\n",
        encoding="utf-8",
    )
    newest_path = trace_dir / "999_newest.jsonl"
    newest_path.write_text(
        json.dumps({"request_id": "different-request", "status": "failed"}) + "\n",
        encoding="utf-8",
    )

    runner = ExperimentRunner(trace_dir=trace_dir)
    record = runner._load_trace_by_request_id("expected-request")

    assert record is not None
    assert record["request_id"] == "expected-request"
    assert record["status"] == "completed"
    assert record["trace_file"] == str(expected_path)
