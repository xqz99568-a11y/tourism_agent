import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.attraction import AttractionAgent
from app.agents.orchestrator import AgentOrchestrator
from app.agents.base import AgentCapability, AgentConfig, AgentResponse, AgentStatus, BaseAgent
from app.core.context import ExecutionContext, SessionContext
from app.core.llm.client import BaseLLMClient, LLMManager, LLMMessage, LLMResponse, MockLLMClient
from app.core.llm.manager import EnhancedLLMManager, LLMCallMetrics, SimpleLLMCache
from app.core.tool_executor import ToolExecutor
from app.main import TourismSystemApp
from app.core.tracing import (
    REDACTED,
    record_api_call,
    record_selected_tool,
    record_tool_call,
    request_trace,
    trace_component,
)
from app.scripts.summarize_traces import summarize
from app.schemas import DialogMode, IntentType
from app.tools.base import ToolResult


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
                "tokens": "plural-secret",
                "nested": {"Authorization": "Bearer token-value"},
            },
            missing_fields=["budget"],
        )
        trace.record_stage_timing("intent_parsing", 12.345)
        record_selected_tool("poi_search")
        record_tool_call(
            "poi_search",
            params={"key": "amap-secret", "city": "Hangzhou", "tokens": "plural-tool-secret"},
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
    assert record["extracted_info"]["tokens"] == REDACTED
    assert record["extracted_info"]["nested"]["Authorization"] == REDACTED
    assert record["tool_calls"][0]["params"]["key"] == REDACTED
    assert record["tool_calls"][0]["params"]["tokens"] == REDACTED
    assert record["api_calls"][0]["params"]["token"] == REDACTED
    assert "plain-secret" not in raw
    assert "amap-secret" not in raw
    assert "api-token" not in raw
    assert "token-value" not in raw
    assert "plural-secret" not in raw
    assert "plural-tool-secret" not in raw
    assert record["schema_version"] == "1.7"
    assert "input_hash" in record
    assert "result_hash" in record
    assert "offline_data" in record
    assert record["planned_tools"] == ["poi_search"]
    assert record["executed_tools"] == ["poi_search"]
    assert record["selected_tools"] == ["poi_search"]
    assert record["goal"]["intent"] == "trip_planning"
    assert record["goal"]["route"] == "FULL_NEW_PLAN"
    assert record["goal"]["slots"]["destination"] == "Hangzhou"
    assert record["tool_call_count"] == 1
    assert record["selected_tool_count"] == 1
    assert record["api_call_count"] == 1
    assert record["llm_call_count"] == 0


def test_trace_defaults_goal_and_records_selected_tools_without_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ENABLE_TRACING", "true")
    monkeypatch.setenv("TRACE_OUTPUT_DIR", str(tmp_path))

    with request_trace("default-goal-request", "default-goal-session") as trace:
        assert trace is not None
        trace.set_intent_info(intent="unknown", route="unknown", extracted_info={"topic": "hello"})
        record_selected_tool("weather")

    record = _trace_records(tmp_path)[0]
    assert record["intent"] == "general_chat"
    assert record["route"] == "GENERAL_CHAT"
    assert record["selected_agents"] == []
    assert record["planned_tools"] == ["weather"]
    assert record["executed_tools"] == []
    assert record["selected_tools"] == ["weather"]
    assert record["tool_call_count"] == 0
    assert record["selected_tool_count"] == 1
    assert record["goal"] == {
        "intent": "general_chat",
        "route": "GENERAL_CHAT",
        "slots": {"topic": "hello"},
        "constraints": [],
        "planned_agents": [],
        "selected_agents": [],
    }


def test_start_agent_run_records_execution_without_changing_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ENABLE_TRACING", "true")
    monkeypatch.setenv("TRACE_OUTPUT_DIR", str(tmp_path))

    with request_trace("agent-run-request", "agent-run-session") as trace:
        assert trace is not None
        trace.start_agent_run("runtime-only-agent")

    record = _trace_records(tmp_path)[0]
    assert record["planned_agents"] == []
    assert record["executed_agents"] == ["runtime-only-agent"]
    assert record["selected_agents"] == []


def test_tool_executor_records_tool_trace_and_success_rate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ENABLE_TRACING", "true")
    monkeypatch.setenv("TRACE_OUTPUT_DIR", str(tmp_path))

    class DemoTool:
        name = "demo_tool"
        description = "Demo tool"
        parameters = {"required": ["value"]}

        def validate_params(self, params):
            return "value" in params

        async def execute(self, **kwargs):
            return ToolResult(success=True, data={"echo": kwargs["value"]})

    async def run_tools() -> None:
        executor = ToolExecutor(tools={"demo_tool": DemoTool()})
        with request_trace("executor-tool-request", "executor-tool-session"):
            ok = await executor.execute("demo_tool", {"value": "杭州"}, call_id="tool-ok")
            missing = await executor.execute("missing_tool", {}, call_id="tool-missing")
            invalid = await executor.execute("demo_tool", {}, call_id="tool-invalid")
            assert ok.is_completed
            assert missing.is_failed
            assert invalid.is_failed

    asyncio.run(run_tools())

    record = _trace_records(tmp_path)[0]
    assert record["planned_tools"] == []
    assert record["executed_tools"] == ["demo_tool", "missing_tool"]
    assert record["selected_tools"] == []
    assert record["tool_call_count"] == 3
    assert record["successful_tool_call_count"] == 1
    assert record["failed_tool_call_count"] == 2
    assert record["tool_call_success_rate"] == pytest.approx(1 / 3, abs=0.0001)
    assert [call["call_id"] for call in record["tool_calls"]] == ["tool-ok", "tool-missing", "tool-invalid"]
    assert [call["success"] for call in record["tool_calls"]] == [True, False, False]
    assert [call["name"] for call in record["tool_calls"]] == ["demo_tool", "missing_tool", "demo_tool"]


def test_thinking_steps_tool_and_api_calls_are_recorded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ENABLE_TRACING", "true")
    monkeypatch.setenv("TRACE_OUTPUT_DIR", str(tmp_path))

    with request_trace("thinking-request", "thinking-session") as trace:
        assert trace is not None
        trace.record_event(
            {
                "thinking_steps": [
                    {
                        "agent": "Planner",
                        "tool_calls": [
                            {
                                "call_id": "tool-step-1",
                                "tool_name": "poi_search",
                                "arguments": {"keywords": "lake"},
                                "status": "completed",
                                "cost_ms": 4.5,
                                "component": "planner.tool",
                                "cache_hit": False,
                                "fallback_used": False,
                            }
                        ],
                        "api_calls": [
                            {
                                "call_id": "api-step-1",
                                "service": "amap",
                                "endpoint": "/v3/place/text",
                                "params": {"keywords": "lake"},
                                "status": "failed",
                                "success": False,
                                "http_status": 429,
                                "error": "rate limited",
                                "cost_ms": 6.75,
                                "component": "planner.api",
                                "cache_hit": False,
                                "fallback_used": True,
                            }
                        ],
                    }
                ]
            }
        )

    record = _trace_records(tmp_path)[0]
    tool_call = record["tool_calls"][0]
    assert tool_call["call_id"] == "tool-step-1"
    assert tool_call["agent_name"] == "Planner"
    assert tool_call["component"] == "planner.tool"
    assert tool_call["name"] == "poi_search"
    assert tool_call["params"] == {"keywords": "lake"}
    assert tool_call["duration_ms"] == 4.5
    assert tool_call["cache_hit"] is False

    api_call = record["api_calls"][0]
    assert api_call["call_id"] == "api-step-1"
    assert api_call["agent_name"] == "Planner"
    assert api_call["component"] == "planner.api"
    assert api_call["name"] == "amap"
    assert api_call["endpoint"] == "/v3/place/text"
    assert api_call["duration_ms"] == 6.75
    assert api_call["http_status"] == 429
    assert api_call["success"] is False
    assert api_call["error"] == "rate limited"
    assert api_call["fallback_used"] is True


def test_tool_api_cost_ms_and_call_id_dedupe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ENABLE_TRACING", "true")
    monkeypatch.setenv("TRACE_OUTPUT_DIR", str(tmp_path))

    with request_trace("dedupe-request", "dedupe-session"):
        record_tool_call(
            "poi_search",
            call_id="same-tool-call",
            params={"keywords": "same"},
            status="running",
        )
        record_tool_call(
            "poi_search",
            call_id="same-tool-call",
            params={"keywords": "same"},
            duration_ms=5.25,
            status="completed",
            cache_hit=False,
        )
        record_tool_call(
            "poi_search",
            call_id="tool-call-a",
            params={"keywords": "same"},
            status="completed",
        )
        record_tool_call(
            "poi_search",
            call_id="tool-call-b",
            params={"keywords": "same"},
            status="completed",
        )
        record_api_call(
            "amap",
            call_id="api-cost-call",
            endpoint="/v3/place/text",
            params={"keywords": "same"},
            cost_ms=12.5,
            status="completed",
            http_status=200,
            agent="Attraction",
            component="poi_search",
            cache_hit=True,
            fallback_used=True,
        )
        record_api_call(
            "amap",
            call_id="api-cost-call",
            endpoint="/v3/place/text",
            params={"keywords": "same"},
            status="completed",
            http_status=200,
        )

    record = _trace_records(tmp_path)[0]
    tool_calls = record["tool_calls"]
    assert [call["call_id"] for call in tool_calls].count("same-tool-call") == 1
    assert len(tool_calls) == 3
    assert {call["call_id"] for call in tool_calls} == {
        "same-tool-call",
        "tool-call-a",
        "tool-call-b",
    }

    same_call = next(call for call in tool_calls if call["call_id"] == "same-tool-call")
    assert same_call["status"] == "completed"
    assert same_call["duration_ms"] == 5.25
    assert same_call["cache_hit"] is False

    api_calls = record["api_calls"]
    assert len(api_calls) == 1
    assert api_calls[0]["duration_ms"] == 12.5
    assert api_calls[0]["duration"] == 12.5
    assert api_calls[0]["agent_name"] == "Attraction"
    assert api_calls[0]["component"] == "poi_search"
    assert api_calls[0]["cache_hit"] is True
    assert api_calls[0]["fallback_used"] is True
    assert api_calls[0]["http_status"] == 200
    assert record["tool_call_count"] == 3
    assert record["api_call_count"] == 1
    assert record["cache_hit_count"] == 1
    assert record["fallback_count"] == 1


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


def test_trace_summary_includes_stage_percentiles_and_slowest_modules(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ENABLE_TRACING", "true")
    monkeypatch.setenv("TRACE_OUTPUT_DIR", str(tmp_path))

    for index, planner_ms in enumerate([100.0, 200.0, 300.0]):
        with request_trace(f"summary-request-{index}", "summary-session") as trace:
            assert trace is not None
            trace.record_stage_timing("intent_parsing", 10.0)
            trace.record_stage_timing("planner", planner_ms)
            record_tool_call("poi_search", status="completed", cache_hit=index == 0)
            record_api_call("amap", status="completed", fallback_used=index == 1)

    summary = summarize(tmp_path)

    assert summary["trace_count"] == 3
    assert summary["unique_request_count"] == 3
    assert summary["stage_timings"]["planner"] == {
        "mean": 200.0,
        "p50": 200.0,
        "p90": 300.0,
        "p95": 300.0,
    }
    assert summary["slowest_stage_by_mean_ms"] == {"name": "planner", "mean_ms": 200.0}
    assert summary["slowest_agent_by_mean_ms"] == {"name": "planner", "mean_ms": 200.0}
    assert summary["tool_call_count"] == 3
    assert summary["api_call_count"] == 3
    assert summary["cache_hit_count"] == 1
    assert summary["fallback_count"] == 1


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
    assert calls[0]["tokens"] == {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
    assert calls[1]["tokens"] == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    assert calls[1]["cached_source_usage"] == {
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "total_tokens": 2,
    }


def test_strict_mode_rejects_already_initialized_mock_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ENABLE_TRACING", "true")
    monkeypatch.setenv("TRACE_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("EXPERIMENT_STRICT_MODE", "true")

    chat_manager = LLMManager.__new__(LLMManager)
    chat_manager._client = MockLLMClient()

    stream_manager = EnhancedLLMManager.__new__(EnhancedLLMManager)
    stream_manager._client = MockLLMClient()
    stream_manager._mock_client = stream_manager._client
    stream_manager._using_mock = True
    stream_manager.metrics = LLMCallMetrics()
    stream_manager._cache = SimpleLLMCache(ttl_seconds=300)

    async def run_mock_calls() -> None:
        with request_trace("strict-mock-request", "strict-mock-session"):
            with pytest.raises(RuntimeError):
                await chat_manager.chat([LLMMessage(role="user", content="hello")])
            with pytest.raises(RuntimeError):
                async for _chunk in stream_manager.stream([LLMMessage(role="user", content="hello")]):
                    pass

    asyncio.run(run_mock_calls())

    calls = _trace_records(tmp_path)[0]["llm_calls"]
    assert len(calls) == 2
    assert [call["streaming"] for call in calls] == [False, True]
    for call in calls:
        assert call["success"] is False
        assert call["mock_used"] is True
        assert call["fallback_used"] is False
        assert "EXPERIMENT_STRICT_MODE" in call["error"]


class _FakePOISearchTool:
    external_service = "amap"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def execute(self, **kwargs) -> ToolResult:
        self.calls.append(dict(kwargs))
        return ToolResult(
            success=True,
            data=[
                {
                    "id": "poi-west-lake",
                    "name": "West Lake",
                    "address": "Hangzhou",
                    "type": "scenic",
                }
            ],
            api_calls=[
                {
                    "call_id": f"amap-search-{len(self.calls)}",
                    "service": self.external_service,
                    "endpoint": "/v3/place/text",
                    "params": dict(kwargs),
                    "status": "completed",
                    "success": True,
                    "http_status": 200,
                    "cost_ms": 11.25,
                    "cache_hit": False,
                }
            ],
        )


def test_attraction_simulated_poi_search_trace_records_cache_hit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ENABLE_TRACING", "true")
    monkeypatch.setenv("TRACE_OUTPUT_DIR", str(tmp_path))

    agent = AttractionAgent(llm=None)
    fake_tool = _FakePOISearchTool()
    agent.poi_search_tool = fake_tool
    context = ExecutionContext(request_id="attraction-request", session_id="attraction-session")
    raw_steps: list[dict] = []
    original_add_thinking_step = context.add_thinking_step

    def capture_thinking_step(**kwargs):
        raw_steps.append(
            {
                "agent": kwargs.get("agent_name"),
                "step": kwargs.get("step"),
                "status": kwargs.get("status"),
                "tool_calls": kwargs.get("tool_calls") or [],
                "api_calls": kwargs.get("api_calls") or [],
            }
        )
        return original_add_thinking_step(**kwargs)

    context.add_thinking_step = capture_thinking_step  # type: ignore[method-assign]
    request_cache = {"poi_search": {}, "poi_detail": {}}

    async def run_searches() -> None:
        with request_trace("attraction-request", "attraction-session") as trace:
            assert trace is not None
            first = await agent._search_candidates_concurrent(
                context,
                "Hangzhou",
                ["lake"],
                request_cache,
            )
            second = await agent._search_candidates_concurrent(
                context,
                "Hangzhou",
                ["lake"],
                request_cache,
            )
            assert len(first) == 1
            assert len(second) == 1
            trace.record_event({"thinking_steps": raw_steps})

    asyncio.run(run_searches())

    assert fake_tool.calls == [{"keywords": "lake", "city": "Hangzhou", "limit": 8}]
    record = _trace_records(tmp_path)[0]
    tool_calls = record["tool_calls"]
    assert len(tool_calls) == 2
    assert [call["agent_name"] for call in tool_calls] == ["Attraction", "Attraction"]
    assert [call["name"] for call in tool_calls] == ["poi_search", "poi_search"]
    assert [call["params"] for call in tool_calls] == [
        {"keywords": "lake", "city": "Hangzhou", "limit": 8},
        {"keywords": "lake", "city": "Hangzhou", "limit": 8},
    ]
    assert [call["cache_hit"] for call in tool_calls] == [False, True]
    assert len({call["call_id"] for call in tool_calls}) == 2

    api_calls = record["api_calls"]
    assert len(api_calls) == 1
    assert api_calls[0]["agent_name"] == "Attraction"
    assert api_calls[0]["name"] == "amap"
    assert api_calls[0]["endpoint"] == "/v3/place/text"
    assert api_calls[0]["params"] == {"keywords": "lake", "city": "Hangzhou", "limit": 8}
    assert api_calls[0]["duration_ms"] == 11.25
    assert api_calls[0]["cache_hit"] is False


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
    assert isinstance(record["first_body_token_ms"], (int, float))


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
