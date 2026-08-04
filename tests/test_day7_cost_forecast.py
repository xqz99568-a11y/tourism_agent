import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.day7_cost_forecast import (
    DAY7_COST_FORECAST_SCHEMA_VERSION,
    build_day7_cost_forecast,
    write_day7_cost_forecast,
)
from app.core.experiment_runner import ExperimentRunner
from experiments.run_day7_dev_experiment import run_day7_dev_experiment
from tests.test_day7_dev_experiment import (
    _dev_env,
    _file_sha256,
    _rewrite_run_as_1024_empty_token_capped,
    _write_dev_mini_benchmark,
)
from tests.test_day7_pilot import _fake_weather_handler


def test_day7_cost_forecast_freezes_model_runtime_and_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = _run_unit_dev_experiment(monkeypatch, tmp_path)

    payload = write_day7_cost_forecast(
        run_dir,
        expected_dev_case_count=2,
        expected_dev_turn_count=3,
        expected_dev_raw_result_count=12,
        expected_task_type_count=1,
        formal_case_count=10,
        formal_turn_count=15,
        formal_raw_result_count=60,
        input_usd_per_1m=1.0,
        output_usd_per_1m=2.0,
        price_source_url="https://api.vectorengine.ai/pricing",
        price_snapshot_date="2026-08-01",
        usd_to_cny_rate=7.3,
    )

    assert payload["status"] == "completed"
    assert payload["freeze_status"] == "frozen_for_cost_and_runtime"
    assert payload["budget_status"] == "passed"
    assert payload["failed_checks"] == []
    assert Path(payload["json"]).exists()
    assert Path(payload["markdown"]).exists()

    forecast = json.loads(Path(payload["json"]).read_text(encoding="utf-8"))
    assert forecast["schema_version"] == DAY7_COST_FORECAST_SCHEMA_VERSION
    assert forecast["status"] == "passed"
    assert forecast["paper_claims_allowed"] is False
    assert forecast["observed_development_run"]["raw_result_count"] == 12
    assert forecast["observed_development_run"]["scope_matches_expected"] is True
    assert forecast["development_totals"]["prompt_tokens"] == 108
    assert forecast["development_totals"]["completion_tokens"] == 36
    assert forecast["development_totals"]["total_tokens"] == 144
    assert forecast["development_totals"]["cost_cny"] > 0
    assert forecast["formal_projection"]["scale_factor_from_development_raw_rows"] == 5
    assert forecast["formal_projection"]["raw_result_count"] == 60
    assert forecast["budget_gate"]["two_week_total_cny"] < 150
    assert forecast["runtime_freeze"]["consistent"] is True
    assert forecast["runtime_freeze"]["matches_day7_max_tokens_protocol"] is True
    assert forecast["runtime_freeze"]["deterministic_research_final_answer"] is True
    assert (
        forecast["runtime_freeze"]["final_answer_generation_mode"]
        == "deterministic_research_evidence_renderer"
    )
    assert forecast["checks"]["runtime_max_tokens_matches_day7_protocol"] is True
    assert forecast["checks"]["deterministic_research_final_answer_recorded"] is True
    assert forecast["checks"]["completion_token_cap_hit_rate_below_limit"] is True
    assert forecast["checks"]["no_empty_outputs_at_token_cap"] is True
    assert forecast["quality_advisory_failed_checks"] == []
    assert forecast["evidence_quality"]["output_length_risk"]["completion_token_cap_hit_rate"] == 0.0
    assert forecast["freeze_decision"]["model"] == "day7-pilot-unit-model"
    assert forecast["freeze_decision"]["max_tokens"] == 4096
    assert forecast["freeze_decision"]["reasoning_effort"] == "minimal"
    assert forecast["freeze_decision"]["deterministic_research_final_answer"] is True
    assert forecast["freeze_decision"]["rerun_required"] is False
    assert forecast["freeze_decision"]["quality_rerun_recommended"] is False
    assert "subsequent development repair run" not in forecast["freeze_decision"]["quality_scope_note"]
    assert len(forecast["method_costs"]) == 4
    assert {row["name"] for row in forecast["method_costs"]} == set(ExperimentRunner.METHODS)
    assert forecast["evidence_quality"]["mock_call_count"] == 0
    assert forecast["evidence_quality"]["fallback_call_count"] == 0
    assert forecast["evidence_quality"]["cache_hit_count"] == 0
    assert forecast["evidence_quality"]["trace_standardized_cost_sum"] > 0
    assert forecast["evidence_quality"]["trace_env_or_zero_default_call_count"] == 0

    manifest = json.loads((run_dir / "experiment_manifest.json").read_text(encoding="utf-8"))
    assert manifest["day7_cost_forecast"]["status"] == "passed"
    assert manifest["day7_cost_forecast"]["freeze_status"] == "frozen_for_cost_and_runtime"
    assert manifest["results"]["day7_cost_forecast_json"] == payload["json"]
    assert manifest["results"]["day7_cost_forecast_report"] == payload["markdown"]

    dev_gate = json.loads((run_dir / "day7_dev_gate.json").read_text(encoding="utf-8"))
    manifest_hash = next(
        item["sha256"]
        for item in dev_gate["artifact_index"]["files"]
        if item["key"] == "manifest"
    )
    assert manifest_hash == _file_sha256(run_dir / "experiment_manifest.json")


def test_day7_cost_forecast_blocks_freeze_when_budget_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = _run_unit_dev_experiment(monkeypatch, tmp_path)

    forecast = build_day7_cost_forecast(
        run_dir,
        expected_dev_case_count=2,
        expected_dev_turn_count=3,
        expected_dev_raw_result_count=12,
        expected_task_type_count=1,
        formal_case_count=10,
        formal_turn_count=15,
        formal_raw_result_count=60,
        dev_budget_cny=0.000001,
        formal_budget_cny=0.000001,
        two_week_budget_cny=0.000001,
        input_usd_per_1m=1000.0,
        output_usd_per_1m=2000.0,
        usd_to_cny_rate=7.3,
    )

    assert forecast["status"] == "failed"
    assert forecast["freeze_decision"]["status"] == "not_frozen"
    assert forecast["budget_gate"]["status"] == "failed"
    assert "dev_budget_within_15_cny" in forecast["failed_checks"]
    assert "formal_budget_within_75_cny" in forecast["failed_checks"]
    assert "two_week_budget_within_150_cny" in forecast["failed_checks"]


def test_day7_cost_forecast_requires_protocol_runtime_and_uncapped_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = _run_unit_dev_experiment(monkeypatch, tmp_path)
    _rewrite_run_as_1024_empty_token_capped(run_dir)

    forecast = build_day7_cost_forecast(
        run_dir,
        expected_dev_case_count=2,
        expected_dev_turn_count=3,
        expected_dev_raw_result_count=12,
        expected_task_type_count=1,
        formal_case_count=10,
        formal_turn_count=15,
        formal_raw_result_count=60,
        input_usd_per_1m=1.0,
        output_usd_per_1m=2.0,
        usd_to_cny_rate=7.3,
    )

    assert forecast["status"] == "failed"
    assert forecast["freeze_decision"]["status"] == "not_frozen"
    assert forecast["freeze_decision"]["rerun_required"] is True
    assert "runtime_max_tokens_matches_day7_protocol" in forecast["failed_checks"]
    assert "completion_token_cap_hit_rate_below_limit" in forecast["failed_checks"]
    assert "no_empty_outputs_at_token_cap" in forecast["quality_advisory_failed_checks"]
    assert forecast["runtime_freeze"]["matches_day7_max_tokens_protocol"] is False
    assert forecast["evidence_quality"]["output_length_risk"]["completion_token_cap_hit_rate"] == 1.0
    assert forecast["evidence_quality"]["output_length_risk"]["empty_and_token_capped_call_count"] == 12


def test_day7_cost_forecast_freezes_cost_with_quality_advisory_for_rare_empty_cap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = _run_unit_dev_experiment(monkeypatch, tmp_path)
    _rewrite_one_call_as_4096_empty_token_capped(run_dir)

    forecast = build_day7_cost_forecast(
        run_dir,
        expected_dev_case_count=2,
        expected_dev_turn_count=3,
        expected_dev_raw_result_count=12,
        expected_task_type_count=1,
        formal_case_count=10,
        formal_turn_count=15,
        formal_raw_result_count=60,
        input_usd_per_1m=1.0,
        output_usd_per_1m=2.0,
        usd_to_cny_rate=7.3,
        token_cap_hit_rate_limit=0.10,
    )

    assert forecast["status"] == "passed"
    assert forecast["freeze_decision"]["status"] == "frozen_for_cost_and_runtime"
    assert forecast["failed_checks"] == []
    assert forecast["checks"]["no_empty_outputs_at_token_cap"] is False
    assert "no_empty_outputs_at_token_cap" in forecast["quality_advisory_failed_checks"]
    assert forecast["quality_advisory"]["quality_rerun_recommended"] is True
    assert forecast["freeze_decision"]["rerun_required"] is False
    assert forecast["freeze_decision"]["quality_rerun_recommended"] is True
    assert forecast["evidence_quality"]["output_length_risk"]["empty_and_token_capped_call_count"] == 1


def _run_unit_dev_experiment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    _dev_env(monkeypatch)
    monkeypatch.setenv("LLM_PRICE_INPUT_PER_1K", "0.00025")
    monkeypatch.setenv("LLM_PRICE_OUTPUT_PER_1K", "0.002")
    monkeypatch.setenv("LLM_PRICE_SNAPSHOT_DATE", "2026-08-01")
    monkeypatch.setenv("LLM_PRICE_SOURCE_URL", "https://api.vectorengine.ai/pricing")
    monkeypatch.setenv("LLM_PRICE_CURRENCY", "USD")
    benchmark_path = _write_dev_mini_benchmark(tmp_path / "day7_dev_mini.json")
    payload = run_day7_dev_experiment(
        benchmark_path=benchmark_path,
        output_dir=tmp_path / "day7_dev_runs",
        run_id="day7-cost-unit",
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
    assert payload["dev_gate_status"] == "passed"
    return Path(payload["output_dir"])


def _rewrite_one_call_as_4096_empty_token_capped(run_dir: Path) -> None:
    results = json.loads((run_dir / "benchmark_results.json").read_text(encoding="utf-8"))
    result = results[0]
    trace_path = Path(str(result["trace_file"]))
    if not trace_path.is_absolute():
        trace_path = run_dir / trace_path
    trace = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
    call = next(call for call in trace.get("llm_calls") or [] if isinstance(call, dict))
    call["max_tokens"] = 4096
    call["output_chars"] = 0
    options = call.setdefault("request_options", {})
    options["max_tokens"] = 4096
    usage = call.setdefault("usage", {})
    prompt_tokens = int(usage.get("prompt_tokens") or 9)
    usage["prompt_tokens"] = prompt_tokens
    usage["completion_tokens"] = 4096
    usage["total_tokens"] = prompt_tokens + 4096
    trace_path.write_text(
        json.dumps(trace, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
