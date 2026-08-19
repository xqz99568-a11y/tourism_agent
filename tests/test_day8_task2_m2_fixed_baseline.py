import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.experiment_method_input import build_generation_case, parse_visible_request_slots
from app.core.experiment_runner import ExperimentRunner
from app.core.goal_state_scheduler import build_goal_state_ticket


FORMAL_DATASET_PATH = ROOT / "experiments" / "ctp100_formal_v2.json"


def test_m2_fixed_templates_match_formal_ctp100_stsr_scopes() -> None:
    """M2's fixed templates must not contradict the frozen formal gold scopes."""
    document = json.loads(FORMAL_DATASET_PATH.read_text(encoding="utf-8"))
    runner = ExperimentRunner(trace_dir=ROOT / "experiments" / "results" / "tmp_debug" / "task2_static_traces")
    checked_turns = 0

    for case in document["cases"]:
        previous_state = None
        for turn in case.get("turns") or [case]:
            current_slots = parse_visible_request_slots(turn["user_input"])
            ticket = build_goal_state_ticket(
                user_input=turn["user_input"],
                current_slots=current_slots,
                previous_state=previous_state,
            )
            agents, tools, _reasons = runner._m2_fixed_template_for_ticket(ticket.to_dict())
            expected = turn.get("expected") or {}

            if expected.get("accepted_agent_sets"):
                assert agents in expected["accepted_agent_sets"], (
                    case["case_id"],
                    turn.get("turn_id"),
                    ticket.task_type,
                    ticket.changed_slots,
                    agents,
                    expected["accepted_agent_sets"],
                )
            if expected.get("accepted_tool_sets"):
                assert tools in expected["accepted_tool_sets"], (
                    case["case_id"],
                    turn.get("turn_id"),
                    ticket.task_type,
                    ticket.changed_slots,
                    tools,
                    expected["accepted_tool_sets"],
                )
            assert not (set(expected.get("forbidden_tools") or []) & set(tools)), (
                case["case_id"],
                turn.get("turn_id"),
                tools,
                expected.get("forbidden_tools"),
            )
            previous_state = {"slots": ticket.current_slots}
            checked_turns += 1

    assert checked_turns == 130


def test_generation_case_preserves_user_supplied_weather_change_without_gold() -> None:
    generation_case = build_generation_case(
        {
            "case_id": "visible-weather-change",
            "user_input": "The second day becomes rain. Adjust the itinerary.",
            "weather_change": {"scenario_type": "rain", "affected_days": [2]},
            "expected": {
                "task_type": "weather_adjustment",
                "required_tools": ["budget_calculator"],
            },
            "gold": {"answer": "hidden"},
        },
        "fixed_multi_agent",
    )

    assert generation_case["weather_change"] == {
        "scenario_type": "rain",
        "affected_days": [2],
    }
    assert generation_case["method_input"]["weather_change"] == {
        "scenario_type": "rain",
        "affected_days": [2],
    }
    assert "expected" not in generation_case
    assert "gold" not in generation_case
