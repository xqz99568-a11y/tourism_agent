"""
Recommendation Service
个性化推荐服务
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
import re

from app.core.logger import get_logger
from app.schemas import AttractionSchema

logger = get_logger(__name__)


@dataclass
class UserProfile:
    """用户画像"""
    user_id: str

    # 基础属性
    travel_styles: List[str] = field(default_factory=list)
    budget_level: str = "medium"
    tourist_type: str = "general"
    age_group: Optional[str] = None
    group_type: Optional[str] = None

    # 饮食偏好
    dietary_restrictions: List[str] = field(default_factory=list)

    # 行为特征
    pace_preference: str = "moderate"  # tight/moderate/relaxed
    accessibility_needs: bool = False

    # 学习到的偏好
    liked_attractions: List[str] = field(default_factory=list)
    disliked_attractions: List[str] = field(default_factory=list)
    liked_categories: Set[str] = field(default_factory=set)
    disliked_categories: Set[str] = field(default_factory=set)
    liked_tags: Set[str] = field(default_factory=set)

    # 统计信息
    total_trips: int = 0
    avg_trip_duration: float = 0
    total_spent: float = 0

    # 隐式偏好
    implicit_preferences: Dict[str, float] = field(default_factory=dict)


class PreferenceLearner:
    """
    偏好学习器
    从用户交互中学习偏好
    """

    # 显式偏好关键词
    EXPLICIT_LIKE_PATTERNS = [
        r"喜欢", r"想(去|看|玩|吃)", r"推荐", r"好(的|玩|吃)",
        r"想去", r"下次还去", r"满意",
    ]

    EXPLICIT_DISLIKE_PATTERNS = [
        r"不想", r"讨厌", r"不(喜欢|想去|好吃)", r"差", r"失望",
        r"再也不去", r"后悔",
    ]

    EXPLICIT_BUDGET_PATTERNS = [
        (r"穷游", "economy"),
        (r"省钱", "economy"),
        (r"经济", "economy"),
        (r"奢华", "luxury"),
        (r"高端", "luxury"),
        (r"豪华", "luxury"),
        (r"舒适", "medium"),
        (r"中等", "medium"),
    ]

    def __init__(self):
        self._like_patterns = [re.compile(p) for p in self.EXPLICIT_LIKE_PATTERNS]
        self._dislike_patterns = [re.compile(p) for p in self.EXPLICIT_DISLIKE_PATTERNS]

    def learn_from_interaction(
        self,
        profile: UserProfile,
        interaction_type: str,
        data: Dict[str, Any],
    ) -> UserProfile:
        """
        从交互中学习

        Args:
            profile: 当前用户画像
            interaction_type: 交互类型
            data: 交互数据

        Returns:
            UserProfile: 更新后的画像
        """
        if interaction_type == "message":
            self._learn_from_message(profile, data.get("message", ""))
        elif interaction_type == "attraction_view":
            self._learn_from_view(profile, data)
        elif interaction_type == "attraction_like":
            self._learn_from_like(profile, data)
        elif interaction_type == "attraction_dislike":
            self._learn_from_dislike(profile, data)
        elif interaction_type == "booking":
            self._learn_from_booking(profile, data)
        elif interaction_type == "feedback":
            self._learn_from_feedback(profile, data)

        return profile

    def _learn_from_message(self, profile: UserProfile, message: str) -> None:
        """从消息中学习"""
        # 检查是否表达喜欢
        for pattern in self._like_patterns:
            if pattern.search(message):
                profile.implicit_preferences["positive"] = (
                    profile.implicit_preferences.get("positive", 0) + 0.1
                )
                break

        # 检查是否表达不喜欢
        for pattern in self._dislike_patterns:
            if pattern.search(message):
                profile.implicit_preferences["negative"] = (
                    profile.implicit_preferences.get("negative", 0) + 0.1
                )
                break

        # 检查预算表达
        for pattern, level in self.EXPLICIT_BUDGET_PATTERNS:
            if re.search(pattern, message):
                if profile.budget_level != level:
                    # 双重确认才更新
                    if profile.implicit_preferences.get(f"budget_{level}", 0) > 1:
                        profile.budget_level = level
                    else:
                        profile.implicit_preferences[f"budget_{level}"] = (
                            profile.implicit_preferences.get(f"budget_{level}", 0) + 1
                        )
                break

    def _learn_from_view(self, profile: UserProfile, data: Dict[str, Any]) -> None:
        """从浏览行为学习"""
        attraction_id = data.get("attraction_id", "")
        category = data.get("category", "")
        tags = data.get("tags", [])

        # 浏览时间（如果提供）
        view_duration = data.get("duration", 0)
        if view_duration > 60:  # 超过1分钟
            profile.liked_categories.add(category)
            for tag in tags:
                profile.liked_tags.add(tag)

    def _learn_from_like(self, profile: UserProfile, data: Dict[str, Any]) -> None:
        """从点赞行为学习"""
        attraction_id = data.get("attraction_id", "")
        category = data.get("category", "")
        tags = data.get("tags", [])

        if attraction_id:
            profile.liked_attractions.append(attraction_id)
        profile.liked_categories.add(category)
        for tag in tags:
            profile.liked_tags.add(tag)

        # 移除不喜欢列表
        if attraction_id in profile.disliked_attractions:
            profile.disliked_attractions.remove(attraction_id)

    def _learn_from_dislike(self, profile: UserProfile, data: Dict[str, Any]) -> None:
        """从点踩行为学习"""
        attraction_id = data.get("attraction_id", "")
        category = data.get("category", "")
        tags = data.get("tags", [])

        if attraction_id:
            profile.disliked_attractions.append(attraction_id)
        profile.disliked_categories.add(category)
        for tag in tags:
            profile.implicit_preferences[f"dislike_tag_{tag}"] = (
                profile.implicit_preferences.get(f"dislike_tag_{tag}", 0) + 1
            )

    def _learn_from_booking(self, profile: UserProfile, data: Dict[str, Any]) -> None:
        """从预订行为学习"""
        cost = data.get("cost", 0)
        attraction_id = data.get("attraction_id", "")
        category = data.get("category", "")

        profile.total_trips += 1
        profile.total_spent += cost

        # 预订意味着强烈偏好
        if attraction_id and attraction_id not in profile.liked_attractions:
            profile.liked_attractions.append(attraction_id)
        profile.liked_categories.add(category)

    def _learn_from_feedback(self, profile: UserProfile, data: Dict[str, Any]) -> None:
        """从反馈学习"""
        rating = data.get("rating", 3)  # 默认3星
        comment = data.get("comment", "")

        if rating >= 4:
            profile.implicit_preferences["satisfaction"] = (
                profile.implicit_preferences.get("satisfaction", 0) + (rating - 3) * 0.1
            )
        elif rating <= 2:
            profile.implicit_preferences["dissatisfaction"] = (
                profile.implicit_preferences.get("dissatisfaction", 0) + (3 - rating) * 0.1
            )

        # 从评论中提取偏好
        if comment:
            self._learn_from_message(profile, comment)


class RecommendationService:
    """
    推荐服务
    基于用户画像和上下文提供个性化推荐
    """

    def __init__(self):
        self.learner = PreferenceLearner()

    def recommend_attractions(
        self,
        profile: UserProfile,
        candidates: List[AttractionSchema],
        context: Dict[str, Any],
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        推荐景点

        Args:
            profile: 用户画像
            candidates: 候选景点列表
            context: 当前上下文（目的地、时间等）
            limit: 返回数量

        Returns:
            List[Dict]: 推荐结果列表
        """
        # 1. 基础过滤
        filtered = self._apply_hard_filters(candidates, profile, context)

        # 2. 评分
        scored = [(attraction, self._calculate_match_score(attraction, profile)) for attraction in filtered]

        # 3. 多样性优化
        diversified = self._apply_diversity_optimization(scored, profile, limit)

        # 4. 排序并返回
        diversified.sort(key=lambda x: x[1], reverse=True)

        return [
            {
                "attraction": attr,
                "score": score,
                "reasons": self._generate_reasons(attr, profile),
            }
            for attr, score in diversified[:limit]
        ]

    def _apply_hard_filters(
        self,
        candidates: List[AttractionSchema],
        profile: UserProfile,
        context: Dict[str, Any],
    ) -> List[AttractionSchema]:
        """应用硬过滤条件"""
        filtered = []

        for attraction in candidates:
            # 过滤已浏览过的景点（如果需要）
            if context.get("exclude_viewed") and attraction.poi_id in profile.liked_attractions:
                continue

            # 过滤明确不喜欢的景点
            if attraction.poi_id in profile.disliked_attractions:
                continue

            # 预算过滤
            budget_levels = {
                "economy": 100,
                "medium": 300,
                "luxury": 1000,
            }
            max_price = budget_levels.get(profile.budget_level, 300)
            if attraction.ticket_price and attraction.ticket_price > max_price:
                # 软过滤：降低优先级但不排除
                pass

            # 适老化需求过滤
            if profile.accessibility_needs and attraction.accessibility_score < 0.5:
                continue

            filtered.append(attraction)

        return filtered

    def _calculate_match_score(
        self,
        attraction: AttractionSchema,
        profile: UserProfile,
    ) -> float:
        """计算匹配分数"""
        score = 0.0

        # 1. 评分贡献 (0-40分)
        score += attraction.rating * 8  # 满分5分 * 8 = 40

        # 2. 偏好类别匹配 (0-30分)
        if attraction.category in profile.liked_categories:
            score += 30
        elif attraction.category in profile.disliked_categories:
            score -= 20
        else:
            score += 15  # 中性类别给基础分

        # 3. 标签匹配 (0-20分)
        tag_match = 0
        for tag in attraction.tags:
            if tag in profile.liked_tags:
                tag_match += 5
            profile_tags = {f"dislike_tag_{t}": v for t in profile.liked_tags}
            if tag in profile_tags:
                tag_match -= 3

        score += min(20, tag_match)

        # 4. 适老化评分 (0-10分)
        if profile.accessibility_needs:
            score += attraction.accessibility_score * 10

        # 5. 预算匹配 (0-10分)
        budget_levels = {
            "economy": (0, 100),
            "medium": (100, 300),
            "luxury": (300, 1000),
        }
        price_range = budget_levels.get(profile.budget_level, (100, 300))
        if attraction.ticket_price:
            if price_range[0] <= attraction.ticket_price <= price_range[1]:
                score += 10
            elif attraction.ticket_price < price_range[0]:
                score += 5  # 便宜加分
            else:
                score -= (attraction.ticket_price - price_range[1]) / 50

        # 6. 隐式偏好调整
        satisfaction = profile.implicit_preferences.get("satisfaction", 0)
        dissatisfaction = profile.implicit_preferences.get("dissatisfaction", 0)
        if satisfaction > dissatisfaction:
            score *= 1.1  # 满意度高时放宽推荐
        elif dissatisfaction > satisfaction:
            score *= 0.9  # 满意度低时保守推荐

        return max(0, min(100, score))

    def _apply_diversity_optimization(
        self,
        scored: List[tuple],
        profile: UserProfile,
        limit: int,
    ) -> List[tuple]:
        """应用多样性优化"""
        if limit >= len(scored):
            return scored

        selected = []
        categories_selected = set()

        # 先选一个高分项
        scored.sort(key=lambda x: x[1], reverse=True)
        if scored:
            top = scored[0]
            selected.append(top)
            categories_selected.add(top[0].category)

        # 然后尽量选择不同类别的
        remaining = [s for s in scored if s[0].category not in categories_selected]
        remaining.sort(key=lambda x: x[1], reverse=True)

        for item in remaining:
            if len(selected) >= limit:
                break
            selected.append(item)
            categories_selected.add(item[0].category)

        # 如果还不够，从剩余中按分数选
        if len(selected) < limit:
            remaining = [s for s in scored if s not in selected]
            remaining.sort(key=lambda x: x[1], reverse=True)
            selected.extend(remaining[:limit - len(selected)])

        return selected

    def _generate_reasons(
        self,
        attraction: AttractionSchema,
        profile: UserProfile,
    ) -> List[str]:
        """生成推荐理由"""
        reasons = []

        # 评分原因
        if attraction.rating >= 4.5:
            reasons.append(f"评分高达 {attraction.rating} 分，口碑很好")

        # 类别匹配
        if attraction.category in profile.liked_categories:
            reasons.append(f"符合您喜欢的 {attraction.category} 类型")

        # 标签匹配
        matching_tags = [t for t in attraction.tags if t in profile.liked_tags]
        if matching_tags:
            reasons.append(f"包含您感兴趣的标签: {', '.join(matching_tags[:2])}")

        # 价格合理
        if attraction.ticket_price == 0:
            reasons.append("免费景点，性价比高")
        elif attraction.ticket_price and attraction.ticket_price < 100:
            reasons.append(f"门票仅 {attraction.ticket_price} 元，价格实惠")

        # 适老化
        if profile.accessibility_needs and attraction.accessibility_score >= 0.8:
            reasons.append("适老化设施完善，适合您出行")

        # 默认原因
        if not reasons:
            reasons.append("综合评分不错，值得一去")

        return reasons

    def predict_next_destination(
        self,
        profile: UserProfile,
        history: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        预测下一个目的地

        Args:
            profile: 用户画像
            history: 历史旅行记录

        Returns:
            List[Dict]: 推荐目的地列表
        """
        # 基于历史目的地类型推荐
        recommendations = []

        # 分析历史目的地特征
        history_destinations = [h.get("destination", "") for h in history]
        history_categories = [h.get("categories", []) for h in history]

        # 简化实现：基于偏好推荐
        if profile.travel_styles:
            if "cultural" in profile.travel_styles:
                recommendations.append({
                    "destination": "西安",
                    "reason": "十三朝古都，文化底蕴深厚",
                    "match_score": 0.9,
                })
            if "adventurous" in profile.travel_styles:
                recommendations.append({
                    "destination": "张家界",
                    "reason": "奇峰怪林，适合探险",
                    "match_score": 0.85,
                })
            if "relaxed" in profile.travel_styles:
                recommendations.append({
                    "destination": "大理",
                    "reason": "风花雪月，适合休闲度假",
                    "match_score": 0.88,
                })

        return recommendations[:5]


# 全局实例
recommendation_service = RecommendationService()
