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
    RESEARCH_AGENT_DECISION_SCHEMA_VERSION,
    RESEARCH_AGENT_OUTPUT_SCHEMA_VERSION,
    ExperimentRunner,
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
from app.core.tracing import get_current_trace, record_selected_tool, set_trace_selected_agents
from app.tools.research_tools import GENERATION_TOOL_NAMES


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
        assert result["evaluation"]["catalog_id"] == "day5_independent_evaluator_rules"
        assert "stsr" in result["metrics"]

    csv_path = tmp_path / "results" / runner.run_id / "benchmark_results.csv"
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    assert [row["method"] for row in rows] == expected_methods
    assert all(row["case_id"] == "case001" for row in rows)
    assert all(row["evaluation_mode"] == "end_to_end" for row in rows)
    assert all(row["tool_selection_accuracy"] == "1.0" for row in rows)
    assert all(float(row["ttft_ms"]) >= 0 for row in rows)
    assert {"stsr", "evaluation_hcsr", "evaluation_failed_rule_ids", "agent_selection_f1", "tool_selection_f1"} <= set(rows[0])
    summary = json.loads((csv_path.parent / "evaluation_summary.json").read_text(encoding="utf-8"))
    assert summary["schema_version"] == EVALUATION_SUMMARY_SCHEMA_VERSION
    assert summary["result_count"] == 4


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
    assert lf_manifest["evaluation"]["catalog_id"] == "day5_independent_evaluator_rules"
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
            "user_input": "Plan a three-day Hangzhou trip for two people.",
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
    assert manifest["cache_enabled"] is False
    assert manifest["strict_mode"] is True
    assert manifest["repeats"] == 2
    assert manifest["model_config_name"] == "offline-static"
    assert manifest["method_order_seed"] == runner.method_order_seed
    assert manifest["prompt_versions"]["structured_llm_output"] == "ctp-structured-llm-output-prompts-v1"
    assert manifest["prompt_versions"]["research_agent"] == "ctp-research-agent-prompts-v1"
    assert manifest["costing"]["schema_version"] == "ctp-llm-costing-v1"
    assert manifest["costing"]["price_snapshot"]["pricing_mode"] == "mock_zero_cost"
    assert manifest["costing"]["input_token_unit_price"] == 0.0
    assert manifest["costing"]["output_token_unit_price"] == 0.0
    assert manifest["offline_data"]["snapshot"]["hash_strategy"] == CANONICAL_JSON_SHA256_STRATEGY
    assert manifest["offline_data"]["snapshot"]["combined_sha256"] == FIXED_DATA_EXPECTED_COMBINED_SHA256
    assert manifest["evaluation"]["schema_version"] == EVALUATION_SCHEMA_VERSION
    assert manifest["evaluation"]["summary_schema_version"] == EVALUATION_SUMMARY_SCHEMA_VERSION
    assert manifest["evaluation"]["catalog_id"] == "day5_independent_evaluator_rules"
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
    fake_llm = _CountingResearchLLM()
    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        llm_factory=lambda: fake_llm,
    )

    result = runner.run(
        {
            "case_id": "m2-agent-llm",
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
    assert all(
        day["agent_decision_source"] == "itinerary"
        for day in result["output"]["daily_itinerary"]
    )
    assert result["output"]["daily_itinerary"][0]["notes"] == "test itinerary day 1"
    assert result["output"]["weather"]["agent_weather_decision"]["source"] == "weather"
    assert result["output"]["budget"]["agent_budget_decision"]["feasibility"] == "feasible"
    assert result["output"]["metadata"]["agent_decision_schema_version"] == (
        RESEARCH_AGENT_DECISION_SCHEMA_VERSION
    )
    assert result["output"]["metadata"]["agent_decision_audit"]["itinerary"] == {
        "status": "completed",
        "reused": False,
        "decision_parse_status": "passed",
        "decision_validation_status": "passed",
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


def test_business_agent_invalid_json_marks_method_failed(tmp_path: Path) -> None:
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
    assert attraction_output["status"] == "failed"
    assert attraction_output["decision_parse_status"] == "failed"
    assert "not strict JSON" in attraction_output["error"]
    assert result["output"]["execution_status"] == "failed"
    assert result["status"] == "failed"


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
