"""
Dynamic Replanner
动态重规划服务
当天气突变或交通延误时自动调整行程
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import uuid

from app.core.logger import get_logger
from app.schemas import ItinerarySchema, DayPlanSchema

logger = get_logger(__name__)


class DisruptionType(str, Enum):
    """中断/变更类型"""
    WEATHER_WARNING = "weather_warning"      # 天气预警
    HEAVY_RAIN = "heavy_rain"             # 暴雨
    TRAFFIC_DELAY = "traffic_delay"        # 交通延误
    ATTRACTION_CLOSED = "attraction_closed"  # 景点关闭
    EMERGENCY = "emergency"                # 紧急情况


@dataclass
class Disruption:
    """中断事件"""
    id: str
    type: DisruptionType
    location: str  # 受影响地点
    description: str
    severity: str = "medium"  # low, medium, high, severe
    start_time: datetime
    expected_end_time: Optional[datetime] = None
    alternatives: List[str] = field(default_factory=list)


@dataclass
class PlanAdjustment:
    """计划调整"""
    original_plan: Dict[str, Any]
    adjusted_plan: Dict[str, Any]
    changes: List[Dict[str, Any]] = field(default_factory=list)
    estimated_delay_minutes: int = 0
    additional_cost: float = 0
    reasoning: str = ""


class WeatherImpactAnalyzer:
    """天气影响分析器"""

    # 天气类型对景点的影响
    WEATHER_IMPACT_MAP = {
        "rainy": {
            "outdoor": "high",      # 户外景点影响大
            "indoor": "low",        # 室内景点影响小
            "museum": "none",       # 博物馆无影响
            "shopping": "low",      # 购物影响小
        },
        "stormy": {
            "outdoor": "severe",
            "indoor": "low",
            "museum": "none",
            "shopping": "medium",
        },
        "sunny": {
            "outdoor": "positive",  # 好天气户外景点加分
            "indoor": "neutral",
            "museum": "neutral",
            "shopping": "neutral",
        },
        "snowy": {
            "outdoor": "severe",
            "indoor": "low",
            "museum": "none",
            "shopping": "low",
        },
    }

    # 景点类型映射
    ATTRACTION_TYPES = {
        "outdoor": ["公园", "景区", "山", "湖", "海滩", "游乐园"],
        "indoor": ["餐厅", "商场", "剧院", "影院"],
        "museum": ["博物馆", "纪念馆", "展览馆", "美术馆"],
        "shopping": ["商业街", "免税店", "特产店"],
    }

    def analyze_weather_impact(
        self,
        planned_attractions: List[Dict[str, Any]],
        weather_condition: str,
    ) -> List[Dict[str, Any]]:
        """
        分析天气对已计划景点的影响

        Args:
            planned_attractions: 已计划的景点列表
            weather_condition: 天气状况

        Returns:
            List: 各景点的受影响程度和建议
        """
        impact_map = self.WEATHER_IMPACT_MAP.get(
            weather_condition,
            self.WEATHER_IMPACT_MAP["sunny"]
        )

        impacts = []

        for attraction in planned_attractions:
            category = attraction.get("category", "")
            name = attraction.get("name", "")

            # 判断景点类型
            attraction_type = self._classify_attraction(name, category)

            # 获取影响程度
            impact_level = impact_map.get(attraction_type, "neutral")

            # 生成建议
            suggestion = self._generate_weather_suggestion(
                name, weather_condition, attraction_type, impact_level
            )

            impacts.append({
                "attraction": name,
                "type": attraction_type,
                "impact": impact_level,
                "suggestion": suggestion,
                "priority": self._calculate_priority(impact_level),
            })

        # 按优先级排序
        impacts.sort(key=lambda x: x["priority"], reverse=True)

        return impacts

    def _classify_attraction(self, name: str, category: str) -> str:
        """分类景点类型"""
        combined = f"{name} {category}"

        for atype, keywords in self.ATTRACTION_TYPES.items():
            if any(kw in combined for kw in keywords):
                return atype

        return "indoor"  # 默认室内

    def _generate_weather_suggestion(
        self,
        name: str,
        weather: str,
        attraction_type: str,
        impact: str,
    ) -> str:
        """生成天气相关建议"""
        if impact == "none":
            return f"{name}不受影响，可正常游览"
        elif impact == "low":
            return f"{name}受天气影响较小，建议正常安排"
        elif impact == "medium":
            return f"建议准备雨具，或考虑调整{name}的游览时间"
        elif impact == "high":
            return f"建议将{name}调整至室内时段或更换景点"
        elif impact == "severe":
            return f"强烈建议取消{name}的户外行程，改为室内活动"
        elif impact == "positive":
            return f"好天气适合游览{name}，建议优先安排"
        else:
            return f"正常安排{name}"

    def _calculate_priority(self, impact: str) -> int:
        """计算处理优先级"""
        priority_map = {
            "severe": 5,
            "high": 4,
            "medium": 3,
            "low": 2,
            "none": 1,
            "positive": 0,
        }
        return priority_map.get(impact, 1)


class DynamicReplanner:
    """
    动态重规划器
    处理突发情况下的行程调整
    """

    def __init__(self):
        self.weather_analyzer = WeatherImpactAnalyzer()

    def detect_disruption(
        self,
        weather_data: Optional[Dict[str, Any]] = None,
        traffic_data: Optional[Dict[str, Any]] = None,
    ) -> List[Disruption]:
        """
        检测中断事件

        Args:
            weather_data: 天气数据
            traffic_data: 交通数据

        Returns:
            List[Disruption]: 检测到的中断事件列表
        """
        disruptions = []

        # 检测天气中断
        if weather_data:
            disruptions.extend(self._detect_weather_disruptions(weather_data))

        # 检测交通中断
        if traffic_data:
            disruptions.extend(self._detect_traffic_disruptions(traffic_data))

        return disruptions

    def _detect_weather_disruptions(
        self,
        weather_data: Dict[str, Any],
    ) -> List[Disruption]:
        """检测天气相关中断"""
        disruptions = []

        condition = weather_data.get("condition", "").lower()
        precipitation = weather_data.get("precipitation_chance", 0)
        wind_speed = weather_data.get("wind_speed", 0)

        if condition in ["rainy", "stormy"]:
            disruptions.append(Disruption(
                id=str(uuid.uuid4()),
                type=DisruptionType.WEATHER_WARNING,
                location=weather_data.get("location", "目的地"),
                description=f"天气预报显示{condition}，降水概率{precipitation}%",
                severity="high" if condition == "stormy" else "medium",
                start_time=datetime.now(),
                alternatives=["室内景点", "购物中心", "博物馆"],
            ))

        if precipitation > 70:
            disruptions.append(Disruption(
                id=str(uuid.uuid4()),
                type=DisruptionType.HEAVY_RAIN,
                location=weather_data.get("location", "目的地"),
                description=f"降水概率高达{precipitation}%，户外活动受影响",
                severity="high",
                start_time=datetime.now(),
                alternatives=["博物馆之旅", "室内美食探索"],
            ))

        if wind_speed > 15:  # m/s
            disruptions.append(Disruption(
                id=str(uuid.uuid4()),
                type=DisruptionType.WEATHER_WARNING,
                location=weather_data.get("location", "目的地"),
                description=f"大风天气，风速{wind_speed}m/s",
                severity="medium",
                start_time=datetime.now(),
                alternatives=["室内活动", "商场购物"],
            ))

        return disruptions

    def _detect_traffic_disruptions(
        self,
        traffic_data: Dict[str, Any],
    ) -> List[Disruption]:
        """检测交通中断"""
        disruptions = []

        delay_minutes = traffic_data.get("delay_minutes", 0)
        route = traffic_data.get("route", "")

        if delay_minutes > 30:
            disruptions.append(Disruption(
                id=str(uuid.uuid4()),
                type=DisruptionType.TRAFFIC_DELAY,
                location=route,
                description=f"预计延误{delay_minutes}分钟",
                severity="high" if delay_minutes > 60 else "medium",
                start_time=datetime.now(),
                expected_end_time=datetime.now() + timedelta(minutes=delay_minutes),
                alternatives=["地铁", "步行", "更换路线"],
            ))

        return disruptions

    def create_replan_suggestions(
        self,
        current_plan: Dict[str, Any],
        disruptions: List[Disruption],
        available_alternatives: List[Dict[str, Any]],
    ) -> PlanAdjustment:
        """
        创建重规划建议

        Args:
            current_plan: 当前计划
            disruptions: 中断事件
            available_alternatives: 可用的替代景点

        Returns:
            PlanAdjustment: 调整建议
        """
        changes = []

        # 分析每个中断的影响
        for disruption in disruptions:
            change = self._create_change_for_disruption(
                disruption, available_alternatives
            )
            changes.append(change)

        # 构建调整后的计划
        adjusted_plan = self._apply_changes(current_plan, changes)

        # 计算影响
        total_delay = sum(
            d.expected_end_time.timestamp() - datetime.now().timestamp()
            for d in disruptions
            if d.expected_end_time
        ) / 60

        return PlanAdjustment(
            original_plan=current_plan,
            adjusted_plan=adjusted_plan,
            changes=changes,
            estimated_delay_minutes=int(total_delay),
            additional_cost=0,  # 简化计算
            reasoning=self._generate_reasoning(disruptions, changes),
        )

    def _create_change_for_disruption(
        self,
        disruption: Disruption,
        alternatives: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """为单个中断创建变更"""
        if disruption.type == DisruptionType.WEATHER_WARNING:
            # 天气原因：寻找室内替代
            indoor_alts = [
                a for a in alternatives
                if a.get("category") in ["博物馆", "商场", "餐厅"]
            ]
            return {
                "type": "replace",
                "reason": "天气原因",
                "original": disruption.location,
                "replacement": indoor_alts[0] if indoor_alts else None,
                "suggestion": disruption.alternatives[0] if disruption.alternatives else "室内活动",
            }

        elif disruption.type == DisruptionType.TRAFFIC_DELAY:
            # 交通延误：调整时间或路线
            return {
                "type": "delay",
                "reason": "交通延误",
                "affected": disruption.location,
                "delay_minutes": 30,  # 简化
                "suggestion": "建议提前出发或选择替代路线",
            }

        elif disruption.type == DisruptionType.ATTRACTION_CLOSED:
            # 景点关闭：完全替换
            return {
                "type": "replace",
                "reason": "景点关闭",
                "original": disruption.location,
                "replacement": alternatives[0] if alternatives else None,
                "suggestion": "已为您找到替代景点",
            }

        else:
            return {
                "type": "note",
                "reason": disruption.description,
                "suggestion": "请留意最新信息",
            }

    def _apply_changes(
        self,
        original: Dict[str, Any],
        changes: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """应用变更到原计划"""
        adjusted = original.copy()

        # 简化实现：只添加变更记录
        adjusted["adjustments"] = changes
        adjusted["adjusted_at"] = datetime.now().isoformat()

        return adjusted

    def _generate_reasoning(
        self,
        disruptions: List[Disruption],
        changes: List[Dict[str, Any]],
    ) -> str:
        """生成调整说明"""
        if not disruptions:
            return "暂无重大变更，计划正常运行。"

        reasons = []
        for d in disruptions:
            if d.type == DisruptionType.WEATHER_WARNING:
                reasons.append("由于天气变化")
            elif d.type == DisruptionType.TRAFFIC_DELAY:
                reasons.append("由于交通状况")
            elif d.type == DisruptionType.ATTRACTION_CLOSED:
                reasons.append("由于景点临时关闭")

        if reasons:
            return f"{'、'.join(reasons)}，已为您调整行程计划。"

        return "已根据最新情况优化行程。"

    def generate_quick_adjustment(
        self,
        original_plan: Dict[str, Any],
        disruption_type: str,
    ) -> str:
        """
        生成快速调整建议（用于即时回复）

        Args:
            original_plan: 原计划
            disruption_type: 中断类型

        Returns:
            str: 调整建议文本
        """
        if disruption_type == "weather":
            return (
                "根据最新天气情况，建议您：\n"
                "1. 准备好雨具\n"
                "2. 将户外景点调整到上午游览\n"
                "3. 下午可以改为室内活动，如博物馆或购物中心\n"
                "4. 保持灵活，如果天气好转可以临时调整"
            )
        elif disruption_type == "traffic":
            return (
                "交通出现延误，建议您：\n"
                "1. 预留更多出行时间\n"
                "2. 考虑地铁等公共交通\n"
                "3. 适当减少每个景点的游览时间"
            )
        else:
            return "当前计划可能需要调整，建议您留意最新通知。"


# 全局实例
dynamic_replanner = DynamicReplanner()
