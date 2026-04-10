"""
LLM 路由模块 (简化版)
提供简单的任务类型和路由策略定义
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TaskType(str, Enum):
    """任务类型"""
    INTENT_PARSING = "intent_parsing"       # 意图解析
    TOOL_CALLING = "tool_calling"           # 工具调用
    COMPLEX_REASONING = "complex_reasoning" # 复杂推理
    SIMPLE_CHAT = "simple_chat"             # 简单对话


class RouterStrategy(str, Enum):
    """路由策略"""
    BALANCED = "balanced"                   # 平衡策略
    COST_OPTIMIZED = "cost_optimized"       # 成本优先
    QUALITY_OPTIMIZED = "quality_optimized" # 质量优先
    LATENCY_OPTIMIZED = "latency_optimized" # 延迟优先


@dataclass
class RoutingContext:
    """路由上下文"""
    task_type: TaskType
    strategy: RouterStrategy = RouterStrategy.BALANCED
    preferred_model: Optional[str] = None
    temperature: float = 0.3
    max_tokens: int = 4096


@dataclass
class RouteResult:
    """路由结果"""
    provider: str
    model: str
    context: RoutingContext
    reason: str = ""


# 保留兼容性别名
ModelRouter = None
