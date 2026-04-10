"""
Dialog Mode Detector
对话模式自动检测与切换
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.core.logger import get_logger
from app.schemas import DialogMode, ModeContext

logger = get_logger(__name__)


class DialogModeDetector:
    """
    对话模式检测器
    自动识别用户意图并切换对话模式
    """

    # 模式关键词映射
    MODE_PATTERNS: Dict[DialogMode, Dict[str, List[str]]] = {
        DialogMode.QA: {
            "keywords": [
                "是什么", "在哪里", "怎么去", "多远", "多少钱", "门票",
                "开放时间", "好不好玩", "怎么样", "哪个好", "推荐",
                "什么景点", "有什么", "怎么走", "怎么玩",
            ],
            "intents": [
                "问", "查询", "了解", "想知道", "看看", "介绍一下",
            ],
        },
        DialogMode.PLANNING: {
            "keywords": [
                "规划", "计划", "行程", "安排", "路线", "几天",
                "想去", "要去", "旅游", "旅行", "游玩", "攻略",
                "预算", "多少钱", "两天", "三天", "周末",
            ],
            "intents": [
                "帮", "安排", "制定", "规划", "设计", "推荐路线",
            ],
        },
        DialogMode.CHAT: {
            "keywords": [
                "你好", "嗨", "哈喽", "在吗", "聊", "随便", "天气",
                "今天", "现在", "吃饭", "睡觉", "无聊",
            ],
            "intents": [
                "聊", "说", "讲", "聊聊", "扯", "吹",
            ],
        },
    }

    # 模式切换信号
    MODE_SWITCH_SIGNALS: Dict[Tuple[DialogMode, DialogMode], List[str]] = {
        (DialogMode.CHAT, DialogMode.PLANNING): [
            "想", "要去", "准备", "计划", "安排",
        ],
        (DialogMode.QA, DialogMode.PLANNING): [
            "帮我", "安排", "规划", "制定", "计划",
        ],
        (DialogMode.PLANNING, DialogMode.QA): [
            "顺便问一下", "想问一下", "另外", "还有",
        ],
    }

    def __init__(self):
        """初始化模式检测器"""
        self._default_mode = DialogMode.PLANNING
        self._mode_keywords: Dict[DialogMode, List[str]] = {}

        # 合并所有模式的关键词
        for mode, patterns in self.MODE_PATTERNS.items():
            all_keywords = patterns.get("keywords", []) + patterns.get("intents", [])
            self._mode_keywords[mode] = all_keywords

    def detect_mode(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ModeContext:
        """
        检测对话模式

        Args:
            message: 用户消息
            context: 上下文信息

        Returns:
            ModeContext: 模式检测结果
        """
        # 获取当前模式
        current_mode = self._default_mode
        if context and "current_mode" in context:
            try:
                current_mode = DialogMode(context["current_mode"])
            except ValueError:
                pass

        # 分析消息
        mode_scores = self._calculate_mode_scores(message, context)

        # 决策
        if mode_scores:
            detected_mode = max(mode_scores, key=mode_scores.get)
            confidence = mode_scores[detected_mode]
        else:
            detected_mode = current_mode
            confidence = 0.6

        # 检查是否需要切换模式
        suggested_switch = None
        if detected_mode != current_mode and confidence > 0.5:
            suggested_switch = detected_mode

        # 生成推理说明
        reasoning = self._generate_reasoning(detected_mode, mode_scores)

        logger.debug(f"Mode detected: {detected_mode} (confidence: {confidence})")

        return ModeContext(
            current_mode=detected_mode,
            mode_confidence=confidence,
            mode_reasoning=reasoning,
            suggested_mode_switch=suggested_switch,
            conversation_state=self._determine_conversation_state(message, context),
        )

    def _calculate_mode_scores(
        self,
        message: str,
        context: Optional[Dict[str, Any]],
    ) -> Dict[DialogMode, float]:
        """
        计算各模式的匹配分数

        Args:
            message: 用户消息
            context: 上下文信息

        Returns:
            Dict[DialogMode, float]: 模式到分数的映射
        """
        scores: Dict[DialogMode, float] = {}
        message_lower = message.lower()

        for mode, keywords in self._mode_keywords.items():
            matches = sum(1 for keyword in keywords if keyword in message_lower)
            if matches > 0:
                # 匹配越多，分数越高
                scores[mode] = min(0.4 + matches * 0.2, 0.95)

        # 上下文调整
        if context:
            scores = self._adjust_scores_by_context(scores, context)

        # 组合关键词检测
        combo_scores = self._detect_combination_patterns(message)
        for mode, score in combo_scores.items():
            if mode in scores:
                scores[mode] = max(scores[mode], score)
            else:
                scores[mode] = score

        return scores

    def _detect_combination_patterns(self, message: str) -> Dict[DialogMode, float]:
        """
        检测组合关键词模式

        Args:
            message: 用户消息

        Returns:
            Dict[DialogMode, float]: 组合模式分数
        """
        scores: Dict[DialogMode, float] = {}

        # 规划 + 具体时间的强信号
        planning_keywords = ["天", "日", "晚"]
        time_keywords = ["想去", "要去", "计划", "安排"]

        has_time = any(kw in message for kw in planning_keywords)
        has_planning = any(kw in message for kw in time_keywords)

        if has_time and has_planning:
            scores[DialogMode.PLANNING] = 0.9

        # 问句模式检测
        if message.strip().endswith(("？", "?", "?")):
            if any(kw in message for kw in ["怎么", "如何", "为什么", "是不是", "能不能"]):
                scores[DialogMode.QA] = scores.get(DialogMode.QA, 0.5) + 0.3

        return scores

    def _adjust_scores_by_context(
        self,
        scores: Dict[DialogMode, float],
        context: Dict[str, Any],
    ) -> Dict[DialogMode, float]:
        """
        根据上下文调整分数

        Args:
            scores: 原始分数
            context: 上下文信息

        Returns:
            Dict[DialogMode, float]: 调整后的分数
        """
        adjusted = scores.copy()

        # 如果已有规划目的地的上下文，提升规划模式分数
        if context.get("has_destination"):
            adjusted[DialogMode.PLANNING] = adjusted.get(DialogMode.PLANNING, 0.3) + 0.2

        # 如果在澄清过程中，保持当前模式
        if context.get("is_clarifying"):
            current = context.get("current_mode", "planning")
            try:
                current_mode = DialogMode(current)
                adjusted[current_mode] = adjusted.get(current_mode, 0.5) + 0.3
            except ValueError:
                pass

        return adjusted

    def _determine_conversation_state(
        self,
        message: str,
        context: Optional[Dict[str, Any]],
    ) -> str:
        """
        判断对话状态

        Args:
            message: 用户消息
            context: 上下文信息

        Returns:
            str: 对话状态
        """
        # 检查是否在澄清
        clarifying_phrases = [
            "你说", "什么意思", "具体", "详细",
            "展开", "举个例子", "还有呢",
        ]
        if any(phrase in message for phrase in clarifying_phrases):
            return "clarifying"

        # 检查是否完成
        completion_phrases = [
            "谢谢", "好了", "可以", "够了",
            "就这样", "明白了", "知道了",
        ]
        if any(phrase in message for phrase in completion_phrases):
            return "completed"

        return "ongoing"

    def _generate_reasoning(
        self,
        mode: DialogMode,
        scores: Dict[DialogMode, float],
    ) -> str:
        """
        生成推理说明

        Args:
            mode: 判定模式
            scores: 各模式分数

        Returns:
            str: 推理说明
        """
        reasons = {
            DialogMode.QA: "检测到询问类关键词",
            DialogMode.PLANNING: "检测到规划类关键词",
            DialogMode.CHAT: "检测到闲聊类关键词",
        }

        reason = reasons.get(mode, "默认模式")

        if scores:
            other_modes = [m for m in scores if m != mode]
            if other_modes:
                other_scores = [f"{m.value}:{scores[m]:.2f}" for m in other_modes]
                reason += f", 其他模式分数: {', '.join(other_scores)}"

        return reason

    def should_switch_mode(
        self,
        current: DialogMode,
        suggested: DialogMode,
        confidence: float,
    ) -> bool:
        """
        判断是否应该切换模式

        Args:
            current: 当前模式
            suggested: 建议模式
            confidence: 置信度

        Returns:
            bool: 是否切换
        """
        if current == suggested:
            return False

        # 高置信度切换
        if confidence > 0.7:
            return True

        # 检查切换信号
        signals = self.MODE_SWITCH_SIGNALS.get((current, suggested), [])
        if signals:
            return True

        return False

    def get_mode_agent(self, mode: DialogMode) -> str:
        """
        获取模式对应的 Agent 名称

        Args:
            mode: 对话模式

        Returns:
            str: Agent 名称
        """
        mode_agents = {
            DialogMode.QA: "qa_agent",
            DialogMode.PLANNING: "orchestrator",
            DialogMode.CHAT: "chat_agent",
        }
        return mode_agents.get(mode, "orchestrator")


# 全局实例
mode_detector = DialogModeDetector()
