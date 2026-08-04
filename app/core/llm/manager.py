"""
LLM 管理器 (简化版)
只支持单模型 OpenRouter，自动降级到 Mock 客户端
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logger import get_logger
from app.core.tracing import (
    finish_llm_call,
    is_experiment_cache_disabled,
    is_experiment_strict_mode,
    mark_llm_first_token,
    start_llm_call,
)

from .client import (
    LLMMessage,
    LLMResponse,
    ToolDefinition,
    BaseLLMClient,
    OpenRouterClient,
    MockLLMClient,
    _retry_audit,
    _retry_result_from_policy,
    _runtime_llm_max_tokens,
    _runtime_llm_reasoning_effort,
    _runtime_llm_retry_max_attempts_for_client,
    _runtime_llm_temperature,
    _runtime_llm_timeout_for_client,
    _runtime_options,
)

logger = get_logger(__name__)


@dataclass
class LLMCallMetrics:
    """LLM 调用指标"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    cached_calls: int = 0
    total_latency_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.successful_calls / self.total_calls

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "cached_calls": self.cached_calls,
            "success_rate": f"{self.success_rate:.2%}",
            "total_latency_ms": f"{self.total_latency_ms:.2f}ms",
        }


class SimpleLLMCache:
    """
    简单的 LLM 响应缓存
    基于消息哈希的精确匹配
    """

    def __init__(self, ttl_seconds: int = 300):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._ttl = ttl_seconds

    def _make_key(self, messages: List[LLMMessage]) -> str:
        """生成缓存键"""
        content = "".join(m.content for m in messages)
        return hashlib.md5(content.encode()).hexdigest()

    def get(self, messages: List[LLMMessage]) -> Optional[LLMResponse]:
        """获取缓存的响应"""
        key = self._make_key(messages)
        entry = self._cache.get(key)

        if entry:
            if time.time() - entry["timestamp"] < self._ttl:
                return entry["response"]
            else:
                del self._cache[key]
        return None

    def set(self, messages: List[LLMMessage], response: LLMResponse) -> None:
        """缓存响应"""
        key = self._make_key(messages)
        self._cache[key] = {
            "response": response,
            "timestamp": time.time(),
        }

    def clear(self) -> None:
        """清空缓存"""
        self._cache.clear()


class EnhancedLLMManager:
    """
    简化的 LLM 管理器
    使用单一 OpenRouter 模型，失败时降级到 Mock 客户端
    """

    def __init__(
        self,
        enable_caching: bool = True,  # 默认启用缓存
    ):
        self._client: Optional[BaseLLMClient] = None
        self._mock_client = MockLLMClient()
        self._using_mock = False
        self.metrics = LLMCallMetrics()
        self._cache = SimpleLLMCache(ttl_seconds=300) if enable_caching else None
        self._initialize_client()

    def _initialize_client(self) -> None:
        """初始化客户端"""
        strict_mode = is_experiment_strict_mode()
        llm_configured = bool(os.getenv("LLM_API_KEY") or settings.llm.is_configured)
        if llm_configured:
            try:
                self._client = OpenRouterClient(
                    api_key=os.getenv("LLM_API_KEY") or settings.llm.api_key,
                    base_url=os.getenv("LLM_BASE_URL") or settings.llm.base_url,
                    model=os.getenv("LLM_MODEL") or settings.llm.model,
                )
                self._using_mock = False
                logger.info(f"LLM 客户端已初始化: {settings.llm.model}")
            except Exception as e:
                if strict_mode:
                    raise RuntimeError("EXPERIMENT_STRICT_MODE forbids Mock LLM fallback") from e
                logger.warning(f"初始化 OpenRouter 失败: {e}, 使用 Mock 客户端")
                self._client = self._mock_client
                self._using_mock = True
        else:
            if strict_mode:
                raise RuntimeError("EXPERIMENT_STRICT_MODE forbids implicit Mock LLM client")
            logger.warning("未配置 LLM API Key, 使用 Mock 客户端")
            self._client = self._mock_client
            self._using_mock = True

    @property
    def is_mock(self) -> bool:
        return self._using_mock

    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        use_cache: bool = True,  # 默认使用缓存
        **kwargs,
    ) -> LLMResponse:
        """发送对话请求"""
        start_time = time.time()
        self.metrics.total_calls += 1

        # 尝试从缓存获取
        if use_cache and self._cache and not tools:
            cached = self._cache.get(messages)
            if cached:
                self.metrics.cached_calls += 1
                logger.debug("LLM 响应命中缓存")
                return cached

        try:
            response = await self._client.chat(messages, tools, **kwargs)
            self.metrics.successful_calls += 1
            self.metrics.total_latency_ms += (time.time() - start_time) * 1000

            # 缓存响应
            if use_cache and self._cache and not tools:
                self._cache.set(messages, response)

            return response
        except Exception as e:
            logger.warning(f"LLM 调用失败: {e}")

            # 如果当前不是 Mock 客户端，尝试降级
            if not self._using_mock:
                logger.info("尝试使用 Mock 客户端...")
                try:
                    response = await self._mock_client.chat(messages, tools, **kwargs)
                    self.metrics.successful_calls += 1
                    self.metrics.total_latency_ms += (time.time() - start_time) * 1000
                    return response
                except Exception as mock_error:
                    logger.error(f"Mock 客户端也失败: {mock_error}")

            self.metrics.failed_calls += 1
            self.metrics.total_latency_ms += (time.time() - start_time) * 1000
            raise

    async def stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs,
    ):
        """流式对话"""
        async for chunk in self._client.stream(messages, tools, **kwargs):
            yield chunk


# 全局单例
def _estimate_message_chars(messages: List[LLMMessage]) -> int:
    return sum(len(str(getattr(message, "content", "") or "")) for message in messages)


def _manager_client_model_name(client: Optional[BaseLLMClient]) -> str:
    return str(getattr(client, "model", settings.llm.model) or settings.llm.model)


def _manager_client_provider_name(client: Optional[BaseLLMClient]) -> Optional[str]:
    if client is None:
        return None
    if isinstance(client, MockLLMClient):
        return "mock"
    if isinstance(client, OpenRouterClient):
        return "openrouter"
    return client.__class__.__name__.replace("Client", "").lower() or None


def _manager_request_options(
    client: Optional[BaseLLMClient],
    kwargs: Dict[str, Any],
    tools: Optional[List[ToolDefinition]],
    *,
    streaming: bool,
) -> Dict[str, Any]:
    return _runtime_options(
        model=_manager_client_model_name(client),
        base_url=getattr(client, "base_url", ""),
        temperature=_runtime_llm_temperature(kwargs.get("temperature")),
        max_tokens=_runtime_llm_max_tokens(kwargs.get("max_tokens")),
        timeout_seconds=_runtime_llm_timeout_for_client(client, kwargs.get("timeout")),
        reasoning_effort=_runtime_llm_reasoning_effort(kwargs.get("reasoning_effort")),
        tool_count=len(tools or []),
        tool_choice="auto" if tools else None,
        streaming=streaming,
    )


def _manager_retry_policy(client: Optional[BaseLLMClient]) -> Dict[str, Any]:
    max_attempts = _runtime_llm_retry_max_attempts_for_client(client)
    return _retry_audit(max_attempts=max_attempts, attempts=[])


async def _traced_enhanced_llm_chat(
    self: EnhancedLLMManager,
    messages: List[LLMMessage],
    tools: Optional[List[ToolDefinition]] = None,
    use_cache: bool = True,
    **kwargs,
) -> LLMResponse:
    start_time = time.time()
    self.metrics.total_calls += 1
    client = self._client
    request_options = _manager_request_options(client, kwargs, tools, streaming=False)
    retry_policy = _manager_retry_policy(client)

    if is_experiment_strict_mode() and (self._using_mock or isinstance(client, MockLLMClient)):
        trace_call = start_llm_call(
            provider=_manager_client_provider_name(client),
            model=_manager_client_model_name(client),
            streaming=False,
            mock=True,
            fallback=False,
            message_count=len(messages),
            message_chars=_estimate_message_chars(messages),
            tool_count=len(tools or []),
            request_options=request_options,
            retry_policy=retry_policy,
        )
        error = RuntimeError("EXPERIMENT_STRICT_MODE forbids Mock LLM client")
        finish_llm_call(
            trace_call,
            provider=_manager_client_provider_name(client),
            model=_manager_client_model_name(client),
            success=False,
            error=error,
            mock=True,
            fallback=False,
            request_options=request_options,
            retry=retry_policy,
        )
        self.metrics.failed_calls += 1
        self.metrics.total_latency_ms += (time.time() - start_time) * 1000
        raise error

    cache_allowed = use_cache and not is_experiment_cache_disabled()
    if cache_allowed and self._cache and not tools:
        cached = self._cache.get(messages)
        if cached:
            self.metrics.cached_calls += 1
            logger.debug("LLM 鍝嶅簲鍛戒腑缂撳瓨")
            trace_call = start_llm_call(
                provider=_manager_client_provider_name(self._client),
                model=cached.model,
                streaming=False,
                mock=self._using_mock,
                fallback=False,
                cache_hit=True,
                message_count=len(messages),
                message_chars=_estimate_message_chars(messages),
                tool_count=0,
                request_options=request_options,
                retry_policy=retry_policy,
            )
            finish_llm_call(
                trace_call,
                provider=_manager_client_provider_name(self._client),
                model=cached.model,
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                success=True,
                mock=self._using_mock,
                fallback=False,
                cache_hit=True,
                cached_source_usage=cached.usage,
                output_chars=len(str(cached.content or "")),
                chunk_count=0,
                request_options=request_options,
                retry=_retry_result_from_policy(retry_policy, success=True),
            )
            return cached

    trace_call = start_llm_call(
        provider=_manager_client_provider_name(client),
        model=_manager_client_model_name(client),
        streaming=False,
        mock=self._using_mock,
        fallback=False,
        message_count=len(messages),
        message_chars=_estimate_message_chars(messages),
        tool_count=len(tools or []),
        request_options=request_options,
        retry_policy=retry_policy,
    )

    try:
        response = await client.chat(messages, tools, **kwargs)
        response_metadata = getattr(response, "metadata", None)
        response_metadata = response_metadata if isinstance(response_metadata, dict) else {}
        self.metrics.successful_calls += 1
        self.metrics.total_latency_ms += (time.time() - start_time) * 1000
        finish_llm_call(
            trace_call,
            provider=_manager_client_provider_name(client),
            model=response.model,
            usage=response.usage,
            success=True,
            mock=self._using_mock,
            fallback=False,
            output_chars=len(str(response.content or "")),
            request_options=response_metadata.get("request_options") or request_options,
            retry=response_metadata.get("retry")
            or _retry_result_from_policy(retry_policy, success=True),
        )

        if cache_allowed and self._cache and not tools:
            self._cache.set(messages, response)

        return response
    except Exception as exc:
        logger.warning(f"LLM 璋冪敤澶辫触: {exc}")

        if not self._using_mock and not is_experiment_strict_mode():
            logger.info("灏濊瘯浣跨敤 Mock 瀹㈡埛绔?..")
            mock_request_options = _manager_request_options(
                self._mock_client,
                kwargs,
                tools,
                streaming=False,
            )
            mock_retry_policy = _manager_retry_policy(self._mock_client)
            try:
                response = await self._mock_client.chat(messages, tools, **kwargs)
                self.metrics.successful_calls += 1
                self.metrics.total_latency_ms += (time.time() - start_time) * 1000
                finish_llm_call(
                    trace_call,
                    provider="mock",
                    model=response.model,
                    usage=response.usage,
                    success=True,
                    mock=True,
                    fallback=True,
                    output_chars=len(str(response.content or "")),
                    request_options=mock_request_options,
                    retry=_retry_result_from_policy(mock_retry_policy, success=True),
                )
                return response
            except Exception as mock_error:
                logger.error(f"Mock 瀹㈡埛绔篃澶辫触: {mock_error}")
                finish_llm_call(
                    trace_call,
                    provider="mock",
                    model="mock-model",
                    success=False,
                    error=mock_error,
                    mock=True,
                    fallback=True,
                    request_options=mock_request_options,
                    retry=_retry_result_from_policy(
                        mock_retry_policy,
                        success=False,
                        error=mock_error,
                    ),
                )
                self.metrics.failed_calls += 1
                self.metrics.total_latency_ms += (time.time() - start_time) * 1000
                raise exc

        self.metrics.failed_calls += 1
        self.metrics.total_latency_ms += (time.time() - start_time) * 1000
        error_metadata = getattr(exc, "llm_audit_metadata", None)
        error_metadata = error_metadata if isinstance(error_metadata, dict) else {}
        finish_llm_call(
            trace_call,
            provider=_manager_client_provider_name(client),
            model=_manager_client_model_name(client),
            success=False,
            error=exc,
            mock=self._using_mock,
            fallback=False,
            request_options=error_metadata.get("request_options") or request_options,
            retry=error_metadata.get("retry")
            or _retry_result_from_policy(retry_policy, success=False, error=exc),
        )
        raise


async def _traced_enhanced_llm_stream(
    self: EnhancedLLMManager,
    messages: List[LLMMessage],
    tools: Optional[List[ToolDefinition]] = None,
    **kwargs,
):
    client = self._client
    request_options = _manager_request_options(client, kwargs, tools, streaming=True)
    retry_policy = _manager_retry_policy(client)
    trace_call = start_llm_call(
        provider=_manager_client_provider_name(client),
        model=_manager_client_model_name(client),
        streaming=True,
        mock=self._using_mock,
        fallback=False,
        message_count=len(messages),
        message_chars=_estimate_message_chars(messages),
        tool_count=len(tools or []),
        request_options=request_options,
        retry_policy=retry_policy,
    )
    chunk_count = 0
    output_chars = 0
    if is_experiment_strict_mode() and (self._using_mock or isinstance(client, MockLLMClient)):
        error = RuntimeError("EXPERIMENT_STRICT_MODE forbids Mock LLM client")
        finish_llm_call(
            trace_call,
            provider=_manager_client_provider_name(client),
            model=_manager_client_model_name(client),
            success=False,
            error=error,
            mock=True,
            fallback=False,
            output_chars=0,
            chunk_count=0,
            request_options=request_options,
            retry=retry_policy,
        )
        raise error
    try:
        async for chunk in client.stream(messages, tools, **kwargs):
            if chunk_count == 0:
                mark_llm_first_token(trace_call)
            chunk_count += 1
            output_chars += len(str(chunk or ""))
            yield chunk
    except BaseException as exc:
        finish_llm_call(
            trace_call,
            provider=_manager_client_provider_name(client),
            model=_manager_client_model_name(client),
            success=False,
            error=exc,
            mock=self._using_mock,
            fallback=False,
            output_chars=output_chars,
            chunk_count=chunk_count,
            request_options=request_options,
            retry=_retry_result_from_policy(retry_policy, success=False, error=exc),
        )
        raise
    else:
        finish_llm_call(
            trace_call,
            provider=_manager_client_provider_name(client),
            model=_manager_client_model_name(client),
            success=True,
            mock=self._using_mock,
            fallback=False,
            output_chars=output_chars,
            chunk_count=chunk_count,
            request_options=request_options,
            retry=_retry_result_from_policy(retry_policy, success=True),
        )


EnhancedLLMManager.chat = _traced_enhanced_llm_chat  # type: ignore[method-assign]
EnhancedLLMManager.stream = _traced_enhanced_llm_stream  # type: ignore[method-assign]


_llm_manager: Optional[EnhancedLLMManager] = None


def get_llm_manager() -> EnhancedLLMManager:
    """获取 LLM 管理器单例"""
    global _llm_manager
    if _llm_manager is None:
        _llm_manager = EnhancedLLMManager(enable_caching=True)
    return _llm_manager


def init_llm_manager() -> EnhancedLLMManager:
    """初始化 LLM 管理器"""
    return get_llm_manager()
