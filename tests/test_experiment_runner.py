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

from app.core.experiment_runner import ExperimentRunner
from app.core.fixed_data import (
    CANONICAL_JSON_SHA256_STRATEGY,
    FIXED_DATA_EXPECTED_COMBINED_SHA256,
)
from app.core.llm.client import ToolCall
from app.core.tracing import get_current_trace, record_selected_tool, set_trace_selected_agents


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
    expected_methods = runner._ordered_methods_for_benchmark(list(ExperimentRunner.METHODS))

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

    csv_path = tmp_path / "results" / runner.run_id / "benchmark_results.csv"
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    assert [row["method"] for row in rows] == expected_methods
    assert all(row["case_id"] == "case001" for row in rows)
    assert all(row["evaluation_mode"] == "end_to_end" for row in rows)
    assert all(row["tool_selection_accuracy"] == "1.0" for row in rows)
    assert all(float(row["ttft_ms"]) >= 0 for row in rows)


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

    assert result["output"]["schema_version"] == "ctp-experiment-output-v1"
    assert result["output"]["final_answer"] == "tool-backed plan"
    assert result["raw_output"] == "tool-backed plan"
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
    assert manifest["offline_data"]["snapshot"]["hash_strategy"] == CANONICAL_JSON_SHA256_STRATEGY
    assert manifest["offline_data"]["snapshot"]["combined_sha256"] == FIXED_DATA_EXPECTED_COMBINED_SHA256
    assert len(list(csv.DictReader((run_output_dir / "benchmark_results.csv").open(encoding="utf-8-sig")))) == 16


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
