"""
Database Models - Extended
SQLAlchemy ORM 模型 - 扩展版本
支持多层数据架构: PostgreSQL + Redis + Vector DB
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, CIDR, INET, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """SQLAlchemy 基类"""
    pass


# ==================== 枚举类型 ====================

class UserStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class BudgetLevel(str, Enum):
    ECONOMY = "economy"      # 经济型
    MEDIUM = "medium"        # 舒适型
    LUXURY = "luxury"        # 豪华型


class TravelStyle(str, Enum):
    RELAXED = "relaxed"      # 轻松休闲
    ADVENTURE = "adventure"  # 冒险挑战
    CULTURAL = "cultural"    # 文化探索
    FOODIE = "foodie"        # 美食之旅
    NATURE = "nature"        # 自然风光
    URBAN = "urban"          # 都市观光


class TouristType(str, Enum):
    SOLO = "solo"            # 独自旅行
    COUPLE = "couple"        # 情侣
    FAMILY = "family"        # 家庭
    FRIENDS = "friends"      # 朋友同行
    SENIOR = "senior"        # 老年人
    STUDENT = "student"      # 学生
    BUSINESS = "business"    # 商务


class SessionStatus(str, Enum):
    ACTIVE = "active"
    IDLE = "idle"
    COMPLETED = "completed"
    EXPIRED = "expired"


class ItineraryStatus(str, Enum):
    DRAFT = "draft"          # 草稿
    ACTIVE = "active"        # 进行中
    COMPLETED = "completed"   # 已完成
    CANCELLED = "cancelled"  # 已取消
    SHARED = "shared"        # 已分享


class POICategory(str, Enum):
    HISTORICAL = "historical"        # 历史遗迹
    NATURE = "nature"                # 自然风光
    MUSEUM = "museum"                # 博物馆
    FOOD = "food"                    # 美食
    ENTERTAINMENT = "entertainment"  # 娱乐
    SHOPPING = "shopping"            # 购物
    NIGHTLIFE = "nightlife"          # 夜生活
    SCENIC = "scenic"                # 景区
    RELIGIOUS = "religious"          # 宗教场所
    RECREATION = "recreation"        # 休闲


class AgentType(str, Enum):
    PLANNER = "planner"              # 规划Agent
    ATTRACTION = "attraction"        # 景点Agent
    ITINERARY = "itinerary"          # 行程Agent
    BUDGET = "budget"                # 预算Agent
    WEATHER = "weather"              # 天气Agent
    MEMORY = "memory"                # 记忆Agent
    REFLECTION = "reflection"        # 反思Agent
    PERSONALIZATION = "personalization"  # 个性化Agent
    QUALITY = "quality"              # 质量Agent


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# ==================== 用户相关表 ====================

class User(Base):
    """用户表 - 扩展版本"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    # 基本信息
    username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, unique=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # 状态
    status: Mapped[str] = mapped_column(String(32), default=UserStatus.ACTIVE.value)

    # 偏好设置 (JSONB 存储结构化偏好)
    preferences: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)

    # 枚举偏好 (便于索引和查询)
    travel_styles: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)
    budget_level: Mapped[str] = mapped_column(String(32), default=BudgetLevel.MEDIUM.value)
    tourist_type: Mapped[str] = mapped_column(String(32), default=TouristType.SOLO.value)
    dietary_restrictions: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)

    # 学习到的偏好 (从交互中学习)
    liked_pois: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)
    disliked_pois: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)
    preferred_destinations: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)
    preferred_cities: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)

    # 偏好标签 (用于标签匹配)
    preference_tags: Mapped[Dict[str, float]] = mapped_column(JSONB, default=dict)

    # 统计信息
    total_sessions: Mapped[int] = mapped_column(Integer, default=0)
    total_itineraries: Mapped[int] = mapped_column(Integer, default=0)
    last_active_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    sessions: Mapped[List["Session"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    feedbacks: Mapped[List["Feedback"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    preferences_records: Mapped[List["PreferenceRecord"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_users_travel_styles", "travel_styles", postgresql_using="gin"),
        Index("ix_users_preferred_cities", "preferred_cities", postgresql_using="gin"),
    )


class PreferenceRecord(Base):
    """用户偏好记录表 - 用于追踪偏好变化"""
    __tablename__ = "preference_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    # 偏好类型
    preference_type: Mapped[str] = mapped_column(String(64))  # liked_poi, disliked_poi, style_changed, etc.
    target_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)  # POI ID, city, etc.

    # 偏好值
    value: Mapped[Dict[str, Any]] = mapped_column(JSONB)

    # 来源
    source: Mapped[str] = mapped_column(String(32), default="implicit")  # explicit, implicit, inferred

    # 上下文
    context: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # 关系
    user: Mapped["User"] = relationship(back_populates="preferences_records")


# ==================== 会话相关表 ====================

class Session(Base):
    """会话表 - 扩展版本"""
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    # 会话状态
    status: Mapped[str] = mapped_column(String(32), default=SessionStatus.ACTIVE.value)

    # 对话模式
    dialog_mode: Mapped[str] = mapped_column(String(32), default="planning")  # qa, planning, chat

    # 上下文数据 (完整上下文存储)
    context_data: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)

    # 对话统计
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)

    # 情感追踪
    detected_emotion: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    emotion_history: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, default=list)

    # 意图追踪
    last_intent: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    intent_history: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, default=list)

    # IP 信息 (用于安全分析)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 关系
    user: Mapped[Optional["User"]] = relationship(back_populates="sessions")
    messages: Mapped[List["Message"]] = relationship(
        back_populates="session",
        order_by="Message.created_at",
        cascade="all, delete-orphan"
    )
    agent_executions: Mapped[List["AgentExecution"]] = relationship(back_populates="session", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_sessions_user_id", "user_id"),
        Index("ix_sessions_status", "status"),
        Index("ix_sessions_created_at", "created_at"),
    )


class Message(Base):
    """消息表 - 扩展版本"""
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), nullable=False)

    role: Mapped[str] = mapped_column(String(32))  # user, assistant, system
    content: Mapped[str] = mapped_column(Text)

    # 元数据
    agent_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    intent: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tools_used: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)

    # 响应信息
    response_time_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    token_usage: Mapped[Optional[Dict[str, int]]] = mapped_column(JSONB)

    # 消息内容类型
    content_type: Mapped[str] = mapped_column(String(32), default="text")  # text, html, markdown, structured

    # 附件
    attachments: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, default=list)

    # 扩展元数据
    extra_metadata: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)

    # 情感信息
    sentiment: Mapped[Optional[Dict[str, float]]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # 关系
    session: Mapped["Session"] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_messages_session_id", "session_id"),
        Index("ix_messages_created_at", "created_at"),
        Index("ix_messages_role", "role"),
    )


class AgentExecution(Base):
    """Agent 执行记录表"""
    __tablename__ = "agent_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), nullable=False)

    # Agent 信息
    agent_name: Mapped[str] = mapped_column(String(64))
    agent_type: Mapped[str] = mapped_column(String(32))

    # 执行状态
    status: Mapped[str] = mapped_column(String(32))  # pending, running, completed, failed

    # 执行时间
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    execution_time_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 输入输出
    input_data: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    output_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    # 依赖关系
    depends_on: Mapped[List[int]] = mapped_column(ARRAY(Integer), default=list)  # 依赖的 execution IDs
    execution_order: Mapped[int] = mapped_column(Integer, default=0)

    # 资源使用
    token_usage: Mapped[Optional[Dict[str, int]]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # 关系
    session: Mapped["Session"] = relationship(back_populates="agent_executions")

    __table_args__ = (
        Index("ix_agent_executions_session_id", "session_id"),
        Index("ix_agent_executions_agent_name", "agent_name"),
        Index("ix_agent_executions_started_at", "started_at"),
    )


# ==================== POI 相关表 ====================

class POI(Base):
    """景点表 - 扩展版本"""
    __tablename__ = "pois"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    poi_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    name_en: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    name_pinyin: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    # 位置信息
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    address: Mapped[Optional[str]] = mapped_column(Text)
    city: Mapped[str] = mapped_column(String(64))
    city_code: Mapped[str] = mapped_column(String(32))
    province: Mapped[Optional[str]] = mapped_column(String(64))
    district: Mapped[Optional[str]] = mapped_column(String(64))

    # 分类 (多标签)
    category: Mapped[str] = mapped_column(String(64), index=True)
    subcategory: Mapped[Optional[str]] = mapped_column(String(64))
    tags: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)

    # 详细描述
    description: Mapped[Optional[str]] = mapped_column(Text)
    short_description: Mapped[Optional[str]] = mapped_column(String(256))

    # 评分
    rating: Mapped[float] = mapped_column(Float, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    rating_distribution: Mapped[Dict[str, int]] = mapped_column(JSONB, default=dict)  # {"5": 100, "4": 50, ...}

    # 运营信息
    opening_hours: Mapped[Optional[str]] = mapped_column(Text)
    ticket_price: Mapped[Optional[float]] = mapped_column(Float)
    ticket_note: Mapped[Optional[str]] = mapped_column(Text)
    recommended_duration: Mapped[int] = mapped_column(Integer, default=120)  # 分钟

    # 适老化信息
    accessibility_score: Mapped[float] = mapped_column(Float, default=1.0)
    has_wheelchair_access: Mapped[bool] = mapped_column(Boolean, default=False)
    has_elevator: Mapped[bool] = mapped_column(Boolean, default=False)
    has_seating: Mapped[bool] = mapped_column(Boolean, default=True)

    # 物理属性
    indoor_outdoor: Mapped[str] = mapped_column(String(16), default="mixed")
    intensity: Mapped[str] = mapped_column(String(16), default="medium")  # low, medium, high
    walk_level: Mapped[str] = mapped_column(String(16), default="medium")

    # 最佳游览时间
    best_seasons: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)
    best_time_of_day: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)

    # 适合人群
    suitable_for: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)

    # 联系信息
    phone: Mapped[Optional[str]] = mapped_column(String(32))
    website: Mapped[Optional[str]] = mapped_column(String(256))
    images: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)

    # 嵌入向量 (可选，主要存储在向量数据库)
    embedding: Mapped[Optional[List[float]]] = mapped_column(JSONB, nullable=True)
    embedding_model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # 统计数据
    popularity_score: Mapped[float] = mapped_column(Float, default=0)
    search_count: Mapped[int] = mapped_column(Integer, default=0)
    recommendation_count: Mapped[int] = mapped_column(Integer, default=0)

    # 数据来源
    data_source: Mapped[str] = mapped_column(String(32), default="amap")  # amap, manual, import
    source_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_pois_city", "city"),
        Index("ix_pois_category", "category"),
        Index("ix_pois_tags", "tags", postgresql_using="gin"),
        Index("ix_pois_rating", "rating"),
        Index("ix_pois_popularity", "popularity_score"),
        Index("ix_pois_coordinates", "latitude", "longitude"),
        Index("ix_pois_suitable_for", "suitable_for", postgresql_using="gin"),
    )


class POIRelationship(Base):
    """景点关系表 - 存储景点之间的关联"""
    __tablename__ = "poi_relationships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 关联的 POI
    source_poi_id: Mapped[str] = mapped_column(String(128), index=True)
    target_poi_id: Mapped[str] = mapped_column(String(128), index=True)

    # 关系类型
    relationship_type: Mapped[str] = mapped_column(String(64))  # nearby, similar, same_chain, alternate

    # 关系属性
    distance_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    travel_time_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    similarity_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 元数据
    extra_metadata: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("source_poi_id", "target_poi_id", "relationship_type"),
        Index("ix_poi_rel_source", "source_poi_id"),
        Index("ix_poi_rel_target", "target_poi_id"),
    )


class Restaurant(Base):
    """餐厅表"""
    __tablename__ = "restaurants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    restaurant_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    name_en: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    # 位置
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    address: Mapped[Optional[str]] = mapped_column(Text)
    city: Mapped[str] = mapped_column(String(64))
    district: Mapped[Optional[str]] = mapped_column(String(64))

    # 分类
    cuisine_type: Mapped[str] = mapped_column(String(64))
    price_level: Mapped[str] = mapped_column(String(16), default="medium")  # budget, medium, high
    tags: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)

    # 评分
    rating: Mapped[float] = mapped_column(Float, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)

    # 营业信息
    opening_hours: Mapped[Optional[str]] = mapped_column(Text)
    average_price: Mapped[Optional[float]] = mapped_column(Float)

    # 特色
    features: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)  # 亲子, 情侣, 商务, 等
    dietary_options: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)  # 素食, 清真, 等

    # 联系
    phone: Mapped[Optional[str]] = mapped_column(String(32))
    images: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)

    # 适老化
    accessibility_score: Mapped[float] = mapped_column(Float, default=1.0)

    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_restaurants_city", "city"),
        Index("ix_restaurants_cuisine", "cuisine_type"),
        Index("ix_restaurants_rating", "rating"),
    )


# ==================== 行程相关表 ====================

class Itinerary(Base):
    """行程表 - 扩展版本"""
    __tablename__ = "itineraries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    itinerary_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    # 基本信息
    title: Mapped[str] = mapped_column(String(256))
    destination: Mapped[str] = mapped_column(String(256))
    destination_city: Mapped[str] = mapped_column(String(64))
    start_date: Mapped[str] = mapped_column(String(16))  # YYYY-MM-DD
    end_date: Mapped[str] = mapped_column(String(16))
    duration_days: Mapped[int] = mapped_column(Integer)

    # 行程数据 (每日计划)
    plan_data: Mapped[Dict[str, Any]] = mapped_column(JSONB)

    # 预算
    total_budget: Mapped[float] = mapped_column(Float)
    estimated_cost: Mapped[float] = mapped_column(Float)
    actual_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    budget_breakdown: Mapped[Dict[str, float]] = mapped_column(JSONB, default=dict)

    # 参与者信息
    num_travelers: Mapped[int] = mapped_column(Integer, default=1)
    traveler_ages: Mapped[List[int]] = mapped_column(ARRAY(Integer), default=list)
    group_type: Mapped[str] = mapped_column(String(32), default="solo")

    # 偏好
    travel_styles: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)
    special_requirements: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)

    # 状态和版本
    status: Mapped[str] = mapped_column(String(32), default=ItineraryStatus.DRAFT.value)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)

    # 分享
    share_code: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)

    # 统计
    poi_count: Mapped[int] = mapped_column(Integer, default=0)
    estimated_duration_hours: Mapped[float] = mapped_column(Float, default=0)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_itineraries_user_id", "user_id"),
        Index("ix_itineraries_status", "status"),
        Index("ix_itineraries_destination", "destination"),
        Index("ix_itineraries_created_at", "created_at"),
    )


class ItineraryPOI(Base):
    """行程-景点关联表"""
    __tablename__ = "itinerary_pois"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    itinerary_id: Mapped[int] = mapped_column(ForeignKey("itineraries.id"), nullable=False)
    poi_id: Mapped[str] = mapped_column(String(128), nullable=False)

    # 位置信息
    day_number: Mapped[int] = mapped_column(Integer)  # 第几天
    order_in_day: Mapped[int] = mapped_column(Integer)  # 当天第几个

    # 时间安排
    planned_start_time: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)  # HH:MM
    planned_end_time: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    actual_start_time: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    actual_end_time: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)

    # 费用
    estimated_ticket: Mapped[float] = mapped_column(Float, default=0)
    actual_ticket: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 状态
    status: Mapped[str] = mapped_column(String(32), default="planned")  # planned, visited, skipped
    notes: Mapped[Optional[str]] = mapped_column(Text)
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 用户评分 1-5

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("itinerary_id", "day_number", "order_in_day"),
        Index("ix_itinerary_pois_itinerary", "itinerary_id"),
        Index("ix_itinerary_pois_poi", "poi_id"),
    )


# ==================== 反馈相关表 ====================

class Feedback(Base):
    """反馈表"""
    __tablename__ = "feedbacks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    itinerary_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # 评分
    overall_rating: Mapped[int] = mapped_column(Integer)  # 1-5
    recommendation_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-5
    accuracy_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-5

    # 帮助性
    helpful: Mapped[bool] = mapped_column(Boolean)

    # 反馈内容
    comment: Mapped[Optional[str]] = mapped_column(Text)
    liked_items: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)
    disliked_items: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)

    # 改进建议
    suggestions: Mapped[Optional[str]] = mapped_column(Text)

    # 偏好反馈
    preference_updates: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)

    # 是否已处理
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # 关系
    user: Mapped[Optional["User"]] = relationship(back_populates="feedbacks")

    __table_args__ = (
        Index("ix_feedbacks_session_id", "session_id"),
        Index("ix_feedbacks_created_at", "created_at"),
    )


# ==================== 日志相关表 ====================

class OperationLog(Base):
    """操作日志表 - MongoDB 风格存储"""
    __tablename__ = "operation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    log_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    # 用户信息
    user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    # 操作信息
    action: Mapped[str] = mapped_column(String(64), index=True)
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # 级别
    level: Mapped[str] = mapped_column(String(16), default=LogLevel.INFO.value)

    # 内容
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)

    # 来源
    source: Mapped[str] = mapped_column(String(64), default="api")  # api, agent, tool, system
    agent_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # 性能
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 环境
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_op_logs_user_id", "user_id"),
        Index("ix_op_logs_session_id", "session_id"),
        Index("ix_op_logs_action", "action"),
        Index("ix_op_logs_created_at", "created_at"),
        Index("ix_op_logs_level", "level"),
    )


# ==================== 缓存相关表 ====================

class CacheEntry(Base):
    """缓存条目表 - 用于持久化缓存"""
    __tablename__ = "cache_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 缓存键
    cache_key: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    cache_category: Mapped[str] = mapped_column(String(64), index=True)  # poi, weather, route, etc.

    # 缓存值
    cache_value: Mapped[Dict[str, Any]] = mapped_column(JSONB)

    # 元数据
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    last_hit_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # TTL
    ttl_seconds: Mapped[int] = mapped_column(Integer, default=3600)  # 默认 1 小时
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_cache_category", "cache_category"),
        Index("ix_cache_expires", "expires_at"),
    )


# ==================== 模型列表 ====================

# 核心模型
MODELS = [
    User,
    PreferenceRecord,
    Session,
    Message,
    AgentExecution,
    POI,
    POIRelationship,
    Restaurant,
    Itinerary,
    ItineraryPOI,
    Feedback,
    OperationLog,
    CacheEntry,
]

# 创建表的顺序 (考虑外键依赖)
CREATE_ORDER = [
    User,
    PreferenceRecord,
    Session,
    Message,
    AgentExecution,
    POI,
    POIRelationship,
    Restaurant,
    Itinerary,
    ItineraryPOI,
    Feedback,
    OperationLog,
    CacheEntry,
]
