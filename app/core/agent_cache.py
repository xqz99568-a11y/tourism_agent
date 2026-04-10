"""
Agent 请求缓存模块
对相同或相似的 Agent 请求进行缓存，避免重复 LLM 调用
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
from enum import Enum

from cachetools import TTLCache
from app.core.logger import get_logger

logger = get_logger(__name__)


class CacheLevel(str, Enum):
    """缓存级别"""
    EXACT = "exact"           # 完全匹配
    SEMANTIC = "semantic"     # 语义相似
    PARTIAL = "partial"       # 部分匹配（参数级别）


@dataclass
class RequestCacheKey:
    """请求缓存键"""
    agent_name: str
    intent_type: str
    destination: Optional[str] = None
    duration: Optional[int] = None
    num_travelers: Optional[int] = None
    budget_level: Optional[str] = None
    travel_styles: Optional[str] = None
    special_requirements: Optional[str] = None

    def to_hash(self) -> str:
        """转换为哈希字符串"""
        parts = [
            self.agent_name,
            self.intent_type,
            self.destination or "",
            str(self.duration or ""),
            str(self.num_travelers or ""),
            self.budget_level or "",
            self.travel_styles or "",
            self.special_requirements or "",
        ]
        content = "|".join(parts)
        return hashlib.sha256(content.encode()).hexdigest()[:24]

    @classmethod
    def from_extracted_info(
        cls,
        agent_name: str,
        intent_type: str,
        extracted_info: Dict[str, Any],
    ) -> "RequestCacheKey":
        """从提取的信息创建缓存键"""
        # 标准化旅行风格
        styles = extracted_info.get("travel_styles", [])
        if isinstance(styles, list):
            styles_str = ",".join(sorted(styles)) if styles else ""
        else:
            styles_str = str(styles) if styles else ""

        # 标准化特殊需求
        special = extracted_info.get("special_requirements", [])
        if isinstance(special, list):
            special_str = ",".join(sorted(special)) if special else ""
        else:
            special_str = str(special) if special else ""

        return cls(
            agent_name=agent_name,
            intent_type=intent_type,
            destination=extracted_info.get("destination"),
            duration=extracted_info.get("duration"),
            num_travelers=extracted_info.get("num_travelers"),
            budget_level=extracted_info.get("budget_level"),
            travel_styles=styles_str,
            special_requirements=special_str,
        )


@dataclass
class CachedAgentResult:
    """缓存的 Agent 结果"""
    key: RequestCacheKey
    content: str
    data: Optional[Dict[str, Any]] = None
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    ttl: int = 3600  # 默认 1 小时
    tokens_saved: int = 0

    @property
    def is_expired(self) -> bool:
        """检查是否过期"""
        return time.time() - self.created_at > self.ttl

    @property
    def age_seconds(self) -> float:
        """获取缓存年龄"""
        return time.time() - self.created_at

    def touch(self) -> None:
        """更新访问时间"""
        self.last_accessed = time.time()
        self.access_count += 1


@dataclass
class CacheMetrics:
    """缓存指标"""
    total_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    exact_hits: int = 0
    semantic_hits: int = 0
    partial_hits: int = 0
    evictions: int = 0
    total_tokens_saved: int = 0

    @property
    def hit_rate(self) -> float:
        """命中率"""
        if self.total_requests == 0:
            return 0.0
        return self.cache_hits / self.total_requests

    @property
    def exact_hit_rate(self) -> float:
        """精确命中率"""
        if self.total_requests == 0:
            return 0.0
        return self.exact_hits / self.total_requests

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "hit_rate": f"{self.hit_rate:.2%}",
            "exact_hit_rate": f"{self.exact_hit_rate:.2%}",
            "exact_hits": self.exact_hits,
            "semantic_hits": self.semantic_hits,
            "partial_hits": self.partial_hits,
            "evictions": self.evictions,
            "tokens_saved": self.total_tokens_saved,
        }


class AgentRequestCache:
    """
    Agent 请求缓存
    支持多级缓存：精确匹配、语义相似、部分参数匹配
    """

    # 缓存配置
    DEFAULT_TTL = 3600  # 1小时
    MIN_TTL_FOR_STALE = 300  # 5分钟
    MAX_CACHE_SIZE = 500

    def __init__(
        self,
        max_size: int = MAX_CACHE_SIZE,
        default_ttl: int = DEFAULT_TTL,
        enable_partial_match: bool = True,
    ):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.enable_partial_match = enable_partial_match

        # 精确匹配缓存
        self._exact_cache: Dict[str, CachedAgentResult] = {}

        # 按目的地索引（用于部分匹配）
        self._destination_index: Dict[str, List[str]] = {}

        # 指标
        self.metrics = CacheMetrics()

        logger.info(
            f"AgentRequestCache initialized: max_size={max_size}, "
            f"ttl={default_ttl}s, partial_match={enable_partial_match}"
        )

    def _estimate_tokens(self, content: str) -> int:
        """估算 token 数量"""
        chinese_chars = sum(1 for c in content if '\u4e00' <= c <= '\u9fff')
        other_chars = len(content) - chinese_chars
        return int(chinese_chars * 1.5 + other_chars * 0.25)

    def _index_by_destination(self, key: RequestCacheKey, cache_key: str) -> None:
        """按目的地建立索引"""
        if key.destination:
            if key.destination not in self._destination_index:
                self._destination_index[key.destination] = []
            if cache_key not in self._destination_index[key.destination]:
                self._destination_index[key.destination].append(cache_key)

    def _get_from_index(self, destination: str) -> List[CachedAgentResult]:
        """从索引获取缓存"""
        results = []
        cache_keys = self._destination_index.get(destination, [])
        for ck in cache_keys:
            if ck in self._exact_cache:
                entry = self._exact_cache[ck]
                if not entry.is_expired:
                    results.append(entry)
                else:
                    # 清理过期项
                    self._remove_expired(ck)
        return results

    def _remove_expired(self, cache_key: str) -> None:
        """移除过期缓存"""
        if cache_key in self._exact_cache:
            entry = self._exact_cache[cache_key]
            del self._exact_cache[cache_key]
            self.metrics.evictions += 1

            # 从索引中移除
            if entry.key.destination:
                dest_list = self._destination_index.get(entry.key.destination, [])
                if cache_key in dest_list:
                    dest_list.remove(cache_key)

    def _evict_if_needed(self) -> None:
        """必要时淘汰缓存"""
        if len(self._exact_cache) >= self.max_size:
            # LRU: 移除最久未访问的
            oldest_key = None
            oldest_time = float('inf')
            for key, entry in self._exact_cache.items():
                if entry.last_accessed < oldest_time:
                    oldest_time = entry.last_accessed
                    oldest_key = key

            if oldest_key:
                del self._exact_cache[oldest_key]
                self.metrics.evictions += 1

    def get(
        self,
        agent_name: str,
        intent_type: str,
        extracted_info: Dict[str, Any],
        min_similarity: float = 0.85,
    ) -> Optional[CachedAgentResult]:
        """
        获取缓存结果

        Args:
            agent_name: Agent 名称
            intent_type: 意图类型
            extracted_info: 提取的信息
            min_similarity: 最小相似度（用于部分匹配）

        Returns:
            缓存结果或 None
        """
        self.metrics.total_requests += 1

        # 构建缓存键
        cache_key_obj = RequestCacheKey.from_extracted_info(
            agent_name, intent_type, extracted_info
        )
        cache_key = cache_key_obj.to_hash()

        # 1. 精确匹配
        if cache_key in self._exact_cache:
            entry = self._exact_cache[cache_key]
            if not entry.is_expired:
                entry.touch()
                self.metrics.cache_hits += 1
                self.metrics.exact_hits += 1
                self.metrics.total_tokens_saved += entry.tokens_saved
                logger.debug(f"Cache hit (exact): {agent_name}")
                return entry
            else:
                self._remove_expired(cache_key)

        # 2. 部分匹配（相同目的地）
        if self.enable_partial_match and cache_key_obj.destination:
            partial_matches = self._find_partial_matches(
                cache_key_obj, min_similarity
            )
            if partial_matches:
                best = partial_matches[0]
                best.touch()
                self.metrics.cache_hits += 1
                self.metrics.partial_hits += 1
                self.metrics.total_tokens_saved += best.tokens_saved
                logger.debug(
                    f"Cache hit (partial): {agent_name}, similarity={partial_matches[1]:.2f}"
                )
                return best

        # 未命中
        self.metrics.cache_misses += 1
        return None

    def _find_partial_matches(
        self,
        key: RequestCacheKey,
        min_similarity: float,
    ) -> Optional[tuple[CachedAgentResult, float]]:
        """查找部分匹配的缓存"""
        candidates = self._get_from_index(key.destination)

        if not candidates:
            return None

        best_match = None
        best_similarity = 0.0

        for entry in candidates:
            similarity = self._calculate_similarity(key, entry.key)
            if similarity > best_similarity and similarity >= min_similarity:
                best_similarity = similarity
                best_match = entry

        if best_match:
            return (best_match, best_similarity)
        return None

    def _calculate_similarity(self, key1: RequestCacheKey, key2: RequestCacheKey) -> float:
        """计算两个缓存键的相似度"""
        weights = {
            "destination": 0.4,
            "duration": 0.15,
            "num_travelers": 0.1,
            "budget_level": 0.15,
            "travel_styles": 0.15,
            "special_requirements": 0.05,
        }

        total_weight = 0.0
        weighted_similarity = 0.0

        attrs = ["destination", "duration", "num_travelers", "budget_level",
                 "travel_styles", "special_requirements"]

        for attr in attrs:
            v1 = getattr(key1, attr)
            v2 = getattr(key2, attr)
            weight = weights[attr]

            total_weight += weight

            if v1 == v2:
                weighted_similarity += weight
            elif v1 and v2:
                # 部分匹配
                weighted_similarity += weight * 0.5
            # else: 0

        return weighted_similarity / total_weight if total_weight > 0 else 0.0

    def set(
        self,
        agent_name: str,
        intent_type: str,
        extracted_info: Dict[str, Any],
        content: str,
        data: Optional[Dict[str, Any]] = None,
        ttl: Optional[int] = None,
    ) -> None:
        """
        设置缓存

        Args:
            agent_name: Agent 名称
            intent_type: 意图类型
            extracted_info: 提取的信息
            content: 结果内容
            data: 额外数据
            ttl: 过期时间（秒）
        """
        cache_key_obj = RequestCacheKey.from_extracted_info(
            agent_name, intent_type, extracted_info
        )
        cache_key = cache_key_obj.to_hash()

        # 淘汰旧缓存
        self._evict_if_needed()

        entry = CachedAgentResult(
            key=cache_key_obj,
            content=content,
            data=data,
            ttl=ttl or self.default_ttl,
            tokens_saved=self._estimate_tokens(content),
        )

        self._exact_cache[cache_key] = entry
        self._index_by_destination(cache_key_obj, cache_key)

        logger.debug(f"Cache set: {agent_name}, ttl={entry.ttl}s")

    def invalidate(
        self,
        agent_name: Optional[str] = None,
        destination: Optional[str] = None,
        pattern: Optional[str] = None,
    ) -> int:
        """
        使缓存失效

        Args:
            agent_name: 特定 Agent 的缓存
            destination: 特定目的地的缓存
            pattern: 匹配模式的缓存

        Returns:
            清除的条目数
        """
        count = 0

        if destination:
            # 清除特定目的地的所有缓存
            cache_keys = self._destination_index.get(destination, [])
            for ck in cache_keys:
                if ck in self._exact_cache:
                    del self._exact_cache[ck]
                    count += 1
            self._destination_index[destination] = []

        elif agent_name:
            # 清除特定 Agent 的缓存
            keys_to_remove = [
                k for k, v in self._exact_cache.items()
                if v.key.agent_name == agent_name
            ]
            for k in keys_to_remove:
                del self._exact_cache[k]
                count += 1

        elif pattern:
            # 按模式清除
            keys_to_remove = [
                k for k in self._exact_cache.keys()
                if pattern in k
            ]
            for k in keys_to_remove:
                del self._exact_cache[k]
                count += 1

        else:
            # 清除所有
            count = len(self._exact_cache)
            self._exact_cache.clear()
            self._destination_index.clear()

        logger.info(f"Cache invalidated: {count} entries removed")
        return count

    def cleanup_expired(self) -> int:
        """清理过期缓存"""
        count = 0
        keys_to_remove = [
            k for k, v in self._exact_cache.items() if v.is_expired
        ]
        for k in keys_to_remove:
            self._remove_expired(k)
            count += 1
        return count

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        return {
            "size": len(self._exact_cache),
            "max_size": self.max_size,
            "metrics": self.metrics.to_dict(),
        }

    @property
    def size(self) -> int:
        """获取当前缓存大小"""
        return len(self._exact_cache)


# 全局缓存实例
_agent_cache: Optional[AgentRequestCache] = None


def get_agent_cache() -> AgentRequestCache:
    """获取 Agent 缓存实例"""
    global _agent_cache
    if _agent_cache is None:
        _agent_cache = AgentRequestCache()
    return _agent_cache


def init_agent_cache(
    max_size: int = 500,
    default_ttl: int = 3600,
) -> AgentRequestCache:
    """初始化 Agent 缓存"""
    global _agent_cache
    _agent_cache = AgentRequestCache(
        max_size=max_size,
        default_ttl=default_ttl,
    )
    return _agent_cache
