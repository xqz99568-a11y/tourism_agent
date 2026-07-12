"""
Real-weather agent for itinerary collaboration.

It fetches real weather from QWeather, converts it
into stable structured fields, assesses travel risk with explicit rules, and
returns data that itinerary planning can consume directly.
"""
from __future__ import annotations

from datetime import datetime
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

from app.agents.base import AgentCapability, AgentConfig, AgentResponse, AgentStatus, BaseAgent
from app.core.context import ExecutionContext, SessionContext
from app.core.logger import get_logger
from app.services.weather_client import QWeatherWeatherClient

logger = get_logger(__name__)

# ----------------------------------------------------------------------
# WMO weather-code → Chinese description
# https://open-meteo.com/en/docs  →  WMO Code 0-99
# ----------------------------------------------------------------------
WMO_WEATHER_MAP: Dict[int, str] = {
    0: "晴",
    1: "晴间多云",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "中毛毛雨",
    55: "大毛毛雨",
    56: "冻毛毛雨",
    57: "大冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "大冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    79: "雨夹雪",
    80: "小阵雨",
    81: "中阵雨",
    82: "大阵雨",
    85: "小阵雪",
    86: "大阵雪",
    89: "小冰雹",
    90: "大冰雹",
    95: "雷阵雨",
    96: "雷暴伴小冰雹",
    99: "雷暴伴大冰雹",
}


def _wmo_to_text(code: Optional[int]) -> str:
    if code is None:
        return "未知天气"
    return WMO_WEATHER_MAP.get(int(code), "其他天气")


def _build_day_advice(item: Dict[str, Any]) -> str:
    """Generate per-day advice from structured fields; never from LLM."""
    parts: List[str] = []
    rain_prob = item.get("precipitation") or item.get("rain_prob") or 0
    max_temp = item.get("max_temp")
    wind_speed = item.get("wind_speed")
    weather = item.get("weather") or item.get("day_weather") or ""
    risk_tags: List[str] = item.get("risk_tags") or []

    if rain_prob >= 70:
        parts.append("建议带雨具")
    elif rain_prob >= 40:
        parts.append("备好雨具")
    if max_temp is not None and max_temp >= 33:
        parts.append("注意防晒降温")
    elif max_temp is not None and max_temp <= 10:
        parts.append("注意保暖")
    if wind_speed is not None and wind_speed >= 30:
        parts.append("风力较大，户外注意防风")
    if "rain" in risk_tags:
        parts.append("户外活动建议安排在室内时段")
    if "heat" in risk_tags:
        parts.append("高温时段避免暴晒")
    return "，".join(parts)

WEATHER_POLICY = {
    "max_supported_days": 7,
    "heat_temp_c": 33,
    "extreme_heat_temp_c": 36,
    "large_temp_gap_c": 8,
    "wind_medium_level": 4,
    "wind_high_level": 6,
}
RAIN_KEYWORDS = ("雨", "阵雨", "雷阵雨", "小雨", "中雨", "大雨", "暴雨")
SEVERE_KEYWORDS = ("暴雨", "大暴雨", "特大暴雨", "雷", "雷暴", "冰雹", "台风", "沙尘暴")
SUNNY_KEYWORDS = ("晴", "少云")
CLOUDY_KEYWORDS = ("多云", "阴")

WEATHER_CONFIG = AgentConfig(
    name="weather",
    description="天气 Agent，负责真实天气查询、规则化判断与 itinerary 决策支持。",
    instructions="基于真实天气结果输出结构化风险、携带建议与行程调整依据。",
    capabilities=[AgentCapability.SEARCH, AgentCapability.REASONING],
    max_retries=2,
    timeout_seconds=45,
)


class WeatherAgent(BaseAgent):
    """Fetch, normalize, and expose real weather data for planning."""

    def __init__(self, llm=None, **kwargs):
        super().__init__(WEATHER_CONFIG, llm)
        self._client = QWeatherWeatherClient()

    async def plan(self, session: SessionContext, context: ExecutionContext) -> List[str]:
        return ["resolve_location", "fetch_weather", "assess_risk", "build_guidance"]

    async def execute(self, session: SessionContext, context: ExecutionContext) -> AgentResponse:
        request = self._resolve_weather_request(session, context)
        destination = request["label"]
        if not destination and request["coordinates"] is None:
            data = self._build_fallback_weather_result("", request["requested_days"], "缺少目的地信息，无法调用真实天气接口。")
            return AgentResponse(agent_name=self.name, status=AgentStatus.COMPLETED, content="请先提供目的地城市、区域或坐标，我再为你查询真实天气。", data=data)

        self._record_thinking_reasoning(
            context,
            step_name="解析天气请求",
            reasoning_content=f"目的地：{destination or '坐标定位'}\n出行天数：{request['requested_days']} 天\n起始日期：{request['start_date'] or '未提供'}",
            reasoning_type="fact",
        )
        self._record_tool_usage(
            context,
            step_name="调用天气接口",
            tool_name="qweather_weather_api",
            arguments={"label": destination, "coordinates": request["coordinates"], "requested_days": request["requested_days"]},
        )

        try:
            provider_payload = await self._client.fetch_weather(label=destination, coordinates=request["coordinates"], context=context)
            result = self._normalize_weather(request, provider_payload) if provider_payload else self._build_fallback_weather_result(destination, request["requested_days"], "天气接口返回空数据，已返回结构化降级结果。")
            self._record_thinking_reasoning(
                context,
                step_name="天气风险评估",
                reasoning_content=f"天气类型：{result.get('weather_type')}\n风险等级：{result.get('risk_level')}\n预报覆盖：{result.get('coverage_days', 0)} 天",
                reasoning_type="analysis",
            )
            self._record_thinking_complete(context, step_name="天气风险评估", result_summary=f"天气处理完成：{result.get('weather_type')} / {result.get('risk_level')} 风险。")
            return AgentResponse(
                agent_name=self.name,
                status=AgentStatus.COMPLETED,
                content=self._build_weather_summary(result),
                data=result,
                metadata={"provider": "qweather", "degraded": result.get("degraded", False), "coverage_days": result.get("coverage_days", 0)},
            )
        except Exception as exc:
            logger.exception(f"Weather agent failed, returning degraded result: {exc}")
            result = self._build_fallback_weather_result(destination, request["requested_days"], f"天气处理异常：{exc}")
            return AgentResponse(agent_name=self.name, status=AgentStatus.COMPLETED, content=self._build_weather_summary(result), data=result, metadata={"provider": "qweather", "degraded": True})

    def _resolve_weather_request(self, session: SessionContext, context: ExecutionContext) -> Dict[str, Any]:
        extracted = context.extracted_info or {}
        destination = next(
            (str(value).strip() for value in [
                extracted.get("city"),
                extracted.get("destination"),
                extracted.get("location"),
                extracted.get("region"),
                extracted.get("area"),
                extracted.get("query"),
                session.trip_context.destination,
            ] if str(value or "").strip()),
            "",
        )
        longitude = self._coerce_float(extracted.get("lng") or extracted.get("longitude") or extracted.get("lon"))
        latitude = self._coerce_float(extracted.get("lat") or extracted.get("latitude"))
        coordinates = (longitude, latitude) if longitude is not None and latitude is not None else None
        return {
            "label": destination,
            "coordinates": coordinates,
            "requested_days": self._resolve_trip_days(session, extracted),
            "start_date": self._normalize_request_start_date(extracted.get("start_date") or session.trip_context.start_date),
        }

    def _resolve_trip_days(self, session: SessionContext, extracted: Dict[str, Any]) -> int:
        for key in ("duration", "travel_days", "days"):
            value = self._coerce_int(extracted.get(key))
            if value and value > 0:
                return min(value, WEATHER_POLICY["max_supported_days"])
        start_date = self._parse_date(extracted.get("start_date") or session.trip_context.start_date)
        end_date = self._parse_date(extracted.get("end_date") or session.trip_context.end_date)
        if start_date and end_date and end_date >= start_date:
            return min((end_date - start_date).days + 1, WEATHER_POLICY["max_supported_days"])
        trip_days = self._coerce_int(session.trip_context.duration_days)
        return min(trip_days or 3, WEATHER_POLICY["max_supported_days"])

    def _normalize_weather(self, request: Dict[str, Any], provider_payload: Dict[str, Any]) -> Dict[str, Any]:
        location = provider_payload.get("location") or {}
        current = self._normalize_current(provider_payload.get("current") or {})
        forecast_items = provider_payload.get("forecast") or []
        raw_daily_items = ((provider_payload.get("raw") or {}).get("daily") or [])
        selected_forecasts, selected_raw_daily, selection_warnings = self._select_forecast_window(
            forecast_items,
            raw_daily_items,
            request.get("start_date"),
            request["requested_days"],
        )
        daily_forecasts = [self._normalize_daily(cast) for cast in selected_forecasts]
        risk_level = self._assess_weather_risk(daily_forecasts)
        warnings: List[str] = list(selection_warnings)
        if len(daily_forecasts) < request["requested_days"]:
            warnings.append(f"天气预报仅覆盖未来 {len(daily_forecasts)} 天，超出部分不伪造。")
        current_available = current.get("temperature") is not None or bool(current.get("weather"))
        forecast_available = bool(daily_forecasts)
        degraded = bool(warnings) or not forecast_available
        result = {
            "provider": "qweather",
            "available": current_available or forecast_available,
            "degraded": degraded,
            "current_available": current_available,
            "forecast_available": forecast_available,
            "forecast_type": "qweather_7d",
            "destination": request["label"] or location.get("city") or "目的地",
            "city": location.get("city") or request["label"],
            "location": {
                "city": location.get("city"),
                "province": location.get("province"),
                "district": location.get("district"),
                "adcode": location.get("adcode"),
                "location": location.get("location"),
                "coordinates": request["coordinates"],
                "location_id": provider_payload.get("location_id"),
                "source": provider_payload.get("location_source"),
                "resolved_query": provider_payload.get("resolved_query") or request.get("label"),
            },
            "requested_days": request["requested_days"],
            "coverage_days": len(daily_forecasts),
            "current": current,
            "daily_forecasts": daily_forecasts,
            "forecast": daily_forecasts,
            "daily_weather": daily_forecasts,
            "temperature_range": self._build_temperature_range(daily_forecasts),
            "weather_type": self._infer_weather_type(daily_forecasts, risk_level),
            "risk_level": risk_level,
            "risk_tags": self._collect_overall_tags(daily_forecasts),
            "packing_list": self._build_packing_list(daily_forecasts, risk_level),
            "alternatives": self._build_alternatives(daily_forecasts, risk_level),
            "warnings": warnings,
            "applied_rules": self._collect_applied_rules(daily_forecasts, risk_level),
            "provider_trace": {
                "location_id": provider_payload.get("location_id"),
                "location_source": provider_payload.get("location_source"),
                "resolved_query": provider_payload.get("resolved_query") or request.get("label"),
                "current": current.get("provider_raw") if isinstance(current.get("provider_raw"), dict) else {},
                "daily": selected_raw_daily,
            },
        }
        return result

    def _normalize_current(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "temperature": self._coerce_int(data.get("temperature")),
            "weather": str(data.get("weather") or "").strip(),
            "wind_direction": str(data.get("wind_direction") or "").strip(),
            "wind_level": self._coerce_int(data.get("wind_level")),
            "humidity": self._coerce_int(data.get("humidity")),
            "report_time": str(data.get("report_time") or "").strip(),
            "provider_raw": data.get("provider_raw") if isinstance(data.get("provider_raw"), dict) else {},
        }

    def _normalize_daily(self, cast: Dict[str, Any]) -> Dict[str, Any]:
        code = cast.get("weather_code")
        day_weather_text = str(cast.get("day_weather") or cast.get("weather") or "").strip() or _wmo_to_text(code)
        night_weather_text = str(cast.get("night_weather") or "").strip()
        max_temp = self._coerce_int(cast.get("max_temp"))
        min_temp = self._coerce_int(cast.get("min_temp"))
        wind_speed = cast.get("wind_speed")
        precip_prob = cast.get("precipitation_probability")

        rain_prob_int = self._coerce_int(precip_prob)

        risk_tags = self._infer_daily_risk_tags(day_weather_text, night_weather_text, max_temp, min_temp, wind_speed, rain_prob_int)

        return {
            "date": str(cast.get("date") or "").strip(),
            "week": "",
            "weather": day_weather_text,
            "day_weather": day_weather_text,
            "night_weather": night_weather_text,
            "min_temp": min_temp,
            "max_temp": max_temp,
            "wind_speed": wind_speed,
            "wind_level": None,
            "humidity": None,
            "precipitation": rain_prob_int,
            "rain_prob": rain_prob_int,
            "suitable_periods": self._infer_suitable_periods(risk_tags),
            "risk_tags": risk_tags,
            "risk_level": self._risk_level_from_tags(risk_tags),
            "provider_raw": cast.get("raw") if isinstance(cast.get("raw"), dict) else {},
        }

    def _select_forecast_window(
        self,
        forecast_items: List[Dict[str, Any]],
        raw_daily_items: List[Dict[str, Any]],
        start_date_value: Any,
        requested_days: int,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        warnings: List[str] = []
        start_date = self._parse_date(start_date_value)
        start_index = 0

        if start_date:
            matched_index: Optional[int] = None
            for idx, item in enumerate(forecast_items):
                forecast_date = self._parse_date(item.get("date"))
                if forecast_date and forecast_date >= start_date:
                    matched_index = idx
                    break
            if matched_index is None:
                return [], [], [f"行程开始日期 {start_date.isoformat()} 不在和风 7 日预报覆盖范围内，不伪造天气。"]
            start_index = matched_index

        end_index = start_index + max(requested_days, 0)
        return (
            forecast_items[start_index:end_index],
            raw_daily_items[start_index:end_index],
            warnings,
        )

    def _build_temperature_range(self, daily_forecasts: List[Dict[str, Any]]) -> Dict[str, Any]:
        mins = [item["min_temp"] for item in daily_forecasts if item.get("min_temp") is not None]
        maxs = [item["max_temp"] for item in daily_forecasts if item.get("max_temp") is not None]
        values = [*mins, *maxs]
        return {"min": min(mins) if mins else None, "max": max(maxs) if maxs else None, "avg": round(mean(values), 1) if values else None, "by_day": [{"date": item.get("date"), "min": item.get("min_temp"), "max": item.get("max_temp")} for item in daily_forecasts]}

    def _assess_weather_risk(self, daily_forecasts: List[Dict[str, Any]]) -> str:
        if not daily_forecasts:
            return "medium"
        if any(item.get("risk_level") == "high" for item in daily_forecasts):
            return "high"
        if any(item.get("risk_level") == "medium" for item in daily_forecasts):
            return "medium"
        return "low"

    def _infer_weather_type(self, daily_forecasts: List[Dict[str, Any]], risk_level: str) -> str:
        if not daily_forecasts:
            return "unavailable"
        combined = " ".join(f"{item.get('day_weather', '')} {item.get('night_weather', '')}" for item in daily_forecasts)
        highest_temp = max((item.get("max_temp") or -99) for item in daily_forecasts)
        if any(word in combined for word in SEVERE_KEYWORDS) or risk_level == "high":
            return "storm_risk"
        if any(word in combined for word in RAIN_KEYWORDS):
            return "rainy"
        if highest_temp >= WEATHER_POLICY["heat_temp_c"]:
            return "sunny_hot"
        if any(word in combined for word in CLOUDY_KEYWORDS):
            return "cloudy_stable"
        if any(word in combined for word in SUNNY_KEYWORDS):
            return "sunny_stable"
        return "variable"

    def _build_packing_list(self, daily_forecasts: List[Dict[str, Any]], risk_level: str) -> List[str]:
        items = ["轻便鞋"]
        tags = self._collect_overall_tags(daily_forecasts)
        highest_temp = max((item.get("max_temp") or -99) for item in daily_forecasts) if daily_forecasts else None
        lowest_temp = min((item.get("min_temp") or 99) for item in daily_forecasts) if daily_forecasts else None
        if "rain" in tags:
            items.extend(["雨具", "防滑鞋"])
        if "wind" in tags:
            items.append("防风外套")
        if "temperature_gap" in tags:
            items.append("薄外套")
        if highest_temp is not None and highest_temp >= WEATHER_POLICY["heat_temp_c"]:
            items.extend(["防晒用品", "透气衣物", "补水用品"])
        if lowest_temp is not None and lowest_temp <= 12:
            items.append("保温衣物")
        if risk_level == "high":
            items.append("应急备用衣物")
        return self._dedupe(items)

    def _build_alternatives(self, daily_forecasts: List[Dict[str, Any]], risk_level: str) -> List[Dict[str, Any]]:
        tags = self._collect_overall_tags(daily_forecasts)
        items: List[Dict[str, Any]] = []
        if "rain" in tags:
            items.append({"condition": "rain", "action": "雨天优先切换到室内展馆、博物馆、商场或餐饮街区，减少公园、山地和长步行路线。", "preferred_categories": ["museum", "exhibition", "mall", "food", "cultural_indoor"]})
        if "heat" in tags:
            items.append({"condition": "heat", "action": "高温时段把户外活动前置到上午或后置到傍晚，中午优先午餐、午休或室内活动。", "preferred_categories": ["restaurant", "cafe", "mall", "museum", "indoor_rest"]})
        if "storm" in tags or "wind" in tags or risk_level == "high":
            items.append({"condition": "storm_or_wind", "action": "恶劣天气下减少山顶、滨水、露天观景和长距离步行项目，优先采用室内替代方案。", "preferred_categories": ["museum", "mall", "exhibition", "indoor_attraction", "food"]})
        return items or [{"condition": "stable", "action": "天气整体稳定，可按常规行程推进，保留少量室内机动位即可。", "preferred_categories": ["mixed"]}]

    def _collect_applied_rules(self, daily_forecasts: List[Dict[str, Any]], risk_level: str) -> List[str]:
        tags = self._collect_overall_tags(daily_forecasts)
        rules: List[str] = []
        if "rain" in tags:
            rules.append("rain_reduce_outdoor")
        if "heat" in tags:
            rules.append("heat_shift_outdoor_to_morning_evening")
        if "storm" in tags or "wind" in tags or risk_level == "high":
            rules.append("storm_or_wind_use_indoor_alternatives")
        if "temperature_gap" in tags:
            rules.append("temperature_gap_adjust_packing")
        return rules

    def _build_weather_summary(self, result: Dict[str, Any]) -> str:
        temp = result.get("temperature_range") or {}
        temp_text = f"{temp.get('min')} - {temp.get('max')}°C" if temp.get("min") is not None and temp.get("max") is not None else "暂无温度区间"
        lines = [f"## {(result.get('destination') or '目的地')} 天气", "- 数据来源：和风天气（QWeather）", f"- 天气类型：{result.get('weather_type')}", f"- 风险等级：{result.get('risk_level')}", f"- 温度区间：{temp_text}"]
        if result.get("warnings"):
            lines.append(f"- 降级说明：{'；'.join(str(item) for item in result['warnings'])}")
        daily_forecasts = result.get("daily_forecasts") or []
        if daily_forecasts:
            lines.append("")
            lines.append("### 逐日预报")
            for item in daily_forecasts:
                advice = _build_day_advice(item)
                lines.append(f"- {item.get('date') or '未知日期'}：{item.get('day_weather') or item.get('weather')}，{item.get('min_temp')} - {item.get('max_temp')}°C，风速 {item.get('wind_speed')} km/h，降水概率 {item.get('precipitation') or 0}%{'，' + advice if advice else ''}")
        if result.get("packing_list"):
            lines.append("")
            lines.append(f"### 携带建议\n- {'、'.join(result['packing_list'])}")
        if result.get("alternatives"):
            lines.append("")
            lines.append("### 天气替代方案")
            for item in result["alternatives"]:
                lines.append(f"- {item.get('condition')}：{item.get('action')}")
        return "\n".join(lines)

    def _build_fallback_weather_result(self, destination: str, requested_days: int, warning: str) -> Dict[str, Any]:
        return {
            "provider": "qweather",
            "available": False,
            "degraded": True,
            "current_available": False,
            "forecast_available": False,
            "forecast_type": "unavailable",
            "destination": destination or "目的地",
            "city": destination or "目的地",
            "location": {"city": destination or None, "province": None, "district": None, "adcode": None, "location": None, "coordinates": None, "location_id": None, "source": None, "resolved_query": destination or None},
            "requested_days": requested_days,
            "coverage_days": 0,
            "current": {"temperature": None, "weather": "", "wind_direction": "", "wind_level": None, "humidity": None, "report_time": "", "provider_raw": {}},
            "daily_forecasts": [],
            "forecast": [],
            "daily_weather": [],
            "temperature_range": {"min": None, "max": None, "avg": None, "by_day": []},
            "weather_type": "unavailable",
            "risk_level": "medium",
            "risk_tags": [],
            "packing_list": ["请在出发前再次确认天气"],
            "alternatives": [{"condition": "weather_unavailable", "action": "天气接口不可用时，不伪造天气数据，建议保留可切换的室内备选方案。", "preferred_categories": ["museum", "mall", "food", "mixed"]}],
            "warnings": [warning],
            "applied_rules": ["weather_api_unavailable"],
            "provider_trace": {"location_id": None, "location_source": None, "resolved_query": destination or None, "current": {}, "daily": []},
        }

    def _infer_daily_risk_tags(self, day_weather: str, night_weather: str, max_temp: Optional[int], min_temp: Optional[int], wind_speed: Optional[float], rain_prob: Optional[int]) -> List[str]:
        tags: List[str] = []
        weather_text = f"{day_weather} {night_weather}"
        if any(word in weather_text for word in RAIN_KEYWORDS):
            tags.append("rain")
        if any(word in weather_text for word in SEVERE_KEYWORDS):
            tags.append("storm")
        if rain_prob is not None and rain_prob >= 60:
            tags.append("rain")
        if max_temp is not None and max_temp >= WEATHER_POLICY["heat_temp_c"]:
            tags.append("heat")
        if wind_speed is not None and wind_speed >= 25:
            tags.append("wind")
        if max_temp is not None and min_temp is not None and max_temp - min_temp >= WEATHER_POLICY["large_temp_gap_c"]:
            tags.append("temperature_gap")
        return tags

    def _risk_level_from_tags(self, tags: List[str]) -> str:
        if "storm" in tags or ("rain" in tags and "heat" in tags):
            return "high"
        if any(tag in tags for tag in ("rain", "heat", "wind", "temperature_gap")):
            return "medium"
        return "low"

    def _infer_suitable_periods(self, risk_tags: List[str]) -> List[str]:
        if "storm" in risk_tags:
            return ["indoor_daytime"]
        if "rain" in risk_tags:
            return ["morning_indoor", "afternoon_indoor"]
        if "heat" in risk_tags:
            return ["morning", "evening"]
        return ["morning", "afternoon", "evening"]

    def _collect_overall_tags(self, daily_forecasts: List[Dict[str, Any]]) -> List[str]:
        tags: List[str] = []
        for item in daily_forecasts:
            tags.extend(item.get("risk_tags") or [])
        return self._dedupe(tags)

    def _parse_wind_level(self, value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        text = str(value).strip().replace("≤", "").replace("级", "")
        valid = [self._coerce_int(part) for part in text.split("-")]
        numbers = [item for item in valid if item is not None]
        if numbers:
            return max(numbers)
        digits = "".join(ch for ch in text if ch.isdigit())
        return int(digits) if digits else None

    def _coerce_int(self, value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(round(value))
        digits = "".join(ch for ch in str(value).strip() if ch.isdigit() or ch == "-")
        try:
            return int(digits) if digits else None
        except ValueError:
            return None

    def _coerce_float(self, value: Any) -> Optional[float]:
        try:
            return float(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def _parse_date(self, value: Any) -> Optional[datetime.date]:
        if not value:
            return None
        if hasattr(value, "date"):
            try:
                return value.date()
            except Exception:
                pass
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None

    def _normalize_request_start_date(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d")
        text = str(value).strip()
        return text

    def _dedupe(self, items: List[str]) -> List[str]:
        seen = set()
        result: List[str] = []
        for item in items:
            text = str(item or "").strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return result
