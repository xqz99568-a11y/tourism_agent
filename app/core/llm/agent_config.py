"""
Agent 模型配置 (简化版)
定义 Agent 使用统一模型配置
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


class RouterStrategy:
    """路由策略"""
    BALANCED = "balanced"
    COST_OPTIMIZED = "cost_optimized"
    QUALITY_OPTIMIZED = "quality_optimized"
    LATENCY_OPTIMIZED = "latency_optimized"


class TaskType:
    """任务类型"""
    INTENT_PARSING = "intent_parsing"
    TOOL_CALLING = "tool_calling"
    COMPLEX_REASONING = "complex_reasoning"
    SIMPLE_CHAT = "simple_chat"


@dataclass
class ModelPreference:
    """模型偏好配置"""
    preferred_model: Optional[str] = None
    preferred_provider: Optional[str] = None
    fallback_models: List[str] = field(default_factory=list)
    strategy: str = RouterStrategy.BALANCED
    temperature: float = 0.3
    max_tokens: int = 4096
    enable_cache: bool = True
    enable_fallback: bool = True


@dataclass
class AgentModelConfig:
    """Agent 模型配置"""
    agent_name: str
    task_type: str
    model_preference: ModelPreference = field(default_factory=ModelPreference)
    description: str = ""


class AgentModelRegistry:
    """
    Agent 模型配置注册表
    简化版：所有 Agent 使用统一配置
    """

    # 简化配置
    DEFAULT_CONFIGS: Dict[str, AgentModelConfig] = {
        "orchestrator": AgentModelConfig(
            agent_name="orchestrator",
            task_type=TaskType.INTENT_PARSING,
            model_preference=ModelPreference(
                temperature=0.3,
                max_tokens=2048,
            ),
            description="编排器 - 意图解析",
        ),
        "planner": AgentModelConfig(
            agent_name="planner",
            task_type=TaskType.COMPLEX_REASONING,
            model_preference=ModelPreference(
                temperature=0.5,
                max_tokens=8192,
            ),
            description="规划器 - 复杂推理",
        ),
        "attraction": AgentModelConfig(
            agent_name="attraction",
            task_type=TaskType.TOOL_CALLING,
            model_preference=ModelPreference(
                temperature=0.3,
                max_tokens=4096,
            ),
            description="景点推荐 - 工具调用",
        ),
        "itinerary": AgentModelConfig(
            agent_name="itinerary",
            task_type=TaskType.COMPLEX_REASONING,
            model_preference=ModelPreference(
                temperature=0.4,
                max_tokens=8192,
            ),
            description="行程规划 - 复杂推理",
        ),
        "budget": AgentModelConfig(
            agent_name="budget",
            task_type=TaskType.TOOL_CALLING,
            model_preference=ModelPreference(
                temperature=0.2,
                max_tokens=2048,
            ),
            description="预算分析 - 工具调用",
        ),
        "weather": AgentModelConfig(
            agent_name="weather",
            task_type=TaskType.TOOL_CALLING,
            model_preference=ModelPreference(
                temperature=0.1,
                max_tokens=1024,
            ),
            description="天气查询 - 快速响应",
        ),
        "review": AgentModelConfig(
            agent_name="review",
            task_type=TaskType.COMPLEX_REASONING,
            model_preference=ModelPreference(
                temperature=0.3,
                max_tokens=4096,
                enable_cache=False,
            ),
            description="审查 - 质量敏感",
        ),
    }

    def __init__(self):
        self._configs: Dict[str, AgentModelConfig] = dict(self.DEFAULT_CONFIGS)

    def get_config(self, agent_name: str) -> Optional[AgentModelConfig]:
        """获取 Agent 的模型配置"""
        return self._configs.get(agent_name)

    def get_all_configs(self) -> Dict[str, AgentModelConfig]:
        """获取所有配置"""
        return dict(self._configs)


# 全局注册表实例
_agent_model_registry: Optional[AgentModelRegistry] = None


def get_agent_model_registry() -> AgentModelRegistry:
    """获取 Agent 模型注册表"""
    global _agent_model_registry
    if _agent_model_registry is None:
        _agent_model_registry = AgentModelRegistry()
    return _agent_model_registry


def get_agent_model_config(agent_name: str) -> Optional[ModelPreference]:
    """获取 Agent 的模型偏好配置"""
    registry = get_agent_model_registry()
    config = registry.get_config(agent_name)
    return config.model_preference if config else None


def update_agent_model(
    agent_name: str,
    model: str,
    provider: Optional[str] = None,
) -> bool:
    """快捷方法：更新 Agent 的模型"""
    registry = get_agent_model_registry()
    config = registry.get_config(agent_name)
    if config:
        config.model_preference.preferred_model = model
        config.model_preference.preferred_provider = provider
        return True
    return False
