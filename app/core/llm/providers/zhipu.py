"""
智谱 AI (GLM) Provider
支持智谱 GLM 系列模型
"""
from __future__ import annotations

from typing import Any, AsyncGenerator, TYPE_CHECKING

import httpx

from app.core.llm.providers.base import BaseLLMProvider, ModelCapability, ModelInfo
from app.core.logger import get_logger

if TYPE_CHECKING:
    from app.core.llm.client import LLMMessage, ToolDefinition

logger = get_logger(__name__)


class ZhipuProvider(BaseLLMProvider):
    """智谱 AI (GLM) Provider"""

    BASE_URL = "https://open.bigmodel.cn/api/paas/v4"

    MODELS = {
        "glm-4": ModelInfo(
            name="glm-4",
            provider="zhipu",
            display_name="GLM-4",
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.STREAMING,
                ModelCapability.FUNCTION_CALLING,
                ModelCapability.LONG_CONTEXT,
            ],
            context_window=128_000,
            max_output_tokens=4096,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=800,
            reliability=0.95,
        ),
        "glm-4v": ModelInfo(
            name="glm-4v",
            provider="zhipu",
            display_name="GLM-4V (视觉)",
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.STREAMING,
                ModelCapability.VISION,
                ModelCapability.FUNCTION_CALLING,
            ],
            context_window=128_000,
            max_output_tokens=4096,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=1000,
            reliability=0.92,
        ),
        "glm-4-flash": ModelInfo(
            name="glm-4-flash",
            provider="zhipu",
            display_name="GLM-4 Flash (快速)",
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.STREAMING,
                ModelCapability.FUNCTION_CALLING,
                ModelCapability.FAST,
            ],
            context_window=128_000,
            max_output_tokens=4096,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=300,
            reliability=0.98,
        ),
        "glm-3-turbo": ModelInfo(
            name="glm-3-turbo",
            provider="zhipu",
            display_name="GLM-3 Turbo",
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.STREAMING,
                ModelCapability.FUNCTION_CALLING,
            ],
            context_window=128_000,
            max_output_tokens=4096,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=500,
            reliability=0.96,
        ),
        "glm-z1-flash": ModelInfo(
            name="glm-z1-flash",
            provider="zhipu",
            display_name="GLM-Z1 Flash (推理)",
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.STREAMING,
                ModelCapability.REASONING,
                ModelCapability.FAST,
            ],
            context_window=32_000,
            max_output_tokens=8192,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=400,
            reliability=0.95,
        ),
        "glm-z1-rationance": ModelInfo(
            name="glm-z1-rationance",
            provider="zhipu",
            display_name="GLM-Z1 Rationance (深度推理)",
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.STREAMING,
                ModelCapability.REASONING,
            ],
            context_window=32_000,
            max_output_tokens=8192,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=3000,
            reliability=0.90,
        ),
        "cogview-3": ModelInfo(
            name="cogview-3",
            provider="zhipu",
            display_name="CogView-3 (图像生成)",
            capabilities=[],
            context_window=0,
            max_output_tokens=0,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=5000,
            reliability=0.85,
        ),
    }

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int = 60,
    ):
        from app.core.config import settings

        self.api_key = api_key or settings.llm.zhipu_api_key
        self.base_url = base_url or self.BASE_URL
        self.timeout = timeout

        if not self.api_key:
            raise ValueError("Zhipu API key is required")

        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

    @property
    def provider_name(self) -> str:
        return "zhipu"

    @property
    def default_model(self) -> str:
        return "glm-4"

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

        api_messages = []
        for msg in messages:
            role = msg.role.value if hasattr(msg.role, 'value') else msg.role
            if role == "system":
                api_messages.insert(0, {"role": "system", "content": msg.content})
            else:
                api_messages.append({"role": role, "content": msg.content})

        model_name = model or self.default_model

        request_data: dict[str, Any] = {
            "model": model_name,
            "messages": api_messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4096),
        }

        if tools:
            request_data["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    }
                }
                for tool in tools
            ]

        try:
            response = await self.client.post("/chat/completions", json=request_data)
            response.raise_for_status()
            data = response.json()

            return self._parse_response(data, model_name)

        except Exception as e:
            logger.error(f"Zhipu API call failed: {e}")
            raise

    def _parse_response(self, data: dict, model_name: str) -> "LLMResponse":
        from app.core.llm.client import LLMResponse, ToolCall

        choices = data.get("choices", [])
        if not choices:
            return LLMResponse(
                content="",
                model=model_name,
                usage={},
                finish_reason="empty",
                tool_calls=[],
            )

        choice = choices[0]
        message = choice.get("message", {})

        tool_calls = []
        if "tool_calls" in message:
            for tc in message["tool_calls"]:
                if "function" in tc:
                    tool_calls.append(
                        ToolCall(
                            id=tc.get("id", ""),
                            name=tc["function"].get("name", ""),
                            arguments=tc["function"].get("arguments", "{}"),
                        )
                    )

        usage = data.get("usage", {})

        return LLMResponse(
            content=message.get("content", ""),
            model=model_name,
            usage={
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            finish_reason=choice.get("finish_reason", "stop"),
            tool_calls=tool_calls,
        )

    async def stream(
        self,
        messages: list["LLMMessage"],
        model: str | None = None,
        tools: list["ToolDefinition"] | None = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        api_messages = []
        for msg in messages:
            role = msg.role.value if hasattr(msg.role, 'value') else msg.role
            if role == "system":
                api_messages.insert(0, {"role": "system", "content": msg.content})
            else:
                api_messages.append({"role": role, "content": msg.content})

        model_name = model or self.default_model

        request_data: dict[str, Any] = {
            "model": model_name,
            "messages": api_messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4096),
            "stream": True,
        }

        if tools:
            request_data["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    }
                }
                for tool in tools
            ]

        try:
            async with self.client.stream("POST", "/chat/completions", json=request_data) as stream:
                async for line in stream.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        import json
                        data = json.loads(data_str)
                        choices = data.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            if "content" in delta:
                                content = delta["content"]
                                if content:
                                    yield content

        except Exception as e:
            logger.error(f"Zhipu streaming failed: {e}")
            raise

    async def embeddings(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        try:
            embeddings = []
            for text in texts:
                response = await self.client.post(
                    "/embeddings",
                    json={
                        "model": model or "embedding-2",
                        "input": text,
                    }
                )
                response.raise_for_status()
                data = response.json()
                embedding_data = data.get("data", [])
                if embedding_data:
                    embeddings.append(embedding_data[0].get("embedding", []))
                else:
                    embeddings.append([])
            return embeddings
        except Exception as e:
            logger.error(f"Zhipu embedding failed: {e}")
            raise

    async def health_check(self) -> bool:
        try:
            response = await self.client.post(
                "/chat/completions",
                json={
                    "model": self.default_model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 10,
                }
            )
            return response.status_code == 200
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
            context_window=128_000,
            max_output_tokens=4096,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=800,
            reliability=0.90,
        )
