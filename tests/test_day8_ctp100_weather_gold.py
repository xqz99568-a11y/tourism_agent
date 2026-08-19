import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.benchmark_dataset_validator import build_benchmark_dataset_quality_report
from app.core.formal_experiment_preflight import load_benchmark_document


DATASET_PATH = ROOT / "experiments" / "ctp100_formal_v2.json"
BENCHMARK_PATH = ROOT / "experiments" / "benchmark.json"


def _units(cases: list[dict]) -> list[dict]:
    flattened: list[dict] = []
    for case in cases:
        if not isinstance(case.get("turns"), list):
            flattened.append(case)
            continue
        base = {key: value for key, value in case.items() if key != "turns"}
        for turn in case["turns"]:
            unit = dict(base)
            unit.update(turn)
            unit.setdefault("case_id", case["case_id"])
            flattened.append(unit)
    return flattened


def _label(unit: dict) -> str:
    return f"{unit['case_id']}::{unit['turn_id']}" if unit.get("turn_id") else unit["case_id"]


def _expected(unit: dict) -> dict:
    return unit.get("expected") if isinstance(unit.get("expected"), dict) else {}


def _has_start_date(unit: dict) -> bool:
    expected = _expected(unit)
    hard_constraints = expected.get("hard_constraints") if isinstance(expected.get("hard_constraints"), dict) else {}
    slots = unit.get("slots") if isinstance(unit.get("slots"), dict) else {}
    return bool(slots.get("start_date") or expected.get("start_date") or hard_constraints.get("start_date"))


def test_ctp100_weather_gold_policy_passes_quality_gate() -> None:
    document, cases = load_benchmark_document(DATASET_PATH)

    report = build_benchmark_dataset_quality_report(
        document=document,
        cases=cases,
        expected_case_count=100,
        strict_formal=True,
    )

    assert report["status"] == "passed", report["errors"]
    assert report["warnings"] == []
    assert report["policy"]["day8_weather_policy_enforced"] is True


def test_explicit_date_trip_planning_requires_frozen_weather() -> None:
    document = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    date_trip_units = [
        unit
        for unit in _units(document["cases"])
        if _expected(unit).get("task_type") == "trip_planning" and _has_start_date(unit)
    ]

    assert len(date_trip_units) == 32
    for unit in date_trip_units:
        expected = _expected(unit)
        assert "weather_query" in expected["required_tools"], _label(unit)
        assert "weather_query" in expected["accepted_tool_sets"][0], _label(unit)
        assert "weather" in expected["accepted_agent_sets"][0], _label(unit)
        assert "weather_query" not in expected.get("forbidden_tools", []), _label(unit)
        assert expected["weather_required"] is True, _label(unit)
        assert expected["weather_date_policy"] == "explicit_date_use_qweather_snapshot", _label(unit)
        assert expected["expected_weather_coverage_status"] in {"full", "partial", "out_of_range"}, _label(unit)


def test_no_date_trip_planning_forbids_weather_and_requires_predeparture_reminder() -> None:
    document = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    no_date_trip_units = [
        unit
        for unit in _units(document["cases"])
        if _expected(unit).get("task_type") == "trip_planning" and not _has_start_date(unit)
    ]

    assert len(no_date_trip_units) == 18
    for unit in no_date_trip_units:
        expected = _expected(unit)
        assert "weather_query" not in expected["required_tools"], _label(unit)
        assert "weather_query" not in expected["accepted_tool_sets"][0], _label(unit)
        assert "weather_query" in expected["forbidden_tools"], _label(unit)
        assert expected["weather_required"] is False, _label(unit)
        assert expected["weather_date_policy"] == "no_date_no_specific_weather_for_trip_plan", _label(unit)
        assert expected["no_date_weather_reminder_required"] is True, _label(unit)


def test_ctp100_v2_039_is_weather_query_not_general_chat() -> None:
    document = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    case = next(case for case in document["cases"] if case["case_id"] == "ctp100_v2_039")
    expected = _expected(case)

    assert case["task_type"] == "weather_query"
    assert case["slots"]["duration_days"] == 1
    assert expected["task_type"] == "weather_query"
    assert expected["required_tools"] == ["weather_query"]
    assert expected["accepted_agent_sets"] == [["weather"]]
    assert expected["accepted_tool_sets"] == [["weather_query"]]
    assert expected["forbidden_tools"] == ["poi_search", "budget_calculator"]


def test_weather_adjustment_cases_query_first_turn_and_reuse_second_turn_weather() -> None:
    document = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    cases = {
        case["case_id"]: case
        for case in document["cases"]
        if "ctp100_v2_070" <= case["case_id"] <= "ctp100_v2_074"
    }

    assert set(cases) == {f"ctp100_v2_{index:03d}" for index in range(70, 75)}
    for case in cases.values():
        t1, t2 = case["turns"]
        t1_expected = _expected(t1)
        t2_expected = _expected(t2)

        assert "weather_query" in t1_expected["required_tools"], case["case_id"]
        assert "weather" in t1_expected["accepted_agent_sets"][0], case["case_id"]
        assert t1_expected["weather_required"] is True, case["case_id"]
        assert t2_expected["required_tools"] == ["budget_calculator"], case["case_id"]
        assert t2_expected["accepted_agent_sets"] == [["itinerary", "budget"]], case["case_id"]
        assert t2_expected["accepted_tool_sets"] == [["budget_calculator"]], case["case_id"]
        assert t2_expected["forbidden_tools"] == [
            "poi_search",
            "weather_query",
        ], case["case_id"]
        assert t2_expected["partial_replan_policy"] == (
            "weather_adjustment_itinerary_budget"
        ), case["case_id"]
        assert t2_expected["weather_reuse_expected"] is True, case["case_id"]
        assert t2_expected["weather_reuse_source_turn_id"] == "t1", case["case_id"]
        assert t2_expected["weather_query_must_not_rerun"] is True, case["case_id"]


def test_weather_sensitive_partial_replans_keep_weather_required() -> None:
    document = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    partial_units = [
        unit
        for unit in _units(document["cases"])
        if _expected(unit).get("task_type") == "partial_replan"
        and set(_expected(unit).get("changed_slots") or []) & {"start_date", "duration_days"}
        and _has_start_date(unit)
    ]

    assert len(partial_units) == 8
    for unit in partial_units:
        expected = _expected(unit)
        assert "weather_query" in expected["required_tools"], _label(unit)
        assert "weather_query" in expected["accepted_tool_sets"][0], _label(unit)
        assert "weather" in expected["accepted_agent_sets"][0], _label(unit)
        assert expected["weather_required"] is True, _label(unit)
        assert expected["weather_date_policy"] == "explicit_date_use_qweather_snapshot", _label(unit)


def test_benchmark_manifest_points_to_weather_fixed_formal_dataset() -> None:
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    benchmark = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))

    assert dataset["dataset_version"] == "2026-08-18-day8-formal-v2-weather-gold-fix"
    assert benchmark["dataset_version"] == dataset["dataset_version"]
    assert benchmark["case_files"] == ["ctp100_formal_v2.json"]
