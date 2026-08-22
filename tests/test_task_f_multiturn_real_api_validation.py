import json
from pathlib import Path

from experiments.run_task_f_multiturn_real_api_validation import (
    TASK_F_CUSTOM_DESTINATION_SCENARIO_ID,
    TASK_F_METHODS,
    _task_f_env_values,
    build_task_f_benchmark,
    build_task_f_report,
    render_task_f_report,
)


ROOT = Path(__file__).resolve().parents[1]


def test_task_f_benchmark_builds_m2_m3_multiturn_set_with_custom_destination() -> None:
    benchmark = build_task_f_benchmark(ROOT / "experiments" / "ctp100_formal_v2.json")

    assert benchmark["schema_version"] == "ctp-task-f-multiturn-real-api-benchmark-v1"
    assert benchmark["dataset_id"] == "task_f_multiturn_real_api_m2_m3"
    assert benchmark["method_scope"] == list(TASK_F_METHODS)
    assert benchmark["case_count"] == 6
    assert benchmark["turn_count"] == 12
    assert benchmark["expected_raw_result_count"] == 24
    assert benchmark["source_benchmark"]["dataset_version"] == (
        "2026-08-21-formal-v3-runtime-control-freeze"
    )
    assert len(benchmark["source_benchmark"]["dataset_sha256"]) == 64
    scenario_ids = benchmark["selection_policy"]["fixed_scenario_ids"]
    assert TASK_F_CUSTOM_DESTINATION_SCENARIO_ID in scenario_ids
    custom = next(
        case
        for case in benchmark["cases"]
        if case["scenario_id"] == TASK_F_CUSTOM_DESTINATION_SCENARIO_ID
    )
    assert custom["task_f_only"] is True
    assert custom["turns"][1]["expected"]["changed_slots"] == ["destination"]
    assert benchmark["selection_policy"]["coverage"]["changed_slot_counts"][
        "destination"
    ] == 1


def test_task_f_benchmark_supports_targeted_existing_and_custom_subset() -> None:
    benchmark = build_task_f_benchmark(
        ROOT / "experiments" / "ctp100_formal_v2.json",
        scenario_ids=["ctp100_v2_051", TASK_F_CUSTOM_DESTINATION_SCENARIO_ID],
    )

    assert benchmark["case_count"] == 2
    assert benchmark["turn_count"] == 4
    assert benchmark["expected_raw_result_count"] == 8
    assert benchmark["selection_policy"]["fixed_scenario_ids"] == (
        "ctp100_v2_051",
        TASK_F_CUSTOM_DESTINATION_SCENARIO_ID,
    )


def test_task_f_report_passes_for_clean_multiturn_m2_m3_grid(tmp_path: Path) -> None:
    run_dir = tmp_path / "task-f"
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True)
    benchmark = _unit_benchmark()
    results = []
    for scenario_id in ["ctp100_v2_051", TASK_F_CUSTOM_DESTINATION_SCENARIO_ID]:
        for turn_index, turn_id in enumerate(["t1", "t2"]):
            for method in TASK_F_METHODS:
                result = _result(
                    scenario_id=scenario_id,
                    turn_id=turn_id,
                    turn_index=turn_index,
                    method=method,
                    previous_state_provided=turn_index > 0,
                    m3_reused_agents=(
                        ["attraction", "itinerary"]
                        if scenario_id == "ctp100_v2_051"
                        else []
                    ),
                    m3_invalidated_agents=(
                        ["budget"]
                        if scenario_id == "ctp100_v2_051"
                        else ["attraction", "weather", "itinerary", "budget"]
                    ),
                    m3_decision_reasons=(
                        ["budget_changed_budget_only"]
                        if scenario_id == "ctp100_v2_051"
                        else ["destination_changed_invalidate_all"]
                    ),
                )
                results.append(result)
                _write_trace(
                    trace_dir / f"{scenario_id}_{turn_id}_{method}.jsonl",
                    scenario_id=scenario_id,
                    turn_id=turn_id,
                    method=method,
                    prompt_tokens=100,
                    completion_tokens=20,
                    total_tokens=120,
                    tool_count=1,
                    agent_run_count=1,
                )

    report = build_task_f_report(
        run_id="task-f-unit",
        run_dir=run_dir,
        benchmark_path=run_dir / "benchmark.json",
        benchmark_document=benchmark,
        runtime_config={"provider": "vectorengine_openai_compatible", "model": "gpt-test"},
        results=results,
        elapsed_seconds=8.0,
    )

    assert report["status"] == "passed"
    assert report["gate"]["failed_checks"] == []
    assert report["turn_method_grid"]["missing_count"] == 0
    assert report["second_turn_reuse_audit"]["m2_reuse_violation_count"] == 0
    assert report["second_turn_reuse_audit"]["m3_expectation_violation_count"] == 0
    assert report["second_turn_reuse_audit"]["destination_change_invalidation_passed"] is True
    assert report["decision_normalizer"]["decision_normalizer_recovery_count"] == 8
    markdown = render_task_f_report(report)
    assert "Task F Multi-Turn Real API Validation Report" in markdown
    assert "| m3_second_turn_reuse_expectations_met | `True` |" in markdown


def test_task_f_report_fails_when_destination_change_reuses_old_agents(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "task-f-fail"
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True)
    benchmark = _unit_benchmark()
    results = []
    for scenario_id in ["ctp100_v2_051", TASK_F_CUSTOM_DESTINATION_SCENARIO_ID]:
        for turn_index, turn_id in enumerate(["t1", "t2"]):
            for method in TASK_F_METHODS:
                results.append(
                    _result(
                        scenario_id=scenario_id,
                        turn_id=turn_id,
                        turn_index=turn_index,
                        method=method,
                        previous_state_provided=turn_index > 0,
                        m3_reused_agents=["attraction"] if scenario_id == TASK_F_CUSTOM_DESTINATION_SCENARIO_ID else [],
                        m3_invalidated_agents=[] if scenario_id == TASK_F_CUSTOM_DESTINATION_SCENARIO_ID else ["budget"],
                        m3_decision_reasons=["wrong_reuse"],
                    )
                )
                _write_trace(
                    trace_dir / f"{scenario_id}_{turn_id}_{method}.jsonl",
                    scenario_id=scenario_id,
                    turn_id=turn_id,
                    method=method,
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                    tool_count=1,
                    agent_run_count=1,
                )

    report = build_task_f_report(
        run_id="task-f-fail",
        run_dir=run_dir,
        benchmark_path=run_dir / "benchmark.json",
        benchmark_document=benchmark,
        runtime_config={"provider": "vectorengine_openai_compatible", "model": "gpt-test"},
        results=results,
        elapsed_seconds=8.0,
    )

    assert report["status"] == "failed"
    assert "m3_destination_change_invalidates_all" in report["gate"]["failed_checks"]
    assert "m3_second_turn_reuse_expectations_met" in report["gate"]["failed_checks"]


def test_task_f_report_fails_when_second_turn_lacks_previous_state(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "task-f-no-prev"
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True)
    benchmark = _unit_benchmark()
    results = []
    for scenario_id in ["ctp100_v2_051", TASK_F_CUSTOM_DESTINATION_SCENARIO_ID]:
        for turn_index, turn_id in enumerate(["t1", "t2"]):
            for method in TASK_F_METHODS:
                results.append(
                    _result(
                        scenario_id=scenario_id,
                        turn_id=turn_id,
                        turn_index=turn_index,
                        method=method,
                        previous_state_provided=False,
                    )
                )
                _write_trace(
                    trace_dir / f"{scenario_id}_{turn_id}_{method}.jsonl",
                    scenario_id=scenario_id,
                    turn_id=turn_id,
                    method=method,
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                    tool_count=1,
                    agent_run_count=1,
                )

    report = build_task_f_report(
        run_id="task-f-no-prev",
        run_dir=run_dir,
        benchmark_path=run_dir / "benchmark.json",
        benchmark_document=benchmark,
        runtime_config={"provider": "vectorengine_openai_compatible", "model": "gpt-test"},
        results=results,
        elapsed_seconds=8.0,
    )

    assert report["status"] == "failed"
    assert "second_turn_previous_state_present" in report["gate"]["failed_checks"]


def test_task_f_env_values_force_strict_multiturn_real_api_runtime() -> None:
    env = _task_f_env_values(
        {
            "base_url": "https://api.vectorengine.ai/v1",
            "model": "gpt-5-mini",
            "temperature": 0.0,
            "max_tokens": 4096,
            "timeout_seconds": 120,
            "retry_max_attempts": 3,
            "reasoning_effort": "minimal",
            "hard_timeout_seconds": 900,
        }
    )

    assert env["EXPERIMENT_STRICT_MODE"] == "true"
    assert env["EXPERIMENT_DISABLE_CACHE"] == "true"
    assert env["TRACE_SAVE_USER_MESSAGE"] == "false"
    assert env["LLM_BASE_URL"] == "https://api.vectorengine.ai/v1"
    assert env["LLM_MODEL"] == "gpt-5-mini"
    assert env["LLM_MAX_TOKENS"] == "4096"
    assert env["LLM_TIMEOUT"] == "120"
    assert env["EXPERIMENT_RESULT_HARD_TIMEOUT_SECONDS"] == "900"
    assert env["EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER"] == "true"


def _unit_benchmark() -> dict:
    return {
        "dataset_id": "task_f_unit",
        "dataset_version": "unit",
        "case_count": 2,
        "turn_count": 4,
        "expected_raw_result_count": 8,
        "method_scope": list(TASK_F_METHODS),
        "selection_policy": {
            "fixed_scenario_ids": (
                "ctp100_v2_051",
                TASK_F_CUSTOM_DESTINATION_SCENARIO_ID,
            ),
            "scenario_turns": [
                {"scenario_id": "ctp100_v2_051", "turn_ids": ["t1", "t2"]},
                {
                    "scenario_id": TASK_F_CUSTOM_DESTINATION_SCENARIO_ID,
                    "turn_ids": ["t1", "t2"],
                },
            ],
            "m3_second_turn_expectations": {
                "ctp100_v2_051": {
                    "required_reused_agents": ["attraction", "itinerary"],
                    "required_invalidated_agents": ["budget"],
                    "forbidden_reused_agents": ["budget"],
                    "required_decision_reasons": ["budget_changed_budget_only"],
                },
                TASK_F_CUSTOM_DESTINATION_SCENARIO_ID: {
                    "required_reused_agents": [],
                    "required_invalidated_agents": [
                        "attraction",
                        "weather",
                        "itinerary",
                        "budget",
                    ],
                    "forbidden_reused_agents": [
                        "attraction",
                        "weather",
                        "itinerary",
                        "budget",
                    ],
                    "required_decision_reasons": ["destination_changed_invalidate_all"],
                },
            },
        },
    }


def _result(
    *,
    scenario_id: str,
    turn_id: str,
    turn_index: int,
    method: str,
    previous_state_provided: bool,
    m3_reused_agents: list[str] | None = None,
    m3_invalidated_agents: list[str] | None = None,
    m3_decision_reasons: list[str] | None = None,
) -> dict:
    metadata = {}
    metrics = {}
    if method == "fixed_multi_agent":
        metadata["fixed_template_scheduler"] = {
            "state_reuse": False,
            "decision": {"reused_agents": []},
        }
    if method == "adaptive_multi_agent":
        metrics.update(
            {
                "m3_reused_agents": m3_reused_agents or [],
                "m3_invalidated_agents": m3_invalidated_agents or [],
                "m3_decision_reasons": m3_decision_reasons or [],
            }
        )
    if method in TASK_F_METHODS:
        metadata["agent_decision_audit"] = {
            "attraction": {
                "status": "completed",
                "reused": False,
                "decision_source": "llm",
                "decision_fallback_used": False,
                "llm_decision_error_count": 0,
            },
            "itinerary": {
                "status": "completed",
                "reused": False,
                "decision_source": "deterministic_evidence_normalizer",
                "decision_fallback_used": True,
                "llm_decision_error_count": 1,
            },
        }
    return {
        "case_id": scenario_id,
        "scenario_id": scenario_id,
        "turn_id": turn_id,
        "turn_index": turn_index,
        "method": method,
        "status": "completed",
        "latency_ms": 1000.0,
        "hard_timeout_triggered": False,
        "previous_state_provided": previous_state_provided,
        "output": {"metadata": metadata},
        "metrics": metrics,
    }


def _write_trace(
    path: Path,
    *,
    scenario_id: str,
    turn_id: str,
    method: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    tool_count: int,
    agent_run_count: int,
) -> None:
    record = {
        "request_id": path.stem,
        "case_id": scenario_id,
        "scenario_id": scenario_id,
        "turn_id": turn_id,
        "method": method,
        "status": "completed",
        "llm_calls": [
            {
                "provider": "vectorengine_openai_compatible",
                "model": "gpt-test",
                "mock": False,
                "mock_used": False,
                "fallback": False,
                "fallback_used": False,
                "success": True,
                "duration_ms": 900,
                "prompt_version": "ctp-research-agent-prompts-v2",
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                },
                "retry": {
                    "attempt_count": 1,
                    "attempts": [
                        {
                            "attempt_index": 1,
                            "success": True,
                            "finish_reason": "stop",
                        }
                    ],
                },
                "estimated_cost": 0.02,
                "standardized_estimated_cost": 0.02,
                "actual_cost": None,
            }
        ],
        "tool_calls": [
            {"tool_name": "poi_search", "status": "completed", "success": True}
            for _ in range(tool_count)
        ],
        "agent_runs": [
            {"agent_name": "attraction", "status": "completed"}
            for _ in range(agent_run_count)
        ],
        "tool_call_count": tool_count,
        "agent_call_count": agent_run_count,
    }
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
