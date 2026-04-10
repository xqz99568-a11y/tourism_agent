"""
降级链模块
支持主模型失败时自动切换备用模型
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TypeVar

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from app.core.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class FallbackError(Exception):
    """降级链错误"""

    def __init__(self, message: str, attempts: int = 0):
        super().__init__(message)
        self.message = message
        self.attempts = attempts


class FallbackStrategy(str, Enum):
    """降级策略"""
    SEQUENTIAL = "sequential"      # 顺序降级：依次尝试每个模型
    PARALLEL = "parallel"          # 并行降级：同时尝试多个模型
    PARALLEL_WITH_TIMEOUT = "parallel_with_timeout"  # 带超时的并行


@dataclass
class FallbackConfig:
    """降级配置"""
    max_retries: int = 3                    # 最大重试次数
    retry_delay: float = 1.0                # 重试延迟（秒）
    timeout: float = 30.0                   # 单次调用超时（秒）
    enable_circuit_breaker: bool = True    # 是否启用熔断器
    circuit_breaker_threshold: int = 5    # 熔断器阈值
    circuit_breaker_timeout: float = 60.0  # 熔断器恢复时间（秒）


@dataclass
class ModelEndpoint:
    """模型端点"""
    name: str                              # 模型名称
    provider: str                           # 提供商
    priority: int = 0                       # 优先级（数字越大优先级越高）
    enabled: bool = True                    # 是否启用
    is_healthy: bool = True                # 健康状态
    last_failure: Optional[float] = None   # 上次失败时间
    failure_count: int = 0                 # 连续失败次数

    def mark_failure(self) -> None:
        """标记失败"""
        self.last_failure = time.time()
        self.failure_count += 1
        if self.failure_count >= 5:
            self.is_healthy = False

    def mark_success(self) -> None:
        """标记成功"""
        self.failure_count = 0
        self.is_healthy = True

    @property
    def should_skip(self) -> bool:
        """是否应该跳过"""
        if not self.enabled:
            return True

        # 如果熔断器启用，检查是否在冷却期
        if self.last_failure:
            cooldown = 60  # 60 秒冷却
            if time.time() - self.last_failure < cooldown:
                return True

        return False


@dataclass
class FallbackAttempt:
    """降级尝试记录"""
    model: str
    provider: str
    success: bool
    latency_ms: float
    error: Optional[str] = None
    attempt_number: int = 1


@dataclass
class FallbackResult:
    """降级链执行结果"""
    success: bool
    response: Any = None
    final_model: Optional[str] = None
    final_provider: Optional[str] = None
    attempts: List[FallbackAttempt] = field(default_factory=list)
    total_latency_ms: float = 0.0
    error: Optional[str] = None
    from_cache: bool = False

    @property
    def attempt_count(self) -> int:
        """尝试次数"""
        return len(self.attempts)

    @property
    def model_tried(self) -> List[str]:
        """尝试过的模型列表"""
        return [a.model for a in self.attempts]


class CircuitBreaker:
    """
    熔断器
    防止对持续失败的模型进行无效调用
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_attempts: int = 1,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_attempts = half_open_attempts

        # 状态
        self._failure_count: Dict[str, int] = {}
        self._last_failure_time: Dict[str, float] = {}
        self._state: Dict[str, str] = {}  # closed, open, half_open

    def is_available(self, model_key: str) -> bool:
        """检查模型是否可用"""
        state = self._state.get(model_key, "closed")

        if state == "closed":
            return True

        if state == "open":
            # 检查是否超时
            last_failure = self._last_failure_time.get(model_key, 0)
            if time.time() - last_failure >= self.recovery_timeout:
                # 进入半开状态
                self._state[model_key] = "half_open"
                return True
            return False

        # 半开状态，允许请求
        return True

    def record_success(self, model_key: str) -> None:
        """记录成功"""
        self._failure_count[model_key] = 0
        self._state[model_key] = "closed"

    def record_failure(self, model_key: str) -> None:
        """记录失败"""
        self._failure_count[model_key] = self._failure_count.get(model_key, 0) + 1
        self._last_failure_time[model_key] = time.time()

        if self._failure_count[model_key] >= self.failure_threshold:
            self._state[model_key] = "open"
            logger.warning(f"Circuit breaker opened for {model_key}")

    def get_state(self, model_key: str) -> str:
        """获取模型状态"""
        return self._state.get(model_key, "closed")

    def reset(self, model_key: Optional[str] = None) -> None:
        """重置熔断器"""
        if model_key:
            self._failure_count.pop(model_key, None)
            self._last_failure_time.pop(model_key, None)
            self._state.pop(model_key, None)
        else:
            self._failure_count.clear()
            self._last_failure_time.clear()
            self._state.clear()


class FallbackChain:
    """
    降级链
    支持多种降级策略
    """

    def __init__(
        self,
        config: Optional[FallbackConfig] = None,
        strategy: FallbackStrategy = FallbackStrategy.SEQUENTIAL,
    ):
        self.config = config or FallbackConfig()
        self.strategy = strategy
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=self.config.circuit_breaker_threshold,
            recovery_timeout=self.config.circuit_breaker_timeout,
        )

        # 模型端点列表
        self._endpoints: List[ModelEndpoint] = []
        self._endpoint_map: Dict[str, ModelEndpoint] = {}

        # 统计信息
        self._total_requests = 0
        self._total_fallbacks = 0

    def add_endpoint(
        self,
        name: str,
        provider: str,
        priority: int = 0,
        enabled: bool = True,
    ) -> None:
        """添加模型端点"""
        endpoint = ModelEndpoint(
            name=name,
            provider=provider,
            priority=priority,
            enabled=enabled,
        )
        self._endpoints.append(endpoint)
        self._endpoint_map[f"{provider}:{name}"] = endpoint

        # 按优先级排序
        self._endpoints.sort(key=lambda x: x.priority, reverse=True)

    def remove_endpoint(self, name: str, provider: str) -> bool:
        """移除模型端点"""
        key = f"{provider}:{name}"
        if key in self._endpoint_map:
            endpoint = self._endpoint_map[key]
            self._endpoints.remove(endpoint)
            del self._endpoint_map[key]
            return True
        return False

    def get_available_endpoints(self) -> List[ModelEndpoint]:
        """获取可用的端点列表"""
        return [
            ep for ep in self._endpoints
            if not ep.should_skip and self.circuit_breaker.is_available(f"{ep.provider}:{ep.name}")
        ]

    async def execute(
        self,
        func: Callable[..., T],
        *args,
        **kwargs,
    ) -> FallbackResult:
        """
        执行带降级的函数

        Args:
            func: 要执行的函数（接收 provider, model 参数）
            *args, **kwargs: 传递给 func 的其他参数

        Returns:
            FallbackResult: 执行结果
        """
        self._total_requests += 1
        start_time = time.time()
        attempts: List[FallbackAttempt] = []
        last_error: Optional[str] = None

        available_endpoints = self.get_available_endpoints()

        if not available_endpoints:
            return FallbackResult(
                success=False,
                error="No available endpoints",
                attempts=attempts,
                total_latency_ms=0,
            )

        # 如果启用熔断器，先过滤
        if self.config.enable_circuit_breaker:
            available_endpoints = [
                ep for ep in available_endpoints
                if self.circuit_breaker.is_available(f"{ep.provider}:{ep.name}")
            ]

        try:
            if self.strategy == FallbackStrategy.SEQUENTIAL:
                # 顺序降级
                for i, endpoint in enumerate(available_endpoints):
                    attempt = await self._try_endpoint(
                        endpoint, func, *args, **kwargs
                    )
                    attempt.attempt_number = i + 1
                    attempts.append(attempt)

                    if attempt.success:
                        self.circuit_breaker.record_success(f"{endpoint.provider}:{endpoint.name}")
                        endpoint.mark_success()

                        total_time = (time.time() - start_time) * 1000
                        return FallbackResult(
                            success=True,
                            response=attempt,
                            final_model=endpoint.name,
                            final_provider=endpoint.provider,
                            attempts=attempts,
                            total_latency_ms=total_time,
                        )

                    last_error = attempt.error
                    self.circuit_breaker.record_failure(f"{endpoint.provider}:{endpoint.name}")
                    endpoint.mark_failure()

                    # 等待后重试
                    if i < len(available_endpoints) - 1:
                        await asyncio.sleep(self.config.retry_delay * (i + 1))

            elif self.strategy == FallbackStrategy.PARALLEL_WITH_TIMEOUT:
                # 并行降级（带超时）
                result = await asyncio.wait_for(
                    self._parallel_execute(
                        available_endpoints, func, *args, **kwargs
                    ),
                    timeout=self.config.timeout * len(available_endpoints),
                )
                return result

            else:
                # 简单并行
                result = await self._parallel_execute(
                    available_endpoints, func, *args, **kwargs
                )
                return result

        except asyncio.TimeoutError:
            last_error = "All endpoints timed out"

        except Exception as e:
            last_error = str(e)
            logger.exception(f"Fallback chain execution failed: {e}")

        total_time = (time.time() - start_time) * 1000

        if len(attempts) > 1:
            self._total_fallbacks += 1

        return FallbackResult(
            success=False,
            attempts=attempts,
            total_latency_ms=total_time,
            error=last_error,
        )

    async def _try_endpoint(
        self,
        endpoint: ModelEndpoint,
        func: Callable[..., T],
        *args,
        **kwargs,
    ) -> FallbackAttempt:
        """尝试单个端点"""
        start_time = time.time()
        model_key = f"{endpoint.provider}:{endpoint.name}"

        try:
            # 添加 provider 和 model 到参数
            enhanced_kwargs = {
                **kwargs,
                "provider": endpoint.provider,
                "model": endpoint.name,
            }

            result = await asyncio.wait_for(
                func(*args, **enhanced_kwargs),
                timeout=self.config.timeout,
            )

            latency = (time.time() - start_time) * 1000

            return FallbackAttempt(
                model=endpoint.name,
                provider=endpoint.provider,
                success=True,
                latency_ms=latency,
                response=result,
            )

        except asyncio.TimeoutError:
            latency = (time.time() - start_time) * 1000
            self.circuit_breaker.record_failure(model_key)

            return FallbackAttempt(
                model=endpoint.name,
                provider=endpoint.provider,
                success=False,
                latency_ms=latency,
                error="Timeout",
            )

        except Exception as e:
            latency = (time.time() - start_time) * 1000
            self.circuit_breaker.record_failure(model_key)

            return FallbackAttempt(
                model=endpoint.name,
                provider=endpoint.provider,
                success=False,
                latency_ms=latency,
                error=str(e),
            )

    async def _parallel_execute(
        self,
        endpoints: List[ModelEndpoint],
        func: Callable[..., T],
        *args,
        **kwargs,
    ) -> FallbackResult:
        """并行执行所有端点"""
        start_time = time.time()
        tasks = [
            self._try_endpoint(endpoint, func, *args, **kwargs)
            for endpoint in endpoints
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        attempts: List[FallbackAttempt] = []
        successful: Optional[FallbackAttempt] = None

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                attempts.append(FallbackAttempt(
                    model=endpoints[i].name,
                    provider=endpoints[i].provider,
                    success=False,
                    latency_ms=0,
                    error=str(result),
                ))
            else:
                attempts.append(result)
                if result.success and successful is None:
                    successful = result

        total_time = (time.time() - start_time) * 1000

        if successful:
            return FallbackResult(
                success=True,
                response=successful.response if hasattr(successful, 'response') else None,
                final_model=successful.model,
                final_provider=successful.provider,
                attempts=attempts,
                total_latency_ms=total_time,
            )

        return FallbackResult(
            success=False,
            attempts=attempts,
            total_latency_ms=total_time,
            error="All endpoints failed",
        )

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        success_rate = (
            (self._total_requests - self._total_fallbacks) / self._total_requests
            if self._total_requests > 0 else 0
        )

        return {
            "total_requests": self._total_requests,
            "total_fallbacks": self._total_fallbacks,
            "fallback_rate": f"{self._total_fallbacks / self._total_requests:.2%}" if self._total_requests > 0 else "0%",
            "success_rate": f"{success_rate:.2%}" if self._total_requests > 0 else "0%",
            "endpoints": [
                {
                    "name": ep.name,
                    "provider": ep.provider,
                    "priority": ep.priority,
                    "enabled": ep.enabled,
                    "is_healthy": ep.is_healthy,
                    "failure_count": ep.failure_count,
                    "circuit_state": self.circuit_breaker.get_state(f"{ep.provider}:{ep.name}"),
                }
                for ep in self._endpoints
            ],
            "circuit_breaker": {
                "enabled": self.config.enable_circuit_breaker,
                "threshold": self.config.circuit_breaker_threshold,
                "timeout": self.config.circuit_breaker_timeout,
            },
        }

    def reset(self) -> None:
        """重置降级链"""
        self.circuit_breaker.reset()
        for endpoint in self._endpoints:
            endpoint.failure_count = 0
            endpoint.is_healthy = True
            endpoint.last_failure = None


def create_fallback_chain_from_config(
    primary_model: str = "gpt-4o-mini",
    primary_provider: str = "openai",
    fallback_models: Optional[List[Dict[str, Any]]] = None,
    config: Optional[FallbackConfig] = None,
) -> FallbackChain:
    """
    从配置创建降级链

    Args:
        primary_model: 主模型
        primary_provider: 主提供商
        fallback_models: 备用模型列表 [{"model": "...", "provider": "...", "priority": 0}]
        config: 降级配置

    Returns:
        配置好的降级链
    """
    chain = FallbackChain(config=config)

    # 添加主模型
    chain.add_endpoint(
        name=primary_model,
        provider=primary_provider,
        priority=100,
    )

    # 添加备用模型
    if fallback_models:
        for fb in fallback_models:
            chain.add_endpoint(
                name=fb.get("model", "unknown"),
                provider=fb.get("provider", "openai"),
                priority=fb.get("priority", 0),
            )

    return chain
