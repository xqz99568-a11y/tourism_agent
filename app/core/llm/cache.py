"""
语义缓存模块
基于语义相似度的响应缓存
"""
from __future__ import annotations

import hashlib
import time
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import numpy as np

from cachetools import TTLCache
from app.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CacheEntry:
    """缓存条目"""
    key: str                          # 缓存键
    response: str                     # 缓存的响应内容
    model: str                        # 生成响应的模型
    task_type: str                    # 任务类型
    created_at: float                  # 创建时间
    last_accessed: float              # 最后访问时间
    access_count: int = 0             # 访问次数
    ttl: int = 3600                   # TTL（秒）
    embedding: Optional[List[float]] = None  # 语义向量

    @property
    def is_expired(self) -> bool:
        """检查是否过期"""
        return time.time() - self.created_at > self.ttl

    @property
    def age_seconds(self) -> float:
        """获取缓存年龄（秒）"""
        return time.time() - self.created_at


@dataclass
class CacheStats:
    """缓存统计"""
    hits: int = 0                     # 命中次数
    misses: int = 0                   # 未命中次数
    evictions: int = 0                # 淘汰次数
    total_requests: int = 0           # 总请求数
    total_saved_tokens: int = 0       # 节省的 token 数

    @property
    def hit_rate(self) -> float:
        """命中率"""
        if self.total_requests == 0:
            return 0.0
        return self.hits / self.total_requests

    def record_hit(self, tokens_saved: int = 0) -> None:
        """记录命中"""
        self.hits += 1
        self.total_requests += 1
        self.total_saved_tokens += tokens_saved

    def record_miss(self) -> None:
        """记录未命中"""
        self.misses += 1
        self.total_requests += 1

    def record_eviction(self) -> None:
        """记录淘汰"""
        self.evictions += 1


class SemanticCache:
    """
    语义缓存
    支持精确匹配和语义相似度匹配
    """

    # 缓存键前缀
    EXACT_PREFIX = "cache:exact:"
    SEMANTIC_PREFIX = "cache:semantic:"

    # 相似度阈值
    DEFAULT_SIMILARITY_THRESHOLD = 0.92  # 92% 相似度

    def __init__(
        self,
        max_size: int = 1000,
        default_ttl: int = 3600,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        enable_semantic: bool = True,
        embedding_model: Optional[str] = None,
    ):
        """
        初始化语义缓存

        Args:
            max_size: 最大缓存条目数
            default_ttl: 默认 TTL（秒）
            similarity_threshold: 语义相似度阈值
            enable_semantic: 是否启用语义缓存
            embedding_model: 用于生成嵌入向量的模型
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.similarity_threshold = similarity_threshold
        self.enable_semantic = enable_semantic
        self.embedding_model = embedding_model

        # 精确匹配缓存（使用 TTLCache）
        self._exact_cache: TTLCache = TTLCache(
            maxsize=max_size,
            ttl=default_ttl,
        )

        # 语义缓存存储
        self._semantic_cache: Dict[str, CacheEntry] = {}
        self._semantic_vectors: Dict[str, List[float]] = {}

        # 统计信息
        self.stats = CacheStats()

        logger.info(
            f"SemanticCache initialized: max_size={max_size}, "
            f"ttl={default_ttl}s, similarity_threshold={similarity_threshold}"
        )

    def _generate_key(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        task_type: Optional[str] = None,
    ) -> str:
        """
        生成缓存键

        Args:
            messages: 消息列表
            model: 模型名称
            task_type: 任务类型

        Returns:
            缓存键
        """
        # 提取关键内容
        key_parts = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            # 对 system 和 user 消息敏感
            if role in ("system", "user"):
                key_parts.append(f"{role}:{content}")

        # 添加模型和任务类型
        if model:
            key_parts.append(f"model:{model}")
        if task_type:
            key_parts.append(f"task:{task_type}")

        # 生成哈希
        key_content = "|".join(key_parts)
        key_hash = hashlib.sha256(key_content.encode()).hexdigest()[:32]

        return key_hash

    async def get(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        task_type: Optional[str] = None,
    ) -> Optional[str]:
        """
        获取缓存的响应

        Args:
            messages: 消息列表
            model: 模型名称
            task_type: 任务类型

        Returns:
            缓存的响应，如果未命中则返回 None
        """
        cache_key = self._generate_key(messages, model, task_type)

        # 1. 先尝试精确匹配
        cached = self._exact_cache.get(cache_key)
        if cached:
            self.stats.record_hit(cached.get("tokens_saved", 0))
            logger.debug(f"Cache hit (exact): {cache_key[:8]}...")
            return cached.get("response")

        # 2. 尝试语义匹配
        if self.enable_semantic and self._semantic_cache:
            semantic_result = await self._get_semantic_match(messages)
            if semantic_result:
                self.stats.record_hit(semantic_result.get("tokens_saved", 0))
                return semantic_result.get("response")

        # 未命中
        self.stats.record_miss()
        return None

    async def _get_semantic_match(
        self,
        messages: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """获取语义相似的缓存"""
        if not self.embedding_model:
            return None

        try:
            # 生成当前查询的嵌入向量
            query_text = self._extract_text_for_embedding(messages)
            query_embedding = await self._get_embedding(query_text)

            if query_embedding is None:
                return None

            # 遍历所有缓存，找最相似的
            best_match = None
            best_similarity = 0.0

            for key, cached_embedding in self._semantic_vectors.items():
                if key in self._semantic_cache:
                    entry = self._semantic_cache[key]

                    # 跳过过期条目
                    if entry.is_expired:
                        continue

                    # 计算余弦相似度
                    similarity = self._cosine_similarity(query_embedding, cached_embedding)

                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_match = entry

            # 如果相似度超过阈值
            if best_match and best_similarity >= self.similarity_threshold:
                logger.debug(
                    f"Cache hit (semantic): similarity={best_similarity:.3f}"
                )
                return {
                    "response": best_match.response,
                    "tokens_saved": self._estimate_tokens(best_match.response),
                    "similarity": best_similarity,
                }

        except Exception as e:
            logger.warning(f"Semantic cache lookup failed: {e}")

        return None

    def _extract_text_for_embedding(self, messages: List[Dict[str, Any]]) -> str:
        """提取用于生成嵌入的文本"""
        parts = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role in ("system", "user"):
                parts.append(content)

        return " ".join(parts)

    async def _get_embedding(self, text: str) -> Optional[List[float]]:
        """获取文本嵌入（需要外部调用 LLM provider）"""
        # 延迟导入避免循环依赖
        try:
            from app.core.llm.client import get_llm

            llm = get_llm()
            embeddings = await llm._default_client.embeddings([text])
            return embeddings[0] if embeddings else None
        except Exception:
            return None

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        if len(vec1) != len(vec2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def _estimate_tokens(self, text: str) -> int:
        """估算 token 数量（粗略）"""
        # 中英文混合估算
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars * 1.5 + other_chars * 0.25)

    async def set(
        self,
        messages: List[Dict[str, Any]],
        response: str,
        model: str,
        task_type: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> None:
        """
        设置缓存

        Args:
            messages: 消息列表
            response: 响应内容
            model: 模型名称
            task_type: 任务类型
            ttl: TTL（秒）
        """
        cache_key = self._generate_key(messages, model, task_type)
        ttl = ttl or self.default_ttl

        # 存储到精确缓存
        entry = {
            "response": response,
            "model": model,
            "task_type": task_type or "unknown",
            "created_at": time.time(),
            "tokens_saved": self._estimate_tokens(response),
        }

        self._exact_cache[cache_key] = entry

        # 存储到语义缓存
        if self.enable_semantic:
            semantic_entry = CacheEntry(
                key=cache_key,
                response=response,
                model=model,
                task_type=task_type or "unknown",
                created_at=time.time(),
                last_accessed=time.time(),
                ttl=ttl,
            )
            self._semantic_cache[cache_key] = semantic_entry

            # 生成并存储嵌入向量
            query_text = self._extract_text_for_embedding(messages)
            embedding = await self._get_embedding(query_text)
            if embedding:
                self._semantic_vectors[cache_key] = embedding

        logger.debug(f"Cache set: {cache_key[:8]}..., ttl={ttl}s")

    def invalidate(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        pattern: Optional[str] = None,
    ) -> int:
        """
        使缓存失效

        Args:
            messages: 如果提供，只清除特定消息的缓存
            model: 如果提供，只清除特定模型的缓存
            pattern: 如果提供，清除匹配模式的所有缓存

        Returns:
            清除的条目数
        """
        count = 0

        if messages:
            # 清除特定消息的缓存
            cache_key = self._generate_key(messages, model)
            if cache_key in self._exact_cache:
                del self._exact_cache[cache_key]
                count += 1

            if cache_key in self._semantic_cache:
                del self._semantic_cache[cache_key]
                if cache_key in self._semantic_vectors:
                    del self._semantic_vectors[cache_key]
                count += 1

        elif pattern:
            # 按模式清除
            keys_to_delete = [
                k for k in self._exact_cache.keys()
                if pattern in str(k)
            ]
            for k in keys_to_delete:
                del self._exact_cache[k]
                count += 1

            keys_to_delete = [
                k for k in self._semantic_cache.keys()
                if pattern in str(k)
            ]
            for k in keys_to_delete:
                if k in self._semantic_vectors:
                    del self._semantic_vectors[k]
                del self._semantic_cache[k]
                count += 1

        else:
            # 清除所有缓存
            count = len(self._exact_cache)
            self._exact_cache.clear()
            self._semantic_cache.clear()
            self._semantic_vectors.clear()

        return count

    def cleanup_expired(self) -> int:
        """清理过期的缓存条目"""
        count = 0

        # 清理语义缓存
        expired_keys = [
            k for k, entry in self._semantic_cache.items()
            if entry.is_expired
        ]

        for k in expired_keys:
            del self._semantic_cache[k]
            if k in self._semantic_vectors:
                del self._semantic_vectors[k]
            count += 1

        logger.info(f"Cleaned up {count} expired cache entries")
        return count

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        return {
            "size": {
                "exact": len(self._exact_cache),
                "semantic": len(self._semantic_cache),
                "max": self.max_size,
            },
            "stats": {
                "hits": self.stats.hits,
                "misses": self.stats.misses,
                "evictions": self.stats.evictions,
                "total_requests": self.stats.total_requests,
                "hit_rate": f"{self.stats.hit_rate:.2%}",
                "tokens_saved": self.stats.total_saved_tokens,
            },
            "config": {
                "default_ttl": self.default_ttl,
                "similarity_threshold": self.similarity_threshold,
                "enable_semantic": self.enable_semantic,
            },
        }

    @property
    def size(self) -> int:
        """获取当前缓存大小"""
        return len(self._exact_cache)


# 全局缓存实例
_semantic_cache: Optional[SemanticCache] = None


def get_semantic_cache() -> SemanticCache:
    """获取语义缓存实例"""
    global _semantic_cache
    if _semantic_cache is None:
        _semantic_cache = SemanticCache()
    return _semantic_cache


def init_semantic_cache(
    max_size: int = 1000,
    default_ttl: int = 3600,
    similarity_threshold: float = 0.92,
    enable_semantic: bool = True,
) -> SemanticCache:
    """初始化语义缓存"""
    global _semantic_cache
    _semantic_cache = SemanticCache(
        max_size=max_size,
        default_ttl=default_ttl,
        similarity_threshold=similarity_threshold,
        enable_semantic=enable_semantic,
    )
    return _semantic_cache
