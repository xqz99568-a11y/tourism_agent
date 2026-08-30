import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.formal_experiment_preflight import load_benchmark_document  # noqa: E402
from experiments.run_ctp100_m3_no_reuse_ablation import (  # noqa: E402
    CTP100_M3_NO_REUSE_ABLATION_METHOD,
    CTP100_M3_NO_REUSE_EXPECTED_RESULTS,
    M3NoReuseAblationRunner,
    build_ctp100_m3_no_reuse_ablation_preflight,
    build_ctp100_m3_no_reuse_ablation_report,
    render_ctp100_m3_no_reuse_ablation_report,
    select_ctp100_two_turn_scenarios,
)


DATASET = ROOT / "experiments" / "benchmark.json"


def test_ctp100_m3_no_reuse_preflight_selects_all_two_turn_scenarios(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _formal_env(monkeypatch)

    report = build_ctp100_m3_no_reuse_ablation_preflight(
        benchmark_path=DATASET,
        output_dir=tmp_path / "runs",
        run_id="m3-no-reuse-unit",
        require_clean_git=False,
    )

    assert report["status"] == "passed"
    assert report["run"]["methods"] == [CTP100_M3_NO_REUSE_ABLATION_METHOD]
    assert report["run"]["repeats"] == 3
    assert report["run"]["repeat_index_start"] == 0
    assert report["run"]["expected_raw_run_count"] == 180
    assert report["benchmark"]["selected_two_turn_scenario_count"] == 30
    assert report["benchmark"]["selected_turn_count"] == 60
    assert report["checks"]["two_turn_scenario_count_30"] is True


def test_m3_no_reuse_strips_previous_artifacts_but_keeps_slots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured = {}

    async def fake_research_multi_agent(**kwargs):
        captured.update(kwargs)
        return {
            "method": kwargs["method"],
            "case": kwargs["case"],
            "scheduler_metadata": kwargs["scheduler_metadata"],
            "initial_tool_results": kwargs["initial_tool_results"],
        }

    runner = M3NoReuseAblationRunner(
        trace_dir=tmp_path / "traces",
    )
    monkeypatch.setattr(runner, "_run_research_multi_agent", fake_research_multi_agent)

    previous_state = {
        "schema_version": "ctp-method-previous-state-v1",
        "case_id": "ctp100_v2_051",
        "scenario_id": "ctp100_v2_051",
        "turn_id": "t1",
        "turn_index": 0,
        "method": CTP100_M3_NO_REUSE_ABLATION_METHOD,
        "status": "completed",
        "execution_status": "completed",
        "slots": {
            "destination": "shenzhen",
            "duration_days": 3,
            "people_count": 2,
            "budget_amount": 5600,
        },
        "tool_results": {"poi_search": {"status": "success", "data": {"attractions": []}}},
        "agent_outputs": {"attraction": {"status": "completed", "reused": False}},
        "output": {
            "daily_itinerary": [{"day": 1, "attractions": [{"poi_id": "sz001"}]}],
            "budget": {"total": 1000},
        },
    }
    case = {
        "case_id": "ctp100_v2_051",
        "user_input": "预算改成5200元，出发时间、目的地、人数都不变。",
        "current_turn_slots": {"budget_amount": 5200},
        "previous_state": previous_state,
        "evaluation_mode": "end_to_end",
    }

    result = asyncio.run(
        runner._run_adaptive_multi_agent_no_reuse(case, "m3-no-reuse-request")
    )

    assert result["method"] == CTP100_M3_NO_REUSE_ABLATION_METHOD
    assert captured["initial_tool_results"] == {}
    execution_case = captured["case"]
    stripped_previous = execution_case["previous_state"]
    assert stripped_previous["slots"]["destination"] == "shenzhen"
    assert stripped_previous["slots"]["people_count"] == 2
    assert "tool_results" not in stripped_previous
    assert "agent_outputs" not in stripped_previous
    assert "output" not in stripped_previous
    scheduler = captured["scheduler_metadata"]
    assert scheduler["name"] == "goal_state_scheduler_no_reuse_ablation"
    assert scheduler["ablation"]["uses_previous_slots"] is True
    assert scheduler["ablation"]["previous_tool_results_available_before_strip"] is True
    assert scheduler["ablation"]["previous_agent_outputs_available_before_strip"] is True
    assert scheduler["ablation"]["previous_artifacts_available_after_strip"] is False
    assert scheduler["reuse_execution"]["reused_agent_results"] == []
    assert scheduler["reuse_execution"]["reused_tool_results"] == []


def test_ctp100_m3_no_reuse_report_passes_for_complete_no_reuse_grid(
    tmp_path: Path,
) -> None:
    document, all_cases = load_benchmark_document(DATASET)
    cases = select_ctp100_two_turn_scenarios(all_cases)
    subset = {"dataset_id": "unit-subset", "cases": cases}
    results = _complete_results(cases)
    preflight = {
        "status": "passed",
        "run": {"expected_raw_run_count": CTP100_M3_NO_REUSE_EXPECTED_RESULTS},
    }

    report = build_ctp100_m3_no_reuse_ablation_report(
        run_id="m3-no-reuse-unit",
        run_dir=tmp_path,
        benchmark_path=DATASET,
        subset_path=tmp_path / "subset.json",
        benchmark_document=document,
        subset_document=subset,
        cases=cases,
        preflight=preflight,
        results=results,
        elapsed_seconds=1.0,
    )

    assert report["status"] == "passed"
    assert report["failed_checks"] == []
    assert report["results"]["actual_raw_result_count"] == 180
    assert report["no_reuse_audit"]["reused_agent_violation_count"] == 0
    assert report["previous_state_audit"]["second_turn_slots_missing_count"] == 0
    markdown = render_ctp100_m3_no_reuse_ablation_report(report)
    assert "CTP100 M3-no-reuse Ablation Report" in markdown
    assert "| no_reused_agents_recorded | `True` |" in markdown


def test_ctp100_m3_no_reuse_report_fails_when_reuse_is_recorded(
    tmp_path: Path,
) -> None:
    document, all_cases = load_benchmark_document(DATASET)
    cases = select_ctp100_two_turn_scenarios(all_cases)
    subset = {"dataset_id": "unit-subset", "cases": cases}
    results = _complete_results(cases)
    results[0]["metrics"]["m3_reused_agents"] = ["attraction"]
    results[0]["metrics"]["m3_reused_agent_count"] = 1
    results[0]["output"]["metadata"]["adaptive_scheduler"]["reuse_execution"][
        "reused_agent_results"
    ] = ["attraction"]
    preflight = {
        "status": "passed",
        "run": {"expected_raw_run_count": CTP100_M3_NO_REUSE_EXPECTED_RESULTS},
    }

    report = build_ctp100_m3_no_reuse_ablation_report(
        run_id="m3-no-reuse-unit",
        run_dir=tmp_path,
        benchmark_path=DATASET,
        subset_path=tmp_path / "subset.json",
        benchmark_document=document,
        subset_document=subset,
        cases=cases,
        preflight=preflight,
        results=results,
        elapsed_seconds=1.0,
    )

    assert report["status"] == "failed"
    assert "no_reused_agents_recorded" in report["failed_checks"]


def _complete_results(cases: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for repeat_index in (0, 1, 2):
        for case in cases:
            case_id = str(case.get("case_id") or case.get("scenario_id") or case.get("id"))
            for turn_index, turn in enumerate(case.get("turns") or []):
                turn_id = str(turn.get("turn_id") or turn.get("id") or f"t{turn_index + 1}")
                rows.append(
                    {
                        "case_id": case_id,
                        "scenario_id": case_id,
                        "turn_id": turn_id,
                        "turn_index": turn_index,
                        "scenario_turn_count": 2,
                        "target_turn": turn_index == 1,
                        "method": CTP100_M3_NO_REUSE_ABLATION_METHOD,
                        "repeat_index": repeat_index,
                        "status": "completed",
                        "previous_state_provided": turn_index == 1,
                        "previous_state_is_method_local": turn_index == 1,
                        "previous_state_is_prior_turn": turn_index == 1,
                        "trace": _trace(case_id, turn_id, repeat_index),
                        "output": {
                            "metadata": {
                                "adaptive_scheduler": {
                                    "name": "goal_state_scheduler_no_reuse_ablation",
                                    "ticket": {"task_type": "partial_replan"},
                                    "decision": {
                                        "planned_agents": ["budget"],
                                        "planned_tools": ["budget_calculator"],
                                        "reused_agents": [],
                                        "invalidated_agents": [],
                                        "decision_reasons": ["unit"],
                                    },
                                    "reuse_execution": {
                                        "previous_state_provided": turn_index == 1,
                                        "expected_reused_agents": [],
                                        "reused_agent_results": [],
                                        "missing_reused_agent_results": [],
                                        "expected_reused_tools": [],
                                        "reused_tool_results": [],
                                        "missing_reused_tool_results": [],
                                    },
                                    "ablation": {
                                        "uses_previous_slots": turn_index == 1,
                                        "previous_artifacts_available_after_strip": False,
                                    },
                                }
                            },
                            "agent_outputs": {
                                "budget": {"status": "completed", "reused": False}
                            },
                        },
                        "metrics": {
                            "stsr": 1.0,
                            "hcsr": 1.0,
                            "m3_reused_agents": [],
                            "m3_reused_agent_count": 0,
                            "m3_reused_tool_results": [],
                            "m3_reused_tool_result_count": 0,
                        },
                    }
                )
    assert len(rows) == CTP100_M3_NO_REUSE_EXPECTED_RESULTS
    return rows


def _trace(case_id: str, turn_id: str, repeat_index: int) -> dict:
    return {
        "request_id": f"{case_id}-{turn_id}-{repeat_index}",
        "method": CTP100_M3_NO_REUSE_ABLATION_METHOD,
        "llm_calls": [
            {
                "model": "gpt-5-mini",
                "provider": "vectorengine_openai_compatible",
                "success": True,
                "mock": False,
                "fallback": False,
                "duration_ms": 10,
            }
        ],
    }


def _formal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPERIMENT_STRICT_MODE", "true")
    monkeypatch.setenv("EXPERIMENT_DISABLE_CACHE", "true")
    monkeypatch.setenv("TRACE_SAVE_USER_MESSAGE", "false")
    monkeypatch.setenv("LLM_API_KEY", "test-key-not-persisted")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.vectorengine.ai/v1")
    monkeypatch.setenv("LLM_MODEL", "gpt-5-mini")
    monkeypatch.setenv("LLM_TEMPERATURE", "0")
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
    monkeypatch.setenv("LLM_TIMEOUT", "120")
    monkeypatch.setenv("LLM_RETRY_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "minimal")
    monkeypatch.setenv("EXPERIMENT_RESULT_HARD_TIMEOUT_SECONDS", "900")
    monkeypatch.setenv("EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER", "true")
