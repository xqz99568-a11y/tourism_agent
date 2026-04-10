"""
User Preference Persistence Service
用户偏好持久化服务
支持 Redis + PostgreSQL 双存储
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from app.core.context import UserPreferences
from app.core.logger import get_logger

if TYPE_CHECKING:
    from app.storage.session_store import RedisSessionStore

logger = get_logger(__name__)


@dataclass
class UserProfile:
    """用户画像"""
    user_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    preferences: UserPreferences = field(default_factory=UserPreferences)
    travel_history: List[Dict[str, Any]] = field(default_factory=list)
    feedback: Dict[str, Any] = field(default_factory=dict)
    statistics: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def update_preferences(self, preferences: UserPreferences) -> None:
        """更新偏好"""
        self.preferences = preferences
        self.updated_at = datetime.utcnow()

    def add_travel_record(self, record: Dict[str, Any]) -> None:
        """添加旅行记录"""
        self.travel_history.append({
            **record,
            "timestamp": datetime.utcnow().isoformat(),
        })
        self.updated_at = datetime.utcnow()

    def add_feedback(self, feedback_type: str, data: Dict[str, Any]) -> None:
        """添加反馈"""
        if feedback_type not in self.feedback:
            self.feedback[feedback_type] = []

        self.feedback[feedback_type].append({
            **data,
            "timestamp": datetime.utcnow().isoformat(),
        })
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "preferences": {
                "travel_style": self.preferences.travel_style,
                "budget_level": self.preferences.budget_level,
                "tourist_type": self.preferences.tourist_type,
                "preferred_seasons": self.preferences.preferred_seasons,
                "dietary_restrictions": self.preferences.dietary_restrictions,
                "mobility_requirements": self.preferences.mobility_requirements,
                "special_needs": self.preferences.special_needs,
                "liked_attractions": self.preferences.liked_attractions,
                "disliked_attractions": self.preferences.disliked_attractions,
                "preferred_destinations": self.preferences.preferred_destinations,
                "average_trip_duration": self.preferences.average_trip_duration,
            },
            "travel_history": self.travel_history,
            "feedback": self.feedback,
            "statistics": self.statistics,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserProfile":
        """从字典创建用户画像"""
        preferences = UserPreferences(
            travel_style=data.get("preferences", {}).get("travel_style", []),
            budget_level=data.get("preferences", {}).get("budget_level", "medium"),
            tourist_type=data.get("preferences", {}).get("tourist_type", "general"),
            preferred_seasons=data.get("preferences", {}).get("preferred_seasons", []),
            dietary_restrictions=data.get("preferences", {}).get("dietary_restrictions", []),
            mobility_requirements=data.get("preferences", {}).get("mobility_requirements", []),
            special_needs=data.get("preferences", {}).get("special_needs", []),
            liked_attractions=data.get("preferences", {}).get("liked_attractions", []),
            disliked_attractions=data.get("preferences", {}).get("disliked_attractions", []),
            preferred_destinations=data.get("preferences", {}).get("preferred_destinations", []),
            average_trip_duration=data.get("preferences", {}).get("average_trip_duration"),
        )

        return cls(
            user_id=data["user_id"],
            created_at=datetime.fromisoformat(data.get("created_at", datetime.utcnow().isoformat())),
            updated_at=datetime.fromisoformat(data.get("updated_at", datetime.utcnow().isoformat())),
            preferences=preferences,
            travel_history=data.get("travel_history", []),
            feedback=data.get("feedback", {}),
            statistics=data.get("statistics", {}),
            metadata=data.get("metadata", {}),
        )


class PreferenceLearner:
    """
    偏好学习器
    从用户行为中学习偏好
    """

    def __init__(self):
        self._weight_decay = 0.95

    def learn_from_interaction(
        self,
        profile: UserProfile,
        interaction_type: str,
        data: Dict[str, Any],
    ) -> UserProfile:
        """从交互中学习偏好"""
        if interaction_type == "attraction_view":
            self._learn_attraction_view(profile, data)
        elif interaction_type == "attraction_like":
            self._learn_attraction_like(profile, data)
        elif interaction_type == "attraction_dislike":
            self._learn_attraction_dislike(profile, data)
        elif interaction_type == "booking":
            self._learn_booking(profile, data)
        elif interaction_type == "feedback":
            self._learn_feedback(profile, data)
        elif interaction_type == "search":
            self._learn_search(profile, data)

        profile.updated_at = datetime.utcnow()
        return profile

    def _learn_attraction_view(self, profile: UserProfile, data: Dict[str, Any]) -> None:
        """学习景点浏览"""
        attraction_name = data.get("attraction_name")
        category = data.get("category", "unknown")
        duration = data.get("duration", 0)

        # 增加景点浏览计数
        if "viewed_attractions" not in profile.statistics:
            profile.statistics["viewed_attractions"] = {}

        profile.statistics["viewed_attractions"][attraction_name] = \
            profile.statistics["viewed_attractions"].get(attraction_name, 0) + 1

        # 学习类别偏好
        if "category_views" not in profile.statistics:
            profile.statistics["category_views"] = {}

        profile.statistics["category_views"][category] = \
            profile.statistics["category_views"].get(category, 0) + 1

    def _learn_attraction_like(self, profile: UserProfile, data: Dict[str, Any]) -> None:
        """学习景点喜欢"""
        attraction_name = data.get("attraction_name")
        tags = data.get("tags", [])

        if attraction_name not in profile.preferences.liked_attractions:
            profile.preferences.liked_attractions.append(attraction_name)

        # 从喜欢的景点中学习标签偏好
        for tag in tags:
            if tag not in profile.preferences.travel_style:
                # 标签可以暗示旅行风格
                profile.preferences.travel_style.append(tag)

    def _learn_attraction_dislike(self, profile: UserProfile, data: Dict[str, Any]) -> None:
        """学习景点不喜欢"""
        attraction_name = data.get("attraction_name")

        if attraction_name not in profile.preferences.disliked_attractions:
            profile.preferences.disliked_attractions.append(attraction_name)

        # 从不喜欢的景点中移除
        if attraction_name in profile.preferences.liked_attractions:
            profile.preferences.liked_attractions.remove(attraction_name)

    def _learn_booking(self, profile: UserProfile, data: Dict[str, Any]) -> None:
        """学习预订行为"""
        destination = data.get("destination")
        budget = data.get("budget", 0)
        duration = data.get("duration", 0)

        # 更新旅行历史
        profile.add_travel_record({
            "type": "booking",
            "destination": destination,
            "budget": budget,
            "duration": duration,
        })

        # 学习目的地偏好
        if destination and destination not in profile.preferences.preferred_destinations:
            profile.preferences.preferred_destinations.append(destination)

        # 更新平均行程时长
        if profile.preferences.average_trip_duration is None:
            profile.preferences.average_trip_duration = duration
        else:
            profile.preferences.average_trip_duration = int(
                profile.preferences.average_trip_duration * self._weight_decay +
                duration * (1 - self._weight_decay)
            )

        # 更新统计信息
        if "total_trips" not in profile.statistics:
            profile.statistics["total_trips"] = 0
        profile.statistics["total_trips"] += 1

        if "total_spent" not in profile.statistics:
            profile.statistics["total_spent"] = 0
        profile.statistics["total_spent"] += budget

    def _learn_feedback(self, profile: UserProfile, data: Dict[str, Any]) -> None:
        """学习反馈"""
        feedback_type = data.get("feedback_type", "general")
        rating = data.get("rating")
        attraction_name = data.get("attraction_name")

        # 添加反馈记录
        profile.add_feedback(feedback_type, {
            "rating": rating,
            "attraction_name": attraction_name,
            "comment": data.get("comment", ""),
        })

        # 如果评分低，学习不喜欢的标签
        if rating and rating < 3 and attraction_name:
            tags = data.get("tags", [])
            for tag in tags:
                if tag in profile.preferences.travel_style:
                    profile.preferences.travel_style.remove(tag)

    def _learn_search(self, profile: UserProfile, data: Dict[str, Any]) -> None:
        """学习搜索行为"""
        keywords = data.get("keywords", [])

        # 更新搜索统计
        if "search_keywords" not in profile.statistics:
            profile.statistics["search_keywords"] = {}

        for keyword in keywords:
            profile.statistics["search_keywords"][keyword] = \
                profile.statistics["search_keywords"].get(keyword, 0) + 1

    def infer_budget_level(self, profile: UserProfile) -> str:
        """推断预算级别"""
        total_spent = profile.statistics.get("total_spent", 0)
        total_trips = profile.statistics.get("total_trips", 0)

        if total_trips == 0:
            return profile.preferences.budget_level

        avg_budget = total_spent / total_trips

        # 根据平均消费推断预算级别
        if avg_budget < 1000:
            return "economy"
        elif avg_budget < 5000:
            return "medium"
        else:
            return "luxury"

    def infer_travel_style(self, profile: UserProfile) -> List[str]:
        """推断旅行风格"""
        category_views = profile.statistics.get("category_views", {})

        if not category_views:
            return profile.preferences.travel_style

        # 基于浏览最多的类别推断旅行风格
        style_map = {
            "历史文化": "文化",
            "自然风光": "自然",
            "美食": "美食",
            "冒险": "冒险",
            "亲子": "家庭",
            "浪漫": "浪漫",
        }

        inferred_styles = []
        for category, count in sorted(category_views.items(), key=lambda x: x[1], reverse=True)[:3]:
            if category in style_map:
                style = style_map[category]
                if style not in inferred_styles:
                    inferred_styles.append(style)

        return inferred_styles


class PreferencePersistenceService:
    """
    偏好持久化服务
    支持 Redis 缓存 + PostgreSQL 持久化
    """

    def __init__(self, session_store: Optional["RedisSessionStore"] = None):
        self.session_store = session_store
        self._learner = PreferenceLearner()
        self._cache: Dict[str, UserProfile] = {}
        self._cache_ttl = 3600  # 1小时

    async def get_profile(self, user_id: str) -> UserProfile:
        """获取用户画像"""
        # 先查内存缓存
        if user_id in self._cache:
            return self._cache[user_id]

        # TODO: 从 PostgreSQL 加载
        # 暂时使用默认画像
        profile = UserProfile(user_id=user_id)
        self._cache[user_id] = profile
        return profile

    async def save_profile(self, profile: UserProfile) -> None:
        """保存用户画像"""
        # 保存到内存缓存
        self._cache[profile.user_id] = profile

        # TODO: 持久化到 PostgreSQL
        logger.debug(f"Saved profile for user {profile.user_id}")

    async def update_preferences(
        self,
        user_id: str,
        preferences: UserPreferences,
    ) -> UserProfile:
        """更新用户偏好"""
        profile = await self.get_profile(user_id)
        profile.update_preferences(preferences)
        await self.save_profile(profile)
        return profile

    async def learn_from_interaction(
        self,
        user_id: str,
        interaction_type: str,
        data: Dict[str, Any],
    ) -> UserProfile:
        """从交互中学习偏好"""
        profile = await self.get_profile(user_id)
        profile = self._learner.learn_from_interaction(profile, interaction_type, data)
        await self.save_profile(profile)
        return profile

    async def get_recommendations(self, user_id: str) -> Dict[str, Any]:
        """获取个性化推荐参数"""
        profile = await self.get_profile(user_id)

        # 基于用户画像推断推荐参数
        inferred_budget = self._learner.infer_budget_level(profile)
        inferred_styles = self._learner.infer_travel_style(profile)

        return {
            "preferred_destinations": profile.preferences.preferred_destinations[-5:],
            "travel_style": inferred_styles or profile.preferences.travel_style,
            "budget_level": inferred_budget,
            "liked_attractions": profile.preferences.liked_attractions[-10:],
            "disliked_attractions": profile.preferences.disliked_attractions[-10:],
            "statistics": profile.statistics,
        }

    async def clear_cache(self, user_id: Optional[str] = None) -> None:
        """清除缓存"""
        if user_id:
            self._cache.pop(user_id, None)
        else:
            self._cache.clear()


# ========== 全局服务实例 ==========

_preference_service: Optional[PreferencePersistenceService] = None


def get_preference_service() -> PreferencePersistenceService:
    """获取偏好服务"""
    global _preference_service
    if _preference_service is None:
        _preference_service = PreferencePersistenceService()
    return _preference_service
