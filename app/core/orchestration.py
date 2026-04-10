"""
Task Decomposer & DAG Scheduler - 任务分解器与 DAG 调度器
将复杂任务分解为子任务，并按依赖关系调度执行
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, TYPE_CHECKING

from app.core.logger import get_logger

if TYPE_CHECKING:
    from app.core.agent.protocol import AgentProtocol, AgentTask, AgentResult

logger = get_logger(__name__)


class TaskPriority(str, Enum):
    """任务优先级"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TaskState(str, Enum):
    """任务状态"""
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class SubTask:
    """子任务"""
    id: str
    name: str
    description: str
    agent_name: str
    agent_type: str
    dependencies: List[str] = field(default_factory=list)  # 依赖的任务ID
    priority: TaskPriority = TaskPriority.NORMAL
    state: TaskState = TaskState.PENDING
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Any = None
    result: Any = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    execution_time_ms: float = 0.0

    @property
    def is_ready(self) -> bool:
        """检查任务是否准备就绪"""
        return self.state == TaskState.READY

    @property
    def is_completed(self) -> bool:
        return self.state == TaskState.COMPLETED

    @property
    def is_failed(self) -> bool:
        return self.state == TaskState.FAILED

    @property
    def can_execute(self) -> bool:
        """检查任务是否可以执行"""
        return self.state in (TaskState.PENDING, TaskState.READY)


@dataclass
class ExecutionGraph:
    """执行图（DAG）"""
    tasks: Dict[str, SubTask] = field(default_factory=dict)
    adjacency_list: Dict[str, List[str]] = field(default_factory=defaultdict(list))
    reverse_adjacency: Dict[str, List[str]] = field(default_factory=defaultdict(list))

    def add_task(self, task: SubTask) -> None:
        """添加任务"""
        self.tasks[task.id] = task
        for dep in task.dependencies:
            self.adjacency_list[dep].append(task.id)
            self.reverse_adjacency[task.id].append(dep)

    def get_ready_tasks(self, completed: Set[str]) -> List[SubTask]:
        """获取准备就绪的任务"""
        ready = []
        for task_id, task in self.tasks.items():
            if task.state not in (TaskState.PENDING, TaskState.READY):
                continue

            # 检查所有依赖是否已完成
            deps_satisfied = all(dep in completed for dep in task.dependencies)
            if deps_satisfied:
                task.state = TaskState.READY
                ready.append(task)

        # 按优先级排序
        priority_order = {
            TaskPriority.URGENT: 0,
            TaskPriority.HIGH: 1,
            TaskPriority.NORMAL: 2,
            TaskPriority.LOW: 3,
        }
        ready.sort(key=lambda t: priority_order.get(t.priority, 2))

        return ready

    def get_execution_order(self) -> List[List[str]]:
        """获取执行顺序（分层）"""
        in_degree = defaultdict(int)
        for task in self.tasks.values():
            in_degree[task.id] = len(task.dependencies)

        layers = []
        remaining = set(self.tasks.keys())

        while remaining:
            # 找到入度为0的任务
            ready = [t for t in remaining if in_degree[t] == 0]
            if not ready:
                # 可能有循环依赖
                break

            layers.append(ready)
            remaining -= set(ready)

            # 更新入度
            for task_id in ready:
                for next_task in self.adjacency_list[task_id]:
                    in_degree[next_task] -= 1

        return layers

    def get_completed_results(self) -> Dict[str, Any]:
        """获取已完成任务的结果"""
        return {
            task_id: task.result
            for task_id, task in self.tasks.items()
            if task.is_completed and task.result is not None
        }


class TaskDecomposer:
    """
    任务分解器
    将复杂任务分解为可执行的子任务
    """

    # 意图到任务模板的映射
    INTENT_TASK_TEMPLATES: Dict[str, List[Dict[str, Any]]] = {
        "trip_planning": [
            {
                "name": "parse_intent",
                "agent": "planner",
                "description": "解析用户意图和提取旅行信息",
                "dependencies": [],
                "priority": "high",
            },
            {
                "name": "search_attractions",
                "agent": "attraction",
                "description": "搜索目的地景点",
                "dependencies": ["parse_intent"],
                "priority": "high",
            },
            {
                "name": "check_weather",
                "agent": "weather",
                "description": "查询天气预报",
                "dependencies": ["parse_intent"],
                "priority": "normal",
            },
            {
                "name": "plan_itinerary",
                "agent": "itinerary",
                "description": "规划行程安排",
                "dependencies": ["search_attractions", "check_weather"],
                "priority": "high",
            },
            {
                "name": "calculate_budget",
                "agent": "budget",
                "description": "计算预算",
                "dependencies": ["plan_itinerary"],
                "priority": "normal",
            },
            {
                "name": "review_plan",
                "agent": "review",
                "description": "审查规划结果",
                "dependencies": ["plan_itinerary", "calculate_budget"],
                "priority": "normal",
            },
        ],
        "attraction_recommendation": [
            {
                "name": "parse_destination",
                "agent": "planner",
                "description": "解析目的地信息",
                "dependencies": [],
                "priority": "high",
            },
            {
                "name": "search_attractions",
                "agent": "attraction",
                "description": "搜索景点",
                "dependencies": ["parse_destination"],
                "priority": "high",
            },
            {
                "name": "personalize_recommendations",
                "agent": "personalization",
                "description": "个性化推荐",
                "dependencies": ["search_attractions"],
                "priority": "normal",
            },
        ],
        "itinerary_planning": [
            {
                "name": "analyze_requirements",
                "agent": "planner",
                "description": "分析行程需求",
                "dependencies": [],
                "priority": "high",
            },
            {
                "name": "search_places",
                "agent": "attraction",
                "description": "搜索地点",
                "dependencies": ["analyze_requirements"],
                "priority": "high",
            },
            {
                "name": "create_schedule",
                "agent": "itinerary",
                "description": "创建日程安排",
                "dependencies": ["search_places"],
                "priority": "high",
            },
            {
                "name": "optimize_route",
                "agent": "route",
                "description": "优化路线",
                "dependencies": ["create_schedule"],
                "priority": "normal",
            },
        ],
        "budget_control": [
            {
                "name": "analyze_budget",
                "agent": "budget",
                "description": "分析预算需求",
                "dependencies": [],
                "priority": "high",
            },
            {
                "name": "calculate_costs",
                "agent": "budget",
                "description": "计算费用",
                "dependencies": ["analyze_budget"],
                "priority": "high",
            },
        ],
        "weather_adjustment": [
            {
                "name": "get_weather",
                "agent": "weather",
                "description": "获取天气预报",
                "dependencies": [],
                "priority": "high",
            },
            {
                "name": "adjust_itinerary",
                "agent": "itinerary",
                "description": "调整行程",
                "dependencies": ["get_weather"],
                "priority": "high",
            },
        ],
    }

    def __init__(self, llm: Optional[Any] = None):
        self._llm = llm

    async def decompose(
        self,
        intent: str,
        context: Dict[str, Any],
    ) -> ExecutionGraph:
        """
        分解任务

        Args:
            intent: 用户意图
            context: 上下文信息

        Returns:
            ExecutionGraph: 执行图
        """
        import uuid

        # 获取任务模板
        template = self.INTENT_TASK_TEMPLATES.get(
            intent,
            self.INTENT_TASK_TEMPLATES.get("trip_planning", [])
        )

        graph = ExecutionGraph()

        for task_spec in template:
            task_id = f"{intent}_{task_spec['name']}_{uuid.uuid4().hex[:4]}"
            task = SubTask(
                id=task_id,
                name=task_spec["name"],
                description=task_spec["description"],
                agent_name=task_spec["agent"],
                agent_type=task_spec["agent"],
                dependencies=task_spec.get("dependencies", []),
                priority=TaskPriority(task_spec.get("priority", "normal")),
                input_data=context.copy(),
            )
            graph.add_task(task)

        return graph

    async def decompose_with_llm(
        self,
        user_message: str,
        context: Dict[str, Any],
    ) -> ExecutionGraph:
        """
        使用 LLM 智能分解任务

        Args:
            user_message: 用户消息
            context: 上下文信息

        Returns:
            ExecutionGraph: 执行图
        """
        if not self._llm:
            # 没有 LLM，使用模板
            intent = context.get("intent", "trip_planning")
            return await self.decompose(intent, context)

        # 构建提示
        prompt = f"""分析用户请求，将任务分解为可执行的子任务。

用户请求: {user_message}

可用Agent类型:
- planner: 规划协调
- attraction: 景点搜索推荐
- itinerary: 行程规划
- budget: 预算计算
- weather: 天气查询
- route: 路线规划
- review: 结果审查
- personalization: 个性化推荐
- memory: 记忆管理

请输出JSON格式，包含任务列表：
{{
    "tasks": [
        {{
            "name": "task_name",
            "agent": "agent_type",
            "description": "任务描述",
            "dependencies": ["dependency_task_name"],  // 依赖的任务名称
            "priority": "high/normal/low"
        }}
    ]
}}

只输出JSON。"""

        try:
            from app.core.llm.client import LLMMessage

            messages = [LLMMessage(role="user", content=prompt)]
            response = await self._llm.chat(messages)

            import json
            content = response.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            data = json.loads(content)
            return self._build_graph_from_spec(data.get("tasks", []), context)

        except Exception as e:
            logger.warning(f"LLM decomposition failed: {e}, using template")
            intent = context.get("intent", "trip_planning")
            return await self.decompose(intent, context)

    def _build_graph_from_spec(
        self,
        task_specs: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> ExecutionGraph:
        """从规格构建执行图"""
        import uuid

        graph = ExecutionGraph()
        task_map: Dict[str, str] = {}  # name -> id

        # 第一遍：创建所有任务
        for spec in task_specs:
            task_id = f"task_{spec['name']}_{uuid.uuid4().hex[:4]}"
            task = SubTask(
                id=task_id,
                name=spec["name"],
                description=spec.get("description", ""),
                agent_name=spec["agent"],
                agent_type=spec["agent"],
                dependencies=[],  # 暂时为空
                priority=TaskPriority(spec.get("priority", "normal")),
                input_data=context.copy(),
            )
            graph.add_task(task)
            task_map[spec["name"]] = task_id

        # 第二遍：设置依赖关系
        for spec in task_specs:
            task_id = task_map.get(spec["name"])
            if not task_id:
                continue

            task = graph.tasks[task_id]
            for dep_name in spec.get("dependencies", []):
                dep_id = task_map.get(dep_name)
                if dep_id:
                    task.dependencies.append(dep_id)

        return graph


class DAGScheduler:
    """
    DAG 调度器
    按依赖关系调度任务执行
    """

    def __init__(
        self,
        agent_registry: Optional[Any] = None,
        max_parallel: int = 5,
    ):
        self.agent_registry = agent_registry
        self.max_parallel = max_parallel
        self._semaphore = asyncio.Semaphore(max_parallel)
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._results: Dict[str, Any] = {}

    async def execute(
        self,
        graph: ExecutionGraph,
        on_task_start: Optional[Callable] = None,
        on_task_complete: Optional[Callable] = None,
        on_task_error: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        执行 DAG

        Args:
            graph: 执行图
            on_task_start: 任务开始回调
            on_task_complete: 任务完成回调
            on_task_error: 任务错误回调

        Returns:
            Dict[str, Any]: 所有任务的结果
        """
        completed: Set[str] = set()
        results: Dict[str, Any] = {}
        failed_tasks: List[str] = []

        logger.info(f"Starting DAG execution with {len(graph.tasks)} tasks")

        while True:
            # 获取准备就绪的任务
            ready_tasks = graph.get_ready_tasks(completed)

            if not ready_tasks and not self._running_tasks:
                # 没有更多任务
                break

            # 启动就绪的任务
            for task in ready_tasks:
                task.state = TaskState.RUNNING
                task.started_at = datetime.utcnow()

                if on_task_start:
                    await on_task_start(task)

                # 创建执行任务
                exec_task = asyncio.create_task(self._execute_task(task, graph))
                self._running_tasks[task.id] = exec_task

            # 等待任一任务完成
            if self._running_tasks:
                done, pending = await asyncio.wait(
                    self._running_tasks.values(),
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for d in done:
                    task_id = None
                    for tid, t in list(self._running_tasks.items()):
                        if t == d:
                            task_id = tid
                            break

                    if task_id:
                        task = graph.tasks[task_id]
                        del self._running_tasks[task_id]

                        try:
                            result = d.result()
                            results[task_id] = result
                            completed.add(task_id)

                            task.result = result
                            task.completed_at = datetime.utcnow()
                            task.execution_time_ms = (
                                task.completed_at - task.started_at
                            ).total_seconds() * 1000
                            task.state = TaskState.COMPLETED

                            if on_task_complete:
                                await on_task_complete(task, result)

                        except Exception as e:
                            task.state = TaskState.FAILED
                            task.error = str(e)
                            failed_tasks.append(task_id)
                            logger.error(f"Task {task_id} failed: {e}")

                            if on_task_error:
                                await on_task_error(task, e)

        logger.info(
            f"DAG execution completed: "
            f"{len(completed)} succeeded, {len(failed_tasks)} failed"
        )

        return {
            "results": results,
            "completed": list(completed),
            "failed": failed_tasks,
            "success": len(failed_tasks) == 0,
        }

    async def _execute_task(
        self,
        task: SubTask,
        graph: ExecutionGraph,
    ) -> Any:
        """执行单个任务"""
        async with self._semaphore:
            # 获取 Agent
            agent = self._get_agent(task.agent_name)

            if agent is None:
                logger.warning(f"No agent found for: {task.agent_name}, using mock result")
                return {"mock": True, "task": task.name}

            # 准备输入数据
            input_data = task.input_data.copy()

            # 注入依赖结果
            for dep_id in task.dependencies:
                if dep_id in graph.tasks:
                    dep_task = graph.tasks[dep_id]
                    if dep_task.result:
                        input_data[f"from_{dep_task.name}"] = dep_task.result

            # 执行
            try:
                if hasattr(agent, "run"):
                    # 旧版 Agent
                    result = await agent.run(input_data, {})
                    return result
                elif hasattr(agent, "execute"):
                    # 新版 Agent
                    from app.core.agent.protocol import AgentTask
                    agent_task = AgentTask(
                        id=task.id,
                        agent_type=task.agent_type,
                        description=task.description,
                        input_data=input_data,
                    )
                    result = await agent.execute(agent_task, input_data)
                    return result.data if hasattr(result, "data") else result

            except Exception as e:
                logger.exception(f"Agent execution error: {task.agent_name}")
                raise

    def _get_agent(self, agent_name: str) -> Optional[Any]:
        """获取 Agent"""
        if self.agent_registry:
            return self.agent_registry.get(agent_name)

        # 尝试从注册表获取
        try:
            from app.core.agent.registry import get_agent_registry
            registry = get_agent_registry()
            return registry.get(agent_name)
        except Exception:
            return None

    async def cancel(self) -> None:
        """取消所有运行中的任务"""
        for task_id, task in self._running_tasks.items():
            task.cancel()
            graph_task = self._results.get(task_id)
            if graph_task:
                graph_task.state = TaskState.CANCELLED

        self._running_tasks.clear()

    def get_running_count(self) -> int:
        """获取运行中的任务数"""
        return len(self._running_tasks)


# ========== 全局实例 ==========

_decomposer: Optional[TaskDecomposer] = None


def get_task_decomposer(llm: Optional[Any] = None) -> TaskDecomposer:
    """获取任务分解器"""
    global _decomposer
    if _decomposer is None:
        _decomposer = TaskDecomposer(llm)
    return _decomposer


_scheduler: Optional[DAGScheduler] = None


def get_dag_scheduler(agent_registry: Optional[Any] = None) -> DAGScheduler:
    """获取 DAG 调度器"""
    global _scheduler
    if _scheduler is None:
        _scheduler = DAGScheduler(agent_registry)
    return _scheduler
