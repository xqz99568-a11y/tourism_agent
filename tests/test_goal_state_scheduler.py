import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.goal_state_scheduler import (
    DECISION_SCHEMA_VERSION,
    TICKET_SCHEMA_VERSION,
    build_goal_state_ticket,
    is_goal_state_agent_reusable,
    normalize_slots,
    schedule_goal_state_ticket,
)
from app.core.experiment_method_input import parse_visible_request_slots


def _successful_previous_state(
    slots: dict,
    *,
    agents: tuple[str, ...] = ("attraction", "weather", "itinerary", "budget"),
) -> dict:
    city = slots.get("destination") or "hangzhou"
    start_date = slots.get("start_date") or "2026-08-01"
    days = slots.get("duration_days") or 2
    people_count = slots.get("people_count") or 2
    preferences = slots.get("preferences") or []
    traveler_group = slots.get("traveler_group") or "general"
    state = {
        "slots": dict(slots),
        "available_results": {agent: True for agent in agents},
        "tool_results": {},
    }
    if "attraction" in agents:
        state["tool_results"]["poi_search"] = {
            "tool_name": "poi_search",
            "status": "success",
            "success": True,
            "input": {
                "city": city,
                "preferences": preferences,
                "people": traveler_group,
                "limit": 4,
            },
            "data": {
                "attractions": [
                    {"poi_id": f"{city}-poi-1", "name": "POI 1", "city": city}
                ]
            },
        }
    if "weather" in agents:
        state["tool_results"]["weather_query"] = {
            "tool_name": "weather_query",
            "status": "success",
            "success": True,
            "input": {"city": city, "date": start_date, "days": days},
            "data": {"daily_weather": [{"date": start_date, "condition": "sunny"}]},
        }
    if "budget" in agents:
        state["tool_results"]["budget_calculator"] = {
            "tool_name": "budget_calculator",
            "status": "success",
            "success": True,
            "input": {
                "city": city,
                "days": days,
                "people_count": people_count,
                "attractions": [f"{city}-poi-1"],
            },
            "data": {"total": 1000},
        }
    if "itinerary" in agents:
        state["daily_itinerary"] = [
            {"day": 1, "attractions": [{"poi_id": f"{city}-poi-1"}]}
        ]
    return state


def test_goal_state_ticket_matches_day4_acceptance_cases() -> None:
    acceptance_path = ROOT / "experiments" / "day4_scheduler_acceptance_cases.json"
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))

    assert acceptance["ticket_schema_version"] == TICKET_SCHEMA_VERSION

    for case in acceptance["cases"]:
        ticket = build_goal_state_ticket(
            user_input=case["user_input"],
            current_slots=case.get("current_slots"),
            previous_state=case.get("previous_state"),
        ).to_dict()
        expected = case["expected_ticket"]

        for field, expected_value in expected.items():
            assert ticket[field] == expected_value, f"{case['case_id']} {field}"


def test_goal_state_scheduler_matches_day4_acceptance_cases() -> None:
    acceptance_path = ROOT / "experiments" / "day4_scheduler_acceptance_cases.json"
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))

    assert acceptance["decision_schema_version"] == DECISION_SCHEMA_VERSION

    for case in acceptance["cases"]:
        ticket = build_goal_state_ticket(
            user_input=case["user_input"],
            current_slots=case.get("current_slots"),
            previous_state=case.get("previous_state"),
        )
        decision = schedule_goal_state_ticket(
            ticket,
            previous_state=case.get("previous_state"),
        ).to_dict()
        expected = case["expected_decision"]

        for field, expected_value in expected.items():
            assert decision[field] == expected_value, f"{case['case_id']} {field}"


def test_complete_plan_with_attractions_weather_and_budget_beats_weather_query() -> None:
    ticket = build_goal_state_ticket(
        user_input=(
            "请为两人规划杭州2天旅游，2026-08-01出发，"
            "预算5000元，需要景点、天气和预算。"
        ),
        current_slots={
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
            "budget_amount": 5000,
        },
    )
    decision = schedule_goal_state_ticket(ticket)

    assert ticket.task_type == "trip_planning"
    assert ticket.required_capabilities == [
        "poi_evidence",
        "weather_evidence",
        "itinerary_generation",
        "budget_estimation",
    ]
    assert decision.planned_agents == ["attraction", "weather", "itinerary", "budget"]
    assert decision.planned_tools == [
        "poi_search",
        "weather_query",
        "budget_calculator",
    ]


def test_complete_plan_wording_with_budget_still_routes_to_full_plan() -> None:
    user_input = "我们一家3口想在2026年8月5日去西安玩两天，偏历史文化和亲子体验，预算6000元，请给完整旅行计划。"
    ticket = build_goal_state_ticket(
        user_input=user_input,
        current_slots=parse_visible_request_slots(user_input),
    )
    decision = schedule_goal_state_ticket(ticket)

    assert ticket.task_type == "trip_planning"
    assert decision.planned_agents == ["attraction", "weather", "itinerary", "budget"]
    assert decision.planned_tools == [
        "poi_search",
        "weather_query",
        "budget_calculator",
    ]


def test_landmark_route_weather_budget_wording_routes_to_full_plan() -> None:
    user_input = "请安排深圳2026年8月7日出发的两天城市地标游，2个成人，预算7000元，同时给天气、路线和预算估算。"
    ticket = build_goal_state_ticket(
        user_input=user_input,
        current_slots=parse_visible_request_slots(user_input),
    )
    decision = schedule_goal_state_ticket(ticket)

    assert ticket.task_type == "trip_planning"
    assert decision.planned_agents == ["attraction", "weather", "itinerary", "budget"]
    assert decision.planned_tools == [
        "poi_search",
        "weather_query",
        "budget_calculator",
    ]


def test_clear_weather_only_request_still_routes_to_weather_agent() -> None:
    ticket = build_goal_state_ticket(
        user_input="帮我查一下西安 2026-08-10 开始两天的天气风险。",
        current_slots={
            "destination": "xian",
            "start_date": "2026-08-10",
            "duration_days": 2,
        },
    )
    decision = schedule_goal_state_ticket(ticket)

    assert ticket.task_type == "weather_query"
    assert decision.planned_agents == ["weather"]
    assert decision.planned_tools == ["weather_query"]


def test_chinese_weather_only_with_negated_route_poi_budget_stays_weather_query() -> None:
    user_input = "帮我只看深圳2026年8月11日起两天的天气，别做路线、景点或预算。"
    ticket = build_goal_state_ticket(
        user_input=user_input,
        current_slots=parse_visible_request_slots(user_input),
    )
    decision = schedule_goal_state_ticket(ticket)

    assert ticket.task_type == "weather_query"
    assert ticket.clarification_required is False
    assert decision.planned_agents == ["weather"]
    assert decision.planned_tools == ["weather_query"]


def test_rough_budget_with_negated_ticket_dependency_uses_budget_only() -> None:
    user_input = "请只粗略估算桂林2026年8月12日出发三天2人游是否能控制在4500元内，不要计算具体景点门票。"
    ticket = build_goal_state_ticket(
        user_input=user_input,
        current_slots=parse_visible_request_slots(user_input),
    )
    decision = schedule_goal_state_ticket(ticket)

    assert ticket.task_type == "budget_query"
    assert ticket.dependency_policy == {
        "budget_scope": "rough_budget_without_ticket_dependency",
        "requires_attraction_evidence": False,
    }
    assert decision.planned_agents == ["budget"]
    assert decision.planned_tools == ["budget_calculator"]


def test_chinese_capability_question_and_goodnight_are_general_chat() -> None:
    for user_input in (
        "你好，我只是想了解这个旅游助手能做什么，暂时不要制定旅行计划。",
        "谢谢，今天不需要景点、天气、路线或预算，我只是来道个晚安。",
    ):
        ticket = build_goal_state_ticket(
            user_input=user_input,
            current_slots=parse_visible_request_slots(user_input),
        )
        decision = schedule_goal_state_ticket(ticket)

        assert ticket.task_type == "general_chat"
        assert ticket.clarification_required is False
        assert decision.planned_agents == []
        assert decision.planned_tools == []


def test_goal_state_ticket_merges_previous_state_when_current_turn_only_has_changes() -> None:
    ticket = build_goal_state_ticket(
        user_input="目的地改成桂林，其他条件不变，重新做完整计划。",
        current_slots={"city": "桂林"},
        previous_state={
            "slots": {
                "destination": "杭州",
                "date": "2026-09-01",
                "days": "3",
                "people": "2",
                "traveler_type": "adult",
                "spending_level": "standard",
                "interests": ["classic"],
            }
        },
    )

    assert ticket.current_slots == {
        "destination": "guilin",
        "start_date": "2026-09-01",
        "duration_days": 3,
        "people_count": 2,
        "traveler_group": "adult",
        "budget_level": "standard",
        "preferences": ["classic"],
    }
    assert ticket.changed_slots == ["destination"]
    assert ticket.preserved_slots == [
        "start_date",
        "duration_days",
        "people_count",
        "traveler_group",
        "budget_level",
        "preferences",
    ]
    assert ticket.task_type == "partial_replan"


def test_partial_replan_combines_date_and_people_changes() -> None:
    previous_state = _successful_previous_state(
        {
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
            "preferences": ["classic"],
        }
    )

    ticket = build_goal_state_ticket(
        user_input="日期和人数都改一下，其他不变",
        current_slots={"start_date": "2026-08-05", "people_count": 3},
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert ticket.changed_slots == ["start_date", "people_count"]
    assert decision.planned_agents == ["weather", "itinerary", "budget"]
    assert decision.reused_agents == ["attraction"]
    assert decision.invalidated_agents == ["weather", "itinerary", "budget"]
    assert decision.decision_reasons == [
        "date_changed_weather_replan",
        "people_count_changed_budget_only",
    ]


def test_partial_replan_combines_duration_and_preference_changes() -> None:
    previous_state = _successful_previous_state(
        {
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
            "preferences": ["classic"],
        }
    )

    ticket = build_goal_state_ticket(
        user_input="改成三天，并且多安排自然风光景点",
        current_slots={"duration_days": 3, "preferences": ["nature"]},
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert ticket.changed_slots == ["duration_days", "preferences"]
    assert decision.planned_agents == ["attraction", "weather", "itinerary", "budget"]
    assert decision.reused_agents == []
    assert decision.invalidated_agents == ["attraction", "weather", "itinerary", "budget"]
    assert decision.decision_reasons == [
        "duration_changed_partial_replan",
        "preferences_changed_replan",
    ]


def test_goal_shift_without_slot_change_is_not_identical_reuse() -> None:
    previous_state = _successful_previous_state(
        {
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
        }
    )

    chat_ticket = build_goal_state_ticket(
        user_input="谢谢，今天心情不错。",
        current_slots={},
        previous_state=previous_state,
    )
    chat_decision = schedule_goal_state_ticket(chat_ticket, previous_state=previous_state)
    assert chat_ticket.task_type == "general_chat"
    assert chat_decision.planned_agents == []
    assert chat_decision.reused_agents == []

    more_poi_ticket = build_goal_state_ticket(
        user_input="再推荐几个景点。",
        current_slots={},
        previous_state=previous_state,
    )
    more_poi_decision = schedule_goal_state_ticket(
        more_poi_ticket,
        previous_state=previous_state,
    )
    assert more_poi_ticket.task_type == "attraction_recommendation"
    assert more_poi_decision.planned_agents == ["attraction"]
    assert more_poi_decision.reused_agents == []

    redo_ticket = build_goal_state_ticket(
        user_input="重新做一版。",
        current_slots={},
        previous_state=previous_state,
    )
    redo_decision = schedule_goal_state_ticket(redo_ticket, previous_state=previous_state)
    assert redo_ticket.task_type == "partial_replan"
    assert redo_decision.planned_agents == ["attraction", "weather", "itinerary", "budget"]
    assert redo_decision.reused_agents == []
    assert redo_decision.decision_reasons == ["explicit_replan_requested"]


def test_greeting_that_negates_travel_planning_is_general_chat() -> None:
    ticket = build_goal_state_ticket(
        user_input="Hello, I am only saying hi and do not need travel planning.",
        current_slots={},
        previous_state=None,
    )
    decision = schedule_goal_state_ticket(ticket)

    assert ticket.task_type == "general_chat"
    assert ticket.clarification_required is False
    assert decision.planned_agents == []
    assert decision.planned_tools == []


def test_chinese_negated_tourism_terms_stay_general_chat() -> None:
    user_input = "你好，我只是测试一下对话，不需要任何旅行规划、景点、天气或预算。"
    ticket = build_goal_state_ticket(
        user_input=user_input,
        current_slots=parse_visible_request_slots(user_input),
        previous_state=None,
    )
    decision = schedule_goal_state_ticket(ticket)

    assert ticket.task_type == "general_chat"
    assert ticket.clarification_required is False
    assert decision.planned_agents == []
    assert decision.planned_tools == []


def test_chinese_attraction_only_request_ignores_negated_full_plan_terms() -> None:
    user_input = "只帮我挑深圳2个适合室内参观的景点，不要天气、行程和预算。"
    ticket = build_goal_state_ticket(
        user_input=user_input,
        current_slots=parse_visible_request_slots(user_input),
        previous_state=None,
    )
    decision = schedule_goal_state_ticket(ticket)

    assert ticket.task_type == "attraction_recommendation"
    assert ticket.clarification_required is False
    assert decision.planned_agents == ["attraction"]
    assert decision.planned_tools == ["poi_search"]


def test_chinese_attraction_only_request_ignores_negated_complete_itinerary_phrase() -> None:
    user_input = "只推荐桂林3个自然山水类景点，不要生成完整行程、天气报告或预算。"
    ticket = build_goal_state_ticket(
        user_input=user_input,
        current_slots={
            "destination": "guilin",
            "preferences": ["nature"],
            "special_requirements": ["avoidance_constraint"],
        },
        previous_state=None,
    )
    decision = schedule_goal_state_ticket(ticket)

    assert ticket.task_type == "attraction_recommendation"
    assert ticket.clarification_required is False
    assert ticket.missing_slots == []
    assert decision.planned_agents == ["attraction"]
    assert decision.planned_tools == ["poi_search"]


def test_chinese_budget_only_request_ignores_negated_poi_and_itinerary_terms() -> None:
    user_input = "只估算杭州2026年8月8日出发的三天2人游，预算4600元是否够用，不要生成景点清单。"
    ticket = build_goal_state_ticket(
        user_input=user_input,
        current_slots=parse_visible_request_slots(user_input),
        previous_state=None,
    )
    decision = schedule_goal_state_ticket(ticket)

    assert ticket.task_type == "budget_query"
    assert ticket.clarification_required is False
    assert decision.planned_agents == ["budget"]
    assert decision.planned_tools == ["budget_calculator"]


def test_chinese_explicit_clarification_uses_user_named_missing_slots() -> None:
    user_input = "我想去桂林玩，但没说出发日期、旅行天数和预算，请先向我确认缺失信息。"
    ticket = build_goal_state_ticket(
        user_input=user_input,
        current_slots=parse_visible_request_slots(user_input),
        previous_state=None,
    )
    decision = schedule_goal_state_ticket(ticket)

    assert ticket.task_type == "clarification"
    assert ticket.clarification_fields == [
        "start_date",
        "duration_days",
        "budget_amount",
    ]
    assert decision.planned_agents == []
    assert decision.planned_tools == []


def test_chinese_clarification_handles_not_yet_decided_budget_fields() -> None:
    user_input = "我想去北京旅游，但还没确定出发日期、玩几天和预算，请先问我需要补充什么。"
    ticket = build_goal_state_ticket(
        user_input=user_input,
        current_slots={"destination": "beijing"},
        previous_state=None,
    )
    decision = schedule_goal_state_ticket(ticket)

    assert ticket.task_type == "clarification"
    assert ticket.clarification_fields == [
        "start_date",
        "duration_days",
        "budget_amount",
    ]
    assert decision.planned_agents == []
    assert decision.planned_tools == []


def test_chinese_rain_change_routes_to_weather_adjustment_without_budget_recompute() -> None:
    previous_state = _successful_previous_state(
        {
            "destination": "beijing",
            "start_date": "2026-08-18",
            "duration_days": 2,
            "people_count": 2,
            "budget_amount": 6600,
        }
    )
    user_input = "北京第1天有雨，只调整第一天，2026年8月18日、两天、2个人和6600元预算都不变。"
    ticket = build_goal_state_ticket(
        user_input=user_input,
        current_slots=parse_visible_request_slots(user_input),
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert ticket.task_type == "weather_adjustment"
    assert ticket.changed_slots == ["weather_scenario"]
    assert decision.planned_agents == ["weather", "itinerary"]
    assert decision.planned_tools == ["weather_query"]
    assert decision.reused_agents == ["attraction"]
    assert "budget" not in decision.invalidated_agents


def test_high_temperature_adjustment_reuses_attraction_without_budget_recompute() -> None:
    previous_state = _successful_previous_state(
        {
            "destination": "shenzhen",
            "start_date": "2026-08-21",
            "duration_days": 2,
            "people_count": 2,
            "budget_amount": 7200,
        }
    )
    user_input = "深圳第1天变成高温，请把户外活动调到凉爽时段或室内备选，2026年8月21日、两天、2个人和7200元预算不变。"
    ticket = build_goal_state_ticket(
        user_input=user_input,
        current_slots={
            "weather_scenario": "high_temperature",
            "preferences": ["nature", "indoor"],
            "special_requirements": ["indoor_preferred"],
        },
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert ticket.task_type == "weather_adjustment"
    assert decision.planned_agents == ["weather", "itinerary"]
    assert decision.planned_tools == ["weather_query"]
    assert decision.reused_agents == ["attraction"]
    assert "budget" not in decision.planned_agents
    assert "budget" not in decision.invalidated_agents


def test_identical_chinese_previous_turn_reuses_all_results() -> None:
    previous_state = _successful_previous_state(
        {
            "destination": "hangzhou",
            "start_date": "2026-08-23",
            "duration_days": 2,
            "people_count": 2,
            "budget_amount": 5100,
            "preferences": ["history_culture"],
        }
    )
    user_input = "完全按上一轮杭州文化游再给一次，不改变2026年8月23日、两天、2个人和5100元预算。"
    ticket = build_goal_state_ticket(
        user_input=user_input,
        current_slots={},
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert ticket.task_type == "partial_replan"
    assert ticket.goal_change_type == "identical_request"
    assert decision.planned_agents == []
    assert decision.planned_tools == []
    assert decision.reused_agents == ["attraction", "weather", "itinerary", "budget"]


def test_weather_only_with_negated_itinerary_is_weather_query() -> None:
    ticket = build_goal_state_ticket(
        user_input="Check only the Hangzhou weather forecast for two days from 2026-08-01. Do not plan an itinerary.",
        current_slots={
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
        },
        previous_state=None,
    )
    decision = schedule_goal_state_ticket(ticket)

    assert ticket.task_type == "weather_query"
    assert decision.planned_agents == ["weather"]
    assert decision.planned_tools == ["weather_query"]


def test_dependency_cascade_removes_agents_from_reuse_set() -> None:
    failed_poi = {
        "tool_name": "poi_search",
        "status": "failed",
        "success": False,
        "input": {"city": "hangzhou", "preferences": ["classic"], "people": "adult"},
        "data": {},
        "error": {"message": "previous attraction failed"},
    }
    previous_state = {
        "slots": {
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
            "traveler_group": "adult",
            "preferences": ["classic"],
        },
        "available_results": {
            "attraction": True,
            "weather": True,
            "itinerary": True,
            "budget": True,
        },
        "tool_results": {
            "poi_search": failed_poi,
            "weather_query": {
                "tool_name": "weather_query",
                "status": "success",
                "success": True,
                "input": {"city": "hangzhou", "date": "2026-08-01", "days": 2},
                "data": {},
            },
            "budget_calculator": {
                "tool_name": "budget_calculator",
                "status": "success",
                "success": True,
                "input": {"city": "hangzhou", "days": 2, "people_count": 2},
                "data": {},
            },
        },
        "daily_itinerary": [{"day": 1, "reuse_marker": "old-itinerary"}],
    }

    ticket = build_goal_state_ticket(
        user_input="same plan again",
        current_slots={},
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert decision.planned_agents == ["attraction", "itinerary", "budget"]
    assert decision.reused_agents == ["weather"]
    assert decision.invalidated_agents == ["attraction", "itinerary", "budget"]
    assert not set(decision.reused_agents) & set(decision.planned_agents)
    assert not set(decision.reused_agents) & set(decision.invalidated_agents)


def test_budget_query_requires_reusable_attraction_upstream() -> None:
    previous_state = _successful_previous_state(
        {
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
        },
        agents=("weather",),
    )

    ticket = build_goal_state_ticket(
        user_input="how much will attraction tickets and admission cost for four people",
        current_slots={"people_count": 4},
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert ticket.task_type == "budget_query"
    assert decision.planned_agents == ["attraction", "budget"]
    assert decision.reused_agents == []


def test_rough_budget_query_without_ticket_dependency_uses_budget_only() -> None:
    ticket = build_goal_state_ticket(
        user_input="rough budget estimate for a two day Hangzhou trip for two people",
        current_slots={
            "destination": "hangzhou",
            "duration_days": 2,
            "people_count": 2,
        },
    )
    decision = schedule_goal_state_ticket(ticket)

    assert ticket.task_type == "budget_query"
    assert ticket.dependency_policy == {
        "budget_scope": "rough_budget_without_ticket_dependency",
        "requires_attraction_evidence": False,
    }
    assert decision.planned_agents == ["budget"]
    assert decision.planned_tools == ["budget_calculator"]
    assert decision.decision_reasons == ["rough_budget_without_ticket_dependency"]


def test_ticket_budget_query_without_previous_attractions_runs_attraction_first() -> None:
    ticket = build_goal_state_ticket(
        user_input="estimate attraction tickets and total admission cost for a two day Hangzhou trip for two people",
        current_slots={
            "destination": "hangzhou",
            "duration_days": 2,
            "people_count": 2,
        },
    )
    decision = schedule_goal_state_ticket(ticket)

    assert ticket.task_type == "budget_query"
    assert ticket.dependency_policy == {
        "budget_scope": "ticket_budget_requires_attraction_evidence",
        "requires_attraction_evidence": True,
    }
    assert decision.planned_agents == ["attraction", "budget"]
    assert decision.planned_tools == ["poi_search", "budget_calculator"]
    assert decision.decision_reasons == ["ticket_budget_requires_attraction_evidence"]


def test_identical_request_with_only_budget_result_replans_full_plan() -> None:
    previous_state = _successful_previous_state(
        {
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
        },
        agents=("budget",),
    )

    ticket = build_goal_state_ticket(
        user_input="same plan again",
        current_slots={},
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert decision.planned_agents == ["attraction", "weather", "itinerary", "budget"]
    assert decision.reused_agents == []
    assert "identical_request_incomplete_previous_state_replan" in decision.decision_reasons
    assert "dependent_result_invalidated" in decision.decision_reasons


def test_available_markers_without_artifacts_are_not_reusable() -> None:
    previous_state = {
        "slots": {
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
        },
        "available_results": {
            "attraction": True,
            "weather": True,
            "itinerary": True,
            "budget": True,
        },
    }

    ticket = build_goal_state_ticket(
        user_input="same plan again",
        current_slots={},
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert decision.planned_agents == ["attraction", "weather", "itinerary", "budget"]
    assert decision.reused_agents == []
    assert decision.reuse_validation["raw_available_agents"] == []


def test_expired_previous_result_is_not_reusable() -> None:
    previous_state = _successful_previous_state(
        {
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
        },
        agents=("attraction",),
    )
    previous_state["tool_results"]["poi_search"]["status"] = "expired"

    ticket = build_goal_state_ticket(
        user_input="change it to three days",
        current_slots={"duration_days": 3},
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert "attraction" not in decision.reused_agents
    assert "attraction" in decision.planned_agents
    assert decision.reuse_validation["unusable_reasons"]["attraction"] == (
        "previous_result_failed"
    )


def test_expired_previous_state_flags_are_not_reusable() -> None:
    slots = {
        "destination": "hangzhou",
        "start_date": "2026-08-01",
        "duration_days": 2,
        "people_count": 2,
    }
    for marker, value in (
        ("status", "expired"),
        ("expired", True),
    ):
        previous_state = _successful_previous_state(slots, agents=("attraction",))
        previous_state[marker] = value

        assert not is_goal_state_agent_reusable(
            "attraction",
            current_slots=slots,
            previous_state=previous_state,
        )


def test_expired_tool_result_flag_is_not_reusable() -> None:
    slots = {
        "destination": "hangzhou",
        "start_date": "2026-08-01",
        "duration_days": 2,
        "people_count": 2,
    }
    previous_state = _successful_previous_state(slots, agents=("attraction",))
    previous_state["tool_results"]["poi_search"]["expired"] = True

    assert not is_goal_state_agent_reusable(
        "attraction",
        current_slots=slots,
        previous_state=previous_state,
    )


def test_previous_fingerprint_extra_conditions_do_not_match_missing_current_slots() -> None:
    current_slots = {
        "destination": "hangzhou",
        "duration_days": 2,
        "people_count": 2,
    }

    attraction_state = _successful_previous_state(
        {"destination": "hangzhou"},
        agents=("attraction",),
    )
    attraction_state["result_fingerprints"] = {
        "attraction": {
            "destination": "hangzhou",
            "preferences": ["museum"],
        }
    }
    assert not is_goal_state_agent_reusable(
        "attraction",
        current_slots={"destination": "hangzhou"},
        previous_state=attraction_state,
    )

    budget_state = _successful_previous_state(
        current_slots,
        agents=("attraction", "budget"),
    )
    budget_state["result_fingerprints"] = {
        "budget": {
            "destination": "hangzhou",
            "duration_days": 2,
            "people_count": 2,
            "budget_level": "luxury",
        }
    }
    assert not is_goal_state_agent_reusable(
        "budget",
        current_slots=current_slots,
        previous_state=budget_state,
    )


def test_weather_adjustment_does_not_recompute_budget_when_budget_fingerprint_is_noisy() -> None:
    slots = {
        "destination": "beijing",
        "start_date": "2026-08-18",
        "duration_days": 2,
        "people_count": 2,
        "budget_amount": 6600,
    }
    previous_state = _successful_previous_state(slots)
    previous_state["tool_results"]["budget_calculator"]["input"]["spending_level"] = "luxury"

    ticket = build_goal_state_ticket(
        user_input="北京第1天有雨，只调整第一天，日期、天数、人数和预算都不变。",
        current_slots={"weather_scenario": "rain"},
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert ticket.task_type == "weather_adjustment"
    assert decision.planned_agents == ["weather", "itinerary"]
    assert decision.planned_tools == ["weather_query"]
    assert decision.reused_agents == ["attraction"]
    assert "budget" not in decision.invalidated_agents


def test_empty_preferences_and_none_budget_are_explicit_slot_changes() -> None:
    previous_state = _successful_previous_state(
        {
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
            "preferences": ["classic"],
            "budget_amount": 1000,
        }
    )

    ticket = build_goal_state_ticket(
        user_input="remove the preference and budget limit",
        current_slots={"preferences": [], "budget": None},
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert ticket.current_slots["preferences"] == []
    assert ticket.current_slots["budget_amount"] is None
    assert ticket.changed_slots == ["budget_amount", "preferences"]
    assert decision.planned_agents == ["attraction", "itinerary", "budget"]
    assert decision.reused_agents == ["weather"]


def test_regenerate_wins_over_same_condition_terms() -> None:
    previous_state = _successful_previous_state(
        {
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
        }
    )

    ticket = build_goal_state_ticket(
        user_input="same conditions, regenerate a new version",
        current_slots={},
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert ticket.goal_change_type == "explicit_replan"
    assert decision.planned_agents == ["attraction", "weather", "itinerary", "budget"]
    assert decision.reused_agents == []
    assert decision.decision_reasons == ["explicit_replan_requested"]


def test_attraction_expansion_wins_over_same_condition_terms() -> None:
    previous_state = _successful_previous_state(
        {
            "destination": "hangzhou",
            "start_date": "2026-08-01",
            "duration_days": 2,
            "people_count": 2,
        }
    )

    ticket = build_goal_state_ticket(
        user_input="same plan, recommend more attractions",
        current_slots={},
        previous_state=previous_state,
    )
    decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)

    assert ticket.goal_change_type == "goal_shift_attraction"
    assert ticket.task_type == "attraction_recommendation"
    assert decision.planned_agents == ["attraction"]
    assert decision.reused_agents == []


def test_normalize_slots_ignores_empty_values_and_unknown_fields() -> None:
    assert normalize_slots(
        {
            "destination": " 北京 ",
            "duration": "3",
            "people_count": None,
            "preferences": ["classic", "", "classic"],
            "unknown": "ignored",
        }
    ) == {
        "destination": "beijing",
        "duration_days": 3,
        "preferences": ["classic"],
    }
