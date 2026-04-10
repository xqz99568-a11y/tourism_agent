"""
Image Analyzer
多模态图片分析模块
支持景点识别、图像问答等功能
"""
from __future__ import annotations

import base64
import re
from io import BytesIO
from typing import Any, Dict, List, Optional

from PIL import Image

from app.core.logger import get_logger
from app.schemas import ImageAnalysisSchema

logger = get_logger(__name__)


class ImageAnalyzer:
    """
    图片分析器
    使用 LLM 多模态能力分析用户上传的图片
    """

    SYSTEM_PROMPT = """你是一个专业的景点识别助手，能够根据用户上传的图片识别景点。

请分析图片内容并提供以下信息：
- 景点名称（如能识别）
- 景点位置/地区
- 景点特色描述
- 相关的推荐景点

如果没有足够的识别信息，请如实说明。

输出 JSON 格式："""

    QA_PROMPT = """你是一个专业的旅游助手，可以根据图片回答用户的问题。

请仔细观察图片，结合你的旅游知识，回答用户的问题。
如果图片信息不足以回答问题，请诚实说明。"""

    def __init__(self):
        """初始化图片分析器"""
        self._max_image_size = 10 * 1024 * 1024  # 10MB
        self._supported_formats = {"jpeg", "jpg", "png", "gif", "webp"}

    def validate_image(self, image_data: str) -> tuple[bool, Optional[str]]:
        """
        验证图片数据

        Args:
            image_data: Base64 编码的图片数据

        Returns:
            (是否有效, 错误信息)
        """
        try:
            # 解码 base64
            if image_data.startswith("data:"):
                # 处理 data URI 格式
                image_data = image_data.split(",")[1]

            image_bytes = base64.b64decode(image_data)

            # 检查大小
            if len(image_bytes) > self._max_image_size:
                return False, "图片大小超过 10MB 限制"

            # 尝试打开图片验证格式
            img = Image.open(BytesIO(image_bytes))
            img.verify()

            # 检查格式
            format_lower = img.format.lower() if img.format else "unknown"
            if format_lower not in self._supported_formats:
                return False, f"不支持的图片格式: {format_lower}"

            return True, None

        except Exception as e:
            logger.error(f"Image validation failed: {e}")
            return False, f"图片格式错误: {str(e)}"

    def prepare_image_for_llm(
        self,
        image_data: str,
        max_width: int = 1024,
        max_height: int = 1024,
    ) -> str:
        """
        准备图片数据用于 LLM

        Args:
            image_data: Base64 编码的图片数据
            max_width: 最大宽度
            max_height: 最大高度

        Returns:
            处理后的 Base64 图片数据
        """
        try:
            if image_data.startswith("data:"):
                image_data = image_data.split(",")[1]

            image_bytes = base64.b64decode(image_data)
            img = Image.open(BytesIO(image_bytes))

            # 调整大小
            if img.width > max_width or img.height > max_height:
                img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

            # 转换为 JPEG
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            # 重新编码
            output = BytesIO()
            img.save(output, format="JPEG", quality=85)
            return base64.b64encode(output.getvalue()).decode("utf-8")

        except Exception as e:
            logger.error(f"Image preparation failed: {e}")
            return image_data

    async def analyze_attraction(
        self,
        image_data: str,
        llm_client: Any,
    ) -> ImageAnalysisSchema:
        """
        分析图片识别景点

        Args:
            image_data: Base64 编码的图片数据
            llm_client: LLM 客户端

        Returns:
            ImageAnalysisSchema: 分析结果
        """
        # 准备图片
        prepared_image = self.prepare_image_for_llm(image_data)

        prompt = f"""{self.SYSTEM_PROMPT}

请分析以下图片，识别景点信息。"""

        try:
            # 调用多模态 LLM
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{prepared_image}",
                            },
                        },
                    ],
                }
            ]

            response = await llm_client.chat(messages)

            # 解析响应
            return self._parse_attraction_response(response.content)

        except Exception as e:
            logger.error(f"Image attraction analysis failed: {e}")
            return ImageAnalysisSchema(
                recognized=False,
                confidence=0,
            )

    async def answer_image_question(
        self,
        image_data: str,
        question: str,
        llm_client: Any,
    ) -> str:
        """
        回答关于图片的问题

        Args:
            image_data: Base64 编码的图片数据
            question: 用户问题
            llm_client: LLM 客户端

        Returns:
            str: 回答内容
        """
        # 准备图片
        prepared_image = self.prepare_image_for_llm(image_data)

        prompt = f"""{self.QA_PROMPT}

用户问题: {question}"""

        try:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{prepared_image}",
                            },
                        },
                    ],
                }
            ]

            response = await llm_client.chat(messages)
            return response.content

        except Exception as e:
            logger.error(f"Image QA failed: {e}")
            return "抱歉，我无法分析这张图片。"

    def _parse_attraction_response(self, content: str) -> ImageAnalysisSchema:
        """
        解析景点识别响应

        Args:
            content: LLM 响应内容

        Returns:
            ImageAnalysisSchema: 解析结果
        """
        try:
            # 尝试解析 JSON
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                import json
                data = json.loads(json_match.group())

                return ImageAnalysisSchema(
                    recognized=data.get("recognized", False),
                    attraction_name=data.get("attraction_name"),
                    location=data.get("location"),
                    description=data.get("description"),
                    related_attractions=data.get("related_attractions", []),
                    confidence=data.get("confidence", 0),
                )

        except Exception as e:
            logger.debug(f"JSON parsing failed, using text analysis: {e}")

        # 文本分析
        if any(keyword in content for keyword in ["故宫", "长城", "西湖", "天安门"]):
            return ImageAnalysisSchema(
                recognized=True,
                attraction_name=self._extract_attraction_name(content),
                description=content[:200],
                confidence=0.8,
            )

        return ImageAnalysisSchema(
            recognized=False,
            description=content[:200],
            confidence=0.3,
        )

    def _extract_attraction_name(self, content: str) -> Optional[str]:
        """从内容中提取景点名称"""
        # 简单的名称提取逻辑
        patterns = [
            r"景点名称[：:]\s*([^\n，。]+)",
            r"是\s*([^\n，。]+?)(?:位于|坐落于|在)",
            r"^([^\n，。]{2,10})(?:是|位于)",
        ]

        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                return match.group(1).strip()

        return None


# 全局实例
image_analyzer = ImageAnalyzer()
