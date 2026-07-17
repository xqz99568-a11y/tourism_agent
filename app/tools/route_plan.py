"""
路线规划工具
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.fixed_data import FixedDataError, get_fixed_tourism_data, is_formal_offline_mode
from app.core.logger import get_logger
from app.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)


class RoutePlanningTool(BaseTool):
    """
    路线规划工具
    根据起终点规划驾车或公交路线
    """

    name = "route_planning"
    description = "规划两点或多点之间的路线"
    parameters = {
        "type": "object",
        "properties": {
            "origin": {
                "type": "string",
                "description": "起点坐标，格式：lng,lat",
            },
            "destination": {
                "type": "string",
                "description": "终点坐标，格式：lng,lat",
            },
            "strategy": {
                "type": "string",
                "description": "路线策略：1-最快、2-最短、3-避免高速、4-避免拥堵",
                "enum": ["1", "2", "3", "4"],
            },
            "waypoints": {
                "type": "string",
                "description": "途经点，多个用|分隔",
            },
            "city": {
                "type": "string",
                "description": "固定实验城市",
            },
            "mode": {
                "type": "string",
                "description": "固定交通方式：walking、public_transit、taxi",
                "enum": ["walking", "public_transit", "taxi"],
                "default": "public_transit",
            },
            "origin_node_id": {
                "type": "string",
                "description": "固定交通矩阵起点节点 ID",
            },
            "destination_node_id": {
                "type": "string",
                "description": "固定交通矩阵终点节点 ID",
            },
        },
        "required": [],
    }

    def __init__(self):
        self.api_key = settings.amap.api_key
        self.base_url = "https://restapi.amap.com/v3/direction/driving"

    async def execute(
        self,
        origin: Optional[str] = None,
        destination: Optional[str] = None,
        strategy: str = "1",
        waypoints: Optional[str] = None,
        city: Optional[str] = None,
        mode: str = "public_transit",
        origin_node_id: Optional[str] = None,
        destination_node_id: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """执行路线规划"""
        if not self.validate_params({"origin": origin, "destination": destination}):
            return ToolResult(success=False, error="Invalid parameters")

        try:
            if is_formal_offline_mode():
                fixed_origin = origin_node_id or origin
                fixed_destination = destination_node_id or destination
                if not fixed_origin or not fixed_destination:
                    return ToolResult(success=False, error="origin and destination are required")
                route = get_fixed_tourism_data().route(
                    origin=fixed_origin,
                    destination=fixed_destination,
                    city=city,
                    mode=kwargs.get("transport_mode") or mode,
                )
                return ToolResult(
                    success=True,
                    data=route,
                    metadata={
                        "offline": True,
                        "data_source": "fixed_transport_area_matrix",
                        "real_time_api_allowed": False,
                        "source_file_id": route.get("source_file_id"),
                        "dataset_version": route.get("dataset_version"),
                    },
                    api_calls=[],
                )

            if not origin or not destination:
                return ToolResult(success=False, error="origin and destination are required")
            params = {
                "key": self.api_key,
                "origin": origin,
                "destination": destination,
                "strategy": strategy,
                "extensions": "all",
            }

            if waypoints:
                params["waypoints"] = waypoints

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.base_url, params=params)

                if response.status_code != 200:
                    return ToolResult(
                        success=False,
                        error=f"API request failed: {response.status_code}",
                    )

                data = response.json()

                if data.get("status") != "1":
                    return ToolResult(
                        success=False,
                        error=data.get("info", "Unknown error"),
                    )

                # 解析路线
                route = data.get("route", {})
                paths = route.get("paths", [])

                if not paths:
                    return ToolResult(success=False, error="No route found")

                # 获取最优路线
                best_path = paths[0]

                result = {
                    "distance_km": round(int(best_path.get("distance", 0)) / 1000, 2),
                    "duration_minutes": round(int(best_path.get("duration", 0)) / 60),
                    "strategy": strategy,
                    "steps": [
                        {
                            "instruction": step.get("instruction"),
                            "road": step.get("road"),
                            "distance": step.get("distance"),
                            "duration": step.get("duration"),
                            "orientation": step.get("orientation"),
                        }
                        for step in best_path.get("steps", [])[:10]  # 限制步骤数
                    ],
                    "traffic_lights": best_path.get("traffic_lights"),
                }

                return ToolResult(success=True, data=result)

        except Exception as e:
            if isinstance(e, FixedDataError):
                return ToolResult(success=False, error=str(e), metadata={"offline": True})
            logger.exception(f"Route planning failed: {e}")
            return ToolResult(success=False, error=str(e))


class WalkingRouteTool(BaseTool):
    """
    步行路线工具
    """

    name = "walking_route"
    description = "规划步行路线"
    parameters = {
        "type": "object",
        "properties": {
            "origin": {
                "type": "string",
                "description": "起点坐标，格式：lng,lat",
            },
            "destination": {
                "type": "string",
                "description": "终点坐标，格式：lng,lat",
            },
        },
        "required": ["origin", "destination"],
    }

    def __init__(self):
        self.api_key = settings.amap.api_key
        self.base_url = "https://restapi.amap.com/v3/direction/walking"

    async def execute(
        self,
        origin: str,
        destination: str,
        **kwargs,
    ) -> ToolResult:
        """执行步行路线规划"""
        try:
            if is_formal_offline_mode():
                route = get_fixed_tourism_data().route(
                    origin=origin,
                    destination=destination,
                    city=kwargs.get("city"),
                    mode="walking",
                )
                return ToolResult(
                    success=True,
                    data=route,
                    metadata={
                        "offline": True,
                        "data_source": "fixed_transport_area_matrix",
                        "real_time_api_allowed": False,
                    },
                    api_calls=[],
                )

            params = {
                "key": self.api_key,
                "origin": origin,
                "destination": destination,
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.base_url, params=params)
                data = response.json()

                if data.get("status") != "1":
                    return ToolResult(success=False, error=data.get("info"))

                route = data.get("route", {})
                paths = route.get("paths", [])

                if not paths:
                    return ToolResult(success=False, error="No walking route found")

                best_path = paths[0]

                result = {
                    "distance_km": round(int(best_path.get("distance", 0)) / 1000, 2),
                    "duration_minutes": round(int(best_path.get("duration", 0)) / 60),
                    "steps": [
                        {
                            "instruction": step.get("instruction"),
                            "distance": step.get("distance"),
                        }
                        for step in best_path.get("steps", [])[:5]
                    ],
                }

                return ToolResult(success=True, data=result)

        except Exception as e:
            if isinstance(e, FixedDataError):
                return ToolResult(success=False, error=str(e), metadata={"offline": True})
            logger.exception(f"Walking route planning failed: {e}")
            return ToolResult(success=False, error=str(e))


# 注册工具
def register_route_tools(registry):
    """注册路线规划工具"""
    registry.register(RoutePlanningTool())
    registry.register(WalkingRouteTool())
