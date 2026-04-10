"""
Dependency Injection Container
依赖注入容器
提供全局依赖管理和生命周期控制
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, AsyncGenerator, Callable, Dict, Optional, Type, TypeVar

from app.core.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


@dataclass
class Dependency:
    """依赖项定义"""
    name: str
    factory: Callable[..., Any]
    singleton: bool = True
    instance: Any = None
    dependencies: list[str] = field(default_factory=list)


class Container:
    """
    依赖注入容器
    支持：
    - 单例模式
    - 工厂模式
    - 异步初始化
    - 依赖自动注入
    - 生命周期管理
    """

    def __init__(self):
        self._dependencies: Dict[str, Dependency] = {}
        self._lock = asyncio.Lock()
        self._initialized = False

    def register(
        self,
        name: str,
        factory: Callable[..., Any],
        *,
        singleton: bool = True,
        dependencies: Optional[list[str]] = None,
    ) -> None:
        """
        注册依赖

        Args:
            name: 依赖名称
            factory: 工厂函数或类
            singleton: 是否单例
            dependencies: 依赖的其他服务
        """
        if name in self._dependencies:
            logger.warning(f"Dependency '{name}' already registered, overwriting")

        self._dependencies[name] = Dependency(
            name=name,
            factory=factory,
            singleton=singleton,
            dependencies=dependencies or [],
        )
        logger.debug(f"Registered dependency: {name}")

    def register_instance(self, name: str, instance: Any) -> None:
        """
        注册已存在的实例

        Args:
            name: 依赖名称
            instance: 实例
        """
        self._dependencies[name] = Dependency(
            name=name,
            factory=lambda: instance,
            singleton=True,
            instance=instance,
        )
        logger.debug(f"Registered instance: {name}")

    def register_class(
        self,
        name: str,
        cls: Type[T],
        *,
        singleton: bool = True,
        dependencies: Optional[list[str]] = None,
    ) -> None:
        """
        注册类

        Args:
            name: 依赖名称
            cls: 类
            singleton: 是否单例
            dependencies: 构造参数依赖
        """
        def factory(**kwargs):
            return cls(**kwargs)

        self.register(
            name=name,
            factory=factory,
            singleton=singleton,
            dependencies=dependencies,
        )

    async def get(self, name: str) -> Any:
        """
        获取依赖实例

        Args:
            name: 依赖名称

        Returns:
            实例
        """
        if name not in self._dependencies:
            raise KeyError(f"Dependency not found: {name}")

        dep = self._dependencies[name]

        # 单例且已有实例
        if dep.singleton and dep.instance is not None:
            return dep.instance

        # 解析依赖
        kwargs = {}
        for dep_name in dep.dependencies:
            kwargs[dep_name] = await self.get(dep_name)

        # 创建实例
        instance = dep.factory(**kwargs)

        # 异步初始化
        if asyncio.iscoroutinefunction(getattr(instance, "initialize", None)):
            instance = await instance.initialize()

        # 保存单例
        if dep.singleton:
            dep.instance = instance

        return instance

    def get_sync(self, name: str) -> Any:
        """
        同步获取依赖（用于非异步上下文）

        Args:
            name: 依赖名称
        """
        if name not in self._dependencies:
            raise KeyError(f"Dependency not found: {name}")

        dep = self._dependencies[name]

        if dep.singleton and dep.instance is not None:
            return dep.instance

        raise RuntimeError(
            f"Cannot get '{name}' synchronously: requires async initialization or not a singleton"
        )

    def has(self, name: str) -> bool:
        """检查依赖是否存在"""
        return name in self._dependencies

    async def clear(self, name: str) -> None:
        """
        清除单例实例

        Args:
            name: 依赖名称
        """
        if name in self._dependencies:
            dep = self._dependencies[name]
            if dep.instance is not None:
                if asyncio.iscoroutinefunction(getattr(dep.instance, "shutdown", None)):
                    await dep.instance.shutdown()
                dep.instance = None
                logger.debug(f"Cleared singleton instance: {name}")

    async def clear_all(self) -> None:
        """清除所有单例实例"""
        for name in list(self._dependencies.keys()):
            await self.clear(name)

    async def initialize(self) -> None:
        """初始化所有单例依赖"""
        async with self._lock:
            if self._initialized:
                return

            logger.info("Initializing container dependencies...")

            for name, dep in self._dependencies.items():
                if dep.singleton and dep.instance is None:
                    try:
                        await self.get(name)
                        logger.debug(f"Initialized dependency: {name}")
                    except Exception as e:
                        logger.warning(f"Failed to pre-initialize '{name}': {e}")

            self._initialized = True
            logger.info("Container dependencies initialized")

    async def shutdown(self) -> None:
        """关闭并清理所有依赖"""
        logger.info("Shutting down container...")

        for name in list(self._dependencies.keys()):
            await self.clear(name)

        self._initialized = False
        logger.info("Container shut down")

    def list_dependencies(self) -> list[str]:
        """列出所有已注册的依赖"""
        return list(self._dependencies.keys())


# ========== 全局容器实例 ==========

_container: Optional[Container] = None


def get_container() -> Container:
    """获取全局容器"""
    global _container
    if _container is None:
        _container = Container()
    return _container


async def init_container() -> Container:
    """初始化全局容器"""
    container = get_container()
    await container.initialize()
    return container


async def shutdown_container() -> None:
    """关闭全局容器"""
    global _container
    if _container:
        await _container.shutdown()
        _container = None


# ========== 依赖注入装饰器 ==========

def injectable(name: Optional[str] = None):
    """
    依赖注入装饰器
    将类或函数标记为可注入的依赖

    Usage:
        @injectable("llm_manager")
        class LLMManager:
            ...

        # 或自动使用类名
        @injectable()
        class MyService:
            ...
    """
    def decorator(cls_or_fn):
        dep_name = name or cls_or_fn.__name__
        container = get_container()
        container.register(dep_name, cls_or_fn)
        return cls_or_fn
    return decorator


# ========== 请求作用域依赖 ==========

_request_containers: Dict[str, Container] = {}


async def get_request_container(request_id: str) -> Container:
    """
    获取请求作用域的容器

    Args:
        request_id: 请求ID
    """
    if request_id not in _request_containers:
        _request_containers[request_id] = Container()
    return _request_containers[request_id]


async def cleanup_request_container(request_id: str) -> None:
    """
    清理请求作用域的容器

    Args:
        request_id: 请求ID
    """
    if request_id in _request_containers:
        await _request_containers[request_id].shutdown()
        del _request_containers[request_id]


@asynccontextmanager
async def request_scope(request_id: str) -> AsyncGenerator[Container, None]:
    """
    请求作用域上下文管理器

    Usage:
        async with request_scope(request_id) as container:
            service = await container.get("service")
            ...
    """
    container = await get_request_container(request_id)
    try:
        yield container
    finally:
        await cleanup_request_container(request_id)


# ========== 生命周期管理器 ==========

class LifecycleManager:
    """
    生命周期管理器
    管理应用启动和关闭顺序
    """

    def __init__(self, container: Optional[Container] = None):
        self.container = container or get_container()
        self._startup_tasks: list[Callable] = []
        self._shutdown_tasks: list[Callable] = []
        self._started = False

    def on_startup(self, task: Callable) -> None:
        """注册启动任务"""
        self._startup_tasks.append(task)

    def on_shutdown(self, task: Callable) -> None:
        """注册关闭任务"""
        self._shutdown_tasks.append(task)

    async def startup(self) -> None:
        """执行启动任务"""
        if self._started:
            return

        logger.info("Running startup tasks...")

        for task in self._startup_tasks:
            try:
                if asyncio.iscoroutinefunction(task):
                    await task()
                else:
                    task()
                logger.debug(f"Completed startup task: {task.__name__}")
            except Exception as e:
                logger.error(f"Startup task failed: {task.__name__}: {e}")
                raise

        self._started = True
        logger.info("Startup tasks completed")

    async def shutdown(self) -> None:
        """执行关闭任务"""
        logger.info("Running shutdown tasks...")

        for task in reversed(self._shutdown_tasks):
            try:
                if asyncio.iscoroutinefunction(task):
                    await task()
                else:
                    task()
                logger.debug(f"Completed shutdown task: {task.__name__}")
            except Exception as e:
                logger.error(f"Shutdown task failed: {task.__name__}: {e}")

        await self.container.shutdown()
        logger.info("Shutdown tasks completed")


# ========== FastAPI 集成 ==========

from functools import wraps
from typing import ParamSpec

P = ParamSpec("P")


def inject(**deps: str):
    """
    函数参数注入装饰器

    Usage:
        @inject(llm="llm_manager", store="session_store")
        async def my_function(llm, store, message: str):
            ...
    """
    def decorator(func: Callable[P, Any]) -> Callable[P, Any]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            container = get_container()

            # 注入依赖
            for param_name, dep_name in deps.items():
                if param_name not in kwargs:
                    kwargs[param_name] = await container.get(dep_name)

            return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            container = get_container()

            for param_name, dep_name in deps.items():
                if param_name not in kwargs:
                    kwargs[param_name] = container.get_sync(dep_name)

            return func(*args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return wrapper
        return sync_wrapper

    return decorator
