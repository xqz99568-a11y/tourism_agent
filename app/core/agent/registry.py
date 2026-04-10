"""
Agent Registry - Agent 注册中心
管理 Agent 的注册、生命周期和依赖注入
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

from app.core.agent.base import BaseAgent, LifecycleState
from app.core.agent.protocol import AgentProtocol, AgentType
from app.core.agent.message_bus import MessageBus
from app.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class AgentDependency:
    """Agent 依赖"""
    agent_name: str
    required: bool = True
    optional: bool = False


@dataclass
class AgentRegistration:
    """Agent 注册信息"""
    name: str
    agent_type: AgentType
    cls: Type[AgentProtocol]
    description: str = ""
    dependencies: List[AgentDependency] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    instance: Optional[AgentProtocol] = None


class AgentRegistry:
    """
    Agent 注册中心
    统一管理所有 Agent 的注册、初始化和生命周期
    """

    def __init__(self, message_bus: Optional[MessageBus] = None):
        self.message_bus = message_bus
        self._registrations: Dict[str, AgentRegistration] = {}
        self._agents: Dict[str, AgentProtocol] = {}
        self._initialized = False
        self._lock = asyncio.Lock()

        logger.info("AgentRegistry initialized")

    def register(
        self,
        name: str,
        agent_cls: Type[AgentProtocol],
        agent_type: AgentType,
        description: str = "",
        dependencies: Optional[List[AgentDependency]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        注册 Agent

        Args:
            name: Agent 名称
            agent_cls: Agent 类
            agent_type: Agent 类型
            description: 描述
            dependencies: 依赖的其他 Agent
            config: 配置参数
        """
        if name in self._registrations:
            logger.warning(f"Agent '{name}' already registered, overwriting")

        registration = AgentRegistration(
            name=name,
            agent_type=agent_type,
            cls=agent_cls,
            description=description,
            dependencies=dependencies or [],
            config=config or {},
        )

        self._registrations[name] = registration
        logger.info(f"Registered agent: {name} (type: {agent_type.value})")

    def register_instance(self, agent: AgentProtocol) -> None:
        """
        注册已创建的 Agent 实例

        Args:
            agent: Agent 实例
        """
        name = agent.name

        if name in self._registrations:
            self._registrations[name].instance = agent
        else:
            self._registrations[name] = AgentRegistration(
                name=name,
                agent_type=agent.agent_type,
                cls=type(agent),
                instance=agent,
            )

        self._agents[name] = agent
        logger.info(f"Registered agent instance: {name}")

    def get(self, name: str) -> Optional[AgentProtocol]:
        """获取 Agent 实例"""
        return self._agents.get(name)

    def get_registration(self, name: str) -> Optional[AgentRegistration]:
        """获取 Agent 注册信息"""
        return self._registrations.get(name)

    def get_all(self) -> Dict[str, AgentProtocol]:
        """获取所有 Agent 实例"""
        return dict(self._agents)

    def get_by_type(self, agent_type: AgentType) -> List[AgentProtocol]:
        """获取指定类型的所有 Agent"""
        return [
            agent for agent in self._agents.values()
            if agent.agent_type == agent_type
        ]

    def list_agents(self) -> List[str]:
        """列出所有已注册的 Agent"""
        return list(self._registrations.keys())

    def list_types(self) -> List[AgentType]:
        """列出所有已注册的类型"""
        return list(set(reg.agent_type for reg in self._registrations.values()))

    def has(self, name: str) -> bool:
        """检查 Agent 是否已注册"""
        return name in self._registrations

    def unregister(self, name: str) -> bool:
        """
        注销 Agent

        Args:
            name: Agent 名称

        Returns:
            是否成功注销
        """
        if name not in self._registrations:
            return False

        # 如果有实例，先关闭
        if name in self._agents:
            agent = self._agents[name]
            if hasattr(agent, 'shutdown'):
                asyncio.create_task(agent.shutdown())
            del self._agents[name]

        del self._registrations[name]
        logger.info(f"Unregistered agent: {name}")
        return True

    # ========== 生命周期管理 ==========

    async def initialize(self) -> None:
        """初始化所有 Agent"""
        async with self._lock:
            if self._initialized:
                logger.warning("AgentRegistry already initialized")
                return

            logger.info("Initializing all agents...")

            # 排序初始化顺序（考虑依赖关系）
            sorted_names = self._resolve_init_order()

            for name in sorted_names:
                reg = self._registrations[name]
                if reg.instance:
                    # 已有实例
                    if hasattr(reg.instance, 'initialize'):
                        await reg.instance.initialize()
                    logger.debug(f"Agent '{name}' already instantiated")
                else:
                    # 创建新实例
                    try:
                        agent = self._create_instance(reg)
                        reg.instance = agent
                        self._agents[name] = agent

                        if hasattr(agent, 'initialize'):
                            await agent.initialize()

                    except Exception as e:
                        logger.error(f"Failed to create agent '{name}': {e}")

            self._initialized = True
            logger.info(f"All agents initialized. Total: {len(self._agents)}")

    async def shutdown(self) -> None:
        """关闭所有 Agent"""
        async with self._lock:
            logger.info("Shutting down all agents...")

            for name, agent in list(self._agents.items()):
                try:
                    if hasattr(agent, 'shutdown'):
                        await agent.shutdown()
                except Exception as e:
                    logger.error(f"Error shutting down agent '{name}': {e}")

            self._agents.clear()
            self._initialized = False
            logger.info("All agents shut down")

    def _resolve_init_order(self) -> List[str]:
        """解析初始化顺序（基于依赖关系）"""
        sorted_names = []
        remaining = set(self._registrations.keys())
        resolved = set()

        while remaining:
            progress = False

            for name in list(remaining):
                reg = self._registrations[name]
                deps_satisfied = True

                for dep in reg.dependencies:
                    if dep.required and dep.agent_name not in resolved:
                        deps_satisfied = False
                        break

                if deps_satisfied:
                    sorted_names.append(name)
                    remaining.remove(name)
                    resolved.add(name)
                    progress = True

            if not progress:
                # 无法继续解析，可能有循环依赖或缺少依赖
                # 仍然添加到列表，但记录警告
                for name in remaining:
                    logger.warning(f"Could not resolve dependencies for agent '{name}'")
                    sorted_names.append(name)
                break

        return sorted_names

    def _create_instance(self, reg: AgentRegistration) -> AgentProtocol:
        """创建 Agent 实例"""
        # 准备初始化参数
        init_kwargs = {
            "name": reg.name,
            "agent_type": reg.agent_type,
            "description": reg.description,
            "message_bus": self.message_bus,
            "registry": self,
            **reg.config,
        }

        # 创建实例
        agent = reg.cls(**init_kwargs)
        return agent

    # ========== 依赖注入 ==========

    def get_dependencies(self, agent_name: str) -> Dict[str, AgentProtocol]:
        """
        获取 Agent 的依赖实例

        Args:
            agent_name: Agent 名称

        Returns:
            依赖的 Agent 实例字典
        """
        reg = self._registrations.get(agent_name)
        if not reg:
            return {}

        deps = {}
        for dep in reg.dependencies:
            instance = self._agents.get(dep.agent_name)
            if instance:
                deps[dep.agent_name] = instance
            elif dep.required:
                logger.warning(f"Required dependency '{dep.agent_name}' not available for '{agent_name}'")

        return deps

    def resolve_dependencies(self, agent: AgentProtocol) -> Dict[str, Any]:
        """
        为 Agent 解析依赖

        Args:
            agent: Agent 实例

        Returns:
            依赖实例的字典，可直接传给 Agent
        """
        return self.get_dependencies(agent.name)

    # ========== 工厂方法 ==========

    async def create_agent(
        self,
        name: str,
        agent_cls: Type[AgentProtocol],
        agent_type: AgentType,
        **kwargs,
    ) -> AgentProtocol:
        """
        创建并注册新 Agent

        Args:
            name: Agent 名称
            agent_cls: Agent 类
            agent_type: Agent 类型
            **kwargs: 传递给 Agent 构造函数的参数

        Returns:
            创建的 Agent 实例
        """
        if name in self._agents:
            raise ValueError(f"Agent '{name}' already exists")

        # 添加消息总线和注册表
        kwargs["message_bus"] = kwargs.get("message_bus", self.message_bus)
        kwargs["registry"] = kwargs.get("registry", self)

        agent = agent_cls(name=name, agent_type=agent_type, **kwargs)
        self.register_instance(agent)

        if self._initialized and hasattr(agent, 'initialize'):
            await agent.initialize()

        return agent

    async def destroy_agent(self, name: str) -> bool:
        """
        销毁 Agent

        Args:
            name: Agent 名称

        Returns:
            是否成功销毁
        """
        if name not in self._agents:
            return False

        agent = self._agents[name]

        if hasattr(agent, 'shutdown'):
            await agent.shutdown()

        self.unregister(name)
        return True

    # ========== 统计信息 ==========

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        type_counts: Dict[str, int] = {}
        for reg in self._registrations.values():
            type_name = reg.agent_type.value
            type_counts[type_name] = type_counts.get(type_name, 0) + 1

        state_counts: Dict[str, int] = {}
        for agent in self._agents.values():
            if hasattr(agent, 'state'):
                state_name = agent.state.value
                state_counts[state_name] = state_counts.get(state_name, 0) + 1

        return {
            "total_agents": len(self._registrations),
            "initialized_agents": len(self._agents),
            "is_initialized": self._initialized,
            "by_type": type_counts,
            "by_state": state_counts,
        }


# ========== 全局注册表实例 ==========

_registry: Optional[AgentRegistry] = None


def get_agent_registry() -> AgentRegistry:
    """获取全局 Agent 注册表"""
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry


async def init_agent_registry(message_bus: Optional[MessageBus] = None) -> AgentRegistry:
    """初始化全局 Agent 注册表"""
    global _registry
    _registry = AgentRegistry(message_bus=message_bus)
    return _registry


async def shutdown_agent_registry() -> None:
    """关闭全局 Agent 注册表"""
    global _registry
    if _registry:
        await _registry.shutdown()
        _registry = None


# ========== 装饰器 ==========

def agent(
    name: str,
    agent_type: AgentType,
    description: str = "",
    dependencies: Optional[List[str]] = None,
    config: Optional[Dict[str, Any]] = None,
):
    """
    Agent 注册装饰器

    Usage:
        @agent(name="planner", agent_type=AgentType.PLANNER, dependencies=["memory"])
        class PlannerAgent(BaseAgent):
            ...
    """
    deps = [AgentDependency(d) for d in (dependencies or [])]

    def decorator(cls: Type[AgentProtocol]):
        registry = get_agent_registry()
        registry.register(
            name=name,
            agent_cls=cls,
            agent_type=agent_type,
            description=description,
            dependencies=deps,
            config=config,
        )
        return cls

    return decorator
