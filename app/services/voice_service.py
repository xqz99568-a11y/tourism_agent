"""
Voice Service
语音服务（TTS/STT）
"""
from __future__ import annotations

import base64
from io import BytesIO
from typing import Optional

from app.core.logger import get_logger

logger = get_logger(__name__)


class VoiceService:
    """
    语音服务
    提供文本转语音和语音转文本功能
    """

    # 情感对应的语速和音调调整
    EMOTION_VOICE_CONFIG = {
        "happy": {"rate": 1.1, "pitch": 1.1, "volume": 1.0},
        "excited": {"rate": 1.2, "pitch": 1.2, "volume": 1.0},
        "neutral": {"rate": 1.0, "pitch": 1.0, "volume": 1.0},
        "frustrated": {"rate": 0.9, "pitch": 0.9, "volume": 0.9},
        "confused": {"rate": 0.95, "pitch": 1.0, "volume": 0.95},
        "worried": {"rate": 0.9, "pitch": 0.95, "volume": 0.9},
        "satisfied": {"rate": 1.0, "pitch": 1.05, "volume": 1.0},
    }

    def __init__(self):
        """初始化语音服务"""
        self._default_rate = 1.0
        self._default_pitch = 1.0
        self._default_volume = 1.0

    def get_voice_config(self, emotion: str) -> dict:
        """
        获取情感对应的语音配置

        Args:
            emotion: 情感类型

        Returns:
            dict: 语音配置
        """
        return self.EMOTION_VOICE_CONFIG.get(
            emotion,
            self.EMOTION_VOICE_CONFIG["neutral"]
        )

    async def synthesize_speech(
        self,
        text: str,
        emotion: Optional[str] = None,
        language: str = "zh-CN",
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """
        文本转语音（TTS）

        注意：此方法返回配置参数，实际语音合成应在前端使用 Web Speech API

        Args:
            text: 要转换的文本
            emotion: 情感类型（可选，用于调整语音参数）
            language: 语言代码

        Returns:
            (是否成功, 错误信息, 语音配置JSON)
        """
        try:
            voice_config = self.get_voice_config(emotion or "neutral")

            config = {
                "text": text,
                "language": language,
                "rate": voice_config["rate"],
                "pitch": voice_config["pitch"],
                "volume": voice_config["volume"],
            }

            logger.info(f"TTS config prepared for {len(text)} characters")

            return True, None, config

        except Exception as e:
            logger.error(f"TTS synthesis failed: {e}")
            return False, str(e), None

    def prepare_ssml(self, text: str, emotion: str = "neutral") -> str:
        """
        准备 SSML 标记（用于更精细的 TTS 控制）

        Args:
            text: 文本内容
            emotion: 情感类型

        Returns:
            str: SSML 格式的文本
        """
        config = self.get_voice_config(emotion)

        ssml = f"""<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='zh-CN'>
    <voice name='zh-CN'>
        <prosody rate='{config["rate"]}' pitch='{config["pitch"]}' volume='{config["volume"]}'>
            {text}
        </prosody>
    </voice>
</speak>"""

        return ssml

    def validate_audio_format(self, audio_data: str) -> tuple[bool, Optional[str]]:
        """
        验证音频数据格式

        Args:
            audio_data: Base64 编码的音频数据

        Returns:
            (是否有效, 错误信息)
        """
        try:
            # 检查是否是有效的 base64
            audio_bytes = base64.b64decode(audio_data)

            # 检查文件大小（最大 10MB）
            if len(audio_bytes) > 10 * 1024 * 1024:
                return False, "音频文件过大（最大 10MB）"

            # 检查文件头（简单的 WAV/PCM 检测）
            if len(audio_bytes) >= 4:
                header = audio_bytes[:4]
                # WAV 文件头
                if header == b"RIFF":
                    return True, None

            logger.warning("Unknown audio format, proceeding anyway")
            return True, None

        except Exception as e:
            return False, f"音频格式错误: {str(e)}"

    def get_supported_languages(self) -> list:
        """
        获取支持的语言列表

        Returns:
            list: 支持的语言代码
        """
        return [
            {"code": "zh-CN", "name": "中文（简体）"},
            {"code": "zh-TW", "name": "中文（繁体）"},
            {"code": "en-US", "name": "English (US)"},
            {"code": "en-GB", "name": "English (UK)"},
            {"code": "ja-JP", "name": "日本語"},
            {"code": "ko-KR", "name": "한국어"},
        ]


class SpeechRecognitionConfig:
    """语音识别配置"""

    # 中文常用词汇优化
    CHINESE_VOCABULARY = [
        "旅游", "景点", "行程", "规划", "预算", "酒店",
        "机票", "火车票", "门票", "美食", "购物", "交通",
    ]

    def __init__(
        self,
        language: str = "zh-CN",
        continuous: bool = False,
        interim_results: bool = True,
        max_alternatives: int = 1,
    ):
        self.language = language
        self.continuous = continuous
        self.interim_results = interim_results
        self.max_alternatives = max_alternatives

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "language": self.language,
            "continuous": self.continuous,
            "interimResults": self.interim_results,
            "maxAlternatives": self.max_alternatives,
        }


# 全局实例
voice_service = VoiceService()
