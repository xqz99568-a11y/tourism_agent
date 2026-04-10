"""
Reflection Agent - 自我反思 Agent
负责检查执行结果、识别问题并提出改进建议
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.core.agent.base import BaseAgent
from app.core.agent.protocol import AgentProtocol, AgentResult, AgentTask, AgentType
from app.core.agent.registry import AgentRegistry
from app.core.agent.message_bus import MessageBus
from app.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ReflectionCriteria:
    """反思标准"""
    name: str
    description: str
    weight: float = 1.0
    threshold: float = 0.5


class ReflectionAgent(BaseAgent):
    """
    自我反思 Agent
    检查执行结果质量，识别潜在问题，提出改进建议
    """

    DEFAULT_CRITERIA = [
        ReflectionCriteria(
            name="completeness",
            description="结果是否完整回答了用户问题",
            weight=1.5,
            threshold=0.6,
        ),
        ReflectionCriteria(
            name="accuracy",
            description="结果中的信息是否准确",
            weight=2.0,
            threshold=0.7,
        ),
        ReflectionCriteria(
            name="relevance",
            description="结果是否与用户意图相关",
            weight=1.5,
            threshold=0.6,
        ),
        ReflectionCriteria(
            name="coherence",
            description="结果逻辑是否连贯一致",
            weight=1.0,
            threshold=0.5,
        ),
        ReflectionCriteria(
            name="helpfulness",
            description="结果对用户是否有帮助",
            weight=1.0,
            threshold=0.5,
        ),
    ]

    def __init__(
        self,
        name: str = "reflection",
        agent_type: AgentType = AgentType.REFLECTION,
        description: str = "自我反思 Agent",
        message_bus: Optional[MessageBus] = None,
        registry: Optional[AgentRegistry] = None,
        criteria: Optional[List[ReflectionCriteria]] = None,
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

        self.criteria = criteria or self.DEFAULT_CRITERIA

        logger.info(f"ReflectionAgent initialized with {len(self.criteria)} criteria")

    async def _execute(
        self,
        task: AgentTask,
        context: Dict[str, Any],
    ) -> AgentResult:
        """执行反思"""
        result_data = task.input_data.get("result", {})
        original_content = result_data.get("content", "")
        original_data = result_data.get("data", {})

        # 执行各项反思检查
        scores = []
        issues = []
        suggestions = []

        # 1. 完整性检查
        completeness = self._check_completeness(original_content, original_data)
        scores.append(("completeness", completeness))
        if completeness < 0.6:
            issues.append("结果可能不完整")
            suggestions.append("请补充更多相关信息")

        # 2. 一致性检查
        coherence = self._check_coherence(original_content)
        scores.append(("coherence", coherence))
        if coherence < 0.5:
            issues.append("结果存在逻辑不一致")
            suggestions.append("请检查并修正逻辑矛盾")

        # 3. 有用性检查
        helpfulness = self._check_helpfulness(original_content)
        scores.append(("helpfulness", helpfulness))
        if helpfulness < 0.5:
            issues.append("结果可能不够有帮助")
            suggestions.append("请提供更实用的建议或信息")

        # 4. 可执行性检查（如果有步骤）
        executability = self._check_executability(original_content)
        scores.append(("executability", executability))
        if executability < 0.5:
            issues.append("建议可能无法直接执行")
            suggestions.append("请提供更具体的执行步骤")

        # 计算加权总分
        total_score = 0.0
        total_weight = 0.0
        for name, score in scores:
            for criterion in self.criteria:
                if criterion.name == name:
                    total_score += score * criterion.weight
                    total_weight += criterion.weight
                    break

        overall_score = total_score / total_weight if total_weight > 0 else 0.0

        # 生成反思报告
        report = self._generate_report(
            overall_score=overall_score,
            scores=scores,
            issues=issues,
            suggestions=suggestions,
        )

        return AgentResult(
            task_id=task.id,
            agent_name=self.name,
            success=True,
            data={
                "overall_score": overall_score,
                "scores": dict(scores),
                "issues": issues,
                "suggestions": suggestions,
                "needs_improvement": overall_score < 0.6,
            },
            content=report,
            warnings=issues,
            suggestions=suggestions,
        )

    def _check_completeness(
        self,
        content: str,
        data: Dict[str, Any],
    ) -> float:
        """检查完整性"""
        score = 0.0

        # 检查内容长度
        if len(content) > 100:
            score += 0.3
        elif len(content) > 50:
            score += 0.2
        else:
            score += 0.1

        # 检查是否有数据
        if data:
            score += 0.3

        # 检查是否包含关键部分
        key_indicators = ["景点", "行程", "预算", "建议", "推荐"]
        matches = sum(1 for indicator in key_indicators if indicator in content)
        score += min(0.4, matches * 0.1)

        return min(1.0, score)

    def _check_coherence(self, content: str) -> float:
        """检查连贯性"""
        score = 0.5  # 基础分数

        # 检查是否有矛盾关键词
        contradictions = [
            ("建议", "不推荐"),  # 如果同时出现这两个词，可能是矛盾的
        ]

        for pos, neg in contradictions:
            if pos in content and neg in content:
                # 检查是否在同一句中
                lines = content.split("\n")
                for line in lines:
                    if pos in line and neg in line:
                        score -= 0.2
                        break

        # 检查逻辑连接词的使用
        connectors = ["因为", "所以", "但是", "因此", "而且"]
        connector_count = sum(content.count(c) for c in connectors)
        if connector_count > 2:
            score += 0.2
        elif connector_count > 0:
            score += 0.1

        return max(0.0, min(1.0, score))

    def _check_helpfulness(self, content: str) -> float:
        """检查有用性"""
        score = 0.0

        # 检查是否有实用建议
        helpful_phrases = [
            "建议", "推荐", "可以", "适合",
            "注意", "提醒", "最好", "建议您",
        ]

        helpful_count = sum(content.count(phrase) for phrase in helpful_phrases)
        score += min(0.5, helpful_count * 0.1)

        # 检查是否有具体信息
        specific_indicators = [
            "时间", "地点", "价格", "人数",
            "交通", "住宿", "餐饮",
        ]

        specific_count = sum(1 for ind in specific_indicators if ind in content)
        score += min(0.5, specific_count * 0.1)

        return min(1.0, score)

    def _check_executability(self, content: str) -> float:
        """检查可执行性"""
        score = 0.0

        # 检查是否包含时间或步骤
        step_indicators = ["第1天", "第2天", "第一步", "第二天", "早上", "下午", "晚上"]
        step_count = sum(1 for ind in step_indicators if ind in content)
        score += min(0.4, step_count * 0.1)

        # 检查是否有具体描述
        detail_words = ["具体", "详细", "如下", "包括", "包含"]
        detail_count = sum(1 for w in detail_words if w in content)
        score += min(0.3, detail_count * 0.1)

        # 检查是否有行动项
        action_verbs = ["去", "参观", "游览", "品尝", "体验", "安排"]
        action_count = sum(1 for v in action_verbs if v in content)
        score += min(0.3, action_count * 0.05)

        return min(1.0, score)

    def _generate_report(
        self,
        overall_score: float,
        scores: List[tuple],
        issues: List[str],
        suggestions: List[str],
    ) -> str:
        """生成反思报告"""
        lines = ["## 反思报告\n"]

        # 总体评分
        score_desc = "优秀" if overall_score >= 0.8 else \
                      "良好" if overall_score >= 0.6 else \
                      "一般" if overall_score >= 0.4 else "需要改进"
        lines.append(f"**总体评分**: {overall_score:.2f}/1.0 ({score_desc})")

        # 分项评分
        lines.append("\n### 分项评分:")
        for name, score in scores:
            bar = "█" * int(score * 10) + "░" * (10 - int(score * 10))
            lines.append(f"- {name}: [{bar}] {score:.2f}")

        # 发现的问题
        if issues:
            lines.append("\n### 发现的问题:")
            for i, issue in enumerate(issues, 1):
                lines.append(f"{i}. {issue}")

        # 改进建议
        if suggestions:
            lines.append("\n### 改进建议:")
            for i, suggestion in enumerate(suggestions, 1):
                lines.append(f"{i}. {suggestion}")

        return "\n".join(lines)
