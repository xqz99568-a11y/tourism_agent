import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.core.benchmark_dataset_validator import build_benchmark_dataset_quality_report
from app.core.experiment_runner import RESEARCH_TASK_TYPE_ALIASES
from app.core.formal_experiment_preflight import build_formal_preflight_report
from app.core.intercity_transport_snapshot import query_intercity_rail_snapshot


DAY8_EXPERIMENT_CASES_PATH = ROOT / "experiments" / "day8_dev_experiment_cases_v1_3.json"


def test_day8_dev_experiment_cases_pass_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _formal_preflight_env(monkeypatch)
    report = build_formal_preflight_report(
        benchmark_path=DAY8_EXPERIMENT_CASES_PATH,
        output_dir=tmp_path,
        run_id="day8_dev_experiment_cases_preflight",
        expected_case_count=25,
        require_llm_config=False,
        strict_formal=True,
    )

    assert report["status"] == "passed"
    assert report["errors"] == []
    assert report["benchmark"]["case_count"] == 25
    assert report["benchmark"]["total_turn_count"] == 25
    assert report["benchmark_quality"]["status"] == "passed"
    assert report["benchmark_quality"]["policy"]["recommended_task_coverage_required"] is False


def test_day8_dev_experiment_cases_preserve_source_task_type_and_add_canonical_expected() -> None:
    document = json.loads(DAY8_EXPERIMENT_CASES_PATH.read_text(encoding="utf-8"))
    cases = {case["case_id"]: case for case in document["cases"]}

    destination_case = cases["day8_v13_007_destination_recommendation_national_day_budget"]
    assert destination_case["day8_original_task_type"] == "destination_recommendation"
    assert destination_case["task_type"] == "destination_recommendation"
    assert destination_case["expected"]["task_type"] == "general_chat"
    assert destination_case["expected"]["accepted_agent_sets"] == [[]]
    assert destination_case["expected"]["accepted_tool_sets"] == [[]]

    climate_case = cases["day8_v13_024_guilin_november_weather_climate"]
    assert climate_case["day8_original_task_type"] == "weather_climate_question"
    assert climate_case["task_type"] == "weather_climate_question"
    assert climate_case["expected"]["task_type"] == "general_chat"
    assert climate_case["expected"]["forbidden_tools"] == [
        "poi_search",
        "weather_query",
        "budget_calculator",
    ]


def test_day8_no_tool_task_aliases_match_experiment_labels() -> None:
    assert RESEARCH_TASK_TYPE_ALIASES["destination_recommendation"] == "general_chat"
    assert RESEARCH_TASK_TYPE_ALIASES["weather_climate_question"] == "general_chat"


def test_day8_dev_origin_cases_match_frozen_intercity_snapshot() -> None:
    document = json.loads(DAY8_EXPERIMENT_CASES_PATH.read_text(encoding="utf-8"))
    cases = document["cases"]
    unsupported_cases = []

    for case in cases:
        expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
        hard_constraints = (
            expected.get("hard_constraints")
            if isinstance(expected.get("hard_constraints"), dict)
            else {}
        )
        origin = hard_constraints.get("origin")
        destination = hard_constraints.get("destination")
        if not origin or not destination:
            continue
        result = query_intercity_rail_snapshot(
            origin=str(origin),
            destination=str(destination),
            people_count=int(hard_constraints.get("people_count") or 1),
        )
        if case["case_id"] == "day8_v13_025_lhasa_to_guilin_national_day_unsupported_rail":
            assert result["status"] == "route_not_supported"
            continue
        if not result["intercity_transport_included"]:
            unsupported_cases.append(
                {
                    "case_id": case["case_id"],
                    "origin": origin,
                    "destination": destination,
                    "status": result.get("status"),
                }
            )

    assert unsupported_cases == []


def test_task_coverage_exemption_is_rejected_for_non_development_datasets() -> None:
    report = build_benchmark_dataset_quality_report(
        document={
            "schema_version": "ctp-benchmark-v1",
            "dataset_id": "unsafe_test_dataset",
            "split": "test",
            "annotation_policy": {
                "recommended_formal_task_coverage_required": False,
            },
        },
        cases=[
            {
                "case_id": "case_001",
                "user_input": "你好，我先了解一下。",
                "expected": {
                    "task_type": "general_chat",
                    "required_tools": [],
                    "forbidden_tools": [
                        "poi_search",
                        "weather_query",
                        "budget_calculator",
                    ],
                    "accepted_agent_sets": [[]],
                    "accepted_tool_sets": [[]],
                },
            }
        ],
        strict_formal=True,
    )

    assert report["status"] == "failed"
    assert any(
        "recommended_formal_task_coverage_required=false is only allowed"
        in error
        for error in report["errors"]
    )


def _formal_preflight_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPERIMENT_STRICT_MODE", "true")
    monkeypatch.setenv("EXPERIMENT_DISABLE_CACHE", "true")
    monkeypatch.setenv("TRACE_SAVE_USER_MESSAGE", "false")
    monkeypatch.setenv("EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER", "true")
    monkeypatch.setenv("LLM_TEMPERATURE", "0")
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
    monkeypatch.setenv("LLM_TIMEOUT", "60")
    monkeypatch.setenv("LLM_RETRY_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "minimal")
