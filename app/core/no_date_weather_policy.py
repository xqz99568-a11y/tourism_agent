"""Shared policy for no-date trip plans and weather reminders."""
from __future__ import annotations

from typing import Any, Mapping


NO_DATE_WEATHER_POLICY = "no_date_no_specific_weather_for_trip_plan"
NO_DATE_WEATHER_REMINDER = (
    "当前行程未结合具体出发日期的天气情况，建议出发前重新查询实时天气并适当调整安排。"
)


def gold_requires_no_date_weather_reminder(gold: Mapping[str, Any] | None) -> bool:
    """Return whether a gold label requires the no-date weather reminder."""
    if not isinstance(gold, Mapping):
        return False
    return bool(
        gold.get("no_date_weather_reminder_required") is True
        or gold.get("weather_date_policy") == NO_DATE_WEATHER_POLICY
    )


def append_no_date_weather_reminder(content: Any) -> str:
    """Append the canonical no-date weather reminder once."""
    text = str(content or "").rstrip()
    if NO_DATE_WEATHER_REMINDER in text:
        return text
    return f"{text}\n\n{NO_DATE_WEATHER_REMINDER}" if text else NO_DATE_WEATHER_REMINDER


def answer_has_no_date_weather_reminder(content: Any) -> bool:
    """Accept the canonical reminder or a semantically equivalent Chinese reminder."""
    text = str(content or "").strip()
    if NO_DATE_WEATHER_REMINDER in text:
        return True
    compact = "".join(text.split())
    no_date_signal = any(
        term in compact
        for term in (
            "未结合具体出发日期",
            "没有结合具体出发日期",
            "没有提供明确出发日期",
            "没有明确出发日期",
            "未提供明确出发日期",
        )
    )
    weather_signal = "天气" in compact
    predeparture_signal = "出发前" in compact
    query_signal = any(term in compact for term in ("重新查询", "查询", "查看", "确认"))
    return no_date_signal and weather_signal and predeparture_signal and query_signal
