"""
Multimodal Handler
多模态输入处理器
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.llm.image_analyzer import image_analyzer
from app.core.logger import get_logger
from app.schemas import ImageAnalysisSchema

logger = get_logger(__name__)


class MultimodalHandler:
    """
    多模态输入处理器
    处理图片等多媒体输入
    """

    def __init__(self):
        self.image_analyzer = image_analyzer

    def has_multimodal_input(
        self,
        image_data: Optional[str] = None,
        image_url: Optional[str] = None,
    ) -> bool:
        """
        检查是否有图片输入

        Args:
            image_data: Base64 图片数据
            image_url: 图片 URL

        Returns:
            bool: 是否有图片
        """
        return bool(image_data or image_url)

    async def process_image(
        self,
        image_data: Optional[str],
        image_url: Optional[str],
        llm_client: Any,
        question: Optional[str] = None,
    ) -> tuple[bool, str, Optional[ImageAnalysisSchema]]:
        """
        处理图片输入

        Args:
            image_data: Base64 图片数据
            image_url: 图片 URL
            llm_client: LLM 客户端
            question: 可选的问题（如有则回答图片问题）

        Returns:
            (是否成功, 响应内容, 图片分析结果)
        """
        # 获取图片数据
        if image_url:
            try:
                import httpx
                response = await httpx.AsyncClient().get(image_url)
                import base64
                image_data = base64.b64encode(response.content).decode("utf-8")
            except Exception as e:
                logger.error(f"Failed to fetch image from URL: {e}")
                return False, "无法获取图片，请提供 Base64 编码的图片数据。", None

        if not image_data:
            return False, "没有检测到图片数据。", None

        # 验证图片
        valid, error = self.image_analyzer.validate_image(image_data)
        if not valid:
            return False, f"图片验证失败: {error}", None

        try:
            if question:
                # 回答关于图片的问题
                answer = await self.image_analyzer.answer_image_question(
                    image_data, question, llm_client
                )
                return True, answer, None
            else:
                # 识别景点
                analysis = await self.image_analyzer.analyze_attraction(
                    image_data, llm_client
                )

                # 构建响应
                if analysis.recognized:
                    response = f"我识别到这是 **{analysis.attraction_name}**！\n\n"
                    if analysis.location:
                        response += f"📍 位置: {analysis.location}\n"
                    if analysis.description:
                        response += f"\n{analysis.description}\n"
                    if analysis.related_attractions:
                        response += f"\n💡 相关景点推荐: {', '.join(analysis.related_attractions[:3])}"
                else:
                    response = "抱歉，我无法识别这张图片中的景点。\n\n"
                    if analysis.description:
                        response += f"不过我观察到: {analysis.description[:100]}...\n\n"
                    response += "您可以尝试上传更清晰的景点照片，或者直接告诉我景点名称，我来为您介绍。"

                return True, response, analysis

        except Exception as e:
            logger.error(f"Image processing failed: {e}")
            return False, "图片处理失败，请稍后重试。", None

    def build_multimodal_context(
        self,
        image_analysis: Optional[ImageAnalysisSchema],
        user_message: str,
    ) -> str:
        """
        构建包含图片分析的上下文

        Args:
            image_analysis: 图片分析结果
            user_message: 用户消息

        Returns:
            str: 上下文描述
        """
        if not image_analysis or not image_analysis.recognized:
            return user_message

        context = f"[用户上传了景点图片，已识别为: {image_analysis.attraction_name}] {user_message}"
        return context


# 全局实例
multimodal_handler = MultimodalHandler()
