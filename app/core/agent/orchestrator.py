"""
Agent Orchestrator - 任务编排器
整合任务分解、DAG调度、并发执行和结果聚合
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from app.core.agent.base import BaseAgent
from app.core.agent.protocol import (
    AgentProtocol,
    AgentResult,
    AgentTask,
    AgentType,
    ExecutionPlan,
    Priority,
    TaskDependency,
    TaskStatus,
)
from app.core.agent.message_bus import Message, MessageBus, MessagePriority, MessageType
from app.core.agent.registry import AgentRegistry
from app.core.logger import get_logger

logger = get_logger(__name__)


class OrchestratorState(str, Enum):
    """编排器状态"""
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class OrchestratorConfig:
    """编排器配置"""
    max_parallel_tasks: int = 5
    planning_timeout: int = 30
    execution_timeout: int = 120
    enable_reflection: bool = True
    enable_quality_check: bool = True
    max_retries: int = 3
    concurrency_mode: str = "auto"  # auto, sequential, parallel


@dataclass
class OrchestratorStats:
    """编排器统计"""
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    total_tasks: int = 0
    total_execution_time_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.successful_runs / self.total_runs


class TaskDecomposer:
    """
    任务分解器
    将用户意图分解为可执行的子任务
    """

    # 意图到 Agent 类型的映射
    INTENT_AGENT_MAP: Dict[str, List[AgentType]] = {
        "trip_planning": [
            AgentType.ATTRACTION,
            AgentType.ITINERARY,
            AgentType.BUDGET,
        ],
        "attraction_recommendation": [AgentType.ATTRACTION],
        "itinerary_planning": [AgentType.ITINERARY],
        "budget_control": [AgentType.BUDGET],
        "weather_adjustment": [AgentType.WEATHER, AgentType.ITINERARY],
        "route_consultation": [AgentType.ITINERARY, AgentType.ATTRACTION],
        "general_chat": [],
    }

    def __init__(
        self,
        registry: AgentRegistry,
        message_bus: Optional[MessageBus] = None,
    ):
        self.registry = registry
        self.message_bus = message_bus

    async def decompose(
        self,
        intent: str,
        context: Dict[str, Any],
    ) -> List[AgentTask]:
        """
        分解任务

        Args:
            intent: 用户意图
            context: 上下文信息

        Returns:
            子任务列表
        """
        tasks = []
        agent_types = self.INTENT_AGENT_MAP.get(intent, [])

        for agent_type in agent_types:
            agent = self._get_agent_for_type(agent_type)
            if agent:
                task = AgentTask(
                    id=str(uuid.uuid4()),
                    agent_type=agent_type,
                    agent_name=agent.name,
                    description=f"Execute {agent_type.value} task",
                    input_data={
                        "intent": intent,
                        "context": context,
                    },
                    output_key=f"result_{agent.name}",
                    priority=Priority.NORMAL,
                )
                tasks.append(task)

        # 如果没有匹配到任何 Agent，创建一个通用任务
        if not tasks:
            task = AgentTask(
                id=str(uuid.uuid4()),
                agent_type=AgentType.CUSTOM,
                agent_name="orchestrator",
                description=f"Handle intent: {intent}",
                input_data={
                    "intent": intent,
                    "context": context,
                },
                output_key="result_orchestrator",
                priority=Priority.NORMAL,
            )
            tasks.append(task)

        # 设置依赖关系
        tasks = self._resolve_dependencies(tasks, intent)

        logger.info(f"Decomposed intent '{intent}' into {len(tasks)} tasks")
        return tasks

    def _get_agent_for_type(self, agent_type: AgentType) -> Optional[AgentProtocol]:
        """获取指定类型的 Agent"""
        agents = self.registry.get_by_type(agent_type)
        return agents[0] if agents else None

    def _resolve_dependencies(
        self,
        tasks: List[AgentTask],
        intent: str,
    ) -> List[AgentTask]:
        """解析任务依赖"""
        # 根据意图设置依赖关系
        if intent == "trip_planning":
            # 景点 -> 行程 -> 预算
            for i, task in enumerate(tasks):
                if task.agent_type == AgentType.ITINERARY:
                    attraction_tasks = [t for t in tasks if t.agent_type == AgentType.ATTRACTION]
                    for at in attraction_tasks:
                        task.dependencies.append(TaskDependency(
                            task_id=at.id,
                            required_output_key=f"result_{at.agent_name}",
                            target_input_key="attraction_result",
                        ))

                elif task.agent_type == AgentType.BUDGET:
                    itinerary_tasks = [t for t in tasks if t.agent_type == AgentType.ITINERARY]
                    for it in itinerary_tasks:
                        task.dependencies.append(TaskDependency(
                            task_id=it.id,
                            required_output_key=f"result_{it.agent_name}",
                            target_input_key="itinerary_result",
                        ))

        return tasks


class DAGScheduler:
    """
    DAG 调度器
    管理任务的有向无环图执行
    """

    def __init__(self, max_parallel: int = 5):
        self.max_parallel = max_parallel

    def build_dag(self, tasks: List[AgentTask]) -> ExecutionPlan:
        """
        构建 DAG 执行计划

        Args:
            tasks: 任务列表

        Returns:
            执行计划
        """
        # 计算入度（依赖数）
        task_map = {task.id: task for task in tasks}
        in_degree: Dict[str, int] = {task.id: len(task.dependencies) for task in tasks}

        # 计算并行组
        parallel_groups: List[List[str]] = []
        execution_order: List[str] = []
        remaining = set(task.id for task in tasks)

        while remaining:
            # 找出入度为 0 的任务（没有依赖）
            ready = [tid for tid in remaining if in_degree.get(tid, 0) == 0]

            if not ready:
                # 可能有循环依赖，选择任意一个
                logger.warning("Circular dependency detected, breaking cycle")
                ready = [list(remaining)[0]]

            # 限制并行数
            ready = ready[:self.max_parallel]

            parallel_groups.append(ready)
            execution_order.extend(ready)

            # 更新入度
            for task_id in ready:
                remaining.remove(task_id)
                # 减少依赖该任务的其他任务的入度
                for task in tasks:
                    for dep in task.dependencies:
                        if dep.task_id == task_id:
                            in_degree[task.id] -= 1

        return ExecutionPlan(
            id=str(uuid.uuid4()),
            tasks=tasks,
            execution_order=execution_order,
            parallel_groups=parallel_groups,
        )

    def get_ready_tasks(
        self,
        plan: ExecutionPlan,
        completed: Set[str],
    ) -> List[AgentTask]:
        """获取准备就绪的任务"""
        ready = []

        for group in plan.parallel_groups:
            group_ready = []
            for task_id in group:
                task = plan.get_task(task_id)
                if not task:
                    continue

                # 检查是否已完成
                if task_id in completed:
                    continue

                # 检查所有依赖是否已满足
                deps_satisfied = True
                for dep in task.dependencies:
                    if dep.task_id not in completed:
                        deps_satisfied = False
                        break

                if deps_satisfied:
                    task.status = TaskStatus.READY
                    group_ready.append(task)

            ready.extend(group_ready)

        return ready


class ConcurrentExecutor:
    """
    并发执行引擎
    支持任务的并行执行
    """

    def __init__(
        self,
        registry: AgentRegistry,
        message_bus: Optional[MessageBus] = None,
        max_concurrent: int = 5,
    ):
        self.registry = registry
        self.message_bus = message_bus
        self.max_concurrent = max_concurrent
        self._semaphore: Optional[asyncio.Semaphore] = None

    async def execute_tasks(
        self,
        tasks: List[AgentTask],
        context: Dict[str, Any],
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, AgentResult]:
        """
        并发执行任务

        Args:
            tasks: 任务列表
            context: 执行上下文
            progress_callback: 进度回调

        Returns:
            任务ID -> 结果 的映射
        """
        results: Dict[str, AgentResult] = {}
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

        # 创建所有任务协程
        coroutines = [
            self._execute_task_with_semaphore(task, context, progress_callback)
            for task in tasks
        ]

        # 并发执行
        task_results = await asyncio.gather(*coroutines, return_exceptions=True)

        # 收集结果
        for task, result in zip(tasks, task_results):
            if isinstance(result, Exception):
                results[task.id] = AgentResult(
                    task_id=task.id,
                    agent_name=task.agent_name,
                    success=False,
                    error=str(result),
                )
            else:
                results[task.id] = result

        return results

    async def _execute_task_with_semaphore(
        self,
        task: AgentTask,
        context: Dict[str, Any],
        progress_callback: Optional[Callable],
    ) -> AgentResult:
        """使用信号量控制并发执行"""
        async with self._semaphore:
            # 获取 Agent
            agent = self.registry.get(task.agent_name)
            if not agent:
                return AgentResult(
                    task_id=task.id,
                    agent_name=task.agent_name,
                    success=False,
                    error=f"Agent '{task.agent_name}' not found",
                )

            # 执行任务
            try:
                result = await agent.execute(task, context, self.message_bus)

                # 调用进度回调
                if progress_callback:
                    await progress_callback(task, result)

                return result

            except Exception as e:
                logger.exception(f"Task {task.id} execution failed: {e}")
                return AgentResult(
                    task_id=task.id,
                    agent_name=task.agent_name,
                    success=False,
                    error=str(e),
                )


class ResultAggregator:
    """
    结果聚合器
    收集并整合多个 Agent 的执行结果
    """

    def __init__(
        self,
        registry: AgentRegistry,
        message_bus: Optional[MessageBus] = None,
    ):
        self.registry = registry
        self.message_bus = message_bus

    async def aggregate(
        self,
        results: Dict[str, AgentResult],
        plan: ExecutionPlan,
        intent: str,
    ) -> AgentResult:
        """
        聚合结果

        Args:
            results: 任务结果映射
            plan: 执行计划
            intent: 用户意图

        Returns:
            聚合后的结果
        """
        if not results:
            return AgentResult(
                task_id="aggregator",
                agent_name="orchestrator",
                success=False,
                error="No results to aggregate",
            )

        # 检查是否有失败的任务
        failed = [r for r in results.values() if not r.success]
        overall_success = len(failed) == 0

        # 合并所有结果的数据
        aggregated_data: Dict[str, Any] = {}
        all_warnings: List[str] = []
        all_suggestions: List[str] = []
        total_content = ""
        total_execution_time = 0.0

        for task_id, result in results.items():
            task = plan.get_task(task_id)
            if not task:
                continue

            # 合并数据
            aggregated_data[task.output_key] = result.data
            if result.content:
                total_content += f"\n\n=== {task.agent_name} ===\n{result.content}"

            all_warnings.extend(result.warnings)
            all_suggestions.extend(result.suggestions)
            total_execution_time += result.execution_time_ms

        # 生成摘要
        summary = self._generate_summary(results, intent)

        return AgentResult(
            task_id="aggregator",
            agent_name="orchestrator",
            success=overall_success,
            data=aggregated_data,
            content=summary + total_content,
            metrics={
                "total_tasks": len(results),
                "successful_tasks": len([r for r in results.values() if r.success]),
                "failed_tasks": len(failed),
                "total_execution_time_ms": total_execution_time,
            },
            warnings=all_warnings,
            suggestions=all_suggestions,
            execution_time_ms=total_execution_time,
        )

    def _generate_summary(
        self,
        results: Dict[str, AgentResult],
        intent: str,
    ) -> str:
        """生成结果摘要"""
        lines = ["## 执行摘要\n"]

        success_count = len([r for r in results.values() if r.success])
        total_count = len(results)

        lines.append(f"- 意图类型: {intent}")
        lines.append(f"- 执行任务: {total_count}")
        lines.append(f"- 成功: {success_count}")
        lines.append(f"- 失败: {total_count - success_count}")

        return "\n".join(lines)


class AgentOrchestrator:
    """
    Agent 编排器
    整合所有组件，提供统一的编排接口
    """

    def __init__(
        self,
        registry: Optional[AgentRegistry] = None,
        message_bus: Optional[MessageBus] = None,
        config: Optional[OrchestratorConfig] = None,
    ):
        self.registry = registry
        self.message_bus = message_bus
        self.config = config or OrchestratorConfig()

        self.state = OrchestratorState.IDLE
        self.stats = OrchestratorStats()

        # 初始化组件
        self.decomposer = TaskDecomposer(registry, message_bus)
        self.scheduler = DAGScheduler(max_parallel=self.config.max_parallel_tasks)
        self.executor = ConcurrentExecutor(
            registry,
            message_bus,
            max_concurrent=self.config.max_parallel_tasks,
        )
        self.aggregator = ResultAggregator(registry, message_bus)

        # 当前执行上下文
        self._current_plan: Optional[ExecutionPlan] = None
        self._current_results: Dict[str, AgentResult] = {}

        logger.info("AgentOrchestrator initialized")

    async def run(
        self,
        intent: str,
        context: Dict[str, Any],
        progress_callback: Optional[Callable] = None,
    ) -> AgentResult:
        """
        运行编排流程

        Args:
            intent: 用户意图
            context: 上下文信息
            progress_callback: 进度回调

        Returns:
            执行结果
        """
        start_time = datetime.utcnow()
        self.stats.total_runs += 1
        self.state = OrchestratorState.PLANNING

        try:
            # 1. 任务分解
            tasks = await self.decomposer.decompose(intent, context)
            if not tasks:
                raise ValueError("No tasks generated")

            logger.info(f"Decomposed into {len(tasks)} tasks")

            # 2. 构建 DAG
            plan = self.scheduler.build_dag(tasks)
            self._current_plan = plan

            logger.info(f"DAG built with {len(plan.parallel_groups)} parallel groups")

            # 3. 执行
            self.state = OrchestratorState.EXECUTING
            results = await self.executor.execute_tasks(
                tasks=tasks,
                context=context,
                progress_callback=progress_callback,
            )
            self._current_results = results

            self.stats.total_tasks += len(results)

            # 4. 聚合结果
            self.state = OrchestratorState.WAITING
            final_result = await self.aggregator.aggregate(results, plan, intent)

            # 5. 反思阶段
            if self.config.enable_reflection:
                final_result = await self._reflect(final_result, context)

            # 6. 质量检查
            if self.config.enable_quality_check and final_result.success:
                final_result = await self._quality_check(final_result, context)

            self.state = OrchestratorState.COMPLETED
            self.stats.successful_runs += 1

            execution_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            self.stats.total_execution_time_ms += execution_time

            return final_result

        except Exception as e:
            logger.exception(f"Orchestrator failed: {e}")
            self.state = OrchestratorState.FAILED
            self.stats.failed_runs += 1

            return AgentResult(
                task_id="orchestrator",
                agent_name="orchestrator",
                success=False,
                error=str(e),
            )

    async def run_single(
        self,
        agent_name: str,
        input_data: Dict[str, Any],
    ) -> AgentResult:
        """
        运行单个 Agent

        Args:
            agent_name: Agent 名称
            input_data: 输入数据

        Returns:
            执行结果
        """
        agent = self.registry.get(agent_name) if self.registry else None
        if not agent:
            return AgentResult(
                task_id="single",
                agent_name=agent_name,
                success=False,
                error=f"Agent '{agent_name}' not found",
            )

        task = AgentTask(
            id=str(uuid.uuid4()),
            agent_type=agent.agent_type,
            agent_name=agent_name,
            description=f"Single execution of {agent_name}",
            input_data=input_data,
            output_key=f"result_{agent_name}",
        )

        context = {"mode": "single"}
        return await agent.execute(task, context, self.message_bus)

    async def _reflect(
        self,
        result: AgentResult,
        context: Dict[str, Any],
    ) -> AgentResult:
        """反思阶段"""
        reflection_agent = self.registry.get("reflection") if self.registry else None

        if reflection_agent:
            try:
                task = AgentTask(
                    id=str(uuid.uuid4()),
                    agent_type=AgentType.REFLECTION,
                    agent_name="reflection",
                    description="Reflect on execution results",
                    input_data={
                        "result": result.to_dict(),
                        "context": context,
                    },
                )

                reflection_result = await reflection_agent.execute(task, context, self.message_bus)

                if reflection_result.success:
                    # 合并反思结果
                    result.warnings.extend(reflection_result.warnings)
                    result.suggestions.extend(reflection_result.suggestions)

            except Exception as e:
                logger.warning(f"Reflection failed: {e}")

        return result

    async def _quality_check(
        self,
        result: AgentResult,
        context: Dict[str, Any],
    ) -> AgentResult:
        """质量检查阶段"""
        quality_agent = self.registry.get("quality") if self.registry else None

        if quality_agent:
            try:
                task = AgentTask(
                    id=str(uuid.uuid4()),
                    agent_type=AgentType.QUALITY,
                    agent_name="quality",
                    description="Quality check on results",
                    input_data={
                        "result": result.to_dict(),
                        "context": context,
                    },
                )

                quality_result = await quality_agent.execute(task, context, self.message_bus)

                if quality_result.success and not quality_result.data.get("passed", True):
                    result.warnings.append("Quality check failed")
                    result.suggestions.extend(quality_result.suggestions)

            except Exception as e:
                logger.warning(f"Quality check failed: {e}")

        return result

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "orchestrator": {
                "state": self.state.value,
                "stats": self.stats.__dict__,
            },
            "registry": self.registry.get_stats() if self.registry else {},
            "message_bus": self.message_bus.get_stats() if self.message_bus else {},
        }

    def get_current_status(self) -> Dict[str, Any]:
        """获取当前执行状态"""
        return {
            "state": self.state.value,
            "plan": {
                "id": self._current_plan.id if self._current_plan else None,
                "total_tasks": len(self._current_plan.tasks) if self._current_plan else 0,
                "completed": len([r for r in self._current_results.values() if r.success]) if self._current_results else 0,
            },
        }
