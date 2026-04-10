"""
API Gateway - API 网关
提供统一的 API 入口，处理限流、鉴权、路由、监控
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import StreamingResponse

from app.core.logger import get_logger
from app.core.middleware import (
    RequestContext,
    RateLimiter,
    get_request_id,
    get_trace_id,
    set_request_context,
)
from app.core.config import settings

if TYPE_CHECKING:
    from app.core.llm.client import LLMManager

logger = get_logger(__name__)


class AuthType(str, Enum):
    """认证类型"""
    NONE = "none"
    API_KEY = "api_key"
    JWT = "jwt"
    OAUTH2 = "oauth2"


@dataclass
class APIRoute:
    """API 路由定义"""
    path: str
    method: str
    handler: Callable
    auth_type: AuthType = AuthType.NONE
    rate_limit: Optional[int] = None
    timeout: Optional[float] = None
    tags: List[str] = field(default_factory=list)
    description: str = ""


@dataclass
class APIRequest:
    """API 请求"""
    request_id: str
    trace_id: str
    path: str
    method: str
    headers: Dict[str, str]
    query_params: Dict[str, str]
    body: Optional[Dict[str, Any]] = None
    user_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class APIResponse:
    """API 响应"""
    request_id: str
    status_code: int
    data: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class APIGatewayMetrics:
    """API 网关指标"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency_ms: float = 0.0
    rate_limited_requests: int = 0
    auth_failed_requests: int = 0


class AuthMiddleware:
    """认证中间件"""

    def __init__(self):
        self._valid_api_keys: Dict[str, Dict[str, Any]] = {}

    def add_api_key(self, key: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """添加 API Key"""
        self._valid_api_keys[key] = metadata or {}

    def validate_api_key(self, key: str) -> bool:
        """验证 API Key"""
        return key in self._valid_api_keys

    def get_api_key_metadata(self, key: str) -> Optional[Dict[str, Any]]:
        """获取 API Key 元数据"""
        return self._valid_api_keys.get(key)

    async def authenticate(
        self,
        request: APIRequest,
        auth_type: AuthType,
    ) -> tuple[bool, Optional[str]]:
        """
        认证请求

        Returns:
            (是否通过, 错误信息)
        """
        if auth_type == AuthType.NONE:
            return True, None

        if auth_type == AuthType.API_KEY:
            api_key = request.headers.get("X-API-Key") or request.headers.get("Authorization", "").replace("Bearer ", "")
            if not api_key:
                return False, "Missing API key"

            if not self.validate_api_key(api_key):
                return False, "Invalid API key"

            request.user_id = self.get_api_key_metadata(api_key).get("user_id")

        elif auth_type == AuthType.JWT:
            token = request.headers.get("Authorization", "").replace("Bearer ", "")
            if not token:
                return False, "Missing token"

            # TODO: 实现 JWT 验证
            # 这里简化处理
            try:
                # 实际应该使用 PyJWT 验证
                pass
            except Exception as e:
                return False, f"Invalid token: {e}"

        return True, None


class RateLimitMiddleware:
    """限流中间件"""

    def __init__(
        self,
        default_rate: int = 60,
        default_per_seconds: int = 60,
    ):
        self.default_rate = default_rate
        self.default_per_seconds = default_per_seconds
        self._limiters: Dict[str, RateLimiter] = {}

    def get_limiter(self, key: str) -> RateLimiter:
        """获取限流器"""
        if key not in self._limiters:
            self._limiters[key] = RateLimiter(
                rate=self.default_rate,
                per_seconds=self.default_per_seconds,
            )
        return self._limiters[key]

    async def check_rate_limit(
        self,
        request: APIRequest,
        rate_limit: Optional[int] = None,
    ) -> tuple[bool, Optional[Dict[str, Any]]]:
        """
        检查限流

        Returns:
            (是否允许, 限流信息)
        """
        rate = rate_limit or self.default_rate

        # 使用用户 ID 或 IP 作为限流键
        key = request.user_id or request.headers.get("X-Forwarded-For", "unknown")

        limiter = self.get_limiter(key)
        allowed = limiter.allow(key)

        if not allowed:
            remaining = limiter.get_remaining(key)
            return False, {
                "retry_after": 60,
                "limit": rate,
                "remaining": remaining,
            }

        return True, None

    def reset_limiter(self, key: str) -> None:
        """重置限流器"""
        if key in self._limiters:
            self._limiters[key].reset(key)


class MonitoringMiddleware:
    """监控中间件"""

    def __init__(self):
        self._metrics = APIGatewayMetrics()
        self._request_logs: List[Dict[str, Any]] = []
        self._max_log_size = 1000

    def record_request(
        self,
        request: APIRequest,
        response: APIResponse,
    ) -> None:
        """记录请求"""
        self._metrics.total_requests += 1

        if response.status_code < 400:
            self._metrics.successful_requests += 1
        else:
            self._metrics.failed_requests += 1

        self._metrics.total_latency_ms += response.execution_time_ms

        # 记录日志
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "request_id": request.request_id,
            "trace_id": request.trace_id,
            "path": request.path,
            "method": request.method,
            "status_code": response.status_code,
            "latency_ms": response.execution_time_ms,
            "user_id": request.user_id,
        }

        self._request_logs.append(log_entry)

        # 限制日志大小
        if len(self._request_logs) > self._max_log_size:
            self._request_logs = self._request_logs[-self._max_log_size:]

    def record_rate_limited(self) -> None:
        """记录被限流的请求"""
        self._metrics.rate_limited_requests += 1

    def record_auth_failed(self) -> None:
        """记录认证失败"""
        self._metrics.auth_failed_requests += 1

    def get_metrics(self) -> Dict[str, Any]:
        """获取指标"""
        avg_latency = (
            self._metrics.total_latency_ms / self._metrics.total_requests
            if self._metrics.total_requests > 0 else 0
        )

        return {
            "total_requests": self._metrics.total_requests,
            "successful_requests": self._metrics.successful_requests,
            "failed_requests": self._metrics.failed_requests,
            "success_rate": (
                self._metrics.successful_requests / self._metrics.total_requests
                if self._metrics.total_requests > 0 else 0
            ),
            "average_latency_ms": avg_latency,
            "rate_limited_requests": self._metrics.rate_limited_requests,
            "auth_failed_requests": self._metrics.auth_failed_requests,
        }

    def get_recent_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取最近的日志"""
        return self._request_logs[-limit:]


class APIGateway:
    """
    API 网关
    统一的 API 入口
    """

    def __init__(self):
        self.auth = AuthMiddleware()
        self.rate_limiter = RateLimitMiddleware(
            default_rate=settings.rate_limit.per_minute,
            default_per_seconds=60,
        )
        self.monitoring = MonitoringMiddleware()
        self._routes: Dict[str, APIRoute] = {}

    def add_route(self, route: APIRoute) -> None:
        """添加路由"""
        key = f"{route.method}:{route.path}"
        self._routes[key] = route

    def get_route(self, method: str, path: str) -> Optional[APIRoute]:
        """获取路由"""
        key = f"{method}:{path}"
        return self._routes.get(key)

    async def handle_request(
        self,
        request: Request,
        handler: Callable,
    ) -> Response:
        """处理请求"""
        start_time = time.time()

        # 创建请求上下文
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))
        set_request_context(request_id, trace_id)

        # 构建 API 请求
        api_request = APIRequest(
            request_id=request_id,
            trace_id=trace_id,
            path=str(request.url.path),
            method=request.method,
            headers=dict(request.headers),
            query_params=dict(request.query_params),
            metadata={
                "client_ip": request.client.host if request.client else "unknown",
                "user_agent": request.headers.get("User-Agent", ""),
            },
        )

        # 获取路由配置
        route = self.get_route(request.method, str(request.url.path))

        # 认证检查
        if route and route.auth_type != AuthType.NONE:
            auth_ok, auth_error = await self.auth.authenticate(api_request, route.auth_type)
            if not auth_ok:
                self.monitoring.record_auth_failed()
                return Response(
                    content=json.dumps({"error": auth_error}),
                    status_code=401,
                    media_type="application/json",
                    headers={
                        "X-Request-ID": request_id,
                        "X-Trace-ID": trace_id,
                    },
                )

        # 限流检查
        if route and route.rate_limit:
            allowed, limit_info = await self.rate_limiter.check_rate_limit(
                api_request,
                route.rate_limit,
            )
            if not allowed:
                self.monitoring.record_rate_limited()
                return Response(
                    content=json.dumps({
                        "error": "Rate limit exceeded",
                        **limit_info,
                    }),
                    status_code=429,
                    media_type="application/json",
                    headers={
                        "X-Request-ID": request_id,
                        "X-Trace-ID": trace_id,
                        "Retry-After": str(limit_info["retry_after"]),
                    },
                )

        # 执行请求
        try:
            response_content = await handler(request)
            status_code = 200
            error = None
        except Exception as e:
            logger.exception(f"Request failed: {e}")
            response_content = {"error": str(e)}
            status_code = 500
            error = str(e)

        # 计算执行时间
        execution_time_ms = (time.time() - start_time) * 1000

        # 构建响应
        api_response = APIResponse(
            request_id=request_id,
            status_code=status_code,
            data=response_content,
            error=error,
            execution_time_ms=execution_time_ms,
        )

        # 记录监控
        self.monitoring.record_request(api_request, api_response)

        # 返回响应
        return Response(
            content=json.dumps(response_content, default=str),
            status_code=status_code,
            media_type="application/json",
            headers={
                "X-Request-ID": request_id,
                "X-Trace-ID": trace_id,
                "X-Execution-Time-Ms": str(int(execution_time_ms)),
            },
        )

    def create_route_handler(
        self,
        path: str,
        method: str,
        auth_type: AuthType = AuthType.NONE,
        rate_limit: Optional[int] = None,
    ) -> Callable:
        """创建路由处理器装饰器"""
        def decorator(func: Callable) -> Callable:
            route = APIRoute(
                path=path,
                method=method,
                handler=func,
                auth_type=auth_type,
                rate_limit=rate_limit,
            )
            self.add_route(route)
            return func
        return decorator


# ========== 全局网关实例 ==========

_gateway: Optional[APIGateway] = None


def get_gateway() -> APIGateway:
    """获取 API 网关"""
    global _gateway
    if _gateway is None:
        _gateway = APIGateway()
    return _gateway


def init_gateway() -> APIGateway:
    """初始化 API 网关"""
    gateway = get_gateway()

    # 添加默认 API Key（示例）
    gateway.auth.add_api_key("demo-key", {"user_id": "demo_user", "plan": "free"})

    logger.info("API Gateway initialized")
    return gateway


# ========== FastAPI 集成 ==========

def create_api_gateway_middleware(gateway: APIGateway):
    """创建 FastAPI 中间件"""

    async def middleware(request: Request, call_next):
        async def handler(req: Request):
            body = None
            if request.method in ["POST", "PUT", "PATCH"]:
                try:
                    body = await request.json()
                except Exception:
                    body = None

            # 这里简化处理，实际应该调用具体的路由处理器
            return await call_next(request)

        return await gateway.handle_request(request, handler)

    return middleware
