# Agent Package
"""
Agent Framework
提供基于 Protocol 的 Agent 系统
"""

from app.core.agent.protocol import (
    AgentProtocol,
    AgentType,
    AgentTask,
    AgentResult,
    ExecutionPlan,
    AgentCapability,
    TaskStatus,
    Priority,
    TaskDependency,
    AgentFactory,
    register_agent,
)

from app.core.agent.base import (
    BaseAgent,
    LifecycleState,
    AgentEvent,
    register_agent as register_agent_decorator,
)

from app.core.agent.message_bus import (
    MessageBus,
    Message,
    MessageType,
    MessagePriority,
    Subscription,
    get_message_bus,
    init_message_bus,
    shutdown_message_bus,
)

from app.core.agent.context import (
    SharedContext,
    ExecutionContext,
    StateEntry,
)

from app.core.agent.registry import (
    AgentRegistry,
    AgentRegistration,
    AgentDependency,
    get_agent_registry,
    init_agent_registry,
    shutdown_agent_registry,
    agent,
)

from app.core.agent.orchestrator import (
    AgentOrchestrator,
    OrchestratorState,
    OrchestratorConfig,
    OrchestratorStats,
    TaskDecomposer,
    DAGScheduler,
    ConcurrentExecutor,
    ResultAggregator,
)

# Agents
from app.core.agent.memory_agent import (
    MemoryAgent,
    MemoryStore,
    MemoryEntry,
    MemoryType,
)

from app.core.agent.reflection_agent import (
    ReflectionAgent,
    ReflectionCriteria,
)

from app.core.agent.quality_agent import (
    QualityAgent,
    QualityDimension,
)

__all__ = [
    # Protocol
    "AgentProtocol",
    "AgentType",
    "AgentTask",
    "AgentResult",
    "ExecutionPlan",
    "AgentCapability",
    "TaskStatus",
    "Priority",
    "TaskDependency",
    "AgentFactory",
    "register_agent",
    # Base
    "BaseAgent",
    "LifecycleState",
    "AgentEvent",
    "register_agent_decorator",
    # Message Bus
    "MessageBus",
    "Message",
    "MessageType",
    "MessagePriority",
    "Subscription",
    "get_message_bus",
    "init_message_bus",
    "shutdown_message_bus",
    # Context
    "SharedContext",
    "ExecutionContext",
    "StateEntry",
    # Registry
    "AgentRegistry",
    "AgentRegistration",
    "AgentDependency",
    "get_agent_registry",
    "init_agent_registry",
    "shutdown_agent_registry",
    "agent",
    # Orchestrator
    "AgentOrchestrator",
    "OrchestratorState",
    "OrchestratorConfig",
    "OrchestratorStats",
    "TaskDecomposer",
    "DAGScheduler",
    "ConcurrentExecutor",
    "ResultAggregator",
    # Agents
    "MemoryAgent",
    "MemoryStore",
    "MemoryEntry",
    "MemoryType",
    "ReflectionAgent",
    "ReflectionCriteria",
    "QualityAgent",
    "QualityDimension",
]
