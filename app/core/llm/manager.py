"""
LLM 管理器 (简化版)
只支持单模型 OpenRouter，自动降级到 Mock 客户端
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logger import get_logger

from .client import (
    LLMMessage,
    LLMResponse,
    ToolDefinition,
    BaseLLMClient,
    OpenRouterClient,
    MockLLMClient,
)

logger = get_logger(__name__)


@dataclass
class LLMCallMetrics:
    """LLM 调用指标"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    cached_calls: int = 0
    total_latency_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.successful_calls / self.total_calls

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "cached_calls": self.cached_calls,
            "success_rate": f"{self.success_rate:.2%}",
            "total_latency_ms": f"{self.total_latency_ms:.2f}ms",
        }


class SimpleLLMCache:
    """
    简单的 LLM 响应缓存
    基于消息哈希的精确匹配
    """

    def __init__(self, ttl_seconds: int = 300):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._ttl = ttl_seconds

    def _make_key(self, messages: List[LLMMessage]) -> str:
        """生成缓存键"""
        content = "".join(m.content for m in messages)
        return hashlib.md5(content.encode()).hexdigest()

    def get(self, messages: List[LLMMessage]) -> Optional[LLMResponse]:
        """获取缓存的响应"""
        key = self._make_key(messages)
        entry = self._cache.get(key)

        if entry:
            if time.time() - entry["timestamp"] < self._ttl:
                return entry["response"]
            else:
                del self._cache[key]
        return None

    def set(self, messages: List[LLMMessage], response: LLMResponse) -> None:
        """缓存响应"""
        key = self._make_key(messages)
        self._cache[key] = {
            "response": response,
            "timestamp": time.time(),
        }

    def clear(self) -> None:
        """清空缓存"""
        self._cache.clear()


class EnhancedLLMManager:
    """
    简化的 LLM 管理器
    使用单一 OpenRouter 模型，失败时降级到 Mock 客户端
    """

    def __init__(
        self,
        enable_caching: bool = True,  # 默认启用缓存
    ):
        self._client: Optional[BaseLLMClient] = None
        self._mock_client = MockLLMClient()
        self._using_mock = False
        self.metrics = LLMCallMetrics()
        self._cache = SimpleLLMCache(ttl_seconds=300) if enable_caching else None
        self._initialize_client()

    def _initialize_client(self) -> None:
        """初始化客户端"""
        if settings.llm.is_configured:
            try:
                self._client = OpenRouterClient(
                    api_key=settings.llm.api_key,
                    base_url=settings.llm.base_url,
                    model=settings.llm.model,
                    timeout=settings.llm.timeout,
                )
                self._using_mock = False
                logger.info(f"LLM 客户端已初始化: {settings.llm.model}")
            except Exception as e:
                logger.warning(f"初始化 OpenRouter 失败: {e}, 使用 Mock 客户端")
                self._client = self._mock_client
                self._using_mock = True
        else:
            logger.warning("未配置 LLM API Key, 使用 Mock 客户端")
            self._client = self._mock_client
            self._using_mock = True

    @property
    def is_mock(self) -> bool:
        return self._using_mock

    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        use_cache: bool = True,  # 默认使用缓存
        **kwargs,
    ) -> LLMResponse:
        """发送对话请求"""
        start_time = time.time()
        self.metrics.total_calls += 1

        # 尝试从缓存获取
        if use_cache and self._cache and not tools:
            cached = self._cache.get(messages)
            if cached:
                self.metrics.cached_calls += 1
                logger.debug("LLM 响应命中缓存")
                return cached

        try:
            response = await self._client.chat(messages, tools, **kwargs)
            self.metrics.successful_calls += 1
            self.metrics.total_latency_ms += (time.time() - start_time) * 1000

            # 缓存响应
            if use_cache and self._cache and not tools:
                self._cache.set(messages, response)

            return response
        except Exception as e:
            logger.warning(f"LLM 调用失败: {e}")

            # 如果当前不是 Mock 客户端，尝试降级
            if not self._using_mock:
                logger.info("尝试使用 Mock 客户端...")
                try:
                    response = await self._mock_client.chat(messages, tools, **kwargs)
                    self.metrics.successful_calls += 1
                    self.metrics.total_latency_ms += (time.time() - start_time) * 1000
                    return response
                except Exception as mock_error:
                    logger.error(f"Mock 客户端也失败: {mock_error}")

            self.metrics.failed_calls += 1
            self.metrics.total_latency_ms += (time.time() - start_time) * 1000
            raise

    async def stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs,
    ):
        """流式对话"""
        async for chunk in self._client.stream(messages, tools, **kwargs):
            yield chunk


# 全局单例
_llm_manager: Optional[EnhancedLLMManager] = None


def get_llm_manager() -> EnhancedLLMManager:
    """获取 LLM 管理器单例"""
    global _llm_manager
    if _llm_manager is None:
        _llm_manager = EnhancedLLMManager(enable_caching=True)
    return _llm_manager


def init_llm_manager() -> EnhancedLLMManager:
    """初始化 LLM 管理器"""
    return get_llm_manager()
