import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.core.experiment_runner import (  # noqa: E402
    RESEARCH_AGENT_DECISION_SCHEMA_VERSION,
    RESEARCH_TASK_TYPE_ALIASES,
    ExperimentRunner,
)
from app.core.no_date_weather_policy import NO_DATE_WEATHER_REMINDER  # noqa: E402


FORMAL_CTP100_V2_PATH = ROOT / "experiments" / "ctp100_formal_v2.json"
KEY_DAY8_TASK1_SCENARIOS = {
    "ctp100_v2_064",
    "ctp100_v2_087",
    "ctp100_v2_070",
    "ctp100_v2_071",
    "ctp100_v2_072",
    "ctp100_v2_073",
    "ctp100_v2_074",
}


class _AgentJSONLLM:
    async def chat(self, messages, tools=None):
        payload = self._agent_payload(messages)
        content = self._agent_decision_content(payload) if payload else "tool based answer"
        return SimpleNamespace(content=content, tool_calls=[], usage={"total_tokens": 1})

    def _agent_payload(self, messages):
        try:
            payload = json.loads(messages[-1].content)
        except (json.JSONDecodeError, TypeError, AttributeError, IndexError):
            return {}
        return payload if isinstance(payload, dict) and payload.get("agent_name") else {}

    def _agent_decision_content(self, payload):
        agent_name = str(payload.get("agent_name") or "")
        task_slots = payload.get("task_slots") if isinstance(payload.get("task_slots"), dict) else {}
        tool_evidence = payload.get("tool_evidence") if isinstance(payload.get("tool_evidence"), dict) else {}
        attractions = self._attractions(tool_evidence)
        selected_ids = [
            str(item.get("poi_id"))
            for item in attractions[:4]
            if item.get("poi_id")
        ]
        days = int(task_slots.get("duration_days") or 2)

        if agent_name == "attraction":
            decisions = {
                "selected_poi_ids": selected_ids,
                "ranking_reason": "deterministic acceptance evidence order",
            }
        elif agent_name == "weather":
            decisions = {"risk_days": [], "adjustment_required": False}
        elif agent_name == "itinerary":
            decisions = {
                "daily_itinerary": [
                    {
                        "day": day,
                        "attraction_poi_ids": selected_ids[(day - 1) * 2 : day * 2]
                        or selected_ids[:1],
                        "notes": f"deterministic acceptance itinerary day {day}",
                    }
                    for day in range(1, days + 1)
                ]
            }
        elif agent_name == "budget":
            budget_data = self._tool_data(tool_evidence.get("budget_calculator"))
            decisions = {
                "feasibility": "feasible",
                "budget_notes": "deterministic acceptance budget decision",
                "recommended_total": budget_data.get("total"),
            }
        else:
            decisions = {}

        return json.dumps(
            {
                "schema_version": RESEARCH_AGENT_DECISION_SCHEMA_VERSION,
                "agent_name": agent_name,
                "summary": f"{agent_name} deterministic acceptance decision",
                "decisions": decisions,
                "risks": [],
                "confidence": 1.0,
            },
            ensure_ascii=False,
        )

    def _tool_data(self, result):
        if not isinstance(result, dict):
            return {}
        data = result.get("data")
        return data if isinstance(data, dict) else {}

    def _attractions(self, tool_evidence):
        data = self._tool_data(tool_evidence.get("poi_search"))
        attractions = data.get("attractions") if isinstance(data, dict) else []
        return [item for item in attractions or [] if isinstance(item, dict)]


def test_day8_task1_key_runner_acceptance_cases_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _load_formal_document()
    subset = _document_subset(document, KEY_DAY8_TASK1_SCENARIOS)

    results = _run_adaptive_multi_agent_runner(
        subset,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        run_id="day8_task1_key_runner_acceptance",
    )

    _assert_runner_acceptance_results(
        results,
        subset,
        expected_turn_count=14,
        expected_no_date_reminder_count=1,
    )
    _assert_day8_task1_named_cases(results)


@pytest.mark.skipif(
    os.environ.get("RUN_DAY8_FULL_RUNNER_ACCEPTANCE") != "1",
    reason=(
        "set RUN_DAY8_FULL_RUNNER_ACCEPTANCE=1 to execute the full "
        "130-turn adaptive Runner acceptance gate"
    ),
)
def test_day8_task1_full_130_turn_runner_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _load_formal_document()

    results = _run_adaptive_multi_agent_runner(
        document,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        run_id="day8_task1_full_130_turn_runner_acceptance",
    )

    _assert_runner_acceptance_results(
        results,
        document,
        expected_turn_count=130,
        expected_no_date_reminder_count=18,
    )
    _assert_day8_task1_named_cases(results)


def _run_adaptive_multi_agent_runner(
    document: dict,
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    run_id: str,
) -> list[dict]:
    monkeypatch.setenv("EXPERIMENT_STRICT_MODE", "true")
    monkeypatch.setenv("EXPERIMENT_DISABLE_CACHE", "true")
    monkeypatch.setenv("TRACE_SAVE_USER_MESSAGE", "false")
    monkeypatch.setenv("EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER", "true")
    monkeypatch.setenv("LLM_TEMPERATURE", "0")
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
    monkeypatch.setenv("LLM_TIMEOUT", "60")
    monkeypatch.setenv("LLM_RETRY_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("EXPERIMENT_RESULT_HARD_TIMEOUT_SECONDS", "900")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "minimal")

    benchmark_path = tmp_path / f"{run_id}.json"
    benchmark_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    runner = ExperimentRunner(
        trace_dir=tmp_path / "traces",
        output_dir=tmp_path / "results",
        llm_factory=_AgentJSONLLM,
    )
    return runner.run_benchmark(
        benchmark_path,
        methods=["adaptive_multi_agent"],
        repeats=1,
        run_id=run_id,
    )


def _assert_runner_acceptance_results(
    results: list[dict],
    document: dict,
    *,
    expected_turn_count: int,
    expected_no_date_reminder_count: int,
) -> None:
    expected_by_label = _expected_turns_by_label(document)
    results_by_label = _results_by_label(results)
    assert len(results) == expected_turn_count
    assert set(results_by_label) == set(expected_by_label)

    no_date_reminder_labels = [
        label
        for label, expected in expected_by_label.items()
        if _requires_no_date_weather_reminder(expected)
    ]
    assert len(no_date_reminder_labels) == expected_no_date_reminder_count

    for label, expected in expected_by_label.items():
        result = results_by_label[label]
        output = result["output"]
        expected_task_type = _canonical_task_type(expected.get("task_type"))

        assert _canonical_task_type(output.get("task_type")) == expected_task_type, label
        assert result["method"] == "adaptive_multi_agent", label
        if expected_task_type == "clarification":
            assert result["status"] == "clarification", label
            assert output["execution_status"] == "clarification", label
        else:
            assert result["status"] == "completed", label
            assert output["execution_status"] == "completed", label

        planned_agents = _names(output.get("planned_agents"))
        used_agents = _names(output.get("used_agents"))
        accepted_agent_sets = _accepted_sets(expected, "accepted_agent_sets")
        assert planned_agents in accepted_agent_sets, label
        assert used_agents in accepted_agent_sets, label

        planned_tools = _names(output.get("planned_tools"))
        called_tools = _called_tool_names(output)
        accepted_tool_sets = _accepted_sets(
            expected,
            "accepted_tool_sets",
            default=_names(expected.get("required_tools")),
        )
        assert planned_tools in accepted_tool_sets, label
        assert called_tools in accepted_tool_sets, label

        for forbidden_tool in _names(expected.get("forbidden_tools")):
            assert forbidden_tool not in planned_tools, label
            assert forbidden_tool not in called_tools, label

        if expected_task_type in {"trip_planning", "partial_replan", "weather_adjustment"}:
            assert output.get("daily_itinerary"), label

        if _requires_no_date_weather_reminder(expected):
            assert NO_DATE_WEATHER_REMINDER in str(output.get("final_answer") or ""), label
            assert "weather_query" not in planned_tools, label
            assert "weather_query" not in called_tools, label
            assert output.get("weather") in (None, {}, []), label


def _assert_day8_task1_named_cases(results: list[dict]) -> None:
    by_label = _results_by_label(results)
    case_064_t2 = by_label["ctp100_v2_064::t2"]["output"]
    assert case_064_t2["task_type"] == "partial_replan"
    assert _names(case_064_t2["planned_agents"]) == [
        "attraction",
        "itinerary",
        "budget",
    ]
    assert _names(case_064_t2["planned_tools"]) == [
        "poi_search",
        "budget_calculator",
    ]
    assert _called_tool_names(case_064_t2) == ["poi_search", "budget_calculator"]

    case_087_t2_result = by_label["ctp100_v2_087::t2"]
    case_087_t2 = case_087_t2_result["output"]
    assert case_087_t2["task_type"] == "partial_replan"
    assert _names(case_087_t2["planned_agents"]) == ["itinerary", "budget"]
    assert _names(case_087_t2["planned_tools"]) == ["budget_calculator"]
    assert _called_tool_names(case_087_t2) == ["budget_calculator"]
    assert "attraction" in _names(
        case_087_t2_result["metrics"].get("m3_reused_agents")
    )

    for case_id in (
        "ctp100_v2_070",
        "ctp100_v2_071",
        "ctp100_v2_072",
        "ctp100_v2_073",
        "ctp100_v2_074",
    ):
        label = f"{case_id}::t2"
        result = by_label[label]
        output = result["output"]
        assert output["task_type"] == "weather_adjustment", label
        assert _names(output["planned_agents"]) == ["itinerary", "budget"], label
        assert _names(output["planned_tools"]) == ["budget_calculator"], label
        assert _called_tool_names(output) == ["budget_calculator"], label
        reused_agents = _names(result["metrics"].get("m3_reused_agents"))
        assert {"attraction", "weather"} <= set(reused_agents), label


def _load_formal_document() -> dict:
    return json.loads(FORMAL_CTP100_V2_PATH.read_text(encoding="utf-8"))


def _document_subset(document: dict, scenario_ids: set[str]) -> dict:
    selected_cases = [
        case
        for case in document["cases"]
        if str(case.get("case_id") or case.get("scenario_id") or case.get("id"))
        in scenario_ids
    ]
    subset = {key: value for key, value in document.items() if key != "cases"}
    subset["cases"] = selected_cases
    subset["case_count"] = len(selected_cases)
    subset["turn_count"] = sum(
        len(case.get("turns"))
        if isinstance(case.get("turns"), list)
        else 1
        for case in selected_cases
    )
    return subset


def _expected_turns_by_label(document: dict) -> dict[str, dict]:
    expected: dict[str, dict] = {}
    for case in document["cases"]:
        case_id = str(case.get("case_id") or case.get("scenario_id") or case.get("id"))
        turns = case.get("turns")
        if isinstance(turns, list) and turns:
            for index, turn in enumerate(turns):
                turn_id = str(turn.get("turn_id") or turn.get("id") or f"turn_{index + 1:02d}")
                expected[f"{case_id}::{turn_id}"] = (
                    turn.get("expected") if isinstance(turn.get("expected"), dict) else {}
                )
            continue
        expected[case_id] = (
            case.get("expected") if isinstance(case.get("expected"), dict) else {}
        )
    return expected


def _results_by_label(results: list[dict]) -> dict[str, dict]:
    by_label: dict[str, dict] = {}
    for result in results:
        case_id = str(result.get("scenario_id") or result.get("case_id"))
        turn_id = result.get("turn_id")
        label = f"{case_id}::{turn_id}" if turn_id is not None else case_id
        by_label[label] = result
    return by_label


def _canonical_task_type(value: object) -> str:
    raw = str(value or "").strip()
    return RESEARCH_TASK_TYPE_ALIASES.get(raw, raw)


def _requires_no_date_weather_reminder(expected: dict) -> bool:
    return (
        expected.get("no_date_weather_reminder_required") is True
        or expected.get("weather_date_policy")
        == "no_date_no_specific_weather_for_trip_plan"
    )


def _accepted_sets(
    expected: dict,
    key: str,
    *,
    default: list[str] | None = None,
) -> list[list[str]]:
    value = expected.get(key)
    if isinstance(value, list) and all(isinstance(item, list) for item in value):
        return [_names(item) for item in value]
    return [_names(default or [])]


def _called_tool_names(output: dict) -> list[str]:
    names: list[str] = []
    for item in output.get("called_tools") or []:
        if isinstance(item, dict):
            name = item.get("tool_name") or item.get("name")
        else:
            name = item
        if name:
            names.append(str(name))
    return names


def _names(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if value is None:
        return []
    return [str(value)]
