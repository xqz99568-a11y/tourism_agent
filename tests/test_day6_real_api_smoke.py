import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeOpenAICompatibleClient:
    def __init__(self, api_key: str, base_url: str, model: str, timeout: int) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

    async def chat(self, messages, tools=None, **kwargs):
        return SimpleNamespace(
            content='{"ok": true, "message": "pong"}',
            model=self.model,
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
            finish_reason="stop",
            tool_calls=[],
        )


class EmptyLengthClient(FakeOpenAICompatibleClient):
    async def chat(self, messages, tools=None, **kwargs):
        return SimpleNamespace(
            content="",
            model=self.model,
            usage={
                "prompt_tokens": 56,
                "completion_tokens": 32,
                "total_tokens": 88,
            },
            finish_reason="length",
            tool_calls=[],
        )


def test_real_api_smoke_writes_trace_token_latency_and_cost_reports(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from experiments.run_real_api_smoke import run_real_api_smoke

    monkeypatch.setenv("LLM_PRICE_INPUT_PER_1K", "0.01")
    monkeypatch.setenv("LLM_PRICE_OUTPUT_PER_1K", "0.03")
    monkeypatch.setenv("LLM_PRICE_SNAPSHOT_DATE", "2026-07-30")
    monkeypatch.setenv("LLM_PRICE_SOURCE_URL", "https://api.vectorengine.ai/pricing")

    payload = asyncio.run(
        run_real_api_smoke(
            output_dir=tmp_path / "real_api_smoke",
            run_id="real-api-unit",
            api_key="test-key-not-persisted",
            base_url="https://api.vectorengine.ai/v1",
            model="gpt-test",
            client_factory=FakeOpenAICompatibleClient,
        )
    )

    assert payload["status"] == "completed"
    assert payload["connectivity_gate"]["status"] == "passed"
    assert payload["connectivity_gate"]["connection_verified"] is True
    assert payload["connectivity_gate"]["checks"]["response_content_received"] is True
    assert payload["connectivity_gate"]["checks"]["finish_reason_not_length"] is True
    assert payload["connectivity_gate"]["checks"]["temperature_zero_recorded"] is True
    assert payload["connectivity_gate"]["checks"]["reasoning_effort_recorded"] is True
    assert payload["connectivity_gate"]["checks"]["retry_policy_recorded"] is True
    for key in (
        "api_response",
        "result",
        "token_report",
        "latency_report",
        "cost_report",
        "price_snapshot",
        "manifest",
        "report",
        "trace",
    ):
        assert Path(payload[key]).exists()

    trace = json.loads(Path(payload["trace"]).read_text(encoding="utf-8").splitlines()[0])
    call = trace["llm_calls"][0]
    assert call["mock"] is False
    assert call["fallback"] is False
    assert call["provider"] == "vectorengine_openai_compatible"
    assert call["prompt_version"] == "ctp-real-api-smoke-prompt-v1"
    assert len(call["prompt_hash"]) == 64
    assert call["temperature"] == 0.0
    assert call["max_tokens"] == 128
    assert call["timeout_seconds"] == 30
    assert call["retry_max_attempts"] == 3
    assert call["reasoning_effort"] == "minimal"
    assert call["retry_attempt_count"] == 1
    assert call["estimated_cost"] == 0.0016
    assert call["standardized_estimated_cost"] == 0.0016
    assert call["actual_cost"] is None
    assert call["actual_cost_status"] == "not_reported_by_provider"
    assert "test-key-not-persisted" not in Path(payload["trace"]).read_text(encoding="utf-8")

    token_report = json.loads(Path(payload["token_report"]).read_text(encoding="utf-8"))
    latency_report = json.loads(Path(payload["latency_report"]).read_text(encoding="utf-8"))
    cost_report = json.loads(Path(payload["cost_report"]).read_text(encoding="utf-8"))
    api_response = json.loads(Path(payload["api_response"]).read_text(encoding="utf-8"))
    price_snapshot = json.loads(Path(payload["price_snapshot"]).read_text(encoding="utf-8"))
    manifest = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
    report = Path(payload["report"]).read_text(encoding="utf-8")

    assert api_response["response_received"] is True
    assert api_response["content_received"] is True
    assert api_response["content_preview"] == '{"ok": true, "message": "pong"}'
    assert api_response["runtime_config"]["temperature"] == 0.0
    assert api_response["request_options"]["max_tokens"] == 128
    assert api_response["request_options"]["completion_limit_parameter"] == "max_tokens"
    assert api_response["request_options"]["reasoning_effort"] == "minimal"
    assert api_response["retry"]["attempt_count"] == 1
    assert token_report["total_tokens"] == 120.0
    assert latency_report["llm_call_count"] == 1
    assert latency_report["llm_total_duration_ms"] is not None
    assert cost_report["standardized_estimated_cost"] == 0.0016
    assert cost_report["actual_cost_available"] is False
    assert cost_report["price_snapshots"][0]["provider"] == "vectorengine_openai_compatible"
    assert cost_report["price_snapshots"][0]["price_source_url"] == "https://api.vectorengine.ai/pricing"
    assert price_snapshot["provider"] == "vectorengine_openai_compatible"
    assert price_snapshot["price_source_url"] == "https://api.vectorengine.ai/pricing"
    assert manifest["api_key_configured"] is True
    assert manifest["provider"] == "vectorengine_openai_compatible"
    assert manifest["runtime_config"]["provider"] == "vectorengine_openai_compatible"
    assert manifest["runtime_config"]["temperature"] == 0.0
    assert manifest["runtime_config"]["retry_max_attempts"] == 3
    assert manifest["runtime_config"]["reasoning_effort"] == "minimal"
    assert manifest["runtime_config"]["completion_limit_parameter"] == "max_tokens"
    assert manifest["connectivity_gate"]["status"] == "passed"
    assert manifest["reports"]["api_response"] == payload["api_response"]
    assert manifest["reports"]["price_snapshot"] == payload["price_snapshot"]
    assert manifest["reports"]["trace"] == payload["trace"]
    assert manifest["saved_evidence"]["status"] == "saved"
    assert manifest["saved_evidence"]["trace_file_count"] == 1
    assert "Real API smoke test report" in report
    assert "connection_verified: `True`" in report
    assert "Saved evidence files" in report


def test_real_api_smoke_writes_skipped_reports_without_api_key(tmp_path: Path) -> None:
    from experiments.run_real_api_smoke import _write_skipped_reports

    payload = _write_skipped_reports(
        output_dir=tmp_path / "skipped",
        run_id="missing-key",
        config={
            "api_key": "",
            "base_url": "https://api.vectorengine.ai/v1",
            "model": "gpt-test",
        },
        reason="missing_llm_api_key",
    )

    assert payload["status"] == "skipped"
    assert payload["connectivity_gate"]["status"] == "skipped"
    assert payload["connectivity_gate"]["connection_verified"] is False
    assert payload["connectivity_gate"]["checks"]["response_content_received"] is False
    assert payload["connectivity_gate"]["checks"]["finish_reason_not_length"] is False
    assert payload["trace"] == ""
    for key in (
        "api_response",
        "result",
        "token_report",
        "latency_report",
        "cost_report",
        "price_snapshot",
        "manifest",
        "report",
    ):
        assert Path(payload[key]).exists()
    result = json.loads(Path(payload["result"]).read_text(encoding="utf-8"))
    api_response = json.loads(Path(payload["api_response"]).read_text(encoding="utf-8"))
    manifest = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
    assert result["api_key_configured"] is False
    assert result["reason"] == "missing_llm_api_key"
    assert api_response["request_sent"] is False
    assert manifest["saved_evidence"]["status"] == "saved"
    assert manifest["saved_evidence"]["trace_required"] is False


def test_real_api_smoke_blocks_empty_length_response(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from experiments.run_real_api_smoke import run_real_api_smoke

    monkeypatch.setenv("LLM_PRICE_INPUT_PER_1K", "0.00025")
    monkeypatch.setenv("LLM_PRICE_OUTPUT_PER_1K", "0.002")
    monkeypatch.setenv("LLM_PRICE_SNAPSHOT_DATE", "2026-07-31")
    monkeypatch.setenv("LLM_PRICE_SOURCE_URL", "https://developers.openai.com/api/docs/models/gpt-5-mini")

    payload = asyncio.run(
        run_real_api_smoke(
            output_dir=tmp_path / "real_api_empty",
            run_id="empty-length",
            api_key="test-key-not-persisted",
            base_url="https://api.vectorengine.ai/v1",
            model="gpt-5-mini",
            client_factory=EmptyLengthClient,
        )
    )

    assert payload["status"] == "completed"
    assert payload["connectivity_gate"]["status"] == "failed"
    assert payload["connectivity_gate"]["connection_verified"] is False
    assert set(payload["connectivity_gate"]["failed_checks"]) >= {
        "response_content_received",
        "finish_reason_not_length",
    }
    api_response = json.loads(Path(payload["api_response"]).read_text(encoding="utf-8"))
    assert api_response["response_received"] is True
    assert api_response["content_received"] is False
