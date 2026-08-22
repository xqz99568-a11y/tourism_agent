import json
from pathlib import Path

from experiments.run_task_d_m0_real_api_validation import (
    TASK_D_CASE_IDS,
    TASK_D_METHOD,
    _task_d_env_values,
    build_task_d_benchmark,
    build_task_d_report,
    render_task_d_report,
)


ROOT = Path(__file__).resolve().parents[1]


def test_task_d_benchmark_selects_fixed_twenty_single_turn_cases() -> None:
    benchmark = build_task_d_benchmark(ROOT / "experiments" / "ctp100_formal_v2.json")

    assert benchmark["schema_version"] == "ctp-task-d-m0-real-api-benchmark-v1"
    assert benchmark["dataset_id"] == "task_d_m0_real_api_20"
    assert benchmark["method_scope"] == ["llm_direct"]
    assert benchmark["case_count"] == 20
    assert benchmark["turn_count"] == 20
    assert [case["case_id"] for case in benchmark["cases"]] == list(TASK_D_CASE_IDS)
    assert all("turns" not in case for case in benchmark["cases"])
    assert benchmark["selection_policy"]["single_turn_only"] is True
    assert benchmark["selection_policy"]["random_sampling"] is False
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


def test_task_d_benchmark_supports_targeted_case_id_subset() -> None:
    benchmark = build_task_d_benchmark(
        ROOT / "experiments" / "ctp100_formal_v2.json",
        case_ids=["ctp100_v2_031"],
    )

    assert benchmark["case_count"] == 1
    assert benchmark["turn_count"] == 1
    assert benchmark["selection_policy"]["fixed_case_ids"] == ["ctp100_v2_031"]
    assert [case["case_id"] for case in benchmark["cases"]] == ["ctp100_v2_031"]
    assert benchmark["selection_policy"]["coverage"]["task_type_counts"] == {
        "weather_query": 1
    }


def test_task_d_report_passes_for_clean_real_api_shaped_results(tmp_path: Path) -> None:
    run_dir = tmp_path / "task-d"
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True)
    benchmark = {
        "dataset_id": "task_d_unit",
        "dataset_version": "unit",
        "case_count": 2,
        "turn_count": 2,
        "selection_policy": {"coverage": {"task_type_counts": {"general_chat": 2}}},
    }
    results = [
        {
            "case_id": "case_001",
            "method": TASK_D_METHOD,
            "status": "completed",
            "latency_ms": 1000.0,
            "hard_timeout_triggered": False,
        },
        {
            "case_id": "case_002",
            "method": TASK_D_METHOD,
            "status": "completed",
            "latency_ms": 2000.0,
            "hard_timeout_triggered": False,
        },
    ]
    for index in range(2):
        _write_trace(
            trace_dir / f"trace_{index}.jsonl",
            provider="vectorengine_openai_compatible",
            mock=False,
            fallback=False,
            success=True,
            prompt_tokens=100 + index,
            completion_tokens=20 + index,
            total_tokens=120 + index * 2,
            duration_ms=900 + index,
        )

    report = build_task_d_report(
        run_id="task-d-unit",
        run_dir=run_dir,
        benchmark_path=run_dir / "benchmark.json",
        benchmark_document=benchmark,
        runtime_config={
            "provider": "vectorengine_openai_compatible",
            "model": "gpt-test",
            "max_tokens": 4096,
            "timeout_seconds": 120,
            "hard_timeout_seconds": 300,
        },
        results=results,
        elapsed_seconds=3.0,
    )

    assert report["status"] == "passed"
    assert report["gate"]["failed_checks"] == []
    assert report["trace_audit"]["provider_counts"] == {
        "vectorengine_openai_compatible": 2
    }
    assert report["token_usage"]["total_tokens"] == 242.0
    assert report["latency"]["result_latency_ms_total"] == 3000.0
    assert report["cost"]["standardized_estimated_cost_total"] == 0.04
    markdown = render_task_d_report(report)
    assert "Task D M0 Real API Validation Report" in markdown
    assert "| no_mock_calls | `True` |" in markdown


def test_task_d_report_fails_on_mock_fallback_or_hard_timeout(tmp_path: Path) -> None:
    run_dir = tmp_path / "task-d"
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True)
    _write_trace(
        trace_dir / "trace.jsonl",
        provider="mock",
        mock=True,
        fallback=True,
        success=True,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        duration_ms=100,
    )

    report = build_task_d_report(
        run_id="task-d-failed",
        run_dir=run_dir,
        benchmark_path=run_dir / "benchmark.json",
        benchmark_document={"dataset_id": "unit", "turn_count": 1},
        runtime_config={"provider": "vectorengine_openai_compatible", "model": "gpt-test"},
        results=[
            {
                "case_id": "case_001",
                "method": TASK_D_METHOD,
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
        "all_results_completed",
        "no_mock_calls",
        "no_fallback_calls",
        "no_hard_timeout",
    }
    assert report["results"]["failed_results"][0]["case_id"] == "case_001"


def test_task_d_env_values_force_strict_real_api_runtime() -> None:
    env = _task_d_env_values(
        {
            "base_url": "https://api.vectorengine.ai/v1",
            "model": "gpt-5-mini",
            "temperature": 0.0,
            "max_tokens": 4096,
            "timeout_seconds": 120,
            "retry_max_attempts": 3,
            "reasoning_effort": "minimal",
            "hard_timeout_seconds": 300,
        }
    )

    assert env["EXPERIMENT_STRICT_MODE"] == "true"
    assert env["EXPERIMENT_DISABLE_CACHE"] == "true"
    assert env["TRACE_SAVE_USER_MESSAGE"] == "false"
    assert env["LLM_BASE_URL"] == "https://api.vectorengine.ai/v1"
    assert env["LLM_MODEL"] == "gpt-5-mini"
    assert env["LLM_MAX_TOKENS"] == "4096"
    assert env["LLM_TIMEOUT"] == "120"
    assert env["EXPERIMENT_RESULT_HARD_TIMEOUT_SECONDS"] == "300"


def _write_trace(
    path: Path,
    *,
    provider: str,
    mock: bool,
    fallback: bool,
    success: bool,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    duration_ms: float,
) -> None:
    record = {
        "request_id": path.stem,
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
    }
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
