"""
Agent Protocol 标准接口定义
定义所有 Agent 必须遵循的接口规范
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, TypeVar, Generic

if TYPE_CHECKING:
    from app.core.agent.message_bus import MessageBus

T = TypeVar("T")


class AgentType(str, Enum):
    """Agent 类型枚举"""
    ORCHESTRATOR = "orchestrator"
    PLANNER = "planner"
    ATTRACTION = "attraction"
    ITINERARY = "itinerary"
    BUDGET = "budget"
    WEATHER = "weather"
    REVIEW = "review"
    MEMORY = "memory"
    REFLECTION = "reflection"
    QUALITY = "quality"
    PERSONALIZATION = "personalization"
    CUSTOM = "custom"


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Priority(str, Enum):
    """任务优先级"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class AgentCapability:
    """Agent 能力定义"""
    name: str
    description: str
    input_types: List[str] = field(default_factory=list)
    output_types: List[str] = field(default_factory=list)


@dataclass
class TaskDependency:
    """任务依赖关系"""
    task_id: str
    required_output_key: str
    target_input_key: str


@dataclass
class AgentTask:
    """Agent 任务"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_type: AgentType = AgentType.CUSTOM
    agent_name: str = ""
    description: str = ""
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_key: str = ""
    status: TaskStatus = TaskStatus.PENDING
    priority: Priority = Priority.NORMAL
    dependencies: List[TaskDependency] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_ready(self) -> bool:
        """检查任务是否准备就绪（所有依赖已满足）"""
        return self.status == TaskStatus.READY

    @property
    def execution_time_ms(self) -> float:
        """计算执行时间（毫秒）"""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds() * 1000
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "agent_type": self.agent_type.value,
            "agent_name": self.agent_name,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "dependencies": [
                {"task_id": d.task_id, "required_output_key": d.required_output_key, "target_input_key": d.target_input_key}
                for d in self.dependencies
            ],
            "execution_time_ms": self.execution_time_ms,
            "error": self.error,
        }


@dataclass
class AgentResult:
    """Agent 执行结果"""
    task_id: str
    agent_name: str
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    content: str = ""
    artifacts: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    execution_time_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def merge(self, other: AgentResult) -> AgentResult:
        """合并另一个结果"""
        return AgentResult(
            task_id=self.task_id,
            agent_name=self.agent_name,
            success=self.success and other.success,
            data={**self.data, **other.data},
            content=self.content + "\n" + other.content,
            artifacts={**self.artifacts, **other.artifacts},
            metrics={**self.metrics, **other.metrics},
            error=self.error or other.error,
            warnings=self.warnings + other.warnings,
            suggestions=self.suggestions + other.suggestions,
            execution_time_ms=self.execution_time_ms + other.execution_time_ms,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "success": self.success,
            "data": self.data,
            "content": self.content,
            "execution_time_ms": self.execution_time_ms,
            "error": self.error,
            "warnings": self.warnings,
            "suggestions": self.suggestions,
        }


@dataclass
class ExecutionPlan:
    """执行计划"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tasks: List[AgentTask] = field(default_factory=list)
    execution_order: List[str] = field(default_factory=list)  # 任务ID列表
    parallel_groups: List[List[str]] = field(default_factory=list)  # 可并行执行的任务组
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def get_task(self, task_id: str) -> Optional[AgentTask]:
        """获取指定任务"""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def get_ready_tasks(self, completed_results: Dict[str, AgentResult]) -> List[AgentTask]:
        """获取准备就绪的任务（依赖都已完成）"""
        ready = []
        for task in self.tasks:
            if task.status != TaskStatus.PENDING:
                continue

            all_deps_satisfied = True
            for dep in task.dependencies:
                if dep.task_id not in completed_results or not completed_results[dep.task_id].success:
                    all_deps_satisfied = False
                    break

            if all_deps_satisfied:
                task.status = TaskStatus.READY
                ready.append(task)

        return ready


class AgentProtocol(ABC):
    """
    Agent Protocol 抽象基类
    定义所有 Agent 必须实现的接口
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Agent 名称"""
        pass

    @property
    @abstractmethod
    def agent_type(self) -> AgentType:
        """Agent 类型"""
        pass

    @property
    def description(self) -> str:
        """Agent 描述"""
        return ""

    @property
    def capabilities(self) -> List[AgentCapability]:
        """Agent 支持的能力列表"""
        return []

    @property
    def supported_tasks(self) -> List[str]:
        """支持的输入任务类型"""
        return []

    @abstractmethod
    async def plan(
        self,
        task: AgentTask,
        context: Dict[str, Any],
    ) -> ExecutionPlan:
        """
        计划阶段
        分析任务，生成执行计划

        Args:
            task: 输入任务
            context: 执行上下文

        Returns:
            ExecutionPlan: 执行计划
        """
        pass

    @abstractmethod
    async def execute(
        self,
        task: AgentTask,
        context: Dict[str, Any],
        message_bus: Optional[MessageBus] = None,
    ) -> AgentResult:
        """
        执行阶段
        执行任务并返回结果

        Args:
            task: 要执行的任务
            context: 执行上下文
            message_bus: 消息总线（可选）

        Returns:
            AgentResult: 执行结果
        """
        pass

    async def reflect(
        self,
        result: AgentResult,
        context: Dict[str, Any],
    ) -> AgentResult:
        """
        反思阶段
        检查结果质量，决定是否需要重试或修正

        默认实现：不做任何修改直接返回

        Args:
            result: 执行结果
            context: 执行上下文

        Returns:
            AgentResult: 反思后的结果
        """
        return result

    async def validate_input(self, task: AgentTask) -> tuple[bool, str]:
        """
        验证输入是否有效

        Args:
            task: 输入任务

        Returns:
            (是否有效, 错误信息)
        """
        return True, ""

    def get_dependencies(self, task: AgentTask) -> List[str]:
        """
        获取任务依赖的其他 Agent

        Args:
            task: 输入任务

        Returns:
            依赖的 Agent 名称列表
        """
        return []

    async def cleanup(self) -> None:
        """清理资源"""
        pass


class AgentFactory:
    """Agent 工厂类"""

    _creators: Dict[str, type[AgentProtocol]] = {}

    @classmethod
    def register(cls, name: str, creator: type[AgentProtocol]) -> None:
        """注册 Agent 创建器"""
        cls._creators[name] = creator

    @classmethod
    def create(cls, name: str, **kwargs) -> AgentProtocol:
        """创建 Agent 实例"""
        if name not in cls._creators:
            raise ValueError(f"Unknown agent type: {name}")
        return cls._creators[name](**kwargs)

    @classmethod
    def available_agents(cls) -> List[str]:
        """获取可用的 Agent 列表"""
        return list(cls._creators.keys())


def register_agent(name: str):
    """Agent 注册装饰器"""
    def decorator(cls: type[AgentProtocol]):
        AgentFactory.register(name, cls)
        return cls
    return decorator
