"""
Pydantic Schemas
数据验证和序列化模型
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ============================================================
# 枚举类型
# ============================================================

class IntentType(str, Enum):
    """意图类型"""
    TRIP_PLANNING = "trip_planning"
    ATTRACTION_RECOMMENDATION = "attraction_recommendation"
    ITINERARY_PLANNING = "itinerary_planning"
    BUDGET_CONTROL = "budget_control"
    WEATHER_ADJUSTMENT = "weather_adjustment"
    DESTINATION_KNOWLEDGE = "destination_knowledge"
    ROUTE_CONSULTATION = "route_consultation"
    GENERAL_CHAT = "general_chat"
    UNKNOWN = "unknown"


class DialogMode(str, Enum):
    """对话模式"""
    QA = "qa"                       # 问答模式：回答用户关于景点、目的地等问题
    PLANNING = "planning"           # 规划模式：制定详细旅行计划
    CHAT = "chat"                   # 闲聊模式：轻松对话，不涉及具体规划


class EmotionType(str, Enum):
    """情感类型"""
    HAPPY = "happy"                 # 开心
    NEUTRAL = "neutral"             # 中性
    FRUSTRATED = "frustrated"      # 沮丧/不耐烦
    CONFUSED = "confused"           # 困惑
    EXCITED = "excited"             # 兴奋
    WORRIED = "worried"             # 担忧
    SATISFIED = "satisfied"         # 满意


class BudgetLevel(str, Enum):
    """预算级别"""
    ECONOMY = "economy"
    MEDIUM = "medium"
    LUXURY = "luxury"


class TravelStyle(str, Enum):
    """旅行风格"""
    RELAXED = "relaxed"
    ADVENTUROUS = "adventurous"
    CULTURAL = "cultural"
    CULINARY = "culinary"
    FAMILY = "family"


class TouristType(str, Enum):
    """游客类型"""
    BACKPACKER = "backpacker"
    FAMILY = "family"
    LUXURY = "luxury"
    COUPLE = "couple"
    SENIOR = "senior"
    GENERAL = "general"


class AgentName(str, Enum):
    """Agent 名称"""
    PLANNER = "planner"
    ATTRACTION = "attraction"
    ITINERARY = "itinerary"
    BUDGET = "budget"
    WEATHER = "weather"
    ROUTE = "route"
    REVIEW = "review"
    QA = "qa"  # 问答 Agent
    CHAT = "chat"  # 闲聊 Agent


# ============================================================
# 个性化相关
# ============================================================

class AgeGroup(str, Enum):
    """年龄段"""
    CHILD = "child"       # 儿童 (0-12)
    TEENAGER = "teenager" # 青少年 (13-17)
    YOUNG = "young"       # 青年 (18-35)
    MIDDLE = "middle"     # 中年 (36-55)
    SENIOR_AGE = "senior" # 老年 (56+)


class GroupType(str, Enum):
    """出行人群类型"""
    SOLO = "solo"               # 独自旅行
    COUPLE_GROUP = "couple"     # 情侣/夫妻
    FAMILY_KIDS = "family_kids" # 家庭(带小孩)
    FAMILY_SENIOR = "family_senior"  # 家庭(带老人)
    FRIENDS = "friends"        # 朋友同行
    GROUP = "group"             # 团体


class DietaryType(str, Enum):
    """饮食偏好类型"""
    NONE = "none"
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    HALAL = "halal"
    KOSHER = "kosher"
    GLUTEN_FREE = "gluten_free"
    SEAFOOD = "seafood"
    SPICY = "spicy"


class PacePreference(str, Enum):
    """旅行节奏偏好"""
    TIGHT = "tight"       # 紧凑：每天多景点
    MODERATE = "moderate" # 适中：每天 2-3 个景点
    RELAXED = "relaxed"   # 轻松：每天 1-2 个景点


# ============================================================
# 规划优化相关
# ============================================================

class ObjectiveType(str, Enum):
    """优化目标类型"""
    MIN_TIME = "min_time"               # 最短时间
    MIN_COST = "min_cost"               # 最低成本
    MAX_EXPERIENCE = "max_experience"   # 最佳体验
    MAX_DIVERSITY = "max_diversity"     # 最多样化
    MIN_WALKING = "min_walking"         # 最少步行
    MAX_ACCESSIBILITY = "max_accessibility"  # 最佳适老化


class ConstraintType(str, Enum):
    """约束类型"""
    HARD = "hard"   # 硬约束：必须满足
    SOFT = "soft"   # 软约束：尽量满足


class ConstraintSchema(BaseModel):
    """约束定义"""
    type: ConstraintType
    category: str  # must_visit, must_eat, time_window, budget, accessibility
    value: Any
    description: Optional[str] = None


class OptimizationPreference(BaseModel):
    """优化偏好"""
    objectives: List[ObjectiveType] = Field(default_factory=list)
    weights: Dict[ObjectiveType, float] = Field(default_factory=dict)  # 自定义权重
    constraints: List[ConstraintSchema] = Field(default_factory=list)
    num_variants: int = Field(default=2, ge=2, le=5)  # 生成几个备选方案


class PlanVariant(BaseModel):
    """规划方案变体"""
    id: str
    name: str  # "经典打卡路线" / "深度文化之旅" / "小众探索路线"
    plan: ItinerarySchema
    highlight: str  # 方案亮点
    metrics: Dict[str, Any] = Field(default_factory=dict)  # 时间/成本/体验评分


class PlanComparison(BaseModel):
    """方案对比"""
    variants: List[PlanVariant] = Field(default_factory=list)
    comparison_metrics: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    pros_cons: Dict[str, List[str]] = Field(default_factory=dict)
    recommendation: Optional[str] = None


class ConflictResolution(BaseModel):
    """冲突解决"""
    has_conflict: bool = False
    conflicts: List[Dict[str, Any]] = Field(default_factory=list)
    resolution_suggestions: List[str] = Field(default_factory=list)
    user_decision_needed: bool = False


# ============================================================
# 用户相关
# ============================================================

class UserPreferencesSchema(BaseModel):
    """用户偏好"""
    travel_styles: List[TravelStyle] = Field(default_factory=list)
    budget_level: BudgetLevel = BudgetLevel.MEDIUM
    tourist_type: TouristType = TouristType.GENERAL
    preferred_seasons: List[str] = Field(default_factory=list)
    dietary_restrictions: List[str] = Field(default_factory=list)
    mobility_requirements: List[str] = Field(default_factory=list)


class UserSchema(BaseModel):
    """用户"""
    user_id: str
    username: Optional[str] = None
    preferences: UserPreferencesSchema = Field(default_factory=UserPreferencesSchema)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================================
# 景点相关
# ============================================================

class LocationSchema(BaseModel):
    """位置"""
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    address: Optional[str] = None
    city: Optional[str] = None


class AttractionSchema(BaseModel):
    """景点"""
    poi_id: str
    name: str
    location: LocationSchema
    rating: float = Field(default=0.0, ge=0, le=5)
    review_count: int = Field(default=0, ge=0)
    tags: List[str] = Field(default_factory=list)
    category: str
    description: Optional[str] = None
    opening_hours: Optional[str] = None
    ticket_price: Optional[float] = Field(default=None, ge=0)
    recommended_duration: int = Field(default=120, ge=10)  # 分钟
    accessibility_score: float = Field(default=1.0, ge=0, le=1)  # 适老化评分
    images: List[str] = Field(default_factory=list)
    phone: Optional[str] = None
    website: Optional[str] = None


# ============================================================
# 行程相关
# ============================================================

class TransportSchema(BaseModel):
    """交通"""
    type: str  # walk, bus, subway, taxi, car
    from_location: str
    to_location: str
    distance_km: float
    duration_minutes: int
    cost: float = 0
    description: Optional[str] = None


class PlannedAttractionSchema(BaseModel):
    """规划的景点"""
    attraction: AttractionSchema
    arrival_time: str  # HH:MM
    departure_time: str  # HH:MM
    ticket_booking: bool = False
    notes: Optional[str] = None


class DayPlanSchema(BaseModel):
    """每日行程"""
    date: date
    day_number: int
    attractions: List[PlannedAttractionSchema] = Field(default_factory=list)
    transports: List[TransportSchema] = Field(default_factory=list)
    total_cost: float = 0
    total_duration_minutes: int = 0
    tips: List[str] = Field(default_factory=list)


class ItinerarySchema(BaseModel):
    """完整行程"""
    destination: str
    start_date: date
    end_date: date
    days: List[DayPlanSchema] = Field(default_factory=list)
    total_budget: float
    estimated_cost: float
    currency: str = "CNY"
    summary: Optional[str] = None


# ============================================================
# 预算相关
# ============================================================

class BudgetItemSchema(BaseModel):
    """预算项目"""
    category: str  # transportation, accommodation, food, tickets, shopping, other
    item: str
    estimated_cost: float
    actual_cost: Optional[float] = None
    is_essential: bool = True


class BudgetSchema(BaseModel):
    """预算"""
    total_budget: float
    spent: float = 0
    remaining: float = 0
    currency: str = "CNY"
    items: List[BudgetItemSchema] = Field(default_factory=list)
    daily_budget: Optional[float] = None


# ============================================================
# 天气相关
# ============================================================

class WeatherCondition(str, Enum):
    """天气状况"""
    SUNNY = "sunny"
    CLOUDY = "cloudy"
    RAINY = "rainy"
    STORMY = "stormy"
    SNOWY = "snowy"
    FOGGY = "foggy"


class WeatherForecastSchema(BaseModel):
    """天气预报"""
    date: date
    condition: WeatherCondition
    temperature_min: float
    temperature_max: float
    humidity: int = Field(default=50, ge=0, le=100)
    wind_speed: float = 0  # m/s
    precipitation_chance: int = Field(default=0, ge=0, le=100)
    uv_index: int = Field(default=5, ge=0, le=11)
    description: Optional[str] = None
    clothing_suggestion: Optional[str] = None
    activity_suggestion: Optional[str] = None


# ============================================================
# Agent 相关
# ============================================================

class TaskSchema(BaseModel):
    """任务"""
    task_id: str
    description: str
    agent_name: AgentName
    dependencies: List[str] = Field(default_factory=list)
    status: str = "pending"  # pending, running, completed, failed
    result: Optional[Any] = None


class AgentResultSchema(BaseModel):
    """Agent 结果"""
    agent_name: AgentName
    success: bool
    content: str
    data: Optional[Dict[str, Any]] = None
    tools_used: List[str] = Field(default_factory=list)
    execution_time_ms: float = 0
    error: Optional[str] = None


class PlanSchema(BaseModel):
    """规划计划"""
    intent: IntentType
    tasks: List[TaskSchema]
    estimated_duration_ms: int = 0
    requires_clarification: bool = False
    clarification_message: Optional[str] = None
    clarification_questions: List[str] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    follow_up_questions: List[str] = Field(default_factory=list)
    requires_review: bool = False


# ============================================================
# 对话相关
# ============================================================

class MessageSchema(BaseModel):
    """消息"""
    message_id: str
    role: str  # user, assistant, system
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    agent_name: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChatRequestSchema(BaseModel):
    """聊天请求"""
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    message: str
    stream: bool = True
    context: Optional[Dict[str, Any]] = None
    # 多模式支持
    mode: Optional[DialogMode] = None  # 如果不指定则自动检测
    # 多模态支持
    image_data: Optional[str] = None   # Base64 编码的图片数据
    image_url: Optional[str] = None    # 或图片 URL


class ChatResponseSchema(BaseModel):
    """聊天响应"""
    session_id: str
    message_id: str
    content: str
    agent_results: List[AgentResultSchema] = Field(default_factory=list)
    itinerary: Optional[ItinerarySchema] = None
    usage: Dict[str, int] = Field(default_factory=dict)
    # 扩展字段
    detected_emotion: Optional[EmotionType] = None
    mode: DialogMode = DialogMode.PLANNING
    suggestions: List[str] = Field(default_factory=list)  # 下一句建议


class EmotionSchema(BaseModel):
    """情感分析结果"""
    emotion: EmotionType
    confidence: float = Field(ge=0, le=1)
    intensity: float = Field(default=0.5, ge=0, le=1)  # 情感强度
    reasoning: Optional[str] = None
    suggested_response_style: Optional[str] = None


class ModeContext(BaseModel):
    """对话模式上下文"""
    current_mode: DialogMode = DialogMode.PLANNING
    mode_confidence: float = Field(default=0.8, ge=0, le=1)
    mode_reasoning: Optional[str] = None
    suggested_mode_switch: Optional[DialogMode] = None
    conversation_state: str = "ongoing"  # ongoing, clarifying, completed


class ImageAnalysisSchema(BaseModel):
    """图片分析结果"""
    recognized: bool = False
    attraction_name: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    related_attractions: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)
