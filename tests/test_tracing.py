import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.orchestrator import AgentOrchestrator
from app.core.context import SessionContext
from app.core.llm.client import BaseLLMClient, LLMManager, LLMMessage, LLMResponse
from app.core.tracing import (
    REDACTED,
    record_api_call,
    record_tool_call,
    request_trace,
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
