"""
Enhanced Constraint Solver
增强版约束求解器，支持冲突检测和多方案生成
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
import random
import uuid

from app.core.logger import get_logger
from app.schemas import (
    ConstraintSchema, ConstraintType as SchemaConstraintType,
    ConflictResolution, PlanComparison, PlanVariant,
)

logger = get_logger(__name__)


class ConstraintConflictType(str, Enum):
    """冲突类型"""
    TIME_OVERLAP = "time_overlap"           # 时间重叠
    BUDGET_EXCEED = "budget_exceed"         # 预算超支
    MUTUALLY_EXCLUSIVE = "mutually_exclusive" # 互斥约束
    ORDER_CONFLICT = "order_conflict"       # 顺序冲突
    ACCESSIBILITY_CONFLICT = "accessibility_conflict"  # 无障碍冲突


@dataclass
class ConstraintConflict:
    """约束冲突"""
    id: str
    type: ConstraintConflictType
    description: str
    involved_constraints: List[str]
    severity: str = "high"  # high, medium, low
    suggested_resolution: Optional[str] = None


class ConstraintDetector:
    """
    约束冲突检测器
    检测硬约束之间的冲突
    """

    def __init__(self):
        self.conflicts: List[ConstraintConflict] = []

    def detect_conflicts(
        self,
        constraints: List[ConstraintSchema],
        attractions: List[Any],
        budget: float,
        time_windows: Dict[str, Tuple[str, str]],
    ) -> ConflictResolution:
        """
        检测约束冲突

        Args:
            constraints: 约束列表
            attractions: 景点列表
            budget: 总预算
            time_windows: 时间窗口 {景点ID: (开放时间, 关闭时间)}

        Returns:
            ConflictResolution: 冲突检测结果
        """
        conflicts: List[ConstraintConflict] = []

        # 1. 检测预算冲突
        budget_conflicts = self._detect_budget_conflicts(constraints, budget, attractions)
        conflicts.extend(budget_conflicts)

        # 2. 检测时间窗口冲突
        time_conflicts = self._detect_time_window_conflicts(
            constraints, time_windows, attractions
        )
        conflicts.extend(time_conflicts)

        # 3. 检测顺序冲突
        order_conflicts = self._detect_order_conflicts(constraints)
        conflicts.extend(order_conflicts)

        # 4. 检测互斥冲突
        exclusive_conflicts = self._detect_mutual_exclusivity(constraints, attractions)
        conflicts.extend(exclusive_conflicts)

        # 生成解决建议
        resolutions = self._generate_resolution_suggestions(conflicts)

        self.conflicts = conflicts

        return ConflictResolution(
            has_conflict=len(conflicts) > 0,
            conflicts=[self._conflict_to_dict(c) for c in conflicts],
            resolution_suggestions=resolutions,
            user_decision_needed=any(c.severity == "high" for c in conflicts),
        )

    def _detect_budget_conflicts(
        self,
        constraints: List[ConstraintSchema],
        budget: float,
        attractions: List[Any],
    ) -> List[ConstraintConflict]:
        """检测预算相关冲突"""
        conflicts = []

        # 收集所有必去景点的门票
        must_visit_cost = 0
        for c in constraints:
            if c.category == "must_visit":
                # 假设 value 包含景点ID或列表
                if isinstance(c.value, list):
                    for poi_id in c.value:
                        for attr in attractions:
                            if attr.id == poi_id:
                                must_visit_cost += attr.ticket_price
                                break

        if must_visit_cost > budget:
            conflicts.append(ConstraintConflict(
                id=str(uuid.uuid4()),
                type=ConstraintConflictType.BUDGET_EXCEED,
                description=f"必去景点门票({must_visit_cost}元)超过预算({budget}元)",
                involved_constraints=["budget", "must_visit"],
                severity="high",
                suggested_resolution="降低预算或减少必去景点数量",
            ))

        return conflicts

    def _detect_time_window_conflicts(
        self,
        constraints: List[ConstraintSchema],
        time_windows: Dict[str, Tuple[str, str]],
        attractions: List[Any],
    ) -> List[ConstraintConflict]:
        """检测时间窗口冲突"""
        conflicts = []

        # 检查景点之间的访问时间是否冲突
        time_constraints = [
            c for c in constraints if c.category == "time_window"
        ]

        for i, c1 in enumerate(time_constraints):
            for c2 in time_constraints[i + 1:]:
                poi1 = c1.value if isinstance(c1.value, str) else None
                poi2 = c2.value if isinstance(c2.value, str) else None

                if poi1 and poi2:
                    w1 = time_windows.get(poi1)
                    w2 = time_windows.get(poi2)

                    if w1 and w2:
                        # 检查是否有重叠
                        if self._time_windows_overlap(w1, w2):
                            # 检查游览时长
                            attr1 = next((a for a in attractions if a.id == poi1), None)
                            attr2 = next((a for a in attractions if a.id == poi2), None)

                            if attr1 and attr2:
                                total_duration = attr1.duration_minutes + attr2.duration_minutes
                                available_time = self._calculate_available_time(w1, w2)

                                if total_duration > available_time:
                                    conflicts.append(ConstraintConflict(
                                        id=str(uuid.uuid4()),
                                        type=ConstraintConflictType.TIME_OVERLAP,
                                        description=(
                                            f"{attr1.name}和{attr2.name}在时间窗口内无法同时游览"
                                        ),
                                        involved_constraints=[poi1, poi2],
                                        severity="medium",
                                        suggested_resolution="调整游览顺序或跳过其中一个景点",
                                    ))

        return conflicts

    def _detect_order_conflicts(
        self,
        constraints: List[ConstraintSchema],
    ) -> List[ConstraintConflict]:
        """检测顺序冲突"""
        conflicts = []

        order_constraints = [c for c in constraints if c.category == "order"]

        for i, c1 in enumerate(order_constraints):
            for c2 in order_constraints[i + 1:]:
                # 检查是否存在环形依赖
                if self._creates_circular_dependency(c1, c2):
                    conflicts.append(ConstraintConflict(
                        id=str(uuid.uuid4()),
                        type=ConstraintConflictType.ORDER_CONFLICT,
                        description="存在循环访问顺序依赖，无法满足",
                        involved_constraints=[c1.description, c2.description],
                        severity="high",
                        suggested_resolution="移除其中一个顺序约束",
                    ))

        return conflicts

    def _detect_mutual_exclusivity(
        self,
        constraints: List[ConstraintSchema],
        attractions: List[Any],
    ) -> List[ConstraintConflict]:
        """检测互斥冲突"""
        conflicts = []

        # 检查适老化需求与某些景点的冲突
        accessibility_required = any(
            c.category == "accessibility" for c in constraints
        )

        if accessibility_required:
            for attr in attractions:
                if attr.accessibility_score < 0.5:
                    conflicts.append(ConstraintConflict(
                        id=str(uuid.uuid4()),
                        type=ConstraintConflictType.ACCESSIBILITY_CONFLICT,
                        description=f"景点{attr.name}适老化评分较低，与无障碍需求冲突",
                        involved_constraints=[attr.id, "accessibility"],
                        severity="low",
                        suggested_resolution="可将该景点替换为适老化更好的景点",
                    ))

        return conflicts

    def _time_windows_overlap(
        self,
        w1: Tuple[str, str],
        w2: Tuple[str, str],
    ) -> bool:
        """检查两个时间窗口是否重叠"""
        try:
            o1_start = datetime.strptime(w1[0], "%H:%M")
            o1_end = datetime.strptime(w1[1], "%H:%M")
            o2_start = datetime.strptime(w2[0], "%H:%M")
            o2_end = datetime.strptime(w2[1], "%H:%M")

            return o1_start < o2_end and o2_start < o1_end
        except ValueError:
            return False

    def _calculate_available_time(
        self,
        w1: Tuple[str, str],
        w2: Tuple[str, str],
    ) -> int:
        """计算两个景点之间的可用时间"""
        try:
            o1_start = datetime.strptime(w1[0], "%H:%M")
            o1_end = datetime.strptime(w1[1], "%H:%M")
            o2_start = datetime.strptime(w2[0], "%H:%M")
            o2_end = datetime.strptime(w2[1], "%H:%M")

            # 假设按顺序访问，计算第一个景点后的剩余时间
            return int((o1_end - o1_start).total_seconds() / 60)
        except ValueError:
            return 480  # 默认8小时

    def _creates_circular_dependency(
        self,
        c1: ConstraintSchema,
        c2: ConstraintSchema,
    ) -> bool:
        """检查是否创建循环依赖"""
        # 简化实现：检查是否有 A before B 和 B before A
        if "before" in c1.description.lower() and "before" in c2.description.lower():
            # 检查是否互为前后
            val1_str = str(c1.value).lower()
            val2_str = str(c2.value).lower()

            if (val1_str in val2_str) or (val2_str in val1_str):
                parts1 = c1.description.split()
                parts2 = c2.description.split()

                # 检查是否有冲突
                return len(parts1) >= 4 and len(parts2) >= 4

        return False

    def _generate_resolution_suggestions(
        self,
        conflicts: List[ConstraintConflict],
    ) -> List[str]:
        """生成冲突解决建议"""
        suggestions = []

        for conflict in conflicts:
            if conflict.suggested_resolution:
                suggestions.append(conflict.suggested_resolution)

        # 添加通用建议
        if conflicts:
            suggestions.extend([
                "您可以调整必去景点的数量",
                "可以适当放宽某些时间限制",
                "预算允许的情况下可以考虑增加预算",
            ])

        return list(set(suggestions))  # 去重

    def _conflict_to_dict(self, conflict: ConstraintConflict) -> Dict[str, Any]:
        """将冲突转换为字典"""
        return {
            "id": conflict.id,
            "type": conflict.type.value,
            "description": conflict.description,
            "involved_constraints": conflict.involved_constraints,
            "severity": conflict.severity,
            "suggested_resolution": conflict.suggested_resolution,
        }


class MultiVariantPlanner:
    """
    多方案生成器
    生成多个备选规划方案
    """

    VARIANT_THEMES = {
        "classic": {
            "name": "经典打卡路线",
            "description": "涵盖最知名景点，适合第一次到访",
            "highlight": "必打卡经典，不留遗憾",
        },
        "culture": {
            "name": "深度文化之旅",
            "description": "聚焦历史文化体验，深入了解当地",
            "highlight": "文化底蕴，深度体验",
        },
        "explore": {
            "name": "小众探索路线",
            "description": "发现隐藏宝藏，体验不一样的人文风情",
            "highlight": "独特视角，发现小众之美",
        },
        "foodie": {
            "name": "美食探索路线",
            "description": "以美食为主题，边吃边玩",
            "highlight": "舌尖之旅，美食相伴",
        },
        "relaxed": {
            "name": "悠闲度假路线",
            "description": "节奏舒缓，适合休闲放松",
            "highlight": "慢节奏享受，放松身心",
        },
    }

    def __init__(self):
        self.conflict_detector = ConstraintDetector()

    def generate_variants(
        self,
        attractions: List[Any],
        preferences: Dict[str, Any],
        constraints: List[ConstraintSchema],
        num_variants: int = 3,
    ) -> PlanComparison:
        """
        生成多个规划方案

        Args:
            attractions: 景点列表
            preferences: 用户偏好
            constraints: 约束列表
            num_variants: 生成方案数量

        Returns:
            PlanComparison: 方案对比结果
        """
        # 选择主题
        themes = self._select_themes(preferences, num_variants)

        variants: List[PlanVariant] = []
        comparison_metrics: Dict[str, Dict[str, float]] = {}

        for theme_key in themes:
            theme = self.VARIANT_THEMES.get(theme_key, self.VARIANT_THEMES["classic"])

            # 根据主题筛选和排序景点
            ranked_attractions = self._rank_attractions_by_theme(
                attractions, theme_key, preferences
            )

            # 生成方案
            plan, metrics = self._generate_plan(
                ranked_attractions, theme, preferences
            )

            variant = PlanVariant(
                id=str(uuid.uuid4()),
                name=theme["name"],
                plan=plan,
                highlight=theme["highlight"],
                metrics=metrics,
            )

            variants.append(variant)
            comparison_metrics[theme["name"]] = metrics

        # 生成各方案的优缺点
        pros_cons = self._generate_pros_cons(variants, comparison_metrics)

        # 推荐方案
        recommendation = self._generate_recommendation(variants, preferences)

        return PlanComparison(
            variants=variants,
            comparison_metrics=comparison_metrics,
            pros_cons=pros_cons,
            recommendation=recommendation,
        )

    def _select_themes(
        self,
        preferences: Dict[str, Any],
        num_variants: int,
    ) -> List[str]:
        """根据偏好选择主题"""
        travel_styles = preferences.get("travel_styles", [])
        all_themes = list(self.VARIANT_THEMES.keys())

        # 基于旅行风格选择主题
        selected = []

        if "cultural" in travel_styles:
            selected.append("culture")
        if "culinary" in travel_styles:
            selected.append("foodie")
        if "relaxed" in travel_styles:
            selected.append("relaxed")

        # 如果选的不够，用经典和探索补足
        if len(selected) < num_variants:
            if "classic" not in selected:
                selected.append("classic")
        if len(selected) < num_variants:
            if "explore" not in selected:
                selected.append("explore")

        return selected[:num_variants]

    def _rank_attractions_by_theme(
        self,
        attractions: List[Any],
        theme: str,
        preferences: Dict[str, Any],
    ) -> List[Any]:
        """根据主题对景点进行排序"""
        scored = []

        for attr in attractions:
            score = self._calculate_theme_score(attr, theme, preferences)
            scored.append((score, random.random(), attr))

        # 按分数降序排序
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [attr for _, _, attr in scored]

    def _calculate_theme_score(
        self,
        attraction: Any,
        theme: str,
        preferences: Dict[str, Any],
    ) -> float:
        """计算景点在特定主题下的分数"""
        base_score = attraction.rating

        theme_weights = {
            "classic": {"rating": 1.5, "popularity": 1.0},
            "culture": {"tags": 1.5, "history": 1.0},
            "explore": {"unique": 1.5, "rating": 0.5},
            "foodie": {"food_related": 2.0},
            "relaxed": {"accessibility": 1.5, "duration": -0.5},
        }

        weights = theme_weights.get(theme, theme_weights["classic"])

        score = base_score

        # 根据标签调整
        tags = attraction.tags if hasattr(attraction, "tags") else []
        if "博物馆" in tags or "寺庙" in tags or "古迹" in tags:
            score *= weights.get("tags", 1.0)
        if "hidden" in tags or "小众" in tags:
            score *= weights.get("unique", 1.0)

        return score

    def _generate_plan(
        self,
        attractions: List[Any],
        theme: Dict[str, str],
        preferences: Dict[str, Any],
    ) -> Tuple[Any, Dict[str, float]]:
        """生成单个规划方案"""
        # 简化实现：创建日计划
        plan_data = {
            "destination": preferences.get("destination", "未知"),
            "total_cost": sum(a.ticket_price for a in attractions[:5]),
            "estimated_cost": sum(a.ticket_price for a in attractions[:5]),
        }

        # 计算指标
        metrics = {
            "total_time": sum(a.duration_minutes for a in attractions[:5]),
            "total_cost": sum(a.ticket_price for a in attractions[:5]),
            "avg_rating": sum(a.rating for a in attractions[:5]) / min(5, len(attractions)),
            "diversity": len(set(a.category for a in attractions[:5])),
        }

        return plan_data, metrics

    def _generate_pros_cons(
        self,
        variants: List[PlanVariant],
        metrics: Dict[str, Dict[str, float]],
    ) -> Dict[str, List[str]]:
        """生成各方案的优缺点"""
        pros_cons: Dict[str, List[str]] = {}

        for variant in variants:
            theme_name = variant.name
            m = metrics.get(theme_name, {})
            pros = []
            cons = []

            if m.get("avg_rating", 0) >= 4.5:
                pros.append("景点评分高，体验有保障")
            if m.get("total_cost", 0) < 500:
                pros.append("花费较低，性价比高")
            if m.get("total_time", 0) < 600:
                pros.append("行程紧凑，时间利用率高")
            if m.get("diversity", 0) >= 4:
                pros.append("景点类型多样，选择丰富")

            if m.get("diversity", 0) < 3:
                cons.append("景点类型较单一")
            if m.get("total_time", 0) > 800:
                cons.append("行程较紧，可能较累")

            pros_cons[theme_name] = pros if pros else ["综合表现良好"]

        return pros_cons

    def _generate_recommendation(
        self,
        variants: List[PlanVariant],
        preferences: Dict[str, Any],
    ) -> str:
        """生成推荐建议"""
        if not variants:
            return ""

        # 基于偏好选择推荐
        travel_styles = preferences.get("travel_styles", [])

        for variant in variants:
            if "cultural" in travel_styles and "文化" in variant.name:
                return f"根据您对文化体验的偏好，我推荐「{variant.name}」。{variant.highlight}"
            if "relaxed" in travel_styles and "悠闲" in variant.name:
                return f"根据您轻松旅行的偏好，我推荐「{variant.name}」。{variant.highlight}"

        # 默认推荐第一个
        return f"综合来看，我推荐「{variants[0].name}」。{variants[0].highlight}"


# 全局实例
constraint_detector = ConstraintDetector()
multi_variant_planner = MultiVariantPlanner()
