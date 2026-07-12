"""
Tool Strategy - 工具策略模式
提供统一的工具调用接口，支持多种工具执行策略
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from app.core.logger import get_logger
from app.core.tracing import record_tool_call

if TYPE_CHECKING:
    from app.tools.base import BaseTool

logger = get_logger(__name__)


class ToolStrategyType(str, Enum):
    """工具策略类型"""
    DIRECT = "direct"              # 直接执行
    RETRY = "retry"                # 重试策略
    TIMEOUT = "timeout"             # 超时策略
    FALLBACK = "fallback"          # 降级策略
    CACHED = "cached"               # 缓存策略
    BATCH = "batch"                # 批量策略
    PARALLEL = "parallel"          # 并行策略
    CIRCUIT_BREAKER = "circuit_breaker"  # 熔断策略
    COMPOSITE = "composite"        # 组合策略


@dataclass
class ToolExecutionContext:
    """工具执行上下文"""
    tool_name: str
    params: Dict[str, Any]
    execution_id: str = ""
    start_time: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.execution_id:
            import uuid
            self.execution_id = str(uuid.uuid4())[:8]


@dataclass
class ToolExecutionResult:
    """工具执行结果"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    strategy_used: str = "direct"
    attempts: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)


class ToolStrategy(ABC):
    """
    工具策略基类
    定义工具执行的策略接口
    """

    @property
    @abstractmethod
    def strategy_type(self) -> ToolStrategyType:
        """策略类型"""
        pass

    @abstractmethod
    async def execute(
        self,
        tool: BaseTool,
        params: Dict[str, Any],
        context: Optional[ToolExecutionContext] = None,
    ) -> ToolExecutionResult:
        """执行工具"""
        pass

    async def before_execute(
        self,
        tool: BaseTool,
        params: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> None:
        """执行前钩子"""
        pass

    async def after_execute(
        self,
        tool: BaseTool,
        result: ToolExecutionResult,
        context: ToolExecutionContext,
    ) -> None:
        """执行后钩子"""
        pass


class DirectToolStrategy(ToolStrategy):
    """直接执行策略"""

    @property
    def strategy_type(self) -> ToolStrategyType:
        return ToolStrategyType.DIRECT

    async def execute(
        self,
        tool: BaseTool,
        params: Dict[str, Any],
        context: Optional[ToolExecutionContext] = None,
    ) -> ToolExecutionResult:
        ctx = context or ToolExecutionContext(
            tool_name=tool.name,
            params=params,
        )

        await self.before_execute(tool, params, ctx)
        start = datetime.utcnow()

        try:
            result = await tool.execute(**params)

            execution_time = (datetime.utcnow() - start).total_seconds() * 1000

            tool_result = ToolExecutionResult(
                success=result.success,
                data=result.data,
                error=result.error,
                execution_time_ms=execution_time,
                strategy_used=self.strategy_type.value,
                metadata={"result_metadata": result.metadata} if result.metadata else {},
            )

            await self.after_execute(tool, tool_result, ctx)
            return tool_result

        except Exception as e:
            execution_time = (datetime.utcnow() - start).total_seconds() * 1000
            tool_result = ToolExecutionResult(
                success=False,
                error=str(e),
                execution_time_ms=execution_time,
                strategy_used=self.strategy_type.value,
            )
            await self.after_execute(tool, tool_result, ctx)
            return tool_result


class RetryToolStrategy(ToolStrategy):
    """重试策略"""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        exponential_backoff: bool = True,
        retry_on_errors: Optional[List[type]] = None,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_backoff = exponential_backoff
        self.retry_on_errors = retry_on_errors or [Exception]

    @property
    def strategy_type(self) -> ToolStrategyType:
        return ToolStrategyType.RETRY

    async def execute(
        self,
        tool: BaseTool,
        params: Dict[str, Any],
        context: Optional[ToolExecutionContext] = None,
    ) -> ToolExecutionResult:
        ctx = context or ToolExecutionContext(
            tool_name=tool.name,
            params=params,
        )

        last_error = None
        total_execution_time = 0.0

        for attempt in range(self.max_retries + 1):
            await self.before_execute(tool, params, ctx)

            start = datetime.utcnow()

            try:
                result = await tool.execute(**params)
                execution_time = (datetime.utcnow() - start).total_seconds() * 1000
                total_execution_time += execution_time

                if result.success:
                    tool_result = ToolExecutionResult(
                        success=True,
                        data=result.data,
                        execution_time_ms=total_execution_time,
                        strategy_used=self.strategy_type.value,
                        attempts=attempt + 1,
                        metadata={"result_metadata": result.metadata} if result.metadata else {},
                    )
                    await self.after_execute(tool, tool_result, ctx)
                    return tool_result

                last_error = result.error

            except Exception as e:
                execution_time = (datetime.utcnow() - start).total_seconds() * 1000
                total_execution_time += execution_time

                should_retry = any(isinstance(e, err_type) for err_type in self.retry_on_errors)
                last_error = str(e)

                if not should_retry or attempt >= self.max_retries:
                    tool_result = ToolExecutionResult(
                        success=False,
                        error=str(e),
                        execution_time_ms=total_execution_time,
                        strategy_used=self.strategy_type.value,
                        attempts=attempt + 1,
                    )
                    await self.after_execute(tool, tool_result, ctx)
                    return tool_result

            if attempt < self.max_retries:
                delay = self._calculate_delay(attempt)
                logger.debug(f"Retrying tool '{tool.name}' after {delay}s (attempt {attempt + 1})")
                await asyncio.sleep(delay)

        return ToolExecutionResult(
            success=False,
            error=last_error or "Max retries exceeded",
            execution_time_ms=total_execution_time,
            strategy_used=self.strategy_type.value,
            attempts=self.max_retries + 1,
        )

    def _calculate_delay(self, attempt: int) -> float:
        """计算重试延迟"""
        if self.exponential_backoff:
            return min(self.base_delay * (2 ** attempt), self.max_delay)
        return min(self.base_delay, self.max_delay)


class TimeoutToolStrategy(ToolStrategy):
    """超时策略"""

    def __init__(self, timeout_seconds: float = 30.0):
        self.timeout_seconds = timeout_seconds

    @property
    def strategy_type(self) -> ToolStrategyType:
        return ToolStrategyType.TIMEOUT

    async def execute(
        self,
        tool: BaseTool,
        params: Dict[str, Any],
        context: Optional[ToolExecutionContext] = None,
    ) -> ToolExecutionResult:
        ctx = context or ToolExecutionContext(
            tool_name=tool.name,
            params=params,
        )

        await self.before_execute(tool, params, ctx)
        start = datetime.utcnow()

        try:
            result = await asyncio.wait_for(
                tool.execute(**params),
                timeout=self.timeout_seconds,
            )
            execution_time = (datetime.utcnow() - start).total_seconds() * 1000

            tool_result = ToolExecutionResult(
                success=result.success,
                data=result.data,
                error=result.error,
                execution_time_ms=execution_time,
                strategy_used=self.strategy_type.value,
                metadata={"result_metadata": result.metadata} if result.metadata else {},
            )

            await self.after_execute(tool, tool_result, ctx)
            return tool_result

        except asyncio.TimeoutError:
            execution_time = (datetime.utcnow() - start).total_seconds() * 1000
            tool_result = ToolExecutionResult(
                success=False,
                error=f"Execution timed out after {self.timeout_seconds}s",
                execution_time_ms=execution_time,
                strategy_used=self.strategy_type.value,
            )
            await self.after_execute(tool, tool_result, ctx)
            return tool_result

        except Exception as e:
            execution_time = (datetime.utcnow() - start).total_seconds() * 1000
            tool_result = ToolExecutionResult(
                success=False,
                error=str(e),
                execution_time_ms=execution_time,
                strategy_used=self.strategy_type.value,
            )
            await self.after_execute(tool, tool_result, ctx)
            return tool_result


class FallbackToolStrategy(ToolStrategy):
    """降级策略"""

    def __init__(
        self,
        fallback_tool: Optional[BaseTool] = None,
        fallback_func: Optional[Callable] = None,
    ):
        self.fallback_tool = fallback_tool
        self.fallback_func = fallback_func

    @property
    def strategy_type(self) -> ToolStrategyType:
        return ToolStrategyType.FALLBACK

    async def execute(
        self,
        tool: BaseTool,
        params: Dict[str, Any],
        context: Optional[ToolExecutionContext] = None,
    ) -> ToolExecutionResult:
        ctx = context or ToolExecutionContext(
            tool_name=tool.name,
            params=params,
        )

        await self.before_execute(tool, params, ctx)
        start = datetime.utcnow()

        try:
            result = await tool.execute(**params)

            if result.success:
                execution_time = (datetime.utcnow() - start).total_seconds() * 1000
                tool_result = ToolExecutionResult(
                    success=True,
                    data=result.data,
                    execution_time_ms=execution_time,
                    strategy_used=self.strategy_type.value,
                )
                await self.after_execute(tool, tool_result, ctx)
                return tool_result

        except Exception as e:
            logger.warning(f"Tool '{tool.name}' failed: {e}")

        # 尝试降级
        return await self._execute_fallback(tool, params, ctx, start)

    async def _execute_fallback(
        self,
        original_tool: BaseTool,
        params: Dict[str, Any],
        context: ToolExecutionContext,
        start: datetime,
    ) -> ToolExecutionResult:
        """执行降级逻辑"""
        if self.fallback_tool:
            logger.info(f"Falling back to tool: {self.fallback_tool.name}")
            try:
                result = await self.fallback_tool.execute(**params)
                execution_time = (datetime.utcnow() - start).total_seconds() * 1000
                record_tool_call(
                    original_tool.name,
                    params=params,
                    duration_ms=execution_time,
                    status="completed" if result.success else "failed",
                    success=result.success,
                    error=result.error,
                    cache_hit=False,
                    fallback_used=True,
                )

                return ToolExecutionResult(
                    success=result.success,
                    data=result.data,
                    error=result.error,
                    execution_time_ms=execution_time,
                    strategy_used=self.strategy_type.value,
                    metadata={"fallback": True},
                )
            except Exception as e:
                execution_time = (datetime.utcnow() - start).total_seconds() * 1000
                record_tool_call(
                    original_tool.name,
                    params=params,
                    duration_ms=execution_time,
                    status="failed",
                    success=False,
                    error=e,
                    cache_hit=False,
                    fallback_used=True,
                )
                return ToolExecutionResult(
                    success=False,
                    error=f"Both primary and fallback failed. Last error: {e}",
                    execution_time_ms=execution_time,
                    strategy_used=self.strategy_type.value,
                )

        if self.fallback_func:
            logger.info("Executing fallback function")
            try:
                if asyncio.iscoroutinefunction(self.fallback_func):
                    result = await self.fallback_func(original_tool.name, params)
                else:
                    result = self.fallback_func(original_tool.name, params)

                execution_time = (datetime.utcnow() - start).total_seconds() * 1000
                record_tool_call(
                    original_tool.name,
                    params=params,
                    duration_ms=execution_time,
                    status="completed",
                    success=True,
                    cache_hit=False,
                    fallback_used=True,
                )

                return ToolExecutionResult(
                    success=True,
                    data=result,
                    execution_time_ms=execution_time,
                    strategy_used=self.strategy_type.value,
                    metadata={"fallback": True},
                )
            except Exception as e:
                execution_time = (datetime.utcnow() - start).total_seconds() * 1000
                record_tool_call(
                    original_tool.name,
                    params=params,
                    duration_ms=execution_time,
                    status="failed",
                    success=False,
                    error=e,
                    cache_hit=False,
                    fallback_used=True,
                )
                return ToolExecutionResult(
                    success=False,
                    error=f"Both primary and fallback failed. Last error: {e}",
                    execution_time_ms=execution_time,
                    strategy_used=self.strategy_type.value,
                )

        # 无降级方案
        execution_time = (datetime.utcnow() - start).total_seconds() * 1000
        record_tool_call(
            original_tool.name,
            params=params,
            duration_ms=execution_time,
            status="failed",
            success=False,
            error="No fallback available",
            cache_hit=False,
            fallback_used=False,
        )
        return ToolExecutionResult(
            success=False,
            error="No fallback available",
            execution_time_ms=execution_time,
            strategy_used=self.strategy_type.value,
        )


class CachedToolStrategy(ToolStrategy):
    """缓存策略"""

    def __init__(
        self,
        cache: Optional[Any] = None,
        ttl: int = 300,
        cache_key_func: Optional[Callable] = None,
    ):
        self.cache = cache
        self.ttl = ttl
        self.cache_key_func = cache_key_func or self._default_cache_key

    @property
    def strategy_type(self) -> ToolStrategyType:
        return ToolStrategyType.CACHED

    async def execute(
        self,
        tool: BaseTool,
        params: Dict[str, Any],
        context: Optional[ToolExecutionContext] = None,
    ) -> ToolExecutionResult:
        ctx = context or ToolExecutionContext(
            tool_name=tool.name,
            params=params,
        )

        cache_key = self.cache_key_func(tool.name, params)

        # 尝试从缓存获取
        if self.cache:
            cached_value = self.cache.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache hit for tool '{tool.name}'")
                record_tool_call(
                    tool.name,
                    params=params,
                    duration_ms=0,
                    status="completed",
                    success=True,
                    cache_hit=True,
                    fallback_used=False,
                )
                return ToolExecutionResult(
                    success=True,
                    data=cached_value,
                    execution_time_ms=0,
                    strategy_used=self.strategy_type.value,
                    metadata={"cache_hit": True},
                )

        # 执行工具
        await self.before_execute(tool, params, ctx)
        start = datetime.utcnow()

        try:
            result = await tool.execute(**params)
            execution_time = (datetime.utcnow() - start).total_seconds() * 1000

            # 缓存结果
            if self.cache and result.success:
                self.cache.set(cache_key, result.data, ttl=self.ttl)

            tool_result = ToolExecutionResult(
                success=result.success,
                data=result.data,
                error=result.error,
                execution_time_ms=execution_time,
                strategy_used=self.strategy_type.value,
                metadata={"cache_hit": False},
            )
            record_tool_call(
                tool.name,
                params=params,
                duration_ms=execution_time,
                status="completed" if result.success else "failed",
                success=result.success,
                error=result.error,
                cache_hit=False,
                fallback_used=False,
            )

            await self.after_execute(tool, tool_result, ctx)
            return tool_result

        except Exception as e:
            execution_time = (datetime.utcnow() - start).total_seconds() * 1000
            tool_result = ToolExecutionResult(
                success=False,
                error=str(e),
                execution_time_ms=execution_time,
                strategy_used=self.strategy_type.value,
            )
            await self.after_execute(tool, tool_result, ctx)
            return tool_result

    def _default_cache_key(self, tool_name: str, params: Dict[str, Any]) -> str:
        """默认缓存键生成"""
        import json
        param_str = json.dumps(params, sort_keys=True, default=str)
        return f"tool:{tool_name}:{hash(param_str)}"


class ParallelToolStrategy(ToolStrategy):
    """并行执行策略"""

    def __init__(self, max_concurrent: int = 5):
        self.max_concurrent = max_concurrent
        self._semaphore: Optional[asyncio.Semaphore] = None

    @property
    def strategy_type(self) -> ToolStrategyType:
        return ToolStrategyType.PARALLEL

    @property
    def semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self._semaphore

    async def execute(
        self,
        tool: BaseTool,
        params: Dict[str, Any],
        context: Optional[ToolExecutionContext] = None,
    ) -> ToolExecutionResult:
        ctx = context or ToolExecutionContext(
            tool_name=tool.name,
            params=params,
        )

        await self.before_execute(tool, params, ctx)
        start = datetime.utcnow()

        async with self.semaphore:
            try:
                result = await tool.execute(**params)
                execution_time = (datetime.utcnow() - start).total_seconds() * 1000

                tool_result = ToolExecutionResult(
                    success=result.success,
                    data=result.data,
                    error=result.error,
                    execution_time_ms=execution_time,
                    strategy_used=self.strategy_type.value,
                    metadata={"concurrency_limited": True},
                )

                await self.after_execute(tool, tool_result, ctx)
                return tool_result

            except Exception as e:
                execution_time = (datetime.utcnow() - start).total_seconds() * 1000
                tool_result = ToolExecutionResult(
                    success=False,
                    error=str(e),
                    execution_time_ms=execution_time,
                    strategy_used=self.strategy_type.value,
                )
                await self.after_execute(tool, tool_result, ctx)
                return tool_result


class CircuitBreakerToolStrategy(ToolStrategy):
    """熔断策略"""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._failure_count = 0
        self._last_failure_time: Optional[datetime] = None
        self._state = "closed"  # closed, open, half_open
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

    @property
    def strategy_type(self) -> ToolStrategyType:
        return ToolStrategyType.CIRCUIT_BREAKER

    @property
    def state(self) -> str:
        return self._state

    async def execute(
        self,
        tool: BaseTool,
        params: Dict[str, Any],
        context: Optional[ToolExecutionContext] = None,
    ) -> ToolExecutionResult:
        ctx = context or ToolExecutionContext(
            tool_name=tool.name,
            params=params,
        )

        # 检查熔断状态
        should_allow, reason = await self._check_circuit_state()

        if not should_allow:
            return ToolExecutionResult(
                success=False,
                error=f"Circuit breaker is {self._state}: {reason}",
                execution_time_ms=0,
                strategy_used=self.strategy_type.value,
                metadata={"circuit_state": self._state, "reason": reason},
            )

        await self.before_execute(tool, params, ctx)
        start = datetime.utcnow()

        try:
            result = await tool.execute(**params)
            execution_time = (datetime.utcnow() - start).total_seconds() * 1000

            if result.success:
                await self._on_success()
                tool_result = ToolExecutionResult(
                    success=True,
                    data=result.data,
                    execution_time_ms=execution_time,
                    strategy_used=self.strategy_type.value,
                )
            else:
                await self._on_failure()
                tool_result = ToolExecutionResult(
                    success=False,
                    error=result.error,
                    execution_time_ms=execution_time,
                    strategy_used=self.strategy_type.value,
                )

            await self.after_execute(tool, tool_result, ctx)
            return tool_result

        except Exception as e:
            execution_time = (datetime.utcnow() - start).total_seconds() * 1000
            await self._on_failure()

            tool_result = ToolExecutionResult(
                success=False,
                error=str(e),
                execution_time_ms=execution_time,
                strategy_used=self.strategy_type.value,
            )
            await self.after_execute(tool, tool_result, ctx)
            return tool_result

    async def _check_circuit_state(self) -> tuple[bool, str]:
        """检查熔断状态"""
        async with self._lock:
            if self._state == "closed":
                return True, ""

            if self._state == "open":
                # 检查是否应该转换到 half_open
                if self._last_failure_time:
                    elapsed = (datetime.utcnow() - self._last_failure_time).total_seconds()
                    if elapsed >= self.recovery_timeout:
                        self._state = "half_open"
                        self._half_open_calls = 0
                        return True, "Transitioning to half-open"

                return False, f"Circuit is open. Wait {self.recovery_timeout}s"

            if self._state == "half_open":
                if self._half_open_calls < self.half_open_max_calls:
                    self._half_open_calls += 1
                    return True, "Half-open: testing"

                return False, "Half-open: max test calls reached"

            return True, ""

    async def _on_success(self) -> None:
        """记录成功"""
        async with self._lock:
            if self._state == "half_open":
                self._failure_count = 0
                self._state = "closed"
                logger.info("Circuit breaker closed after successful test")

    async def _on_failure(self) -> None:
        """记录失败"""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = datetime.utcnow()

            if self._state == "half_open":
                self._state = "open"
                logger.warning("Circuit breaker reopened after failed test in half-open state")

            elif self._failure_count >= self.failure_threshold:
                self._state = "open"
                logger.warning(f"Circuit breaker opened after {self._failure_count} failures")


class CompositeToolStrategy(ToolStrategy):
    """组合策略"""

    def __init__(self, strategies: Optional[List[ToolStrategy]] = None):
        self.strategies = strategies or []

    @property
    def strategy_type(self) -> ToolStrategyType:
        return ToolStrategyType.COMPOSITE

    def add_strategy(self, strategy: ToolStrategy) -> "CompositeToolStrategy":
        """添加策略"""
        self.strategies.append(strategy)
        return self

    async def execute(
        self,
        tool: BaseTool,
        params: Dict[str, Any],
        context: Optional[ToolExecutionContext] = None,
    ) -> ToolExecutionResult:
        ctx = context or ToolExecutionContext(
            tool_name=tool.name,
            params=params,
        )

        current_result: Optional[ToolExecutionResult] = None

        for strategy in self.strategies:
            if current_result and current_result.success:
                break

            current_result = await strategy.execute(tool, params, ctx)

        if current_result is None:
            current_result = ToolExecutionResult(
                success=False,
                error="No strategies available",
                strategy_used=self.strategy_type.value,
            )

        return current_result


# ========== 工具策略管理器 ==========

class ToolStrategyManager:
    """
    工具策略管理器
    管理和调度工具执行策略
    """

    def __init__(self):
        self._strategies: Dict[ToolStrategyType, ToolStrategy] = {}
        self._tool_strategies: Dict[str, ToolStrategyType] = {}  # tool_name -> strategy_type

        # 注册默认策略
        self._register_default_strategies()

    def _register_default_strategies(self) -> None:
        """注册默认策略"""
        self.register_strategy(ToolStrategyType.DIRECT, DirectToolStrategy())
        self.register_strategy(ToolStrategyType.RETRY, RetryToolStrategy())
        self.register_strategy(ToolStrategyType.TIMEOUT, TimeoutToolStrategy())
        self.register_strategy(ToolStrategyType.PARALLEL, ParallelToolStrategy())
        self.register_strategy(ToolStrategyType.CACHED, CachedToolStrategy())

    def register_strategy(self, strategy_type: ToolStrategyType, strategy: ToolStrategy) -> None:
        """注册策略"""
        self._strategies[strategy_type] = strategy

    def get_strategy(self, strategy_type: ToolStrategyType) -> Optional[ToolStrategy]:
        """获取策略"""
        return self._strategies.get(strategy_type)

    def set_tool_strategy(self, tool_name: str, strategy_type: ToolStrategyType) -> None:
        """为工具设置策略"""
        self._tool_strategies[tool_name] = strategy_type

    def get_tool_strategy(self, tool_name: str) -> ToolStrategyType:
        """获取工具的策略类型"""
        return self._tool_strategies.get(tool_name, ToolStrategyType.DIRECT)

    async def execute(
        self,
        tool: BaseTool,
        params: Dict[str, Any],
        strategy_type: Optional[ToolStrategyType] = None,
        context: Optional[ToolExecutionContext] = None,
    ) -> ToolExecutionResult:
        """执行工具"""
        strategy_type = strategy_type or self.get_tool_strategy(tool.name)
        strategy = self.get_strategy(strategy_type)

        if strategy is None:
            strategy = DirectToolStrategy()

        return await strategy.execute(tool, params, context)

    def create_composite_strategy(
        self,
        *strategy_types: ToolStrategyType,
    ) -> CompositeToolStrategy:
        """创建组合策略"""
        strategies = []
        for st in strategy_types:
            strategy = self.get_strategy(st)
            if strategy:
                strategies.append(strategy)

        return CompositeToolStrategy(strategies)


# 全局策略管理器
_tool_strategy_manager: Optional[ToolStrategyManager] = None


def get_tool_strategy_manager() -> ToolStrategyManager:
    """获取工具策略管理器"""
    global _tool_strategy_manager
    if _tool_strategy_manager is None:
        _tool_strategy_manager = ToolStrategyManager()
    return _tool_strategy_manager
