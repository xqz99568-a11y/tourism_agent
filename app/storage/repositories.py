"""
Repository Pattern - 数据访问层
提供统一的数据访问接口
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any, Dict, Generic, List, Optional, TypeVar
from uuid import uuid4

from sqlalchemy import select, update, delete, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.storage.models import (
    User, Session as SessionModel, Message, AgentExecution,
    POI, POIRelationship, Restaurant,
    Itinerary, ItineraryPOI,
    Feedback, PreferenceRecord,
    OperationLog, CacheEntry,
    SessionStatus, ItineraryStatus, UserStatus,
)
from app.core.logger import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


# ==================== 基础 Repository ====================

class BaseRepository(ABC, Generic[T]):
    """Repository 基类"""

    def __init__(self, session: AsyncSession):
        self.session = session

    @abstractmethod
    async def get_by_id(self, id: int) -> Optional[T]:
        pass

    @abstractmethod
    async def create(self, data: Dict[str, Any]) -> T:
        pass

    @abstractmethod
    async def update(self, id: int, data: Dict[str, Any]) -> Optional[T]:
        pass

    @abstractmethod
    async def delete(self, id: int) -> bool:
        pass

    async def list(self, skip: int = 0, limit: int = 100) -> List[T]:
        """列表查询"""
        result = await self.session.execute(
            select(self.model).offset(skip).limit(limit)
        )
        return list(result.scalars().all())


# ==================== 用户 Repository ====================

class UserRepository:
    """用户数据访问层"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, id: int) -> Optional[User]:
        """通过 ID 获取用户"""
        result = await self.session.execute(
            select(User).where(User.id == id)
        )
        return result.scalar_one_or_none()

    async def get_by_user_id(self, user_id: str) -> Optional[User]:
        """通过 user_id 获取用户"""
        result = await self.session.execute(
            select(User).where(User.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[User]:
        """通过邮箱获取用户"""
        result = await self.session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def create(self, user_id: Optional[str] = None, **kwargs) -> User:
        """创建用户"""
        if user_id is None:
            user_id = f"user_{uuid4().hex[:16]}"

        user = User(
            user_id=user_id,
            **kwargs
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def update(self, id: int, **kwargs) -> Optional[User]:
        """更新用户"""
        user = await self.get_by_id(id)
        if user is None:
            return None

        for key, value in kwargs.items():
            if hasattr(user, key):
                setattr(user, key, value)

        user.updated_at = datetime.utcnow()
        await self.session.flush()
        return user

    async def update_preferences(self, user_id: int, preferences: Dict[str, Any]) -> Optional[User]:
        """更新用户偏好"""
        user = await self.get_by_id(user_id)
        if user is None:
            return None

        user.preferences = {**user.preferences, **preferences}
        user.updated_at = datetime.utcnow()
        await self.session.flush()
        return user

    async def add_liked_poi(self, user_id: int, poi_id: str) -> Optional[User]:
        """添加喜欢的景点"""
        user = await self.get_by_id(user_id)
        if user is None:
            return None

        if poi_id not in user.liked_pois:
            user.liked_pois = user.liked_pois + [poi_id]
            await self.session.flush()

            # 记录偏好变化
            record = PreferenceRecord(
                user_id=user_id,
                preference_type="liked_poi",
                target_id=poi_id,
                value={"action": "add"},
                source="implicit"
            )
            self.session.add(record)

        return user

    async def add_disliked_poi(self, user_id: int, poi_id: str) -> Optional[User]:
        """添加不喜欢的景点"""
        user = await self.get_by_id(user_id)
        if user is None:
            return None

        if poi_id not in user.disliked_pois:
            user.disliked_pois = user.disliked_pois + [poi_id]
            await self.session.flush()

            record = PreferenceRecord(
                user_id=user_id,
                preference_type="disliked_poi",
                target_id=poi_id,
                value={"action": "add"},
                source="implicit"
            )
            self.session.add(record)

        return user

    async def list(
        self,
        skip: int = 0,
        limit: int = 100,
        status: Optional[str] = None
    ) -> List[User]:
        """列表查询"""
        query = select(User)

        if status:
            query = query.where(User.status == status)

        query = query.offset(skip).limit(limit).order_by(User.created_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count(self, status: Optional[str] = None) -> int:
        """统计数量"""
        query = select(func.count(User.id))

        if status:
            query = query.where(User.status == status)

        result = await self.session.execute(query)
        return result.scalar_one()


# ==================== 会话 Repository ====================

class SessionRepository:
    """会话数据访问层"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, id: int) -> Optional[SessionModel]:
        """通过 ID 获取会话"""
        result = await self.session.execute(
            select(SessionModel)
            .options(selectinload(SessionModel.messages))
            .where(SessionModel.id == id)
        )
        return result.scalar_one_or_none()

    async def get_by_session_id(self, session_id: str) -> Optional[SessionModel]:
        """通过 session_id 获取会话"""
        result = await self.session.execute(
            select(SessionModel)
            .options(selectinload(SessionModel.messages))
            .where(SessionModel.session_id == session_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[int] = None,
        **kwargs
    ) -> SessionModel:
        """创建会话"""
        if session_id is None:
            session_id = f"sess_{uuid4().hex}"

        session = SessionModel(
            session_id=session_id,
            user_id=user_id,
            **kwargs
        )
        self.session.add(session)
        await self.session.flush()
        return session

    async def update(self, id: int, **kwargs) -> Optional[SessionModel]:
        """更新会话"""
        session = await self.get_by_id(id)
        if session is None:
            return None

        for key, value in kwargs.items():
            if hasattr(session, key):
                setattr(session, key, value)

        session.updated_at = datetime.utcnow()
        await self.session.flush()
        return session

    async def update_context(self, session_id: str, context_data: Dict[str, Any]) -> Optional[SessionModel]:
        """更新会话上下文"""
        session = await self.get_by_session_id(session_id)
        if session is None:
            return None

        session.context_data = {**session.context_data, **context_data}
        session.updated_at = datetime.utcnow()
        await self.session.flush()
        return session

    async def increment_message_count(self, session_id: str) -> Optional[SessionModel]:
        """增加消息计数"""
        session = await self.get_by_session_id(session_id)
        if session is None:
            return None

        session.message_count += 1
        session.updated_at = datetime.utcnow()
        await self.session.flush()
        return session

    async def list_by_user(
        self,
        user_id: int,
        skip: int = 0,
        limit: int = 50,
        status: Optional[str] = None
    ) -> List[SessionModel]:
        """获取用户的会话列表"""
        query = select(SessionModel).where(SessionModel.user_id == user_id)

        if status:
            query = query.where(SessionModel.status == status)

        query = query.offset(skip).limit(limit).order_by(SessionModel.updated_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_active_sessions(self, older_than_hours: int = 24) -> List[SessionModel]:
        """获取活跃会话"""
        cutoff_time = datetime.utcnow() - timedelta(hours=older_than_hours)
        result = await self.session.execute(
            select(SessionModel)
            .where(
                and_(
                    SessionModel.status == SessionStatus.ACTIVE.value,
                    SessionModel.updated_at < cutoff_time
                )
            )
        )
        return list(result.scalars().all())

    async def mark_expired(self, session_id: str) -> Optional[SessionModel]:
        """标记会话为过期"""
        return await self.update_by_session_id(session_id, status=SessionStatus.EXPIRED.value)

    async def update_by_session_id(self, session_id: str, **kwargs) -> Optional[SessionModel]:
        """通过 session_id 更新会话"""
        session = await self.get_by_session_id(session_id)
        if session is None:
            return None

        for key, value in kwargs.items():
            if hasattr(session, key):
                setattr(session, key, value)

        session.updated_at = datetime.utcnow()
        await self.session.flush()
        return session


# ==================== 消息 Repository ====================

class MessageRepository:
    """消息数据访问层"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, id: int) -> Optional[Message]:
        """通过 ID 获取消息"""
        result = await self.session.execute(
            select(Message).where(Message.id == id)
        )
        return result.scalar_one_or_none()

    async def create(self, session_id: int, role: str, content: str, **kwargs) -> Message:
        """创建消息"""
        message = Message(
            session_id=session_id,
            role=role,
            content=content,
            **kwargs
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def list_by_session(
        self,
        session_id: int,
        skip: int = 0,
        limit: int = 100,
        role: Optional[str] = None
    ) -> List[Message]:
        """获取会话的消息列表"""
        query = select(Message).where(Message.session_id == session_id)

        if role:
            query = query.where(Message.role == role)

        query = query.offset(skip).limit(limit).order_by(Message.created_at)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_recent(self, session_id: int, limit: int = 10) -> List[Message]:
        """获取最近的消息"""
        result = await self.session.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = list(result.scalars().all())
        return list(reversed(messages))


# ==================== POI Repository ====================

class POIRepository:
    """景点数据访问层"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, id: int) -> Optional[POI]:
        """通过 ID 获取景点"""
        result = await self.session.execute(
            select(POI).where(POI.id == id)
        )
        return result.scalar_one_or_none()

    async def get_by_poi_id(self, poi_id: str) -> Optional[POI]:
        """通过 poi_id 获取景点"""
        result = await self.session.execute(
            select(POI).where(POI.poi_id == poi_id)
        )
        return result.scalar_one_or_none()

    async def create(self, poi_id: str, name: str, city: str, latitude: float,
                    longitude: float, category: str, **kwargs) -> POI:
        """创建景点"""
        poi = POI(
            poi_id=poi_id,
            name=name,
            city=city,
            latitude=latitude,
            longitude=longitude,
            category=category,
            **kwargs
        )
        self.session.add(poi)
        await self.session.flush()
        return poi

    async def update(self, poi_id: str, **kwargs) -> Optional[POI]:
        """更新景点"""
        poi = await self.get_by_poi_id(poi_id)
        if poi is None:
            return None

        for key, value in kwargs.items():
            if hasattr(poi, key):
                setattr(poi, key, value)

        poi.updated_at = datetime.utcnow()
        await self.session.flush()
        return poi

    async def upsert(self, poi_id: str, **kwargs) -> POI:
        """插入或更新"""
        poi = await self.get_by_poi_id(poi_id)
        if poi:
            return await self.update(poi_id, **kwargs)
        else:
            return await self.create(poi_id, **kwargs)

    async def list_by_city(
        self,
        city: str,
        skip: int = 0,
        limit: int = 100,
        category: Optional[str] = None
    ) -> List[POI]:
        """获取城市的景点列表"""
        query = select(POI).where(
            and_(
                POI.city == city,
                POI.is_active == True
            )
        )

        if category:
            query = query.where(POI.category == category)

        query = query.offset(skip).limit(limit).order_by(POI.rating.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def search(
        self,
        keyword: Optional[str] = None,
        city: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        min_rating: Optional[float] = None,
        skip: int = 0,
        limit: int = 50
    ) -> List[POI]:
        """搜索景点"""
        conditions = [POI.is_active == True]

        if city:
            conditions.append(POI.city == city)

        if category:
            conditions.append(POI.category == category)

        if min_rating is not None:
            conditions.append(POI.rating >= min_rating)

        query = select(POI).where(and_(*conditions))

        if keyword:
            keyword_filter = or_(
                POI.name.ilike(f"%{keyword}%"),
                POI.description.ilike(f"%{keyword}%"),
                POI.tags.contains([keyword])
            )
            query = query.where(keyword_filter)

        query = query.offset(skip).limit(limit).order_by(POI.rating.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def increment_search_count(self, poi_id: str) -> Optional[POI]:
        """增加搜索次数"""
        poi = await self.get_by_poi_id(poi_id)
        if poi:
            poi.search_count += 1
            poi.updated_at = datetime.utcnow()
            await self.session.flush()
        return poi

    async def increment_recommendation_count(self, poi_id: str) -> Optional[POI]:
        """增加推荐次数"""
        poi = await self.get_by_poi_id(poi_id)
        if poi:
            poi.recommendation_count += 1
            poi.updated_at = datetime.utcnow()
            await self.session.flush()
        return poi

    async def get_popular(self, city: Optional[str] = None, limit: int = 10) -> List[POI]:
        """获取热门景点"""
        query = select(POI).where(POI.is_active == True)

        if city:
            query = query.where(POI.city == city)

        query = query.order_by(POI.popularity_score.desc()).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count(self, city: Optional[str] = None) -> int:
        """统计数量"""
        query = select(func.count(POI.id)).where(POI.is_active == True)

        if city:
            query = query.where(POI.city == city)

        result = await self.session.execute(query)
        return result.scalar_one()


# ==================== 餐厅 Repository ====================

class RestaurantRepository:
    """餐厅数据访问层"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, id: int) -> Optional[Restaurant]:
        """通过 ID 获取餐厅"""
        result = await self.session.execute(
            select(Restaurant).where(Restaurant.id == id)
        )
        return result.scalar_one_or_none()

    async def get_by_restaurant_id(self, restaurant_id: str) -> Optional[Restaurant]:
        """通过 restaurant_id 获取餐厅"""
        result = await self.session.execute(
            select(Restaurant).where(Restaurant.restaurant_id == restaurant_id)
        )
        return result.scalar_one_or_none()

    async def create(self, restaurant_id: str, name: str, city: str,
                    latitude: float, longitude: float, cuisine_type: str, **kwargs) -> Restaurant:
        """创建餐厅"""
        restaurant = Restaurant(
            restaurant_id=restaurant_id,
            name=name,
            city=city,
            latitude=latitude,
            longitude=longitude,
            cuisine_type=cuisine_type,
            **kwargs
        )
        self.session.add(restaurant)
        await self.session.flush()
        return restaurant

    async def upsert(self, restaurant_id: str, **kwargs) -> Restaurant:
        """插入或更新"""
        restaurant = await self.get_by_restaurant_id(restaurant_id)
        if restaurant:
            for key, value in kwargs.items():
                if hasattr(restaurant, key):
                    setattr(restaurant, key, value)
            restaurant.updated_at = datetime.utcnow()
            await self.session.flush()
            return restaurant
        else:
            return await self.create(restaurant_id, **kwargs)

    async def list_by_city(
        self,
        city: str,
        skip: int = 0,
        limit: int = 100,
        cuisine_type: Optional[str] = None
    ) -> List[Restaurant]:
        """获取城市的餐厅列表"""
        query = select(Restaurant).where(
            and_(
                Restaurant.city == city,
                Restaurant.is_active == True
            )
        )

        if cuisine_type:
            query = query.where(Restaurant.cuisine_type == cuisine_type)

        query = query.offset(skip).limit(limit).order_by(Restaurant.rating.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())


# ==================== 行程 Repository ====================

class ItineraryRepository:
    """行程数据访问层"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, id: int) -> Optional[Itinerary]:
        """通过 ID 获取行程"""
        result = await self.session.execute(
            select(Itinerary)
            .options(selectinload(Itinerary.itinerary_pois))
            .where(Itinerary.id == id)
        )
        return result.scalar_one_or_none()

    async def get_by_itinerary_id(self, itinerary_id: str) -> Optional[Itinerary]:
        """通过 itinerary_id 获取行程"""
        result = await self.session.execute(
            select(Itinerary)
            .options(selectinload(Itinerary.itinerary_pois))
            .where(Itinerary.itinerary_id == itinerary_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        itinerary_id: Optional[str] = None,
        session_id: Optional[str] = None,
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
        if itinerary_id is None:
            itinerary_id = f"itin_{uuid4().hex[:16]}"

        itinerary = Itinerary(
            itinerary_id=itinerary_id,
            session_id=session_id,
            user_id=user_id,
            title=title,
            destination=destination,
            destination_city=destination_city,
            start_date=start_date,
            end_date=end_date,
            duration_days=duration_days,
            total_budget=total_budget,
            **kwargs
        )
        self.session.add(itinerary)
        await self.session.flush()
        return itinerary

    async def update(self, itinerary_id: str, **kwargs) -> Optional[Itinerary]:
        """更新行程"""
        itinerary = await self.get_by_itinerary_id(itinerary_id)
        if itinerary is None:
            return None

        for key, value in kwargs.items():
            if hasattr(itinerary, key):
                setattr(itinerary, key, value)

        itinerary.updated_at = datetime.utcnow()
        await self.session.flush()
        return itinerary

    async def update_plan_data(self, itinerary_id: str, plan_data: Dict[str, Any]) -> Optional[Itinerary]:
        """更新行程计划数据"""
        itinerary = await self.get_by_itinerary_id(itinerary_id)
        if itinerary is None:
            return None

        itinerary.plan_data = plan_data
        itinerary.version += 1
        itinerary.updated_at = datetime.utcnow()
        await self.session.flush()
        return itinerary

    async def list_by_user(
        self,
        user_id: int,
        skip: int = 0,
        limit: int = 50,
        status: Optional[str] = None
    ) -> List[Itinerary]:
        """获取用户的行程列表"""
        query = select(Itinerary).where(Itinerary.user_id == user_id)

        if status:
            query = query.where(Itinerary.status == status)

        query = query.offset(skip).limit(limit).order_by(Itinerary.created_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def list_by_session(
        self,
        session_id: str,
        skip: int = 0,
        limit: int = 50
    ) -> List[Itinerary]:
        """获取会话的行程列表"""
        result = await self.session.execute(
            select(Itinerary)
            .where(Itinerary.session_id == session_id)
            .offset(skip)
            .limit(limit)
            .order_by(Itinerary.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_share(self, share_code: str) -> Optional[Itinerary]:
        """通过分享码获取行程"""
        result = await self.session.execute(
            select(Itinerary).where(Itinerary.share_code == share_code)
        )
        return result.scalar_one_or_none()

    async def create_share_code(self, itinerary_id: str) -> Optional[str]:
        """创建分享码"""
        itinerary = await self.get_by_itinerary_id(itinerary_id)
        if itinerary is None:
            return None

        share_code = uuid4().hex[:8]
        itinerary.share_code = share_code
        itinerary.is_public = True
        itinerary.updated_at = datetime.utcnow()
        await self.session.flush()
        return share_code


# ==================== 反馈 Repository ====================

class FeedbackRepository:
    """反馈数据访问层"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, id: int) -> Optional[Feedback]:
        """通过 ID 获取反馈"""
        result = await self.session.execute(
            select(Feedback).where(Feedback.id == id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        session_id: str,
        overall_rating: int,
        helpful: bool,
        user_id: Optional[int] = None,
        **kwargs
    ) -> Feedback:
        """创建反馈"""
        feedback = Feedback(
            session_id=session_id,
            user_id=user_id,
            overall_rating=overall_rating,
            helpful=helpful,
            **kwargs
        )
        self.session.add(feedback)
        await self.session.flush()
        return feedback

    async def list_by_session(self, session_id: str) -> List[Feedback]:
        """获取会话的反馈"""
        result = await self.session.execute(
            select(Feedback)
            .where(Feedback.session_id == session_id)
            .order_by(Feedback.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_unprocessed(self, skip: int = 0, limit: int = 50) -> List[Feedback]:
        """获取未处理的反馈"""
        result = await self.session.execute(
            select(Feedback)
            .where(Feedback.is_processed == False)
            .offset(skip)
            .limit(limit)
            .order_by(Feedback.created_at.desc())
        )
        return list(result.scalars().all())

    async def mark_processed(self, id: int) -> Optional[Feedback]:
        """标记已处理"""
        feedback = await self.get_by_id(id)
        if feedback is None:
            return None

        feedback.is_processed = True
        feedback.processed_at = datetime.utcnow()
        await self.session.flush()
        return feedback

    async def get_average_rating(self, session_id: Optional[str] = None) -> float:
        """获取平均评分"""
        query = select(func.avg(Feedback.overall_rating))

        if session_id:
            query = query.where(Feedback.session_id == session_id)

        result = await self.session.execute(query)
        avg = result.scalar_one()
        return float(avg) if avg else 0.0


# ==================== 日志 Repository ====================

class OperationLogRepository:
    """操作日志数据访问层"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        action: str,
        resource_type: str,
        message: str,
        level: str = "info",
        **kwargs
    ) -> OperationLog:
        """创建日志"""
        log = OperationLog(
            log_id=f"log_{uuid4().hex}",
            action=action,
            resource_type=resource_type,
            message=message,
            level=level,
            **kwargs
        )
        self.session.add(log)
        await self.session.flush()
        return log

    async def list_by_session(
        self,
        session_id: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[OperationLog]:
        """获取会话的操作日志"""
        result = await self.session.execute(
            select(OperationLog)
            .where(OperationLog.session_id == session_id)
            .offset(skip)
            .limit(limit)
            .order_by(OperationLog.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_user(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[OperationLog]:
        """获取用户的操作日志"""
        result = await self.session.execute(
            select(OperationLog)
            .where(OperationLog.user_id == user_id)
            .offset(skip)
            .limit(limit)
            .order_by(OperationLog.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_action(
        self,
        action: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[OperationLog]:
        """获取指定操作类型的日志"""
        result = await self.session.execute(
            select(OperationLog)
            .where(OperationLog.action == action)
            .offset(skip)
            .limit(limit)
            .order_by(OperationLog.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_recent_errors(self, hours: int = 24, limit: int = 100) -> List[OperationLog]:
        """获取最近的错误日志"""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        result = await self.session.execute(
            select(OperationLog)
            .where(
                and_(
                    OperationLog.level.in_(["error", "critical"]),
                    OperationLog.created_at >= cutoff_time
                )
            )
            .order_by(OperationLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


# ==================== 缓存 Repository ====================

class CacheRepository:
    """缓存数据访问层"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """获取缓存"""
        result = await self.session.execute(
            select(CacheEntry).where(
                and_(
                    CacheEntry.cache_key == cache_key,
                    CacheEntry.expires_at > datetime.utcnow()
                )
            )
        )
        entry = result.scalar_one_or_none()
        if entry:
            entry.hit_count += 1
            entry.last_hit_at = datetime.utcnow()
            await self.session.flush()
            return entry.cache_value
        return None

    async def set(
        self,
        cache_key: str,
        cache_category: str,
        cache_value: Dict[str, Any],
        ttl_seconds: int = 3600
    ) -> CacheEntry:
        """设置缓存"""
        expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)

        result = await self.session.execute(
            select(CacheEntry).where(CacheEntry.cache_key == cache_key)
        )
        entry = result.scalar_one_or_none()

        if entry:
            entry.cache_value = cache_value
            entry.cache_category = cache_category
            entry.ttl_seconds = ttl_seconds
            entry.expires_at = expires_at
            entry.updated_at = datetime.utcnow()
        else:
            entry = CacheEntry(
                cache_key=cache_key,
                cache_category=cache_category,
                cache_value=cache_value,
                ttl_seconds=ttl_seconds,
                expires_at=expires_at
            )
            self.session.add(entry)

        await self.session.flush()
        return entry

    async def delete(self, cache_key: str) -> bool:
        """删除缓存"""
        result = await self.session.execute(
            delete(CacheEntry).where(CacheEntry.cache_key == cache_key)
        )
        await self.session.flush()
        return result.rowcount > 0

    async def delete_by_category(self, cache_category: str) -> int:
        """删除分类下的所有缓存"""
        result = await self.session.execute(
            delete(CacheEntry).where(CacheEntry.cache_category == cache_category)
        )
        await self.session.flush()
        return result.rowcount

    async def cleanup_expired(self) -> int:
        """清理过期缓存"""
        result = await self.session.execute(
            delete(CacheEntry).where(CacheEntry.expires_at < datetime.utcnow())
        )
        await self.session.flush()
        return result.rowcount

    async def get_stats(self, cache_category: Optional[str] = None) -> Dict[str, Any]:
        """获取缓存统计"""
        query = select(
            func.count(CacheEntry.id).label("total"),
            func.sum(CacheEntry.hit_count).label("total_hits"),
            func.avg(CacheEntry.ttl_seconds).label("avg_ttl")
        )

        if cache_category:
            query = query.where(CacheEntry.cache_category == cache_category)

        result = await self.session.execute(query)
        row = result.one()

        return {
            "total_entries": row.total or 0,
            "total_hits": int(row.total_hits or 0),
            "avg_ttl_seconds": float(row.avg_ttl or 0)
        }


# ==================== Agent Execution Repository ====================

class AgentExecutionRepository:
    """Agent 执行记录数据访问层"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        session_id: int,
        agent_name: str,
        agent_type: str,
        **kwargs
    ) -> AgentExecution:
        """创建执行记录"""
        execution = AgentExecution(
            session_id=session_id,
            agent_name=agent_name,
            agent_type=agent_type,
            status="pending",
            **kwargs
        )
        self.session.add(execution)
        await self.session.flush()
        return execution

    async def update_status(
        self,
        execution_id: int,
        status: str,
        **kwargs
    ) -> Optional[AgentExecution]:
        """更新执行状态"""
        result = await self.session.execute(
            select(AgentExecution).where(AgentExecution.id == execution_id)
        )
        execution = result.scalar_one_or_none()
        if execution is None:
            return None

        execution.status = status

        if status == "completed":
            execution.completed_at = datetime.utcnow()
            if execution.started_at:
                execution.execution_time_ms = (
                    execution.completed_at - execution.started_at
                ).total_seconds() * 1000

        for key, value in kwargs.items():
            if hasattr(execution, key):
                setattr(execution, key, value)

        await self.session.flush()
        return execution

    async def list_by_session(
        self,
        session_id: int,
        skip: int = 0,
        limit: int = 100
    ) -> List[AgentExecution]:
        """获取会话的执行记录"""
        result = await self.session.execute(
            select(AgentExecution)
            .where(AgentExecution.session_id == session_id)
            .offset(skip)
            .limit(limit)
            .order_by(AgentExecution.started_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_status(
        self,
        status: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[AgentExecution]:
        """获取指定状态的执行记录"""
        result = await self.session.execute(
            select(AgentExecution)
            .where(AgentExecution.status == status)
            .offset(skip)
            .limit(limit)
            .order_by(AgentExecution.started_at)
        )
        return list(result.scalars().all())


# ==================== 工厂函数 ====================

def get_user_repository(session: AsyncSession) -> UserRepository:
    """获取用户 Repository"""
    return UserRepository(session)


def get_session_repository(session: AsyncSession) -> SessionRepository:
    """获取会话 Repository"""
    return SessionRepository(session)


def get_message_repository(session: AsyncSession) -> MessageRepository:
    """获取消息 Repository"""
    return MessageRepository(session)


def get_poi_repository(session: AsyncSession) -> POIRepository:
    """获取 POI Repository"""
    return POIRepository(session)


def get_restaurant_repository(session: AsyncSession) -> RestaurantRepository:
    """获取餐厅 Repository"""
    return RestaurantRepository(session)


def get_itinerary_repository(session: AsyncSession) -> ItineraryRepository:
    """获取行程 Repository"""
    return ItineraryRepository(session)


def get_feedback_repository(session: AsyncSession) -> FeedbackRepository:
    """获取反馈 Repository"""
    return FeedbackRepository(session)


def get_operation_log_repository(session: AsyncSession) -> OperationLogRepository:
    """获取操作日志 Repository"""
    return OperationLogRepository(session)


def get_cache_repository(session: AsyncSession) -> CacheRepository:
    """获取缓存 Repository"""
    return CacheRepository(session)


def get_agent_execution_repository(session: AsyncSession) -> AgentExecutionRepository:
    """获取 Agent 执行记录 Repository"""
    return AgentExecutionRepository(session)
