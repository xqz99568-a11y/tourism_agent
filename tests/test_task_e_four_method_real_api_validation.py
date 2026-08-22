import json
from pathlib import Path

from experiments.run_task_e_four_method_real_api_validation import (
    TASK_E_METHODS,
    _method_grid,
    _task_e_env_values,
    build_task_e_benchmark,
    build_task_e_report,
    render_task_e_report,
)


ROOT = Path(__file__).resolve().parents[1]


def test_task_e_benchmark_selects_fixed_twenty_cases_for_all_four_methods() -> None:
    benchmark = build_task_e_benchmark(ROOT / "experiments" / "ctp100_formal_v2.json")

    assert benchmark["schema_version"] == "ctp-task-e-four-method-real-api-benchmark-v1"
    assert benchmark["dataset_id"] == "task_e_four_method_real_api_20"
    assert benchmark["method_scope"] == list(TASK_E_METHODS)
    assert benchmark["case_count"] == 20
    assert benchmark["turn_count"] == 20
    assert benchmark["expected_raw_result_count"] == 80
    assert all("turns" not in case for case in benchmark["cases"])
    assert benchmark["selection_policy"]["coverage"]["task_type_counts"] == {
        "attraction_recommendation": 3,
        "budget_query": 4,
        "clarification": 3,
        "general_chat": 3,
        "trip_planning": 4,
        "weather_query": 3,
    }
    assert benchmark["source_benchmark"]["dataset_version"] == (
        "2026-08-21-formal-v3-runtime-control-freeze"
    )
    assert len(benchmark["source_benchmark"]["dataset_sha256"]) == 64


def test_task_e_benchmark_supports_targeted_case_id_subset() -> None:
    benchmark = build_task_e_benchmark(
        ROOT / "experiments" / "ctp100_formal_v2.json",
        case_ids=["ctp100_v2_031", "ctp100_v2_041"],
    )

    assert benchmark["case_count"] == 2
    assert benchmark["turn_count"] == 2
    assert benchmark["expected_raw_result_count"] == 8
    assert benchmark["selection_policy"]["fixed_case_ids"] == [
        "ctp100_v2_031",
        "ctp100_v2_041",
    ]
    assert benchmark["selection_policy"]["coverage"]["task_type_counts"] == {
        "budget_query": 1,
        "weather_query": 1,
    }


def test_task_e_report_passes_for_clean_four_method_grid(tmp_path: Path) -> None:
    run_dir = tmp_path / "task-e"
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True)
    case_ids = ["case_001", "case_002"]
    benchmark = {
        "dataset_id": "task_e_unit",
        "dataset_version": "unit",
        "case_count": 2,
        "turn_count": 2,
        "expected_raw_result_count": 8,
        "method_scope": list(TASK_E_METHODS),
        "selection_policy": {
            "fixed_case_ids": case_ids,
            "coverage": {"task_type_counts": {"general_chat": 2}},
        },
    }
    results = []
    for case_index, case_id in enumerate(case_ids):
        for method_index, method in enumerate(TASK_E_METHODS):
            results.append(
                {
                    "case_id": case_id,
                    "method": method,
                    "status": "completed",
                    "latency_ms": 1000.0 + method_index,
                    "hard_timeout_triggered": False,
                }
            )
            _write_trace(
                trace_dir / f"{case_id}_{method}.jsonl",
                case_id=case_id,
                method=method,
                provider="vectorengine_openai_compatible",
                mock=False,
                fallback=False,
                success=True,
                prompt_tokens=100 + case_index,
                completion_tokens=20 + method_index,
                total_tokens=120 + case_index + method_index,
                duration_ms=900 + method_index,
                tool_count=0 if method == "llm_direct" else 1,
                agent_run_count=0 if method == "llm_direct" else 1,
            )

    report = build_task_e_report(
        run_id="task-e-unit",
        run_dir=run_dir,
        benchmark_path=run_dir / "benchmark.json",
        benchmark_document=benchmark,
        runtime_config={
            "provider": "vectorengine_openai_compatible",
            "model": "gpt-test",
            "max_tokens": 4096,
            "timeout_seconds": 120,
            "hard_timeout_seconds": 600,
        },
        results=results,
        elapsed_seconds=8.0,
    )

    assert report["status"] == "passed"
    assert report["gate"]["failed_checks"] == []
    assert report["results"]["method_counts"] == {
        "adaptive_multi_agent": 2,
        "fixed_multi_agent": 2,
        "llm_direct": 2,
        "single_agent": 2,
    }
    assert report["method_grid"]["missing_count"] == 0
    assert report["trace_audit"]["llm_calls_by_method"] == {
        "adaptive_multi_agent": 2,
        "fixed_multi_agent": 2,
        "llm_direct": 2,
        "single_agent": 2,
    }
    assert report["token_usage"]["total_tokens"] == 976.0
    markdown = render_task_e_report(report)
    assert "Task E Four-Method Real API Validation Report" in markdown
    assert "| method_grid_complete | `True` |" in markdown


def test_task_e_report_fails_on_incomplete_grid_mock_fallback_and_timeout(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "task-e"
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True)
    _write_trace(
        trace_dir / "trace.jsonl",
        case_id="case_001",
        method="llm_direct",
        provider="mock",
        mock=True,
        fallback=True,
        success=True,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        duration_ms=100,
        tool_count=0,
        agent_run_count=0,
    )

    report = build_task_e_report(
        run_id="task-e-failed",
        run_dir=run_dir,
        benchmark_path=run_dir / "benchmark.json",
        benchmark_document={
            "dataset_id": "unit",
            "turn_count": 1,
            "expected_raw_result_count": 4,
            "method_scope": list(TASK_E_METHODS),
            "selection_policy": {"fixed_case_ids": ["case_001"]},
        },
        runtime_config={"provider": "vectorengine_openai_compatible", "model": "gpt-test"},
        results=[
            {
                "case_id": "case_001",
                "method": "llm_direct",
                "status": "failed",
                "error": "experiment result hard timeout",
                "latency_ms": 300000.0,
                "hard_timeout_triggered": True,
            }
        ],
        elapsed_seconds=300.0,
    )

    assert report["status"] == "failed"
    assert set(report["gate"]["failed_checks"]) >= {
        "expected_result_count",
        "all_four_methods_present",
        "method_grid_complete",
        "all_results_completed",
        "no_mock_calls",
        "no_fallback_calls",
        "no_hard_timeout",
    }
    assert report["method_grid"]["missing_count"] == 3
    assert report["results"]["failed_results"][0]["method"] == "llm_direct"


def test_task_e_report_accepts_clarification_as_success_status(tmp_path: Path) -> None:
    run_dir = tmp_path / "task-e-clarification"
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True)
    results = []
    for method in TASK_E_METHODS:
        results.append(
            {
                "case_id": "case_001",
                "method": method,
                "status": "clarification",
                "latency_ms": 1000.0,
                "hard_timeout_triggered": False,
            }
        )
        _write_trace(
            trace_dir / f"case_001_{method}.jsonl",
            case_id="case_001",
            method=method,
            provider="vectorengine_openai_compatible",
            mock=False,
            fallback=False,
            success=True,
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            duration_ms=900,
            tool_count=0 if method == "llm_direct" else 1,
            agent_run_count=0 if method == "llm_direct" else 1,
        )

    report = build_task_e_report(
        run_id="task-e-clarification",
        run_dir=run_dir,
        benchmark_path=run_dir / "benchmark.json",
        benchmark_document={
            "dataset_id": "task_e_unit",
            "dataset_version": "unit",
            "case_count": 1,
            "turn_count": 1,
            "expected_raw_result_count": 4,
            "method_scope": list(TASK_E_METHODS),
            "selection_policy": {"fixed_case_ids": ["case_001"]},
        },
        runtime_config={"provider": "vectorengine_openai_compatible", "model": "gpt-test"},
        results=results,
        elapsed_seconds=4.0,
    )

    assert report["status"] == "passed"
    assert report["results"]["status_counts"] == {"clarification": 4}
    assert report["results"]["failed_results"] == []


def test_task_e_report_warns_but_does_not_fail_on_contained_llm_call_failure(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "task-e-contained-llm-failure"
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True)
    results = []
    for method in TASK_E_METHODS:
        results.append(
            {
                "case_id": "case_001",
                "method": method,
                "status": "completed",
                "latency_ms": 1000.0,
                "hard_timeout_triggered": False,
            }
        )
        _write_trace(
            trace_dir / f"case_001_{method}.jsonl",
            case_id="case_001",
            method=method,
            provider="vectorengine_openai_compatible",
            mock=False,
            fallback=False,
            success=method != "adaptive_multi_agent",
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            duration_ms=900,
            tool_count=0 if method == "llm_direct" else 1,
            agent_run_count=0 if method == "llm_direct" else 1,
        )

    report = build_task_e_report(
        run_id="task-e-contained-llm-failure",
        run_dir=run_dir,
        benchmark_path=run_dir / "benchmark.json",
        benchmark_document={
            "dataset_id": "task_e_unit",
            "dataset_version": "unit",
            "case_count": 1,
            "turn_count": 1,
            "expected_raw_result_count": 4,
            "method_scope": list(TASK_E_METHODS),
            "selection_policy": {"fixed_case_ids": ["case_001"]},
        },
        runtime_config={"provider": "vectorengine_openai_compatible", "model": "gpt-test"},
        results=results,
        elapsed_seconds=4.0,
    )

    assert report["status"] == "passed"
    assert report["trace_audit"]["failed_llm_call_count"] == 1
    assert report["gate"]["failed_checks"] == []
    assert report["warnings"][0]["code"] == "failed_llm_calls_recorded"


def test_task_e_env_values_force_strict_four_method_real_api_runtime() -> None:
    env = _task_e_env_values(
        {
            "base_url": "https://api.vectorengine.ai/v1",
            "model": "gpt-5-mini",
            "temperature": 0.0,
            "max_tokens": 4096,
            "timeout_seconds": 120,
            "retry_max_attempts": 3,
            "reasoning_effort": "minimal",
            "hard_timeout_seconds": 600,
        }
    )

    assert env["EXPERIMENT_STRICT_MODE"] == "true"
    assert env["EXPERIMENT_DISABLE_CACHE"] == "true"
    assert env["TRACE_SAVE_USER_MESSAGE"] == "false"
    assert env["LLM_BASE_URL"] == "https://api.vectorengine.ai/v1"
    assert env["LLM_MODEL"] == "gpt-5-mini"
    assert env["LLM_MAX_TOKENS"] == "4096"
    assert env["LLM_TIMEOUT"] == "120"
    assert env["EXPERIMENT_RESULT_HARD_TIMEOUT_SECONDS"] == "600"
    assert env["EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER"] == "true"


def test_task_e_method_grid_detects_missing_and_duplicate_cells() -> None:
    grid = _method_grid(
        [
            {"case_id": "case_001", "method": "llm_direct"},
            {"case_id": "case_001", "method": "llm_direct"},
            {"case_id": "case_001", "method": "single_agent"},
        ],
        expected_case_ids=["case_001"],
        expected_methods=["llm_direct", "single_agent", "fixed_multi_agent"],
    )

    assert grid["missing"] == [{"case_id": "case_001", "method": "fixed_multi_agent"}]
    assert grid["duplicates"] == [
        {"case_id": "case_001", "method": "llm_direct", "count": 2}
    ]


def _write_trace(
    path: Path,
    *,
    case_id: str,
    method: str,
    provider: str,
    mock: bool,
    fallback: bool,
    success: bool,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    duration_ms: float,
    tool_count: int,
    agent_run_count: int,
) -> None:
    record = {
        "request_id": path.stem,
        "case_id": case_id,
        "method": method,
        "status": "completed" if success else "failed",
        "llm_calls": [
            {
                "provider": provider,
                "model": "gpt-test",
                "mock": mock,
                "mock_used": mock,
                "fallback": fallback,
                "fallback_used": fallback,
                "success": success,
                "duration_ms": duration_ms,
                "prompt_version": "ctp-structured-llm-output-prompts-v2",
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
                            "success": success,
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
            {
                "tool_name": "poi_search",
                "status": "completed",
                "success": True,
            }
            for _ in range(tool_count)
        ],
        "agent_runs": [
            {
                "agent_name": "single_agent" if method == "single_agent" else "attraction",
                "status": "completed",
            }
            for _ in range(agent_run_count)
        ],
        "tool_call_count": tool_count,
        "agent_call_count": agent_run_count,
    }
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
