"""
Tool Executor - 工具执行器
负责并发执行工具、工具选择和循环调用
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from app.core.logger import get_logger
from app.core.tracing import record_selected_tools, record_tool_call

if TYPE_CHECKING:
    from app.tools.base import BaseTool

logger = get_logger(__name__)


class ToolCallStatus(str, Enum):
    """工具调用状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ToolCall:
    """工具调用请求"""
    id: str
    tool_name: str
    arguments: Dict[str, Any]
    status: ToolCallStatus = ToolCallStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    execution_time_ms: float = 0.0

    @property
    def is_completed(self) -> bool:
        return self.status == ToolCallStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        return self.status == ToolCallStatus.FAILED


@dataclass
class ToolExecutorConfig:
    """工具执行器配置"""
    max_concurrent: int = 5  # 最大并发数
    max_retries: int = 3     # 最大重试次数
    retry_delay: float = 1.0  # 重试延迟（秒）
    timeout: float = 30.0     # 单次调用超时
    enable_parallel: bool = True  # 是否允许并行


class ToolExecutor:
    """
    工具执行器
    支持并发执行、错误重试、超时控制
    """

    def __init__(
        self,
        config: Optional[ToolExecutorConfig] = None,
        tools: Optional[Dict[str, "BaseTool"]] = None,
    ):
        self.config = config or ToolExecutorConfig()
        self._tools: Dict[str, "BaseTool"] = tools or {}
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent)
        self._running_calls: Dict[str, ToolCall] = {}

    def register_tool(self, tool: "BaseTool") -> None:
        """注册工具"""
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")

    def unregister_tool(self, tool_name: str) -> bool:
        """注销工具"""
        if tool_name in self._tools:
            del self._tools[tool_name]
            return True
        return False

    def get_tool(self, tool_name: str) -> Optional["BaseTool"]:
        """获取工具"""
        return self._tools.get(tool_name)

    def list_tools(self) -> List[str]:
        """列出所有工具"""
        return list(self._tools.keys())

    async def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        call_id: Optional[str] = None,
    ) -> ToolCall:
        """
        执行单个工具调用

        Args:
            tool_name: 工具名称
            arguments: 工具参数
            call_id: 调用ID

        Returns:
            ToolCall: 调用结果
        """
        import uuid
        call_id = call_id or str(uuid.uuid4())[:8]

        call = ToolCall(
            id=call_id,
            tool_name=tool_name,
            arguments=arguments,
            start_time=datetime.utcnow(),
        )

        self._running_calls[call_id] = call

        try:
            tool = self.get_tool(tool_name)
            if tool is None:
                raise ValueError(f"Tool not found: {tool_name}")

            # 检查参数
            if not tool.validate_params(arguments):
                raise ValueError(f"Invalid arguments for tool: {tool_name}")

            call.status = ToolCallStatus.RUNNING

            # 使用信号量控制并发
            async with self._semaphore:
                result = await asyncio.wait_for(
                    tool.execute(**arguments),
                    timeout=self.config.timeout,
                )

            call.status = ToolCallStatus.COMPLETED
            call.result = result.data if hasattr(result, 'data') else result
            call.end_time = datetime.utcnow()
            call.execution_time_ms = (
                call.end_time - call.start_time
            ).total_seconds() * 1000

            if hasattr(result, 'error') and result.error:
                call.error = result.error
            if hasattr(result, "success") and result.success is False and not call.error:
                call.error = "Tool returned unsuccessful result"
            if hasattr(result, "success") and result.success is False:
                call.status = ToolCallStatus.FAILED

        except asyncio.TimeoutError:
            call.status = ToolCallStatus.FAILED
            call.error = f"Tool execution timed out after {self.config.timeout}s"
            call.end_time = datetime.utcnow()
            call.execution_time_ms = (
                call.end_time - call.start_time
            ).total_seconds() * 1000

        except Exception as e:
            call.status = ToolCallStatus.FAILED
            call.error = str(e)
            call.end_time = datetime.utcnow()
            call.execution_time_ms = (
                call.end_time - call.start_time
            ).total_seconds() * 1000
            logger.exception(f"Tool execution failed: {tool_name}")

        finally:
            if call.end_time is None:
                call.end_time = datetime.utcnow()
            if call.start_time is not None:
                call.execution_time_ms = (
                    call.end_time - call.start_time
                ).total_seconds() * 1000
            record_tool_call(
                tool_name,
                params=arguments,
                duration_ms=call.execution_time_ms,
                status=call.status.value,
                success=self._trace_success_from_call(call),
                error=call.error,
                call_id=call.id,
                cache_hit=self._trace_bool_from_result(call.result, "cache_hit"),
                fallback_used=self._trace_bool_from_result(call.result, "fallback_used"),
            )
            self._running_calls.pop(call_id, None)

        return call

    def _trace_success_from_call(self, call: ToolCall) -> bool:
        if call.status in {ToolCallStatus.FAILED, ToolCallStatus.CANCELLED}:
            return False
        if call.error:
            return False
        return call.status == ToolCallStatus.COMPLETED

    def _trace_bool_from_result(self, result: Any, key: str) -> Optional[bool]:
        if not isinstance(result, dict):
            return None
        value = result.get(key)
        metadata = result.get("metadata")
        if value is None and isinstance(metadata, dict):
            value = metadata.get(key)
        return None if value is None else bool(value)

    async def execute_batch(
        self,
        calls: List[Dict[str, Any]],
    ) -> List[ToolCall]:
        """
        批量执行工具调用

        Args:
            calls: 调用列表 [{"tool_name": "...", "arguments": {...}}]

        Returns:
            List[ToolCall]: 调用结果列表
        """
        if not self.config.enable_parallel:
            # 顺序执行
            results = []
            for call_spec in calls:
                result = await self.execute(
                    tool_name=call_spec["tool_name"],
                    arguments=call_spec.get("arguments", {}),
                    call_id=call_spec.get("id"),
                )
                results.append(result)
            return results

        # 并行执行
        tasks = []
        for call_spec in calls:
            task = self.execute(
                tool_name=call_spec["tool_name"],
                arguments=call_spec.get("arguments", {}),
                call_id=call_spec.get("id"),
            )
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常结果
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                call = ToolCall(
                    id=calls[i].get("id", f"error_{i}"),
                    tool_name=calls[i]["tool_name"],
                    arguments=calls[i].get("arguments", {}),
                    status=ToolCallStatus.FAILED,
                    error=str(result),
                    end_time=datetime.utcnow(),
                )
                processed_results.append(call)
            else:
                processed_results.append(result)

        return processed_results

    async def execute_with_retry(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        max_retries: Optional[int] = None,
    ) -> ToolCall:
        """
        带重试的工具执行

        Args:
            tool_name: 工具名称
            arguments: 工具参数
            max_retries: 最大重试次数

        Returns:
            ToolCall: 最终调用结果
        """
        max_retries = max_retries or self.config.max_retries
        last_call: Optional[ToolCall] = None

        for attempt in range(max_retries + 1):
            call = await self.execute(tool_name, arguments)

            if call.is_completed:
                return call

            last_call = call

            if attempt < max_retries:
                delay = self.config.retry_delay * (2 ** attempt)  # 指数退避
                logger.debug(
                    f"Retrying tool '{tool_name}' "
                    f"(attempt {attempt + 1}/{max_retries}) after {delay}s"
                )
                await asyncio.sleep(delay)

        return last_call or call

    def get_running_calls(self) -> List[ToolCall]:
        """获取正在运行的调用"""
        return list(self._running_calls.values())

    def cancel_call(self, call_id: str) -> bool:
        """取消正在运行的调用"""
        if call_id in self._running_calls:
            call = self._running_calls[call_id]
            call.status = ToolCallStatus.CANCELLED
            return True
        return False


class ToolSelector:
    """
    工具选择器
    根据上下文选择最合适的工具
    """

    def __init__(
        self,
        executor: Optional[ToolExecutor] = None,
        llm: Optional[Any] = None,
    ):
        self.executor = executor or ToolExecutor()
        self._llm = llm
        self._tool_selection_cache: Dict[str, List[str]] = {}

    def register_tool(self, tool: "BaseTool") -> None:
        """注册工具"""
        self.executor.register_tool(tool)

    async def select_tools(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        max_tools: int = 5,
    ) -> List[str]:
        """
        根据查询选择工具

        Args:
            query: 用户查询
            context: 上下文信息
            max_tools: 最大选择工具数

        Returns:
            List[str]: 选中的工具名称列表
        """
        available_tools = self.executor.list_tools()
        if not available_tools:
            return []

        # 如果有 LLM，使用 LLM 选择
        if self._llm:
            selected = await self._select_with_llm(query, available_tools, max_tools)
            record_selected_tools(selected)
            return selected

        # 使用关键词匹配
        selected = self._select_with_keywords(query, available_tools, max_tools)
        record_selected_tools(selected)
        return selected

    async def _select_with_llm(
        self,
        query: str,
        available_tools: List[str],
        max_tools: int,
    ) -> List[str]:
        """使用 LLM 选择工具"""
        # 构建工具描述
        tool_descriptions = []
        for name in available_tools:
            tool = self.executor.get_tool(name)
            if tool:
                tool_descriptions.append(f"- {name}: {tool.description}")

        prompt = f"""根据用户查询，选择需要调用的工具。

用户查询: {query}

可用工具:
{chr(10).join(tool_descriptions)}

请输出 JSON 格式，包含选中的工具名称列表（最多 {max_tools} 个）：
{{"selected_tools": ["tool1", "tool2"]}}

只输出 JSON，不要有其他内容。"""

        try:
            from app.core.llm.client import LLMMessage

            messages = [LLMMessage(role="user", content=prompt)]
            response = await self._llm.chat(messages)

            # 解析响应
            content = response.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            data = json.loads(content)
            selected = data.get("selected_tools", [])

            # 验证选中的工具
            return [t for t in selected if t in available_tools][:max_tools]

        except Exception as e:
            logger.warning(f"LLM tool selection failed: {e}, falling back to keywords")
            return self._select_with_keywords(query, available_tools, max_tools)

    def _select_with_keywords(
        self,
        query: str,
        available_tools: List[str],
        max_tools: int,
    ) -> List[str]:
        """使用关键词选择工具"""
        # 工具关键词映射
        keyword_map = {
            "poi_search": ["景点", "推荐", "好玩", "地方", "景区", "博物馆", "公园"],
            "weather": ["天气", "气温", "温度", "下雨", "气候", "防晒"],
            "route_plan": ["路线", "交通", "怎么去", "行程", "路线", "导航"],
            "budget_calc": ["预算", "费用", "花钱", "价格", "多少钱", "花费", "划算"],
            "poi_detail": ["详情", "介绍", "门票", "开放时间", "地址"],
        }

        selected = []
        query_lower = query.lower()

        for tool_name, keywords in keyword_map.items():
            if tool_name in available_tools:
                for keyword in keywords:
                    if keyword in query:
                        if tool_name not in selected:
                            selected.append(tool_name)
                        break

        return selected[:max_tools]


class ToolLoopExecutor:
    """
    工具循环执行器
    支持 LLM 调用工具直到任务完成
    """

    def __init__(
        self,
        executor: ToolExecutor,
        selector: ToolSelector,
        llm: Any,
        max_iterations: int = 10,
    ):
        self.executor = executor
        self.selector = selector
        self._llm = llm
        self.max_iterations = max_iterations

    async def execute_loop(
        self,
        messages: List[Any],
        system_prompt: str,
        tools: Optional[List[Any]] = None,
    ) -> str:
        """
        执行工具调用循环

        Args:
            messages: 对话消息列表
            system_prompt: 系统提示
            tools: 工具定义列表

        Returns:
            str: 最终响应内容
        """
        iteration = 0
        tool_results = []

        while iteration < self.max_iterations:
            iteration += 1
            logger.debug(f"Tool loop iteration {iteration}/{self.max_iterations}")

            # 调用 LLM
            try:
                response = await self._llm.chat(
                    messages=messages,
                    tools=tools,
                )
            except Exception as e:
                logger.error(f"LLM call failed: {e}")
                return f"抱歉，发生了错误: {e}"

            # 检查是否有工具调用
            if not response.tool_calls:
                # 没有工具调用，返回结果
                return response.content

            # 执行工具调用
            tool_calls = []
            for tc in response.tool_calls:
                call = await self.executor.execute(
                    tool_name=tc.name,
                    arguments=json.loads(tc.arguments),
                    call_id=tc.id,
                )
                tool_calls.append(call)

                # 添加工具结果到消息
                if call.is_completed:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(call.result, ensure_ascii=False, default=str),
                    })
                    tool_results.append({
                        "tool": tc.name,
                        "result": call.result,
                    })
                else:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": f"Error: {call.error}",
                    })

            # 检查是否所有工具都失败了
            if all(tc.is_failed for tc in tool_calls):
                return "抱歉，所有工具执行都失败了。"

        # 达到最大迭代次数
        return "抱歉，工具调用次数过多，请重新描述您的问题。"


# ========== 全局实例 ==========

_tool_executor: Optional[ToolExecutor] = None


def get_tool_executor() -> ToolExecutor:
    """获取工具执行器"""
    global _tool_executor
    if _tool_executor is None:
        _tool_executor = ToolExecutor()
    return _tool_executor


def init_tool_executor(config: Optional[ToolExecutorConfig] = None) -> ToolExecutor:
    """初始化工具执行器"""
    global _tool_executor
    _tool_executor = ToolExecutor(config=config)
    return _tool_executor
