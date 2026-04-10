"""
Agent 基类 - 基于 Protocol 的新实现
支持事件驱动通信和标准化的生命周期
"""
from __future__ import annotations

import asyncio
import time
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from app.core.agent.protocol import (
    AgentProtocol,
    AgentResult,
    AgentTask,
    AgentType,
    ExecutionPlan,
    Priority,
    TaskStatus,
)
from app.core.agent.message_bus import MessageBus, MessagePriority, Message as AgentMessage
from app.core.logger import get_logger

if TYPE_CHECKING:
    from app.core.agent.registry import AgentRegistry

logger = get_logger(__name__)


class LifecycleState(str, Enum):
    """Agent 生命周期状态"""
    CREATED = "created"
    INITIALIZING = "initializing"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass
class AgentEvent:
    """Agent 事件"""
    agent_name: str
    event_type: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    data: Dict[str, Any] = field(default_factory=dict)


class BaseAgent(AgentProtocol):
    """
    基于 Protocol 的 Agent 基类
    提供标准化的生命周期管理和事件处理
    """

    def __init__(
        self,
        name: str,
        agent_type: AgentType,
        description: str = "",
        max_retries: int = 3,
        timeout_seconds: int = 120,
        default_temperature: float = 0.3,
        default_max_tokens: int = 4096,
        message_bus: Optional[MessageBus] = None,
        registry: Optional[AgentRegistry] = None,
    ):
        self._name = name
        self._agent_type = agent_type
        self._description = description
        self._max_retries = max_retries
        self._timeout_seconds = timeout_seconds
        self._default_temperature = default_temperature
        self._default_max_tokens = default_max_tokens

        # 状态管理
        self._state = LifecycleState.CREATED
        self._message_bus = message_bus
        self._registry = registry

        # 事件处理
        self._event_handlers: Dict[str, List[Callable]] = {}
        self._event_history: List[AgentEvent] = []

        # 指标
        self._metrics = {
            "total_executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
            "total_execution_time_ms": 0.0,
            "total_tokens": 0,
        }

        logger.info(f"Agent '{name}' initialized (type: {agent_type.value})")

    # ========== Protocol 实现 ==========

    @property
    def name(self) -> str:
        return self._name

    @property
    def agent_type(self) -> AgentType:
        return self._agent_type

    @property
    def description(self) -> str:
        return self._description

    @property
    def state(self) -> LifecycleState:
        return self._state

    @property
    def metrics(self) -> Dict[str, Any]:
        return {
            **self._metrics,
            "avg_execution_time_ms": (
                self._metrics["total_execution_time_ms"] / self._metrics["total_executions"]
                if self._metrics["total_executions"] > 0 else 0
            ),
            "success_rate": (
                self._metrics["successful_executions"] / self._metrics["total_executions"]
                if self._metrics["total_executions"] > 0 else 0
            ),
        }

    async def plan(
        self,
        task: AgentTask,
        context: Dict[str, Any],
    ) -> ExecutionPlan:
        """默认实现：创建包含单个任务的执行计划"""
        return ExecutionPlan(
            tasks=[task],
            execution_order=[task.id],
        )

    @abstractmethod
    async def _execute(
        self,
        task: AgentTask,
        context: Dict[str, Any],
    ) -> AgentResult:
        """
        实际执行逻辑
        子类必须实现此方法
        """
        pass

    async def execute(
        self,
        task: AgentTask,
        context: Dict[str, Any],
        message_bus: Optional[MessageBus] = None,
    ) -> AgentResult:
        """
        执行任务
        提供标准化的执行流程：验证 -> 前置处理 -> 执行 -> 后置处理 -> 反思
        """
        bus = message_bus or self._message_bus

        # 状态转换
        self._set_state(LifecycleState.RUNNING)
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()

        start_time = time.time()

        # 发布开始事件
        await self._publish_event(bus, "execution_start", {"task_id": task.id})

        try:
            # 验证输入
            is_valid, error_msg = await self.validate_input(task)
            if not is_valid:
                raise ValueError(f"Invalid input: {error_msg}")

            # 前置处理
            await self._pre_execute(task, context, bus)

            # 执行核心逻辑
            result = await self._execute_with_timeout(
                self._execute(task, context),
                timeout=self._timeout_seconds,
            )

            # 后置处理
            result = await self._post_execute(task, context, result, bus)

            # 反思
            result = await self.reflect(result, context)

            # 更新指标
            execution_time = (time.time() - start_time) * 1000
            self._update_metrics(success=True, execution_time_ms=execution_time)

            # 更新任务状态
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.utcnow()

            # 发布完成事件
            await self._publish_event(bus, "execution_complete", {
                "task_id": task.id,
                "execution_time_ms": execution_time,
            })

            self._set_state(LifecycleState.COMPLETED)
            return result

        except asyncio.TimeoutError:
            error_msg = f"Execution timed out after {self._timeout_seconds}s"
            return await self._handle_error(task, error_msg, bus)

        except Exception as e:
            return await self._handle_error(task, str(e), bus)

    async def reflect(
        self,
        result: AgentResult,
        context: Dict[str, Any],
    ) -> AgentResult:
        """
        反思阶段
        子类可以重写此方法添加自定义反思逻辑
        """
        # 如果执行失败且还有重试次数
        if not result.success and result.metrics.get("retry_count", 0) < self._max_retries:
            result.warnings.append(f"Execution failed, but will retry")
            result.metrics["retry_count"] = result.metrics.get("retry_count", 0) + 1

        return result

    async def validate_input(self, task: AgentTask) -> tuple[bool, str]:
        """验证输入"""
        return True, ""

    async def cleanup(self) -> None:
        """清理资源"""
        await self._clear_event_handlers()

    # ========== 生命周期管理 ==========

    async def initialize(self) -> None:
        """初始化 Agent"""
        if self._state != LifecycleState.CREATED:
            return

        self._set_state(LifecycleState.INITIALIZING)

        try:
            await self._setup_subscriptions()
            self._set_state(LifecycleState.READY)
            logger.info(f"Agent '{self._name}' ready")
        except Exception as e:
            logger.error(f"Agent '{self._name}' initialization failed: {e}")
            self._set_state(LifecycleState.FAILED)
            raise

    async def shutdown(self) -> None:
        """关闭 Agent"""
        self._set_state(LifecycleState.STOPPING)
        await self.cleanup()
        self._set_state(LifecycleState.STOPPED)
        logger.info(f"Agent '{self._name}' stopped")

    def _set_state(self, new_state: LifecycleState) -> None:
        """设置状态"""
        old_state = self._state
        self._state = new_state
        logger.debug(f"Agent '{self._name}' state: {old_state.value} -> {new_state.value}")

    # ========== 消息通信 ==========

    async def _setup_subscriptions(self) -> None:
        """设置消息订阅"""
        if not self._message_bus:
            return

        # 订阅自己的任务消息
        self._message_bus.subscribe(
            agent_name=self._name,
            topic=f"task:{self._name}",
            callback=self._handle_task_message,
        )

        # 订阅事件消息
        self._message_bus.subscribe(
            agent_name=self._name,
            topic="agent:*",
            filter_func=lambda msg: msg.metadata.get("target") == self._name,
        )

    async def _handle_task_message(self, message: "AgentMessage") -> None:
        """处理任务消息"""
        try:
            task_data = message.payload.get("task")
            if not task_data:
                return

            task = self._deserialize_task(task_data)
            context = message.payload.get("context", {})

            result = await self.execute(task, context)

            # 发送响应
            if message.correlation_id:
                await self._message_bus.send(
                    recipient=message.sender,
                    sender=self._name,
                    topic=f"result:{self._name}",
                    payload={"result": self._serialize_result(result)},
                    correlation_id=message.correlation_id,
                )

        except Exception as e:
            logger.exception(f"Error handling task message: {e}")

    async def send_message(
        self,
        recipient: str,
        topic: str,
        payload: Dict[str, Any],
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> None:
        """发送消息给其他 Agent"""
        if self._message_bus:
            await self._message_bus.send(
                recipient=recipient,
                sender=self._name,
                topic=topic,
                payload=payload,
                priority=priority,
            )

    async def broadcast(
        self,
        topic: str,
        payload: Dict[str, Any],
    ) -> None:
        """广播消息"""
        if self._message_bus:
            await self._message_bus.broadcast(
                sender=self._name,
                topic=topic,
                payload=payload,
            )

    async def request(
        self,
        recipient: str,
        topic: str,
        payload: Dict[str, Any],
        timeout: float = 30.0,
    ) -> Message:
        """发送请求并等待响应"""
        if not self._message_bus:
            raise RuntimeError("Message bus not available")

        return await self._message_bus.request(
            recipient=recipient,
            sender=self._name,
            topic=topic,
            payload=payload,
            timeout=timeout,
        )

    # ========== 事件处理 ==========

    def on_event(self, event_type: str, handler: Callable) -> None:
        """注册事件处理器"""
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)

    def off_event(self, event_type: str, handler: Callable) -> None:
        """移除事件处理器"""
        if event_type in self._event_handlers:
            self._event_handlers[event_type].remove(handler)

    async def emit_event(self, event_type: str, data: Dict[str, Any] = None) -> None:
        """触发事件"""
        event = AgentEvent(
            agent_name=self._name,
            event_type=event_type,
            data=data or {},
        )

        self._event_history.append(event)

        if event_type in self._event_handlers:
            for handler in self._event_handlers[event_type]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event)
                    else:
                        handler(event)
                except Exception as e:
                    logger.error(f"Error in event handler: {e}")

    async def _publish_event(
        self,
        bus: Optional[MessageBus],
        event_type: str,
        data: Dict[str, Any],
    ) -> None:
        """发布事件到消息总线"""
        if bus:
            await bus.publish(
                topic=f"agent:{event_type}",
                sender=self._name,
                payload=data,
                metadata={"agent": self._name, "target": None},
            )

        await self.emit_event(event_type, data)

    async def _clear_event_handlers(self) -> None:
        """清除事件处理器"""
        self._event_handlers.clear()

    # ========== 辅助方法 ==========

    async def _pre_execute(
        self,
        task: AgentTask,
        context: Dict[str, Any],
        bus: Optional[MessageBus],
    ) -> None:
        """执行前处理"""
        pass

    async def _post_execute(
        self,
        task: AgentTask,
        context: Dict[str, Any],
        result: AgentResult,
        bus: Optional[MessageBus],
    ) -> AgentResult:
        """执行后处理"""
        return result

    async def _handle_error(
        self,
        task: AgentTask,
        error: str,
        bus: Optional[MessageBus],
    ) -> AgentResult:
        """处理错误"""
        task.status = TaskStatus.FAILED
        task.error = error
        task.completed_at = datetime.utcnow()

        self._update_metrics(success=False, execution_time_ms=0)
        self._set_state(LifecycleState.FAILED)

        await self._publish_event(bus, "execution_error", {
            "task_id": task.id,
            "error": error,
        })

        return AgentResult(
            task_id=task.id,
            agent_name=self._name,
            success=False,
            error=error,
        )

    async def _execute_with_timeout(
        self,
        coro,
        timeout: int,
    ):
        """带超时的执行"""
        return await asyncio.wait_for(coro, timeout=timeout)

    def _update_metrics(
        self,
        success: bool,
        execution_time_ms: float,
    ) -> None:
        """更新指标"""
        self._metrics["total_executions"] += 1

        if success:
            self._metrics["successful_executions"] += 1
        else:
            self._metrics["failed_executions"] += 1

        self._metrics["total_execution_time_ms"] += execution_time_ms

    def _deserialize_task(self, data: Dict[str, Any]) -> AgentTask:
        """反序列化任务"""
        return AgentTask(
            id=data.get("id", str(datetime.utcnow().timestamp())),
            agent_type=AgentType(data.get("agent_type", "custom")),
            description=data.get("description", ""),
            input_data=data.get("input_data", {}),
            output_key=data.get("output_key", ""),
        )

    def _serialize_result(self, result: AgentResult) -> Dict[str, Any]:
        """序列化结果"""
        return result.to_dict()

    def get_event_history(self, limit: int = 100) -> List[AgentEvent]:
        """获取事件历史"""
        return self._event_history[-limit:]


def register_agent(name: str, agent_type: AgentType):
    """Agent 注册装饰器"""
    def decorator(cls):
        cls._agent_name = name
        cls._agent_type = agent_type

        # 注册到 AgentFactory
        from app.core.agent.protocol import AgentFactory
        AgentFactory.register(name, cls)

        return cls
    return decorator
