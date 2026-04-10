"""
Middleware Layer - 中间件层
提供日志、追踪、缓存等中间件能力
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional
import hashlib

from app.core.logger import get_logger

logger = get_logger(__name__)

# ========== 请求上下文 ==========

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


def get_request_id() -> str:
    """获取当前请求ID"""
    return request_id_var.get()


def get_trace_id() -> str:
    """获取当前追踪ID"""
    return trace_id_var.get()


def set_request_context(request_id: str, trace_id: Optional[str] = None) -> None:
    """设置请求上下文"""
    request_id_var.set(request_id)
    trace_id_var.set(trace_id or str(uuid.uuid4()))


class RequestContext:
    """请求上下文"""

    def __init__(self, request_id: Optional[str] = None, trace_id: Optional[str] = None):
        self.request_id = request_id or str(uuid.uuid4())
        self.trace_id = trace_id or str(uuid.uuid4())
        self.start_time = time.time()
        self.metadata: Dict[str, Any] = {}

    @property
    def elapsed_ms(self) -> float:
        """经过的时间（毫秒）"""
        return (time.time() - self.start_time) * 1000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "elapsed_ms": self.elapsed_ms,
            "metadata": self.metadata,
        }


# ========== Tracing 中间件 ==========

class SpanStatus(str, Enum):
    """Span 状态"""
    OK = "ok"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class Span:
    """追踪 Span"""
    name: str
    trace_id: str
    span_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    parent_span_id: Optional[str] = None
    service_name: str = "tourism_agent"
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    status: SpanStatus = SpanStatus.OK
    error_message: Optional[str] = None
    tags: Dict[str, str] = field(default_factory=dict)
    logs: List[Dict[str, Any]] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)

    def finish(self, status: SpanStatus = SpanStatus.OK, error: Optional[str] = None) -> None:
        """结束 Span"""
        self.end_time = time.time()
        self.status = status
        if error:
            self.error_message = error
            self.status = SpanStatus.ERROR

    @property
    def duration_ms(self) -> float:
        """持续时间（毫秒）"""
        if self.end_time:
            return (self.end_time - self.start_time) * 1000
        return (time.time() - self.start_time) * 1000

    def add_tag(self, key: str, value: str) -> None:
        """添加标签"""
        self.tags[key] = value

    def add_log(self, message: str, **kwargs) -> None:
        """添加日志"""
        self.logs.append({
            "timestamp": datetime.utcnow().isoformat(),
            "message": message,
            **kwargs,
        })

    def set_attribute(self, key: str, value: Any) -> None:
        """设置属性"""
        self.attributes[key] = value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "service_name": self.service_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "status": self.status.value,
            "error_message": self.error_message,
            "tags": self.tags,
            "logs": self.logs,
            "attributes": self.attributes,
        }


class TracingMiddleware:
    """
    追踪中间件
    提供分布式追踪能力
    """

    def __init__(self, service_name: str = "tourism_agent"):
        self.service_name = service_name
        self._spans: Dict[str, Span] = {}
        self._current_span_var: ContextVar[Optional[Span]] = ContextVar("current_span", default=None)

    def start_span(
        self,
        name: str,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
    ) -> Span:
        """
        开始一个 Span

        Args:
            name: Span 名称
            trace_id: 追踪ID
            parent_span_id: 父 Span ID
            tags: 标签

        Returns:
            Span 实例
        """
        trace_id = trace_id or get_trace_id() or str(uuid.uuid4())

        # 获取当前 span 作为父 span
        current_span = self._current_span_var.get()
        if current_span and not parent_span_id:
            parent_span_id = current_span.span_id

        span = Span(
            name=name,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            service_name=self.service_name,
            tags=tags or {},
        )

        self._spans[span.span_id] = span
        self._current_span_var.set(span)

        logger.debug(f"Started span: {name} ({span.span_id})")
        return span

    def end_span(self, span: Span, status: SpanStatus = SpanStatus.OK, error: Optional[str] = None) -> None:
        """结束一个 Span"""
        span.finish(status=status, error=error)
        self._current_span_var.set(None)
        logger.debug(f"Ended span: {span.name} ({span.span_id}) - {span.duration_ms:.2f}ms")

    def get_current_span(self) -> Optional[Span]:
        """获取当前 Span"""
        return self._current_span_var.get()

    def get_trace(self, trace_id: str) -> List[Span]:
        """获取追踪的所有 Span"""
        return [
            span for span in self._spans.values()
            if span.trace_id == trace_id
        ]

    def clear(self) -> None:
        """清空所有 Span"""
        self._spans.clear()


# 全局追踪中间件
_tracing: Optional[TracingMiddleware] = None


def get_tracing() -> TracingMiddleware:
    """获取追踪中间件"""
    global _tracing
    if _tracing is None:
        _tracing = TracingMiddleware()
    return _tracing


def traced(
    name: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
):
    """
    追踪装饰器

    Usage:
        @traced("my_function")
        async def my_function():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            span_name = name or func.__name__
            tracing = get_tracing()

            span = tracing.start_span(span_name, tags=tags)
            try:
                result = await func(*args, **kwargs)
                tracing.end_span(span, SpanStatus.OK)
                return result
            except Exception as e:
                tracing.end_span(span, SpanStatus.ERROR, str(e))
                raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            span_name = name or func.__name__
            tracing = get_tracing()

            span = tracing.start_span(span_name, tags=tags)
            try:
                result = func(*args, **kwargs)
                tracing.end_span(span, SpanStatus.OK)
                return result
            except Exception as e:
                tracing.end_span(span, SpanStatus.ERROR, str(e))
                raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ========== 缓存中间件 ==========

class CacheStrategy(str, Enum):
    """缓存策略"""
    CACHE_FIRST = "cache_first"  # 先查缓存
    CACHE_ONLY = "cache_only"    # 只查缓存
    NETWORK_FIRST = "network_first"  # 先请求网络
    STALE_WHILE_REVALIDATE = "stale_while-revalidate"  # 返回旧数据同时更新


@dataclass
class CacheEntry:
    """缓存条目"""
    key: str
    value: Any
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    ttl: Optional[int] = None  # 秒
    tags: List[str] = field(default_factory=list)
    hit_count: int = 0

    @property
    def is_expired(self) -> bool:
        """检查是否过期"""
        if self.expires_at:
            return time.time() > self.expires_at
        if self.ttl:
            return time.time() > self.created_at + self.ttl
        return False

    def touch(self) -> None:
        """更新访问时间"""
        self.hit_count += 1


class CacheMiddleware:
    """
    缓存中间件
    提供内存缓存和语义缓存能力
    """

    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: Dict[str, CacheEntry] = {}
        self._access_order: List[str] = []  # LRU 顺序
        self._stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "evictions": 0,
        }

    def _make_key(self, *args, **kwargs) -> str:
        """生成缓存键"""
        data = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
        return hashlib.md5(data.encode()).hexdigest()

    def _make_semantic_key(self, query: str) -> str:
        """生成语义缓存键"""
        normalized = query.strip().lower()
        return f"semantic:{hashlib.sha256(normalized.encode()).hexdigest()[:16]}"

    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        if key in self._cache:
            entry = self._cache[key]
            if not entry.is_expired:
                entry.touch()
                self._update_access_order(key)
                self._stats["hits"] += 1
                return entry.value
            else:
                del self._cache[key]
                self._access_order.remove(key)

        self._stats["misses"] += 1
        return None

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        tags: Optional[List[str]] = None,
    ) -> None:
        """设置缓存"""
        # LRU 淘汰
        if len(self._cache) >= self.max_size and key not in self._cache:
            oldest = self._access_order.pop(0)
            del self._cache[oldest]
            self._stats["evictions"] += 1

        ttl = ttl or self.default_ttl
        entry = CacheEntry(
            key=key,
            value=value,
            ttl=ttl,
            tags=tags or [],
        )

        self._cache[key] = entry
        self._update_access_order(key)
        self._stats["sets"] += 1

    def delete(self, key: str) -> bool:
        """删除缓存"""
        if key in self._cache:
            del self._cache[key]
            self._access_order.remove(key)
            return True
        return False

    def invalidate_by_tags(self, tags: List[str]) -> int:
        """根据标签清除缓存"""
        count = 0
        to_delete = []

        for key, entry in self._cache.items():
            if any(tag in entry.tags for tag in tags):
                to_delete.append(key)

        for key in to_delete:
            del self._cache[key]
            self._access_order.remove(key)
            count += 1

        return count

    def clear(self) -> None:
        """清空缓存"""
        self._cache.clear()
        self._access_order.clear()

    def _update_access_order(self, key: str) -> None:
        """更新访问顺序"""
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        total = self._stats["hits"] + self._stats["misses"]
        return {
            **self._stats,
            "size": len(self._cache),
            "hit_rate": self._stats["hits"] / total if total > 0 else 0,
        }


# 全局缓存中间件
_cache: Optional[CacheMiddleware] = None


def get_cache() -> CacheMiddleware:
    """获取缓存中间件"""
    global _cache
    if _cache is None:
        _cache = CacheMiddleware()
    return _cache


def cached(
    ttl: int = 300,
    key_func: Optional[Callable[..., str]] = None,
):
    """
    缓存装饰器

    Usage:
        @cached(ttl=60)
        async def my_function(param: str):
            ...

        @cached(key_func=lambda param: f"custom_key_{param}")
        async def my_function(param: str):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            cache = get_cache()

            # 生成 key
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = cache._make_key(*args, **kwargs)

            # 尝试获取缓存
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                return cached_value

            # 执行函数
            result = await func(*args, **kwargs)

            # 缓存结果
            cache.set(cache_key, result, ttl=ttl)

            return result

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            cache = get_cache()

            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = cache._make_key(*args, **kwargs)

            cached_value = cache.get(cache_key)
            if cached_value is not None:
                return cached_value

            result = func(*args, **kwargs)
            cache.set(cache_key, result, ttl=ttl)

            return result

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ========== Rate Limiter 中间件 ==========

class RateLimiter:
    """
    限流器
    基于令牌桶算法
    """

    def __init__(self, rate: int, per_seconds: int = 60):
        self.rate = rate
        self.per_seconds = per_seconds
        self._buckets: Dict[str, Dict[str, Any]] = {}

    def _get_bucket(self, key: str) -> Dict[str, Any]:
        """获取或创建桶"""
        if key not in self._buckets:
            self._buckets[key] = {
                "tokens": self.rate,
                "last_update": time.time(),
            }
        return self._buckets[key]

    def allow(self, key: str, tokens: int = 1) -> bool:
        """
        检查是否允许请求

        Args:
            key: 限流键（如用户ID、IP等）
            tokens: 消耗的令牌数

        Returns:
            是否允许
        """
        bucket = self._get_bucket(key)
        now = time.time()

        # 补充令牌
        elapsed = now - bucket["last_update"]
        bucket["tokens"] = min(
            self.rate,
            bucket["tokens"] + elapsed * (self.rate / self.per_seconds)
        )
        bucket["last_update"] = now

        # 检查是否足够
        if bucket["tokens"] >= tokens:
            bucket["tokens"] -= tokens
            return True

        return False

    def get_remaining(self, key: str) -> int:
        """获取剩余令牌数"""
        bucket = self._get_bucket(key)
        return int(bucket["tokens"])

    def reset(self, key: str) -> None:
        """重置桶"""
        if key in self._buckets:
            del self._buckets[key]


# 全局限流器
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """获取限流器"""
    global _rate_limiter
    if _rate_limiter is None:
        from app.core.config import settings
        rate_limiter = get_rate_limiter()
        _rate_limiter = RateLimiter(
            rate=settings.rate_limit.per_minute,
            per_seconds=60,
        )
    return _rate_limiter


# ========== Middleware 组合器 ==========

class MiddlewareChain:
    """
    中间件链
    将多个中间件组合成一个处理链
    """

    def __init__(self):
        self._middlewares: List[Callable] = []

    def use(self, middleware: Callable) -> "MiddlewareChain":
        """添加中间件"""
        self._middlewares.append(middleware)
        return self

    async def handle(self, context: RequestContext, handler: Callable) -> Any:
        """处理请求"""
        async def wrapper(index: int = 0):
            if index >= len(self._middlewares):
                return await handler(context)

            middleware = self._middlewares[index]

            async def next_handler():
                return await wrapper(index + 1)

            return await middleware(context, next_handler)

        return await wrapper()


# ========== 日志中间件增强 ==========

class LogMiddleware:
    """
    日志中间件
    增强请求日志记录
    """

    def __init__(self, logger_name: str = "app.middleware"):
        self.logger = get_logger(logger_name)

    async def __call__(self, context: RequestContext, next_handler: Callable) -> Any:
        """处理请求"""
        start_time = time.time()

        self.logger.info(
            f"Request started",
            extra={
                "request_id": context.request_id,
                "trace_id": context.trace_id,
            }
        )

        try:
            result = await next_handler()
            elapsed_ms = (time.time() - start_time) * 1000

            self.logger.info(
                f"Request completed",
                extra={
                    "request_id": context.request_id,
                    "elapsed_ms": elapsed_ms,
                }
            )

            return result

        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000

            self.logger.error(
                f"Request failed: {e}",
                extra={
                    "request_id": context.request_id,
                    "elapsed_ms": elapsed_ms,
                },
                exc_info=True,
            )
            raise
