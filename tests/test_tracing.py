import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.orchestrator import AgentOrchestrator
from app.agents.base import AgentCapability, AgentConfig, AgentResponse, AgentStatus, BaseAgent
from app.core.context import ExecutionContext, SessionContext
from app.core.llm.client import BaseLLMClient, LLMManager, LLMMessage, LLMResponse
from app.core.llm.manager import EnhancedLLMManager, LLMCallMetrics, SimpleLLMCache
from app.main import TourismSystemApp
from app.core.tracing import (
    REDACTED,
    record_api_call,
    record_tool_call,
    request_trace,
    trace_component,
)
from app.schemas import DialogMode, IntentType


def _trace_records(trace_dir: Path) -> list[dict]:
    records: list[dict] = []
    for path in trace_dir.glob("*.jsonl"):
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        records.append(json.loads(lines[0]))
    return records


def test_tracing_disabled_writes_no_jsonl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ENABLE_TRACING", "false")
    monkeypatch.setenv("TRACE_OUTPUT_DIR", str(tmp_path))

    with request_trace("disabled-request", "disabled-session") as trace:
        assert trace is None
        record_tool_call("demo", params={"api_key": "secret"})

    assert list(tmp_path.glob("*.jsonl")) == []


def test_tracing_enabled_writes_valid_jsonl_and_redacts_sensitive_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ENABLE_TRACING", "true")
    monkeypatch.setenv("TRACE_OUTPUT_DIR", str(tmp_path))

    with request_trace("enabled-request", "session-1") as trace:
        assert trace is not None
        trace.set_intent_info(
            mode="planning",
            intent="trip_planning",
            route="FULL_NEW_PLAN",
            extracted_info={
                "destination": "Hangzhou",
                "api_key": "plain-secret",
                "nested": {"Authorization": "Bearer token-value"},
            },
            missing_fields=["budget"],
        )
        trace.record_stage_timing("intent_parsing", 12.345)
        record_tool_call(
            "poi_search",
            params={"key": "amap-secret", "city": "Hangzhou"},
            duration_ms=7.5,
            status="completed",
        )
        record_api_call(
            "amap",
            endpoint="/v3/place/text",
            params={"token": "api-token", "keywords": "lake"},
            duration_ms=9.0,
            status="completed",
            http_status=200,
        )

    records = _trace_records(tmp_path)
    assert len(records) == 1
    record = records[0]
    raw = json.dumps(record, ensure_ascii=False)
    assert record["request_id"] == "enabled-request"
    assert record["session_id"] == "session-1"
    assert record["status"] == "completed"
    assert record["extracted_info"]["api_key"] == REDACTED
    assert record["extracted_info"]["nested"]["Authorization"] == REDACTED
    assert record["tool_calls"][0]["params"]["key"] == REDACTED
    assert record["api_calls"][0]["params"]["token"] == REDACTED
    assert "plain-secret" not in raw
    assert "amap-secret" not in raw
    assert "api-token" not in raw
    assert "token-value" not in raw


def test_contextvar_isolates_concurrent_traces(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ENABLE_TRACING", "true")
    monkeypatch.setenv("TRACE_OUTPUT_DIR", str(tmp_path))

    async def run_one(request_id: str, destination: str) -> None:
        with request_trace(request_id, f"{request_id}-session") as trace:
            assert trace is not None
            trace.set_intent_info(extracted_info={"destination": destination})
            await asyncio.sleep(0.01)
            record_tool_call("lookup", params={"destination": destination}, status="completed")

    async def run_all() -> None:
        await asyncio.gather(run_one("req-a", "A"), run_one("req-b", "B"))

    asyncio.run(run_all())

    records = sorted(_trace_records(tmp_path), key=lambda item: item["request_id"])
    assert [record["request_id"] for record in records] == ["req-a", "req-b"]
    assert records[0]["extracted_info"]["destination"] == "A"
    assert records[0]["tool_calls"][0]["params"]["destination"] == "A"
    assert records[1]["extracted_info"]["destination"] == "B"
    assert records[1]["tool_calls"][0]["params"]["destination"] == "B"


def test_orchestrator_trace_records_clarification_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ENABLE_TRACING", "true")
    monkeypatch.setenv("TRACE_OUTPUT_DIR", str(tmp_path))

    orchestrator = AgentOrchestrator(object())
    session = SessionContext(session_id="clarify-session")

    monkeypatch.setattr(
        orchestrator,
        "_fast_intent_parse",
        lambda user_message, current_session: (
            IntentType.TRIP_PLANNING,
            {"destination": "Hangzhou", "duration": 3},
        ),
    )

    async def run_process() -> None:
        async for _event in orchestrator.process(
            session,
            "plan Hangzhou for 3 days",
            request_id="clarify-request",
            forced_mode=DialogMode.PLANNING,
        ):
            pass

    asyncio.run(run_process())

    records = _trace_records(tmp_path)
    assert len(records) == 1
    record = records[0]
    assert record["request_id"] == "clarify-request"
    assert record["status"] == "clarification"
    assert record["intent"] == "trip_planning"
    assert record["route"] in {"FULL_NEW_PLAN", "FOLLOW_UP", "GENERAL_CHAT", "CLARIFICATION_ANSWER"}
    assert record["missing_fields"]


def test_trace_records_exception_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ENABLE_TRACING", "true")
    monkeypatch.setenv("TRACE_OUTPUT_DIR", str(tmp_path))

    with pytest.raises(ValueError):
        with request_trace("error-request", "error-session"):
            raise ValueError("boom token=secret")

    records = _trace_records(tmp_path)
    assert len(records) == 1
    assert records[0]["status"] == "failed"
    assert "boom" in records[0]["error"]


class _FakeStreamClient(BaseLLMClient):
    model = "fake-stream-model"

    async def chat(self, messages, tools=None, **kwargs):
        return LLMResponse(
            content="done",
            model=self.model,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            finish_reason="stop",
        )

    async def stream(self, messages, tools=None, **kwargs):
        await asyncio.sleep(0.01)
        yield "first"
        yield "second"

    async def embeddings(self, texts):
        return [[0.0] for _ in texts]


class _FailingClient(BaseLLMClient):
    model = "failing-primary"

    async def chat(self, messages, tools=None, **kwargs):
        raise RuntimeError("primary unavailable")

    async def stream(self, messages, tools=None, **kwargs):
        raise RuntimeError("primary stream unavailable")
        yield ""

    async def embeddings(self, texts):
        return [[0.0] for _ in texts]


class _TraceAgent(BaseAgent):
    def __init__(self, name: str, behavior: str = "success", timeout_seconds: float = 1.0):
        super().__init__(
            AgentConfig(
                name=name,
                description="trace test agent",
                instructions="trace test agent",
                capabilities=[AgentCapability.EXECUTION],
                timeout_seconds=timeout_seconds,
            ),
            llm=None,
        )
        self.behavior = behavior

    async def plan(self, session: SessionContext, context: ExecutionContext):
        return ["run"]

    async def execute(self, session: SessionContext, context: ExecutionContext):
        if self.behavior == "fail":
            raise ValueError("agent boom")
        if self.behavior == "timeout":
            await asyncio.sleep(0.2)
        if self.behavior == "cancel":
            await asyncio.sleep(10)
        return AgentResponse(
            agent_name=self.name,
            status=AgentStatus.COMPLETED,
            content="ok",
            tokens_used=7,
        )


def _execution_context(request_id: str = "agent-request") -> ExecutionContext:
    return ExecutionContext(request_id=request_id, session_id="agent-session")


class _CaptureOrchestrator:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def process(self, session, text, request_id, **kwargs):
        self.calls.append((session.session_id, request_id))
        yield {"phase": "response_synthesis", "status": "completed", "content": "ok"}


def test_llm_stream_trace_records_ttft(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ENABLE_TRACING", "true")
    monkeypatch.setenv("TRACE_OUTPUT_DIR", str(tmp_path))

    manager = LLMManager.__new__(LLMManager)
    manager._client = _FakeStreamClient()

    async def run_stream() -> str:
        with request_trace("ttft-request", "ttft-session"):
            chunks = []
            async for chunk in manager.stream([LLMMessage(role="user", content="hello")]):
                chunks.append(chunk)
            return "".join(chunks)

    assert asyncio.run(run_stream()) == "firstsecond"

    records = _trace_records(tmp_path)
    assert len(records) == 1
    llm_call = records[0]["llm_calls"][0]
    assert llm_call["model"] == "fake-stream-model"
    assert llm_call["streaming"] is True
    assert llm_call["success"] is True
    assert llm_call["ttft_ms"] is not None
    assert llm_call["ttft_ms"] <= llm_call["duration_ms"]
    assert llm_call["chunk_count"] == 2


def test_same_session_two_requests_get_distinct_request_ids(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ENABLE_TRACING", "true")
    monkeypatch.setenv("TRACE_OUTPUT_DIR", str(tmp_path))

    orchestrator = AgentOrchestrator(object())
    session = SessionContext(session_id="same-session")

    async def drain(message: str) -> None:
        async for _event in orchestrator.process(session, message):
            pass

    asyncio.run(drain(""))
    asyncio.run(drain(""))

    records = _trace_records(tmp_path)
    assert len(records) == 2
    assert {record["session_id"] for record in records} == {"same-session"}
    assert len({record["request_id"] for record in records}) == 2


def test_cli_core_generates_distinct_request_ids_for_same_session() -> None:
    fake_orchestrator = _CaptureOrchestrator()
    app = TourismSystemApp()
    app.llm = object()
    app.orchestrator = fake_orchestrator

    app.handle_query("hello", session_id="cli-same-session")
    app.handle_query("again", session_id="cli-same-session")

    assert [session_id for session_id, _ in fake_orchestrator.calls] == [
        "cli-same-session",
        "cli-same-session",
    ]
    assert fake_orchestrator.calls[0][1] != fake_orchestrator.calls[1][1]


def test_llm_call_records_component_attribution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ENABLE_TRACING", "true")
    monkeypatch.setenv("TRACE_OUTPUT_DIR", str(tmp_path))

    manager = LLMManager.__new__(LLMManager)
    manager._client = _FakeStreamClient()

    async def run_chat() -> None:
        with request_trace("component-request", "component-session"):
            with trace_component("IntentParser"):
                await manager.chat([LLMMessage(role="user", content="hello")])

    asyncio.run(run_chat())

    llm_call = _trace_records(tmp_path)[0]["llm_calls"][0]
    assert llm_call["component"] == "IntentParser"
    assert llm_call["agent_name"] is None
    assert llm_call["call_id"]
    assert llm_call["provider"]


def test_agent_failure_timeout_cancel_and_repeated_runs_are_recorded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ENABLE_TRACING", "true")
    monkeypatch.setenv("TRACE_OUTPUT_DIR", str(tmp_path))
    session = SessionContext(session_id="agent-session")

    async def run_agents() -> None:
        with request_trace("agent-request", session.session_id):
            success_agent = _TraceAgent("repeat_agent")
            await success_agent.run(session, _execution_context())
            await success_agent.run(session, _execution_context())

            failed = await _TraceAgent("failed_agent", "fail").run(session, _execution_context())
            assert failed.status == AgentStatus.FAILED

            timed_out = await _TraceAgent("timeout_agent", "timeout", timeout_seconds=0.01).run(
                session,
                _execution_context(),
            )
            assert timed_out.status == AgentStatus.FAILED

            task = asyncio.create_task(
                _TraceAgent("cancel_agent", "cancel").run(session, _execution_context())
            )
            await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(run_agents())

    record = _trace_records(tmp_path)[0]
    runs = record["agent_runs"]
    repeat_runs = [run for run in runs if run["agent_name"] == "repeat_agent"]
    assert len(repeat_runs) == 2
    assert repeat_runs[0]["agent_run_id"] != repeat_runs[1]["agent_run_id"]

    by_agent = {run["agent_name"]: run for run in runs if run["agent_name"] != "repeat_agent"}
    assert by_agent["failed_agent"]["status"] == "failed"
    assert by_agent["failed_agent"]["error"]
    assert by_agent["timeout_agent"]["status"] == "timeout"
    assert by_agent["timeout_agent"]["duration_ms"] is not None
    assert by_agent["cancel_agent"]["status"] == "cancelled"


def test_llm_cache_hit_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ENABLE_TRACING", "true")
    monkeypatch.setenv("TRACE_OUTPUT_DIR", str(tmp_path))
    monkeypatch.delenv("EXPERIMENT_DISABLE_CACHE", raising=False)

    manager = EnhancedLLMManager.__new__(EnhancedLLMManager)
    manager._client = _FakeStreamClient()
    manager._mock_client = _FakeStreamClient()
    manager._using_mock = False
    manager.metrics = LLMCallMetrics()
    manager._cache = SimpleLLMCache(ttl_seconds=300)

    async def run_cached() -> None:
        messages = [LLMMessage(role="user", content="cache me")]
        with request_trace("cache-request", "cache-session"):
            await manager.chat(messages)
            await manager.chat(messages)

    asyncio.run(run_cached())

    calls = _trace_records(tmp_path)[0]["llm_calls"]
    assert len(calls) == 2
    assert calls[0]["cache_hit"] is False
    assert calls[1]["cache_hit"] is True


def test_progress_events_do_not_count_as_body_ttft(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ENABLE_TRACING", "true")
    monkeypatch.setenv("TRACE_OUTPUT_DIR", str(tmp_path))

    with request_trace("ttft-body-request", "ttft-body-session") as trace:
        assert trace is not None
        trace.record_event(
            {
                "type": "phase_update",
                "phase": "intent_parsing",
                "status": "running",
                "content": "正在分析您的意图...",
                "content_kind": "none",
            }
        )
        assert trace.first_body_token_ms is None
        trace.record_event(
            {
                "type": "streaming",
                "phase": "response_synthesis",
                "status": "running",
                "content": "正文",
                "content_kind": "delta",
                "is_streaming": True,
            }
        )
        assert trace.first_body_token_ms is not None

    record = _trace_records(tmp_path)[0]
    assert record["first_body_token_ms"] is not None


def test_mock_fallback_and_strict_mode_are_recorded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ENABLE_TRACING", "true")
    monkeypatch.setenv("TRACE_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("EXPERIMENT_STRICT_MODE", "false")

    manager = LLMManager.__new__(LLMManager)
    manager._client = _FailingClient()

    async def run_fallback() -> None:
        with request_trace("fallback-request", "fallback-session"):
            response = await manager.chat([LLMMessage(role="user", content="hello")])
            assert response.model == "mock-model"

    asyncio.run(run_fallback())

    fallback_call = _trace_records(tmp_path)[0]["llm_calls"][0]
    assert fallback_call["success"] is True
    assert fallback_call["fallback_used"] is True
    assert fallback_call["mock_used"] is True

    strict_dir = tmp_path / "strict"
    monkeypatch.setenv("TRACE_OUTPUT_DIR", str(strict_dir))
    monkeypatch.setenv("EXPERIMENT_STRICT_MODE", "true")
    manager = LLMManager.__new__(LLMManager)
    manager._client = _FailingClient()

    async def run_strict() -> None:
        with request_trace("strict-request", "strict-session"):
            with pytest.raises(RuntimeError):
                await manager.chat([LLMMessage(role="user", content="hello")])

    asyncio.run(run_strict())

    strict_call = _trace_records(strict_dir)[0]["llm_calls"][0]
    assert strict_call["success"] is False
    assert strict_call["fallback_used"] is False
    assert strict_call["mock_used"] is False
