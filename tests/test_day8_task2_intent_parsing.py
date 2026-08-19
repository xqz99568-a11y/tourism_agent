import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.orchestrator import AgentOrchestrator
from app.core.context import SessionContext
from app.core.experiment_method_input import (
    parse_visible_request_slots,
    parse_visible_request_understanding,
)
from app.core.goal_state_scheduler import build_goal_state_ticket, schedule_goal_state_ticket
from app.schemas import IntentType


DAY8_CASES_PATH = ROOT / "experiments" / "day8_dev_acceptance_cases_v1_3.json"
PARSED_SLOT_KEYS = {
    "origin",
    "destination",
    "start_date",
    "end_date",
    "duration_days",
    "people_count",
    "budget_amount",
    "budget_basis",
    "requested_budget_scope",
    "budget_scope",
    "intercity_transport_included",
    "mandatory_budget_disclaimer",
    "hotel_level",
    "food_level",
    "intercity_transport_mode",
    "intercity_seat_class",
}


def _day8_cases() -> list[dict]:
    document = json.loads(DAY8_CASES_PATH.read_text(encoding="utf-8"))
    return list(document["cases"])


@pytest.mark.parametrize("case", _day8_cases(), ids=lambda c: c["case_id"])
def test_day8_v13_acceptance_cases_parse_and_schedule(case: dict) -> None:
    slots = parse_visible_request_slots(case["user_input"])
    ticket = build_goal_state_ticket(user_input=case["user_input"], current_slots=slots)
    decision = schedule_goal_state_ticket(ticket)

    assert ticket.task_type == case["task_type"]

    for key, expected_value in (case.get("gold_slots") or {}).items():
        if key not in PARSED_SLOT_KEYS:
            continue
        if expected_value is None:
            assert key not in slots
        else:
            assert slots.get(key) == expected_value

    expected_behavior = case["expected_tool_behavior"]
    assert decision.planned_tools == expected_behavior["required_tools"]
    for forbidden_tool in expected_behavior["forbidden_tools"]:
        assert forbidden_tool not in decision.planned_tools


def test_day8_v13_complete_plan_without_date_is_trip_plan_without_weather() -> None:
    user_input = "去桂林玩3天，两个人，预算5000左右，帮我安排一下。"
    slots = parse_visible_request_slots(user_input)
    ticket = build_goal_state_ticket(user_input=user_input, current_slots=slots)
    decision = schedule_goal_state_ticket(ticket)

    assert slots == {
        "destination": "guilin",
        "duration_days": 3,
        "people_count": 2,
        "budget_amount": 5000,
        "budget_basis": "total",
        "requested_budget_scope": "destination_local_only",
        "budget_scope": "destination_local_only",
        "intercity_transport_included": False,
        "mandatory_budget_disclaimer": True,
    }
    assert ticket.task_type == "trip_plan"
    assert ticket.missing_slots == []
    assert decision.planned_agents == ["attraction", "itinerary", "budget"]
    assert decision.planned_tools == ["poi_search", "budget_calculator"]


def test_day8_cli_fast_parse_keeps_origin_destination_duration_separate() -> None:
    orchestrator = AgentOrchestrator(object())
    session = SessionContext(session_id="day8-cli")

    intent, info = orchestrator._fast_intent_parse(
        "8月10号从广州出发去桂林玩3天，两个人，预算5000块。",
        session,
    )

    assert intent == IntentType.TRIP_PLANNING
    assert info["origin"] == "guangzhou"
    assert info["destination"] == "guilin"
    assert info["start_date"] == "2026-08-10"
    assert info["duration"] == 3
    assert info["num_travelers"] == 2
    assert info["budget_amount"] == pytest.approx(5000.0)
    assert info.get("budget_level") is None


def test_day8_cli_fast_parse_handles_general_chat_without_business_route() -> None:
    orchestrator = AgentOrchestrator(object())
    session = SessionContext(session_id="day8-cli-chat")

    intent, info = orchestrator._fast_intent_parse("你好", session)

    assert intent == IntentType.GENERAL_CHAT
    assert info == {}


def test_day8_cli_fast_parse_handles_reverse_origin_wording() -> None:
    orchestrator = AgentOrchestrator(object())
    session = SessionContext(session_id="day8-cli-origin")

    intent, info = orchestrator._fast_intent_parse(
        "广州出发，8月10号去深圳玩两天，3个人，预算6000左右。",
        session,
    )

    assert intent == IntentType.TRIP_PLANNING
    assert info["origin"] == "guangzhou"
    assert info["destination"] == "shenzhen"
    assert info["start_date"] == "2026-08-10"
    assert info["duration"] == 2
    assert info["num_travelers"] == 3
    assert info["budget_amount"] == pytest.approx(6000.0)
    assert info.get("budget_level") is None


def test_day8_cli_fast_parse_treats_budget_amount_as_limit_not_spending_tier() -> None:
    orchestrator = AgentOrchestrator(object())
    session = SessionContext(session_id="day8-cli-budget-limit")

    _intent, info = orchestrator._fast_intent_parse(
        "8月10号去桂林玩3天，两个人，预算10000块。",
        session,
    )

    assert info["budget_amount"] == pytest.approx(10000.0)
    assert info.get("budget_level") is None


def test_day8_explicit_ask_me_first_routes_to_clarification_not_destination_recommendation() -> None:
    user_input = "去哪、什么时候走、玩几天、多少钱都没想好，请先问我。"
    slots = parse_visible_request_slots(user_input)
    ticket = build_goal_state_ticket(user_input=user_input, current_slots=slots)
    decision = schedule_goal_state_ticket(ticket)

    assert slots == {}
    assert ticket.task_type == "clarification"
    assert ticket.clarification_fields == [
        "destination",
        "start_date",
        "duration_days",
        "budget_amount",
    ]
    assert decision.planned_agents == []
    assert decision.planned_tools == []


def test_day8_cli_fast_parse_handles_evening_chat_without_unknown_intent() -> None:
    orchestrator = AgentOrchestrator(object())
    session = SessionContext(session_id="day8-cli-evening-chat")

    intent, info = orchestrator._fast_intent_parse("晚上好，我只是来试试聊天。", session)

    assert intent == IntentType.GENERAL_CHAT
    assert info == {}


def test_day8_cli_fast_parse_does_not_treat_ordinal_day_as_duration() -> None:
    orchestrator = AgentOrchestrator(object())
    session = SessionContext(session_id="day8-cli-ordinal-day")
    session.trip_context.destination = "桂林"
    session.trip_context.duration_days = 3

    intent, info = orchestrator._fast_intent_parse("第1天有雨，原来的3天不变。", session)

    assert intent == IntentType.TRIP_PLANNING
    assert info["destination"] == "guilin"
    assert info["duration"] == 3


def test_day8_cli_fast_parse_does_not_extract_arbitrary_phrase_as_origin() -> None:
    orchestrator = AgentOrchestrator(object())
    session = SessionContext(session_id="day8-cli-no-fake-origin")

    _intent, info = orchestrator._fast_intent_parse("请把取舍理由清楚地告诉我。", session)

    assert "origin" not in info
    assert "destination" not in info


def test_day8_origin_only_request_keeps_origin_and_asks_destination() -> None:
    user_input = "从北京出发玩两天。"
    slots = parse_visible_request_slots(user_input)
    ticket = build_goal_state_ticket(user_input=user_input, current_slots=slots)
    decision = schedule_goal_state_ticket(ticket)

    assert slots == {"origin": "beijing", "duration_days": 2}
    assert ticket.task_type == "clarification"
    assert ticket.clarification_fields == ["destination", "people_count"]
    assert decision.planned_agents == []
    assert decision.planned_tools == []

    orchestrator = AgentOrchestrator(object())
    session = SessionContext(session_id="day8-cli-origin-only")
    intent, info = orchestrator._fast_intent_parse(user_input, session)
    normalized = orchestrator._normalize_extracted_info(info, user_message=user_input, session=session)
    plan = orchestrator.task_planner.create_plan(
        intent,
        normalized,
        session=session,
        user_message=user_input,
    )

    assert intent == IntentType.TRIP_PLANNING
    assert normalized["origin"] == "beijing"
    assert "destination" not in normalized
    assert plan.requires_clarification is True
    assert plan.missing_fields == ["destination", "people"]


def test_day8_cli_plan_request_without_duration_or_people_asks_both_not_date_or_budget() -> None:
    orchestrator = AgentOrchestrator(object())
    session = SessionContext(session_id="day8-cli-beijing-clarify")
    user_input = "想去北京玩，帮我安排一下吧。"

    intent, info = orchestrator._fast_intent_parse(user_input, session)
    normalized = orchestrator._normalize_extracted_info(info, user_message=user_input, session=session)
    plan = orchestrator.task_planner.create_plan(
        intent,
        normalized,
        session=session,
        user_message=user_input,
    )

    assert intent == IntentType.TRIP_PLANNING
    assert normalized["destination"] == "beijing"
    assert plan.requires_clarification is True
    assert plan.missing_fields == ["duration", "people"]


def test_day8_cli_fast_parse_uses_formal_reference_date_for_relative_dates() -> None:
    orchestrator = AgentOrchestrator(object())
    session = SessionContext(session_id="day8-cli-relative-date")

    intent, info = orchestrator._fast_intent_parse(
        "明天想去深圳玩两天，两个人，预算4000左右，帮我安排一下。",
        session,
    )
    normalized = orchestrator._normalize_extracted_info(
        info,
        user_message="明天想去深圳玩两天，两个人，预算4000左右，帮我安排一下。",
        session=session,
    )

    assert intent == IntentType.TRIP_PLANNING
    assert info["destination"] == "shenzhen"
    assert info["start_date"] == "2026-08-07"
    assert normalized["start_date"].date().isoformat() == "2026-08-07"


def test_day8_cli_weather_only_request_runs_weather_agent_only() -> None:
    orchestrator = AgentOrchestrator(object())
    session = SessionContext(session_id="day8-cli-weather-only")
    user_input = "桂林未来三天天气怎么样？"

    intent, info = orchestrator._fast_intent_parse(user_input, session)
    normalized = orchestrator._normalize_extracted_info(info, user_message=user_input, session=session)
    plan = orchestrator.task_planner.create_plan(
        intent,
        normalized,
        session=session,
        user_message=user_input,
    )

    assert intent == IntentType.WEATHER_ADJUSTMENT
    assert normalized["destination"] == "guilin"
    assert normalized["duration"] == 3
    assert plan.requires_clarification is False
    assert [task.agent_name for task in plan.tasks] == ["weather"]
    assert plan.requires_review is False


def test_day8_cli_complete_plan_without_date_excludes_weather_agent() -> None:
    orchestrator = AgentOrchestrator(object())
    session = SessionContext(session_id="day8-cli-plan-without-date")
    user_input = "我想去桂林玩3天，两个人，预算5000左右，帮我安排一下。"

    intent, info = orchestrator._fast_intent_parse(user_input, session)
    normalized = orchestrator._normalize_extracted_info(info, user_message=user_input, session=session)
    plan = orchestrator.task_planner.create_plan(
        intent,
        normalized,
        session=session,
        user_message=user_input,
    )

    assert intent == IntentType.TRIP_PLANNING
    assert normalized["destination"] == "guilin"
    assert "start_date" not in normalized
    assert [task.agent_name for task in plan.tasks] == ["attraction", "itinerary", "budget"]


def test_day8_weather_query_without_date_no_longer_requires_start_date() -> None:
    user_input = "桂林天气怎么样？"
    slots = parse_visible_request_slots(user_input)
    ticket = build_goal_state_ticket(user_input=user_input, current_slots=slots)
    decision = schedule_goal_state_ticket(ticket)

    assert slots == {"destination": "guilin"}
    assert ticket.task_type == "weather_query"
    assert ticket.missing_slots == []
    assert decision.planned_agents == ["weather"]
    assert decision.planned_tools == ["weather_query"]


def test_day8_formal_parser_understands_relative_month_and_two_day_weather_query() -> None:
    assert parse_visible_request_slots("一个月后从成都去西安玩3天，两个人，总预算上限6000元。") == {
        "origin": "chengdu",
        "destination": "xian",
        "start_date": "2026-09-06",
        "duration_days": 3,
        "people_count": 2,
        "budget_amount": 6000,
        "budget_basis": "total",
        "requested_budget_scope": "local_plus_round_trip_intercity",
        "budget_scope": "local_plus_round_trip_intercity",
        "intercity_transport_included": True,
        "mandatory_budget_disclaimer": False,
        "intercity_transport_mode": "high_speed_rail",
        "intercity_seat_class": "second_class",
    }
    assert parse_visible_request_slots("杭州明天和后天会不会下雨？出门需要准备什么？") == {
        "destination": "hangzhou",
        "start_date": "2026-08-07",
        "duration_days": 2,
        "weather_scenario": "rain",
    }
    assert parse_visible_request_slots("把室内景点放到有降雨风险的时段，其他景点不变。") == {
        "preferences": ["indoor"],
        "special_requirements": ["indoor_preferred"],
        "weather_scenario": "rain",
    }
    assert parse_visible_request_slots("西安从后天开始连续三天的天气怎么样？") == {
        "destination": "xian",
        "start_date": "2026-08-08",
        "duration_days": 3,
    }
    assert parse_visible_request_slots("深圳明天适不适合安排户外活动？只看天气就行。") == {
        "destination": "shenzhen",
        "start_date": "2026-08-07",
        "duration_days": 1,
        "preferences": ["nature"],
    }


def test_day8_formal_parser_extracts_common_companion_and_replan_constraints() -> None:
    assert parse_visible_request_slots("我和对象想去北京玩3天，总共最多花5000元。") == {
        "destination": "beijing",
        "duration_days": 3,
        "people_count": 2,
        "budget_amount": 5000,
        "budget_basis": "total",
        "requested_budget_scope": "destination_local_only",
        "budget_scope": "destination_local_only",
        "intercity_transport_included": False,
        "mandatory_budget_disclaimer": True,
    }
    assert parse_visible_request_slots(
        "我妈妈膝盖不太好，把节奏放慢，少安排需要长时间步行的景点。"
    ) == {"special_requirements": ["low_intensity"]}
    assert parse_visible_request_slots("我们不想坐船，请在其他条件不变的情况下重新安排。") == {
        "special_requirements": ["avoidance_constraint"]
    }
    assert parse_visible_request_slots("我比较怕晒，多安排室内场馆，别改日期和预算。") == {
        "preferences": ["indoor"],
        "special_requirements": ["indoor_preferred"],
    }
FORMAL_CASES_PATH = ROOT / "experiments" / "ctp100_formal_v2.json"


def _canonical_task_type(task_type: str | None) -> str | None:
    return {
        "trip_plan": "trip_planning",
        "weather_aware_trip_plan": "trip_planning",
        "weather_forecast_query": "weather_query",
        "weather_climate_question": "general_chat",
        "destination_recommendation": "general_chat",
    }.get(task_type, task_type)


def _formal_single_turn_cases() -> list[dict]:
    document = json.loads(FORMAL_CASES_PATH.read_text(encoding="utf-8"))
    return [case for case in document["cases"] if "turns" not in case]


TASK1_SHARED_SLOT_KEYS = (
    "origin",
    "destination",
    "start_date",
    "end_date",
    "duration_days",
    "people_count",
    "budget_amount",
    "budget_basis",
    "requested_budget_scope",
    "budget_scope",
    "intercity_transport_included",
    "mandatory_budget_disclaimer",
    "hotel_level",
    "food_level",
    "intercity_transport_mode",
    "intercity_seat_class",
)
TASK1_GOLD_SLOT_KEYS = tuple(
    key
    for key in TASK1_SHARED_SLOT_KEYS
    if key not in {"intercity_transport_mode", "intercity_seat_class"}
)


def _present_shared_slots(slots: dict) -> dict:
    output = {}
    for key in TASK1_SHARED_SLOT_KEYS:
        if key not in slots:
            continue
        value = slots.get(key)
        if hasattr(value, "date"):
            value = value.date().isoformat()
        if value is None or value == "" or value == [] or value == {}:
            continue
        output[key] = value
    return output


def _cli_research_task_type(intent: IntentType, plan) -> str:
    if plan.requires_clarification:
        return "clarification"
    return {
        IntentType.TRIP_PLANNING: "trip_planning",
        IntentType.ITINERARY_PLANNING: "trip_planning",
        IntentType.ATTRACTION_RECOMMENDATION: "attraction_recommendation",
        IntentType.ROUTE_CONSULTATION: "attraction_recommendation",
        IntentType.WEATHER_ADJUSTMENT: "weather_query",
        IntentType.BUDGET_CONTROL: "budget_query",
        IntentType.GENERAL_CHAT: "general_chat",
    }.get(intent, "general_chat")


@pytest.mark.parametrize("case", _formal_single_turn_cases(), ids=lambda c: c["case_id"])
def test_day8_task1_shared_understanding_matches_formal_single_turn_gold(case: dict) -> None:
    expected = case["expected"]
    understanding = parse_visible_request_understanding(case["user_input"])

    assert _canonical_task_type(understanding["task_type"]) == _canonical_task_type(expected["task_type"])

    parsed_slots = understanding["slots"]
    for key in TASK1_GOLD_SLOT_KEYS:
        if key not in expected:
            continue
        expected_value = expected[key]
        actual_value = parsed_slots.get(key)
        if expected_value is None:
            if key == "mandatory_budget_disclaimer":
                continue
            assert key not in parsed_slots
        else:
            assert actual_value == expected_value


@pytest.mark.parametrize("case", _formal_single_turn_cases(), ids=lambda c: c["case_id"])
def test_day8_task1_cli_and_experiment_use_same_visible_understanding(case: dict) -> None:
    experiment_understanding = parse_visible_request_understanding(case["user_input"])
    cli_intent, cli_slots, cli_plan = _create_day8_cli_plan(case["user_input"])

    assert _canonical_task_type(_cli_research_task_type(cli_intent, cli_plan)) == _canonical_task_type(
        experiment_understanding["task_type"]
    )
    assert _present_shared_slots(cli_slots) == _present_shared_slots(experiment_understanding["slots"])


def test_day8_task1_budget_basis_scope_and_tier_slots_are_separate() -> None:
    user_input = "两个人每人预算3000元，从广州去桂林玩3天，帮我安排一下，但预算只算当地费用，住宿舒适一点，餐饮经济型。"

    slots = parse_visible_request_slots(user_input)
    intent, normalized, plan = _create_day8_cli_plan(user_input)

    expected = {
        "origin": "guangzhou",
        "destination": "guilin",
        "duration_days": 3,
        "people_count": 2,
        "budget_amount": 6000,
        "budget_basis": "per_person",
        "requested_budget_scope": "destination_local_only",
        "budget_scope": "destination_local_only",
        "intercity_transport_included": False,
        "hotel_level": "comfort",
        "food_level": "economy",
    }
    for key, value in expected.items():
        assert slots.get(key) == value
    assert normalized["budget_amount"] == pytest.approx(6000.0)
    assert normalized["budget_basis"] == "per_person"
    assert normalized["hotel_level"] == "comfort"
    assert normalized["food_level"] == "economy"
    assert normalized.get("budget_level") is None
    assert intent == IntentType.TRIP_PLANNING
    assert [task.agent_name for task in plan.tasks] == ["attraction", "itinerary", "budget"]


@pytest.mark.parametrize("case", _formal_single_turn_cases(), ids=lambda c: c["case_id"])
def test_day8_formal_single_turn_cases_schedule_to_expected_tools(case: dict) -> None:
    expected = case["expected"]
    slots = parse_visible_request_slots(case["user_input"])
    ticket = build_goal_state_ticket(user_input=case["user_input"], current_slots=slots)
    decision = schedule_goal_state_ticket(ticket)

    assert _canonical_task_type(ticket.task_type) == _canonical_task_type(expected["task_type"])

    tool_aliases = {"weather_forecast_query": "weather_query"}
    required_tools = [tool_aliases.get(tool, tool) for tool in expected["required_tools"]]
    planned_tools = [tool_aliases.get(tool, tool) for tool in decision.planned_tools]
    forbidden_tools = [tool_aliases.get(tool, tool) for tool in expected.get("forbidden_tools", [])]
    assert set(planned_tools) == set(required_tools)
    assert set(planned_tools).isdisjoint(forbidden_tools)
    assert decision.planned_agents in expected["accepted_agent_sets"]


def _create_day8_cli_plan(user_input: str):
    orchestrator = AgentOrchestrator(object())
    session = SessionContext(session_id="day8-cli-v2-regression")
    intent, info = orchestrator._fast_intent_parse(user_input, session)
    normalized = orchestrator._normalize_extracted_info(
        info,
        user_message=user_input,
        session=session,
    )
    plan = orchestrator.task_planner.create_plan(
        intent,
        normalized,
        session=session,
        user_message=user_input,
    )
    return intent, normalized, plan


def test_day8_cli_attraction_only_request_does_not_become_full_plan() -> None:
    user_input = (
        "\u6df1\u5733\u6709\u54ea\u4e9b\u9002\u5408\u4eb2\u5b50\u53c2\u89c2"
        "\u7684\u5ba4\u5185\u573a\u9986\uff1f\u5148\u522b\u7b97\u8d39\u7528\u548c\u8def\u7ebf\u3002"
    )

    intent, normalized, plan = _create_day8_cli_plan(user_input)

    assert intent == IntentType.ATTRACTION_RECOMMENDATION
    assert normalized["destination"] == "shenzhen"
    assert plan.requires_clarification is False
    assert [task.agent_name for task in plan.tasks] == ["attraction"]


def test_day8_cli_budget_only_request_runs_budget_agent_only() -> None:
    user_input = (
        "\u5317\u4eac\u73a93\u5929\uff0c\u4e24\u4e2a\u4eba\uff0c"
        "\u603b\u9884\u7b97\u4e0a\u965010000\u5143\uff0c"
        "\u5e2e\u6211\u770b\u770b\u5927\u6982\u9700\u8981\u591a\u5c11\u94b1\uff0c"
        "\u4e0d\u7528\u6392\u8def\u7ebf\u3002"
    )

    intent, normalized, plan = _create_day8_cli_plan(user_input)

    assert intent == IntentType.BUDGET_CONTROL
    assert normalized["destination"] == "beijing"
    assert normalized["duration"] == 3
    assert normalized["num_travelers"] == 2
    assert normalized["budget_amount"] == pytest.approx(10000.0)
    assert plan.requires_clarification is False
    assert [task.agent_name for task in plan.tasks] == ["budget"]
    assert plan.requires_review is False


def test_day8_cli_climate_and_destination_recommendation_stay_general_chat() -> None:
    climate_query = "\u897f\u5b89\u5341\u4e00\u6708\u4efd\u901a\u5e38\u51b7\u4e0d\u51b7\uff0c\u9700\u8981\u51c6\u5907\u4ec0\u4e48\u8863\u670d\uff1f"
    destination_query = (
        "\u6211\u4eec\u4e24\u4e2a\u4eba\u60f3\u51fa\u53bb\u73a93\u5929\uff0c"
        "\u603b\u9884\u7b97\u4e0a\u96505000\u5143\uff0c"
        "\u559c\u6b22\u81ea\u7136\u98ce\u666f\u4f46\u4e0d\u60f3\u592a\u7d2f\uff0c"
        "\u4f60\u5148\u63a8\u8350\u51e0\u4e2a\u76ee\u7684\u5730\u3002"
    )

    for user_input in (climate_query, destination_query):
        intent, _normalized, plan = _create_day8_cli_plan(user_input)
        assert intent == IntentType.GENERAL_CHAT
        assert plan.requires_clarification is False
        assert plan.tasks == []
