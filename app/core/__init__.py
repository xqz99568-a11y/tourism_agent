from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "settings": ("app.core.config", "settings"),
    "get_settings": ("app.core.config", "get_settings"),
    "SessionContext": ("app.core.context", "SessionContext"),
    "ExecutionContext": ("app.core.context", "ExecutionContext"),
    "UserPreferences": ("app.core.context", "UserPreferences"),
    "TripContext": ("app.core.context", "TripContext"),
    "ConversationTurn": ("app.core.context", "ConversationTurn"),
    "Container": ("app.core.di", "Container"),
    "get_container": ("app.core.di", "get_container"),
    "init_container": ("app.core.di", "init_container"),
    "shutdown_container": ("app.core.di", "shutdown_container"),
    "LifecycleManager": ("app.core.di", "LifecycleManager"),
    "injectable": ("app.core.di", "injectable"),
    "inject": ("app.core.di", "inject"),
    "request_scope": ("app.core.di", "request_scope"),
    "RequestContext": ("app.core.middleware", "RequestContext"),
    "TracingMiddleware": ("app.core.middleware", "TracingMiddleware"),
    "get_tracing": ("app.core.middleware", "get_tracing"),
    "traced": ("app.core.middleware", "traced"),
    "CacheMiddleware": ("app.core.middleware", "CacheMiddleware"),
    "get_cache": ("app.core.middleware", "get_cache"),
    "cached": ("app.core.middleware", "cached"),
    "RateLimiter": ("app.core.middleware", "RateLimiter"),
    "get_rate_limiter": ("app.core.middleware", "get_rate_limiter"),
    "MiddlewareChain": ("app.core.middleware", "MiddlewareChain"),
    "LogMiddleware": ("app.core.middleware", "LogMiddleware"),
    "ToolStrategy": ("app.core.tool_strategy", "ToolStrategy"),
    "ToolStrategyType": ("app.core.tool_strategy", "ToolStrategyType"),
    "ToolExecutionContext": ("app.core.tool_strategy", "ToolExecutionContext"),
    "ToolExecutionResult": ("app.core.tool_strategy", "ToolExecutionResult"),
    "DirectToolStrategy": ("app.core.tool_strategy", "DirectToolStrategy"),
    "RetryToolStrategy": ("app.core.tool_strategy", "RetryToolStrategy"),
    "TimeoutToolStrategy": ("app.core.tool_strategy", "TimeoutToolStrategy"),
    "FallbackToolStrategy": ("app.core.tool_strategy", "FallbackToolStrategy"),
    "CachedToolStrategy": ("app.core.tool_strategy", "CachedToolStrategy"),
    "ParallelToolStrategy": ("app.core.tool_strategy", "ParallelToolStrategy"),
    "CircuitBreakerToolStrategy": ("app.core.tool_strategy", "CircuitBreakerToolStrategy"),
    "CompositeToolStrategy": ("app.core.tool_strategy", "CompositeToolStrategy"),
    "ToolStrategyManager": ("app.core.tool_strategy", "ToolStrategyManager"),
    "get_tool_strategy_manager": ("app.core.tool_strategy", "get_tool_strategy_manager"),
    "Document": ("app.core.rag", "Document"),
    "Chunk": ("app.core.rag", "Chunk"),
    "RetrievalResult": ("app.core.rag", "RetrievalResult"),
    "RAGContext": ("app.core.rag", "RAGContext"),
    "ChunkingStrategy": ("app.core.rag", "ChunkingStrategy"),
    "EmbeddingFunction": ("app.core.rag", "EmbeddingFunction"),
    "RAGEngine": ("app.core.rag", "RAGEngine"),
    "get_rag_engine": ("app.core.rag", "get_rag_engine"),
    "init_rag_engine": ("app.core.rag", "init_rag_engine"),
    "AgentRequestCache": ("app.core.agent_cache", "AgentRequestCache"),
    "get_agent_cache": ("app.core.agent_cache", "get_agent_cache"),
    "init_agent_cache": ("app.core.agent_cache", "init_agent_cache"),
    "RequestCacheKey": ("app.core.agent_cache", "RequestCacheKey"),
    "CachedAgentResult": ("app.core.agent_cache", "CachedAgentResult"),
    "CacheMetrics": ("app.core.agent_cache", "CacheMetrics"),
    "OptimizedAgentOrchestrator": ("app.core.optimized_orchestrator", "OptimizedAgentOrchestrator"),
    "UnifiedAgentExecutor": ("app.core.optimized_orchestrator", "UnifiedAgentExecutor"),
    "CacheMonitor": ("app.core.cache_monitor", "CacheMonitor"),
    "get_cache_monitor": ("app.core.cache_monitor", "get_cache_monitor"),
    "init_cache_monitor": ("app.core.cache_monitor", "init_cache_monitor"),
    "OptimizationStats": ("app.core.cache_monitor", "OptimizationStats"),
    "CacheSnapshot": ("app.core.cache_monitor", "CacheSnapshot"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
