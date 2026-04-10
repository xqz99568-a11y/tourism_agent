"""
OpenAI 兼容 Provider
支持 OpenAI API 格式的模型
"""
from __future__ import annotations

import httpx
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from app.core.config import settings
from app.core.llm.providers.base import BaseLLMProvider, ModelCapability, ModelInfo
from app.core.logger import get_logger

logger = get_logger(__name__)


class OpenAIProvider(BaseLLMProvider):
    """OpenAI 兼容 Provider"""

    # OpenAI 模型映射
    MODELS = {
        "gpt-4o": ModelInfo(
            name="gpt-4o",
            provider="openai",
            display_name="GPT-4o",
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.STREAMING,
                ModelCapability.FUNCTION_CALLING,
                ModelCapability.VISION,
                ModelCapability.LONG_CONTEXT,
            ],
            context_window=128_000,
            max_output_tokens=16384,
            cost_per_input=2.5,
            cost_per_output=10.0,
            avg_latency_ms=800,
            reliability=0.98,
        ),
        "gpt-4o-mini": ModelInfo(
            name="gpt-4o-mini",
            provider="openai",
            display_name="GPT-4o Mini",
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.STREAMING,
                ModelCapability.FUNCTION_CALLING,
                ModelCapability.FAST,
            ],
            context_window=128_000,
            max_output_tokens=16384,
            cost_per_input=0.15,
            cost_per_output=0.6,
            avg_latency_ms=300,
            reliability=0.99,
        ),
        "gpt-4-turbo": ModelInfo(
            name="gpt-4-turbo",
            provider="openai",
            display_name="GPT-4 Turbo",
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.STREAMING,
                ModelCapability.FUNCTION_CALLING,
                ModelCapability.VISION,
                ModelCapability.LONG_CONTEXT,
            ],
            context_window=128_000,
            max_output_tokens=4096,
            cost_per_input=10.0,
            cost_per_output=30.0,
            avg_latency_ms=1000,
            reliability=0.95,
        ),
        "o1-preview": ModelInfo(
            name="o1-preview",
            provider="openai",
            display_name="OpenAI o1 Preview",
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.REASONING,
                ModelCapability.LONG_CONTEXT,
            ],
            context_window=128_000,
            max_output_tokens=32768,
            cost_per_input=15.0,
            cost_per_output=60.0,
            avg_latency_ms=5000,
            reliability=0.90,
        ),
        "o1-mini": ModelInfo(
            name="o1-mini",
            provider="openai",
            display_name="OpenAI o1 Mini",
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.REASONING,
                ModelCapability.FAST,
            ],
            context_window=128_000,
            max_output_tokens=65536,
            cost_per_input=3.0,
            cost_per_output=12.0,
            avg_latency_ms=2000,
            reliability=0.92,
        ),
    }

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int = 60,
    ):
        self.api_key = api_key or settings.llm.backup_api_key
        self.base_url = base_url or settings.llm.backup_base_url
        self.timeout = timeout

        if not self.api_key:
            raise ValueError("OpenAI API key is required")

        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=timeout,
            http_client=httpx.AsyncClient(timeout=timeout),
        )

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def default_model(self) -> str:
        return "gpt-4o-mini"

    @property
    def supported_models(self) -> list[ModelInfo]:
        return list(self.MODELS.values())

    async def chat(
        self,
        messages: list["LLMMessage"],
        model: str | None = None,
        tools: list["ToolDefinition"] | None = None,
        **kwargs,
    ):
        from app.core.llm.client import LLMResponse, ToolDefinition

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
            response: ChatCompletion = await self.client.chat.completions.create(
                **request_kwargs
            )
            return self._parse_response(response)

        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}")
            raise

    def _parse_response(self, response: ChatCompletion) -> "LLMResponse":
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
            logger.error(f"OpenAI streaming failed: {e}")
            raise

    async def embeddings(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        try:
            response = await self.client.embeddings.create(
                model=model or "text-embedding-3-small",
                input=texts,
            )
            return [item.embedding for item in response.data]
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
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
        )
