"""
Tools 模块
提供各种工具能力
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from app.core.logger import get_logger

if TYPE_CHECKING:
    from app.core.context import ExecutionContext

logger = get_logger(__name__)


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = None
    # API 调用信息
    api_calls: List[Dict[str, Any]] = field(default_factory=list)  # 记录外部API调用

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class BaseTool(ABC):
    """
    工具基类
    所有工具都需要继承此类
    支持自动记录外部 API 调用
    """

    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}

    # 子类可设置此属性以标识外部服务
    external_service: str = ""

    def __init__(self):
        self._context: Optional["ExecutionContext"] = None

    def set_context(self, context: "ExecutionContext") -> None:
        """设置执行上下文（用于记录 API 调用）"""
        self._context = context

    def clear_context(self) -> None:
        """清除执行上下文"""
        self._context = None

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """执行工具"""
        pass

    def validate_params(self, params: Dict[str, Any]) -> bool:
        """验证参数"""
        for key in self.parameters.get("required", []):
            if key not in params:
                logger.error(f"Missing required parameter: {key}")
                return False
        return True

    def record_api_call(
        self,
        endpoint: str,
        params: Dict[str, Any],
        status: str = "completed",
        response: Dict[str, Any] = None,
        http_status: int = 200,
        error: str = None,
        cost_ms: float = None,
    ) -> None:
        """记录外部 API 调用"""
        if self._context is None:
            return

        service = self.external_service or self.name
        self._context.add_api_call_to_latest(
            agent_name=self._context.current_phase or "系统",
            service=service,
            endpoint=endpoint,
            params=params,
            status=status,
            response=response,
            http_status=http_status,
            error=error,
            cost_ms=cost_ms,
        )


class ToolRegistry:
    """
    工具注册中心
    管理所有可用工具
    """

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """注册工具"""
        self._tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")

    def get(self, name: str) -> Optional[BaseTool]:
        """获取工具"""
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        """列出所有工具"""
        return list(self._tools.keys())

    def exists(self, name: str) -> bool:
        """检查工具是否存在"""
        return name in self._tools


# 全局工具注册中心
_tool_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """获取工具注册中心"""
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
    return _tool_registry
