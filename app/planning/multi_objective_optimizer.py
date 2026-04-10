"""
多目标优化器
使用进化算法解决多目标优化问题
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.logger import get_logger
from app.planning.constraint_solver import Attraction, DayPlan, PlannedVisit

logger = get_logger(__name__)


@dataclass
class Objective:
    """优化目标"""
    name: str
    description: str
    direction: str = "minimize"  # minimize 或 maximize
    weight: float = 1.0

    def evaluate(self, solution: Any) -> float:
        """评估目标值"""
        raise NotImplementedError


@dataclass
class TimeObjective(Objective):
    """时间目标 - 最小化总行程时间"""
    def evaluate(self, solution: DayPlan) -> float:
        if not solution.visits:
            return 0
        return solution.total_duration_minutes


@dataclass
class CostObjective(Objective):
    """成本目标 - 最小化总花费"""
    def evaluate(self, solution: DayPlan) -> float:
        return solution.total_cost


@dataclass
class ExperienceObjective(Objective):
    """体验目标 - 最大化总评分"""
    direction = "maximize"

    def evaluate(self, solution: DayPlan) -> float:
        if not solution.visits:
            return 0
        total_rating = sum(v.attraction.rating for v in solution.visits)
        return total_rating / len(solution.visits)


@dataclass
class DiversityObjective(Objective):
    """多样性目标 - 最大化景点类型多样性"""
    direction = "maximize"

    def evaluate(self, solution: DayPlan) -> float:
        if not solution.visits:
            return 0
        categories = set(v.attraction.category for v in solution.visits)
        return len(categories)


@dataclass
class AccessibilityObjective(Objective):
    """适老化目标 - 最大化适老化评分"""
    direction = "maximize"

    def evaluate(self, solution: DayPlan) -> float:
        if not solution.visits:
            return 0
        total_score = sum(v.attraction.accessibility_score for v in solution.visits)
        return total_score / len(solution.visits)


@dataclass
class Solution:
    """解"""
    visits: List[PlannedVisit]
    day_plan: Optional[DayPlan] = None
    objectives: Dict[str, float] = field(default_factory=dict)
    dominated: bool = False
    dominates_count: int = 0
    crowding_distance: float = 0

    def __lt__(self, other: "Solution") -> bool:
        return self.crowding_distance > other.crowding_distance


class ParetoFront:
    """
    Pareto 前沿
    存储非支配解集
    """

    def __init__(self):
        self.solutions: List[Solution] = []

    def add(self, solution: Solution) -> None:
        """添加解"""
        # 检查是否被现有解支配
        for existing in self.solutions[:]:
            if self._dominates(existing, solution):
                return  # 新解被支配，不添加

        # 移除被新解支配的解
        to_remove = []
        for existing in self.solutions:
            if self._dominates(solution, existing):
                to_remove.append(existing)

        for s in to_remove:
            self.solutions.remove(s)

        self.solutions.append(solution)

    def _dominates(self, a: Solution, b: Solution) -> bool:
        """检查解 a 是否支配解 b"""
        better_in_any = False

        for obj_name in a.objectives:
            val_a = a.objectives.get(obj_name, 0)
            val_b = b.objectives.get(obj_name, 0)

            # 假设所有目标都是最小化
            if val_a > val_b:
                return False  # a 在某个目标上比 b 差
            if val_a < val_b:
                better_in_any = True  # a 在某个目标上比 b 好

        return better_in_any

    def get_best(self, preference: Optional[Dict[str, float]] = None) -> Optional[Solution]:
        """
        获取最优解
        如果提供偏好，使用加权求和；否则返回随机非支配解
        """
        if not self.solutions:
            return None

        if preference is None:
            return random.choice(self.solutions)

        # 加权求和
        best_solution = None
        best_score = float("-inf")

        for solution in self.solutions:
            score = sum(
                preference.get(obj_name, 1.0) * value
                for obj_name, value in solution.objectives.items()
            )
            if score > best_score:
                best_score = score
                best_solution = solution

        return best_solution

    def __len__(self) -> int:
        return len(self.solutions)

    def __iter__(self):
        return iter(self.solutions)


class MultiObjectiveOptimizer:
    """
    多目标优化器
    使用 NSGA-II 风格的进化算法
    """

    def __init__(
        self,
        objectives: List[Objective],
        population_size: int = 50,
        generations: int = 100,
        mutation_rate: float = 0.1,
        crossover_rate: float = 0.8,
    ):
        self.objectives = objectives
        self.population_size = population_size
        self.generations = generations
        self.mutation_rate = mutation_rate
        self.crossover_rate = crossover_rate

        logger.info(f"Initialized optimizer with {len(objectives)} objectives")

    def optimize(
        self,
        attractions: List[Attraction],
        start_time: str = "09:00",
        end_time: str = "21:00",
        max_visits_per_day: int = 5,
        seed: Optional[int] = None,
    ) -> ParetoFront:
        """
        优化

        Args:
            attractions: 景点列表
            start_time: 每日开始时间
            end_time: 每日结束时间
            max_visits_per_day: 每天最多访问数
            seed: 随机种子

        Returns:
            Pareto 前沿
        """
        if seed is not None:
            random.seed(seed)

        # 初始化种群
        population = self._initialize_population(attractions, start_time, end_time, max_visits_per_day)

        pareto_front = ParetoFront()

        # 进化
        for generation in range(self.generations):
            # 评估
            for solution in population:
                self._evaluate_solution(solution)

            # 快速非支配排序
            fronts = self._fast_non_dominated_sort(population)

            # 计算拥挤距离
            for front in fronts:
                self._calculate_crowding_distance(front)

            # 更新 Pareto 前沿
            for solution in fronts[0]:
                pareto_front.add(solution)

            # 选择、交叉、变异
            parents = self._select_parents(population)
            offspring = self._crossover(parents)
            offspring = self._mutate(offspring, attractions)

            # 合并并选择下一代
            combined = population + offspring
            population = self._select_next_generation(combined)

            if generation % 10 == 0:
                logger.info(f"Generation {generation}: Pareto front size = {len(pareto_front)}")

        return pareto_front

    def _initialize_population(
        self,
        attractions: List[Attraction],
        start_time: str,
        end_time: str,
        max_visits: int,
    ) -> List[Solution]:
        """初始化种群"""
        population = []

        for _ in range(self.population_size):
            # 随机打乱顺序
            shuffled = random.sample(attractions, min(max_visits, len(attractions)))

            # 构建计划
            plan = self._build_plan(shuffled, start_time, end_time)

            if plan and plan.visits:
                solution = Solution(visits=plan.visits, day_plan=plan)
                population.append(solution)

        return population

    def _build_plan(
        self,
        attractions: List[Attraction],
        start_time: str,
        end_time: str,
    ) -> Optional[DayPlan]:
        """构建日计划"""
        plan = DayPlan(date=datetime.now())
        current_time = datetime.strptime(start_time, "%H:%M")
        end_dt = datetime.strptime(end_time, "%H:%M")

        for attr in attractions:
            # 检查时间
            attr_open = datetime.strptime(attr.open_time, "%H:%M")
            attr_close = datetime.strptime(attr.close_time, "%H:%M")

            if current_time < attr_open:
                arrival = attr_open
            elif current_time >= attr_close:
                continue
            else:
                arrival = current_time

            departure = arrival + timedelta(minutes=attr.duration_minutes)

            if departure > end_dt:
                break

            visit = PlannedVisit(
                attraction=attr,
                arrival_time=arrival.strftime("%H:%M"),
                departure_time=departure.strftime("%H:%M"),
            )

            plan.add_visit(visit)
            current_time = departure

        return plan if plan.visits else None

    def _evaluate_solution(self, solution: Solution) -> None:
        """评估解"""
        if solution.day_plan is None:
            return

        for objective in self.objectives:
            value = objective.evaluate(solution.day_plan)
            solution.objectives[objective.name] = value

    def _fast_non_dominated_sort(
        self,
        population: List[Solution],
    ) -> List[List[Solution]]:
        """快速非支配排序"""
        fronts = [[]]

        for p in population:
            p.dominated = False
            p.dominates_count = 0

            for q in population:
                if self._dominates(p, q):
                    p.dominates_count += 1
                elif self._dominates(q, p):
                    p.dominated = True

            if not p.dominated:
                fronts[0].append(p)

        i = 0
        while fronts[i]:
            next_front = []
            for p in fronts[i]:
                for q in population:
                    if q.dominated and p not in next_front:
                        q.dominates_count -= 1
                        if q.dominates_count == 0:
                            q.dominated = False
                            next_front.append(q)
            i += 1
            fronts.append(next_front)

        return [f for f in fronts if f]

    def _dominates(self, a: Solution, b: Solution) -> bool:
        """检查 a 是否支配 b"""
        better_in_any = False

        for obj in self.objectives:
            val_a = a.objectives.get(obj.name, 0)
            val_b = b.objectives.get(obj.name, 0)

            # 根据方向判断
            if obj.direction == "minimize":
                if val_a > val_b:
                    return False
                if val_a < val_b:
                    better_in_any = True
            else:  # maximize
                if val_a < val_b:
                    return False
                if val_a > val_b:
                    better_in_any = True

        return better_in_any

    def _calculate_crowding_distance(self, front: List[Solution]) -> None:
        """计算拥挤距离"""
        if len(front) <= 2:
            for s in front:
                s.crowding_distance = float("inf")
            return

        for s in front:
            s.crowding_distance = 0

        for obj in self.objectives:
            # 按目标值排序
            sorted_front = sorted(front, key=lambda s: s.objectives.get(obj.name, 0))

            # 边界解距离设为无穷大
            sorted_front[0].crowding_distance = float("inf")
            sorted_front[-1].crowding_distance = float("inf")

            # 计算距离
            obj_range = (
                sorted_front[-1].objectives.get(obj.name, 0) -
                sorted_front[0].objectives.get(obj.name, 0)
            )

            if obj_range == 0:
                continue

            for i in range(1, len(sorted_front) - 1):
                distance = (
                    sorted_front[i + 1].objectives.get(obj.name, 0) -
                    sorted_front[i - 1].objectives.get(obj.name, 0)
                ) / obj_range

                sorted_front[i].crowding_distance += distance * obj.weight

    def _select_parents(self, population: List[Solution]) -> List[Solution]:
        """选择父代"""
        # 锦标赛选择
        parents = []
        for _ in range(len(population)):
            tournament = random.sample(population, k=3)
            winner = max(tournament, key=lambda s: s.crowding_distance)
            parents.append(winner)
        return parents

    def _crossover(self, parents: List[Solution]) -> List[Solution]:
        """交叉"""
        offspring = []

        for i in range(0, len(parents) - 1, 2):
            if random.random() < self.crossover_rate:
                child1, child2 = self._pmx_crossover(parents[i], parents[i + 1])
                offspring.extend([child1, child2])

        return offspring

    def _pmx_crossover(
        self,
        parent1: Solution,
        parent2: Solution,
    ) -> Tuple[Solution, Solution]:
        """部分映射交叉 (PMX)"""
        size = min(len(parent1.visits), len(parent2.visits))
        if size < 2:
            return parent1, parent2

        # 选择交叉点
        point1, point2 = sorted(random.sample(range(size), k=2))

        # 创建子代
        child1_visits = [None] * size
        child2_visits = [None] * size

        # 复制中间段
        child1_visits[point1:point2] = parent1.visits[point1:point2]
        child2_visits[point1:point2] = parent2.visits[point1:point2]

        # 填充剩余位置
        for i in list(range(point1)) + list(range(point2, size)):
            # 简单复制未使用的
            for visit in parent2.visits:
                if visit not in child1_visits:
                    child1_visits[i] = visit
                    break
            for visit in parent1.visits:
                if visit not in child2_visits:
                    child2_visits[i] = visit
                    break

        # 过滤 None
        child1_visits = [v for v in child1_visits if v is not None]
        child2_visits = [v for v in child2_visits if v is not None]

        return Solution(visits=child1_visits), Solution(visits=child2_visits)

    def _mutate(
        self,
        offspring: List[Solution],
        attractions: List[Attraction],
    ) -> List[Solution]:
        """变异"""
        for solution in offspring:
            if random.random() < self.mutation_rate:
                if len(solution.visits) > 1:
                    # 交换两个位置
                    i, j = random.sample(range(len(solution.visits)), k=2)
                    solution.visits[i], solution.visits[j] = (
                        solution.visits[j],
                        solution.visits[i],
                    )

                # 可能添加或移除景点
                if random.random() < 0.5 and len(solution.visits) < len(attractions):
                    # 添加
                    unused = [a for a in attractions if a not in solution.visits]
                    if unused:
                        solution.visits.append(random.choice(unused))
                elif len(solution.visits) > 2:
                    # 移除
                    solution.visits.pop(random.randrange(len(solution.visits)))

        return offspring

    def _select_next_generation(
        self,
        combined: List[Solution],
    ) -> List[Solution]:
        """选择下一代"""
        # 评估
        for solution in combined:
            self._evaluate_solution(solution)

        # 非支配排序
        fronts = self._fast_non_dominated_sort(combined)

        # 计算拥挤距离
        for front in fronts:
            self._calculate_crowding_distance(front)

        # 选择
        next_gen = []
        for front in fronts:
            if len(next_gen) + len(front) <= self.population_size:
                next_gen.extend(front)
            else:
                # 按拥挤距离排序
                front.sort(key=lambda s: s.crowding_distance, reverse=True)
                remaining = self.population_size - len(next_gen)
                next_gen.extend(front[:remaining])
                break

        return next_gen


# 使用示例
def create_travel_optimizer(
    weights: Optional[Dict[str, float]] = None,
) -> MultiObjectiveOptimizer:
    """
    创建旅行优化器

    Args:
        weights: 目标权重 {"time": 0.3, "cost": 0.3, "experience": 0.4}

    Returns:
        配置好的优化器
    """
    objectives = [
        TimeObjective(name="time", description="总行程时间", weight=weights.get("time", 1.0)),
        CostObjective(name="cost", description="总花费", weight=weights.get("cost", 1.0)),
        ExperienceObjective(name="experience", description="体验评分", weight=weights.get("experience", 1.0)),
        DiversityObjective(name="diversity", description="多样性", weight=weights.get("diversity", 0.5)),
        AccessibilityObjective(name="accessibility", description="适老化", weight=weights.get("accessibility", 0.5)),
    ]

    return MultiObjectiveOptimizer(
        objectives=objectives,
        population_size=50,
        generations=100,
        mutation_rate=0.1,
        crossover_rate=0.8,
    )
