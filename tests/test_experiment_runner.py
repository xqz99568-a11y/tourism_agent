import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.experiment_runner import ExperimentRunner
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
        assert result["trace"]["experiment_case_id"] == "case001"
        assert result["trace"]["method"] == result["method"]
        assert result["trace"]["intent"] == "weather_adjustment"
        assert result["trace"]["route"] == "FULL_NEW_PLAN"
        assert result["trace"]["selected_agents"] == ["weather"]
        assert result["trace"]["selected_tools"] == ["weather"]
        assert result["ttft_ms"] == result["trace"]["first_body_token_ms"]
        assert result["metrics"]["tool_selection_accuracy"] == 1.0

    csv_path = tmp_path / "results" / "benchmark_results.csv"
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    assert [row["method"] for row in rows] == ["llm_direct", "single_agent", "full_system"]
    assert all(row["case_id"] == "case001" for row in rows)
    assert all(row["tool_selection_accuracy"] == "1.0" for row in rows)
    assert all(float(row["ttft_ms"]) >= 0 for row in rows)


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
