"""
LLM Provider 抽象接口
支持多种 LLM Provider 的统一接口
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, AsyncGenerator, List, Optional

if TYPE_CHECKING:
    from app.core.llm.client import LLMMessage, ToolDefinition


class ModelCapability(str, Enum):
    """模型能力"""
    CHAT = "chat"                      # 基础对话
    STREAMING = "streaming"             # 流式输出
    FUNCTION_CALLING = "function_calling"  # 函数调用
    VISION = "vision"                  # 视觉理解
    LONG_CONTEXT = "long_context"      # 长上下文
    REASONING = "reasoning"            # 复杂推理
    FAST = "fast"                      # 快速响应


@dataclass
class ModelInfo:
    """模型信息"""
    name: str                          # 模型标识符
    provider: str                      # 提供商
    display_name: str                  # 显示名称
    capabilities: List[ModelCapability] = field(default_factory=list)
    context_window: int = 128_000      # 上下文窗口大小
    max_output_tokens: int = 8192      # 最大输出 token 数
    cost_per_input: float = 0.0        # 每 1M input tokens 成本
    cost_per_output: float = 0.0       # 每 1M output tokens 成本
    avg_latency_ms: float = 0.0        # 平均延迟 (ms)
    reliability: float = 1.0           # 可靠性 (0-1)

    @property
    def cost_per_1k(self) -> tuple[float, float]:
        """每 1K token 的成本 (input, output)"""
        return (self.cost_per_input / 1000, self.cost_per_output / 1000)

    def supports(self, capability: ModelCapability) -> bool:
        """检查是否支持指定能力"""
        return capability in self.capabilities

    def is_suitable_for(self, task_type: str) -> bool:
        """检查是否适合指定任务类型"""
        task_capability_map = {
            "simple_chat": [ModelCapability.CHAT, ModelCapability.FAST],
            "complex_reasoning": [ModelCapability.REASONING, ModelCapability.LONG_CONTEXT],
            "tool_calling": [ModelCapability.FUNCTION_CALLING],
            "streaming": [ModelCapability.STREAMING],
            "vision": [ModelCapability.VISION],
        }
        required = task_capability_map.get(task_type, [])
        return all(cap in self.capabilities for cap in required)


class BaseLLMProvider(ABC):
    """
    LLM Provider 抽象基类
    所有 Provider 必须实现此接口
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider 名称"""
        pass

    @property
    @abstractmethod
    def default_model(self) -> str:
        """默认模型"""
        pass

    @property
    @abstractmethod
    def supported_models(self) -> List[ModelInfo]:
        """支持的模型列表"""
        pass

    @abstractmethod
    async def chat(
        self,
        messages: List["LLMMessage"],
        model: Optional[str] = None,
        tools: Optional[List["ToolDefinition"]] = None,
        **kwargs,
    ) -> Any:
        """发送对话请求"""
        pass

    @abstractmethod
    async def stream(
        self,
        messages: List["LLMMessage"],
        model: Optional[str] = None,
        tools: Optional[List["ToolDefinition"]] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """流式对话"""
        pass

    @abstractmethod
    async def embeddings(self, texts: List[str], model: Optional[str] = None) -> List[List[float]]:
        """获取文本嵌入"""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查"""
        pass

    def get_model_info(self, model: Optional[str] = None) -> ModelInfo:
        """获取模型信息"""
        model_name = model or self.default_model
        for info in self.supported_models:
            if info.name == model_name:
                return info
        # 返回默认信息
        return ModelInfo(
            name=model_name,
            provider=self.provider_name,
            display_name=model_name,
        )
