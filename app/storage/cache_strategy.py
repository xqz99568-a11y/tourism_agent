"""
Cache Strategy - 缓存策略实现
多层缓存架构和缓存管理
"""
from __future__ import annotations

import json
import hashlib
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, TypeVar, Generic
from functools import wraps
import asyncio

from app.core.logger import get_logger
from app.storage.cache_manager import RedisCacheManager, get_cache_manager

logger = get_logger(__name__)

T = TypeVar('T')


class CacheStrategy:
    """缓存策略基类"""

    def __init__(self, cache: RedisCacheManager):
        self.cache = cache

    async def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        raise NotImplementedError

    async def set(self, key: str, value: Any, **kwargs) -> None:
        """设置缓存"""
        raise NotImplementedError

    async def invalidate(self, key: str) -> None:
        """使缓存失效"""
        raise NotImplementedError


class NoCache(CacheStrategy):
    """无缓存策略"""

    async def get(self, key: str) -> Optional[Any]:
        return None

    async def set(self, key: str, value: Any, **kwargs) -> None:
        pass

    async def invalidate(self, key: str) -> None:
        pass


class MemoryCache(CacheStrategy):
    """
    内存缓存策略
    本地内存缓存 + Redis 二级缓存
    """

    def __init__(self, cache: RedisCacheManager, local_cache_size: int = 1000):
        super().__init__(cache)
        self._memory_cache: Dict[str, tuple[Any, datetime]] = {}
        self._local_cache_size = local_cache_size
        self._ttl = 60  # 内存缓存 TTL: 1 分钟

    async def get(self, key: str) -> Optional[Any]:
        """先查内存，再查 Redis"""
        # 检查内存缓存
        if key in self._memory_cache:
            value, cached_at = self._memory_cache[key]
            if datetime.utcnow() - cached_at < timedelta(seconds=self._ttl):
                logger.debug(f"Memory cache hit: {key}")
                return value
            else:
                del self._memory_cache[key]

        # 检查 Redis
        redis_key = f"memory:{key}"
        value = await self.cache.get(redis_key)
        if value:
            try:
                data = json.loads(value)
                # 更新内存缓存
                self._memory_cache[key] = (data, datetime.utcnow())
                logger.debug(f"Redis cache hit: {key}")
                return data
            except json.JSONDecodeError:
                return None

        return None

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """同时写入内存和 Redis"""
        # 写入内存
        self._memory_cache[key] = (value, datetime.utcnow())

        # 限制内存缓存大小
        if len(self._memory_cache) > self._local_cache_size:
            oldest = min(self._memory_cache.items(), key=lambda x: x[1][1])
            del self._memory_cache[oldest[0]]

        # 写入 Redis
        redis_key = f"memory:{key}"
        await self.cache.set(redis_key, json.dumps(value, default=str), ttl=ttl)

    async def invalidate(self, key: str) -> None:
        """删除内存和 Redis 中的缓存"""
        if key in self._memory_cache:
            del self._memory_cache[key]

        redis_key = f"memory:{key}"
        await self.cache.delete(redis_key)


class WriteThrough(CacheStrategy):
    """写穿透策略: 写入时同时更新缓存和数据库"""

    async def get(self, key: str) -> Optional[Any]:
        return await self.cache.get(f"writethrough:{key}")

    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        await self.cache.set(f"writethrough:{key}", value, ttl=ttl)

    async def invalidate(self, key: str) -> None:
        await self.cache.delete(f"writethrough:{key}")


class WriteBehind(CacheStrategy):
    """
    写回策略: 先写缓存，异步写数据库
    适用于高写入场景
    """

    def __init__(self, cache: RedisCacheManager, flush_interval: int = 60):
        super().__init__(cache)
        self._pending_writes: Dict[str, tuple[Any, datetime]] = {}
        self._flush_interval = flush_interval
        self._lock = asyncio.Lock()

    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        """写入缓存，标记待刷新"""
        full_key = f"writebehind:{key}"
        await self.cache.set(full_key, value, ttl=ttl)

        async with self._lock:
            self._pending_writes[key] = (value, datetime.utcnow())

    async def get(self, key: str) -> Optional[Any]:
        """直接从缓存读取"""
        full_key = f"writebehind:{key}"
        return await self.cache.get(full_key)

    async def invalidate(self, key: str) -> None:
        """删除缓存"""
        full_key = f"writebehind:{key}"
        await self.cache.delete(full_key)

        async with self._lock:
            if key in self._pending_writes:
                del self._pending_writes[key]

    async def flush(self) -> int:
        """刷新待写入的数据到数据库"""
        async with self._lock:
            count = len(self._pending_writes)
            self._pending_writes.clear()
        logger.info(f"Flushed {count} write-behind entries")
        return count


class CacheAside(CacheStrategy):
    """
    旁路缓存策略 (Cache-Aside)
    读: Cache Miss 时从数据库读取并写入缓存
    写: 直接写数据库，然后删除缓存
    """

    def __init__(self, cache: RedisCacheManager, default_ttl: int = 3600):
        super().__init__(cache)
        self.default_ttl = default_ttl

    async def get(self, key: str) -> Optional[Any]:
        """尝试从缓存获取"""
        return await self.cache.get(f"cacheaside:{key}")

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """写入缓存"""
        await self.cache.set(
            f"cacheaside:{key}",
            value,
            ttl=ttl or self.default_ttl
        )

    async def invalidate(self, key: str) -> None:
        """删除缓存 (写操作时调用)"""
        await self.cache.delete(f"cacheaside:{key}")


# ==================== 缓存装饰器 ====================

def cached(
    category: str,
    key_func: Optional[Callable[..., str]] = None,
    ttl: int = 300,
    use_memory_cache: bool = True,
):
    """
    缓存装饰器

    Args:
        category: 缓存类别
        key_func: 生成缓存键的函数，默认使用函数名+参数哈希
        ttl: 缓存过期时间 (秒)
        use_memory_cache: 是否使用内存缓存

    Example:
        @cached("poi", ttl=600)
        async def get_poi(poi_id: str):
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            # 生成缓存键
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                # 使用函数名和参数生成键
                key_parts = [func.__name__]
                key_parts.extend(str(arg) for arg in args)
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
                key_str = ":".join(key_parts)
                cache_key = hashlib.md5(key_str.encode()).hexdigest()

            full_key = f"{category}:{cache_key}"

            # 获取缓存管理器
            cache = await get_cache_manager()

            # 尝试获取缓存
            cached_value = await cache.get_cache(category, cache_key)
            if cached_value is not None:
                logger.debug(f"Cache hit: {full_key}")
                return cached_value

            # 执行函数
            logger.debug(f"Cache miss: {full_key}")
            result = await func(*args, **kwargs)

            # 写入缓存
            if result is not None:
                await cache.set_cache(category, cache_key, result, ttl=ttl)

            return result

        return wrapper
    return decorator


def cache_invalidate(category: str, key_pattern: Optional[str] = None):
    """
    缓存失效装饰器

    Example:
        @cache_invalidate("poi")
        async def update_poi(poi_id: str):
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            result = await func(*args, **kwargs)

            # 获取缓存管理器
            cache = await get_cache_manager()

            if key_pattern:
                # 删除匹配模式的缓存
                await cache.delete_cache_pattern(f"{category}:{key_pattern}")
            else:
                # 生成缓存键并删除
                key_parts = [func.__name__]
                key_parts.extend(str(arg) for arg in args)
                key_str = ":".join(key_parts)
                cache_key = hashlib.md5(key_str.encode()).hexdigest()
                await cache.delete_cache(category, cache_key)

            return result

        return wrapper
    return decorator


# ==================== 缓存服务 ====================

class POICacheService:
    """POI 缓存服务"""

    def __init__(self, cache: RedisCacheManager):
        self.cache = cache
        self.category = "poi"

    async def get_poi(self, poi_id: str) -> Optional[Dict[str, Any]]:
        """获取 POI 缓存"""
        return await self.cache.get_cache(self.category, poi_id)

    async def set_poi(self, poi_id: str, poi_data: Dict[str, Any], ttl: int = 3600) -> None:
        """设置 POI 缓存"""
        await self.cache.set_cache(self.category, poi_id, poi_data, ttl=ttl)

    async def invalidate_poi(self, poi_id: str) -> None:
        """失效 POI 缓存"""
        await self.cache.delete_cache(self.category, poi_id)

    async def get_city_pois(self, city: str) -> Optional[List[Dict[str, Any]]]:
        """获取城市 POI 列表缓存"""
        cache_key = f"city:{city}"
        return await self.cache.get_cache(self.category, cache_key)

    async def set_city_pois(self, city: str, pois: List[Dict[str, Any]], ttl: int = 1800) -> None:
        """设置城市 POI 列表缓存"""
        cache_key = f"city:{city}"
        await self.cache.set_cache(self.category, cache_key, pois, ttl=ttl)

    async def invalidate_city_pois(self, city: str) -> None:
        """失效城市 POI 列表缓存"""
        cache_key = f"city:{city}"
        await self.cache.delete_cache(self.category, cache_key)

    async def get_search_results(self, query: str, filters: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """获取搜索结果缓存"""
        filter_str = json.dumps(filters, sort_keys=True, default=str)
        cache_key = f"search:{query}:{hashlib.md5(filter_str.encode()).hexdigest()}"
        return await self.cache.get_cache(self.category, cache_key)

    async def set_search_results(
        self,
        query: str,
        filters: Dict[str, Any],
        results: List[Dict[str, Any]],
        ttl: int = 300
    ) -> None:
        """设置搜索结果缓存"""
        filter_str = json.dumps(filters, sort_keys=True, default=str)
        cache_key = f"search:{query}:{hashlib.md5(filter_str.encode()).hexdigest()}"
        await self.cache.set_cache(self.category, cache_key, results, ttl=ttl)


class WeatherCacheService:
    """天气缓存服务"""

    def __init__(self, cache: RedisCacheManager):
        self.cache = cache
        self.category = "weather"
        self.default_ttl = 1800  # 30 分钟

    async def get_weather(self, city: str, date: str) -> Optional[Dict[str, Any]]:
        """获取天气缓存"""
        cache_key = f"{city}:{date}"
        return await self.cache.get_cache(self.category, cache_key)

    async def set_weather(
        self,
        city: str,
        date: str,
        weather_data: Dict[str, Any],
        ttl: Optional[int] = None
    ) -> None:
        """设置天气缓存"""
        cache_key = f"{city}:{date}"
        await self.cache.set_cache(
            self.category,
            cache_key,
            weather_data,
            ttl=ttl or self.default_ttl
        )

    async def invalidate_weather(self, city: str, date: Optional[str] = None) -> None:
        """失效天气缓存"""
        if date:
            cache_key = f"{city}:{date}"
            await self.cache.delete_cache(self.category, cache_key)
        else:
            # 失效城市所有日期的缓存
            await self.cache.delete_cache_pattern(f"{self.category}:{city}:*")


class SessionCacheService:
    """会话缓存服务"""

    def __init__(self, cache: RedisCacheManager):
        self.cache = cache
        self.category = "session"

    async def get_session_context(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取会话上下文缓存"""
        return await self.cache.get_cache(self.category, session_id)

    async def set_session_context(
        self,
        session_id: str,
        context: Dict[str, Any],
        ttl: int = 3600 * 24 * 7  # 7 天
    ) -> None:
        """设置会话上下文缓存"""
        await self.cache.set_cache(self.category, session_id, context, ttl=ttl)

    async def invalidate_session(self, session_id: str) -> None:
        """失效会话缓存"""
        await self.cache.delete_cache(self.category, session_id)

    async def get_user_sessions(self, user_id: str) -> Optional[List[str]]:
        """获取用户会话列表缓存"""
        cache_key = f"user:{user_id}:sessions"
        return await self.cache.get_cache(self.category, cache_key)

    async def set_user_sessions(
        self,
        user_id: str,
        session_ids: List[str],
        ttl: int = 3600
    ) -> None:
        """设置用户会话列表缓存"""
        cache_key = f"user:{user_id}:sessions"
        await self.cache.set_cache(self.category, cache_key, session_ids, ttl=ttl)


class LLMCacheService:
    """LLM 响应缓存服务"""

    def __init__(self, cache: RedisCacheManager):
        self.cache = cache
        self.category = "llm"
        self.default_ttl = 3600  # 1 小时

    def generate_cache_key(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int
    ) -> str:
        """生成 LLM 缓存键"""
        # 简化版: 使用消息摘要
        message_str = json.dumps(messages, sort_keys=True)
        content = f"{model}:{hashlib.md5(message_str.encode()).hexdigest()}:{temperature}:{max_tokens}"
        return hashlib.md5(content.encode()).hexdigest()

    async def get_response(
        self,
        cache_key: str
    ) -> Optional[Dict[str, Any]]:
        """获取 LLM 响应缓存"""
        return await self.cache.get_cache(self.category, cache_key)

    async def set_response(
        self,
        cache_key: str,
        response: Dict[str, Any],
        ttl: Optional[int] = None
    ) -> None:
        """设置 LLM 响应缓存"""
        await self.cache.set_cache(
            self.category,
            cache_key,
            response,
            ttl=ttl or self.default_ttl
        )

    async def invalidate_by_pattern(self, pattern: str) -> int:
        """按模式失效缓存"""
        return await self.cache.delete_cache_pattern(f"{self.category}:{pattern}")


class RouteCacheService:
    """路线缓存服务"""

    def __init__(self, cache: RedisCacheManager):
        self.cache = cache
        self.category = "route"
        self.default_ttl = 3600  # 1 小时

    async def get_route(
        self,
        origin: str,
        destination: str,
        waypoints: List[str]
    ) -> Optional[Dict[str, Any]]:
        """获取路线缓存"""
        waypoint_key = ":".join(sorted(waypoints)) if waypoints else "none"
        cache_key = f"{origin}:{destination}:{waypoint_key}"
        return await self.cache.get_cache(self.category, cache_key)

    async def set_route(
        self,
        origin: str,
        destination: str,
        waypoints: List[str],
        route_data: Dict[str, Any],
        ttl: Optional[int] = None
    ) -> None:
        """设置路线缓存"""
        waypoint_key = ":".join(sorted(waypoints)) if waypoints else "none"
        cache_key = f"{origin}:{destination}:{waypoint_key}"
        await self.cache.set_cache(
            self.category,
            cache_key,
            route_data,
            ttl=ttl or self.default_ttl
        )

    async def invalidate_area(self, city: str) -> int:
        """失效城市所有路线缓存"""
        return await self.cache.delete_cache_pattern(f"{self.category}:{city}:*")


# ==================== 缓存统计 ====================

class CacheStats:
    """缓存统计"""

    def __init__(self, cache: RedisCacheManager):
        self.cache = cache
        self.hits = 0
        self.misses = 0
        self.writes = 0
        self.invalidations = 0

    async def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        total = self.hits + self.misses
        hit_rate = self.hits / total if total > 0 else 0

        return {
            "hits": self.hits,
            "misses": self.misses,
            "writes": self.writes,
            "invalidations": self.invalidations,
            "total_requests": total,
            "hit_rate": round(hit_rate, 4),
        }

    def record_hit(self) -> None:
        """记录缓存命中"""
        self.hits += 1

    def record_miss(self) -> None:
        """记录缓存未命中"""
        self.misses += 1

    def record_write(self) -> None:
        """记录写操作"""
        self.writes += 1

    def record_invalidation(self) -> None:
        """记录失效操作"""
        self.invalidations += 1

    def reset(self) -> None:
        """重置统计"""
        self.hits = 0
        self.misses = 0
        self.writes = 0
        self.invalidations = 0
