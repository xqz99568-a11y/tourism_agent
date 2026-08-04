import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.experiment_runner import ExperimentRunner
from app.core.tracing import (
    finish_llm_call,
    get_current_trace,
    record_planned_tools,
    record_tool_call,
    set_trace_selected_agents,
    start_llm_call,
)
from app.schemas.experiment import EXPERIMENT_OUTPUT_SCHEMA_VERSION
from experiments.run_day7_pilot import (
    DAY7_PILOT_BENCHMARK_SCHEMA_VERSION,
    DAY7_PILOT_GATE_SCHEMA_VERSION,
    DEFAULT_BENCHMARK_PATH,
    DEFAULT_MAX_CASES,
    build_pilot_benchmark_document,
    run_day7_pilot,
)


def test_day7_pilot_runs_subset_and_writes_gate_report(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _pilot_env(monkeypatch)
    source_benchmark = _write_weather_benchmark(tmp_path / "source_benchmark.json")

    payload = run_day7_pilot(
        benchmark_path=source_benchmark,
        output_dir=tmp_path / "day7_runs",
        run_id="day7-pilot-unit",
        max_cases=1,
        repeats=1,
        methods=ExperimentRunner.METHODS,
        require_llm_config=False,
        runner_kwargs={
            "method_handlers": {
                method: _fake_weather_handler
                for method in ExperimentRunner.METHODS
            }
        },
    )

    assert payload["status"] == "completed"
    assert payload["result_count"] == 4
    assert payload["expected_count"] == 4

    gate = payload["pilot_gate"]
    assert gate["schema_version"] == DAY7_PILOT_GATE_SCHEMA_VERSION
    assert gate["status"] == "passed"
    assert gate["checks"]["preflight_passed"] is True
    assert gate["checks"]["request_level_trace_count_matches"] is True
    assert gate["checks"]["loaded_trace_count_matches"] is True
    assert gate["checks"]["runtime_audit_recorded"] is True
    assert gate["checks"]["run_audit_attached"] is True
    assert gate["checks"]["metric_fields_present"] is True
    assert gate["pilot_structure"]["case_count"] == 1
    assert gate["pilot_structure"]["total_turn_count"] == 1
    assert gate["pilot_structure"]["expected_trace_count"] == 4
    assert gate["pilot_structure"]["actual_trace_file_count"] == 4
    assert gate["result_status_summary"]["status_counts"] == {"completed": 4}
    assert gate["result_status_summary"]["quality_gated"] is False
    assert gate["quality_policy"]["quality_threshold_enforced"] is False
    assert gate["trace_summary"]["trace_without_llm_call_count"] == 0
    assert gate["trace_summary"]["llm_call_count"] == 4
    assert gate["trace_summary"]["total_tokens"] == 48.0

    for key in (
        "pilot_benchmark",
        "preflight",
        "gate",
        "report",
        "csv",
        "json",
        "summary",
        "paper_tables",
        "paper_analysis_json",
        "paper_analysis_md",
        "day7_issue_report_json",
        "day7_fix_report_md",
        "manifest",
    ):
        assert Path(payload[key]).exists()

    rows = list(csv.DictReader(Path(payload["csv"]).open(encoding="utf-8-sig")))
    assert len(rows) == 4
    assert all(row["run_audit_schema_version"] == "ctp-run-audit-v1" for row in rows)
    assert all(row["llm_call_count"] == "1" for row in rows)

    manifest = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
    assert manifest["day7_pilot"]["status"] == "passed"
    assert manifest["results"]["day7_pilot_gate"] == payload["gate"]
    assert manifest["results"]["day7_pilot_report"] == payload["report"]
    assert manifest["paper_analysis"]["status"] == "analysis_only"
    assert manifest["results"]["paper_analysis_json"] == payload["paper_analysis_json"]
    assert manifest["results"]["paper_analysis_md"] == payload["paper_analysis_md"]
    assert manifest["day7_fix_report"]["status"] == "completed"
    assert manifest["results"]["day7_issue_report_json"] == payload["day7_issue_report_json"]
    assert manifest["results"]["day7_fix_report_md"] == payload["day7_fix_report_md"]

    paper_analysis = json.loads(Path(payload["paper_analysis_json"]).read_text(encoding="utf-8"))
    assert paper_analysis["profile"] == "pilot"
    assert paper_analysis["readiness"]["paper_claims_allowed"] is False
    assert paper_analysis["m3_vs_m2"]["pair_count"] == 1

    fix_report = json.loads(Path(payload["day7_issue_report_json"]).read_text(encoding="utf-8"))
    assert fix_report["status"] == "completed"
    assert "systemic_failure" in fix_report["m3_systemic_failure_analysis"]

    report = Path(payload["report"]).read_text(encoding="utf-8")
    assert "Day 7 pilot report" in report
    assert "runtime_audit_recorded" in report
    assert Path(payload["pilot_benchmark"]).read_text(encoding="utf-8") != source_benchmark.read_text(encoding="utf-8")


def test_day7_pilot_preflight_only_does_not_create_run_directory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _pilot_env(monkeypatch)
    source_benchmark = _write_weather_benchmark(tmp_path / "source_benchmark.json")

    payload = run_day7_pilot(
        benchmark_path=source_benchmark,
        output_dir=tmp_path / "day7_runs",
        run_id="day7-preflight-only",
        max_cases=1,
        repeats=1,
        methods=["adaptive_multi_agent"],
        preflight_only=True,
        require_llm_config=False,
    )

    assert payload["status"] == "preflight_passed"
    assert Path(payload["pilot_benchmark"]).exists()
    assert not Path(payload["output_dir"]).exists()


def test_day7_pilot_benchmark_records_source_hash(tmp_path: Path) -> None:
    source_benchmark = _write_weather_benchmark(tmp_path / "source_benchmark.json")

    document = build_pilot_benchmark_document(
        benchmark_path=source_benchmark,
        max_cases=1,
    )

    assert document["schema_version"] == DAY7_PILOT_BENCHMARK_SCHEMA_VERSION
    assert document["selection"]["selected_case_count"] == 1
    assert document["selection"]["selected_case_ids"] == ["pilot_weather_case"]
    assert len(document["source_dataset"]["sha256"]) == 64
    assert document["source_dataset"]["hash_strategy"] == "canonical_json_utf8_sort_keys_v1"


def test_day7_pilot_default_scope_matches_full_smoke_set() -> None:
    document = build_pilot_benchmark_document(
        benchmark_path=DEFAULT_BENCHMARK_PATH,
        max_cases=DEFAULT_MAX_CASES,
    )

    assert DEFAULT_MAX_CASES == 8
    assert document["selection"]["selected_case_count"] == 8
    assert sum(len(case.get("turns") or [case]) for case in document["cases"]) == 10


async def _fake_weather_handler(case: dict) -> dict:
    trace_call = start_llm_call(
        provider="day7_test",
        model="day7-pilot-unit-model",
        streaming=False,
        mock=False,
        fallback=False,
        message_count=1,
        message_chars=len(str(case.get("user_input") or "")),
        tool_count=0,
        prompt_version="day7-pilot-test-prompt-v1",
        prompt_hash="0" * 64,
        request_options={
            "schema_version": "ctp-experiment-runtime-config-v1",
            "provider": "day7_test",
            "model": "day7-pilot-unit-model",
            "temperature": 0.0,
            "max_tokens": 4096,
            "timeout_seconds": 60,
            "retry_max_attempts": 3,
            "reasoning_effort": "minimal",
        },
        retry_policy={
            "schema_version": "ctp-llm-retry-audit-v1",
            "max_attempts": 3,
        },
    )
    trace = get_current_trace()
    if trace is not None:
        trace.mark_first_body_token()
    set_trace_selected_agents(["weather"])
    record_planned_tools(["weather_query"])
    record_tool_call(
        "weather_query",
        params={"city": "hangzhou", "date": "2026-08-01"},
        duration_ms=1,
        status="completed",
        success=True,
        agent="weather",
    )
    finish_llm_call(
        trace_call,
        provider="day7_test",
        model="day7-pilot-unit-model",
        usage={
            "prompt_tokens": 9,
            "completion_tokens": 3,
            "total_tokens": 12,
        },
        success=True,
        mock=False,
        fallback=False,
        output_chars=20,
        request_options={
            "schema_version": "ctp-experiment-runtime-config-v1",
            "provider": "day7_test",
            "model": "day7-pilot-unit-model",
            "temperature": 0.0,
            "max_tokens": 4096,
            "timeout_seconds": 60,
            "retry_max_attempts": 3,
            "reasoning_effort": "minimal",
        },
        retry={
            "schema_version": "ctp-llm-retry-audit-v1",
            "max_attempts": 3,
            "attempt_count": 1,
            "retry_count": 0,
            "error_count": 0,
            "succeeded": True,
            "attempts": [{"attempt_index": 1, "success": True}],
        },
    )

    method = str((case.get("method_input") or {}).get("method") or "unknown")
    return {
        "schema_version": EXPERIMENT_OUTPUT_SCHEMA_VERSION,
        "case_id": str(case.get("case_id") or ""),
        "method": method,
        "task_type": "weather_query",
        "planned_agents": ["weather"],
        "used_agents": ["weather"],
        "planned_tools": ["weather_query"],
        "called_tools": [
            {
                "tool_name": "weather_query",
                "status": "completed",
                "success": True,
                "arguments": {"city": "hangzhou", "date": "2026-08-01"},
                "duration_ms": 1,
            }
        ],
        "tool_results": {
            "weather_query": {
                "schema_version": "research_tool_result_v1",
                "tool_name": "weather_query",
                "status": "success",
                "success": True,
                "input": {"city": "hangzhou", "date": "2026-08-01"},
                "data": {
                    "city": "hangzhou",
                    "daily_weather": [
                        {"day": 1, "date": "2026-08-01", "condition": "sunny"}
                    ],
                },
            }
        },
        "attractions": [],
        "trip_days": None,
        "daily_itinerary": [],
        "budget": None,
        "weather": {
            "city": "hangzhou",
            "daily_weather": [
                {"day": 1, "date": "2026-08-01", "condition": "sunny"}
            ],
        },
        "weather_adjustments": [],
        "execution_status": "completed",
        "final_answer": "Hangzhou weather is sunny.",
        "metadata": {"test_handler": True},
    }


def _write_weather_benchmark(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "ctp-benchmark-v1",
                "dataset_id": "day7_unit_source",
                "dataset_version": "2026-07-31",
                "cases": [
                    {
                        "case_id": "pilot_weather_case",
                        "user_input": "只查询杭州2026年8月1日开始1天天气预报，不要推荐景点。",
                        "slots": {
                            "destination": "hangzhou",
                            "duration": 1,
                            "start_date": "2026-08-01",
                        },
                        "expected": {
                            "task_type": "weather_query",
                            "required_tools": ["weather_query"],
                            "accepted_agent_sets": [["weather"]],
                            "accepted_tool_sets": [["weather_query"]],
                        },
                    },
                    {
                        "case_id": "pilot_weather_case_extra",
                        "user_input": "只查询北京2026年8月1日开始1天天气预报，不要推荐景点。",
                        "slots": {
                            "destination": "beijing",
                            "duration": 1,
                            "start_date": "2026-08-01",
                        },
                        "expected": {
                            "task_type": "weather_query",
                            "required_tools": ["weather_query"],
                            "accepted_agent_sets": [["weather"]],
                            "accepted_tool_sets": [["weather_query"]],
                        },
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _pilot_env(monkeypatch) -> None:
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
    monkeypatch.setenv("EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER", "true")
