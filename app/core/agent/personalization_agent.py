"""
Personalization Agent - 个性化 Agent
负责用户画像学习、偏好推断和个性化推荐
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from app.core.agent.base import BaseAgent
from app.core.agent.protocol import AgentProtocol, AgentResult, AgentTask, AgentType
from app.core.agent.registry import AgentRegistry
from app.core.agent.message_bus import MessageBus
from app.core.logger import get_logger

if TYPE_CHECKING:
    from app.services.preference_service import UserProfile, PreferencePersistenceService

logger = get_logger(__name__)


@dataclass
class UserInsight:
    """用户洞察"""
    insight_type: str
    content: str
    confidence: float = 0.5
    evidence: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PersonalizationContext:
    """个性化上下文"""
    session_id: str
    user_id: Optional[str]
    current_query: str
    context: Dict[str, Any]
    user_profile: Optional["UserProfile"] = None


class PersonalizationAgent(BaseAgent):
    """
    个性化 Agent
    负责用户画像学习、偏好推断和个性化推荐
    """

    def __init__(
        self,
        name: str = "personalization",
        agent_type: AgentType = AgentType.PERSONALIZATION,
        description: str = "个性化推荐 Agent",
        message_bus: Optional[MessageBus] = None,
        registry: Optional[AgentRegistry] = None,
        preference_service: Optional["PreferencePersistenceService"] = None,
        **kwargs,
    ):
        super().__init__(
            name=name,
            agent_type=agent_type,
            description=description,
            message_bus=message_bus,
            registry=registry,
            **kwargs,
        )

        self.preference_service = preference_service
        self._insights: List[UserInsight] = []
        self._learning_enabled = True

        logger.info("PersonalizationAgent initialized")

    async def _execute(
        self,
        task: AgentTask,
        context: Dict[str, Any],
    ) -> AgentResult:
        """执行个性化任务"""
        action = task.input_data.get("action", "profile")

        if action == "profile":
            return await self._get_profile(task, context)
        elif action == "learn":
            return await self._learn_from_interaction(task, context)
        elif action == "recommend":
            return await self._get_personalized_recommendations(task, context)
        elif action == "insights":
            return await self._generate_insights(task, context)
        elif action == "adjust":
            return await self._adjust_for_context(task, context)
        else:
            return AgentResult(
                task_id=task.id,
                agent_name=self.name,
                success=False,
                error=f"Unknown action: {action}",
            )

    async def _get_profile(
        self,
        task: AgentTask,
        context: Dict[str, Any],
    ) -> AgentResult:
        """获取用户画像"""
        user_id = task.input_data.get("user_id")

        if not user_id or not self.preference_service:
            return AgentResult(
                task_id=task.id,
                agent_name=self.name,
                success=True,
                data={
                    "profile": None,
                    "message": "No preference service available",
                },
                content="用户画像服务暂不可用",
            )

        try:
            profile = await self.preference_service.get_profile(user_id)

            return AgentResult(
                task_id=task.id,
                agent_name=self.name,
                success=True,
                data={
                    "user_id": user_id,
                    "preferences": {
                        "travel_style": profile.preferences.travel_style,
                        "budget_level": profile.preferences.budget_level,
                        "liked_attractions": profile.preferences.liked_attractions,
                        "preferred_destinations": profile.preferences.preferred_destinations,
                    },
                    "statistics": profile.statistics,
                    "travel_history_count": len(profile.travel_history),
                },
                content=self._format_profile(profile),
            )

        except Exception as e:
            logger.error(f"Failed to get profile: {e}")
            return AgentResult(
                task_id=task.id,
                agent_name=self.name,
                success=False,
                error=str(e),
            )

    async def _learn_from_interaction(
        self,
        task: AgentTask,
        context: Dict[str, Any],
    ) -> AgentResult:
        """从交互中学习"""
        user_id = task.input_data.get("user_id")
        interaction_type = task.input_data.get("interaction_type")
        interaction_data = task.input_data.get("data", {})

        if not self._learning_enabled:
            return AgentResult(
                task_id=task.id,
                agent_name=self.name,
                success=True,
                data={"learned": False, "reason": "Learning disabled"},
                content="个性化学习已禁用",
            )

        if not user_id or not self.preference_service:
            # 无需持久化，生成洞察
            insight = self._generate_insight_from_interaction(interaction_type, interaction_data)
            self._insights.append(insight)

            return AgentResult(
                task_id=task.id,
                agent_name=self.name,
                success=True,
                data={
                    "learned": True,
                    "insight": {
                        "type": insight.insight_type,
                        "content": insight.content,
                        "confidence": insight.confidence,
                    },
                },
                content=f"从交互中学到: {insight.content}",
            )

        try:
            profile = await self.preference_service.learn_from_interaction(
                user_id=user_id,
                interaction_type=interaction_type,
                data=interaction_data,
            )

            # 生成洞察
            insight = self._generate_insight_from_interaction(interaction_type, interaction_data)
            self._insights.append(insight)

            return AgentResult(
                task_id=task.id,
                agent_name=self.name,
                success=True,
                data={
                    "learned": True,
                    "profile_updated": True,
                    "insight": {
                        "type": insight.insight_type,
                        "content": insight.content,
                        "confidence": insight.confidence,
                    },
                },
                content=f"已学习并更新用户画像: {insight.content}",
            )

        except Exception as e:
            logger.error(f"Failed to learn from interaction: {e}")
            return AgentResult(
                task_id=task.id,
                agent_name=self.name,
                success=False,
                error=str(e),
            )

    async def _get_personalized_recommendations(
        self,
        task: AgentTask,
        context: Dict[str, Any],
    ) -> AgentResult:
        """获取个性化推荐"""
        user_id = task.input_data.get("user_id")
        destination = task.input_data.get("destination")
        num_recommendations = task.input_data.get("num", 5)

        # 获取推荐参数
        if user_id and self.preference_service:
            try:
                recommendations = await self.preference_service.get_recommendations(user_id)
            except Exception:
                recommendations = self._get_default_recommendations()
        else:
            recommendations = self._get_default_recommendations()

        # 根据目的地调整推荐
        if destination:
            recommendations["destination"] = destination

        # 生成个性化推荐
        personalized = self._apply_personalization(
            recommendations,
            task.input_data.get("query_context"),
        )

        return AgentResult(
            task_id=task.id,
            agent_name=self.name,
            success=True,
            data={
                "recommendations": personalized,
                "based_on": recommendations,
            },
            content=self._format_recommendations(personalized),
        )

    async def _generate_insights(
        self,
        task: AgentTask,
        context: Dict[str, Any],
    ) -> AgentResult:
        """生成用户洞察"""
        insights = self._insights[-10:]  # 最近10条

        if not insights:
            insights = [
                UserInsight(
                    insight_type="general",
                    content="暂无足够数据生成洞察",
                    confidence=0.0,
                )
            ]

        return AgentResult(
            task_id=task.id,
            agent_name=self.name,
            success=True,
            data={
                "insights": [
                    {
                        "type": i.insight_type,
                        "content": i.content,
                        "confidence": i.confidence,
                        "evidence": i.evidence,
                        "timestamp": i.timestamp.isoformat(),
                    }
                    for i in insights
                ],
                "total_insights": len(insights),
            },
            content=self._format_insights(insights),
        )

    async def _adjust_for_context(
        self,
        task: AgentTask,
        context: Dict[str, Any],
    ) -> AgentResult:
        """根据上下文调整推荐"""
        query = task.input_data.get("query", "")
        base_result = task.input_data.get("base_result", {})

        adjustments = []

        # 检测时间相关
        time_keywords = ["早上", "下午", "晚上", "早晨", "几点", "时间"]
        if any(kw in query for kw in time_keywords):
            adjustments.append({
                "type": "time_sensitive",
                "adjustment": "考虑游览时间安排",
                "priority": "high",
            })

        # 检测季节相关
        season_keywords = ["春天", "夏天", "秋天", "冬天", "季节", "天气"]
        if any(kw in query for kw in season_keywords):
            adjustments.append({
                "type": "seasonal",
                "adjustment": "考虑季节性景点特色",
                "priority": "high",
            })

        # 检测人数相关
        people_keywords = ["家庭", "亲子", "孩子", "老人", "情侣", "朋友", "一个人"]
        if any(kw in query for kw in people_keywords):
            adjustments.append({
                "type": "group_appropriate",
                "adjustment": "考虑适合特定人群的景点",
                "priority": "medium",
            })

        # 检测预算相关
        budget_keywords = ["省钱", "穷游", "豪华", "性价比", "便宜"]
        if any(kw in query for kw in budget_keywords):
            adjustments.append({
                "type": "budget_aware",
                "adjustment": "根据预算调整推荐",
                "priority": "medium",
            })

        return AgentResult(
            task_id=task.id,
            agent_name=self.name,
            success=True,
            data={
                "adjustments": adjustments,
                "original_query": query,
            },
            content=self._format_adjustments(adjustments),
        )

    # ========== 辅助方法 ==========

    def _generate_insight_from_interaction(
        self,
        interaction_type: str,
        data: Dict[str, Any],
    ) -> UserInsight:
        """从交互生成洞察"""
        if interaction_type == "attraction_view":
            return UserInsight(
                insight_type="view_history",
                content=f"用户浏览了景点: {data.get('attraction_name', '未知')}",
                confidence=0.6,
                evidence=["用户主动浏览了该景点"],
            )

        elif interaction_type == "attraction_like":
            return UserInsight(
                insight_type="preference",
                content=f"用户喜欢景点类型: {data.get('category', '未知类别')}",
                confidence=0.8,
                evidence=["用户明确表示喜欢该景点"],
            )

        elif interaction_type == "booking":
            return UserInsight(
                insight_type="behavior",
                content=f"用户预订了目的地: {data.get('destination', '未知')}",
                confidence=0.9,
                evidence=["用户完成了预订行为"],
            )

        elif interaction_type == "search":
            return UserInsight(
                insight_type="intent",
                content=f"用户搜索了关键词: {data.get('keywords', [])}",
                confidence=0.5,
                evidence=["用户主动发起搜索"],
            )

        else:
            return UserInsight(
                insight_type="general",
                content=f"用户进行了 {interaction_type} 操作",
                confidence=0.3,
            )

    def _get_default_recommendations(self) -> Dict[str, Any]:
        """获取默认推荐参数"""
        return {
            "travel_style": ["文化", "自然"],
            "budget_level": "medium",
            "preferred_destinations": [],
            "seasonal_considerations": True,
        }

    def _apply_personalization(
        self,
        recommendations: Dict[str, Any],
        query_context: Optional[str],
    ) -> Dict[str, Any]:
        """应用个性化调整"""
        personalized = {**recommendations}

        # 基于旅行风格调整
        travel_styles = recommendations.get("travel_style", [])
        if "冒险" in travel_styles:
            personalized["highlight_types"] = ["户外", "极限", "探险"]
        elif "文化" in travel_styles:
            personalized["highlight_types"] = ["博物馆", "历史", "非遗"]
        elif "美食" in travel_styles:
            personalized["highlight_types"] = ["美食街", "特色餐厅", "夜市"]

        # 基于预算调整
        budget = recommendations.get("budget_level", "medium")
        if budget == "economy":
            personalized["show_free_options"] = True
            personalized["show_discounts"] = True
        elif budget == "luxury":
            personalized["highlight_premium"] = True

        return personalized

    def _format_profile(self, profile: "UserProfile") -> str:
        """格式化用户画像"""
        lines = ["## 用户画像\n"]

        prefs = profile.preferences
        lines.append(f"**旅行风格**: {', '.join(prefs.travel_style) or '待探索'}")
        lines.append(f"**预算级别**: {prefs.budget_level}")
        lines.append(f"**常去目的地**: {', '.join(prefs.preferred_destinations[-3:]) or '暂无'}")

        stats = profile.statistics
        if stats:
            lines.append(f"\n**统计**")
            if "total_trips" in stats:
                lines.append(f"- 已规划行程: {stats['total_trips']} 次")
            if "total_spent" in stats:
                lines.append(f"- 总消费: ¥{stats['total_spent']:.0f}")

        return "\n".join(lines)

    def _format_recommendations(self, recommendations: Dict[str, Any]) -> str:
        """格式化推荐"""
        lines = ["## 个性化推荐\n"]

        if "highlight_types" in recommendations:
            lines.append("**推荐类型**: " + ", ".join(recommendations["highlight_types"]))

        if recommendations.get("show_free_options"):
            lines.append("- 优先展示免费景点")

        if recommendations.get("highlight_premium"):
            lines.append("- 突出高端选择")

        return "\n".join(lines)

    def _format_insights(self, insights: List[UserInsight]) -> str:
        """格式化洞察"""
        lines = ["## 用户洞察\n"]

        for i, insight in enumerate(insights, 1):
            confidence_bar = "★" * int(insight.confidence * 5) + "☆" * (5 - int(insight.confidence * 5))
            lines.append(f"{i}. [{confidence_bar}] {insight.content}")

        return "\n".join(lines)

    def _format_adjustments(self, adjustments: List[Dict[str, Any]]) -> str:
        """格式化调整"""
        if not adjustments:
            return "无需特殊调整"

        lines = ["## 个性化调整\n"]
        for adj in adjustments:
            lines.append(f"- **{adj['type']}**: {adj['adjustment']} (优先级: {adj['priority']})")

        return "\n".join(lines)

    # ========== 配置方法 ==========

    def enable_learning(self) -> None:
        """启用学习"""
        self._learning_enabled = True

    def disable_learning(self) -> None:
        """禁用学习"""
        self._learning_enabled = False

    def clear_insights(self) -> None:
        """清除洞察历史"""
        self._insights.clear()
