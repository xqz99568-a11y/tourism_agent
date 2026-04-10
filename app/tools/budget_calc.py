"""
预算计算工具
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from app.tools.base import BaseTool, ToolResult


class BudgetLevel(str, Enum):
    """预算级别"""
    ECONOMY = "economy"      # 经济型
    MEDIUM = "medium"        # 舒适型
    LUXURY = "luxury"        # 豪华型


# 预算参考数据 (每人每天，单位：元)
BUDGET_REFERENCE = {
    BudgetLevel.ECONOMY: {
        "transport": {"min": 50, "max": 100},
        "accommodation": {"min": 80, "max": 200},
        "food": {"min": 50, "max": 100},
        "tickets": {"min": 30, "max": 80},
        "shopping": {"min": 20, "max": 50},
    },
    BudgetLevel.MEDIUM: {
        "transport": {"min": 100, "max": 200},
        "accommodation": {"min": 200, "max": 500},
        "food": {"min": 100, "max": 200},
        "tickets": {"min": 80, "max": 150},
        "shopping": {"min": 50, "max": 150},
    },
    BudgetLevel.LUXURY: {
        "transport": {"min": 200, "max": 500},
        "accommodation": {"min": 500, "max": 2000},
        "food": {"min": 200, "max": 500},
        "tickets": {"min": 150, "max": 300},
        "shopping": {"min": 150, "max": 500},
    },
}


@dataclass
class BudgetItem:
    """预算项目"""
    category: str
    item: str
    estimated_cost: float
    is_essential: bool = True
    notes: Optional[str] = None


@dataclass
class BudgetEstimate:
    """预算估算"""
    total_min: float
    total_max: float
    total_recommended: float
    per_person: float
    daily: float
    breakdown: Dict[str, Dict[str, float]]
    items: List[BudgetItem]


class BudgetCalculatorTool(BaseTool):
    """
    预算计算工具
    估算旅行总预算
    """

    name = "budget_calculator"
    description = "计算旅行预算"
    parameters = {
        "type": "object",
        "properties": {
            "destination": {
                "type": "string",
                "description": "目的地",
            },
            "duration": {
                "type": "integer",
                "description": "行程天数",
            },
            "num_travelers": {
                "type": "integer",
                "description": "出行人数",
                "default": 1,
            },
            "budget_level": {
                "type": "string",
                "description": "预算级别：economy、medium、luxury",
                "enum": ["economy", "medium", "luxury"],
                "default": "medium",
            },
        },
        "required": ["destination", "duration"],
    }

    def __init__(self):
        self.reference = BUDGET_REFERENCE

    async def execute(
        self,
        destination: str,
        duration: int,
        num_travelers: int = 1,
        budget_level: str = "medium",
        **kwargs,
    ) -> ToolResult:
        """计算预算"""
        try:
            level = BudgetLevel(budget_level)
            estimate = self._calculate_estimate(
                destination, duration, num_travelers, level
            )

            return ToolResult(
                success=True,
                data={
                    "destination": destination,
                    "duration": duration,
                    "num_travelers": num_travelers,
                    "budget_level": budget_level,
                    "total_min": estimate.total_min,
                    "total_max": estimate.total_max,
                    "total_recommended": estimate.total_recommended,
                    "per_person": estimate.per_person,
                    "daily": estimate.daily,
                    "breakdown": estimate.breakdown,
                    "items": [
                        {
                            "category": item.category,
                            "item": item.item,
                            "estimated_cost": item.estimated_cost,
                            "is_essential": item.is_essential,
                            "notes": item.notes,
                        }
                        for item in estimate.items
                    ],
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _calculate_estimate(
        self,
        destination: str,
        duration: int,
        num_travelers: int,
        level: BudgetLevel,
    ) -> BudgetEstimate:
        """计算预算估算"""
        ref = self.reference[level]
        breakdown = {}
        items = []
        total_min = 0
        total_max = 0

        # 目的地系数 (大城市系数更高)
        destination_factor = self._get_destination_factor(destination)

        for category, amounts in ref.items():
            min_cost = amounts["min"] * duration * destination_factor
            max_cost = amounts["max"] * duration * destination_factor
            recommended = (min_cost + max_cost) / 2

            breakdown[category] = {
                "min": round(min_cost, 2),
                "max": round(max_cost, 2),
                "recommended": round(recommended, 2),
            }

            total_min += min_cost
            total_max += max_cost

            # 生成预算项目
            items.append(
                BudgetItem(
                    category=category,
                    item=self._get_item_name(category),
                    estimated_cost=round(recommended, 2),
                    is_essential=category != "shopping",
                    notes=self._get_item_notes(category),
                )
            )

        total_recommended = (total_min + total_max) / 2
        per_person = total_recommended / num_travelers

        return BudgetEstimate(
            total_min=round(total_min, 2),
            total_max=round(total_max, 2),
            total_recommended=round(total_recommended, 2),
            per_person=round(per_person, 2),
            daily=round(total_recommended / duration, 2),
            breakdown=breakdown,
            items=items,
        )

    def _get_destination_factor(self, destination: str) -> float:
        """获取目的地系数"""
        # 大城市系数更高
        major_cities = ["北京", "上海", "广州", "深圳", "杭州", "成都"]
        expensive_cities = ["三亚", "丽江", "大理", "西藏", "新疆"]

        if any(city in destination for city in expensive_cities):
            return 1.3
        elif any(city in destination for city in major_cities):
            return 1.2
        return 1.0

    def _get_item_name(self, category: str) -> str:
        """获取项目名称"""
        names = {
            "transport": "交通费用",
            "accommodation": "住宿费用",
            "food": "餐饮费用",
            "tickets": "门票/娱乐",
            "shopping": "购物/其他",
        }
        return names.get(category, category)

    def _get_item_notes(self, category: str) -> str:
        """获取项目备注"""
        notes = {
            "transport": "包含城内交通和往返交通",
            "accommodation": "按标准间计算",
            "food": "含早中晚三餐",
            "tickets": "景点门票和娱乐项目",
            "shopping": "可选，根据个人需求",
        }
        return notes.get(category, "")


class BudgetOptimizerTool(BaseTool):
    """
    预算优化工具
    提供节省预算的建议
    """

    name = "budget_optimizer"
    description = "优化旅行预算，提供省钱建议"
    parameters = {
        "type": "object",
        "properties": {
            "current_budget": {
                "type": "number",
                "description": "当前预算",
            },
            "target_budget": {
                "type": "number",
                "description": "目标预算",
            },
            "duration": {
                "type": "integer",
                "description": "行程天数",
            },
        },
        "required": ["current_budget", "target_budget", "duration"],
    }

    async def execute(
        self,
        current_budget: float,
        target_budget: float,
        duration: int,
        **kwargs,
    ) -> ToolResult:
        """优化预算"""
        try:
            savings_needed = current_budget - target_budget

            if savings_needed <= 0:
                return ToolResult(
                    success=True,
                    data={
                        "can_meet_target": True,
                        "message": "目标预算可以满足",
                        "suggestions": [],
                    },
                )

            daily_savings = savings_needed / duration
            suggestions = self._generate_suggestions(daily_savings, duration)

            return ToolResult(
                success=True,
                data={
                    "can_meet_target": True,
                    "savings_needed": round(savings_needed, 2),
                    "daily_savings": round(daily_savings, 2),
                    "suggestions": suggestions,
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _generate_suggestions(self, daily_savings: float, duration: int) -> List[Dict[str, Any]]:
        """生成省钱建议"""
        suggestions = []

        if daily_savings >= 100:
            suggestions.append({
                "category": "住宿",
                "potential_savings": round(daily_savings * 0.4, 2),
                "suggestion": "选择经济型住宿或青年旅社",
            })

        if daily_savings >= 80:
            suggestions.append({
                "category": "餐饮",
                "potential_savings": round(daily_savings * 0.3, 2),
                "suggestion": "尝试当地小吃和路边店，比餐厅便宜一半",
            })

        if daily_savings >= 50:
            suggestions.append({
                "category": "交通",
                "potential_savings": round(daily_savings * 0.2, 2),
                "suggestion": "使用公共交通代替打车，提前购买优惠票",
            })

        suggestions.append({
            "category": "门票",
            "potential_savings": round(daily_savings * 0.1, 2),
            "suggestion": "关注景点优惠活动，使用旅游APP购票",
        })

        return suggestions


# 注册工具
def register_budget_tools(registry):
    """注册预算工具"""
    registry.register(BudgetCalculatorTool())
    registry.register(BudgetOptimizerTool())
