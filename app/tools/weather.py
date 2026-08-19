"""
天气查询工具
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.core.qweather_snapshot import (
    QWEATHER_DEFAULT_WEATHER_QUERY_DAYS,
    QWEATHER_MAX_QUERY_DAYS,
    QWeatherSnapshotError,
    load_qweather_snapshot_manifest,
    query_qweather_snapshot,
)
from app.core.logger import get_logger
from app.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)


def _bounded_weather_days(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = QWEATHER_DEFAULT_WEATHER_QUERY_DAYS
    return max(1, min(parsed, QWEATHER_MAX_QUERY_DAYS))


class WeatherTool(BaseTool):
    """
    天气预报工具
    查询当前天气和未来天气预报
    """

    name = "weather_query"
    description = "查询目的地的天气预报"
    external_service = "qweather_frozen_snapshot"
    parameters = {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "城市名称",
            },
            "extensions": {
                "type": "string",
                "description": "预报类型：base-基础预报，all-完整预报",
                "enum": ["base", "all"],
                "default": "all",
            },
            "scenario_type": {
                "type": "string",
                "description": "固定实验天气场景",
                "enum": ["sunny", "rain", "high_temperature", "low_temperature", "continuous_change"],
                "default": "sunny",
            },
            "days": {
                "type": "integer",
                "description": "返回的 day_index 天数",
                "default": 5,
            },
        },
        "required": ["city"],
    }

    def __init__(self):
        super().__init__()

    async def execute(
        self,
        city: str,
        extensions: str = "all",
        scenario_type: str = "sunny",
        days: int = QWEATHER_DEFAULT_WEATHER_QUERY_DAYS,
        **kwargs,
    ) -> ToolResult:
        """查询天气预报"""
        if not self.validate_params({"city": city}):
            return ToolResult(success=False, error="Invalid parameters")

        try:
            requested_days = _bounded_weather_days(kwargs.get("duration") or days)
            explicit_date = kwargs.get("start_date") or kwargs.get("date")
            start_date = explicit_date or load_qweather_snapshot_manifest().get("forecast_start_date")
            result = query_qweather_snapshot(
                city=city,
                start_date=str(start_date or ""),
                days=requested_days,
            )
            date_defaulted = not bool(explicit_date)
            return ToolResult(
                success=True,
                data=result,
                metadata={
                    "offline": True,
                    "data_source": "qweather_frozen_snapshot",
                    "source_mode": "qweather_frozen_snapshot",
                    "real_time_api_allowed": False,
                    "snapshot_id": result.get("snapshot_id"),
                    "snapshot_combined_sha256": result.get("snapshot_combined_sha256"),
                    "coverage_status": result.get("coverage_status"),
                    "date_defaulted_to_snapshot_start": date_defaulted,
                    "runtime_online_refresh_allowed": False,
                },
                api_calls=[],
            )

        except Exception as e:
            if isinstance(e, QWeatherSnapshotError):
                return ToolResult(
                    success=False,
                    error=str(e),
                    metadata={
                        "offline": True,
                        "data_source": "qweather_frozen_snapshot",
                        "source_mode": "qweather_frozen_snapshot",
                        "real_time_api_allowed": False,
                        "runtime_online_refresh_allowed": False,
                    },
                    api_calls=[],
                )
            logger.exception(f"Weather query failed: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                metadata={
                    "offline": True,
                    "data_source": "qweather_frozen_snapshot",
                    "source_mode": "qweather_frozen_snapshot",
                    "real_time_api_allowed": False,
                    "runtime_online_refresh_allowed": False,
                },
                api_calls=[],
            )

    def _parse_current_weather(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """解析当前天气"""
        return {
            "temperature": data.get("temperature"),
            "weather": data.get("weather"),
            "wind_direction": data.get("winddirection"),
            "wind_power": data.get("windpower"),
            "humidity": data.get("humidity"),
            "report_time": data.get("report_time"),
        }

    def _parse_forecast(self, casts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """解析预报数据"""
        return [
            {
                "date": cast.get("date"),
                "week": cast.get("week"),
                "day_weather": cast.get("dayweather"),
                "night_weather": cast.get("nightweather"),
                "day_temp": cast.get("daytemp"),
                "night_temp": cast.get("nighttemp"),
                "day_wind": cast.get("daywind"),
                "night_wind": cast.get("nightwind"),
            }
            for cast in casts[:7]
        ]


class WeatherRiskTool(BaseTool):
    """
    天气风险评估工具
    评估天气对行程的影响
    """

    name = "weather_risk_assessment"
    description = "评估天气风险并提供行程调整建议"
    parameters = {
        "type": "object",
        "properties": {
            "weather_data": {
                "type": "object",
                "description": "天气数据（来自 weather_query 结果）",
            },
            "activity_type": {
                "type": "string",
                "description": "活动类型：outdoor、indoor、mixed",
                "enum": ["outdoor", "indoor", "mixed"],
                "default": "mixed",
            },
        },
        "required": ["weather_data"],
    }

    async def execute(
        self,
        weather_data: Dict[str, Any],
        activity_type: str = "mixed",
        **kwargs,
    ) -> ToolResult:
        """评估天气风险"""
        try:
            risk_level = self._calculate_risk(weather_data, activity_type)
            suggestions = self._generate_suggestions(weather_data, activity_type)

            result = {
                "risk_level": risk_level,  # low, medium, high
                "risk_factors": self._identify_risk_factors(weather_data),
                "suggestions": suggestions,
                "overall_score": self._calculate_overall_score(weather_data),
            }

            return ToolResult(success=True, data=result)

        except Exception as e:
            logger.exception(f"Weather risk assessment failed: {e}")
            return ToolResult(success=False, error=str(e))

    def _calculate_risk(self, weather_data: Dict[str, Any], activity_type: str) -> str:
        """计算风险等级"""
        forecast = weather_data.get("forecast", [])
        if not forecast:
            return "unknown"

        # 检查未来几天的天气
        high_risk_days = 0
        medium_risk_days = 0

        for day in forecast:
            # 恶劣天气
            bad_weather = ["雨", "雪", "雾", "霾", "暴", "雷"]
            if any(w in day.get("day_weather", "") for w in bad_weather):
                high_risk_days += 1
            elif "阴" in day.get("day_weather", "") or "多云" in day.get("day_weather", ""):
                medium_risk_days += 1

        if high_risk_days > len(forecast) // 2:
            return "high"
        elif high_risk_days > 0 or medium_risk_days > len(forecast) // 2:
            return "medium"
        return "low"

    def _identify_risk_factors(self, weather_data: Dict[str, Any]) -> List[str]:
        """识别风险因素"""
        factors = []
        forecast = weather_data.get("forecast", [])

        for day in forecast:
            weather = day.get("day_weather", "")
            if "雨" in weather:
                factors.append("降雨天气")
            if "雪" in weather:
                factors.append("降雪天气")
            if "雾" in weather or "霾" in weather:
                factors.append("能见度低")
            if "雷" in weather:
                factors.append("雷暴天气")

        return list(set(factors))[:5]

    def _generate_suggestions(
        self,
        weather_data: Dict[str, Any],
        activity_type: str,
    ) -> List[str]:
        """生成建议"""
        suggestions = []
        forecast = weather_data.get("forecast", [])

        for day in forecast:
            day_suggestions = []

            weather = day.get("day_weather", "")

            # 根据天气给出建议
            if "雨" in weather:
                day_suggestions.append("建议准备雨具，安排室内活动")
            if "雪" in weather:
                day_suggestions.append("注意保暖和交通安全")
            if "晴" in weather:
                day_suggestions.append("适合户外活动，注意防晒")
            if "阴" in weather or "多云" in weather:
                day_suggestions.append("天气适宜，可正常安排活动")

            # 温度建议
            day_temp = day.get("day_temp", "0")
            try:
                temp = int(day_temp)
                if temp > 30:
                    day_suggestions.append("高温天气，注意防暑")
                elif temp < 10:
                    day_suggestions.append("气温较低，注意保暖")
            except:
                pass

            if day_suggestions:
                suggestions.append({
                    "date": day.get("date"),
                    "suggestions": day_suggestions,
                })

        return suggestions

    def _calculate_overall_score(self, weather_data: Dict[str, Any]) -> int:
        """计算整体评分 (0-100)"""
        score = 100
        forecast = weather_data.get("forecast", [])

        for day in forecast:
            weather = day.get("day_weather", "")

            # 扣分项
            if "雨" in weather:
                score -= 15
            if "雪" in weather:
                score -= 20
            if "雾" in weather or "霾" in weather:
                score -= 10
            if "雷" in weather:
                score -= 25

        return max(0, score)


# 注册工具
def register_weather_tools(registry):
    """注册天气工具"""
    registry.register(WeatherTool())
    registry.register(WeatherRiskTool())
