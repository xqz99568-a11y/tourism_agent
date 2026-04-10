"""
Quality Agent - 质量评估 Agent
负责评估答案质量和合规性
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
class QualityDimension:
    """质量维度"""
    name: str
    description: str
    weight: float = 1.0
    min_score: float = 0.0
    max_score: float = 1.0


class QualityAgent(BaseAgent):
    """
    质量评估 Agent
    评估 Agent 输出质量和合规性
    """

    DEFAULT_DIMENSIONS = [
        QualityDimension(
            name="accuracy",
            description="信息准确性",
            weight=2.0,
        ),
        QualityDimension(
            name="relevance",
            description="与用户需求的相关性",
            weight=1.5,
        ),
        QualityDimension(
            name="completeness",
            description="内容完整性",
            weight=1.5,
        ),
        QualityDimension(
            name="clarity",
            description="表达清晰度",
            weight=1.0,
        ),
        QualityDimension(
            name="safety",
            description="内容安全性（无有害信息）",
            weight=2.0,
        ),
        QualityDimension(
            name="appropriateness",
            description="回答适当性",
            weight=1.0,
        ),
    ]

    # 安全关键词（触发安全检查）
    SAFETY_KEYWORDS = [
        "赌博", "色情", "暴力", "毒品", "犯罪",
        "邪教", "自杀", "恐怖", "欺诈",
    ]

    # 不当内容关键词
    INAPPROPRIATE_PATTERNS = [
        "personal information",
        "联系方式",
        "身份证",
        "银行卡",
    ]

    def __init__(
        self,
        name: str = "quality",
        agent_type: AgentType = AgentType.QUALITY,
        description: str = "质量评估 Agent",
        message_bus: Optional[MessageBus] = None,
        registry: Optional[AgentRegistry] = None,
        dimensions: Optional[List[QualityDimension]] = None,
        pass_threshold: float = 0.7,
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

        self.dimensions = dimensions or self.DEFAULT_DIMENSIONS
        self.pass_threshold = pass_threshold

        logger.info(f"QualityAgent initialized with {len(self.dimensions)} dimensions")

    async def _execute(
        self,
        task: AgentTask,
        context: Dict[str, Any],
    ) -> AgentResult:
        """执行质量评估"""
        result_data = task.input_data.get("result", {})
        content = result_data.get("content", "")
        data = result_data.get("data", {})

        # 执行各项质量检查
        dimension_scores: Dict[str, float] = {}
        issues: List[str] = []
        passed = True

        # 1. 安全性检查（最优先）
        safety_score, safety_issues = self._check_safety(content)
        dimension_scores["safety"] = safety_score
        if not safety_issues:
            issues.extend(safety_issues)
        if safety_score < 0.5:
            passed = False

        # 2. 准确性检查
        accuracy_score, accuracy_issues = self._check_accuracy(content, data)
        dimension_scores["accuracy"] = accuracy_score
        issues.extend(accuracy_issues)

        # 3. 相关性检查
        relevance_score, relevance_issues = self._check_relevance(content, context)
        dimension_scores["relevance"] = relevance_score
        issues.extend(relevance_issues)

        # 4. 完整性检查
        completeness_score, completeness_issues = self._check_completeness(content, data)
        dimension_scores["completeness"] = completeness_score
        issues.extend(completeness_issues)

        # 5. 清晰度检查
        clarity_score, clarity_issues = self._check_clarity(content)
        dimension_scores["clarity"] = clarity_score
        issues.extend(clarity_issues)

        # 6. 适当性检查
        appropriateness_score, appropriateness_issues = self._check_appropriateness(content)
        dimension_scores["appropriateness"] = appropriateness_score
        issues.extend(appropriateness_issues)

        # 计算加权总分
        total_score = 0.0
        total_weight = 0.0

        for dim in self.dimensions:
            if dim.name in dimension_scores:
                total_score += dimension_scores[dim.name] * dim.weight
                total_weight += dim.weight

        overall_score = total_score / total_weight if total_weight > 0 else 0.0

        # 检查是否通过
        if overall_score < self.pass_threshold:
            passed = False

        # 生成评估报告
        report = self._generate_report(
            overall_score=overall_score,
            dimension_scores=dimension_scores,
            issues=issues,
            passed=passed,
        )

        return AgentResult(
            task_id=task.id,
            agent_name=self.name,
            success=True,
            data={
                "overall_score": overall_score,
                "dimension_scores": dimension_scores,
                "issues": issues,
                "passed": passed,
                "threshold": self.pass_threshold,
            },
            content=report,
            warnings=issues if not passed else [],
        )

    def _check_safety(
        self,
        content: str,
    ) -> tuple[float, List[str]]:
        """检查安全性"""
        issues = []
        score = 1.0

        # 检查安全关键词
        for keyword in self.SAFETY_KEYWORDS:
            if keyword in content:
                score -= 0.3
                issues.append(f"检测到敏感关键词: {keyword}")

        # 检查不当模式
        for pattern in self.INAPPROPRIATE_PATTERNS:
            if pattern.lower() in content.lower():
                score -= 0.4
                issues.append(f"检测到可能不当内容: {pattern}")

        # 检查是否有外部链接
        if "http://" in content or "https://" in content:
            # 有链接需要谨慎
            score -= 0.1
            issues.append("内容包含外部链接，请确认其安全性")

        return max(0.0, score), issues

    def _check_accuracy(
        self,
        content: str,
        data: Dict[str, Any],
    ) -> tuple[float, List[str]]:
        """检查准确性"""
        issues = []
        score = 0.8  # 基础分数

        # 检查是否有明显的错误表述
        error_indicators = [
            "可能不对",
            "仅供参考",
            "不确定",
            "可能有误",
        ]

        uncertainty_count = sum(1 for ind in error_indicators if ind in content)
        if uncertainty_count > 2:
            score -= 0.2

        # 检查数据是否为空
        if not content and not data:
            score = 0.3
            issues.append("内容为空")

        # 检查是否有具体的数值/日期
        has_specifics = any(char.isdigit() for char in content)
        if not has_specifics:
            score -= 0.1

        return max(0.0, min(1.0, score)), issues

    def _check_relevance(
        self,
        content: str,
        context: Dict[str, Any],
    ) -> tuple[float, List[str]]:
        """检查相关性"""
        issues = []
        score = 0.7  # 基础分数

        # 获取用户意图
        intent = context.get("intent", "")

        # 检查内容是否与意图相关
        intent_keywords = {
            "trip_planning": ["旅行", "行程", "旅游", "景点"],
            "attraction": ["景点", "推荐", "好玩"],
            "budget": ["预算", "费用", "花费", "价格"],
            "itinerary": ["行程", "安排", "计划"],
            "weather": ["天气", "气温", "气候"],
        }

        relevant_keywords = intent_keywords.get(intent, [])
        if relevant_keywords:
            keyword_matches = sum(1 for kw in relevant_keywords if kw in content)
            if keyword_matches == 0:
                score -= 0.3
                issues.append("内容可能与用户意图不相关")
            elif keyword_matches < 2:
                score -= 0.1

        # 检查是否答非所问
        if "不知道" in content or "无法" in content:
            score -= 0.2

        return max(0.0, min(1.0, score)), issues

    def _check_completeness(
        self,
        content: str,
        data: Dict[str, Any],
    ) -> tuple[float, List[str]]:
        """检查完整性"""
        issues = []
        score = 0.0

        # 检查内容长度
        if len(content) < 50:
            score = 0.3
            issues.append("内容过短，可能不完整")
        elif len(content) < 100:
            score = 0.6
        elif len(content) < 300:
            score = 0.8
        else:
            score = 1.0

        # 检查是否有数据支撑
        if data:
            score = min(1.0, score + 0.1)

        # 检查关键部分
        key_parts = ["景点", "行程", "建议"]
        present_parts = sum(1 for part in key_parts if part in content)
        if present_parts < 1:
            score -= 0.2
            issues.append("缺少关键信息部分")

        return max(0.0, min(1.0, score)), issues

    def _check_clarity(
        self,
        content: str,
    ) -> tuple[float, List[str]]:
        """检查清晰度"""
        issues = []
        score = 0.8  # 基础分数

        # 检查是否混乱
        confusion_indicators = ["... ", " 。。", "不不"]
        confusion_count = sum(1 for ind in confusion_indicators if ind in content)
        if confusion_count > 0:
            score -= 0.2

        # 检查是否有列表/结构
        if "\n-" in content or "\n*" in content or "1." in content:
            score += 0.1

        # 检查句子长度
        sentences = content.split("。")
        avg_len = sum(len(s) for s in sentences) / max(1, len(sentences))
        if avg_len > 100:
            score -= 0.1
            issues.append("部分句子过长，可能影响阅读")

        return max(0.0, min(1.0, score)), issues

    def _check_appropriateness(
        self,
        content: str,
    ) -> tuple[float, List[str]]:
        """检查适当性"""
        issues = []
        score = 1.0

        # 检查是否有主观判断
        subjective_phrases = [
            "我觉得",
            "我认为",
            "最好的",
            "最差的",
            "绝对",
            "肯定",
        ]

        subjective_count = sum(1 for phrase in subjective_phrases if phrase in content)
        if subjective_count > 2:
            score -= 0.1

        # 检查语气是否合适
        inappropriate_tones = ["命令", "必须", "强制"]
        tone_count = sum(1 for tone in inappropriate_tones if tone in content)
        if tone_count > 0:
            score -= 0.2
            issues.append("语气可能过于强硬")

        return max(0.0, min(1.0, score)), issues

    def _generate_report(
        self,
        overall_score: float,
        dimension_scores: Dict[str, float],
        issues: List[str],
        passed: bool,
    ) -> str:
        """生成评估报告"""
        lines = ["## 质量评估报告\n"]

        # 总体评估
        status = "通过" if passed else "未通过"
        lines.append(f"**总体评分**: {overall_score:.2f}/1.0 ({status})")
        lines.append(f"**阈值**: {self.pass_threshold:.2f}")

        # 分项评分
        lines.append("\n### 分项评分:")
        for name, score in dimension_scores.items():
            bar = "█" * int(score * 10) + "░" * (10 - int(score * 10))
            status_icon = "✓" if score >= self.pass_threshold else "✗"
            lines.append(f"- {status_icon} {name}: [{bar}] {score:.2f}")

        # 发现的问题
        if issues:
            lines.append("\n### 发现的问题:")
            seen = set()
            for issue in issues:
                if issue not in seen:
                    seen.add(issue)
                    lines.append(f"- {issue}")

        # 建议
        if not passed:
            lines.append("\n### 改进建议:")
            lines.append("1. 检查并修正上述问题")
            lines.append("2. 确保内容准确、完整、相关")

        return "\n".join(lines)
