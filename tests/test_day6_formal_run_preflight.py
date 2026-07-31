import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.experiment_runner import ExperimentRunner
from app.core.formal_experiment_preflight import (
    FORMAL_PREFLIGHT_SCHEMA_VERSION,
    build_formal_preflight_report,
)
from app.core.tracing import get_current_trace


def test_day6_formal_preflight_accepts_scenario_dataset_without_gold_leak(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _formal_env(monkeypatch)
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "dataset_id": "formal-dev",
                "cases": [
                    {
                        "case_id": "scenario_001",
                        "turns": [
                            {
                                "turn_id": "t1",
                                "user_input": "帮我规划杭州2天旅游，2026-08-01出发，两人。",
                                "expected": {
                                    "task_type": "trip_planning",
                                    "duration_days": 2,
                                    "min_attractions": 2,
                                    "required_tools": ["poi_search", "weather_query", "budget_calculator"],
                                    "accepted_agent_sets": [["attraction", "weather", "itinerary", "budget"]],
                                    "accepted_tool_sets": [["poi_search", "weather_query", "budget_calculator"]],
                                    "secret_marker": "GOLD_MUST_NOT_LEAK",
                                },
                            },
                            {
                                "turn_id": "t2",
                                "user_input": "人数改成3人，预算重新算一下",
                                "expected": {
                                    "task_type": "budget_query",
                                    "changed_slots": ["people_count"],
                                    "preserved_slots": ["destination", "duration_days", "start_date"],
                                    "required_tools": ["budget_calculator"],
                                    "accepted_agent_sets": [["budget"]],
                                    "accepted_tool_sets": [["budget_calculator"]],
                                },
                            },
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_formal_preflight_report(
        benchmark_path=benchmark_path,
        output_dir=tmp_path / "runs",
        run_id="formal-preflight",
        methods=ExperimentRunner.METHODS,
        repeats=1,
        require_llm_config=False,
    )

    assert report["schema_version"] == FORMAL_PREFLIGHT_SCHEMA_VERSION
    assert report["status"] == "passed"
    assert report["benchmark"]["case_count"] == 1
    assert report["benchmark"]["scenario_case_count"] == 1
    assert report["benchmark"]["total_turn_count"] == 2
    assert report["run"]["expected_raw_run_count"] == 8
    assert report["method_fairness_contract"]["contract_sha256"]
    assert "LLM runtime configuration check skipped" in report["warnings"]


def test_day6_formal_preflight_blocks_oracle_state_and_nonempty_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _formal_env(monkeypatch)
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "bad_state",
                        "user_input": "帮我规划杭州2天旅游",
                        "evaluation_mode": "oracle_slots",
                        "previous_state": {"status": "completed"},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    occupied = tmp_path / "runs" / "formal-bad"
    occupied.mkdir(parents=True)
    (occupied / "old.txt").write_text("keep", encoding="utf-8")

    report = build_formal_preflight_report(
        benchmark_path=benchmark_path,
        output_dir=tmp_path / "runs",
        run_id="formal-bad",
        methods=ExperimentRunner.METHODS,
        repeats=1,
        require_llm_config=False,
    )

    assert report["status"] == "failed"
    errors = "\n".join(report["errors"])
    assert "previous_state" in errors
    assert "oracle_slots" in errors
    assert "output directory is not empty" in errors
    assert (occupied / "old.txt").read_text(encoding="utf-8") == "keep"


def test_day6_scenario_runner_uses_same_method_previous_turn_state(
    tmp_path: Path,
) -> None:
    seen: dict[str, list[dict]] = {method: [] for method in ExperimentRunner.METHODS}

    def handler_for(method: str):
        async def _handler(case: dict) -> dict:
            previous_state = case.get("previous_state")
            seen[method].append(
                {
                    "turn_id": case.get("turn_id"),
                    "previous_method": (
                        previous_state.get("method")
                        if isinstance(previous_state, dict)
                        else None
                    ),
                    "previous_turn_id": (
                        previous_state.get("turn_id")
                        if isinstance(previous_state, dict)
                        else None
                    ),
                    "previous_has_evaluation": (
                        "evaluation" in previous_state
                        if isinstance(previous_state, dict)
                        else False
                    ),
                    "previous_has_metrics": (
                        "metrics" in previous_state
                        if isinstance(previous_state, dict)
                        else False
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
                "final_answer": f"{method}/{case.get('turn_id')}",
            }

        return _handler

    benchmark_path = tmp_path / "scenario_benchmark.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "dataset_id": "scenario-dev",
                "cases": [
                    {
                        "case_id": "scenario_001",
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
    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        output_dir=tmp_path / "results",
        method_handlers={method: handler_for(method) for method in ExperimentRunner.METHODS},
        run_id="scenario-run",
    )

    results = runner.run_benchmark(benchmark_path)

    assert len(results) == 8
    assert {result["case_id"] for result in results} == {"scenario_001"}
    assert {result["scenario_id"] for result in results} == {"scenario_001"}
    assert {result["turn_id"] for result in results} == {"t1", "t2"}
    for method in ExperimentRunner.METHODS:
        assert seen[method][0] == {
            "turn_id": "t1",
            "previous_method": None,
            "previous_turn_id": None,
            "previous_has_evaluation": False,
            "previous_has_metrics": False,
        }
        assert seen[method][1]["turn_id"] == "t2"
        assert seen[method][1]["previous_method"] == method
        assert seen[method][1]["previous_turn_id"] == "t1"
        assert seen[method][1]["previous_has_evaluation"] is False
        assert seen[method][1]["previous_has_metrics"] is False

    run_output_dir = tmp_path / "results" / "scenario-run"
    summary = json.loads((run_output_dir / "evaluation_summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_output_dir / "experiment_manifest.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader((run_output_dir / "benchmark_results.csv").open(encoding="utf-8-sig")))

    assert summary["unique_case_count"] == 1
    assert summary["paired_statistics"]["pair_count"] == 1
    assert summary["repeat_aggregation"]["unit"] == "evaluation_unit_id"
    assert summary["repeat_aggregation"]["scenario_turns_are_repeats"] is False
    assert summary["quality_evaluation_scope"]["multi_turn"] == "target_turn_only"
    assert summary["scenario_costs"]["scenario_count"] == 1
    assert manifest["benchmark_structure"]["scenario_case_count"] == 1
    assert manifest["benchmark_structure"]["total_turn_count"] == 2
    assert manifest["benchmark_structure"]["statistical_unit"] == "evaluation_unit_id"
    assert {row["scenario_id"] for row in rows} == {"scenario_001"}
    assert {row["turn_id"] for row in rows} == {"t1", "t2"}
    assert "target_turn" in rows[0]


def test_day6_formal_runner_preflight_only_does_not_create_run_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _formal_env(monkeypatch)
    from experiments import run_formal_experiment

    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "c1",
                        "user_input": "你好",
                        "expected": {
                            "task_type": "general_chat",
                            "accepted_agent_sets": [[]],
                            "accepted_tool_sets": [[]],
                            "forbidden_tools": [
                                "poi_search",
                                "weather_query",
                                "budget_calculator",
                            ],
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_root = tmp_path / "formal_runs"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_formal_experiment.py",
            "--benchmark",
            str(benchmark_path),
            "--output-dir",
            str(output_root),
            "--run-id",
            "preflight-only",
            "--preflight-only",
            "--skip-llm-config-check",
        ],
    )

    assert run_formal_experiment.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "passed"
    assert not (output_root / "preflight-only").exists()


def _formal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPERIMENT_STRICT_MODE", "true")
    monkeypatch.setenv("EXPERIMENT_DISABLE_CACHE", "true")
    monkeypatch.setenv("TRACE_SAVE_USER_MESSAGE", "false")
    monkeypatch.setenv("LLM_TEMPERATURE", "0")
