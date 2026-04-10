"""
硅基流动 Provider
支持 SiliconFlow API (OpenAI 兼容格式)
"""
from __future__ import annotations

from typing import Any, AsyncGenerator, TYPE_CHECKING

import httpx
from openai import AsyncOpenAI

from app.core.llm.providers.base import BaseLLMProvider, ModelCapability, ModelInfo
from app.core.logger import get_logger

if TYPE_CHECKING:
    from app.core.llm.client import LLMMessage, ToolDefinition

logger = get_logger(__name__)


class SiliconFlowProvider(BaseLLMProvider):
    """SiliconFlow (硅基流动) Provider"""

    BASE_URL = "https://api.siliconflow.cn/v1"

    MODELS = {
        "Qwen/Qwen2.5-7B-Instruct": ModelInfo(
            name="Qwen/Qwen2.5-7B-Instruct",
            provider="siliconflow",
            display_name="Qwen 2.5 7B",
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.STREAMING,
                ModelCapability.FUNCTION_CALLING,
            ],
            context_window=32_000,
            max_output_tokens=4096,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=500,
            reliability=0.95,
        ),
        "Qwen/Qwen2.5-14B-Instruct": ModelInfo(
            name="Qwen/Qwen2.5-14B-Instruct",
            provider="siliconflow",
            display_name="Qwen 2.5 14B",
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.STREAMING,
                ModelCapability.FUNCTION_CALLING,
            ],
            context_window=32_000,
            max_output_tokens=4096,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=700,
            reliability=0.95,
        ),
        "Qwen/Qwen2.5-72B-Instruct": ModelInfo(
            name="Qwen/Qwen2.5-72B-Instruct",
            provider="siliconflow",
            display_name="Qwen 2.5 72B",
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.STREAMING,
                ModelCapability.FUNCTION_CALLING,
                ModelCapability.LONG_CONTEXT,
            ],
            context_window=32_000,
            max_output_tokens=8192,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=1500,
            reliability=0.93,
        ),
        "THUDM/glm-4-9b-chat": ModelInfo(
            name="THUDM/glm-4-9b-chat",
            provider="siliconflow",
            display_name="GLM-4 9B",
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.STREAMING,
                ModelCapability.FUNCTION_CALLING,
            ],
            context_window=128_000,
            max_output_tokens=4096,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=400,
            reliability=0.95,
        ),
        "THUDM/glm-4v-9b": ModelInfo(
            name="THUDM/glm-4v-9b",
            provider="siliconflow",
            display_name="GLM-4V 9B (视觉)",
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.STREAMING,
                ModelCapability.VISION,
            ],
            context_window=128_000,
            max_output_tokens=4096,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=600,
            reliability=0.90,
        ),
        "deepseek-ai/DeepSeek-V2.5": ModelInfo(
            name="deepseek-ai/DeepSeek-V2.5",
            provider="siliconflow",
            display_name="DeepSeek V2.5",
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.STREAMING,
                ModelCapability.FUNCTION_CALLING,
                ModelCapability.REASONING,
            ],
            context_window=128_000,
            max_output_tokens=8192,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=600,
            reliability=0.95,
        ),
        "deepseek-ai/DeepSeek-R1": ModelInfo(
            name="deepseek-ai/DeepSeek-R1",
            provider="siliconflow",
            display_name="DeepSeek R1",
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.STREAMING,
                ModelCapability.REASONING,
            ],
            context_window=64_000,
            max_output_tokens=8192,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=2000,
            reliability=0.92,
        ),
        "Pro/Qwen/Qwen2.5-7B-Instruct": ModelInfo(
            name="Pro/Qwen/Qwen2.5-7B-Instruct",
            provider="siliconflow",
            display_name="Qwen 2.5 7B (高性能)",
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.STREAMING,
                ModelCapability.FUNCTION_CALLING,
            ],
            context_window=32_000,
            max_output_tokens=4096,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=300,
            reliability=0.98,
        ),
    }

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int = 60,
    ):
        from app.core.config import settings

        self.api_key = api_key or settings.llm.siliconflow_api_key
        self.base_url = base_url or self.BASE_URL
        self.timeout = timeout

        if not self.api_key:
            raise ValueError("SiliconFlow API key is required")

        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=timeout,
            http_client=httpx.AsyncClient(timeout=timeout),
        )

    @property
    def provider_name(self) -> str:
        return "siliconflow"

    @property
    def default_model(self) -> str:
        return "Qwen/Qwen2.5-7B-Instruct"

    @property
    def supported_models(self) -> list[ModelInfo]:
        return list(self.MODELS.values())

    async def chat(
        self,
        messages: list["LLMMessage"],
        model: str | None = None,
        tools: list["ToolDefinition"] | None = None,
        **kwargs,
    ) -> "LLMResponse":
        from app.core.llm.client import LLMResponse, ToolCall

        api_messages = [msg.to_dict() for msg in messages]
        model_name = model or self.default_model

        request_kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": api_messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4096),
        }

        if tools:
            request_kwargs["tools"] = [tool.to_dict() for tool in tools]
            request_kwargs["tool_choice"] = kwargs.get("tool_choice", "auto")

        try:
            response = await self.client.chat.completions.create(**request_kwargs)
            return self._parse_response(response)

        except Exception as e:
            logger.error(f"SiliconFlow API call failed: {e}")
            raise

    def _parse_response(self, response) -> "LLMResponse":
        from app.core.llm.client import LLMResponse, ToolCall

        choice = response.choices[0]
        message = choice.message

        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                if tc.function:
                    tool_calls.append(
                        ToolCall(
                            id=tc.id or "",
                            name=tc.function.name or "",
                            arguments=tc.function.arguments or "{}",
                        )
                    )

        return LLMResponse(
            content=message.content or "",
            model=response.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            },
            finish_reason=choice.finish_reason or "",
            tool_calls=tool_calls,
        )

    async def stream(
        self,
        messages: list["LLMMessage"],
        model: str | None = None,
        tools: list["ToolDefinition"] | None = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        api_messages = [msg.to_dict() for msg in messages]
        model_name = model or self.default_model

        request_kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": api_messages,
            "temperature": kwargs.get("temperature", 0.7),
            "stream": True,
        }

        if tools:
            request_kwargs["tools"] = [tool.to_dict() for tool in tools]

        try:
            stream = await self.client.chat.completions.create(**request_kwargs)

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            logger.error(f"SiliconFlow streaming failed: {e}")
            raise

    async def embeddings(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        try:
            response = await self.client.embeddings.create(
                model=model or "BAAI/bge-m3",
                input=texts,
            )
            return [item.embedding for item in response.data]
        except Exception as e:
            logger.error(f"SiliconFlow embedding failed: {e}")
            raise

    async def health_check(self) -> bool:
        try:
            await self.client.models.list()
            return True
        except Exception:
            return False

    def get_model_info(self, model: str | None = None) -> ModelInfo:
        model_name = model or self.default_model
        if model_name in self.MODELS:
            return self.MODELS[model_name]
        return ModelInfo(
            name=model_name,
            provider=self.provider_name,
            display_name=model_name,
            capabilities=[ModelCapability.CHAT, ModelCapability.STREAMING],
            context_window=32_000,
            max_output_tokens=4096,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=500,
            reliability=0.90,
        )
