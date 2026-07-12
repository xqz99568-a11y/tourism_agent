"""
Agent 基类
所有 Agent 的抽象基类 - 增强版
"""
from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Optional, TypeVar

from pydantic import BaseModel, Field

from app.core.context import ExecutionContext, SessionContext, ToolCall, ReasoningNode
from app.core.llm.client import LLMMessage, LLMResponse, LLMManager, ToolDefinition
from app.core.logger import get_logger
from app.core.tracing import record_agent_timing, record_tool_call

logger = get_logger(__name__)

T = TypeVar("T", bound="AgentResponse")


class AgentStatus(str, Enum):
    """Agent 状态"""
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentCapability(str, Enum):
    """Agent 能力"""
    PLANNING = "planning"
    REASONING = "reasoning"
    SEARCH = "search"
    CALCULATION = "calculation"
    EXECUTION = "execution"
    REVIEW = "review"


@dataclass
class AgentConfig:
    """Agent 配置"""
    name: str
    description: str
    instructions: str
    capabilities: List[AgentCapability] = field(default_factory=list)
    max_retries: int = 3
    timeout_seconds: int = 120
    temperature: float = 0.3
    tools: List[str] = field(default_factory=list)  # 工具名称列表
    system_prompt: Optional[str] = None


@dataclass
class AgentResponse:
    """Agent 响应"""
    agent_name: str
    status: AgentStatus
    content: str
    data: Optional[Dict[str, Any]] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    execution_time_ms: float = 0
    tokens_used: int = 0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == AgentStatus.COMPLETED and self.error is None


class BaseAgent(ABC):
    """
    Agent 基类
    定义 Agent 的标准接口和通用功能 - 增强版
    支持详细的思考过程和推理链记录
    """

    def __init__(
        self,
        config: AgentConfig,
        llm: Optional[LLMManager] = None,
    ):
        self.config = config
        self.llm = llm
        self.status = AgentStatus.IDLE
        self._event_handlers: Dict[str, List[Callable]] = {}

        # 增强：当前推理链
        self._current_reasoning: List[ReasoningNode] = []
        # 增强：当前工具调用
        self._current_tool_calls: List[ToolCall] = []
        # 增强：执行上下文信息
        self._execution_context_info: Dict[str, Any] = {}

        logger.info(f"Initialized {self.config.name} Agent")

    def _start_reasoning(
        self,
        content: str,
        reasoning_type: str = "analysis",
    ) -> ReasoningNode:
        """开始一个推理节点"""
        node = ReasoningNode(
            content=content,
            reasoning_type=reasoning_type,
        )
        self._current_reasoning.append(node)
        return node

    def _add_reasoning_step(
        self,
        content: str,
        reasoning_type: str = "analysis",
        confidence: float = 1.0,
    ) -> ReasoningNode:
        """添加推理步骤"""
        node = ReasoningNode(
            content=content,
            reasoning_type=reasoning_type,
            confidence=confidence,
        )
        self._current_reasoning.append(node)
        return node

    def _start_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any] = None,
    ) -> ToolCall:
        """开始工具调用"""
        call = ToolCall(
            tool_name=tool_name,
            arguments=arguments or {},
            status="running",
            start_time=time.time(),
        )
        self._current_tool_calls.append(call)
        return call

    def _complete_tool_call(
        self,
        tool_name: str,
        result: str = None,
        error: str = None,
    ) -> Optional[ToolCall]:
        """完成工具调用"""
        for call in reversed(self._current_tool_calls):
            if call.tool_name == tool_name and call.status == "running":
                call.complete(result=result, error=error)
                record_tool_call(
                    tool_name,
                    params=call.arguments,
                    duration_ms=call.duration_ms,
                    status=call.status,
                    error=call.error,
                    agent=self.config.name,
                )
                return call
        return None

    def _set_context_info(self, key: str, value: Any) -> None:
        """设置执行上下文信息"""
        self._execution_context_info[key] = value

    def _build_reasoning_chain(self) -> List[Dict[str, Any]]:
        """构建推理链用于上下文记录"""
        return [
            {
                "content": node.content,
                "reasoning_type": node.reasoning_type,
                "confidence": node.confidence,
            }
            for node in self._current_reasoning
        ]

    def _build_tool_calls(self) -> List[Dict[str, Any]]:
        """构建工具调用列表"""
        return [
            {
                "tool_name": call.tool_name,
                "arguments": call.arguments,
                "status": call.status,
                "result": call.result,
            }
            for call in self._current_tool_calls if call.status == "completed"
        ]

    def _reset_state(self) -> None:
        """重置执行状态"""
        self._current_reasoning = []
        self._current_tool_calls = []
        self._execution_context_info = {}

    def add_reasoning(
        self,
        context: ExecutionContext,
        content: str,
        reasoning_type: str = "analysis",
        confidence: float = 1.0,
    ) -> Optional[ReasoningNode]:
        """
        向最新的思考步骤添加推理节点
        用于展示Agent的决策推理过程
        """
        return context.add_reasoning_to_latest(
            agent_name=self.config.name.capitalize(),
            content=content,
            reasoning_type=reasoning_type,
            confidence=confidence,
        )

    @abstractmethod
    async def plan(
        self,
        session: SessionContext,
        context: ExecutionContext,
    ) -> List[str]:
        """
        计划阶段
        分析任务，决定需要哪些子任务
        返回子任务列表
        """
        pass

    @abstractmethod
    async def execute(
        self,
        session: SessionContext,
        context: ExecutionContext,
    ) -> AgentResponse:
        """
        执行阶段
        执行任务并返回结果
        """
        pass

    def _record_thinking_start(self, context: ExecutionContext) -> None:
        """记录思考开始"""
        context.add_thinking_step(
            agent_name=self.config.name.capitalize(),
            step="启动",
            detail=f"🚀 {self.config.name.capitalize()} Agent 开始执行",
            status="running",
        )

    def _record_thinking_reasoning(
        self,
        context: ExecutionContext,
        step_name: str,
        reasoning_content: str,
        reasoning_type: str = "analysis",
    ) -> None:
        """记录带推理的思考步骤"""
        context.add_thinking_step(
            agent_name=self.config.name.capitalize(),
            step=step_name,
            detail=f"💭 {reasoning_content}",
            status="running",
            reasoning_chain=[
                {
                    "content": reasoning_content,
                    "reasoning_type": reasoning_type,
                    "confidence": 0.9,
                }
            ],
        )

    def _record_thinking_detail(
        self,
        context: ExecutionContext,
        step_name: str,
        detail: str,
        context_info: Dict[str, Any] = None,
    ) -> None:
        """记录详细思考步骤"""
        context.add_thinking_step(
            agent_name=self.config.name.capitalize(),
            step=step_name,
            detail=detail,
            status="running",
            context=context_info or self._execution_context_info,
        )

    def _record_thinking_complete(
        self,
        context: ExecutionContext,
        step_name: str,
        result_summary: str,
    ) -> None:
        """记录思考完成"""
        context.update_thinking_step(
            agent_name=self.config.name.capitalize(),
            step=step_name,
            detail=result_summary,
            status="completed",
        )

    def _record_tool_usage(
        self,
        context: ExecutionContext,
        step_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
        status: str = "pending",
        result: str = None,
        duration_ms: float = None,
        error: str = None,
    ) -> None:
        """记录工具使用 - 增强版"""
        tool_call_info = {
            "tool_name": tool_name,
            "arguments": arguments,
            "status": status,
        }
        if result:
            tool_call_info["result"] = result
        if duration_ms is not None:
            tool_call_info["duration_ms"] = duration_ms
        if error:
            tool_call_info["error"] = error

        if status != "pending":
            record_tool_call(
                tool_name,
                params=arguments,
                duration_ms=duration_ms,
                status=status,
                error=error,
                agent=self.config.name,
            )

        context.add_thinking_step(
            agent_name=self.config.name.capitalize(),
            step=step_name,
            detail=f"🔧 调用工具: {tool_name}" + (f" ({duration_ms:.0f}ms)" if duration_ms else ""),
            status="running" if status == "pending" else status,
            tool_calls=[tool_call_info],
        )

    def _record_tool_result(
        self,
        context: ExecutionContext,
        step_name: str,
        tool_name: str,
        result: str = None,
        duration_ms: float = None,
        error: str = None,
    ) -> None:
        """记录工具执行结果"""
        status = "failed" if error else "completed"
        self._record_tool_usage(
            context=context,
            step_name=step_name,
            tool_name=tool_name,
            arguments={},  # 结果不记录参数
            status=status,
            result=result,
            duration_ms=duration_ms,
            error=error,
        )

    def _estimate_message_chars(self, messages: List[LLMMessage]) -> int:
        """估算消息文本总长度，用于轻量性能日志。"""
        total_chars = 0
        for message in messages:
            content = getattr(message, "content", "")
            if content is None:
                continue
            if isinstance(content, list):
                total_chars += sum(len(str(item)) for item in content)
            else:
                total_chars += len(str(content))
        return total_chars

    async def run(
        self,
        session: SessionContext,
        context: ExecutionContext,
    ) -> AgentResponse:
        """
        运行 Agent 的完整生命周期
        包含计划、执行和反思 - 增强版
        """
        start_time = datetime.utcnow()
        self.status = AgentStatus.RUNNING

        logger.info(f"{self.config.name.capitalize()} Agent starting execution")

        # 记录思考步骤：开始执行
        self._record_thinking_start(context)

        # 开始记录指标
        metrics = context.start_agent_metrics(self.config.name)

        try:
            # 计划阶段
            self._add_reasoning_step(
                content=f"分析任务需求，准备执行 {self.config.name} Agent",
                reasoning_type="analysis",
            )
            plan_start = time.perf_counter()
            tasks = await self.plan(session, context)
            plan_time_ms = (time.perf_counter() - plan_start) * 1000
            if tasks:
                context.active_agents.append(self.config.name)
                context.extracted_info[f"{self.config.name}_tasks"] = tasks

            # 更新推理链
            self._add_reasoning_step(
                content=f"分解为 {len(tasks)} 个子任务: {', '.join(tasks)}",
                reasoning_type="decision",
            )

            # 执行阶段
            execute_start = time.perf_counter()
            response = await self._execute_with_timeout(
                self.execute(session, context),
                timeout=self.config.timeout_seconds,
            )
            execute_time_ms = (time.perf_counter() - execute_start) * 1000

            # 更新工具调用计数
            metrics.tool_calls_count = len(self._current_tool_calls)

            # 反思阶段
            reflect_start = time.perf_counter()
            response = await self.reflect(response, session, context)
            reflect_time_ms = (time.perf_counter() - reflect_start) * 1000

            # 更新上下文
            context.add_result(self.config.name, response)

            # 完成指标
            context.complete_agent_metrics(self.config.name, response.tokens_used)

            # 记录执行时间
            execution_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            response.execution_time_ms = execution_time
            record_agent_timing(
                self.config.name,
                execution_time,
                status=response.status.value,
                success=response.success,
                tokens_used=response.tokens_used,
                tool_calls_count=metrics.tool_calls_count,
            )

            self.status = AgentStatus.COMPLETED
            logger.info(
                "%s Agent completed in %.2fms (plan=%.2fms, execute=%.2fms, reflect=%.2fms, tool_calls=%d, tokens=%d)",
                self.config.name.capitalize(),
                execution_time,
                plan_time_ms,
                execute_time_ms,
                reflect_time_ms,
                metrics.tool_calls_count,
                response.tokens_used,
            )

            # 记录最终思考步骤
            self._record_thinking_complete(
                context,
                step_name="完成",
                result_summary=f"✅ {self.config.name.capitalize()} 执行完成，耗时 {execution_time:.0f}ms，使用 {response.tokens_used} tokens",
            )

            # 重置状态
            self._reset_state()

            return response

        except asyncio.TimeoutError:
            error_msg = f"Agent execution timed out after {self.config.timeout_seconds}s"
            logger.error(f"{self.config.name.capitalize()} Agent: {error_msg}")
            self.status = AgentStatus.FAILED

            # 记录失败
            self._record_thinking_complete(
                context,
                step_name="超时",
                result_summary=f"❌ {error_msg}",
            )

            return AgentResponse(
                agent_name=self.config.name,
                status=AgentStatus.FAILED,
                content="",
                error=error_msg,
            )

        except Exception as e:
            logger.exception(f"{self.config.name.capitalize()} Agent failed: {e}")
            self.status = AgentStatus.FAILED
            context.add_error(self.config.name, e)

            # 记录失败
            self._record_thinking_complete(
                context,
                step_name="失败",
                result_summary=f"❌ 执行失败: {str(e)}",
            )

            return AgentResponse(
                agent_name=self.config.name,
                status=AgentStatus.FAILED,
                content="",
                error=str(e),
            )

    async def reflect(
        self,
        response: AgentResponse,
        session: SessionContext,
        context: ExecutionContext,
    ) -> AgentResponse:
        """
        反思阶段
        检查结果质量，决定是否需要重试
        """
        # 如果执行失败且还有重试次数
        if not response.success and context.retry_count < self.config.max_retries:
            logger.info(
                f"{self.config.name.capitalize()} Agent will retry "
                f"(attempt {context.retry_count + 1}/{self.config.max_retries})"
            )

            # 清空错误状态
            response.status = AgentStatus.RUNNING
            response.error = None

        return response

    async def _execute_with_timeout(
        self,
        coro: Awaitable[T],
        timeout: int,
    ) -> T:
        """带超时的执行"""
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            raise asyncio.TimeoutError(f"Operation timed out after {timeout} seconds")

    # ============ 事件处理 ============

    def on(self, event: str, handler: Callable) -> None:
        """注册事件处理器"""
        if event not in self._event_handlers:
            self._event_handlers[event] = []
        self._event_handlers[event].append(handler)

    def off(self, event: str, handler: Callable) -> None:
        """移除事件处理器"""
        if event in self._event_handlers:
            self._event_handlers[event].remove(handler)

    async def emit(self, event: str, *args: Any, **kwargs: Any) -> None:
        """触发事件"""
        if event in self._event_handlers:
            for handler in self._event_handlers[event]:
                if asyncio.iscoroutinefunction(handler):
                    await handler(*args, **kwargs)
                else:
                    handler(*args, **kwargs)

    # ============ LLM 调用辅助 ============

    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs,
    ) -> LLMResponse:
        """调用 LLM"""
        if self.llm is None:
            raise ValueError("LLM not configured for this agent")

        # 记录LLM调用
        self._add_reasoning_step(
            content=f"调用 LLM 生成响应，消息数: {len(messages)}",
            reasoning_type="inference",
        )
        message_chars = self._estimate_message_chars(messages)
        tool_count = len(tools or [])
        llm_start = time.perf_counter()
        logger.info(
            "%s LLM chat starting (messages=%d, chars=%d, tools=%d)",
            self.config.name.capitalize(),
            len(messages),
            message_chars,
            tool_count,
        )
        try:
            response = await self.llm.chat(
                messages=messages,
                tools=tools,
                temperature=self.config.temperature,
                **kwargs,
            )
        except Exception:
            llm_time_ms = (time.perf_counter() - llm_start) * 1000
            logger.warning(
                "%s LLM chat failed in %.2fms (messages=%d, chars=%d, tools=%d)",
                self.config.name.capitalize(),
                llm_time_ms,
                len(messages),
                message_chars,
                tool_count,
            )
            raise

        llm_time_ms = (time.perf_counter() - llm_start) * 1000
        total_tokens = int((response.usage or {}).get("total_tokens", 0) or 0)
        logger.info(
            "%s LLM chat completed in %.2fms (messages=%d, chars=%d, tools=%d, tokens=%d, output_chars=%d)",
            self.config.name.capitalize(),
            llm_time_ms,
            len(messages),
            message_chars,
            tool_count,
            total_tokens,
            len(str(response.content or "")),
        )
        return response

    async def chat_stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """流式调用 LLM，逐 token yield"""
        if self.llm is None:
            raise ValueError("LLM not configured for this agent")

        self._add_reasoning_step(
            content=f"流式调用 LLM，消息数: {len(messages)}",
            reasoning_type="inference",
        )
        message_chars = self._estimate_message_chars(messages)
        tool_count = len(tools or [])
        chunk_count = 0
        output_chars = 0
        llm_start = time.perf_counter()
        logger.info(
            "%s LLM stream starting (messages=%d, chars=%d, tools=%d)",
            self.config.name.capitalize(),
            len(messages),
            message_chars,
            tool_count,
        )
        try:
            async for token in self.llm.stream(
                messages=messages,
                tools=tools,
                temperature=self.config.temperature,
                **kwargs,
            ):
                chunk_count += 1
                output_chars += len(str(token or ""))
                yield token
        except Exception:
            llm_time_ms = (time.perf_counter() - llm_start) * 1000
            logger.warning(
                "%s LLM stream failed in %.2fms (messages=%d, chars=%d, tools=%d, chunks=%d, output_chars=%d)",
                self.config.name.capitalize(),
                llm_time_ms,
                len(messages),
                message_chars,
                tool_count,
                chunk_count,
                output_chars,
            )
            raise

        llm_time_ms = (time.perf_counter() - llm_start) * 1000
        logger.info(
            "%s LLM stream completed in %.2fms (messages=%d, chars=%d, tools=%d, chunks=%d, output_chars=%d)",
            self.config.name.capitalize(),
            llm_time_ms,
            len(messages),
            message_chars,
            tool_count,
            chunk_count,
            output_chars,
        )

    def build_messages(
        self,
        session: SessionContext,
        system_prompt: Optional[str] = None,
        additional_context: Optional[Dict[str, Any]] = None,
    ) -> List[LLMMessage]:
        """构建消息列表"""
        build_start = time.perf_counter()
        messages = []

        # 系统提示词
        prompt = system_prompt or self.config.system_prompt or self.config.instructions

        # 添加上下文信息
        if additional_context:
            context_info = "\n\n当前上下文信息:\n"
            for key, value in additional_context.items():
                context_info += f"- {key}: {value}\n"
            prompt += context_info

        messages.append(LLMMessage(role="system", content=prompt))

        # 添加对话历史 (最近 5 轮)
        recent_turns = session.get_recent_messages(5)
        for turn in recent_turns:
            messages.append(LLMMessage(role="user", content=turn.user_message))
            if turn.ai_message:
                messages.append(LLMMessage(role="assistant", content=turn.ai_message))

        build_time_ms = (time.perf_counter() - build_start) * 1000
        logger.info(
            "%s build_messages completed in %.2fms (messages=%d, recent_turns=%d, prompt_chars=%d, total_chars=%d)",
            self.config.name.capitalize(),
            build_time_ms,
            len(messages),
            len(recent_turns),
            len(prompt),
            self._estimate_message_chars(messages),
        )
        return messages

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def description(self) -> str:
        return self.config.description
