"""
Emotion Detector
基于 LLM 的情感识别模块
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.logger import get_logger
from app.schemas import EmotionType, EmotionSchema

logger = get_logger(__name__)


class EmotionDetector:
    """
    情感检测器
    通过关键词和 LLM 分析用户消息的情感
    """

    # 情感关键词映射
    POSITIVE_KEYWORDS = {
        "happy": ["开心", "高兴", "喜欢", "太好了", "棒", "不错", "期待", "兴奋", "完美"],
        "excited": ["太棒了", "激动", "兴奋", "超棒", "太赞了", "哇", "哇塞"],
        "satisfied": ["满意", "不错", "很好", "挺好", "谢谢", "感谢", "靠谱"],
    }

    NEGATIVE_KEYWORDS = {
        "frustrated": ["烦", "恼火", "郁闷", "生气", "糟糕", "太差", "失望", "不满意", "烦人"],
        "confused": ["不懂", "困惑", "不明白", "什么意思", "搞不懂", "迷糊", "晕"],
        "worried": ["担心", "害怕", "忧虑", "紧张", "怕", "不安", "放心不下"],
    }

    # 情感响应策略
    RESPONSE_STRATEGIES: Dict[str, Dict[str, Any]] = {
        "happy": {
            "tone": "warm",
            "expressions": ["太棒了！", "太好了！", "听起来很有趣！"],
            "suggestions": ["增加更多推荐", "提供额外选项", "分享相关攻略"],
        },
        "neutral": {
            "tone": "professional",
            "expressions": ["明白了", "好的", "了解"],
            "suggestions": ["提供实用信息", "给出具体建议"],
        },
        "frustrated": {
            "tone": "patient",
            "expressions": ["我理解您的感受", "别着急，我们慢慢来", "我来帮您解决这个问题"],
            "suggestions": ["简化说明", "提供更多选择", "主动询问具体问题"],
        },
        "confused": {
            "tone": "simple",
            "expressions": ["让我解释一下", "简单来说", "我重新说明一下"],
            "suggestions": ["使用更简单的语言", "分步骤说明", "提供示例"],
        },
        "excited": {
            "tone": "enthusiastic",
            "expressions": ["哇！", "太棒了！", "我也好期待！", "这听起来很有趣！"],
            "suggestions": ["分享更多精彩内容", "提供独家攻略", "推荐隐藏景点"],
        },
        "worried": {
            "tone": "reassuring",
            "expressions": ["别担心", "放心", "我会帮您考虑周全"],
            "suggestions": ["提供备选方案", "强调安全保障", "展示应急预案"],
        },
        "satisfied": {
            "tone": "appreciative",
            "expressions": ["谢谢您的认可", "很高兴能帮到您", "有什么需要随时告诉我"],
            "suggestions": ["提供后续服务", "分享相关资源"],
        },
    }

    def __init__(self):
        """初始化情感检测器"""
        self._all_keywords: Dict[str, List[str]] = {}
        for emotion, keywords in self.POSITIVE_KEYWORDS.items():
            self._all_keywords[emotion] = keywords
        for emotion, keywords in self.NEGATIVE_KEYWORDS.items():
            self._all_keywords[emotion] = keywords

    def detect(self, message: str, context: Optional[Dict[str, Any]] = None) -> EmotionSchema:
        """
        检测消息的情感

        Args:
            message: 用户消息
            context: 额外的上下文信息

        Returns:
            EmotionSchema: 情感分析结果
        """
        # 1. 快速关键词检测
        emotion_scores = self._keyword_based_detection(message)

        # 2. 如果关键词检测不确定，使用模式检测
        if not emotion_scores or max(emotion_scores.values()) < 0.3:
            pattern_emotion = self._pattern_based_detection(message)
            if pattern_emotion:
                emotion_scores[pattern_emotion] = max(
                    emotion_scores.get(pattern_emotion, 0), 0.5
                )

        # 3. 综合分析
        if emotion_scores:
            detected_emotion = max(emotion_scores, key=emotion_scores.get)
            confidence = emotion_scores[detected_emotion]
        else:
            detected_emotion = "neutral"
            confidence = 0.6  # 默认置信度

        # 4. 计算情感强度
        intensity = self._calculate_intensity(message, detected_emotion)

        # 5. 获取建议的响应风格
        strategy = self.RESPONSE_STRATEGIES.get(
            detected_emotion,
            self.RESPONSE_STRATEGIES["neutral"]
        )

        logger.debug(f"Emotion detected: {detected_emotion} (confidence: {confidence})")

        return EmotionSchema(
            emotion=EmotionType(detected_emotion),
            confidence=confidence,
            intensity=intensity,
            suggested_response_style=strategy["tone"],
        )

    def _keyword_based_detection(self, message: str) -> Dict[str, float]:
        """
        基于关键词的情感检测

        Args:
            message: 用户消息

        Returns:
            Dict[str, float]: 情感类型到置信度的映射
        """
        scores: Dict[str, float] = {}

        for emotion, keywords in self._all_keywords.items():
            matches = sum(1 for keyword in keywords if keyword in message)
            if matches > 0:
                # 匹配越多，置信度越高
                scores[emotion] = min(0.5 + matches * 0.15, 0.95)

        return scores

    def _pattern_based_detection(self, message: str) -> Optional[str]:
        """
        基于句式模式的情感检测

        Args:
            message: 用户消息

        Returns:
            Optional[str]: 检测到的情感类型
        """
        message = message.strip()

        # 感叹句检测
        if message.endswith(("！", "!!", "!!!", "!")):
            return "excited" if len(message) < 20 else "happy"

        # 问句检测 - 可能表示困惑或担忧
        if message.endswith(("？", "??", "???", "?")):
            if any(word in message for word in ["怎么", "如何", "为什么", "是不是"]):
                return "confused"
            return "worried"

        # 短句可能表示急切或兴奋
        if len(message) < 10:
            if any(word in message for word in ["好", "行", "可以", "要", "去"]):
                return "excited"

        # 重复字符可能表示情绪
        if "!!" in message or "！！" in message:
            return "excited"

        return None

    def _calculate_intensity(self, message: str, emotion: str) -> float:
        """
        计算情感强度

        Args:
            message: 用户消息
            emotion: 检测到的情感类型

        Returns:
            float: 情感强度 (0-1)
        """
        base_intensity = 0.5

        # 感叹号增加强度
        exclamation_count = message.count("!") + message.count("！")
        base_intensity += min(exclamation_count * 0.1, 0.3)

        # 重复字符增加强度
        if any(char * 2 in message for char in message):
            base_intensity += 0.1

        # 消息长度调整
        if len(message) < 5:
            base_intensity += 0.1
        elif len(message) > 50:
            base_intensity -= 0.1

        return min(max(base_intensity, 0.1), 1.0)

    def get_response_strategy(self, emotion: EmotionType) -> Dict[str, Any]:
        """
        获取特定情感的响应策略

        Args:
            emotion: 情感类型

        Returns:
            Dict: 响应策略配置
        """
        return self.RESPONSE_STRATEGIES.get(
            emotion.value,
            self.RESPONSE_STRATEGIES["neutral"]
        )

    def adjust_message_based_on_emotion(
        self,
        message: str,
        emotion: EmotionSchema
    ) -> str:
        """
        根据情感调整消息前缀

        Args:
            message: 原始消息
            emotion: 检测到的情感

        Returns:
            str: 调整后的消息
        """
        if emotion.emotion.value == "neutral":
            return message

        strategy = self.get_response_strategy(emotion.emotion)
        expressions = strategy["expressions"]

        # 根据情感强度选择表达
        if emotion.intensity > 0.7 and expressions:
            prefix = expressions[0]
        else:
            return message

        return f"{prefix} {message}"

    def get_suggestions(self, emotion: EmotionType) -> List[str]:
        """
        获取针对特定情感的回复建议

        Args:
            emotion: 情感类型

        Returns:
            List[str]: 建议列表
        """
        strategy = self.get_response_strategy(emotion)
        return strategy.get("suggestions", [])


# 全局实例
emotion_detector = EmotionDetector()
