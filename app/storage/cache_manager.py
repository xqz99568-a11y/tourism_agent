"""
Enhanced Redis Session Store
增强版 Redis 会话存储
支持多层缓存策略、会话持久化和热点数据缓存
"""
from __future__ import annotations

import json
import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Callable
from dataclasses import asdict

import redis.asyncio as redis

from app.core.config import settings
from app.core.context import SessionContext
from app.core.logger import get_logger

logger = get_logger(__name__)


class RedisCacheManager:
    """
    Redis 缓存管理器
    提供统一的缓存操作接口
    """

    # 缓存前缀
    PREFIX = "tourism"
    SESSION_PREFIX = f"{PREFIX}:session"
    CACHE_PREFIX = f"{PREFIX}:cache"
    LOCK_PREFIX = f"{PREFIX}:lock"
    COUNTER_PREFIX = f"{PREFIX}:counter"
    RATE_LIMIT_PREFIX = f"{PREFIX}:ratelimit"
    HOT_PREFIX = f"{PREFIX}:hot"

    # TTL 配置
    DEFAULT_TTL = 3600 * 24 * 7  # 7 天
    CACHE_TTL = 300  # 5 分钟
    LOCK_TTL = 30  # 30 秒
    RATE_LIMIT_WINDOW = 60  # 1 分钟

    def __init__(self):
        self.redis_url = settings.database.redis_url
        self._client: Optional[redis.Redis] = None
        self._pubsub: Optional[redis.client.PubSub] = None

    async def connect(self) -> None:
        """连接 Redis"""
        if self._client is None:
            self._client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            logger.info("Redis Cache Manager connected")

    async def close(self) -> None:
        """关闭连接"""
        if self._client:
            await self._client.close()
            self._client = None

    @property
    def client(self) -> redis.Redis:
        """获取 Redis 客户端"""
        if self._client is None:
            raise RuntimeError("Redis not connected. Call connect() first.")
        return self._client

    # ==================== 基础操作 ====================

    async def get(self, key: str) -> Optional[str]:
        """获取值"""
        return await self.client.get(f"{self.PREFIX}:{key}")

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        json_encode: bool = True
    ) -> None:
        """设置值"""
        full_key = f"{self.PREFIX}:{key}"
        if json_encode and not isinstance(value, str):
            value = json.dumps(value, default=str)
        if ttl:
            await self.client.setex(full_key, ttl, value)
        else:
            await self.client.set(full_key, value)

    async def delete(self, key: str) -> bool:
        """删除键"""
        result = await self.client.delete(f"{self.PREFIX}:{key}")
        return result > 0

    async def exists(self, key: str) -> bool:
        """检查键是否存在"""
        return await self.client.exists(f"{self.PREFIX}:{key}") > 0

    async def expire(self, key: str, ttl: int) -> bool:
        """设置过期时间"""
        return await self.client.expire(f"{self.PREFIX}:{key}", ttl)

    async def ttl(self, key: str) -> int:
        """获取剩余生存时间"""
        return await self.client.ttl(f"{self.PREFIX}:{key}")

    # ==================== Hash 操作 ====================

    async def hset(self, key: str, field: str, value: Any) -> None:
        """设置 hash 字段"""
        full_key = f"{self.PREFIX}:{key}"
        if not isinstance(value, str):
            value = json.dumps(value, default=str)
        await self.client.hset(full_key, field, value)

    async def hget(self, key: str, field: str) -> Optional[str]:
        """获取 hash 字段"""
        return await self.client.hget(f"{self.PREFIX}:{key}", field)

    async def hgetall(self, key: str) -> Dict[str, str]:
        """获取所有 hash 字段"""
        return await self.client.hgetall(f"{self.PREFIX}:{key}")

    async def hdel(self, key: str, *fields: str) -> int:
        """删除 hash 字段"""
        return await self.client.hdel(f"{self.PREFIX}:{key}", *fields)

    # ==================== List 操作 ====================

    async def lpush(self, key: str, *values: Any) -> int:
        """左推入列表"""
        full_key = f"{self.PREFIX}:{key}"
        str_values = [json.dumps(v, default=str) if not isinstance(v, str) else v for v in values]
        return await self.client.lpush(full_key, *str_values)

    async def rpush(self, key: str, *values: Any) -> int:
        """右推入列表"""
        full_key = f"{self.PREFIX}:{key}"
        str_values = [json.dumps(v, default=str) if not isinstance(v, str) else v for v in values]
        return await self.client.rpush(full_key, *str_values)

    async def lrange(self, key: str, start: int, end: int) -> List[str]:
        """获取列表范围"""
        return await self.client.lrange(f"{self.PREFIX}:{key}", start, end)

    async def ltrim(self, key: str, start: int, end: int) -> bool:
        """修剪列表"""
        return await self.client.ltrim(f"{self.PREFIX}:{key}", start, end)

    # ==================== Sorted Set 操作 ====================

    async def zadd(self, key: str, mapping: Dict[str, float]) -> int:
        """添加有序集合"""
        return await self.client.zadd(f"{self.PREFIX}:{key}", mapping)

    async def zrange(self, key: str, start: int, end: int, withscores: bool = False) -> List[Any]:
        """获取有序集合范围"""
        return await self.client.zrange(f"{self.PREFIX}:{key}", start, end, withscores=withscores)

    async def zrevrange(self, key: str, start: int, end: int, withscores: bool = False) -> List[Any]:
        """获取有序集合倒序范围"""
        return await self.client.zrevrange(f"{self.PREFIX}:{key}", start, end, withscores=withscores)

    async def zrank(self, key: str, member: str) -> Optional[int]:
        """获取成员排名"""
        return await self.client.zrank(f"{self.PREFIX}:{key}", member)

    # ==================== 计数器 ====================

    async def incr(self, key: str, amount: int = 1) -> int:
        """递增计数器"""
        return await self.client.incr(f"{self.COUNTER_PREFIX}:{key}", amount)

    async def decr(self, key: str, amount: int = 1) -> int:
        """递减计数器"""
        return await self.client.decr(f"{self.COUNTER_PREFIX}:{key}", amount)

    async def get_counter(self, key: str) -> int:
        """获取计数器值"""
        value = await self.client.get(f"{self.COUNTER_PREFIX}:{key}")
        return int(value) if value else 0

    # ==================== 分布式锁 ====================

    async def acquire_lock(
        self,
        lock_name: str,
        timeout: int = LOCK_TTL,
        retry_times: int = 3,
        retry_delay: float = 0.1
    ) -> Optional[str]:
        """获取分布式锁"""
        lock_key = f"{self.LOCK_PREFIX}:{lock_name}"
        lock_value = f"{datetime.utcnow().timestamp()}:{id(self)}"

        for _ in range(retry_times):
            if await self.client.set(lock_key, lock_value, nx=True, ex=timeout):
                return lock_value
            await asyncio.sleep(retry_delay)

        return None

    async def release_lock(self, lock_name: str, lock_value: str) -> bool:
        """释放分布式锁"""
        lock_key = f"{self.LOCK_PREFIX}:{lock_name}"

        # 使用 Lua 脚本确保原子性
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        result = await self.client.eval(script, 1, lock_key, lock_value)
        return result == 1

    # ==================== 限流 ====================

    async def check_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int = RATE_LIMIT_WINDOW
    ) -> tuple[bool, int]:
        """
        检查限流
        返回: (是否允许, 剩余请求数)
        """
        rate_key = f"{self.RATE_LIMIT_PREFIX}:{key}"
        current = await self.client.incr(rate_key)

        if current == 1:
            await self.client.expire(rate_key, window_seconds)

        remaining = max(0, max_requests - current)
        allowed = current <= max_requests

        return allowed, remaining

    # ==================== 缓存策略 ====================

    async def get_cache(self, category: str, key: str) -> Optional[Any]:
        """获取缓存"""
        cache_key = f"{self.CACHE_PREFIX}:{category}:{key}"
        data = await self.client.get(cache_key)
        if data:
            return json.loads(data)
        return None

    async def set_cache(
        self,
        category: str,
        key: str,
        value: Any,
        ttl: int = CACHE_TTL
    ) -> None:
        """设置缓存"""
        cache_key = f"{self.CACHE_PREFIX}:{category}:{key}"
        await self.client.setex(cache_key, ttl, json.dumps(value, default=str))

    async def delete_cache(self, category: str, key: str) -> bool:
        """删除缓存"""
        cache_key = f"{self.CACHE_PREFIX}:{category}:{key}"
        return await self.delete(cache_key)

    async def delete_cache_pattern(self, pattern: str) -> int:
        """删除匹配模式的缓存"""
        full_pattern = f"{self.CACHE_PREFIX}:{pattern}"
        keys = []
        async for key in self.client.scan_iter(match=full_pattern, count=100):
            keys.append(key)

        if keys:
            return await self.client.delete(*keys)
        return 0

    # ==================== 热点数据 ====================

    async def increment_hot_score(self, item_key: str, delta: float = 1.0) -> float:
        """增加热点分数"""
        return await self.client.zincrby(f"{self.HOT_PREFIX}:items", delta, item_key)

    async def get_hot_items(self, limit: int = 10) -> List[tuple[str, float]]:
        """获取热点数据"""
        return await self.zrevrange(f"{self.HOT_PREFIX}:items", 0, limit - 1, withscores=True)

    # ==================== 批量操作 ====================

    async def mget(self, keys: List[str]) -> List[Optional[str]]:
        """批量获取"""
        if not keys:
            return []
        full_keys = [f"{self.PREFIX}:{k}" for k in keys]
        return await self.client.mget(full_keys)

    async def mset(self, mapping: Dict[str, Any], ttl: Optional[int] = None) -> None:
        """批量设置"""
        if not mapping:
            return

        pipe = self.client.pipeline()
        for key, value in mapping.items():
            full_key = f"{self.PREFIX}:{key}"
            if not isinstance(value, str):
                value = json.dumps(value, default=str)
            if ttl:
                pipe.setex(full_key, ttl, value)
            else:
                pipe.set(full_key, value)
        await pipe.execute()

    # ==================== 发布订阅 ====================

    async def publish(self, channel: str, message: Any) -> int:
        """发布消息"""
        if not isinstance(message, str):
            message = json.dumps(message, default=str)
        return await self.client.publish(f"{self.PREFIX}:channel:{channel}", message)

    async def subscribe(self, *channels: str) -> redis.client.PubSub:
        """订阅频道"""
        pubsub = self.client.pubsub()
        channel_names = [f"{self.PREFIX}:channel:{ch}" for ch in channels]
        await pubsub.subscribe(*channel_names)
        return pubsub


# ==================== Session Store ====================

class RedisSessionStore:
    """
    Redis 会话存储
    管理会话状态和上下文
    """

    def __init__(self, cache_manager: Optional[RedisCacheManager] = None):
        self._cache = cache_manager or RedisCacheManager()
        self._prefix = RedisCacheManager.SESSION_PREFIX
        self._ttl = RedisCacheManager.DEFAULT_TTL

    async def connect(self) -> None:
        """连接"""
        await self._cache.connect()

    async def close(self) -> None:
        """关闭"""
        await self._cache.close()

    def _key(self, session_id: str) -> str:
        """生成 Redis key"""
        return f"{self._prefix}:{session_id}"

    async def get(self, session_id: str) -> Optional[SessionContext]:
        """获取会话"""
        data = await self._cache.get(self._key(session_id))
        if data:
            try:
                parsed = json.loads(data)
                return self._deserialize_context(parsed)
            except Exception as e:
                logger.error(f"Failed to deserialize session: {e}")
        return None

    async def set(
        self,
        session_id: str,
        context: SessionContext,
        ttl: Optional[int] = None,
    ) -> None:
        """保存会话"""
        data = self._serialize_context(context)
        await self._cache.set(
            self._key(session_id),
            data,
            ttl=ttl or self._ttl
        )

    async def delete(self, session_id: str) -> None:
        """删除会话"""
        await self._cache.delete(self._key(session_id))

    async def exists(self, session_id: str) -> bool:
        """检查会话是否存在"""
        return await self._cache.exists(self._key(session_id))

    async def refresh(self, session_id: str) -> None:
        """刷新会话过期时间"""
        await self._cache.expire(self._key(session_id), self._ttl)

    async def get_or_create(
        self,
        session_id: str,
        creator: Optional[Callable[[], SessionContext]] = None
    ) -> SessionContext:
        """获取或创建会话"""
        context = await self.get(session_id)
        if context is None:
            if creator:
                context = creator()
            else:
                context = SessionContext(session_id=session_id)
            await self.set(session_id, context)
        return context

    # ==================== 辅助方法 ====================

    def _serialize_context(self, context: SessionContext) -> Dict[str, Any]:
        """序列化上下文"""
        return {
            "session_id": context.session_id,
            "created_at": context.created_at.isoformat(),
            "updated_at": context.updated_at.isoformat(),
            "user_id": context.user_id,
            "conversation_history": [
                {
                    "turn_id": turn.turn_id,
                    "user_message": turn.user_message,
                    "ai_message": turn.ai_message,
                    "timestamp": turn.timestamp.isoformat(),
                    "metadata": turn.metadata,
                    "agent_name": turn.agent_name,
                    "tools_used": turn.tools_used,
                    "execution_time_ms": turn.execution_time_ms,
                }
                for turn in context.conversation_history
            ],
            "current_turn": context.current_turn,
            "preferences": {
                "travel_style": context.preferences.travel_style,
                "budget_level": context.preferences.budget_level,
                "tourist_type": context.preferences.tourist_type,
                "preferred_seasons": context.preferences.preferred_seasons,
                "dietary_restrictions": context.preferences.dietary_restrictions,
                "mobility_requirements": context.preferences.mobility_requirements,
                "interests": context.preferences.interests,
                "special_needs": context.preferences.special_needs,
                "special_requirements": context.preferences.special_requirements,
                "liked_attractions": context.preferences.liked_attractions,
                "disliked_attractions": context.preferences.disliked_attractions,
                "preferred_destinations": context.preferences.preferred_destinations,
                "average_trip_duration": context.preferences.average_trip_duration,
            },
            "trip_context": {
                "destination": context.trip_context.destination,
                "departure_place": context.trip_context.departure_place,
                "origin": context.trip_context.origin,
                "start_date": context.trip_context.start_date.isoformat() if context.trip_context.start_date else None,
                "end_date": context.trip_context.end_date.isoformat() if context.trip_context.end_date else None,
                "duration_days": context.trip_context.duration_days,
                "budget_amount": context.trip_context.budget_amount,
                "num_travelers": context.trip_context.num_travelers,
                "traveler_ages": context.trip_context.traveler_ages,
                "is_domestic": context.trip_context.is_domestic,
                "planned_days": context.trip_context.planned_days,
            },
            "metadata": context.metadata,
        }

    def _deserialize_context(self, data: Dict[str, Any]) -> SessionContext:
        """反序列化上下文"""
        from datetime import datetime

        # 重建 ConversationTurns
        turns = []
        for turn_data in data.get("conversation_history", []):
            turns.append(
                {
                    "turn_id": turn_data["turn_id"],
                    "user_message": turn_data["user_message"],
                    "ai_message": turn_data.get("ai_message"),
                    "timestamp": datetime.fromisoformat(turn_data["timestamp"]),
                    "metadata": turn_data.get("metadata", {}),
                    "agent_name": turn_data.get("agent_name"),
                    "tools_used": turn_data.get("tools_used", []),
                    "execution_time_ms": turn_data.get("execution_time_ms"),
                }
            )

        from app.core.context import ConversationTurn, UserPreferences, TripContext

        # 重建 UserPreferences
        prefs_data = data.get("preferences", {})
        preferences = UserPreferences(
            travel_style=prefs_data.get("travel_style", []),
            budget_level=prefs_data.get("budget_level", "medium"),
            tourist_type=prefs_data.get("tourist_type", "general"),
            preferred_seasons=prefs_data.get("preferred_seasons", []),
            dietary_restrictions=prefs_data.get("dietary_restrictions", []),
            mobility_requirements=prefs_data.get("mobility_requirements", []),
            interests=prefs_data.get("interests", []),
            special_needs=prefs_data.get("special_requirements", prefs_data.get("special_needs", [])),
            liked_attractions=prefs_data.get("liked_attractions", []),
            disliked_attractions=prefs_data.get("disliked_attractions", []),
            preferred_destinations=prefs_data.get("preferred_destinations", []),
            average_trip_duration=prefs_data.get("average_trip_duration"),
        )

        # 重建 TripContext
        trip_data = data.get("trip_context", {})
        trip_context = TripContext(
            destination=trip_data.get("destination"),
            departure_place=trip_data.get("origin", trip_data.get("departure_place")),
            start_date=datetime.fromisoformat(trip_data["start_date"]) if trip_data.get("start_date") else None,
            end_date=datetime.fromisoformat(trip_data["end_date"]) if trip_data.get("end_date") else None,
            duration_days=trip_data.get("duration_days"),
            budget_amount=trip_data.get("budget_amount"),
            num_travelers=trip_data.get("num_travelers", 1),
            traveler_ages=trip_data.get("traveler_ages", []),
            is_domestic=trip_data.get("is_domestic", True),
            planned_days=trip_data.get("planned_days", []),
        )

        return SessionContext(
            session_id=data["session_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            user_id=data.get("user_id"),
            preferences=preferences,
            trip_context=trip_context,
            metadata=data.get("metadata", {}),
            conversation_history=[
                ConversationTurn(**turn) for turn in turns
            ],
            current_turn=data.get("current_turn", len(turns)),
        )

    # ==================== LLM 响应缓存 ====================

    async def cache_response(
        self,
        cache_key: str,
        response: Any,
        ttl: int = 300,
    ) -> None:
        """
        缓存 LLM 响应
        用于减少重复请求
        """
        await self._cache.set_cache("llm", cache_key, response, ttl)

    async def get_cached_response(self, cache_key: str) -> Optional[Any]:
        """获取缓存的响应"""
        return await self._cache.get_cache("llm", cache_key)

    # ==================== 会话列表管理 ====================

    async def get_user_sessions(self, user_id: str, limit: int = 50) -> List[str]:
        """获取用户的所有会话 ID"""
        user_sessions_key = f"{self._prefix}:user:{user_id}:sessions"
        session_ids = await self._cache.lrange(user_sessions_key, 0, limit - 1)
        return [json.loads(s) for s in session_ids]

    async def add_user_session(self, user_id: str, session_id: str) -> None:
        """添加用户会话"""
        user_sessions_key = f"{self._prefix}:user:{user_id}:sessions"
        await self._cache.lpush(user_sessions_key, session_id)
        # 保持最多 100 个会话
        await self._cache.ltrim(user_sessions_key, 0, 99)

    async def remove_user_session(self, user_id: str, session_id: str) -> None:
        """移除用户会话"""
        user_sessions_key = f"{self._prefix}:user:{user_id}:sessions"
        # 从列表中移除
        await self._cache.lrem(user_sessions_key, session_id)


# ==================== 全局实例 ====================

_cache_manager: Optional[RedisCacheManager] = None
_session_store: Optional[RedisSessionStore] = None


async def get_cache_manager() -> RedisCacheManager:
    """获取缓存管理器"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = RedisCacheManager()
    return _cache_manager


async def get_session_store() -> RedisSessionStore:
    """获取会话存储"""
    global _session_store
    if _session_store is None:
        _session_store = RedisSessionStore()
    return _session_store


async def init_redis() -> None:
    """初始化 Redis 连接"""
    cache = await get_cache_manager()
    await cache.connect()

    session = await get_session_store()
    await session.connect()

    logger.info("Redis initialized")


async def close_redis() -> None:
    """关闭 Redis 连接"""
    global _cache_manager, _session_store

    if _session_store:
        await _session_store.close()
        _session_store = None

    if _cache_manager:
        await _cache_manager.close()
        _cache_manager = None

    logger.info("Redis closed")


# 添加缺失的 asyncio 导入
import asyncio
