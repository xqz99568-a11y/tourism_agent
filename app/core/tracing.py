from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

REDACTED = "[REDACTED]"
TRACE_SCHEMA_VERSION = "1.0"
DEFAULT_TRACE_DIR = Path("experiments/results/traces")

_current_trace: ContextVar[Optional["TraceState"]] = ContextVar(
    "tourism_request_trace",
    default=None,
)

_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "access_key",
    "secret",
    "token",
    "password",
    "passwd",
    "authorization",
    "security_code",
    "private_key",
    "credential",
    "cookie",
    "signature",
    "jwt",
)
_SENSITIVE_EXACT_KEYS = {"key", "x-api-key", "api-key", "auth"}
_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"),
)
_AGENT_STAGE_NAMES = {
    "planner",
    "attraction",
    "itinerary",
    "budget",
    "weather",
    "review",
    "unified_planner",
}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def is_tracing_enabled() -> bool:
    """Return the runtime tracing flag without requiring a settings reload."""
    return _env_bool("ENABLE_TRACING", bool(settings.features.enable_tracing))


def get_trace_dir() -> Path:
    return Path(os.getenv("TRACE_OUTPUT_DIR", str(DEFAULT_TRACE_DIR)))


def get_current_trace() -> Optional["TraceState"]:
    return _current_trace.get()


def _is_sensitive_key(key: Any) -> bool:
    key_text = str(key or "").strip().lower().replace("-", "_")
    if key_text.replace("_", "-") in _SENSITIVE_EXACT_KEYS or key_text in _SENSITIVE_EXACT_KEYS:
        return True
    return any(part in key_text for part in _SENSITIVE_KEY_PARTS)


def _looks_like_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS)


def sanitize_value(value: Any, *, key: Any = None, depth: int = 0) -> Any:
    """Sanitize values before they are persisted to experiment traces."""
    if _is_sensitive_key(key):
        return REDACTED
    if depth > 8:
        return "<max_depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if _looks_like_secret(value):
            return REDACTED
        return value if len(value) <= 2000 else value[:2000] + "...<truncated>"
    if isinstance(value, dict):
        return {
            str(item_key): sanitize_value(item_value, key=item_key, depth=depth + 1)
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        sanitized = [sanitize_value(item, depth=depth + 1) for item in items[:100]]
        if len(items) > 100:
            sanitized.append(f"<truncated {len(items) - 100} items>")
        return sanitized
    if isinstance(value, datetime):
        return value.isoformat()
    return sanitize_value(str(value), key=key, depth=depth + 1)


def _round_ms(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 2)


def _stable_json(value: Any) -> str:
    return json.dumps(sanitize_value(value), ensure_ascii=False, sort_keys=True, default=str)


def _success_from_status(status: Optional[str], success: Optional[bool]) -> Optional[bool]:
    if success is not None:
        return bool(success)
    if status is None:
        return None
    return str(status).lower() not in {"failed", "error", "timeout"}


def _safe_filename_part(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "request")).strip("._")
    return (safe or "request")[:80]


@dataclass
class TraceState:
    request_id: str
    session_id: str
    started_at_perf: float = field(default_factory=time.perf_counter)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "running"
    mode: Optional[str] = None
    intent: Optional[str] = None
    route: Optional[str] = None
    extracted_info: Dict[str, Any] = field(default_factory=dict)
    missing_fields: List[Any] = field(default_factory=list)
    selected_agents: List[str] = field(default_factory=list)
    stage_timings: Dict[str, float] = field(default_factory=dict)
    agent_timings: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    llm_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    api_calls: List[Dict[str, Any]] = field(default_factory=list)
    total_duration_ms: Optional[float] = None
    first_token_ms: Optional[float] = None
    error: Optional[str] = None
    trace_file: Optional[str] = None
    _finished: bool = field(default=False, repr=False)
    _tool_keys: set[str] = field(default_factory=set, repr=False)
    _api_keys: set[str] = field(default_factory=set, repr=False)

    def mark_first_token(self) -> None:
        if self.first_token_ms is None:
            self.first_token_ms = _round_ms((time.perf_counter() - self.started_at_perf) * 1000)

    def record_event(self, event: Dict[str, Any]) -> None:
        if not isinstance(event, dict):
            return

        if event.get("mode"):
            self.mode = str(event["mode"])
        if event.get("intent"):
            self.intent = str(event["intent"])
        if "extracted_info" in event and isinstance(event.get("extracted_info"), dict):
            self.extracted_info = sanitize_value(event["extracted_info"])
        if "missing_fields" in event and event.get("missing_fields") is not None:
            self.missing_fields = sanitize_value(event.get("missing_fields"))

        status = str(event.get("status") or "").lower()
        phase = str(event.get("phase") or "").lower()
        if event.get("requires_clarification"):
            self.status = "clarification"
        elif status == "failed" or phase == "error":
            self.status = "failed"
            self.error = str(event.get("error") or event.get("message") or self.error or "")
        elif (
            status == "completed"
            and self.status == "running"
            and (event.get("content") or event.get("event") == "final")
        ):
            self.status = "completed"

        self._record_first_content_from_event(event)
        self._record_final_data(event)
        self._record_agent_results(event)
        self._record_thinking_steps(event.get("thinking_steps") or [])

    def _record_first_content_from_event(self, event: Dict[str, Any]) -> None:
        content = event.get("content")
        if isinstance(content, str) and content:
            self.mark_first_token()

    def _record_final_data(self, event: Dict[str, Any]) -> None:
        if event.get("event") != "final" or not event.get("data"):
            return
        raw_data = event.get("data")
        parsed: Dict[str, Any]
        if isinstance(raw_data, str):
            try:
                parsed = json.loads(raw_data)
            except json.JSONDecodeError:
                parsed = {"content": raw_data}
        elif isinstance(raw_data, dict):
            parsed = raw_data
        else:
            parsed = {}
        if parsed.get("content"):
            self.mark_first_token()
        if "missing_fields" in parsed:
            self.missing_fields = sanitize_value(parsed.get("missing_fields"))
        if parsed.get("status") == "failed":
            self.status = "failed"

    def _record_agent_results(self, event: Dict[str, Any]) -> None:
        metrics = event.get("agent_metrics")
        if isinstance(metrics, dict):
            for name, metric in metrics.items():
                if isinstance(metric, dict):
                    self.record_agent_timing(
                        str(name),
                        metric.get("execution_time_ms"),
                        status=metric.get("status"),
                        tokens_used=metric.get("tokens_used"),
                        tool_calls_count=metric.get("tool_calls_count"),
                    )

        results = event.get("results")
        if isinstance(results, list):
            for item in results:
                if not isinstance(item, dict):
                    continue
                agent_name = item.get("agent") or item.get("agent_name")
                if agent_name:
                    self.add_selected_agents([str(agent_name)])
                    self.record_agent_timing(
                        str(agent_name),
                        item.get("execution_time_ms"),
                        status=item.get("status"),
                        success=item.get("success"),
                    )

    def _record_thinking_steps(self, steps: List[Any]) -> None:
        for step in steps:
            if not isinstance(step, dict):
                continue
            agent_name = step.get("agent") or step.get("agent_name")
            for tool_call in step.get("tool_calls") or []:
                if not isinstance(tool_call, dict):
                    continue
                self.record_tool_call(
                    name=str(tool_call.get("tool_name") or tool_call.get("name") or ""),
                    params=tool_call.get("arguments") or tool_call.get("params") or {},
                    duration_ms=tool_call.get("duration_ms"),
                    status=tool_call.get("status"),
                    error=tool_call.get("error"),
                    agent=str(agent_name) if agent_name else None,
                )
            for api_call in step.get("api_calls") or []:
                if not isinstance(api_call, dict):
                    continue
                self.record_api_call(
                    name=str(api_call.get("service") or api_call.get("name") or ""),
                    endpoint=api_call.get("endpoint"),
                    params=api_call.get("params") or {},
                    duration_ms=api_call.get("duration_ms"),
                    status=api_call.get("status"),
                    http_status=api_call.get("http_status"),
                    error=api_call.get("error"),
                    agent=str(agent_name) if agent_name else None,
                )

    def record_stage_timing(self, stage: str, duration_ms: Any, **metadata: Any) -> None:
        if duration_ms is None:
            return
        stage_name = str(stage)
        self.stage_timings[stage_name] = _round_ms(float(duration_ms)) or 0.0
        if stage_name in _AGENT_STAGE_NAMES:
            self.record_agent_timing(
                stage_name,
                duration_ms,
                status=metadata.get("status"),
                streamed=metadata.get("streamed"),
            )

    def record_agent_timing(
        self,
        agent_name: str,
        duration_ms: Any,
        *,
        status: Any = None,
        success: Optional[bool] = None,
        tokens_used: Any = None,
        tool_calls_count: Any = None,
        streamed: Any = None,
    ) -> None:
        if not agent_name:
            return
        self.add_selected_agents([agent_name])
        current = self.agent_timings.get(agent_name, {})
        if duration_ms is not None:
            current["duration_ms"] = _round_ms(float(duration_ms))
        if status is not None:
            current["status"] = str(status)
        inferred_success = _success_from_status(str(status) if status is not None else None, success)
        if inferred_success is not None:
            current["success"] = inferred_success
        if tokens_used is not None:
            current["tokens_used"] = tokens_used
        if tool_calls_count is not None:
            current["tool_calls_count"] = tool_calls_count
        if streamed is not None:
            current["streamed"] = bool(streamed)
        self.agent_timings[agent_name] = sanitize_value(current)

    def add_selected_agents(self, agents: List[str]) -> None:
        for agent in agents:
            if agent and agent not in self.selected_agents:
                self.selected_agents.append(agent)

    def set_route(self, route: Any) -> None:
        if route is not None:
            self.route = str(route)

    def set_intent_info(
        self,
        *,
        mode: Any = None,
        intent: Any = None,
        route: Any = None,
        extracted_info: Any = None,
        missing_fields: Any = None,
    ) -> None:
        if mode is not None:
            self.mode = str(mode)
        if intent is not None:
            self.intent = str(intent)
        if route is not None:
            self.route = str(route)
        if isinstance(extracted_info, dict):
            self.extracted_info = sanitize_value(extracted_info)
        if missing_fields is not None:
            self.missing_fields = sanitize_value(missing_fields)

    def finish_llm_call(
        self,
        call: Dict[str, Any],
        *,
        model: Any = None,
        usage: Optional[Dict[str, Any]] = None,
        success: bool = True,
        error: Any = None,
        fallback: Optional[bool] = None,
        mock: Optional[bool] = None,
        output_chars: Optional[int] = None,
        chunk_count: Optional[int] = None,
    ) -> None:
        duration_ms = (time.perf_counter() - call["started_at_perf"]) * 1000
        ttft_ms = call.get("ttft_ms")
        if ttft_ms is None and not call.get("streaming") and success:
            ttft_ms = duration_ms
        tokens = usage or {
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
        }
        entry = {
            "id": call["id"],
            "model": str(model or call.get("model") or "unknown"),
            "duration_ms": _round_ms(duration_ms),
            "ttft_ms": _round_ms(ttft_ms),
            "tokens": sanitize_value(tokens),
            "streaming": bool(call.get("streaming")),
            "mock": bool(call.get("mock") if mock is None else mock),
            "fallback": bool(call.get("fallback") if fallback is None else fallback),
            "success": bool(success),
            "message_count": call.get("message_count"),
            "message_chars": call.get("message_chars"),
            "tool_count": call.get("tool_count"),
        }
        if output_chars is not None:
            entry["output_chars"] = int(output_chars)
        if chunk_count is not None:
            entry["chunk_count"] = int(chunk_count)
        if error:
            entry["error"] = sanitize_value(str(error))
        self.llm_calls.append(entry)

    def record_tool_call(
        self,
        *,
        name: str,
        params: Any = None,
        duration_ms: Any = None,
        status: Any = None,
        success: Optional[bool] = None,
        error: Any = None,
        agent: Optional[str] = None,
    ) -> None:
        if not name:
            return
        entry = {
            "name": name,
            "agent": agent,
            "params": sanitize_value(params or {}),
            "duration_ms": _round_ms(float(duration_ms)) if duration_ms is not None else None,
            "status": str(status or ("completed" if success else "failed" if success is False else "unknown")),
            "success": _success_from_status(str(status) if status is not None else None, success),
            "error": sanitize_value(str(error)) if error else None,
        }
        key = _stable_json(entry)
        if key in self._tool_keys:
            return
        self._tool_keys.add(key)
        self.tool_calls.append({k: v for k, v in entry.items() if v is not None})

    def record_api_call(
        self,
        *,
        name: str,
        endpoint: Any = None,
        params: Any = None,
        duration_ms: Any = None,
        status: Any = None,
        success: Optional[bool] = None,
        http_status: Any = None,
        error: Any = None,
        agent: Optional[str] = None,
    ) -> None:
        if not name and not endpoint:
            return
        entry = {
            "name": name,
            "agent": agent,
            "endpoint": sanitize_value(endpoint),
            "params": sanitize_value(params or {}),
            "duration_ms": _round_ms(float(duration_ms)) if duration_ms is not None else None,
            "status": str(status or ("completed" if success else "failed" if success is False else "unknown")),
            "success": _success_from_status(str(status) if status is not None else None, success),
            "http_status": http_status,
            "error": sanitize_value(str(error)) if error else None,
        }
        key = _stable_json(entry)
        if key in self._api_keys:
            return
        self._api_keys.add(key)
        self.api_calls.append({k: v for k, v in entry.items() if v is not None})

    def record_error(self, error: BaseException | str, *, status: str = "failed") -> None:
        self.status = status
        self.error = sanitize_value(str(error))

    def to_record(self) -> Dict[str, Any]:
        return {
            "schema_version": TRACE_SCHEMA_VERSION,
            "created_at": self.started_at,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "status": self.status,
            "mode": self.mode,
            "intent": self.intent,
            "route": self.route,
            "extracted_info": self.extracted_info,
            "missing_fields": self.missing_fields,
            "selected_agents": self.selected_agents,
            "stage_timings": self.stage_timings,
            "agent_timings": self.agent_timings,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "api_calls": self.api_calls,
            "total_duration_ms": self.total_duration_ms,
            "first_token_ms": self.first_token_ms,
            "error": self.error,
        }

    def finish(self) -> Optional[Path]:
        if self._finished:
            return Path(self.trace_file) if self.trace_file else None
        self._finished = True
        if self.status == "running":
            self.status = "completed"
        self.total_duration_ms = _round_ms((time.perf_counter() - self.started_at_perf) * 1000)
        record = sanitize_value(self.to_record())
        trace_dir = get_trace_dir()
        trace_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        filename = f"{timestamp}_{_safe_filename_part(self.request_id)}_{uuid.uuid4().hex[:8]}.jsonl"
        path = trace_dir / filename
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp_path.replace(path)
        self.trace_file = str(path)
        return path


def start_request_trace(request_id: str, session_id: str) -> tuple[Optional[TraceState], Optional[Token]]:
    if not is_tracing_enabled():
        return None, None
    existing = get_current_trace()
    if existing is not None:
        return existing, None
    trace = TraceState(request_id=str(request_id), session_id=str(session_id))
    token = _current_trace.set(trace)
    return trace, token


def finish_request_trace(token: Optional[Token] = None) -> Optional[Path]:
    trace = get_current_trace()
    path: Optional[Path] = None
    try:
        if trace is not None:
            path = trace.finish()
    except Exception as exc:
        logger.exception("Failed to write request trace: %s", exc)
    finally:
        if token is not None:
            _current_trace.reset(token)
    return path


@contextmanager
def request_trace(request_id: str, session_id: str) -> Iterator[Optional[TraceState]]:
    trace, token = start_request_trace(request_id, session_id)
    try:
        yield trace
    except BaseException as exc:
        if trace is not None:
            if isinstance(exc, asyncio.CancelledError):
                trace.record_error(exc, status="cancelled")
            else:
                trace.record_error(exc, status="failed")
        raise
    finally:
        if token is not None:
            finish_request_trace(token)


def record_trace_event(event: Dict[str, Any]) -> None:
    trace = get_current_trace()
    if trace is not None:
        trace.record_event(event)


def record_stage_timing(stage: str, duration_ms: Any, **metadata: Any) -> None:
    trace = get_current_trace()
    if trace is not None:
        trace.record_stage_timing(stage, duration_ms, **metadata)


def record_agent_timing(agent_name: str, duration_ms: Any, **metadata: Any) -> None:
    trace = get_current_trace()
    if trace is not None:
        trace.record_agent_timing(agent_name, duration_ms, **metadata)


def set_trace_route(route: Any) -> None:
    trace = get_current_trace()
    if trace is not None:
        trace.set_route(route)


def set_trace_intent_info(**kwargs: Any) -> None:
    trace = get_current_trace()
    if trace is not None:
        trace.set_intent_info(**kwargs)


def set_trace_selected_agents(agents: List[str]) -> None:
    trace = get_current_trace()
    if trace is not None:
        trace.add_selected_agents(agents)


def start_llm_call(
    *,
    model: Any = None,
    streaming: bool = False,
    mock: bool = False,
    fallback: bool = False,
    message_count: Optional[int] = None,
    message_chars: Optional[int] = None,
    tool_count: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    if get_current_trace() is None:
        return None
    return {
        "id": uuid.uuid4().hex,
        "started_at_perf": time.perf_counter(),
        "model": model,
        "streaming": streaming,
        "mock": mock,
        "fallback": fallback,
        "message_count": message_count,
        "message_chars": message_chars,
        "tool_count": tool_count,
        "ttft_ms": None,
    }


def mark_llm_first_token(call: Optional[Dict[str, Any]]) -> None:
    if call is None or call.get("ttft_ms") is not None:
        return
    call["ttft_ms"] = (time.perf_counter() - call["started_at_perf"]) * 1000


def finish_llm_call(
    call: Optional[Dict[str, Any]],
    *,
    model: Any = None,
    usage: Optional[Dict[str, Any]] = None,
    success: bool = True,
    error: Any = None,
    fallback: Optional[bool] = None,
    mock: Optional[bool] = None,
    output_chars: Optional[int] = None,
    chunk_count: Optional[int] = None,
) -> None:
    trace = get_current_trace()
    if trace is not None and call is not None:
        trace.finish_llm_call(
            call,
            model=model,
            usage=usage,
            success=success,
            error=error,
            fallback=fallback,
            mock=mock,
            output_chars=output_chars,
            chunk_count=chunk_count,
        )


def record_tool_call(
    name: str,
    *,
    params: Any = None,
    duration_ms: Any = None,
    status: Any = None,
    success: Optional[bool] = None,
    error: Any = None,
    agent: Optional[str] = None,
) -> None:
    trace = get_current_trace()
    if trace is not None:
        trace.record_tool_call(
            name=name,
            params=params,
            duration_ms=duration_ms,
            status=status,
            success=success,
            error=error,
            agent=agent,
        )


def record_api_call(
    name: str,
    *,
    endpoint: Any = None,
    params: Any = None,
    duration_ms: Any = None,
    status: Any = None,
    success: Optional[bool] = None,
    http_status: Any = None,
    error: Any = None,
    agent: Optional[str] = None,
) -> None:
    trace = get_current_trace()
    if trace is not None:
        trace.record_api_call(
            name=name,
            endpoint=endpoint,
            params=params,
            duration_ms=duration_ms,
            status=status,
            success=success,
            http_status=http_status,
            error=error,
            agent=agent,
        )
