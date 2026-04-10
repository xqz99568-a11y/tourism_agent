"""
Redis Session Store
会话状态管理
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import redis.asyncio as redis

from app.core.config import settings
from app.core.context import SessionContext
from app.core.logger import get_logger

logger = get_logger(__name__)


class RedisSessionStore:
    """
    Redis 会话存储
    管理会话状态和上下文
    """

    def __init__(self):
        self.redis_url = settings.database.redis_url
        self._client: Optional[redis.Redis] = None
        self._prefix = "tourism:session:"
        self._ttl = 3600 * 24 * 7  # 7 天过期

    async def connect(self) -> None:
        """连接 Redis"""
        if self._client is None:
            self._client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            logger.info("Connected to Redis")

    async def close(self) -> None:
        """关闭连接"""
        if self._client:
            await self._client.close()
            self._client = None

    def _key(self, session_id: str) -> str:
        """生成 Redis key"""
        return f"{self._prefix}{session_id}"

    async def get(self, session_id: str) -> Optional[SessionContext]:
        """获取会话"""
        if not self._client:
            await self.connect()

        data = await self._client.get(self._key(session_id))

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
        if not self._client:
            await self.connect()

        data = self._serialize_context(context)
        await self._client.setex(
            self._key(session_id),
            ttl or self._ttl,
            json.dumps(data, default=str),
        )

    async def delete(self, session_id: str) -> None:
        """删除会话"""
        if not self._client:
            await self.connect()

        await self._client.delete(self._key(session_id))

    async def exists(self, session_id: str) -> bool:
        """检查会话是否存在"""
        if not self._client:
            await self.connect()

        return await self._client.exists(self._key(session_id)) > 0

    async def refresh(self, session_id: str) -> None:
        """刷新会话过期时间"""
        if not self._client:
            await self.connect()

        await self._client.expire(self._key(session_id), self._ttl)

    # ============ 辅助方法 ============

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
        if not self._client:
            await self.connect()

        cache_key = f"tourism:cache:{cache_key}"
        await self._client.setex(
            cache_key,
            ttl,
            json.dumps(response, default=str),
        )

    async def get_cached_response(self, cache_key: str) -> Optional[Any]:
        """获取缓存的响应"""
        if not self._client:
            await self.connect()

        cache_key = f"tourism:cache:{cache_key}"
        data = await self._client.get(cache_key)

        if data:
            return json.loads(data)

        return None


# 全局实例
session_store: Optional[RedisSessionStore] = None


async def get_session_store() -> RedisSessionStore:
    """获取会话存储"""
    global session_store
    if session_store is None:
        session_store = RedisSessionStore()
    return session_store
