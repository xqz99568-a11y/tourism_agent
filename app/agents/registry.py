"""
Agent 注册中心
管理所有 Agent 的注册和发现
"""
from __future__ import annotations

from typing import Dict, List, Optional, Type

from app.agents.base import AgentConfig, AgentCapability, BaseAgent
from app.core.logger import get_logger

logger = get_logger(__name__)


class AgentRegistry:
    """
    Agent 注册中心
    提供 Agent 的注册、查找和发现功能
    """

    def __init__(self):
        self._agents: Dict[str, Type[BaseAgent]] = {}
        self._configs: Dict[str, AgentConfig] = {}
        self._capability_map: Dict[AgentCapability, List[str]] = {}

    def register(
        self,
        agent_class: Type[BaseAgent],
        config: AgentConfig,
    ) -> None:
        """
        注册 Agent

        Args:
            agent_class: Agent 类
            config: Agent 配置
        """
        self._agents[config.name] = agent_class
        self._configs[config.name] = config

        # 更新能力映射
        for capability in config.capabilities:
            if capability not in self._capability_map:
                self._capability_map[capability] = []
            self._capability_map[capability].append(config.name)

        logger.info(f"Registered agent: {config.name} with capabilities: {config.capabilities}")

    def get(self, name: str) -> Optional[Type[BaseAgent]]:
        """获取 Agent 类"""
        return self._agents.get(name)

    def get_config(self, name: str) -> Optional[AgentConfig]:
        """获取 Agent 配置"""
        return self._configs.get(name)

    def get_all(self) -> Dict[str, Type[BaseAgent]]:
        """获取所有注册的 Agent"""
        return self._agents.copy()

    def get_by_capability(self, capability: AgentCapability) -> List[str]:
        """根据能力查找 Agent"""
        return self._capability_map.get(capability, [])

    def get_by_capabilities(self, capabilities: List[AgentCapability]) -> List[str]:
        """根据多个能力查找 Agent (交集)"""
        if not capabilities:
            return list(self._agents.keys())

        result = None
        for cap in capabilities:
            agents = set(self._capability_map.get(cap, []))
            if result is None:
                result = agents
            else:
                result = result.intersection(agents)

        return list(result) if result else []

    def list_names(self) -> List[str]:
        """列出所有 Agent 名称"""
        return list(self._agents.keys())

    def exists(self, name: str) -> bool:
        """检查 Agent 是否存在"""
        return name in self._agents

    def unregister(self, name: str) -> bool:
        """注销 Agent"""
        if name in self._agents:
            del self._agents[name]

            # 清理能力映射
            config = self._configs.get(name)
            if config:
                for capability in config.capabilities:
                    if capability in self._capability_map:
                        self._capability_map[capability].remove(name)

            del self._configs[name]
            logger.info(f"Unregistered agent: {name}")
            return True

        return False


# 全局注册中心
_global_registry: Optional[AgentRegistry] = None


def get_registry() -> AgentRegistry:
    """获取全局注册中心"""
    global _global_registry
    if _global_registry is None:
        _global_registry = AgentRegistry()
    return _global_registry


def register_agent(
    agent_class: Type[BaseAgent],
    config: AgentConfig,
) -> None:
    """装饰器：注册 Agent"""
    registry = get_registry()
    registry.register(agent_class, config)


def get_agent(name: str) -> Optional[Type[BaseAgent]]:
    """获取 Agent"""
    return get_registry().get(name)


def get_agent_config(name: str) -> Optional[AgentConfig]:
    """获取 Agent 配置"""
    return get_registry().get_config(name)
