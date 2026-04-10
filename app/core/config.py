"""
配置管理模块
使用 Pydantic Settings 进行类型安全的配置管理
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    """LLM 配置 (简化版)"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="LLM_",
    )

    # OpenRouter
    api_key: str = Field(default="", description="OpenRouter API Key")
    base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        description="API Base URL"
    )
    model: str = Field(
        default="Qwen/Qwen2.5-7B-Instruct",
        description="模型名称 (推荐: Qwen/Qwen2.5-7B-Instruct)"
    )
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    timeout: int = Field(default=60, ge=1)
    max_tokens: int = Field(default=4096, ge=100)

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


class AMapSettings(BaseSettings):
    """高德地图配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="AMAP_",
    )

    api_key: str = Field(default="", description="高德地图 API Key")
    security_code: str = Field(default="", description="高德地图安全码")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


class DatabaseSettings(BaseSettings):
    """数据库配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="DATABASE_",
    )

    # PostgreSQL
    url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/tourism_agent"
    )
    sync_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/tourism_agent"
    )

    # Redis
    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_db: int = Field(default=0, ge=0)
    redis_password: str = Field(default="")

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


class VectorDBSettings(BaseSettings):
    """向量数据库配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="VECTOR_DB_",
    )

    provider: Literal["qdrant", "milvus", "chroma"] = Field(default="qdrant")
    host: str = Field(default="localhost")
    port: int = Field(default=6333, ge=1, le=65535)
    api_key: str = Field(default="")
    collection_name: str = Field(default="poi_embeddings")
    dimension: int = Field(default=1536)


class ServerSettings(BaseSettings):
    """服务器配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="SERVER_",
    )

    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000, ge=1, le=65535)
    debug: bool = Field(default=False)
    workers: int = Field(default=1, ge=1)
    reload: bool = Field(default=False)


class FeatureFlags(BaseSettings):
    """功能开关"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    enable_streaming: bool = Field(default=True)
    enable_caching: bool = Field(default=True)
    enable_metrics: bool = Field(default=True)
    enable_tracing: bool = Field(default=False)


class RateLimitSettings(BaseSettings):
    """限流配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="RATE_LIMIT_",
    )

    per_minute: int = Field(default=60)
    per_hour: int = Field(default=1000)


class Settings(BaseSettings):
    """
    应用全局配置
    所有配置通过环境变量或 .env 文件加载
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 版本信息
    version: str = Field(default="2.0.0")
    app_name: str = Field(default="Tourism Agent")

    # 子配置
    llm: LLMSettings = Field(default_factory=LLMSettings)
    amap: AMapSettings = Field(default_factory=AMapSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    vector_db: VectorDBSettings = Field(default_factory=VectorDBSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)

    # 日志
    log_level: Literal[
        "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
    ] = Field(default="INFO")
    log_format: Literal["text", "json"] = Field(default="json")
    log_file: Path = Field(default=Path("logs/app.log"))

    # 前端
    frontend_url: str = Field(default="http://127.0.0.1:3000")

    # Session
    max_session_history: int = Field(default=50)

    @field_validator("log_file", mode="before")
    @classmethod
    def ensure_log_dir(cls, v: Path | str) -> Path:
        path = Path(v) if isinstance(v, str) else v
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def is_production(self) -> bool:
        return not self.server.debug


@lru_cache
def get_settings() -> Settings:
    """
    获取全局配置单例
    使用 lru_cache 确保只加载一次
    """
    return Settings()


# 全局配置实例
settings = get_settings()
