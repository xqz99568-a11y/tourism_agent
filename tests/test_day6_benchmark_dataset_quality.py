import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.benchmark_dataset_validator import (
    BENCHMARK_DATASET_QUALITY_SCHEMA_VERSION,
    build_benchmark_dataset_quality_report,
)
from app.core.formal_experiment_preflight import (
    build_formal_preflight_report,
    load_benchmark_document,
)
from experiments import validate_benchmark_dataset


def test_day6_benchmark_quality_accepts_labeled_single_and_scenario_cases() -> None:
    document = {
        "schema_version": "ctp-benchmark-v1",
        "dataset_id": "ctp-dev-quality",
        "dataset_version": "2026-07-29",
        "cases": [
            {
                "case_id": "quality_full_plan",
                "user_input": "请为两人规划杭州2天旅游，2026-08-01出发，预算5000元。",
                "expected": {
                    "task_type": "trip_planning",
                    "duration_days": 2,
                    "min_attractions": 2,
                    "max_pois_per_day": 2,
                    "budget_limit": 5000,
                    "required_tools": ["poi_search", "weather_query", "budget_calculator"],
                    "accepted_agent_sets": [["attraction", "weather", "itinerary", "budget"]],
                    "accepted_tool_sets": [["poi_search", "weather_query", "budget_calculator"]],
                },
            },
            {
                "case_id": "quality_budget_followup",
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
                        },
                    },
                    {
                        "turn_id": "t2",
                        "user_input": "人数改成3人，只重新计算预算，其他条件不变。",
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
            },
        ],
    }

    report = build_benchmark_dataset_quality_report(
        document=document,
        cases=document["cases"],
        expected_case_count=2,
        strict_formal=True,
    )

    assert report["schema_version"] == BENCHMARK_DATASET_QUALITY_SCHEMA_VERSION
    assert report["status"] == "passed"
    assert report["dataset"]["case_count"] == 2
    assert report["dataset"]["scenario_case_count"] == 1
    assert report["dataset"]["total_unit_count"] == 3
    assert report["coverage"]["task_distribution"]["trip_planning"] == 2
    assert report["coverage"]["task_distribution"]["budget_query"] == 1
    assert report["coverage"]["city_distribution"]["hangzhou"] == 3


def test_day6_benchmark_quality_blocks_missing_gold_bad_tools_and_chat_scope() -> None:
    document = {
        "cases": [
            {"case_id": "bad_missing_gold", "user_input": "帮我规划杭州2天旅游"},
            {
                "case_id": "bad_unknown_tool",
                "user_input": "查询杭州天气",
                "expected": {
                    "task_type": "weather_query",
                    "required_tools": ["live_weather_api"],
                    "accepted_agent_sets": [["weather"]],
                    "accepted_tool_sets": [["live_weather_api"]],
                },
            },
            {
                "case_id": "bad_chat_scope",
                "user_input": "你好，只是打个招呼。",
                "expected": {
                    "task_type": "general_chat",
                    "accepted_agent_sets": [["attraction"]],
                    "accepted_tool_sets": [["poi_search"]],
                },
            },
        ],
    }

    report = build_benchmark_dataset_quality_report(
        document=document,
        cases=document["cases"],
        strict_formal=True,
    )

    errors = "\n".join(report["errors"])
    assert report["status"] == "failed"
    assert "missing expected/gold labels" in errors
    assert "live_weather_api" in errors
    assert "general_chat must use empty accepted_agent_sets" in errors
    assert "general_chat must use empty accepted_tool_sets" in errors


def test_day6_formal_preflight_includes_benchmark_quality_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _formal_env(monkeypatch)
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(
        json.dumps(
            {"cases": [{"case_id": "no_gold", "user_input": "帮我规划杭州2天旅游"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_formal_preflight_report(
        benchmark_path=benchmark_path,
        output_dir=tmp_path / "runs",
        run_id="quality-preflight",
        require_llm_config=False,
        strict_formal=True,
    )

    assert report["status"] == "failed"
    assert report["benchmark_quality"]["schema_version"] == BENCHMARK_DATASET_QUALITY_SCHEMA_VERSION
    assert report["benchmark_quality"]["status"] == "failed"
    assert "benchmark_quality:" in "\n".join(report["errors"])


def test_day6_validate_benchmark_dataset_cli_reports_without_llm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "cli_dev_case",
                        "user_input": "帮我规划杭州2天旅游",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validate_benchmark_dataset.py",
            "--benchmark",
            str(benchmark_path),
            "--dev",
        ],
    )

    assert validate_benchmark_dataset.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "passed"
    assert report["warnings"]


def test_ctp120_dev_dataset_is_strictly_labeled_and_covered() -> None:
    benchmark_path = ROOT / "experiments" / "ctp120_dev.json"
    document, cases = load_benchmark_document(benchmark_path)

    report = build_benchmark_dataset_quality_report(
        document=document,
        cases=cases,
        expected_case_count=20,
        strict_formal=True,
    )

    assert report["status"] == "passed", report["errors"]
    assert report["warnings"] == []
    assert report["dataset"]["case_count"] == 20
    assert report["dataset"]["scenario_case_count"] == 6
    assert report["dataset"]["total_unit_count"] == 26
    assert set(report["coverage"]["task_distribution"]) == {
        "trip_planning",
        "attraction_recommendation",
        "weather_query",
        "budget_query",
        "partial_replan",
        "weather_adjustment",
        "clarification",
        "general_chat",
    }
    assert set(report["coverage"]["city_distribution"]) == {
        "beijing",
        "guilin",
        "hangzhou",
        "shenzhen",
        "xian",
    }


def test_benchmark_test_smoke_dataset_has_strict_gold_labels() -> None:
    benchmark_path = ROOT / "experiments" / "benchmark_test.json"
    document, cases = load_benchmark_document(benchmark_path)

    report = build_benchmark_dataset_quality_report(
        document=document,
        cases=cases,
        strict_formal=True,
    )

    assert report["status"] == "passed", report["errors"]
    assert report["warnings"] == []
    assert report["dataset"]["case_count"] == 8
    assert report["dataset"]["scenario_case_count"] == 2
    assert set(report["coverage"]["task_distribution"]) == set(
        report["coverage"]["recommended_task_types"]
    )
    assert not any("missing expected/gold labels" in error for error in report["errors"])


def test_benchmark_manifest_can_expand_dataset_document_case_file() -> None:
    benchmark_path = ROOT / "experiments" / "benchmark.json"
    document, cases = load_benchmark_document(benchmark_path)

    assert document["case_files"] == ["ctp120_dev.json"]
    assert len(cases) == 20
    assert cases[0]["case_id"] == "ctp_dev_001_hangzhou_full_plan"


def test_development_sized_dataset_requires_task_and_city_coverage() -> None:
    document = {
        "schema_version": "ctp-benchmark-v1",
        "dataset_id": "undercovered-dev",
        "cases": [
            {
                "case_id": f"undercovered_{index:02d}",
                "user_input": f"Hello only, no travel planning case {index}.",
                "expected": {
                    "task_type": "general_chat",
                    "accepted_agent_sets": [[]],
                    "accepted_tool_sets": [[]],
                    "forbidden_tools": ["poi_search", "weather_query", "budget_calculator"],
                },
            }
            for index in range(20)
        ],
    }

    report = build_benchmark_dataset_quality_report(
        document=document,
        cases=document["cases"],
        expected_case_count=20,
        strict_formal=True,
    )

    errors = "\n".join(report["errors"])
    assert report["status"] == "failed"
    assert "dataset task coverage is incomplete" in errors
    assert "dataset fixed-city coverage is incomplete" in errors


def test_no_change_reuse_partial_replan_must_be_explicitly_labeled() -> None:
    valid_case = {
        "case_id": "repeat_no_change",
        "turns": [
            {
                "turn_id": "t1",
                "user_input": "Plan a two day Hangzhou trip for two people starting 2026-08-01 with budget 5000 yuan.",
                "expected": {
                    "task_type": "trip_planning",
                    "required_tools": ["poi_search", "weather_query", "budget_calculator"],
                    "accepted_agent_sets": [["attraction", "weather", "itinerary", "budget"]],
                    "accepted_tool_sets": [["poi_search", "weather_query", "budget_calculator"]],
                    "hard_constraints": {
                        "duration_days": 2,
                        "min_attractions": 3,
                        "max_pois_per_day": 2,
                        "budget_limit": 5000,
                    },
                },
            },
            {
                "turn_id": "t2",
                "user_input": "Repeat exactly the same Hangzhou request with no changes.",
                "expected": {
                    "task_type": "partial_replan",
                    "replan_policy": "no_change_reuse",
                    "changed_slots": [],
                    "preserved_slots": ["destination", "duration_days", "people_count"],
                    "required_tools": [],
                    "accepted_agent_sets": [[]],
                    "accepted_tool_sets": [[]],
                },
            },
        ],
    }
    invalid_case = json.loads(json.dumps(valid_case))
    invalid_case["case_id"] = "repeat_no_change_bad"
    invalid_case["turns"][1]["expected"].pop("replan_policy")

    valid_report = build_benchmark_dataset_quality_report(
        document={"cases": [valid_case]},
        cases=[valid_case],
        strict_formal=True,
    )
    invalid_report = build_benchmark_dataset_quality_report(
        document={"cases": [invalid_case]},
        cases=[invalid_case],
        strict_formal=True,
    )

    assert valid_report["status"] == "passed", valid_report["errors"]
    assert invalid_report["status"] == "failed"
    assert "empty changed_slots" in "\n".join(invalid_report["errors"])


def _formal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPERIMENT_STRICT_MODE", "true")
    monkeypatch.setenv("EXPERIMENT_DISABLE_CACHE", "true")
    monkeypatch.setenv("TRACE_SAVE_USER_MESSAGE", "false")
    monkeypatch.setenv("LLM_TEMPERATURE", "0")
