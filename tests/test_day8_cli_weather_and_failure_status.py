from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.base import AgentResponse, AgentStatus
from app.agents.weather import WeatherAgent
from app.core.context import ExecutionContext, SessionContext
from app.core.qweather_snapshot import load_qweather_snapshot_manifest
from app.tools.weather import WeatherTool


def _context(extracted_info: dict) -> ExecutionContext:
    return ExecutionContext(
        request_id="day8-weather-status",
        session_id="day8-weather-status",
        extracted_info=extracted_info,
    )


def _snapshot_start_date() -> str:
    return str(load_qweather_snapshot_manifest()["forecast_start_date"])


def test_cli_weather_agent_reads_frozen_qweather_snapshot() -> None:
    session = SessionContext(session_id="day8-weather-full")
    context = _context(
        {
            "destination": "guilin",
            "start_date": _snapshot_start_date(),
            "duration": 2,
        }
    )

    response = asyncio.run(WeatherAgent().execute(session, context))

    assert response.status == AgentStatus.COMPLETED
    assert response.success is True
    assert response.data["provider"] == "qweather_snapshot"
    assert response.data["coverage_status"] == "full"
    assert response.metadata["real_time_api_allowed"] is False
    assert response.metadata["runtime_online_refresh_allowed"] is False


def test_cli_weather_agent_without_date_defaults_to_snapshot_first_seven_days() -> None:
    session = SessionContext(session_id="day8-weather-default-seven")
    context = _context({"destination": "guilin"})

    response = asyncio.run(WeatherAgent().execute(session, context))

    assert response.status == AgentStatus.COMPLETED
    assert response.success is True
    assert response.data["provider"] == "qweather_snapshot"
    assert response.data["date"] == _snapshot_start_date()
    assert response.data["requested_days"] == 7
    assert response.data["coverage_status"] == "full"
    assert len(response.data["daily_weather"]) == 7


def test_weather_tool_reads_frozen_snapshot_without_network_and_defaults_to_seven_days() -> None:
    result = asyncio.run(WeatherTool().execute(city="guilin"))

    assert result.success is True
    assert result.api_calls == []
    assert result.data["provider"] == "qweather_snapshot"
    assert result.data["date"] == _snapshot_start_date()
    assert result.data["requested_days"] == 7
    assert result.data["coverage_status"] == "full"
    assert result.metadata["data_source"] == "qweather_frozen_snapshot"
    assert result.metadata["date_defaulted_to_snapshot_start"] is True
    assert result.metadata["runtime_online_refresh_allowed"] is False


def test_cli_weather_runtime_does_not_require_qweather_env() -> None:
    env = dict(os.environ)
    env.pop("QWEATHER_API_HOST", None)
    env.pop("QWEATHER_API_KEY", None)
    env["PYTHONPATH"] = str(ROOT)
    code = """
import asyncio
from app.agents.weather import WeatherAgent
from app.core.context import ExecutionContext, SessionContext
from app.core.qweather_snapshot import load_qweather_snapshot_manifest
from app.tools.weather import WeatherTool

start_date = load_qweather_snapshot_manifest()["forecast_start_date"]
context = ExecutionContext(
    request_id="no-qweather-env",
    session_id="no-qweather-env",
    extracted_info={"destination": "guilin", "start_date": start_date, "duration": 1},
)
agent_result = asyncio.run(WeatherAgent().execute(SessionContext(session_id="s"), context))
tool_result = asyncio.run(WeatherTool().execute(city="guilin", date=start_date, days=1))
assert agent_result.success is True
assert tool_result.success is True
assert agent_result.data["provider"] == "qweather_snapshot"
assert tool_result.data["provider"] == "qweather_snapshot"
assert tool_result.api_calls == []
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_cli_weather_agent_treats_out_of_range_as_coverage_warning_not_failure() -> None:
    session = SessionContext(session_id="day8-weather-out-of-range")
    context = _context(
        {
            "destination": "guilin",
            "start_date": "2026-10-01",
            "duration": 3,
        }
    )

    response = asyncio.run(WeatherAgent().execute(session, context))

    assert response.status == AgentStatus.COMPLETED
    assert response.success is True
    assert response.data["provider"] == "qweather_snapshot"
    assert response.data["coverage_status"] == "out_of_range"
    assert response.data["daily_weather"] == []
    assert response.data["missing_dates"] == ["2026-10-01", "2026-10-02", "2026-10-03"]


def test_cli_weather_agent_marks_unsupported_snapshot_city_as_failed() -> None:
    session = SessionContext(session_id="day8-weather-unsupported")
    context = _context(
        {
            "destination": "lhasa",
            "start_date": _snapshot_start_date(),
            "duration": 3,
        }
    )

    response = asyncio.run(WeatherAgent().execute(session, context))

    assert response.status == AgentStatus.FAILED
    assert response.success is False
    assert response.data["provider"] == "qweather_snapshot"
    assert "unsupported qweather snapshot city" in (response.error or "")


def test_execution_context_does_not_mark_failed_agent_as_completed() -> None:
    context = _context({})
    failed = AgentResponse(
        agent_name="weather",
        status=AgentStatus.FAILED,
        content="天气快照读取失败",
        error="snapshot missing",
    )

    context.add_result("weather", failed)

    assert "weather" not in context.completed_agents
    assert "weather" in context.failed_agents
    assert context.errors["weather"]["error"] == "snapshot missing"
    assert context.retry_count == 1


def test_execution_context_marks_only_successful_agent_as_completed() -> None:
    context = _context({})
    success = AgentResponse(
        agent_name="weather",
        status=AgentStatus.COMPLETED,
        content="天气可用",
    )

    context.add_result("weather", success)

    assert context.completed_agents == ["weather"]
    assert context.failed_agents == []
    assert context.errors == {}
