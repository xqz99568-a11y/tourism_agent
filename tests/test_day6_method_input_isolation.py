import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.experiment_method_input import (
    METHOD_INPUT_SCHEMA_VERSION,
    build_generation_case,
    contains_evaluator_only_generation_fields,
    parse_visible_request_slots,
)
from app.core.experiment_runner import RESEARCH_AGENT_DECISION_SCHEMA_VERSION, ExperimentRunner


def test_generation_case_removes_gold_fields_and_parses_visible_request() -> None:
    case = {
        "case_id": "day6-visible-input",
        "user_input": "帮我规划杭州3天2人旅游，2026-08-01出发，预算1000元，偏自然风景。",
        "slots": {
            "destination": "GOLD_CITY_SHOULD_NOT_LEAK",
            "duration_days": 5,
            "people_count": 9,
        },
        "expected": {"secret": "EXPECTED_SHOULD_NOT_LEAK"},
        "gold": {"secret": "GOLD_SHOULD_NOT_LEAK"},
        "accepted_agent_sets": [["weather"]],
        "hard_constraints": {"secret": "HARD_CONSTRAINT_SHOULD_NOT_LEAK"},
    }

    generation_case = build_generation_case(case, "adaptive_multi_agent")
    parsed_slots = generation_case["method_input"]["parsed_slots"]
    serialized = json.dumps(generation_case, ensure_ascii=False, sort_keys=True)

    assert generation_case["method_input"]["schema_version"] == METHOD_INPUT_SCHEMA_VERSION
    assert contains_evaluator_only_generation_fields(generation_case) is False
    assert "slots" not in generation_case
    assert "expected" not in generation_case
    assert "gold" not in generation_case
    assert "GOLD_CITY_SHOULD_NOT_LEAK" not in serialized
    assert "EXPECTED_SHOULD_NOT_LEAK" not in serialized
    assert parsed_slots["destination"] == "hangzhou"
    assert parsed_slots["duration_days"] == 3
    assert parsed_slots["people_count"] == 2
    assert parsed_slots["start_date"] == "2026-08-01"
    assert parsed_slots["budget_amount"] == 1000
    assert parsed_slots["preferences"] == ["nature"]


def test_visible_request_parser_supports_common_chinese_and_english_slots() -> None:
    chinese = parse_visible_request_slots("8月1日从北京出发玩两天，情侣两人，预算2000元")
    english = parse_visible_request_slots(
        "Plan a two-day Hangzhou trip on 2026-08-01 for two people within budget 10000"
    )
    followup = parse_visible_request_slots("把两天改成三天，其他条件不变")

    assert chinese["destination"] == "beijing"
    assert chinese["duration_days"] == 2
    assert chinese["people_count"] == 2
    assert chinese["start_date"] == "2026-08-01"
    assert chinese["budget_amount"] == 2000
    assert chinese["traveler_group"] == "couple"

    assert english["destination"] == "hangzhou"
    assert english["duration_days"] == 2
    assert english["people_count"] == 2
    assert english["start_date"] == "2026-08-01"
    assert english["budget_amount"] == 10000
    assert followup["duration_days"] == 3


def test_builtin_m2_m3_use_parsed_method_input_not_gold_slots(tmp_path: Path) -> None:
    class SpyLLM:
        def __init__(self) -> None:
            self.messages = []

        async def chat(self, messages, tools=None):
            self.messages.append([message.to_dict() for message in messages])
            try:
                payload = json.loads(messages[-1].content)
            except (json.JSONDecodeError, TypeError, AttributeError, IndexError):
                payload = {}
            content = (
                self._agent_decision_content(payload)
                if isinstance(payload, dict) and payload.get("agent_name")
                else "visible-input answer"
            )
            return SimpleNamespace(content=content, tool_calls=[], usage={"total_tokens": 1})

        def _agent_decision_content(self, payload):
            agent_name = str(payload.get("agent_name") or "")
            tool_evidence = payload.get("tool_evidence") if isinstance(payload.get("tool_evidence"), dict) else {}
            attractions = self._attractions(tool_evidence)
            selected_ids = [str(item.get("poi_id")) for item in attractions[:6] if item.get("poi_id")]
            task_slots = payload.get("task_slots") if isinstance(payload.get("task_slots"), dict) else {}
            days = int(task_slots.get("duration_days") or 3)
            if agent_name == "attraction":
                decisions = {"selected_poi_ids": selected_ids}
            elif agent_name == "weather":
                decisions = {"risk_days": [], "adjustment_required": False}
            elif agent_name == "itinerary":
                decisions = {
                    "daily_itinerary": [
                        {
                            "day": day,
                            "attraction_poi_ids": selected_ids[(day - 1) * 2 : day * 2] or selected_ids[:1],
                        }
                        for day in range(1, days + 1)
                    ]
                }
            elif agent_name == "budget":
                decisions = {"feasibility": "feasible", "budget_notes": "visible input test"}
            else:
                decisions = {}
            return json.dumps(
                {
                    "schema_version": RESEARCH_AGENT_DECISION_SCHEMA_VERSION,
                    "agent_name": agent_name,
                    "summary": f"{agent_name} visible input decision",
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

    llm = SpyLLM()
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=lambda: llm)
    case = {
        "case_id": "day6-no-gold-leak",
        "user_input": "帮我规划杭州3天2人旅游，2026-08-01出发，预算1000元。",
        "slots": {
            "destination": "beijing",
            "duration_days": 5,
            "people_count": 9,
            "start_date": "2026-09-09",
        },
        "expected": {"secret": "EXPECTED_SECRET_SHOULD_NOT_LEAK"},
        "gold": {"secret": "GOLD_SECRET_SHOULD_NOT_LEAK"},
    }

    m2 = runner.run(case, method="fixed_multi_agent")
    m3 = runner.run(case, method="adaptive_multi_agent")
    prompt_payload = json.dumps(llm.messages, ensure_ascii=False, sort_keys=True)

    assert m2["raw_output"]["tool_results"]["poi_search"]["input"]["city"] == "hangzhou"
    assert m2["raw_output"]["tool_results"]["weather_query"]["input"]["city"] == "hangzhou"
    assert m2["raw_output"]["tool_results"]["weather_query"]["input"]["days"] == 3
    assert m2["raw_output"]["tool_results"]["budget_calculator"]["input"]["people_count"] == 2
    assert m3["raw_output"]["tool_results"]["poi_search"]["input"]["city"] == "hangzhou"
    assert m3["raw_output"]["tool_results"]["weather_query"]["input"]["city"] == "hangzhou"
    assert m3["output"]["metadata"]["adaptive_scheduler"]["ticket"]["current_slots"][
        "destination"
    ] == "hangzhou"
    assert "beijing" not in prompt_payload
    assert "EXPECTED_SECRET_SHOULD_NOT_LEAK" not in prompt_payload
    assert "GOLD_SECRET_SHOULD_NOT_LEAK" not in prompt_payload
