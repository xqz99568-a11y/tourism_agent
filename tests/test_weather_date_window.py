import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.orchestrator import AgentOrchestrator  # noqa: E402
from app.agents.weather import WeatherAgent  # noqa: E402
from app.core.context import ExecutionContext, SessionContext  # noqa: E402


def _build_forecast_items(start: datetime, days: int) -> tuple[list[dict], list[dict]]:
    forecast_items = []
    raw_daily_items = []
    for offset in range(days):
        current = start + timedelta(days=offset)
        current_date = current.strftime("%Y-%m-%d")
        forecast_items.append({"date": current_date, "weather": "cloudy"})
        raw_daily_items.append({"date": current_date})
    return forecast_items, raw_daily_items


def test_extract_trip_dates_from_text_may_day(monkeypatch) -> None:
    orchestrator = AgentOrchestrator(object())
    monkeypatch.setattr(orchestrator, "_get_current_datetime", lambda: datetime(2026, 4, 22, 9, 0, 0))

    normalized = orchestrator._normalize_extracted_info(
        {},
        user_message="\u6211\u60f3\u4e94\u4e00\u53bb\u676d\u5dde\u73a93\u5929",
        session=SessionContext(session_id="may-day"),
    )

    assert normalized["start_date"] is not None
    assert normalized["start_date"].month == 5
    assert normalized["start_date"].day == 1


def test_extract_trip_dates_from_text_tomorrow(monkeypatch) -> None:
    orchestrator = AgentOrchestrator(object())
    fixed_now = datetime(2026, 4, 22, 9, 0, 0)
    monkeypatch.setattr(orchestrator, "_get_current_datetime", lambda: fixed_now)

    normalized = orchestrator._normalize_extracted_info(
        {},
        user_message="\u6211\u60f3\u660e\u5929\u53bb\u676d\u5dde\u73a92\u5929",
        session=SessionContext(session_id="tomorrow"),
    )

    assert normalized["start_date"] == datetime(2026, 4, 23)


def test_extract_trip_dates_from_text_weekend(monkeypatch) -> None:
    orchestrator = AgentOrchestrator(object())
    monkeypatch.setattr(orchestrator, "_get_current_datetime", lambda: datetime(2026, 4, 22, 9, 0, 0))

    normalized = orchestrator._normalize_extracted_info(
        {},
        user_message="\u5468\u672b\u53bb\u676d\u5dde\u73a92\u5929",
        session=SessionContext(session_id="weekend"),
    )

    assert normalized["start_date"] is not None
    assert normalized["start_date"].weekday() == 5


def test_persist_partial_trip_context_keeps_start_date(monkeypatch) -> None:
    orchestrator = AgentOrchestrator(object())
    session = SessionContext(session_id="persist-start-date")
    monkeypatch.setattr(orchestrator, "_get_current_datetime", lambda: datetime(2026, 4, 22, 9, 0, 0))

    extracted_info = orchestrator._normalize_extracted_info(
        {},
        user_message="\u6211\u60f3\u4e94\u4e00\u53bb\u676d\u5dde\u73a93\u5929",
        session=session,
    )
    orchestrator._persist_partial_trip_context(session, extracted_info)

    assert session.trip_context.start_date == datetime(2026, 5, 1)


def test_weather_request_uses_session_start_date() -> None:
    agent = WeatherAgent(llm=None)
    session = SessionContext(session_id="weather-request")
    session.trip_context.destination = "\u676d\u5dde"
    session.trip_context.start_date = datetime(2026, 5, 1)
    context = ExecutionContext(request_id="weather-request", session_id=session.session_id)
    context.extracted_info = {"destination": "\u676d\u5dde", "duration": 2}

    request = agent._resolve_weather_request(session, context)

    assert request["start_date"] == "2026-05-01"


def test_select_forecast_window_out_of_range_keeps_warning_and_no_fake_data() -> None:
    agent = WeatherAgent(llm=None)
    forecast_items, raw_daily_items = _build_forecast_items(datetime(2026, 4, 22), 7)

    selected_forecasts, selected_raw_daily, warnings = agent._select_forecast_window(
        forecast_items,
        raw_daily_items,
        datetime(2026, 5, 1),
        3,
    )

    assert selected_forecasts == []
    assert selected_raw_daily == []
    assert warnings


def test_no_start_date_still_keeps_current_behavior() -> None:
    agent = WeatherAgent(llm=None)
    forecast_items, raw_daily_items = _build_forecast_items(datetime(2026, 4, 22), 7)

    selected_forecasts, selected_raw_daily, warnings = agent._select_forecast_window(
        forecast_items,
        raw_daily_items,
        None,
        3,
    )

    assert [item["date"] for item in selected_forecasts] == [
        "2026-04-22",
        "2026-04-23",
        "2026-04-24",
    ]
    assert [item["date"] for item in selected_raw_daily] == [
        "2026-04-22",
        "2026-04-23",
        "2026-04-24",
    ]
    assert warnings == []


def test_unresolved_lunar_holiday_does_not_fabricate_start_date(monkeypatch) -> None:
    orchestrator = AgentOrchestrator(object())
    monkeypatch.setattr(orchestrator, "_get_current_datetime", lambda: datetime(2026, 4, 22, 9, 0, 0))

    normalized = orchestrator._normalize_extracted_info(
        {},
        user_message="\u6211\u60f3\u6625\u8282\u53bb\u676d\u5dde\u73a93\u5929",
        session=SessionContext(session_id="spring-festival"),
    )

    assert normalized.get("start_date") is None
