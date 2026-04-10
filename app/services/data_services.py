"""
Service Layer - 业务服务层
提供业务逻辑封装和跨 Repository 协调
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Callable
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models import (
    User, Session as SessionModel, Message, POI, Itinerary,
    Feedback, PreferenceRecord, OperationLog,
    SessionStatus, ItineraryStatus,
)
from app.storage.repositories import (
    UserRepository, SessionRepository, MessageRepository,
    POIRepository, RestaurantRepository, ItineraryRepository,
    FeedbackRepository, OperationLogRepository, CacheRepository,
    get_user_repository, get_session_repository, get_message_repository,
    get_poi_repository, get_itinerary_repository, get_feedback_repository,
    get_operation_log_repository, get_cache_repository,
)
from app.storage.cache_manager import RedisCacheManager, RedisSessionStore, get_cache_manager
from app.storage.vector_service import VectorSearchService, POIEmbedding, get_vector_service
from app.core.context import SessionContext, UserPreferences, TripContext
from app.core.logger import get_logger

logger = get_logger(__name__)


# ==================== Session Service ====================

class SessionService:
    """会话服务"""

    def __init__(
        self,
        session_repo: SessionRepository,
        message_repo: MessageRepository,
        cache_manager: RedisCacheManager,
    ):
        self.session_repo = session_repo
        self.message_repo = message_repo
        self.cache = cache_manager

    async def create_session(
        self,
        user_id: Optional[int] = None,
        dialog_mode: str = "planning",
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> SessionModel:
        """创建新会话"""
        session_id = f"sess_{uuid4().hex}"

        session = await self.session_repo.create(
            session_id=session_id,
            user_id=user_id,
            dialog_mode=dialog_mode,
            ip_address=ip_address,
            user_agent=user_agent,
            status=SessionStatus.ACTIVE.value,
            expires_at=datetime.utcnow() + timedelta(days=7),
        )

        # 更新缓存中的用户会话列表
        if user_id:
            user = await self.session_repo.session.get(User)
            if user:
                await self.cache.lpush(
                    f"session:user:{user_id}:list",
                    session_id
                )

        await self.session_repo.session.commit()
        return session

    async def get_or_create_session(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> tuple[SessionModel, bool]:
        """
        获取或创建会话

        Returns:
            (session, created): 会话和是否新建
        """
        created = False

        if session_id:
            session = await self.session_repo.get_by_session_id(session_id)
            if session:
                return session, False

        session = await self.create_session(user_id=user_id)
        created = True
        return session, created

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        agent_name: Optional[str] = None,
        intent: Optional[str] = None,
        tools_used: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Message:
        """添加消息"""
        session = await self.session_repo.get_by_session_id(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        message = await self.message_repo.create(
            session_id=session.id,
            role=role,
            content=content,
            agent_name=agent_name,
            intent=intent,
            tools_used=tools_used or [],
            metadata=metadata or {},
        )

        # 更新会话统计
        await self.session_repo.increment_message_count(session_id)

        await self.session_repo.session.commit()
        return message

    async def get_conversation_history(
        self,
        session_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """获取对话历史"""
        session = await self.session_repo.get_by_session_id(session_id)
        if not session:
            return []

        messages = await self.message_repo.list_by_session(
            session_id=session.id,
            limit=limit,
        )

        return [
            {
                "role": msg.role,
                "content": msg.content,
                "agent_name": msg.agent_name,
                "timestamp": msg.created_at.isoformat(),
            }
            for msg in messages
        ]

    async def close_session(self, session_id: str) -> Optional[SessionModel]:
        """关闭会话"""
        session = await self.session_repo.update_by_session_id(
            session_id,
            status=SessionStatus.COMPLETED.value,
        )
        await self.session_repo.session.commit()
        return session

    async def cleanup_expired_sessions(self, older_than_days: int = 7) -> int:
        """清理过期会话"""
        sessions = await self.session_repo.get_active_sessions(
            older_than_hours=older_than_days * 24
        )

        count = 0
        for session in sessions:
            await self.session_repo.mark_expired(session.session_id)
            count += 1

        await self.session_repo.session.commit()
        return count


# ==================== User Service ====================

class UserService:
    """用户服务"""

    def __init__(
        self,
        user_repo: UserRepository,
        session_repo: SessionRepository,
        feedback_repo: FeedbackRepository,
        cache_manager: RedisCacheManager,
    ):
        self.user_repo = user_repo
        self.session_repo = session_repo
        self.feedback_repo = feedback_repo
        self.cache = cache_manager

    async def create_or_get_user(
        self,
        user_id: Optional[str] = None,
        email: Optional[str] = None,
        **kwargs
    ) -> User:
        """创建或获取用户"""
        # 优先通过 user_id 查找
        if user_id:
            user = await self.user_repo.get_by_user_id(user_id)
            if user:
                return user

        # 通过邮箱查找
        if email:
            user = await self.user_repo.get_by_email(email)
            if user:
                return user

        # 创建新用户
        if user_id is None:
            user_id = f"user_{uuid4().hex[:16]}"

        user = await self.user_repo.create(user_id=user_id, email=email, **kwargs)
        await self.user_repo.session.commit()
        return user

    async def update_preferences(
        self,
        user_id: int,
        preferences: Dict[str, Any]
    ) -> User:
        """更新用户偏好"""
        user = await self.user_repo.update_preferences(user_id, preferences)
        if not user:
            raise ValueError(f"User not found: {user_id}")

        await self.user_repo.session.commit()
        return user

    async def record_poi_feedback(
        self,
        user_id: int,
        poi_id: str,
        liked: bool
    ) -> User:
        """记录用户对景点的反馈"""
        if liked:
            user = await self.user_repo.add_liked_poi(user_id, poi_id)
        else:
            user = await self.user_repo.add_disliked_poi(user_id, poi_id)

        if not user:
            raise ValueError(f"User not found: {user_id}")

        await self.user_repo.session.commit()
        return user

    async def get_user_profile(
        self,
        user_id: int
    ) -> Optional[Dict[str, Any]]:
        """获取用户画像"""
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            return None

        return {
            "user_id": user.user_id,
            "username": user.username,
            "email": user.email,
            "travel_styles": user.travel_styles,
            "budget_level": user.budget_level,
            "tourist_type": user.tourist_type,
            "dietary_restrictions": user.dietary_restrictions,
            "liked_pois": user.liked_pois,
            "disliked_pois": user.disliked_pois,
            "preferred_cities": user.preferred_cities,
            "total_sessions": user.total_sessions,
            "total_itineraries": user.total_itineraries,
            "last_active_at": user.last_active_at.isoformat() if user.last_active_at else None,
            "created_at": user.created_at.isoformat(),
        }

    async def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """获取用户统计"""
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            return {}

        sessions = await self.session_repo.list_by_user(user_id, limit=1000)
        feedbacks = await self.feedback_repo.list_by_session(user_id)

        return {
            "total_sessions": len(sessions),
            "active_sessions": len([s for s in sessions if s.status == SessionStatus.ACTIVE.value]),
            "total_feedbacks": len(feedbacks),
            "avg_rating": sum(f.overall_rating for f in feedbacks) / len(feedbacks) if feedbacks else 0,
            "liked_pois_count": len(user.liked_pois),
            "disliked_pois_count": len(user.disliked_pois),
        }


# ==================== POI Service ====================

class POIService:
    """景点服务"""

    def __init__(
        self,
        poi_repo: POIRepository,
        vector_service: VectorSearchService,
        cache_manager: RedisCacheManager,
    ):
        self.poi_repo = poi_repo
        self.vector_service = vector_service
        self.cache = cache_manager

    async def search_pois(
        self,
        keyword: Optional[str] = None,
        city: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        min_rating: Optional[float] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[POI]:
        """搜索景点"""
        # 先尝试从数据库查询
        pois = await self.poi_repo.search(
            keyword=keyword,
            city=city,
            category=category,
            tags=tags,
            min_rating=min_rating,
            skip=skip,
            limit=limit,
        )

        # 增加搜索次数
        for poi in pois:
            await self.poi_repo.increment_search_count(poi.poi_id)

        await self.poi_repo.session.commit()
        return pois

    async def get_popular_pois(
        self,
        city: Optional[str] = None,
        limit: int = 20,
    ) -> List[POI]:
        """获取热门景点"""
        return await self.poi_repo.get_popular(city=city, limit=limit)

    async def get_poi_detail(self, poi_id: str) -> Optional[POI]:
        """获取景点详情"""
        return await self.poi_repo.get_by_poi_id(poi_id)

    async def semantic_search_pois(
        self,
        query_text: str,
        embedding_func: Callable[[str], List[float]],
        city: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """语义搜索景点"""
        # 检查缓存
        cache_key = f"semantic:{city}:{category}:{query_text}"
        cached = await self.cache.get_cache("poi", cache_key)
        if cached:
            return cached

        # 执行语义搜索
        results = await self.vector_service.search_by_text(
            query_text=query_text,
            embedding_func=embedding_func,
            top_k=top_k,
            city=city,
            category=category,
            tags=tags,
        )

        # 转换为 POI 对象
        poi_ids = [r.poi_id for r in results if r.poi_id]
        pois = []
        for poi_id in poi_ids:
            poi = await self.poi_repo.get_by_poi_id(poi_id)
            if poi:
                pois.append({
                    "poi_id": poi.poi_id,
                    "name": poi.name,
                    "city": poi.city,
                    "category": poi.category,
                    "tags": poi.tags,
                    "rating": poi.rating,
                    "ticket_price": poi.ticket_price,
                    "description": poi.description,
                })

        # 缓存结果
        await self.cache.set_cache("poi", cache_key, pois, ttl=300)

        return pois

    async def index_poi(self, poi: POI) -> bool:
        """索引景点到向量数据库"""
        embedding = POIEmbedding(
            poi_id=poi.poi_id,
            name=poi.name,
            name_pinyin=poi.name_pinyin,
            description=poi.description,
            category=poi.category,
            tags=poi.tags,
            city=poi.city,
            province=poi.province,
            address=poi.address,
            latitude=poi.latitude,
            longitude=poi.longitude,
            rating=poi.rating,
            ticket_price=poi.ticket_price,
            opening_hours=poi.opening_hours,
            recommended_duration=poi.recommended_duration,
            suitable_for=poi.suitable_for,
            indoor_outdoor=poi.indoor_outdoor,
            intensity=poi.intensity,
            accessibility_score=poi.accessibility_score,
            popularity_score=poi.popularity_score,
        )

        return await self.vector_service.upsert_poi_embedding(embedding)

    async def batch_index_pois(self, pois: List[POI]) -> Dict[str, int]:
        """批量索引景点"""
        embeddings = []
        for poi in pois:
            embedding = POIEmbedding(
                poi_id=poi.poi_id,
                name=poi.name,
                name_pinyin=poi.name_pinyin,
                description=poi.description,
                category=poi.category,
                tags=poi.tags,
                city=poi.city,
                province=poi.province,
                latitude=poi.latitude,
                longitude=poi.longitude,
                rating=poi.rating,
                ticket_price=poi.ticket_price,
                recommended_duration=poi.recommended_duration,
                suitable_for=poi.suitable_for,
                indoor_outdoor=poi.indoor_outdoor,
                intensity=poi.intensity,
                popularity_score=poi.popularity_score,
            )
            embeddings.append(embedding)

        return await self.vector_service.batch_upsert(embeddings)


# ==================== Itinerary Service ====================

class ItineraryService:
    """行程服务"""

    def __init__(
        self,
        itinerary_repo: ItineraryRepository,
        poi_repo: POIRepository,
        cache_manager: RedisCacheManager,
    ):
        self.itinerary_repo = itinerary_repo
        self.poi_repo = poi_repo
        self.cache = cache_manager

    async def create_itinerary(
        self,
        session_id: str,
        user_id: Optional[int] = None,
        title: str = "",
        destination: str = "",
        destination_city: str = "",
        start_date: str = "",
        end_date: str = "",
        duration_days: int = 1,
        total_budget: float = 0,
        **kwargs
    ) -> Itinerary:
        """创建行程"""
        itinerary = await self.itinerary_repo.create(
            session_id=session_id,
            user_id=user_id,
            title=title or f"{destination}旅行计划",
            destination=destination,
            destination_city=destination_city,
            start_date=start_date,
            end_date=end_date,
            duration_days=duration_days,
            total_budget=total_budget,
            estimated_cost=0,
            plan_data={},
            status=ItineraryStatus.DRAFT.value,
            **kwargs
        )
        await self.itinerary_repo.session.commit()
        return itinerary

    async def update_plan(
        self,
        itinerary_id: str,
        plan_data: Dict[str, Any],
        estimated_cost: Optional[float] = None,
    ) -> Itinerary:
        """更新行程计划"""
        updates = {"plan_data": plan_data}
        if estimated_cost is not None:
            updates["estimated_cost"] = estimated_cost

        itinerary = await self.itinerary_repo.update(itinerary_id, **updates)
        if not itinerary:
            raise ValueError(f"Itinerary not found: {itinerary_id}")

        await self.itinerary_repo.session.commit()
        return itinerary

    async def get_itinerary(self, itinerary_id: str) -> Optional[Itinerary]:
        """获取行程"""
        return await self.itinerary_repo.get_by_itinerary_id(itinerary_id)

    async def get_user_itineraries(
        self,
        user_id: int,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Itinerary]:
        """获取用户行程列表"""
        return await self.itinerary_repo.list_by_user(
            user_id=user_id,
            status=status,
            limit=limit,
        )

    async def share_itinerary(self, itinerary_id: str) -> str:
        """分享行程"""
        share_code = await self.itinerary_repo.create_share_code(itinerary_id)
        if not share_code:
            raise ValueError(f"Itinerary not found: {itinerary_id}")

        await self.itinerary_repo.session.commit()
        return share_code

    async def get_shared_itinerary(self, share_code: str) -> Optional[Itinerary]:
        """获取分享的行程"""
        return await self.itinerary_repo.get_share(share_code)

    async def complete_itinerary(self, itinerary_id: str) -> Itinerary:
        """完成行程"""
        itinerary = await self.itinerary_repo.update(
            itinerary_id,
            status=ItineraryStatus.COMPLETED.value,
            completed_at=datetime.utcnow(),
        )
        if not itinerary:
            raise ValueError(f"Itinerary not found: {itinerary_id}")

        await self.itinerary_repo.session.commit()
        return itinerary


# ==================== Feedback Service ====================

class FeedbackService:
    """反馈服务"""

    def __init__(
        self,
        feedback_repo: FeedbackRepository,
        user_repo: UserRepository,
        log_repo: OperationLogRepository,
    ):
        self.feedback_repo = feedback_repo
        self.user_repo = user_repo
        self.log_repo = log_repo

    async def submit_feedback(
        self,
        session_id: str,
        overall_rating: int,
        helpful: bool,
        user_id: Optional[int] = None,
        comment: Optional[str] = None,
        liked_items: Optional[List[str]] = None,
        disliked_items: Optional[List[str]] = None,
        suggestions: Optional[str] = None,
        **kwargs
    ) -> Feedback:
        """提交反馈"""
        feedback = await self.feedback_repo.create(
            session_id=session_id,
            user_id=user_id,
            overall_rating=overall_rating,
            helpful=helpful,
            comment=comment,
            liked_items=liked_items or [],
            disliked_items=disliked_items or [],
            suggestions=suggestions,
            **kwargs
        )

        # 记录日志
        await self.log_repo.create(
            action="feedback_submitted",
            resource_type="feedback",
            resource_id=str(feedback.id),
            message=f"User submitted feedback with rating {overall_rating}",
            session_id=session_id,
            user_id=str(user_id) if user_id else None,
        )

        await self.feedback_repo.session.commit()
        return feedback

    async def get_session_feedbacks(self, session_id: str) -> List[Feedback]:
        """获取会话的反馈"""
        return await self.feedback_repo.list_by_session(session_id)

    async def get_unprocessed_feedbacks(self, limit: int = 50) -> List[Feedback]:
        """获取未处理的反馈"""
        return await self.feedback_repo.list_unprocessed(limit=limit)

    async def process_feedback(self, feedback_id: int) -> Feedback:
        """处理反馈"""
        feedback = await self.feedback_repo.mark_processed(feedback_id)
        if not feedback:
            raise ValueError(f"Feedback not found: {feedback_id}")

        await self.feedback_repo.session.commit()
        return feedback

    async def get_average_rating(self) -> float:
        """获取平均评分"""
        return await self.feedback_repo.get_average_rating()


# ==================== Analytics Service ====================

class AnalyticsService:
    """分析服务"""

    def __init__(
        self,
        session_repo: SessionRepository,
        message_repo: MessageRepository,
        poi_repo: POIRepository,
        feedback_repo: FeedbackRepository,
        log_repo: OperationLogRepository,
        cache_manager: RedisCacheManager,
    ):
        self.session_repo = session_repo
        self.message_repo = message_repo
        self.poi_repo = poi_repo
        self.feedback_repo = feedback_repo
        self.log_repo = log_repo
        self.cache = cache_manager

    async def get_dashboard_stats(self) -> Dict[str, Any]:
        """获取仪表盘统计"""
        # 检查缓存
        cached = await self.cache.get_cache("analytics", "dashboard")
        if cached:
            return cached

        # 统计数据
        total_users = await self.user_repo.count()
        active_sessions = await self.session_repo.get_active_sessions(older_than_hours=24)
        poi_count = await self.poi_repo.count()
        avg_rating = await self.feedback_repo.get_average_rating()

        stats = {
            "total_users": total_users,
            "active_sessions_24h": len(active_sessions),
            "total_pois": poi_count,
            "average_rating": round(avg_rating, 2),
            "generated_at": datetime.utcnow().isoformat(),
        }

        # 缓存 5 分钟
        await self.cache.set_cache("analytics", "dashboard", stats, ttl=300)

        return stats

    async def get_popular_pois_stats(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取热门景点统计"""
        pois = await self.poi_repo.get_popular(limit=limit)
        return [
            {
                "poi_id": poi.poi_id,
                "name": poi.name,
                "city": poi.city,
                "search_count": poi.search_count,
                "recommendation_count": poi.recommendation_count,
                "rating": poi.rating,
                "popularity_score": poi.popularity_score,
            }
            for poi in pois
        ]

    async def get_error_logs(self, hours: int = 24) -> List[Dict[str, Any]]:
        """获取错误日志"""
        logs = await self.log_repo.get_recent_errors(hours=hours)
        return [
            {
                "log_id": log.log_id,
                "action": log.action,
                "message": log.message,
                "details": log.details,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]


# ==================== 工厂函数 ====================

async def create_session_service(
    session: AsyncSession,
    cache_manager: RedisCacheManager,
) -> SessionService:
    """创建会话服务"""
    return SessionService(
        session_repo=get_session_repository(session),
        message_repo=get_message_repository(session),
        cache_manager=cache_manager,
    )


async def create_user_service(
    session: AsyncSession,
    cache_manager: RedisCacheManager,
) -> UserService:
    """创建用户服务"""
    return UserService(
        user_repo=get_user_repository(session),
        session_repo=get_session_repository(session),
        feedback_repo=get_feedback_repository(session),
        cache_manager=cache_manager,
    )


async def create_poi_service(
    session: AsyncSession,
    vector_service: VectorSearchService,
    cache_manager: RedisCacheManager,
) -> POIService:
    """创建 POI 服务"""
    return POIService(
        poi_repo=get_poi_repository(session),
        vector_service=vector_service,
        cache_manager=cache_manager,
    )


async def create_itinerary_service(
    session: AsyncSession,
    cache_manager: RedisCacheManager,
) -> ItineraryService:
    """创建行程服务"""
    return ItineraryService(
        itinerary_repo=get_itinerary_repository(session),
        poi_repo=get_poi_repository(session),
        cache_manager=cache_manager,
    )


async def create_feedback_service(
    session: AsyncSession,
) -> FeedbackService:
    """创建反馈服务"""
    return FeedbackService(
        feedback_repo=get_feedback_repository(session),
        user_repo=get_user_repository(session),
        log_repo=get_operation_log_repository(session),
    )


async def create_analytics_service(
    session: AsyncSession,
    cache_manager: RedisCacheManager,
) -> AnalyticsService:
    """创建分析服务"""
    return AnalyticsService(
        session_repo=get_session_repository(session),
        message_repo=get_message_repository(session),
        poi_repo=get_poi_repository(session),
        feedback_repo=get_feedback_repository(session),
        log_repo=get_operation_log_repository(session),
        cache_manager=cache_manager,
    )
