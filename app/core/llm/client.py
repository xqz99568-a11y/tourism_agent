"""
LLM 客户端模块
支持多种 LLM Provider 的统一接口
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    AsyncGenerator,
    Dict,
    List,
    Literal,
    Optional,
    Union,
)

import httpx
from openai import APIStatusError, APITimeoutError, AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from openai.types.chat.chat_completion import Choice
from app.core.config import settings
from app.core.logger import get_logger
from app.core.tracing import (
    finish_llm_call,
    is_experiment_strict_mode,
    mark_llm_first_token,
    start_llm_call,
)

logger = get_logger(__name__)

LLM_RUNTIME_OPTIONS_SCHEMA_VERSION = "ctp-llm-runtime-options-v1"
LLM_RETRY_AUDIT_SCHEMA_VERSION = "ctp-llm-retry-audit-v1"
OPENAI_SDK_MAX_RETRIES = 0
LLM_REASONING_EFFORT_ENV = "LLM_REASONING_EFFORT"
LLM_CHAT_TOKEN_PARAM_ENV = "LLM_CHAT_TOKEN_PARAM"
SUPPORTED_REASONING_EFFORTS = {"minimal", "low", "medium", "high"}
SUPPORTED_CHAT_TOKEN_PARAMS = {"auto", "max_tokens", "max_completion_tokens"}


def llm_provider_from_base_url(base_url: Any) -> str:
    """Return the experiment-facing provider label for an OpenAI-compatible URL.

    ``OpenRouterClient`` is the historical client class name in this project,
    but formal experiments may route requests through other OpenAI-compatible
    gateways such as VectorEngine.  Paper artifacts should identify the actual
    gateway from ``base_url`` instead of leaking the implementation class name.
    """
    text = str(base_url or "").casefold()
    if "vectorengine" in text:
        return "vectorengine_openai_compatible"
    if "openrouter" in text:
        return "openrouter"
    if "openai" in text:
        return "openai"
    return "openai_compatible"


def _coalesce(value: Any, default: Any) -> Any:
    return default if value is None else value


def _runtime_text(env_name: str, default: Any) -> str:
    value = os.getenv(env_name)
    if value is None or not str(value).strip():
        return str(default or "")
    return str(value).strip()


def _runtime_float(env_name: str, default: Any) -> float:
    value = os.getenv(env_name)
    if value is None or not str(value).strip():
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _runtime_int(env_name: str, default: Any) -> int:
    value = os.getenv(env_name)
    if value is None or not str(value).strip():
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _runtime_llm_temperature(explicit: Any = None, fallback: Any = None) -> float:
    if explicit is not None:
        return float(explicit)
    default = settings.llm.temperature if fallback is None else fallback
    return _runtime_float("LLM_TEMPERATURE", default)


def _runtime_llm_max_tokens(explicit: Any = None, fallback: Any = None) -> int:
    if explicit is not None:
        return _positive_int(explicit, settings.llm.max_tokens)
    default = settings.llm.max_tokens if fallback is None else fallback
    return _positive_int(
        _runtime_int("LLM_MAX_TOKENS", default),
        settings.llm.max_tokens,
    )


def _runtime_llm_timeout(explicit: Any = None, fallback: Any = None) -> int:
    if explicit is not None:
        return _positive_int(explicit, settings.llm.timeout)
    default = settings.llm.timeout if fallback is None else fallback
    return _positive_int(
        _runtime_int("LLM_TIMEOUT", default),
        settings.llm.timeout,
    )


def _runtime_llm_retry_max_attempts(explicit: Any = None, fallback: Any = None) -> int:
    if explicit is not None:
        return _positive_int(explicit, settings.llm.retry_max_attempts)
    default = settings.llm.retry_max_attempts if fallback is None else fallback
    return _positive_int(
        _runtime_int("LLM_RETRY_MAX_ATTEMPTS", default),
        settings.llm.retry_max_attempts,
    )


def _runtime_llm_reasoning_effort(explicit: Any = None) -> Optional[str]:
    """Return the optional reasoning-effort setting for reasoning models."""
    raw = explicit if explicit is not None else os.getenv(LLM_REASONING_EFFORT_ENV)
    if raw is None:
        return None
    value = str(raw).strip().lower()
    if not value:
        return None
    return value if value in SUPPORTED_REASONING_EFFORTS else None


def _prefers_max_completion_tokens(model: Any) -> bool:
    """Return true for OpenAI reasoning-family model names.

    OpenAI-compatible gateways are not perfectly consistent, but gpt-5/o-series
    chat-completion endpoints generally understand `max_completion_tokens` as
    the output budget that includes visible and reasoning tokens.  Keeping this
    choice deterministic prevents a formal run from silently using a token cap
    parameter that the gateway ignores for reasoning models.
    """
    value = str(model or "").strip().lower()
    if not value:
        return False
    normalized = value.split("/")[-1]
    return normalized.startswith(("gpt-5", "o1", "o3", "o4"))


def _runtime_llm_chat_token_param(model: Any, explicit: Any = None) -> str:
    raw = explicit if explicit is not None else os.getenv(LLM_CHAT_TOKEN_PARAM_ENV)
    value = str(raw or "auto").strip().lower()
    if value not in SUPPORTED_CHAT_TOKEN_PARAMS:
        value = "auto"
    if value == "auto":
        return "max_completion_tokens" if _prefers_max_completion_tokens(model) else "max_tokens"
    return value


def _runtime_llm_timeout_for_client(client: Any, explicit: Any = None) -> int:
    if explicit is not None or getattr(client, "_timeout_explicit", False):
        return _runtime_llm_timeout(
            explicit if explicit is not None else getattr(client, "timeout", None)
        )
    return _runtime_llm_timeout(None, fallback=getattr(client, "timeout", None))


def _runtime_llm_retry_max_attempts_for_client(client: Any, explicit: Any = None) -> int:
    if explicit is not None or getattr(client, "_retry_max_attempts_explicit", False):
        return _runtime_llm_retry_max_attempts(
            explicit
            if explicit is not None
            else getattr(client, "retry_max_attempts", None)
        )
    return _runtime_llm_retry_max_attempts(
        None,
        fallback=getattr(client, "retry_max_attempts", None),
    )


def _retryable_llm_error_reason(exc: BaseException) -> Optional[str]:
    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)
    try:
        numeric_status = int(status_code) if status_code is not None else None
    except (TypeError, ValueError):
        numeric_status = None
    if numeric_status == 429:
        return "http_429"
    if numeric_status is not None and 500 <= numeric_status <= 599:
        return "http_5xx"
    if isinstance(exc, (APITimeoutError, httpx.TimeoutException, TimeoutError, asyncio.TimeoutError)):
        return "network_timeout"
    if isinstance(exc, APIStatusError):
        return None
    return None


def _is_retryable_llm_error(exc: BaseException) -> bool:
    return _retryable_llm_error_reason(exc) is not None


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return int(default)
    return max(1, parsed)


def _runtime_options(
    *,
    model: Any,
    temperature: Any,
    max_tokens: Any,
    timeout_seconds: Any,
    tool_count: int,
    streaming: bool,
    base_url: Any = None,
    tool_choice: Any = None,
    reasoning_effort: Any = None,
    completion_limit_parameter: Any = None,
) -> Dict[str, Any]:
    return {
        "schema_version": LLM_RUNTIME_OPTIONS_SCHEMA_VERSION,
        "model": str(model or ""),
        "base_url": str(base_url or ""),
        "temperature": temperature,
        "max_tokens": max_tokens,
        "completion_limit_parameter": completion_limit_parameter,
        "timeout_seconds": timeout_seconds,
        "reasoning_effort": reasoning_effort,
        "tool_count": int(tool_count),
        "tool_choice": tool_choice,
        "streaming": bool(streaming),
    }


def _retry_audit(
    *,
    max_attempts: int,
    attempts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    error_count = sum(1 for attempt in attempts if attempt.get("success") is False)
    return {
        "schema_version": LLM_RETRY_AUDIT_SCHEMA_VERSION,
        "max_attempts": int(max_attempts),
        "attempt_count": len(attempts),
        "retry_count": max(0, len(attempts) - 1),
        "error_count": error_count,
        "succeeded": bool(attempts and attempts[-1].get("success") is True),
        "attempts": attempts,
    }


def _usage_from_chat_completion(response: ChatCompletion) -> Dict[str, Any]:
    usage = {
        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
        "total_tokens": response.usage.total_tokens if response.usage else 0,
    }
    if response.usage:
        completion_details = getattr(response.usage, "completion_tokens_details", None)
        if completion_details is not None:
            usage["completion_tokens_details"] = (
                completion_details.model_dump(mode="json")
                if hasattr(completion_details, "model_dump")
                else completion_details
            )
        prompt_details = getattr(response.usage, "prompt_tokens_details", None)
        if prompt_details is not None:
            usage["prompt_tokens_details"] = (
                prompt_details.model_dump(mode="json")
                if hasattr(prompt_details, "model_dump")
                else prompt_details
            )
    return usage


def _sum_usage_records(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    has_any = False
    for record in records:
        usage = record.get("usage")
        if not isinstance(usage, dict):
            continue
        has_any = True
        for key in totals:
            try:
                totals[key] += int(usage.get(key) or 0)
            except (TypeError, ValueError):
                continue
    return totals if has_any else {}


def _empty_token_capped_retry_reason(
    response: "LLMResponse",
    *,
    max_tokens: int,
) -> Optional[str]:
    if response.tool_calls:
        return None
    if str(response.content or "").strip():
        return None
    try:
        completion_tokens = int(response.usage.get("completion_tokens") or 0)
    except (TypeError, ValueError):
        completion_tokens = 0
    finish_reason = str(response.finish_reason or "").strip().lower()
    if finish_reason in {"length", "max_tokens", "content_filter"} or (
        max_tokens > 0 and completion_tokens >= max_tokens
    ):
        return "empty_output_at_token_cap"
    return None


def _retry_result_from_policy(
    policy: Dict[str, Any],
    *,
    success: bool,
    error: Any = None,
) -> Dict[str, Any]:
    attempt: Dict[str, Any] = {"attempt_index": 1, "success": bool(success)}
    if error:
        attempt["error_type"] = error.__class__.__name__
        attempt["error"] = str(error)
    return _retry_audit(
        max_attempts=_positive_int(policy.get("max_attempts"), settings.llm.retry_max_attempts),
        attempts=[attempt],
    )


def _attach_llm_audit_metadata(
    target: Any,
    *,
    request_options: Dict[str, Any],
    retry: Dict[str, Any],
) -> None:
    try:
        setattr(
            target,
            "llm_audit_metadata",
            {
                "request_options": request_options,
                "retry": retry,
            },
        )
    except Exception:
        return


def _audit_metadata(value: Any) -> Dict[str, Any]:
    metadata = getattr(value, "metadata", None)
    if isinstance(metadata, dict):
        return metadata
    metadata = getattr(value, "llm_audit_metadata", None)
    return metadata if isinstance(metadata, dict) else {}


class MessageRole(str, Enum):
    """消息角色"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class LLMMessage:
    """LLM 消息"""
    role: MessageRole | str
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: List[Any] = field(default_factory=list)

    def to_dict(self) -> dict:
        result: dict = {
            "role": self.role.value if isinstance(self.role, MessageRole) else self.role,
            "content": self.content,
        }
        if self.name:
            result["name"] = self.name
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            result["tool_calls"] = [
                call.to_dict() if hasattr(call, "to_dict") else call
                for call in self.tool_calls
            ]
        return result


@dataclass
class ToolCall:
    """工具调用"""
    id: str
    name: str
    arguments: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.arguments,
            },
        }


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    parameters: dict

    def to_dict(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class LLMResponse:
    """LLM 响应"""
    content: str
    model: str
    usage: dict
    finish_reason: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class BaseLLMClient(ABC):
    """LLM 客户端基类"""

    @abstractmethod
    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs,
    ) -> LLMResponse:
        """发送对话请求"""
        pass

    @abstractmethod
    async def stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """流式对话"""
        pass

    @abstractmethod
    async def embeddings(self, texts: List[str]) -> List[List[float]]:
        """获取文本嵌入"""
        pass


class OpenRouterClient(BaseLLMClient):
    """
    OpenRouter API 客户端
    支持 OpenAI 兼容格式
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
        retry_max_attempts: Optional[int] = None,
        retry_wait_min_seconds: float = 1.0,
        retry_wait_max_seconds: float = 5.0,
    ):
        self.api_key = api_key or _runtime_text("LLM_API_KEY", settings.llm.api_key)
        self.base_url = base_url or _runtime_text("LLM_BASE_URL", settings.llm.base_url)
        self.model = model or _runtime_text("LLM_MODEL", settings.llm.model)
        self._timeout_explicit = timeout is not None
        self._retry_max_attempts_explicit = retry_max_attempts is not None
        self.timeout = _runtime_llm_timeout(timeout)
        self.retry_max_attempts = _runtime_llm_retry_max_attempts(retry_max_attempts)
        self.retry_wait_min_seconds = max(0.0, float(retry_wait_min_seconds))
        self.retry_wait_max_seconds = max(
            self.retry_wait_min_seconds,
            float(retry_wait_max_seconds),
        )
        self.sdk_max_retries = OPENAI_SDK_MAX_RETRIES

        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=self.sdk_max_retries,
            http_client=httpx.AsyncClient(timeout=httpx.Timeout(self.timeout)),
        )

    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        retry_max_attempts: Optional[int] = None,
        **kwargs,
    ) -> LLMResponse:
        """发送对话请求"""

        # 转换为 API 格式
        api_messages = [msg.to_dict() for msg in messages]
        resolved_temperature = _runtime_llm_temperature(temperature)
        resolved_max_tokens = _runtime_llm_max_tokens(max_tokens)
        resolved_reasoning_effort = _runtime_llm_reasoning_effort(
            kwargs.pop("reasoning_effort", reasoning_effort)
        )
        resolved_token_param = _runtime_llm_chat_token_param(
            self.model,
            kwargs.pop("token_limit_parameter", None),
        )
        resolved_timeout = _runtime_llm_timeout_for_client(
            self,
            kwargs.pop("timeout", None),
        )
        resolved_max_attempts = _runtime_llm_retry_max_attempts_for_client(
            self,
            retry_max_attempts,
        )
        request_options = _runtime_options(
            model=self.model,
            base_url=self.base_url,
            temperature=resolved_temperature,
            max_tokens=resolved_max_tokens,
            timeout_seconds=resolved_timeout,
            reasoning_effort=resolved_reasoning_effort,
            completion_limit_parameter=resolved_token_param,
            tool_count=len(tools or []),
            tool_choice="auto" if tools else None,
            streaming=False,
        )
        request_options["sdk_max_retries"] = self.sdk_max_retries

        # 构建请求参数
        request_kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "temperature": resolved_temperature,
            "timeout": resolved_timeout,
        }
        request_kwargs[resolved_token_param] = resolved_max_tokens
        if resolved_reasoning_effort is not None:
            request_kwargs["reasoning_effort"] = resolved_reasoning_effort

        if tools:
            request_kwargs["tools"] = [tool.to_dict() for tool in tools]
            request_kwargs["tool_choice"] = "auto"

        attempts: List[Dict[str, Any]] = []
        last_error: Optional[BaseException] = None
        for attempt_index in range(1, resolved_max_attempts + 1):
            attempt_started = time.perf_counter()
            try:
                response: ChatCompletion = await self.client.chat.completions.create(
                    **request_kwargs
                )
            except Exception as exc:
                last_error = exc
                retry_reason = _retryable_llm_error_reason(exc)
                attempts.append(
                    {
                        "attempt_index": attempt_index,
                        "success": False,
                        "duration_ms": round(
                            (time.perf_counter() - attempt_started) * 1000,
                            2,
                        ),
                        "error_type": exc.__class__.__name__,
                        "error": str(exc),
                        "retryable": retry_reason is not None,
                        "retry_reason": retry_reason,
                    }
                )
                if retry_reason is None or attempt_index >= resolved_max_attempts:
                    retry_record = _retry_audit(
                        max_attempts=resolved_max_attempts,
                        attempts=attempts,
                    )
                    _attach_llm_audit_metadata(
                        exc,
                        request_options=request_options,
                        retry=retry_record,
                    )
                    logger.error(f"LLM API 调用失败: {exc}")
                    raise
                wait_seconds = min(
                    self.retry_wait_max_seconds,
                    self.retry_wait_min_seconds * (2 ** (attempt_index - 1)),
                )
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)
                continue

            try:
                parsed_response = self._parse_response(response)
            except Exception as parse_error:
                retry_record = _retry_audit(
                    max_attempts=resolved_max_attempts,
                    attempts=attempts,
                )
                _attach_llm_audit_metadata(
                    parse_error,
                    request_options=request_options,
                    retry=retry_record,
                )
                raise
            usage = dict(parsed_response.usage or {})
            duration_ms = round(
                (time.perf_counter() - attempt_started) * 1000,
                2,
            )
            retry_reason = _empty_token_capped_retry_reason(
                parsed_response,
                max_tokens=resolved_max_tokens,
            )
            if retry_reason is not None and attempt_index < resolved_max_attempts:
                attempts.append(
                    {
                        "attempt_index": attempt_index,
                        "success": False,
                        "duration_ms": duration_ms,
                        "retryable": True,
                        "retry_reason": retry_reason,
                        "finish_reason": parsed_response.finish_reason,
                        "output_chars": len(str(parsed_response.content or "")),
                        "usage": usage,
                    }
                )
                wait_seconds = min(
                    self.retry_wait_max_seconds,
                    self.retry_wait_min_seconds * (2 ** (attempt_index - 1)),
                )
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)
                continue

            attempts.append(
                {
                    "attempt_index": attempt_index,
                    "success": True,
                    "duration_ms": duration_ms,
                    "finish_reason": parsed_response.finish_reason,
                    "output_chars": len(str(parsed_response.content or "")),
                    "usage": usage,
                }
            )
            retry_record = _retry_audit(
                max_attempts=resolved_max_attempts,
                attempts=attempts,
            )
            aggregated_usage = _sum_usage_records(attempts)
            if aggregated_usage:
                parsed_response.metadata["single_attempt_usage"] = parsed_response.usage
                parsed_response.usage = aggregated_usage
            parsed_response.metadata["request_options"] = request_options
            parsed_response.metadata["retry"] = retry_record
            return parsed_response

        assert last_error is not None
        raise last_error

    def _parse_response(
        self,
        response: ChatCompletion,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> LLMResponse:
        """解析 API 响应"""
        choice: Choice = response.choices[0]
        message = choice.message

        # 解析 tool_calls
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                if tc.function:
                    tool_calls.append(
                        ToolCall(
                            id=tc.id or "",
                            name=tc.function.name or "",
                            arguments=tc.function.arguments or "{}",
                        )
                    )

        usage = _usage_from_chat_completion(response)

        return LLMResponse(
            content=message.content or "",
            model=response.model,
            usage=usage,
            finish_reason=choice.finish_reason or "",
            tool_calls=tool_calls,
            metadata=metadata or {},
        )

    async def stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: Optional[float] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """流式对话"""

        api_messages = [msg.to_dict() for msg in messages]
        resolved_temperature = _runtime_llm_temperature(temperature)
        resolved_reasoning_effort = _runtime_llm_reasoning_effort(
            kwargs.pop("reasoning_effort", None)
        )
        resolved_max_tokens = _runtime_llm_max_tokens(kwargs.pop("max_tokens", None))
        resolved_token_param = _runtime_llm_chat_token_param(
            self.model,
            kwargs.pop("token_limit_parameter", None),
        )
        resolved_timeout = _runtime_llm_timeout_for_client(
            self,
            kwargs.pop("timeout", None),
        )

        request_kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "temperature": resolved_temperature,
            "timeout": resolved_timeout,
            "stream": True,
        }
        request_kwargs[resolved_token_param] = resolved_max_tokens
        if resolved_reasoning_effort is not None:
            request_kwargs["reasoning_effort"] = resolved_reasoning_effort

        if tools:
            request_kwargs["tools"] = [tool.to_dict() for tool in tools]

        try:
            stream = await self.client.chat.completions.create(**request_kwargs)

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            logger.error(f"LLM 流式调用失败: {e}")
            raise

    async def embeddings(self, texts: List[str]) -> List[List[float]]:
        """获取文本嵌入"""
        try:
            response = await self.client.embeddings.create(
                model="text-embedding-3-small",
                input=texts,
            )
            return [item.embedding for item in response.data]
        except Exception as e:
            logger.error(f"Embedding 获取失败: {e}")
            raise


class OllamaClient(BaseLLMClient):
    """
    Ollama 本地模型客户端
    支持本地部署的模型（如 Qwen2.5, Llama3.2 等）
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5",
        timeout: int = 120,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
        )

    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMResponse:
        """发送对话请求"""
        # 转换消息格式 (Ollama 格式)
        ollama_messages = [msg.to_dict() for msg in messages]

        request_data: Dict[str, Any] = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": False,
            "options": {
                "temperature": _runtime_llm_temperature(temperature),
                "num_predict": _runtime_llm_max_tokens(max_tokens),
            },
        }

        # 添加 tools 如果支持
        if tools:
            request_data["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    }
                }
                for tool in tools
            ]

        try:
            response = await self.client.post("/api/chat", json=request_data)
            response.raise_for_status()
            data = response.json()

            content = data.get("message", {}).get("content", "")

            tool_calls = []
            if "tool_calls" in data.get("message", {}):
                for tc in data["message"]["tool_calls"]:
                    tool_calls.append(
                        ToolCall(
                            id=tc.get("id", ""),
                            name=tc.get("function", {}).get("name", ""),
                            arguments=tc.get("function", {}).get("arguments", "{}"),
                        )
                    )

            return LLMResponse(
                content=content,
                model=self.model,
                usage={
                    "prompt_tokens": data.get("prompt_eval_count", 0),
                    "completion_tokens": data.get("eval_count", 0),
                    "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
                },
                finish_reason=data.get("done_reason", "stop"),
                tool_calls=tool_calls,
            )

        except httpx.HTTPError as e:
            logger.error(f"Ollama API 调用失败: {e}")
            raise

    async def stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: Optional[float] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """流式对话"""
        # 转换消息格式
        ollama_messages = []
        for msg in messages:
            role = msg.role.value if hasattr(msg.role, 'value') else msg.role
            ollama_messages.append({
                "role": role,
                "content": msg.content,
            })

        request_data: Dict[str, Any] = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": True,
            "options": {
                "temperature": _runtime_llm_temperature(temperature),
                "num_predict": _runtime_llm_max_tokens(kwargs.get("max_tokens")),
            },
        }

        try:
            async with self.client.stream("POST", "/api/chat", json=request_data) as stream:
                async for line in stream.aiter_lines():
                    if line:
                        import json
                        data = json.loads(line)
                        if "message" in data and "content" in data["message"]:
                            content = data["message"]["content"]
                            if content:
                                yield content

        except httpx.HTTPError as e:
            logger.error(f"Ollama 流式调用失败: {e}")
            raise

    async def embeddings(self, texts: List[str]) -> List[List[float]]:
        """获取文本嵌入"""
        model_name = "nomic-embed-text"

        try:
            embeddings = []
            for text in texts:
                response = await self.client.post(
                    "/api/embeddings",
                    json={"model": model_name, "prompt": text},
                )
                response.raise_for_status()
                data = response.json()
                embeddings.append(data.get("embedding", []))
            return embeddings
        except httpx.HTTPError as e:
            logger.error(f"Ollama embedding 失败: {e}")
            raise

    async def health_check(self) -> bool:
        """健康检查"""
        try:
            response = await self.client.get("/api/tags")
            return response.status_code == 200
        except Exception:
            return False


class MockLLMClient(BaseLLMClient):
    """
    Mock LLM 客户端（用于开发/测试）
    当没有配置 API key 时使用
    """

    # 用于存储上一次意图解析的结果
    _last_intent_info = {}

    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs,
    ) -> LLMResponse:
        """返回模拟响应"""
        # 分析消息
        user_message = ""
        system_prompt = ""
        for msg in messages:
            if hasattr(msg, 'role'):
                if msg.role == "user":
                    user_message = msg.content
                elif msg.role == "system":
                    system_prompt = msg.content

        # 检测是否需要 JSON 响应（IntentParser 场景）
        if "JSON" in system_prompt or "json" in system_prompt.lower():
            response_content = self._generate_json_response(user_message)
            # 尝试解析并存储意图信息
            try:
                import json
                data = json.loads(response_content)
                self._last_intent_info = data.get("extracted_info", {})
            except:
                pass
        else:
            # 根据系统提示判断是哪个 Agent
            if "景点推荐" in system_prompt or "景点" in system_prompt:
                response_content = self._generate_attraction_response(user_message)
            elif "预算" in system_prompt:
                response_content = self._generate_budget_response(user_message)
            elif "行程" in system_prompt:
                response_content = self._generate_itinerary_response(user_message)
            elif "天气" in system_prompt:
                response_content = self._generate_weather_response(user_message)
            elif "审查" in system_prompt:
                response_content = self._generate_review_response(user_message)
            else:
                response_content = self._generate_response(user_message)

        return LLMResponse(
            content=response_content,
            model="mock-model",
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 200,
                "total_tokens": 300,
            },
            finish_reason="stop",
            tool_calls=[],
        )

    async def stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """流式响应（单次返回）"""
        response = await self.chat(messages, tools, **kwargs)
        yield response.content

    async def embeddings(self, texts: List[str]) -> List[List[float]]:
        """返回随机嵌入向量"""
        import random
        return [[random.random() for _ in range(1536)] for _ in texts]

    def _generate_json_response(self, user_message: str) -> str:
        """生成 JSON 格式的意图解析响应"""
        import re

        # 检测目的地
        destinations = ["杭州", "北京", "上海", "成都", "西安", "桂林", "深圳", "广州", "厦门", "丽江"]
        found_destination = None
        for dest in destinations:
            if dest in user_message:
                found_destination = dest
                break

        # 检测天数
        days_match = re.search(r"(\d+)[天日]", user_message)
        days = int(days_match.group(1)) if days_match else 3

        # 检测人数
        people_match = re.search(r"(\d+)[个人位]", user_message)
        people = int(people_match.group(1)) if people_match else 2

        # 检测预算
        budget_match = re.search(r"(\d+)(?:00)?[0-9]?[元块]", user_message)
        budget = int(budget_match.group(1)) * 100 if budget_match else 5000

        # 确定意图
        if found_destination:
            intent = "trip_planning"
        else:
            intent = "general_chat"

        return f'{{"intent": "{intent}", "extracted_info": {{"destination": "{found_destination or ""}", "duration": {days}, "num_travelers": {people}, "budget": {budget}, "travel_styles": []}}}}'

    def _generate_attraction_response(self, user_message: str) -> str:
        """生成景点推荐响应"""
        dest = self._last_intent_info.get("destination", "当地")
        return f"""## {dest}景点推荐

根据您的需求，为您推荐以下景点：

### 必去经典景点
1. **西湖** - 杭州的标志性景点，环境优美，适合漫步
2. **灵隐寺** - 历史悠久的佛教寺院，香火鼎盛
3. **宋城** - 体验南宋文化的主题公园

### 特色景点
1. **河坊街** - 古老的商业街，可以品尝当地小吃
2. **龙井村** - 著名的龙井茶产地，空气清新

### 适合人群
- 西湖适合所有人群，老人家也可以轻松游览
- 灵隐寺建议穿舒适的鞋子
- 记得提前预约热门景点门票"""

    def _generate_budget_response(self, user_message: str) -> str:
        """生成预算分析响应"""
        days = self._last_intent_info.get("duration", 3)
        people = self._last_intent_info.get("num_travelers", 2)
        budget = self._last_intent_info.get("budget", 5000)

        per_person = budget // people
        per_day = per_person // days

        return f"""## 预算分析

### 总体预算
- 总预算：{budget}元
- 人均预算：{per_person}元
- 每日预算：约{per_day}元

### 费用分配建议
| 类别 | 占比 | 金额 |
|------|------|------|
| 交通 | 20% | {int(budget*0.2)}元 |
| 住宿 | 35% | {int(budget*0.35)}元 |
| 餐饮 | 20% | {int(budget*0.2)}元 |
| 门票 | 15% | {int(budget*0.15)}元 |
| 其他 | 10% | {int(budget*0.1)}元 |

### 省钱建议
1. 提前预订机票/火车票
2. 选择性价比高的酒店
3. 尝试当地特色小吃，比餐厅便宜"""

    def _generate_itinerary_response(self, user_message: str) -> str:
        """生成行程规划响应"""
        dest = self._last_intent_info.get("destination", "当地")
        days = self._last_intent_info.get("duration", 3)
        return f"""## {dest}{days}日行程规划

### 第1天：抵达与休整
- 上午：抵达后前往酒店办理入住
- 中午：在酒店附近品尝当地美食
- 下午：游览核心景区
- 晚上：欣赏夜景，休息调整

### 第2天：深度游览
- 上午：参观著名景点
- 中午：尝试当地特色午餐
- 下午：继续探索周边景点
- 晚上：自由活动时间

### 第3天：休闲返程
- 上午：安排轻松的景点
- 中午：享受最后一顿美食
- 下午：准备返程

### 温馨提示
- 建议提前查看天气预报
- 热门景点请提前预约"""

    def _generate_weather_response(self, user_message: str) -> str:
        """生成天气响应"""
        dest = self._last_intent_info.get("destination", "当地")
        return f"""## {dest}天气预报

### 出行建议
- 温度适宜，建议携带薄外套
- 可能有小雨，请带好雨具
- 紫外线较强，注意防晒

### 穿着建议
- 白天：轻薄长袖+短裤/长裙
- 早晚：添加薄外套
- 鞋子：舒适的步行鞋

### 必备物品
- 雨伞/雨衣
- 防晒霜
- 常用药品"""

    def _generate_review_response(self, user_message: str) -> str:
        """生成审查响应"""
        return """## 规划质量审查报告

### 完整性检查
- [x] 包含目的地介绍
- [x] 有每日行程安排
- [x] 有预算分析
- [x] 有实用贴士

### 质量评分
- 内容质量：8/10
- 实用性：9/10
- 个性化程度：7/10

### 总体评价
规划方案完整合理，可以作为出行参考。建议根据实际情况微调。"""

    def _generate_response(self, user_message: str) -> str:
        """根据用户输入生成模拟响应"""
        user_lower = user_message.lower()

        # 检测目的地
        destinations = ["杭州", "北京", "上海", "成都", "西安", "桂林", "深圳", "杭州"]
        found_destination = None
        for dest in destinations:
            if dest in user_message:
                found_destination = dest
                break

        # 检测天数
        import re
        days_match = re.search(r"(\d+)[天日]", user_message)
        days = int(days_match.group(1)) if days_match else 3

        # 检测人数
        people_match = re.search(r"(\d+)[个人位]", user_message)
        people = int(people_match.group(1)) if people_match else 2

        if found_destination:
            return f"""## {found_destination}旅行规划建议

### 目的地简介
{found_destination}是中国著名的旅游城市，拥有丰富的历史文化和美丽的自然风光。建议游览时间：{days}天。

### 行程安排

**第1天：市区经典游**
- 上午：抵达后入住酒店，休整片刻
- 中午：品尝当地特色美食
- 下午：游览核心景区
- 晚上：欣赏夜景

**第2天：深度体验**
- 上午：参观博物馆或文化遗址
- 中午：尝试当地小吃
- 下午：探索特色街区
- 晚上：自由活动

**第3天：周边休闲**
- 上午：前往周边景点
- 中午：农家乐午餐
- 下午：返回市区，准备返程

### 预算估算（{people}人/{days}天）
| 类别 | 预算 |
|------|------|
| 交通 | ¥800-1500 |
| 住宿 | ¥600-1200 |
| 餐饮 | ¥500-1000 |
| 门票 | ¥400-800 |
| 其他 | ¥200-500 |
| **总计** | **¥2500-5000** |

### 实用贴士
1. 提前查看天气预报，准备合适的衣物
2. 热门景点建议提前预约门票
3. 准备好舒适的步行鞋
4. 随身携带常用药品和防晒用品

祝您旅途愉快！"""

        return f"""## 旅行规划助手

您好！我是您的智能旅行规划助手。

要为您制定完美的旅行规划，请告诉我：
1. **想去哪里？**（目的地）
2. **玩几天？**
3. **几个人一起？**
4. **预算大概多少？**

例如："我想去杭州玩3天，2个人，预算5000元"

我会为您安排好一切！"""


class LLMManager:
    """
    LLM 管理器
    支持多种后端：Ollama (本地) > OpenRouter (云端) > Mock
    """

    def __init__(self):
        self._client: Optional[BaseLLMClient] = None
        self._init_client()

    def _init_client(self) -> None:
        """初始化客户端，优先使用本地 Ollama"""
        strict_mode = is_experiment_strict_mode()
        llm_configured = bool(os.getenv("LLM_API_KEY") or settings.llm.is_configured)
        if strict_mode and llm_configured:
            self._client = OpenRouterClient()
            logger.info(f"OpenRouter 客户端已初始化，使用模型: {settings.llm.model}")
            return
        # 检查是否配置了 Ollama (本地模型)
        ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        ollama_model = os.environ.get("OLLAMA_MODEL", "qwen2.5")
        
        # 尝试连接 Ollama
        try:
            import httpx
            test_client = httpx.AsyncClient(base_url=ollama_base_url, timeout=5)
            response = test_client.sync_client.get("/api/tags")
            if response.status_code == 200:
                self._client = OllamaClient(
                    base_url=ollama_base_url,
                    model=ollama_model,
                    timeout=120,
                )
                logger.info(f"Ollama 客户端已初始化，使用模型: {ollama_model}")
                return
        except Exception as e:
            logger.debug(f"Ollama 不可用: {e}")

        # 降级到 OpenRouter
        if llm_configured:
            self._client = OpenRouterClient()
            logger.info(f"OpenRouter 客户端已初始化，使用模型: {settings.llm.model}")
        else:
            if strict_mode:
                raise RuntimeError("EXPERIMENT_STRICT_MODE forbids implicit Mock LLM client")
            logger.warning("No LLM API key configured, using mock client for demo")
            self._client = MockLLMClient()

    def get_client(self) -> BaseLLMClient:
        """获取 LLM 客户端"""
        if self._client:
            return self._client
        raise ValueError("No LLM client configured")

    def _estimate_message_chars(self, messages: List[LLMMessage]) -> int:
        total = 0
        for message in messages:
            total += len(str(getattr(message, "content", "") or ""))
        return total

    def _prompt_hash(self, messages: List[LLMMessage], tools: Optional[List[ToolDefinition]]) -> str:
        payload = {
            "messages": [
                message.to_dict() if hasattr(message, "to_dict") else str(message)
                for message in messages
            ],
            "tools": [
                tool.to_dict() if hasattr(tool, "to_dict") else str(tool)
                for tool in (tools or [])
            ],
        }
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _prompt_version(self, messages: List[LLMMessage]) -> str:
        versions: list[str] = []
        for message in messages:
            content = str(getattr(message, "content", "") or "")
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict) and parsed.get("prompt_version"):
                versions.append(str(parsed["prompt_version"]))
            for marker in (
                "ctp-structured-llm-output-prompts-v2",
                "ctp-research-agent-prompts-v2",
                "ctp-structured-llm-output-prompts-v1",
                "ctp-research-agent-prompts-v1",
            ):
                if marker in content and marker not in versions:
                    versions.append(marker)
        return "+".join(versions) if versions else "unversioned"

    def _client_model_name(self, client: BaseLLMClient) -> str:
        return str(getattr(client, "model", settings.llm.model) or settings.llm.model)

    def _client_provider_name(self, client: BaseLLMClient) -> str:
        if isinstance(client, MockLLMClient):
            return "mock"
        if isinstance(client, OllamaClient):
            return "ollama"
        if isinstance(client, OpenRouterClient):
            return llm_provider_from_base_url(getattr(client, "base_url", ""))
        if getattr(client, "base_url", None):
            return llm_provider_from_base_url(getattr(client, "base_url", ""))
        return client.__class__.__name__.replace("Client", "").lower() or "unknown"

    def _request_options(
        self,
        client: BaseLLMClient,
        kwargs: Dict[str, Any],
        tools: Optional[List[ToolDefinition]],
        *,
        streaming: bool,
    ) -> Dict[str, Any]:
        return _runtime_options(
            model=self._client_model_name(client),
            base_url=getattr(client, "base_url", ""),
            temperature=_runtime_llm_temperature(kwargs.get("temperature")),
            max_tokens=_runtime_llm_max_tokens(kwargs.get("max_tokens")),
            timeout_seconds=_runtime_llm_timeout_for_client(client, kwargs.get("timeout")),
            reasoning_effort=_runtime_llm_reasoning_effort(kwargs.get("reasoning_effort")),
            completion_limit_parameter=_runtime_llm_chat_token_param(
                self._client_model_name(client),
                kwargs.get("token_limit_parameter"),
            ),
            tool_count=len(tools or []),
            tool_choice="auto" if tools else None,
            streaming=streaming,
        )

    def _retry_policy(self, client: BaseLLMClient) -> Dict[str, Any]:
        max_attempts = _runtime_llm_retry_max_attempts_for_client(client)
        return _retry_audit(max_attempts=max_attempts, attempts=[])

    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs,
    ) -> LLMResponse:
        """发送对话请求"""
        client = self.get_client()

        try:
            return await client.chat(messages, tools, **kwargs)
        except Exception as e:
            logger.error(f"LLM API 调用失败: {e}")
            # 失败时尝试使用 Mock 客户端
            if not isinstance(client, MockLLMClient):
                logger.info("回退到 Mock 客户端")
                mock_client = MockLLMClient()
                return await mock_client.chat(messages, tools, **kwargs)
            raise

    async def stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """流式对话"""
        client = self.get_client()
        async for chunk in client.stream(messages, tools, **kwargs):
            yield chunk


# 全局 LLM 管理器
_llm_manager: Optional[LLMManager] = None


async def _traced_llm_manager_chat(
    self: LLMManager,
    messages: List[LLMMessage],
    tools: Optional[List[ToolDefinition]] = None,
    **kwargs,
) -> LLMResponse:
    client = self.get_client()
    request_options = self._request_options(client, kwargs, tools, streaming=False)
    retry_policy = self._retry_policy(client)
    trace_call = start_llm_call(
        provider=self._client_provider_name(client),
        model=self._client_model_name(client),
        streaming=False,
        mock=isinstance(client, MockLLMClient),
        fallback=False,
        message_count=len(messages),
        message_chars=self._estimate_message_chars(messages),
        tool_count=len(tools or []),
        prompt_version=self._prompt_version(messages),
        prompt_hash=self._prompt_hash(messages, tools),
        request_options=request_options,
        retry_policy=retry_policy,
    )
    if is_experiment_strict_mode() and isinstance(client, MockLLMClient):
        error = RuntimeError("EXPERIMENT_STRICT_MODE forbids Mock LLM client")
        finish_llm_call(
            trace_call,
            provider=self._client_provider_name(client),
            model=self._client_model_name(client),
            success=False,
            error=error,
            mock=True,
            fallback=False,
            request_options=request_options,
            retry=retry_policy,
        )
        raise error

    try:
        response = await client.chat(messages, tools, **kwargs)
        audit_metadata = _audit_metadata(response)
        finish_llm_call(
            trace_call,
            provider=self._client_provider_name(client),
            model=response.model,
            usage=response.usage,
            success=True,
            mock=isinstance(client, MockLLMClient),
            fallback=False,
            output_chars=len(str(response.content or "")),
            request_options=audit_metadata.get("request_options") or request_options,
            retry=audit_metadata.get("retry")
            or _retry_result_from_policy(retry_policy, success=True),
        )
        return response
    except Exception as exc:
        logger.error(f"LLM API 璋冪敤澶辫触: {exc}")
        error_metadata = _audit_metadata(exc)
        if not isinstance(client, MockLLMClient) and not is_experiment_strict_mode():
            logger.info("Falling back to Mock LLM client")
            mock_client = MockLLMClient()
            mock_request_options = self._request_options(mock_client, kwargs, tools, streaming=False)
            mock_retry_policy = self._retry_policy(mock_client)
            try:
                response = await mock_client.chat(messages, tools, **kwargs)
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
                raise
        finish_llm_call(
            trace_call,
            provider=self._client_provider_name(client),
            model=self._client_model_name(client),
            success=False,
            error=exc,
            mock=isinstance(client, MockLLMClient),
            fallback=False,
            request_options=error_metadata.get("request_options") or request_options,
            retry=error_metadata.get("retry")
            or _retry_result_from_policy(retry_policy, success=False, error=exc),
        )
        raise


async def _traced_llm_manager_stream(
    self: LLMManager,
    messages: List[LLMMessage],
    tools: Optional[List[ToolDefinition]] = None,
    **kwargs,
) -> AsyncGenerator[str, None]:
    client = self.get_client()
    request_options = self._request_options(client, kwargs, tools, streaming=True)
    retry_policy = self._retry_policy(client)
    trace_call = start_llm_call(
        provider=self._client_provider_name(client),
        model=self._client_model_name(client),
        streaming=True,
        mock=isinstance(client, MockLLMClient),
        fallback=False,
        message_count=len(messages),
        message_chars=self._estimate_message_chars(messages),
        tool_count=len(tools or []),
        prompt_version=self._prompt_version(messages),
        prompt_hash=self._prompt_hash(messages, tools),
        request_options=request_options,
        retry_policy=retry_policy,
    )
    chunk_count = 0
    output_chars = 0
    if is_experiment_strict_mode() and isinstance(client, MockLLMClient):
        error = RuntimeError("EXPERIMENT_STRICT_MODE forbids Mock LLM client")
        finish_llm_call(
            trace_call,
            provider=self._client_provider_name(client),
            model=self._client_model_name(client),
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
            provider=self._client_provider_name(client),
            model=self._client_model_name(client),
            success=False,
            error=exc,
            mock=isinstance(client, MockLLMClient),
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
            provider=self._client_provider_name(client),
            model=self._client_model_name(client),
            success=True,
            mock=isinstance(client, MockLLMClient),
            fallback=False,
            output_chars=output_chars,
            chunk_count=chunk_count,
            request_options=request_options,
            retry=_retry_result_from_policy(retry_policy, success=True),
        )


LLMManager.chat = _traced_llm_manager_chat  # type: ignore[method-assign]
LLMManager.stream = _traced_llm_manager_stream  # type: ignore[method-assign]


def get_llm() -> LLMManager:
    """获取 LLM 管理器"""
    global _llm_manager
    if _llm_manager is None:
        _llm_manager = LLMManager()
    return _llm_manager
