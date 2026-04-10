"""
LLM 调用优化统计和缓存模块
增强现有 LLM Manager 的缓存统计
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
from app.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class LLMCallRecord:
    """LLM 调用记录"""
    timestamp: float
    model: str
    prompt_tokens: int
    completion_tokens: int
    cached: bool
    latency_ms: float
    error: Optional[str] = None


class LLMCacheStats:
    """LLM 缓存统计"""

    def __init__(self):
        self.records: List[LLMCallRecord] = []
        self.total_calls = 0
        self.cached_calls = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_latency_ms = 0.0
        self.failed_calls = 0

    def record(self, record: LLMCallRecord) -> None:
        """记录调用"""
        self.records.append(record)
        self.total_calls += 1
        self.total_prompt_tokens += record.prompt_tokens
        self.total_completion_tokens += record.completion_tokens
        self.total_latency_ms += record.latency_ms
        if record.cached:
            self.cached_calls += 1
        if record.error:
            self.failed_calls += 1

    @property
    def cache_hit_rate(self) -> float:
        """缓存命中率"""
        if self.total_calls == 0:
            return 0.0
        return self.cached_calls / self.total_calls

    @property
    def avg_latency_ms(self) -> float:
        """平均延迟"""
        if self.total_calls == 0:
            return 0.0
        non_cached = [r for r in self.records if not r.cached]
        if not non_cached:
            return 0.0
        return sum(r.latency_ms for r in non_cached) / len(non_cached)

    @property
    def tokens_per_call(self) -> float:
        """平均每次调用 token 数"""
        if self.total_calls == 0:
            return 0.0
        return (self.total_prompt_tokens + self.total_completion_tokens) / self.total_calls

    def get_summary(self) -> Dict[str, Any]:
        """获取统计摘要"""
        return {
            "total_calls": self.total_calls,
            "cached_calls": self.cached_calls,
            "cache_hit_rate": f"{self.cache_hit_rate:.2%}",
            "avg_latency_ms": f"{self.avg_latency_ms:.2f}ms",
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "tokens_per_call": f"{self.tokens_per_call:.1f}",
            "failed_calls": self.failed_calls,
        }


class LLMCacheOptimizer:
    """
    LLM 缓存优化器
    提供缓存统计、提示词压缩等功能
    """

    def __init__(self):
        self.stats = LLMCacheStats()

    def record_call(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cached: bool,
        latency_ms: float,
        error: Optional[str] = None,
    ) -> None:
        """记录 LLM 调用"""
        record = LLMCallRecord(
            timestamp=time.time(),
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached=cached,
            latency_ms=latency_ms,
            error=error,
        )
        self.stats.record(record)

    def compress_prompt(
        self,
        prompt: str,
        max_length: int = 2000,
    ) -> str:
        """
        压缩提示词以减少 token 消耗
        Args:
            prompt: 原始提示词
            max_length: 最大长度
        Returns:
            压缩后的提示词
        """
        if len(prompt) <= max_length:
            return prompt

        # 简单的压缩策略：移除多余空白、缩短描述
        import re

        # 移除多余空白
        compressed = re.sub(r'\s+', ' ', prompt).strip()

        # 如果还是太长，截断
        if len(compressed) > max_length:
            compressed = compressed[:max_length] + "..."

        return compressed

    def should_use_cache(
        self,
        messages: List[Dict[str, Any]],
        cache_key: str,
        cache_ttl: int = 300,
    ) -> bool:
        """
        判断是否应该使用缓存

        Args:
            messages: 消息列表
            cache_key: 缓存键
            cache_ttl: 缓存 TTL

        Returns:
            是否使用缓存
        """
        # 对于工具调用，不使用缓存
        if any(m.get("tools") for m in messages if isinstance(m, dict)):
            return False

        # 对于流式请求，不使用缓存
        if any(m.get("stream") for m in messages if isinstance(m, dict)):
            return False

        return True

    def estimate_cost_saving(
        self,
        cached_calls: int,
        avg_tokens_per_call: int,
        cost_per_1k_tokens: float = 0.002,
    ) -> Dict[str, Any]:
        """
        估算成本节省

        Args:
            cached_calls: 缓存命中次数
            avg_tokens_per_call: 平均每次调用 token 数
            cost_per_1k_tokens: 每 1000 token 成本

        Returns:
            成本节省统计
        """
        tokens_saved = cached_calls * avg_tokens_per_call
        cost_saved = (tokens_saved / 1000) * cost_per_1k_tokens

        return {
            "cached_calls": cached_calls,
            "tokens_saved": tokens_saved,
            "cost_saved_usd": f"${cost_saved:.4f}",
            "cost_per_1k_tokens": f"${cost_per_1k_tokens:.4f}",
        }


# 全局优化器
_llm_optimizer: Optional[LLMCacheOptimizer] = None


def get_llm_optimizer() -> LLMCacheOptimizer:
    """获取 LLM 优化器"""
    global _llm_optimizer
    if _llm_optimizer is None:
        _llm_optimizer = LLMCacheOptimizer()
    return _llm_optimizer
