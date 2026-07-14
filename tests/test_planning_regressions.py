import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.itinerary import ItineraryAgent  # noqa: E402
from app.agents.orchestrator import AgentOrchestrator, TaskPlanner  # noqa: E402
from app.core.context import SessionContext  # noqa: E402
from app.schemas import DialogMode, IntentType  # noqa: E402


def test_itinerary_anchor_pois_are_duration_compatible() -> None:
    agent = ItineraryAgent(llm=None)

    anchors = agent._build_destination_anchor_pois("杭州", 3)

    assert anchors
    for poi in anchors:
        assert "recommended_visit_duration_hours" in poi
        assert "suggested_duration_hours" in poi
        assert "visit_duration_hours" in poi


def test_itinerary_normalize_pois_accepts_recommended_visit_duration_hours() -> None:
    agent = ItineraryAgent(llm=None)

    normalized = agent._normalize_pois(
        [
            {
                "name": "西湖",
                "city": "杭州",
                "region": "西湖区",
                "recommended_visit_duration_hours": "3.5",
                "opening_hours": "09:00-17:00",
            }
        ]
    )

    assert len(normalized) == 1
    assert normalized[0]["visit_duration_hours"] == pytest.approx(3.5)
    assert normalized[0]["suggested_duration_hours"] == pytest.approx(3.5)
    assert normalized[0]["recommended_visit_duration_hours"] == pytest.approx(3.5)


def test_followup_budget_turn_does_not_overwrite_destination_with_origin() -> None:
    orchestrator = AgentOrchestrator(object())
    session = SessionContext(session_id="follow-up-destination")
    session.trip_context.destination = "杭州"

    normalized = orchestrator._normalize_extracted_info(
        {"destination": "上海"},
        user_message="从上海出发，3个人，预算4000元左右",
        session=session,
    )

    assert normalized["destination"] == "杭州"
    assert normalized["origin"] == "上海"
    assert normalized["budget_amount"] == pytest.approx(4000.0)
    assert normalized["num_travelers"] == 3


def test_partial_slots_are_persisted_before_clarification_finishes(monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator = AgentOrchestrator(object())
    session = SessionContext(session_id="clarification-persist")

    monkeypatch.setattr(
        orchestrator,
        "_fast_intent_parse",
        lambda user_message, current_session: (
            IntentType.TRIP_PLANNING,
            {"destination": "杭州", "duration": 3},
        ),
    )

    async def fake_parse(user_message: str, current_session: SessionContext):
        return IntentType.TRIP_PLANNING, {"destination": "杭州", "duration": 3}

    monkeypatch.setattr(orchestrator.intent_parser, "parse", fake_parse)

    async def run_process():
        async for event in orchestrator.process(
            session,
            "我想五一和爸妈去杭州玩三天，想轻松一点，帮我安排一下。",
            request_id="clarification-persist",
            forced_mode=DialogMode.PLANNING,
        ):
            if event.get("requires_clarification"):
                return event
        return None

    event = asyncio.run(run_process())

    assert event is not None
    assert session.trip_context.destination == "杭州"
    assert session.trip_context.duration_days == 3
    assert session.pending_clarification_latch is not None
    assert session.pending_clarification_latch.partial_extracted["destination"] == "杭州"
    assert session.pending_clarification_latch.partial_extracted["duration"] == 3


def test_create_plan_does_not_reask_duration_after_duration_is_persisted() -> None:
    planner = TaskPlanner()
    session = SessionContext(session_id="planner-duration")
    session.trip_context.destination = "杭州"
    session.trip_context.duration_days = 3

    plan = planner.create_plan(
        IntentType.TRIP_PLANNING,
        {
            "destination": "杭州",
            "budget_amount": 4000,
            "num_travelers": 3,
        },
        session=session,
        user_message="从上海出发，3个人，预算4000元左右",
    )

    assert "travel_time" not in (plan.missing_fields or [])


def test_task_planner_reports_tools_separately_from_runtime_execution() -> None:
    planner = TaskPlanner()

    plan = planner.create_plan(
        IntentType.TRIP_PLANNING,
        {
            "destination": "杭州",
            "duration": 3,
            "budget_amount": 4000,
            "num_travelers": 2,
        },
    )

    assert planner.tools_for_plan(plan) == [
        "poi_search",
        "poi_detail",
        "weather_query",
        "route_planning",
        "budget_calculator",
    ]
