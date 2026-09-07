import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core import experiment_result_worker  # noqa: E402
from app.core.goal_state_scheduler import (  # noqa: E402
    build_goal_state_result_fingerprints,
)
from experiments.m3_core_ablation_variants import (  # noqa: E402
    M3_CORE_ABLATION_METHODS,
    M3_NO_PROPAGATION_METHOD,
    M3_NO_STATE_METHOD,
    M3CoreAblationRunner,
)

DATASET = ROOT / "experiments" / "ctp100_formal_v2.json"


def _successful_previous_state(slots: dict) -> dict:
    city = slots["destination"]
    start_date = slots["start_date"]
    days = slots["duration_days"]
    people = slots["people_count"]
    tool_results = {
        "poi_search": {
            "tool_name": "poi_search",
            "status": "success",
            "success": True,
            "input": {
                "city": city,
                "preferences": slots.get("preferences") or [],
                "people": "general",
                "limit": 4,
            },
            "data": {"attractions": [{"poi_id": f"{city}-poi-1", "name": "POI 1", "city": city}]},
        },
        "weather_query": {
            "tool_name": "weather_query",
            "status": "success",
            "success": True,
            "input": {"city": city, "date": start_date, "days": days},
            "data": {"daily_weather": [{"date": start_date, "condition": "sunny"}]},
        },
        "budget_calculator": {
            "tool_name": "budget_calculator",
            "status": "success",
            "success": True,
            "input": {
                "city": city,
                "days": days,
                "people_count": people,
                "attractions": [f"{city}-poi-1"],
            },
            "data": {"total": 1000},
        },
    }
    daily_itinerary = [{"day": 1, "attractions": [{"poi_id": f"{city}-poi-1"}]}]
    state = {
        "schema_version": "ctp-method-previous-state-v1",
        "case_id": "core-ablation-case",
        "scenario_id": "core-ablation-case",
        "turn_id": "t1",
        "turn_index": 0,
        "method": M3_NO_PROPAGATION_METHOD,
        "status": "completed",
        "execution_status": "completed",
        "slots": dict(slots),
        "available_results": {
            "attraction": True,
            "weather": True,
            "itinerary": True,
            "budget": True,
        },
        "tool_results": tool_results,
        "daily_itinerary": daily_itinerary,
    }
    state["result_fingerprints"] = build_goal_state_result_fingerprints(
        slots=slots,
        tool_results=tool_results,
        daily_itinerary=daily_itinerary,
        result_agents=("attraction", "weather", "itinerary", "budget"),
    )
    return state


def test_core_ablation_methods_are_supplementary_not_main_methods(tmp_path: Path) -> None:
    runner = M3CoreAblationRunner(trace_dir=tmp_path / "traces")

    assert set(M3_CORE_ABLATION_METHODS).isdisjoint(runner.METHODS)
    assert runner._normalize_method("m3-no-state") == M3_NO_STATE_METHOD
    assert runner._normalize_method("m3-no-propagation") == M3_NO_PROPAGATION_METHOD


def test_no_state_strips_structured_state_gold_and_structured_history(
    tmp_path: Path,
) -> None:
    runner = M3CoreAblationRunner(trace_dir=tmp_path / "traces")
    raw_case = {
        "case_id": "core-ablation-case",
        "user_input": "总预算上限改成4000元，其他条件不要动。",
        "dialogue_history": [
            {"role": "user", "content": "明天去杭州玩3天。", "slots": {"leak": 1}},
            {
                "role": "assistant",
                "content": "上一轮普通文本回答。",
                "output": {"daily_itinerary": [{"gold": "must-not-leak"}]},
            },
        ],
        "previous_state": {"slots": {"destination": "hangzhou"}},
        "method_previous_state": {"slots": {"destination": "hangzhou"}},
        "slots": {"destination": "gold-city"},
        "expected": {"task_type": "partial_replan"},
        "task_type": "partial_replan",
        "evaluation_mode": "end_to_end",
    }

    visible = runner._case_visible_to_generation(raw_case, M3_NO_STATE_METHOD)
    scheduler = runner._stateless_scheduler_metadata(visible)

    assert visible["current_turn_slots"] == {
        "budget_amount": 4000,
        "budget_basis": "total",
    }
    for forbidden in (
        "previous_state",
        "method_previous_state",
        "slots",
        "expected",
        "task_type",
    ):
        assert forbidden not in visible
    assert all(set(item) == {"role", "content"} for item in visible["dialogue_history"])
    assert "ticket" not in scheduler
    assert scheduler["decision"]["reused_agents"] == []
    assert scheduler["ablation"]["structured_goal_state_ticket_used"] is False
    assert scheduler["ablation"]["method_previous_state_visible"] is False
    assert scheduler["ablation"]["previous_slots_visible"] is False


def test_no_state_executes_without_previous_artifacts_or_reuse(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured = {}

    async def fake_research_multi_agent(**kwargs):
        captured.update(kwargs)
        return {"method": kwargs["method"]}

    runner = M3CoreAblationRunner(trace_dir=tmp_path / "traces")
    monkeypatch.setattr(runner, "_run_research_multi_agent", fake_research_multi_agent)
    result = asyncio.run(
        runner._run_adaptive_multi_agent_no_state(
            {
                "case_id": "core-ablation-case",
                "user_input": "总预算上限改成4000元，其他条件不要动。",
                "dialogue_history": [
                    {"role": "user", "content": "明天去杭州玩3天。"},
                    {"role": "assistant", "content": "上一轮普通文本回答。"},
                ],
                "previous_state": _successful_previous_state(
                    {
                        "destination": "hangzhou",
                        "start_date": "2026-08-07",
                        "duration_days": 3,
                        "people_count": 2,
                        "budget_amount": 5000,
                    }
                ),
                "evaluation_mode": "end_to_end",
            },
            "no-state-request",
        )
    )

    assert result["method"] == M3_NO_STATE_METHOD
    assert captured["method"] == M3_NO_STATE_METHOD
    assert captured["planned_agents"] == ["budget"]
    assert captured["planned_tools"] == ["budget_calculator"]
    assert captured["initial_tool_results"] == {}
    assert "previous_state" not in captured["case"]
    assert "method_previous_state" not in captured["case"]
    assert "ticket" not in captured["scheduler_metadata"]


def test_no_state_routes_frozen_multiturn_scope_from_visible_text_only(
    tmp_path: Path,
) -> None:
    runner = M3CoreAblationRunner(trace_dir=tmp_path / "traces")
    document = json.loads(DATASET.read_text(encoding="utf-8"))
    task_types = Counter()
    selected = 0

    for scenario in document["cases"]:
        turns = scenario.get("turns")
        if not isinstance(turns, list) or len(turns) != 2:
            continue
        selected += 1
        visible = runner._stateless_generation_case(
            {
                **turns[1],
                "case_id": scenario["case_id"],
                "dialogue_history": [
                    {"role": "user", "content": turns[0]["user_input"]},
                    {"role": "assistant", "content": "上一轮普通文本回答。"},
                ],
                "previous_state": {"slots": {"forbidden": True}},
                "expected": turns[1].get("expected") or {},
                "evaluation_mode": "end_to_end",
            }
        )
        scheduler = runner._stateless_scheduler_metadata(visible)
        task_types[scheduler["stateless_understanding"]["task_type"]] += 1
        assert scheduler["decision"]["planned_agents"]
        assert scheduler["decision"]["reused_agents"] == []
        assert "ticket" not in scheduler
        assert "previous_state" not in visible
        assert "expected" not in visible

    assert selected == 30
    assert task_types == {"partial_replan": 25, "weather_adjustment": 5}


def test_no_state_scenario_audit_reports_history_without_structured_state(
    tmp_path: Path,
) -> None:
    runner = M3CoreAblationRunner(trace_dir=tmp_path / "traces")
    result = {}
    previous_state = {
        "schema_version": "ctp-method-previous-state-v1",
        "method": M3_NO_STATE_METHOD,
        "turn_id": "t1",
        "turn_index": 0,
    }

    runner._attach_scenario_result_metadata(
        result,
        scenario_id="core-ablation-case",
        turn_id="t2",
        turn_index=1,
        turn_count=2,
        target_turn=True,
        previous_state=previous_state,
        method=M3_NO_STATE_METHOD,
    )

    assert result["method_previous_state_policy"] == (
        "role_content_dialogue_history_only_no_structured_state"
    )
    assert result["previous_state_provided"] is False
    assert result["previous_state_schema_version"] is None
    assert result["previous_state_is_method_local"] is True
    assert result["previous_state_is_prior_turn"] is True
    audit = result["method_previous_state_audit"]
    assert audit["structured_previous_state_visible"] is False
    assert audit["orchestrator_prior_result_available_for_history"] is True
    assert audit["orchestrator_prior_result_is_prior_turn"] is True
    assert audit["dialogue_history_is_method_local"] is True


def test_no_propagation_keeps_state_and_reuses_healthy_downstream_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured = {}

    async def fake_research_multi_agent(**kwargs):
        captured.update(kwargs)
        return {"method": kwargs["method"]}

    previous_slots = {
        "destination": "hangzhou",
        "start_date": "2026-08-07",
        "duration_days": 3,
        "people_count": 2,
        "budget_amount": 5000,
        "preferences": ["classic"],
    }
    previous_state = _successful_previous_state(previous_slots)
    case = {
        "case_id": "core-ablation-case",
        "user_input": "偏好改成自然风光，其他条件不变。",
        "current_turn_slots": {"preferences": ["nature"]},
        "previous_state": previous_state,
        "method_previous_state": previous_state,
        "evaluation_mode": "end_to_end",
    }
    runner = M3CoreAblationRunner(trace_dir=tmp_path / "traces")
    monkeypatch.setattr(runner, "_run_research_multi_agent", fake_research_multi_agent)

    result = asyncio.run(
        runner._run_adaptive_multi_agent_no_propagation(
            case,
            "no-propagation-request",
        )
    )

    scheduler = captured["scheduler_metadata"]
    decision = scheduler["decision"]
    assert result["method"] == M3_NO_PROPAGATION_METHOD
    assert captured["planned_agents"] == ["attraction"]
    assert captured["planned_tools"] == ["poi_search"]
    assert decision["invalidation_propagation_enabled"] is False
    assert decision["initial_invalidated_agents"] == ["attraction"]
    assert decision["propagated_invalidated_agents"] == []
    assert decision["final_invalidated_agents"] == ["attraction"]
    assert decision["propagation_candidates"] == ["itinerary", "budget"]
    assert decision["reused_agents"] == ["weather", "itinerary", "budget"]
    assert set(captured["initial_tool_results"]) == {
        "weather_query",
        "budget_calculator",
    }
    assert scheduler["reuse_execution"]["reused_agent_results"] == [
        "weather",
        "itinerary",
        "budget",
    ]
    assert scheduler["ablation"]["downstream_invalidation_propagation_enabled"] is False
    assert captured["case"]["slots"]["preferences"] == ["nature"]


def test_no_propagation_does_not_reuse_failed_downstream_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured = {}

    async def fake_research_multi_agent(**kwargs):
        captured.update(kwargs)
        return {"method": kwargs["method"]}

    previous_slots = {
        "destination": "hangzhou",
        "start_date": "2026-08-07",
        "duration_days": 3,
        "people_count": 2,
        "budget_amount": 5000,
        "preferences": ["classic"],
    }
    previous_state = _successful_previous_state(previous_slots)
    previous_state["tool_results"]["budget_calculator"].update(
        {
            "status": "failed",
            "success": False,
            "error": {"message": "previous budget failed"},
        }
    )
    runner = M3CoreAblationRunner(trace_dir=tmp_path / "traces")
    monkeypatch.setattr(runner, "_run_research_multi_agent", fake_research_multi_agent)

    asyncio.run(
        runner._run_adaptive_multi_agent_no_propagation(
            {
                "case_id": "core-ablation-case",
                "user_input": "偏好改成自然风光，其他条件不变。",
                "current_turn_slots": {"preferences": ["nature"]},
                "previous_state": previous_state,
                "evaluation_mode": "end_to_end",
            },
            "no-propagation-failed-result",
        )
    )

    decision = captured["scheduler_metadata"]["decision"]
    assert captured["planned_agents"] == ["attraction", "budget"]
    assert decision["initial_invalidated_agents"] == ["attraction", "budget"]
    assert decision["reused_agents"] == ["weather", "itinerary"]
    assert "budget_calculator" not in captured["initial_tool_results"]


@pytest.mark.parametrize("method", M3_CORE_ABLATION_METHODS)
def test_result_worker_selects_core_ablation_runner(method: str) -> None:
    runner_class = experiment_result_worker._runner_class_for_payload({"method": method})

    assert runner_class is M3CoreAblationRunner
