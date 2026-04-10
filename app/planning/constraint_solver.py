"""
约束求解器
基于约束满足问题 (CSP) 的行程规划算法
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import random

from app.core.logger import get_logger

logger = get_logger(__name__)


class ConstraintType(str, Enum):
    """约束类型"""
    HARD = "hard"      # 硬约束，必须满足
    SOFT = "soft"      # 软约束，尽量满足


@dataclass
class Constraint:
    """约束基类"""
    name: str
    description: str
    constraint_type: ConstraintType = ConstraintType.HARD

    def is_satisfied(self, solution: Dict[str, Any]) -> bool:
        """检查约束是否满足"""
        raise NotImplementedError


@dataclass
class TimeWindowConstraint(Constraint):
    """时间窗口约束 - 景点必须在开放时间内"""
    attraction_id: str
    open_time: str      # HH:MM
    close_time: str      # HH:MM
    preferred_time: Optional[str] = None  # HH:MM 最佳游览时间

    def is_satisfied(self, solution: Dict[str, Any]) -> bool:
        visit_time = solution.get("visit_time", "")
        if not visit_time:
            return False
        return self.open_time <= visit_time < self.close_time


@dataclass
class BudgetConstraint(Constraint):
    """预算约束"""
    max_budget: float
    constraint_type: ConstraintType = ConstraintType.HARD

    def is_satisfied(self, solution: Dict[str, Any]) -> bool:
        total_cost = solution.get("total_cost", 0)
        return total_cost <= self.max_budget


@dataclass
class DurationConstraint(Constraint):
    """时长约束 - 每个景点游览时间"""
    attraction_id: str
    min_duration_minutes: int = 30
    max_duration_minutes: int = 480  # 8小时

    def is_satisfied(self, solution: Dict[str, Any]) -> bool:
        duration = solution.get("duration", 0)
        return self.min_duration_minutes <= duration <= self.max_duration_minutes


@dataclass
class DistanceConstraint(Constraint):
    """距离约束 - 相邻景点之间的距离"""
    from_attraction: str
    to_attraction: str
    max_distance_km: float
    max_travel_time_minutes: int = 60

    def is_satisfied(self, solution: Dict[str, Any]) -> bool:
        travel_time = solution.get("travel_time", 0)
        return travel_time <= self.max_travel_time_minutes


@dataclass
class VisitingOrderConstraint(Constraint):
    """访问顺序约束 - 某些景点必须按顺序访问"""
    must_visit_before: str   # 必须先访问
    must_visit_after: str     # 必须后访问

    def is_satisfied(self, solution: Dict[str, Any]) -> bool:
        order = solution.get("visiting_order", [])
        try:
            before_idx = order.index(self.must_visit_before)
            after_idx = order.index(self.must_visit_after)
            return before_idx < after_idx
        except ValueError:
            return True  # 如果景点不在顺序中，约束自动满足


@dataclass
class PreferenceConstraint(Constraint):
    """偏好约束 - 用户偏好"""
    category: str           # 如 "景点类型"
    preferred_values: List[str]  # 如 ["博物馆", "公园"]
    weight: float = 1.0       # 权重
    constraint_type: ConstraintType = ConstraintType.SOFT

    def is_satisfied(self, solution: Dict[str, Any]) -> bool:
        """软约束总是满足，返回满意度分数"""
        category_values = solution.get(self.category, [])
        match_count = sum(1 for v in self.preferred_values if v in category_values)
        return match_count > 0

    def satisfaction_score(self, solution: Dict[str, Any]) -> float:
        """计算满意度分数 0-1"""
        category_values = solution.get(self.category, [])
        if not category_values:
            return 0.0
        match_count = sum(1 for v in self.preferred_values if v in category_values)
        return min(1.0, match_count / len(self.preferred_values)) * self.weight


@dataclass
class Attraction:
    """景点"""
    id: str
    name: str
    category: str
    latitude: float
    longitude: float
    rating: float = 4.0
    duration_minutes: int = 120
    ticket_price: float = 0
    open_time: str = "09:00"
    close_time: str = "18:00"
    tags: List[str] = field(default_factory=list)
    accessibility_score: float = 1.0

    def __hash__(self):
        return hash(self.id)


@dataclass
class PlannedVisit:
    """规划的访问"""
    attraction: Attraction
    arrival_time: str       # HH:MM
    departure_time: str      # HH:MM
    travel_from_previous: Optional[int] = None  # 从上一个景点过来的时间(分钟)


@dataclass
class DayPlan:
    """每日计划"""
    date: datetime
    visits: List[PlannedVisit] = field(default_factory=list)
    total_cost: float = 0
    total_duration_minutes: int = 0

    def add_visit(self, visit: PlannedVisit) -> None:
        self.visits.append(visit)
        self.total_cost += visit.attraction.ticket_price
        # 计算游览时长
        start = datetime.strptime(visit.arrival_time, "%H:%M")
        end = datetime.strptime(visit.departure_time, "%H:%M")
        self.total_duration_minutes += int((end - start).total_seconds() / 60)


class ConstraintSolver:
    """
    约束求解器
    使用回溯算法解决约束满足问题
    """

    def __init__(self):
        self.constraints: List[Constraint] = []
        self.hard_constraints: List[Constraint] = []
        self.soft_constraints: List[Constraint] = []

    def add_constraint(self, constraint: Constraint) -> None:
        """添加约束"""
        self.constraints.append(constraint)
        if constraint.constraint_type == ConstraintType.HARD:
            self.hard_constraints.append(constraint)
        else:
            self.soft_constraints.append(constraint)

    def add_constraints(self, constraints: List[Constraint]) -> None:
        """批量添加约束"""
        for c in constraints:
            self.add_constraint(c)

    def clear_constraints(self) -> None:
        """清除所有约束"""
        self.constraints.clear()
        self.hard_constraints.clear()
        self.soft_constraints.clear()

    def check_hard_constraints(
        self,
        partial_solution: Dict[str, Any],
    ) -> Tuple[bool, List[str]]:
        """
        检查硬约束
        Returns: (是否满足, 未满足的约束名称列表)
        """
        failed = []
        for constraint in self.hard_constraints:
            if not constraint.is_satisfied(partial_solution):
                failed.append(constraint.name)
        return len(failed) == 0, failed

    def calculate_satisfaction_score(
        self,
        solution: Dict[str, Any],
    ) -> float:
        """计算软约束满意度分数"""
        if not self.soft_constraints:
            return 1.0

        total_weight = sum(c.weight for c in self.soft_constraints)
        if total_weight == 0:
            return 1.0

        total_score = sum(
            c.satisfaction_score(solution) for c in self.soft_constraints
        )

        return total_score / total_weight

    def solve(
        self,
        attractions: List[Attraction],
        start_time: str = "09:00",
        end_time: str = "21:00",
        max_visits_per_day: int = 5,
        seed: Optional[int] = None,
    ) -> Optional[DayPlan]:
        """
        求解 - 排列景点，找到满足约束的最优解

        Args:
            attractions: 景点列表
            start_time: 每日开始时间
            end_time: 每日结束时间
            max_visits_per_day: 每天最多访问数
            seed: 随机种子

        Returns:
            满足约束的日计划，如果无解返回 None
        """
        if seed is not None:
            random.seed(seed)

        # 按评分排序
        sorted_attractions = sorted(
            attractions,
            key=lambda a: (a.rating, a.accessibility_score),
            reverse=True,
        )

        # 尝试不同的排列
        best_plan = None
        best_score = -1

        # 使用贪心 + 局部搜索
        for _ in range(min(100, len(attractions) * 10)):
            plan = self._greedy_build_plan(
                sorted_attractions,
                start_time,
                end_time,
                max_visits_per_day,
            )

            if plan is None:
                continue

            # 评估计划
            score = self._evaluate_plan(plan)
            if score > best_score:
                best_score = score
                best_plan = plan

            # 随机打乱
            random.shuffle(sorted_attractions)

        return best_plan

    def _greedy_build_plan(
        self,
        attractions: List[Attraction],
        start_time: str,
        end_time: str,
        max_visits: int,
    ) -> Optional[DayPlan]:
        """贪心构建计划"""
        plan = DayPlan(date=datetime.now())
        current_time = datetime.strptime(start_time, "%H:%M")
        end_dt = datetime.strptime(end_time, "%H:%M")

        remaining_attractions = attractions.copy()

        while remaining_attractions and len(plan.visits) < max_visits:
            best_next = None
            best_score = -1

            for attr in remaining_attractions:
                # 检查时间窗口
                attr_open = datetime.strptime(attr.open_time, "%H:%M")
                attr_close = datetime.strptime(attr.close_time, "%H:%M")

                if current_time < attr_open:
                    arrival = attr_open
                elif current_time >= attr_close:
                    continue  # 已关门
                else:
                    arrival = current_time

                departure = arrival + timedelta(minutes=attr.duration_minutes)

                if departure > end_dt:
                    continue  # 超出当天时间

                # 计算分数 (评分高、距离近、门票便宜优先)
                score = (
                    attr.rating * 10 +
                    attr.accessibility_score * 5 -
                    attr.ticket_price / 100
                )

                if score > best_score:
                    best_score = score
                    best_next = attr

            if best_next is None:
                break

            # 添加到计划
            arrival_str = current_time.strftime("%H:%M")
            departure = current_time + timedelta(minutes=best_next.duration_minutes)
            departure_str = departure.strftime("%H:%M")

            visit = PlannedVisit(
                attraction=best_next,
                arrival_time=arrival_str,
                departure_time=departure_str,
            )

            plan.add_visit(visit)
            current_time = departure
            remaining_attractions.remove(best_next)

        if not plan.visits:
            return None

        return plan

    def _evaluate_plan(self, plan: DayPlan) -> float:
        """评估计划"""
        if not plan.visits:
            return 0

        # 构建解决方案
        solution = {
            "visits": plan.visits,
            "total_cost": plan.total_cost,
            "total_duration": plan.total_duration_minutes,
            "categories": [v.attraction.category for v in plan.visits],
        }

        # 检查硬约束
        hard_ok, _ = self.check_hard_constraints(solution)
        if not hard_ok:
            return 0

        # 计算软约束满意度
        soft_score = self.calculate_satisfaction_score(solution)

        # 其他指标
        total_rating = sum(v.attraction.rating for v in plan.visits) / len(plan.visits)
        total_cost_penalty = plan.total_cost / 1000  # 成本惩罚

        return soft_score * 0.5 + total_rating * 0.4 - total_cost_penalty * 0.1


# 使用示例
def create_travel_constraint_solver(
    attractions: List[Attraction],
    preferences: Dict[str, Any],
    budget: float,
) -> ConstraintSolver:
    """创建旅行约束求解器"""
    solver = ConstraintSolver()

    # 添加偏好约束
    if travel_styles := preferences.get("travel_styles", []):
        solver.add_constraint(
            PreferenceConstraint(
                name="travel_style",
                description=f"偏好旅行风格: {travel_styles}",
                category="categories",
                preferred_values=travel_styles,
                weight=2.0,
            )
        )

    # 添加预算约束
    solver.add_constraint(
        BudgetConstraint(
            name="daily_budget",
            description=f"日预算上限: {budget}",
            max_budget=budget,
        )
    )

    # 添加时长约束
    for attr in attractions:
        solver.add_constraint(
            DurationConstraint(
                name=f"duration_{attr.id}",
                description=f"景点 {attr.name} 的时长",
                attraction_id=attr.id,
                min_duration_minutes=30,
                max_duration_minutes=480,
            )
        )

    # 添加适老化约束 (如果有老年游客)
    if "senior" in preferences.get("tourist_type", ""):
        for attr in attractions:
            if attr.accessibility_score < 0.7:
                solver.add_constraint(
                    DistanceConstraint(
                        name=f"accessibility_{attr.id}",
                        description=f"景点 {attr.name} 适老化要求",
                        from_attraction="any",
                        to_attraction=attr.id,
                        max_distance_km=0.5,
                        max_travel_time_minutes=15,
                    )
                )

    return solver
