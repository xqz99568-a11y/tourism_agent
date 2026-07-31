import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_day6_acceptance_script_writes_pipeline_evidence(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    from experiments import run_day6_acceptance as day6_acceptance

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_day6_acceptance.py",
            "--output-dir",
            str(tmp_path / "day6_acceptance"),
            "--run-id",
            "day6-unit",
        ],
    )

    assert day6_acceptance.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "passed"
    assert payload["acceptance_level"] == "infrastructure_acceptance"
    assert payload["academic_quality_status"] == "not_evaluated_with_fake_llm"
    assert payload["quality_gate"]["schema_version"] == "day6-acceptance-gate-v1"
    assert payload["quality_gate"]["task_type_alignment"]["status"] == "passed"
    assert payload["quality_gate"]["task_type_alignment"]["checked_unit_count"] == 32
    assert payload["quality_gate"]["task_type_alignment"]["mismatch_count"] == 0
    assert payload["quality_gate"]["task_type_alignment"]["non_frozen_task_type_count"] == 0
    assert payload["quality_gate"]["stsr"]["status"] == "informational_only"
    assert payload["quality_gate"]["stsr"]["total_count"] == 32
    assert payload["quality_gate"]["stsr"]["interpretation"] == "fake_llm_not_model_quality"
    assert payload["run_id"] == "day6-unit"
    assert payload["result_count"] == payload["expected_count"] == 44
    assert payload["saved_evidence"]["schema_version"] == "day6-saved-evidence-v1"
    assert payload["saved_evidence"]["status"] == "saved"
    assert payload["saved_evidence"]["result_count"] == 44
    assert payload["saved_evidence"]["expected_count"] == 44
    assert payload["trace_file_count"] == payload["result_count"]
    assert Path(payload["trace_dir"]).exists()
    assert Path(payload["representative_trace"]).exists()
    for key in ("benchmark", "csv", "json", "summary", "paper_tables", "manifest", "report"):
        assert Path(payload[key]).exists()

    summary = json.loads(Path(payload["summary"]).read_text(encoding="utf-8"))
    manifest = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
    results = json.loads(Path(payload["json"]).read_text(encoding="utf-8"))
    paper_tables = Path(payload["paper_tables"]).read_text(encoding="utf-8")

    assert set(summary["methods"]) == set(day6_acceptance.ExperimentRunner.METHODS)
    assert summary["paired_statistics"]["pair_count"] == 8
    assert summary["unique_case_count"] == 8
    assert summary["quality_evaluation_scope"]["multi_turn"] == "target_turn_only"
    assert summary["repeat_aggregation"]["unit"] == "evaluation_unit_id"
    assert summary["repeat_aggregation"]["scenario_turns_are_repeats"] is False
    assert summary["scenario_costs"]["scenario_count"] == 3
    m3_costs = summary["scenario_costs"]["methods"]["adaptive_multi_agent"]
    assert m3_costs["target_increment_llm_call_count_mean"] < (
        m3_costs["scenario_total_llm_call_count_mean"]
    )
    assert "llm_call_count_mean" in summary["methods"]["adaptive_multi_agent"]
    assert "called_tool_count_mean" in summary["methods"]["adaptive_multi_agent"]
    assert "Prompt tokens" in paper_tables
    assert "Standardized cost/case" in paper_tables
    assert "M3 Proposed" in paper_tables
    assert "Multi-turn scenario costs" in paper_tables
    assert "Target turn incremental" in paper_tables
    assert "Scenario total" in paper_tables
    report_text = Path(payload["report"]).read_text(encoding="utf-8")
    assert "acceptance_level: `infrastructure_acceptance`" in report_text
    assert "academic_quality_status: `not_evaluated_with_fake_llm`" in report_text
    assert "status: `passed`" in report_text
    assert "git_commit:" in report_text
    assert "saved_evidence_status: `saved`" in report_text
    assert "trace_file_count: `44`" in report_text
    assert "Saved evidence files" in report_text
    assert "fake_llm_not_model_quality" in report_text
    assert "FakeLLM diagnostics only, not academic-quality model results" in report_text
    assert manifest["method_fairness_contract"]["schema_version"] == (
        day6_acceptance.METHOD_FAIRNESS_CONTRACT_SCHEMA_VERSION
    )
    assert len(manifest["method_fairness_contract"]["contract_sha256"]) == 64
    assert manifest["prompt_versions"]["structured_llm_output"] == (
        day6_acceptance.STRUCTURED_LLM_OUTPUT_PROMPT_VERSION
    )
    assert manifest["costing"]["schema_version"] == "ctp-llm-costing-v1"
    assert manifest["costing"]["price_snapshot_date"]
    assert manifest["costing"]["input_token_unit_price"] == 0.0
    assert manifest["costing"]["output_token_unit_price"] == 0.0
    day6_evidence = manifest["day6_acceptance"]
    assert day6_evidence["status"] == "passed"
    assert day6_evidence["result_count"] == 44
    assert day6_evidence["expected_count"] == 44
    assert day6_evidence["quality_gate"]["task_type_alignment"]["status"] == "passed"
    assert day6_evidence["saved_evidence"]["status"] == "saved"
    assert day6_evidence["saved_evidence"]["trace_file_count"] == 44
    assert manifest["results"]["day6_acceptance_report"] == payload["report"]
    assert manifest["results"]["trace_dir"] == payload["trace_dir"]
    assert manifest["results"]["representative_trace"] == payload["representative_trace"]

    quality_task_types = {
        (result["output"] or {}).get("task_type")
        for result in results
        if result.get("target_turn") is not False
    }
    assert {
        "trip_planning",
        "attraction_recommendation",
        "weather_query",
        "budget_query",
        "partial_replan",
        "weather_adjustment",
        "clarification",
        "general_chat",
    } <= quality_task_types
    task_type_mismatches = [
        (
            result["method"],
            result["case_id"],
            result.get("turn_id"),
            (result["evaluation"] or {}).get("task_type"),
            (result["output"] or {}).get("task_type"),
        )
        for result in results
        if result.get("target_turn") is not False
        and (result["evaluation"] or {}).get("task_type") != (result["output"] or {}).get("task_type")
    ]
    assert task_type_mismatches == []

    llm_calls = [
        call
        for result in results
        for call in (result.get("trace") or {}).get("llm_calls", [])
    ]
    assert llm_calls
    assert all(call["mock"] is True and call["mock_used"] is True for call in llm_calls)
    assert all(call["fallback"] is False and call["fallback_used"] is False for call in llm_calls)
    assert all(call["estimated_cost"] is not None for call in llm_calls)
    assert all(call["standardized_estimated_cost"] is not None for call in llm_calls)
    assert all(call["actual_cost"] == 0.0 for call in llm_calls)
    assert all(call["price_snapshot_date"] for call in llm_calls)
    assert all(len(call["prompt_hash"]) == 64 for call in llm_calls)

    for method in ("llm_direct", "single_agent"):
        structured = next(
            result
            for result in results
            if result["case_id"] == "day6_full_plan" and result["method"] == method
        )
        assert structured["raw_output"]["schema_version"] == "ctp-experiment-output-v1"
        assert structured["raw_output"]["metadata"]["structured_llm_output"]["parse_status"] == "passed"
        assert structured["raw_output"]["metadata"]["structured_llm_output"]["validation_status"] == "passed"

    m3_full_plan = next(
        result
        for result in results
        if result["case_id"] == "day6_full_plan"
        and result["method"] == "adaptive_multi_agent"
    )
    full_plan_scheduler = m3_full_plan["output"]["metadata"]["adaptive_scheduler"]
    assert full_plan_scheduler["ticket"]["task_type"] == "trip_planning"
    assert full_plan_scheduler["decision"]["planned_agents"] == [
        "attraction",
        "weather",
        "itinerary",
        "budget",
    ]
    assert full_plan_scheduler["decision"]["planned_tools"] == [
        "poi_search",
        "weather_query",
        "budget_calculator",
    ]
    assert m3_full_plan["run_audit"]["metrics"]["planned_agent_count"] == 4
    assert m3_full_plan["run_audit"]["metrics"]["called_tool_count"] == 3

    clarification = next(
        result
        for result in results
        if result["case_id"] == "day6_clarification_missing_date_days"
        and result["method"] == "adaptive_multi_agent"
    )
    clarification_scheduler = clarification["output"]["metadata"]["adaptive_scheduler"]
    assert clarification["status"] == "clarification"
    assert clarification_scheduler["ticket"]["task_type"] == "clarification"
    assert clarification_scheduler["decision"]["planned_agents"] == []
    assert clarification_scheduler["decision"]["planned_tools"] == []
    assert clarification["run_audit"]["metrics"]["planned_agent_count"] == 0
    assert clarification["run_audit"]["metrics"]["called_tool_count"] == 0

    m3_reuse = next(
        result
        for result in results
        if result["case_id"] == "day6_scenario_people_change"
        and result["method"] == "adaptive_multi_agent"
        and result["turn_id"] == "t2_people_change"
    )
    m2_reuse = next(
        result
        for result in results
        if result["case_id"] == "day6_scenario_people_change"
        and result["method"] == "fixed_multi_agent"
        and result["turn_id"] == "t2_people_change"
    )

    assert m3_reuse["run_audit"]["schema_version"] == day6_acceptance.RUN_AUDIT_SCHEMA_VERSION
    assert m3_reuse["audit"] == m3_reuse["run_audit"]
    assert m3_reuse["target_turn"] is True
    assert "attraction" in m3_reuse["metrics"]["m3_reused_agents"]
    assert m3_reuse["run_audit"]["metrics"]["planned_agent_count"] < (
        m2_reuse["run_audit"]["metrics"]["planned_agent_count"]
    )
    assert m3_reuse["run_audit"]["metrics"]["called_tool_count"] < (
        m2_reuse["run_audit"]["metrics"]["called_tool_count"]
    )

    for method in ("llm_direct", "single_agent"):
        target = next(
            result
            for result in results
            if result["case_id"] == "day6_scenario_people_change"
            and result["method"] == method
            and result["turn_id"] == "t2_people_change"
        )
        model_meta = target["raw_output"]["metadata"]["model_metadata"]
        assert model_meta["dialogue_history_count"] >= 2
        assert model_meta["assistant_history_seen"] is True
        assert model_meta["previous_state_method"] == method
        assert model_meta["previous_state_turn_id"] == "t1_full_plan"

    rain = next(
        result
        for result in results
        if result["case_id"] == "day6_scenario_rain_day2"
        and result["method"] == "adaptive_multi_agent"
        and result["turn_id"] == "t2_rain_day2"
    )
    rain_scheduler = rain["output"]["metadata"]["adaptive_scheduler"]
    assert rain_scheduler["ticket"]["task_type"] == "weather_adjustment"
    assert rain_scheduler["decision"]["planned_agents"] == ["weather", "itinerary"]
    assert rain_scheduler["decision"]["planned_tools"] == ["weather_query"]
    assert "attraction" in rain["metrics"]["m3_reused_agents"]
    assert any(
        adjustment.get("day") == 2 and adjustment.get("day_index") == 2
        for adjustment in rain["output"]["weather_adjustments"]
    )

    repeat = next(
        result
        for result in results
        if result["case_id"] == "day6_scenario_repeat_request"
        and result["method"] == "adaptive_multi_agent"
        and result["turn_id"] == "t2_repeat_same"
    )
    assert repeat["metrics"]["m3_reused_agents"] == [
        "attraction",
        "weather",
        "itinerary",
        "budget",
    ]
    assert repeat["run_audit"]["metrics"]["planned_agent_count"] == 0
    assert repeat["run_audit"]["metrics"]["called_tool_count"] == 0


def test_day6_acceptance_refuses_to_overwrite_output_dir(monkeypatch, tmp_path: Path) -> None:
    from experiments import run_day6_acceptance as day6_acceptance

    output_root = tmp_path / "day6_acceptance"
    occupied = output_root / "day6-unit"
    occupied.mkdir(parents=True)
    marker = occupied / "old.txt"
    marker.write_text("keep", encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_day6_acceptance.py",
            "--output-dir",
            str(output_root),
            "--run-id",
            "day6-unit",
        ],
    )

    with pytest.raises(RuntimeError, match="not empty"):
        day6_acceptance.main()
    assert marker.read_text(encoding="utf-8") == "keep"


def test_day6_acceptance_task_type_alignment_is_blocking() -> None:
    from experiments import run_day6_acceptance as day6_acceptance

    results = [
        {
            "method": "adaptive_multi_agent",
            "case_id": "weather_only",
            "turn_id": None,
            "target_turn": True,
            "output": {"task_type": "trip_planning"},
            "evaluation": {"task_type": "weather_query", "metrics": {"stsr": False}},
        },
        {
            "method": "fixed_multi_agent",
            "case_id": "budget_only",
            "turn_id": None,
            "target_turn": True,
            "output": {"task_type": "budget_control"},
            "evaluation": {"task_type": "budget_query", "metrics": {"stsr": False}},
        },
    ]

    report = day6_acceptance._task_type_alignment_report(results)
    assert report["status"] == "failed"
    assert report["mismatch_count"] == 2
    assert report["non_frozen_task_type_count"] == 1

    with pytest.raises(RuntimeError, match="Day6 task type alignment failed"):
        day6_acceptance._validate_task_type_alignment(results)
