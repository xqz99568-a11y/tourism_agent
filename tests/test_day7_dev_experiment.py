import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.day7_dev_experiment_gate import (
    DAY7_DEV_EXPERIMENT_GATE_SCHEMA_VERSION,
    _multi_turn_state_isolation,
    build_day7_dev_experiment_gate,
)
from app.core.experiment_runner import ExperimentRunner
from experiments.run_day7_dev_experiment import run_day7_dev_experiment
from experiments.run_day7_m3_ablation import run_day7_m3_ablation
from tests.test_day7_pilot import _fake_weather_handler


def test_day7_dev_experiment_writes_104_style_gate_for_mini_dataset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _dev_env(monkeypatch)
    benchmark_path = _write_dev_mini_benchmark(tmp_path / "day7_dev_mini.json")

    payload = run_day7_dev_experiment(
        benchmark_path=benchmark_path,
        output_dir=tmp_path / "day7_dev_runs",
        run_id="day7-dev-unit",
        expected_case_count=2,
        expected_turn_count=3,
        expected_scenario_case_count=1,
        require_llm_config=False,
        runner_kwargs={
            "method_handlers": {
                method: _fake_weather_handler
                for method in ExperimentRunner.METHODS
            }
        },
    )

    assert payload["status"] == "completed"
    assert payload["result_count"] == 12
    assert payload["expected_count"] == 12
    assert payload["dev_gate_status"] == "passed"
    assert payload["paper_claims_allowed"] is False

    for key in (
        "preflight",
        "csv",
        "json",
        "summary",
        "paper_tables",
        "manifest",
        "day7_dev_gate",
        "day7_dev_report",
    ):
        assert Path(payload[key]).exists()

    gate = json.loads(Path(payload["day7_dev_gate"]).read_text(encoding="utf-8"))
    assert gate["schema_version"] == DAY7_DEV_EXPERIMENT_GATE_SCHEMA_VERSION
    assert gate["status"] == "passed"
    assert gate["expected"]["raw_result_count"] == 12
    assert gate["actual"]["raw_result_count"] == 12
    assert gate["method_result_counts"]["counts"] == {
        "adaptive_multi_agent": 3,
        "fixed_multi_agent": 3,
        "llm_direct": 3,
        "single_agent": 3,
    }
    assert gate["raw_turn_pairing"]["complete"] is True
    assert gate["raw_turn_pairing"]["unit_count"] == 3
    assert gate["trace_summary"]["trace_file_count"] == 12
    assert gate["trace_summary"]["loaded_trace_count"] == 12
    assert gate["trace_summary"]["mock_llm_call_count"] == 0
    assert gate["trace_summary"]["fallback_llm_call_count"] == 0
    assert gate["trace_summary"]["cache_hit_count"] == 0
    assert gate["runtime_audit"]["consistent_with_manifest"] is True
    assert gate["runtime_audit"]["matches_day7_max_tokens_protocol"] is True
    assert gate["checks"]["runtime_matches_day7_max_tokens_protocol"] is True
    assert gate["expected"]["max_tokens"] == 4096
    assert gate["output_length_risk"]["completion_token_cap_hit_rate"] == 0.0
    assert gate["output_length_risk"]["empty_and_token_capped_call_count"] == 0
    assert gate["checks"]["completion_token_cap_hit_rate_below_limit"] is True
    assert gate["checks"]["no_empty_outputs_at_token_cap"] is True
    assert gate["field_completeness"]["token_latency_complete"] is True
    assert gate["field_completeness"]["cost_complete_for_llm_rows"] is True
    assert gate["multi_turn_state_isolation"]["passed"] is True
    assert gate["multi_turn_state_isolation"]["scenario_case_count"] == 1
    assert gate["multi_turn_state_isolation"]["checked_method_scenario_count"] == 4
    assert gate["infrastructure_failures"]["failure_rate"] == 0.0

    rows = list(csv.DictReader(Path(payload["csv"]).open(encoding="utf-8-sig")))
    assert len(rows) == 12
    scenario_rows = [row for row in rows if row["scenario_id"] == "dev_scenario_state"]
    assert scenario_rows
    assert "previous_state_is_method_local" in rows[0]
    assert all(row["previous_state_has_evaluation"] == "False" for row in scenario_rows)
    assert all(row["previous_state_has_metrics"] == "False" for row in scenario_rows)

    manifest = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
    assert manifest["day7_dev_experiment"]["status"] == "passed"
    assert manifest["day7_dev_experiment"]["paper_claims_allowed"] is False
    assert manifest["results"]["day7_dev_gate"] == payload["day7_dev_gate"]
    assert manifest["results"]["day7_dev_report"] == payload["day7_dev_report"]
    manifest_hash = next(
        item["sha256"]
        for item in gate["artifact_index"]["files"]
        if item["key"] == "manifest"
    )
    assert manifest_hash == _file_sha256(Path(payload["manifest"]))


def test_day7_dev_experiment_forces_frozen_max_tokens_over_stale_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _dev_env(monkeypatch)
    monkeypatch.setenv("LLM_MAX_TOKENS", "1024")
    benchmark_path = _write_dev_mini_benchmark(tmp_path / "day7_dev_mini.json")

    payload = run_day7_dev_experiment(
        benchmark_path=benchmark_path,
        output_dir=tmp_path / "day7_dev_runs",
        run_id="day7-dev-forced-runtime",
        expected_case_count=2,
        expected_turn_count=3,
        expected_scenario_case_count=1,
        require_llm_config=False,
        runner_kwargs={
            "method_handlers": {
                method: _fake_weather_handler
                for method in ExperimentRunner.METHODS
            }
        },
    )

    assert payload["status"] == "completed"
    gate = json.loads(Path(payload["day7_dev_gate"]).read_text(encoding="utf-8"))
    manifest = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
    assert gate["runtime_audit"]["manifest_runtime"]["max_tokens"] == 4096
    assert gate["runtime_audit"]["matches_day7_max_tokens_protocol"] is True
    assert manifest["runtime_config"]["max_tokens"] == 4096
    assert manifest["runtime_config"]["deterministic_research_final_answer"] is True
    assert gate["checks"]["deterministic_research_final_answer_recorded"] is True


def test_day7_m3_ablation_writes_no_normalizer_report_for_mini_dataset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _dev_env(monkeypatch)
    benchmark_path = _write_dev_mini_benchmark(tmp_path / "day7_dev_mini.json")

    payload = run_day7_m3_ablation(
        benchmark_path=benchmark_path,
        output_dir=tmp_path / "day7_m3_ablation",
        run_id="day7-m3-ablation-unit",
        expected_case_count=2,
        expected_turn_count=3,
        expected_scenario_case_count=1,
        require_llm_config=False,
        runner_kwargs={
            "method_handlers": {
                "adaptive_multi_agent": _fake_weather_handler,
            }
        },
    )

    assert payload["status"] == "completed"
    assert payload["result_count"] == 3
    assert payload["expected_count"] == 3
    assert payload["dev_gate_status"] == "passed"
    assert payload["ablation_status"] == "passed"
    assert Path(payload["ablation_report_json"]).exists()

    manifest = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
    report = json.loads(Path(payload["ablation_report_json"]).read_text(encoding="utf-8"))
    assert manifest["methods"] == ["adaptive_multi_agent"]
    assert manifest["method_controls"]["research_agent_decision_normalizer_enabled"] is False
    assert report["controlled_change"]["name"] == "M3-no-decision-normalizer"
    assert report["checks"]["manifest_decision_normalizer_disabled"] is True
    assert report["checks"]["deterministic_normalizer_not_used"] is True
    gate = json.loads(Path(payload["day7_dev_gate"]).read_text(encoding="utf-8"))
    manifest_hash = next(
        item["sha256"]
        for item in gate["artifact_index"]["files"]
        if item["key"] == "manifest"
    )
    assert manifest_hash == _file_sha256(Path(payload["manifest"]))


def test_day8_single_turn_dev_gate_treats_state_isolation_as_not_applicable() -> None:
    state = _multi_turn_state_isolation(
        [
            {"case_id": "single-1", "method": "llm_direct"},
            {"case_id": "single-1", "method": "single_agent"},
            {"case_id": "single-1", "method": "fixed_multi_agent"},
            {"case_id": "single-1", "method": "adaptive_multi_agent"},
        ],
        list(ExperimentRunner.METHODS),
    )

    assert state["passed"] is True
    assert state["applicable"] is False
    assert state["scenario_case_count"] == 0
    assert state["violation_count"] == 0


def test_day7_dev_gate_fails_without_state_isolation_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _dev_env(monkeypatch)
    benchmark_path = _write_dev_mini_benchmark(tmp_path / "day7_dev_mini.json")
    payload = run_day7_dev_experiment(
        benchmark_path=benchmark_path,
        output_dir=tmp_path / "day7_dev_runs",
        run_id="day7-dev-state-fail",
        expected_case_count=2,
        expected_turn_count=3,
        expected_scenario_case_count=1,
        require_llm_config=False,
        runner_kwargs={
            "method_handlers": {
                method: _fake_weather_handler
                for method in ExperimentRunner.METHODS
            }
        },
    )
    results_path = Path(payload["json"])
    results = json.loads(results_path.read_text(encoding="utf-8"))
    for result in results:
        for key in (
            "previous_state_provided",
            "previous_state_is_method_local",
            "previous_state_is_prior_turn",
            "previous_state_has_evaluation",
            "previous_state_has_metrics",
        ):
            result.pop(key, None)
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    gate = build_day7_dev_experiment_gate(
        Path(payload["output_dir"]),
        expected_case_count=2,
        expected_turn_count=3,
        expected_scenario_case_count=1,
    )

    assert gate["status"] == "failed"
    assert "multi_turn_state_isolation_passed" in gate["failed_checks"]


def test_day7_dev_gate_blocks_1024_empty_token_capped_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _dev_env(monkeypatch)
    benchmark_path = _write_dev_mini_benchmark(tmp_path / "day7_dev_mini.json")
    payload = run_day7_dev_experiment(
        benchmark_path=benchmark_path,
        output_dir=tmp_path / "day7_dev_runs",
        run_id="day7-dev-token-cap-fail",
        expected_case_count=2,
        expected_turn_count=3,
        expected_scenario_case_count=1,
        require_llm_config=False,
        runner_kwargs={
            "method_handlers": {
                method: _fake_weather_handler
                for method in ExperimentRunner.METHODS
            }
        },
    )
    run_dir = Path(payload["output_dir"])
    _rewrite_run_as_1024_empty_token_capped(run_dir)

    gate = build_day7_dev_experiment_gate(
        run_dir,
        expected_case_count=2,
        expected_turn_count=3,
        expected_scenario_case_count=1,
    )

    assert gate["status"] == "failed"
    assert "runtime_matches_day7_max_tokens_protocol" in gate["failed_checks"]
    assert "completion_token_cap_hit_rate_below_limit" in gate["failed_checks"]
    assert "no_empty_outputs_at_token_cap" in gate["failed_checks"]
    assert gate["runtime_audit"]["matches_day7_max_tokens_protocol"] is False
    assert gate["output_length_risk"]["completion_token_cap_hit_rate"] == 1.0
    assert gate["output_length_risk"]["empty_and_token_capped_call_count"] == 12


def test_day7_dev_preflight_only_does_not_create_run_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _dev_env(monkeypatch)
    benchmark_path = _write_dev_mini_benchmark(tmp_path / "day7_dev_mini.json")

    payload = run_day7_dev_experiment(
        benchmark_path=benchmark_path,
        output_dir=tmp_path / "day7_dev_runs",
        run_id="day7-dev-preflight",
        expected_case_count=2,
        expected_turn_count=3,
        expected_scenario_case_count=1,
        preflight_only=True,
        require_llm_config=False,
    )

    assert payload["status"] == "preflight_passed"
    assert payload["expected_count"] == 12
    assert not Path(payload["output_dir"]).exists()


def test_day7_dev_experiment_rejects_repeats_above_one(tmp_path: Path) -> None:
    benchmark_path = _write_dev_mini_benchmark(tmp_path / "day7_dev_mini.json")

    with pytest.raises(ValueError, match="requires repeats=1"):
        run_day7_dev_experiment(
            benchmark_path=benchmark_path,
            output_dir=tmp_path / "day7_dev_runs",
            repeats=2,
            expected_case_count=2,
            expected_turn_count=3,
            expected_scenario_case_count=1,
            require_llm_config=False,
        )


def _write_dev_mini_benchmark(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "ctp-benchmark-v1",
                "dataset_id": "day7_dev_unit",
                "dataset_version": "2026-07-31-zh",
                "split": "development",
                "cases": [
                    {
                        "case_id": "dev_single_weather",
                        "user_input": "请只查询北京2026年8月6日开始两天的天气预报，别推荐景点。",
                        "expected": {
                            "task_type": "weather_query",
                            "destination": "beijing",
                            "start_date": "2026-08-06",
                            "duration_days": 2,
                            "required_tools": ["weather_query"],
                            "accepted_agent_sets": [["weather"]],
                            "accepted_tool_sets": [["weather_query"]],
                        },
                    },
                    {
                        "case_id": "dev_scenario_state",
                        "turns": [
                            {
                                "turn_id": "t1_full_plan",
                                "user_input": (
                                    "先为2个人规划2026年8月13日出发的杭州两天游，预算5200元，"
                                    "要有景点、天气、行程和预算。"
                                ),
                                "expected": {
                                    "task_type": "trip_planning",
                                    "required_tools": [
                                        "poi_search",
                                        "weather_query",
                                        "budget_calculator",
                                    ],
                                    "accepted_agent_sets": [
                                        ["attraction", "weather", "itinerary", "budget"]
                                    ],
                                    "accepted_tool_sets": [
                                        [
                                            "poi_search",
                                            "weather_query",
                                            "budget_calculator",
                                        ]
                                    ],
                                    "hard_constraints": {
                                        "destination": "hangzhou",
                                        "start_date": "2026-08-13",
                                        "duration_days": 2,
                                        "people_count": 2,
                                        "min_attractions": 3,
                                        "max_pois_per_day": 2,
                                        "budget_limit": 5200,
                                    },
                                },
                            },
                            {
                                "turn_id": "t2_people_change",
                                "user_input": (
                                    "把人数改成3个人，只重新计算预算，杭州、2026年8月13日"
                                    "和两天行程都不变。"
                                ),
                                "expected": {
                                    "task_type": "budget_query",
                                    "changed_slots": ["people_count"],
                                    "preserved_slots": [
                                        "destination",
                                        "start_date",
                                        "duration_days",
                                        "budget_amount",
                                    ],
                                    "required_tools": ["budget_calculator"],
                                    "accepted_agent_sets": [["budget"]],
                                    "accepted_tool_sets": [["budget_calculator"]],
                                    "hard_constraints": {
                                        "destination": "hangzhou",
                                        "start_date": "2026-08-13",
                                        "duration_days": 2,
                                        "people_count": 3,
                                        "budget_limit": 5200,
                                    },
                                },
                            },
                        ],
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _dev_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPERIMENT_STRICT_MODE", "true")
    monkeypatch.setenv("EXPERIMENT_DISABLE_CACHE", "true")
    monkeypatch.setenv("TRACE_SAVE_USER_MESSAGE", "false")
    monkeypatch.setenv("LLM_MODEL", "day7-pilot-unit-model")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.vectorengine.ai/v1")
    monkeypatch.setenv("LLM_TEMPERATURE", "0")
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
    monkeypatch.setenv("LLM_TIMEOUT", "60")
    monkeypatch.setenv("LLM_RETRY_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "minimal")


def _rewrite_run_as_1024_empty_token_capped(run_dir: Path) -> None:
    results = json.loads((run_dir / "benchmark_results.json").read_text(encoding="utf-8"))
    for result in results:
        trace_path = Path(str(result["trace_file"]))
        if not trace_path.is_absolute():
            trace_path = run_dir / trace_path
        trace = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
        for call in trace.get("llm_calls") or []:
            if not isinstance(call, dict):
                continue
            call["max_tokens"] = 1024
            call["output_chars"] = 0
            options = call.setdefault("request_options", {})
            options["max_tokens"] = 1024
            usage = call.setdefault("usage", {})
            prompt_tokens = int(usage.get("prompt_tokens") or 9)
            usage["prompt_tokens"] = prompt_tokens
            usage["completion_tokens"] = 1024
            usage["total_tokens"] = prompt_tokens + 1024
        trace_path.write_text(
            json.dumps(trace, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    manifest_path = run_dir / "experiment_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["max_tokens"] = 1024
    manifest.setdefault("runtime_config", {})["max_tokens"] = 1024
    manifest.setdefault("model_config", {})["max_tokens"] = 1024
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
