"""
天气查询工具
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.logger import get_logger
from app.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)


class WeatherTool(BaseTool):
    """
    天气预报工具
    查询当前天气和未来天气预报
    """

    name = "weather_query"
    description = "查询目的地的天气预报"
    external_service = "高德地图API"  # 标识外部服务
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
        },
        "required": ["city"],
    }

    def __init__(self):
        super().__init__()
        self.api_key = settings.amap.api_key
        self.base_url = "https://restapi.amap.com/v3/weather/weatherInfo"

    async def execute(
        self,
        city: str,
        extensions: str = "all",
        **kwargs,
    ) -> ToolResult:
        """查询天气预报"""
        if not self.validate_params({"city": city}):
            return ToolResult(success=False, error="Invalid parameters")

        try:
            params = {
                "key": self.api_key,
                "city": city,
                "extensions": extensions,
            }

            start_time = time.time()

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.base_url, params=params)
                cost_ms = (time.time() - start_time) * 1000

                if response.status_code != 200:
                    self.record_api_call(
                        endpoint="/v3/weather/weatherInfo",
                        params={"city": city, "extensions": extensions},
                        status="failed",
                        http_status=response.status_code,
                        error=f"API request failed: {response.status_code}",
                        cost_ms=cost_ms,
                    )
                    return ToolResult(
                        success=False,
                        error=f"API request failed: {response.status_code}",
                    )

                data = response.json()

                if data.get("status") != "1":
                    self.record_api_call(
                        endpoint="/v3/weather/weatherInfo",
                        params={"city": city, "extensions": extensions},
                        status="failed",
                        http_status=200,
                        error=data.get("info", "Unknown error"),
                        cost_ms=cost_ms,
                    )
                    return ToolResult(
                        success=False,
                        error=data.get("info", "Unknown error"),
                    )

                # 记录成功的 API 调用
                self.record_api_call(
                    endpoint="/v3/weather/weatherInfo",
                    params={"city": city, "extensions": extensions},
                    status="completed",
                    response={
                        "lives_count": len(data.get("lives", [])),
                        "forecasts_count": len(data.get("forecasts", [])),
                    },
                    http_status=200,
                    cost_ms=cost_ms,
                )

                # 解析天气数据
                weather_data = data.get("lives", [])
                forecasts = data.get("forecasts", [])

                result = {
                    "city": city,
                    "current": self._parse_current_weather(weather_data[0] if weather_data else {}),
                    "forecast": self._parse_forecast(forecasts[0].get("casts", []) if forecasts else []),
                }

                return ToolResult(
                    success=True,
                    data=result,
                    api_calls=[{
                        "service": "高德地图API",
                        "endpoint": "/v3/weather/weatherInfo",
                        "status": "completed",
                        "cost_ms": cost_ms,
                        "city": city,
                    }],
                )

        except Exception as e:
            logger.exception(f"Weather query failed: {e}")
            self.record_api_call(
                endpoint="/v3/weather/weatherInfo",
                params={"city": city, "extensions": extensions},
                status="failed",
                error=str(e),
            )
            return ToolResult(success=False, error=str(e))

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
