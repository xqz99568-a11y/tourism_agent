"""
结构化日志模块
支持 JSON 格式和文本格式，支持多端输出
"""
from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import json


class LogLevel(str, Enum):
    """日志级别"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LoggerMixin:
    """
    日志混入类
    为任何类添加日志能力
    """

    @property
    def logger(self) -> logging.Logger:
        name = f"{self.__class__.__module__}.{self.__class__.__name__}"
        return logging.getLogger(name)


# Context Variables for request tracking
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
user_id_var: ContextVar[Optional[str]] = ContextVar("user_id", default=None)
session_id_var: ContextVar[Optional[str]] = ContextVar("session_id", default=None)


class StructuredFormatter(logging.Formatter):
    """
    结构化日志格式化器
    输出 JSON 格式的日志，便于日志收集和分析
    """

    def __init__(self):
        super().__init__()

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 添加 trace 信息
        if request_id := request_id_var.get():
            log_data["request_id"] = request_id
        if user_id := user_id_var.get():
            log_data["user_id"] = user_id
        if session_id := session_id_var.get():
            log_data["session_id"] = session_id

        # 添加异常信息
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # 添加额外字段
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)

        return json.dumps(log_data, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """
    文本日志格式化器
    人类可读的日志格式
    """

    def __init__(self):
        super().__init__(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


def setup_logging() -> None:
    """
    配置全局日志系统
    """
    from app.core.config import settings

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.log_level))

    # 清除现有 handlers
    root_logger.handlers.clear()

    # 控制台 Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(
        TextFormatter() if settings.log_format == "text" else StructuredFormatter()
    )
    root_logger.addHandler(console_handler)

    # 文件 Handler
    if settings.log_file:
        settings.log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(
            settings.log_file,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(StructuredFormatter())
        root_logger.addHandler(file_handler)

    # 设置第三方库日志级别
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("fastapi").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


class AppLogger:
    """
    应用日志记录器
    提供统一的日志接口
    """

    def __init__(self, name: str):
        self._logger = logging.getLogger(name)

    def _log(
        self,
        level: int,
        message: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        exc_info = kwargs.pop("exc_info", None)
        if args:
            try:
                message = message % args
            except Exception:
                rendered_args = " ".join(str(arg) for arg in args)
                message = f"{message} {rendered_args}".strip()
        extra = {"extra_fields": kwargs} if kwargs else None
        self._logger.log(level, message, extra=extra, exc_info=exc_info)

    def debug(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.DEBUG, message, *args, **kwargs)

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.INFO, message, *args, **kwargs)

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.WARNING, message, *args, **kwargs)

    def error(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.ERROR, message, *args, **kwargs)

    def critical(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.CRITICAL, message, *args, **kwargs)

    def exception(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.ERROR, message, *args, exc_info=True, **kwargs)


def get_logger(name: str) -> AppLogger:
    """获取应用日志记录器"""
    return AppLogger(name)


# 预配置的日志记录器
agent_logger = get_logger("app.agents")
tool_logger = get_logger("app.tools")
api_logger = get_logger("app.api")
llm_logger = get_logger("app.llm")
