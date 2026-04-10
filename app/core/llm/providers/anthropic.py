"""
Anthropic Provider
支持 Claude 系列模型
"""
from __future__ import annotations

from typing import Any, AsyncGenerator, TYPE_CHECKING

from anthropic import AsyncAnthropic

from app.core.llm.providers.base import BaseLLMProvider, ModelCapability, ModelInfo
from app.core.logger import get_logger

if TYPE_CHECKING:
    from app.core.llm.client import LLMMessage, ToolDefinition, LLMResponse

logger = get_logger(__name__)


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude Provider"""

    MODELS = {
        "claude-3-5-sonnet-20241022": ModelInfo(
            name="claude-3-5-sonnet-20241022",
            provider="anthropic",
            display_name="Claude 3.5 Sonnet",
            capabilities=[ModelCapability.CHAT, ModelCapability.STREAMING, ModelCapability.VISION, ModelCapability.LONG_CONTEXT],
            context_window=200_000,
            max_output_tokens=8192,
            cost_per_input=3.0,
            cost_per_output=15.0,
            avg_latency_ms=1000,
            reliability=0.98,
        ),
        "claude-3-5-haiku-20241022": ModelInfo(
            name="claude-3-5-haiku-20241022",
            provider="anthropic",
            display_name="Claude 3.5 Haiku",
            capabilities=[ModelCapability.CHAT, ModelCapability.STREAMING, ModelCapability.FAST],
            context_window=200_000,
            max_output_tokens=8192,
            cost_per_input=0.8,
            cost_per_output=4.0,
            avg_latency_ms=300,
            reliability=0.99,
        ),
        "claude-3-opus-20240229": ModelInfo(
            name="claude-3-opus-20240229",
            provider="anthropic",
            display_name="Claude 3 Opus",
            capabilities=[ModelCapability.CHAT, ModelCapability.STREAMING, ModelCapability.VISION, ModelCapability.LONG_CONTEXT, ModelCapability.REASONING],
            context_window=200_000,
            max_output_tokens=4096,
            cost_per_input=15.0,
            cost_per_output=75.0,
            avg_latency_ms=2000,
            reliability=0.95,
        ),
        "claude-sonnet-4-20250514": ModelInfo(
            name="claude-sonnet-4-20250514",
            provider="anthropic",
            display_name="Claude Sonnet 4",
            capabilities=[ModelCapability.CHAT, ModelCapability.STREAMING, ModelCapability.VISION, ModelCapability.LONG_CONTEXT, ModelCapability.REASONING],
            context_window=200_000,
            max_output_tokens=8192,
            cost_per_input=3.0,
            cost_per_output=15.0,
            avg_latency_ms=800,
            reliability=0.97,
        ),
    }

    def __init__(
        self,
        api_key: str | None = None,
        timeout: int = 60,
    ):
        try:
            import os
            self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        except Exception:
            self.api_key = api_key or ""
        
        self.timeout = timeout

        if not self.api_key:
            raise ValueError("Anthropic API key is required")

        self.client = AsyncAnthropic(api_key=self.api_key, timeout=timeout)

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def default_model(self) -> str:
        return "claude-3-5-sonnet-20241022"

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
        from app.core.llm.client import LLMResponse

        # 转换消息格式
        system_prompt = ""
        anthropic_messages = []

        for msg in messages:
            role = msg.role.value if hasattr(msg.role, 'value') else msg.role
            if role == "system":
                system_prompt = msg.content
            elif role == "user":
                anthropic_messages.append({"role": "user", "content": msg.content})
            elif role == "assistant":
                anthropic_messages.append({"role": "assistant", "content": msg.content})

        model_name = model or self.default_model

        request_kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": anthropic_messages,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7),
        }

        if system_prompt:
            request_kwargs["system"] = system_prompt

        # Anthropic 使用 tool_use 而不是 tools
        if tools:
            request_kwargs["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters,
                }
                for tool in tools
            ]

        try:
            response = await self.client.messages.create(**request_kwargs)

            # 解析响应
            content = response.content[0].text if response.content else ""

            from app.core.llm.client import ToolCall
            tool_calls = []
            if hasattr(response, 'tool_use') and response.tool_use:
                for tc in response.tool_use:
                    tool_calls.append(
                        ToolCall(
                            id=tc.id or "",
                            name=tc.name or "",
                            arguments=str(tc.input) if tc.input else "{}",
                        )
                    )

            return LLMResponse(
                content=content,
                model=model_name,
                usage={
                    "prompt_tokens": response.usage.input_tokens if hasattr(response.usage, 'input_tokens') else 0,
                    "completion_tokens": response.usage.output_tokens if hasattr(response.usage, 'output_tokens') else 0,
                    "total_tokens": (response.usage.input_tokens + response.usage.output_tokens) if hasattr(response.usage, 'input_tokens') else 0,
                },
                finish_reason=response.stop_reason or "stop",
                tool_calls=tool_calls,
            )

        except Exception as e:
            logger.error(f"Anthropic API call failed: {e}")
            raise

    async def stream(
        self,
        messages: list["LLMMessage"],
        model: str | None = None,
        tools: list["ToolDefinition"] | None = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        # 转换消息格式
        system_prompt = ""
        anthropic_messages = []

        for msg in messages:
            role = msg.role.value if hasattr(msg.role, 'value') else msg.role
            if role == "system":
                system_prompt = msg.content
            elif role == "user":
                anthropic_messages.append({"role": "user", "content": msg.content})
            elif role == "assistant":
                anthropic_messages.append({"role": "assistant", "content": msg.content})

        model_name = model or self.default_model

        request_kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": anthropic_messages,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7),
            "stream": True,
        }

        if system_prompt:
            request_kwargs["system"] = system_prompt

        try:
            async with self.client.messages.stream(**request_kwargs) as stream:
                async for text in stream.text_stream:
                    yield text

        except Exception as e:
            logger.error(f"Anthropic streaming failed: {e}")
            raise

    async def embeddings(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        # Anthropic 本身不提供 embedding 服务
        # 可以通过其他方式实现
        logger.warning("Anthropic provider does not support embeddings directly")
        raise NotImplementedError("Anthropic does not provide embedding API")

    async def health_check(self) -> bool:
        try:
            await self.client.messages.create(
                model=self.default_model,
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
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
            context_window=200_000,
            max_output_tokens=4096,
            cost_per_input=3.0,
            cost_per_output=15.0,
            avg_latency_ms=1000,
            reliability=0.95,
        )
