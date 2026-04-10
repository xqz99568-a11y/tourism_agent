"""
本地模型 Provider
支持 Ollama 等本地部署的模型
"""
from __future__ import annotations

import httpx
from typing import TYPE_CHECKING, Any, AsyncGenerator

from app.core.llm.providers.base import BaseLLMProvider, ModelCapability, ModelInfo
from app.core.logger import get_logger

if TYPE_CHECKING:
    from app.core.llm.client import LLMMessage, ToolDefinition

logger = get_logger(__name__)


class LocalProvider(BaseLLMProvider):
    """
    本地模型 Provider
    支持 Ollama、LM Studio 等本地部署
    """

    MODELS = {
        "llama3.2": ModelInfo(
            name="llama3.2",
            provider="local",
            display_name="Llama 3.2",
            capabilities=[ModelCapability.CHAT, ModelCapability.STREAMING],
            context_window=128_000,
            max_output_tokens=4096,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=500,
            reliability=0.95,
        ),
        "qwen2.5": ModelInfo(
            name="qwen2.5",
            provider="local",
            display_name="Qwen 2.5",
            capabilities=[ModelCapability.CHAT, ModelCapability.STREAMING, ModelCapability.FUNCTION_CALLING],
            context_window=128_000,
            max_output_tokens=8192,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=400,
            reliability=0.95,
        ),
        "deepseek-r1": ModelInfo(
            name="deepseek-r1",
            provider="local",
            display_name="DeepSeek R1",
            capabilities=[ModelCapability.CHAT, ModelCapability.STREAMING, ModelCapability.REASONING],
            context_window=64_000,
            max_output_tokens=8192,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=800,
            reliability=0.90,
        ),
        "codellama": ModelInfo(
            name="codellama",
            provider="local",
            display_name="Code Llama",
            capabilities=[ModelCapability.CHAT, ModelCapability.STREAMING],
            context_window=16_000,
            max_output_tokens=4096,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=600,
            reliability=0.95,
        ),
    }

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeout: int = 120,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
        )

    @property
    def provider_name(self) -> str:
        return "local"

    @property
    def default_model(self) -> str:
        return "llama3.2"

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

        # 转换消息格式 (Ollama 格式)
        ollama_messages = []
        for msg in messages:
            role = msg.role.value if hasattr(msg.role, 'value') else msg.role
            ollama_messages.append({
                "role": role,
                "content": msg.content,
            })

        model_name = model or self.default_model

        request_data: dict[str, Any] = {
            "model": model_name,
            "messages": ollama_messages,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.7),
                "num_predict": kwargs.get("max_tokens", 4096),
            },
        }

        # 添加 tools 如果支持
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
            response = await self.client.post("/api/chat", json=request_data)
            response.raise_for_status()
            data = response.json()

            content = data.get("message", {}).get("content", "")

            tool_calls = []
            if "tool_calls" in data.get("message", {}):
                for tc in data["message"]["tool_calls"]:
                    tool_calls.append(
                        ToolCall(
                            id=tc.get("id", ""),
                            name=tc.get("function", {}).get("name", ""),
                            arguments=tc.get("function", {}).get("arguments", "{}"),
                        )
                    )

            return LLMResponse(
                content=content,
                model=model_name,
                usage={
                    "prompt_tokens": data.get("prompt_eval_count", 0),
                    "completion_tokens": data.get("eval_count", 0),
                    "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
                },
                finish_reason=data.get("done_reason", "stop"),
                tool_calls=tool_calls,
            )

        except httpx.HTTPError as e:
            logger.error(f"Local model API call failed: {e}")
            raise

    async def stream(
        self,
        messages: list["LLMMessage"],
        model: str | None = None,
        tools: list["ToolDefinition"] | None = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        from app.core.llm.client import LLMMessage

        # 转换消息格式
        ollama_messages = []
        for msg in messages:
            role = msg.role.value if hasattr(msg.role, 'value') else msg.role
            ollama_messages.append({
                "role": role,
                "content": msg.content,
            })

        model_name = model or self.default_model

        request_data: dict[str, Any] = {
            "model": model_name,
            "messages": ollama_messages,
            "stream": True,
            "options": {
                "temperature": kwargs.get("temperature", 0.7),
                "num_predict": kwargs.get("max_tokens", 4096),
            },
        }

        try:
            async with self.client.stream("POST", "/api/chat", json=request_data) as stream:
                async for line in stream.aiter_lines():
                    if line:
                        import json
                        data = json.loads(line)
                        if "message" in data and "content" in data["message"]:
                            content = data["message"]["content"]
                            if content:
                                yield content

        except httpx.HTTPError as e:
            logger.error(f"Local model streaming failed: {e}")
            raise

    async def embeddings(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """获取文本嵌入"""
        model_name = model or "nomic-embed-text"

        try:
            embeddings = []
            for text in texts:
                response = await self.client.post(
                    "/api/embeddings",
                    json={"model": model_name, "prompt": text},
                )
                response.raise_for_status()
                data = response.json()
                embeddings.append(data.get("embedding", []))
            return embeddings
        except httpx.HTTPError as e:
            logger.error(f"Local embedding failed: {e}")
            raise

    async def health_check(self) -> bool:
        """健康检查"""
        try:
            response = await self.client.get("/api/tags")
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
            context_window=4096,
            max_output_tokens=2048,
            cost_per_input=0.0,
            cost_per_output=0.0,
            avg_latency_ms=500,
            reliability=0.90,
        )

    async def list_models(self) -> list[str]:
        """列出本地可用的模型"""
        try:
            response = await self.client.get("/api/tags")
            response.raise_for_status()
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []
