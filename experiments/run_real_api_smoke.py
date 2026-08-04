"""Run a real OpenAI-compatible LLM API smoke test and write audit reports.

This script is intentionally separate from the offline FakeLLM acceptance run.
It proves connectivity and trace/cost accounting for one real API call without
spending the tokens required by a full four-method benchmark.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.core.llm.client import LLMMessage, OpenRouterClient
from app.core.llm_costing import COSTING_SCHEMA_VERSION, build_price_snapshot
from app.core.tracing import (
    finish_llm_call,
    mark_trace_status,
    request_trace,
    set_trace_result_summary,
    start_llm_call,
)


REAL_API_SMOKE_SCHEMA_VERSION = "ctp-real-api-smoke-v1"
REAL_API_SMOKE_PROMPT_VERSION = "ctp-real-api-smoke-prompt-v1"
DEFAULT_OUTPUT_ROOT = ROOT / "experiments" / "results" / "real_api_smoke"
DEFAULT_CASE_ID = "real_api_smoke_connectivity"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_TOKENS = 128
DEFAULT_RETRY_MAX_ATTEMPTS = 3
DEFAULT_REASONING_EFFORT = "minimal"
REAL_API_EVIDENCE_SCHEMA_VERSION = "ctp-real-api-smoke-evidence-v1"
REAL_API_RUNTIME_CONFIG_SCHEMA_VERSION = "ctp-experiment-runtime-config-v1"
REAL_API_RETRY_AUDIT_SCHEMA_VERSION = "ctp-llm-retry-audit-v1"

ClientFactory = Callable[[str, str, str, int], Any]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--base-url", type=str, default=None)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--retry-max-attempts", type=int, default=DEFAULT_RETRY_MAX_ATTEMPTS)
    parser.add_argument("--reasoning-effort", type=str, default=DEFAULT_REASONING_EFFORT)
    parser.add_argument(
        "--allow-missing-config",
        action="store_true",
        help="Write skipped reports instead of returning a failing exit code when LLM_API_KEY is absent.",
    )
    args = parser.parse_args()

    run_id = args.run_id or f"real_api_smoke_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    output_dir = args.output_dir if args.output_dir.name == run_id else args.output_dir / run_id
    if output_dir.exists() and any(output_dir.iterdir()):
        raise RuntimeError(f"real API smoke output directory is not empty: {output_dir}")

    config = _resolve_config(model=args.model, base_url=args.base_url)
    if not config["api_key"]:
        payload = _write_skipped_reports(
            output_dir=output_dir,
            run_id=run_id,
            config=config,
            reason="missing_llm_api_key",
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if args.allow_missing_config else 2

    payload = asyncio.run(
        run_real_api_smoke(
            output_dir=output_dir,
            run_id=run_id,
            api_key=config["api_key"],
            base_url=config["base_url"],
            model=config["model"],
            timeout=args.timeout,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            retry_max_attempts=args.retry_max_attempts,
            reasoning_effort=args.reasoning_effort,
        )
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    gate = payload.get("connectivity_gate") if isinstance(payload.get("connectivity_gate"), dict) else {}
    return 0 if payload["status"] == "completed" and gate.get("status") == "passed" else 1


async def run_real_api_smoke(
    *,
    output_dir: Path,
    run_id: str,
    api_key: str,
    base_url: str,
    model: str,
    timeout: int = 30,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    retry_max_attempts: int = DEFAULT_RETRY_MAX_ATTEMPTS,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    client_factory: Optional[ClientFactory] = None,
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = output_dir / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    request_id = f"{DEFAULT_CASE_ID}_{run_id}"
    provider = _provider_name(base_url)
    messages = _smoke_messages()
    prompt_hash = _prompt_hash(messages)
    runtime_config = _build_runtime_config(
        provider=provider,
        base_url=base_url,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        retry_max_attempts=retry_max_attempts,
        reasoning_effort=reasoning_effort,
    )
    retry_policy = _retry_audit(max_attempts=retry_max_attempts, attempts=[])
    started = time.perf_counter()
    status = "completed"
    error: Optional[str] = None
    result: Dict[str, Any] = {}

    env = {
        "ENABLE_TRACING": "true",
        "TRACE_OUTPUT_DIR": str(trace_dir),
        "EXPERIMENT_STRICT_MODE": "true",
        "TRACE_SAVE_USER_MESSAGE": "false",
        "EXPERIMENT_RUN_ID": run_id,
        "EXPERIMENT_CASE_ID": DEFAULT_CASE_ID,
        "EXPERIMENT_METHOD": "real_api_smoke",
        "SYSTEM_VARIANT": "real_api_smoke",
        "MODEL_CONFIG_NAME": "real-api-smoke",
        "LLM_MODEL": model,
        "LLM_BASE_URL": base_url,
        "LLM_TEMPERATURE": str(temperature),
        "LLM_MAX_TOKENS": str(max_tokens),
        "LLM_TIMEOUT": str(timeout),
        "LLM_RETRY_MAX_ATTEMPTS": str(retry_max_attempts),
        "LLM_REASONING_EFFORT": str(reasoning_effort),
    }

    with _temporary_env(env):
        with request_trace(
            request_id,
            f"real-api-smoke-{run_id}",
            user_message="real API smoke prompt omitted from persisted trace",
            experiment_case_id=DEFAULT_CASE_ID,
            method="real_api_smoke",
            evaluation_mode="connectivity_smoke",
            run_id=run_id,
            system_variant="real_api_smoke",
            model_config_name="real-api-smoke",
        ) as trace:
            trace_call = start_llm_call(
                provider=provider,
                model=model,
                streaming=False,
                mock=False,
                fallback=False,
                message_count=len(messages),
                message_chars=sum(len(message.content or "") for message in messages),
                tool_count=0,
                prompt_version=REAL_API_SMOKE_PROMPT_VERSION,
                prompt_hash=prompt_hash,
                request_options=runtime_config,
                retry_policy=retry_policy,
            )
            client = (
                client_factory(api_key, base_url, model, timeout)
                if client_factory
                else OpenRouterClient(
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    timeout=timeout,
                    retry_max_attempts=retry_max_attempts,
                )
            )
            try:
                response = await client.chat(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    reasoning_effort=reasoning_effort,
                )
                content = str(getattr(response, "content", "") or "")
                usage = dict(getattr(response, "usage", None) or {})
                audit_metadata = _llm_audit_metadata(response)
                if trace is not None:
                    trace.mark_first_body_token()
                finish_llm_call(
                    trace_call,
                    provider=provider,
                    model=getattr(response, "model", model),
                    usage=usage,
                    success=True,
                    mock=False,
                    fallback=False,
                    output_chars=len(content),
                    request_options=audit_metadata.get("request_options") or runtime_config,
                    retry=audit_metadata.get("retry")
                    or _retry_audit(
                        max_attempts=retry_max_attempts,
                        attempts=[{"attempt_index": 1, "success": True}],
                    ),
                )
                result = {
                    "schema_version": REAL_API_SMOKE_SCHEMA_VERSION,
                    "status": "completed",
                    "run_id": run_id,
                    "case_id": DEFAULT_CASE_ID,
                    "provider": provider,
                    "base_url": base_url,
                    "model": model,
                    "response_model": str(getattr(response, "model", model)),
                    "runtime_config": runtime_config,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "timeout_seconds": timeout,
                    "retry_max_attempts": retry_max_attempts,
                    "reasoning_effort": reasoning_effort,
                    "finish_reason": str(getattr(response, "finish_reason", "")),
                    "usage": usage,
                    "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "content_preview": content[:500],
                    "prompt_version": REAL_API_SMOKE_PROMPT_VERSION,
                    "prompt_hash": prompt_hash,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                }
                set_trace_result_summary(result)
            except Exception as exc:  # write failure evidence instead of hiding it
                status = "failed"
                error = str(exc)
                audit_metadata = _llm_audit_metadata(exc)
                mark_trace_status("failed", error=error)
                finish_llm_call(
                    trace_call,
                    provider=provider,
                    model=model,
                    success=False,
                    error=exc,
                    mock=False,
                    fallback=False,
                    output_chars=0,
                    request_options=audit_metadata.get("request_options") or runtime_config,
                    retry=audit_metadata.get("retry")
                    or _retry_audit(
                        max_attempts=retry_max_attempts,
                        attempts=[{"attempt_index": 1, "success": False, "error": error}],
                    ),
                )
                result = {
                    "schema_version": REAL_API_SMOKE_SCHEMA_VERSION,
                    "status": "failed",
                    "run_id": run_id,
                    "case_id": DEFAULT_CASE_ID,
                    "provider": provider,
                    "base_url": base_url,
                    "model": model,
                    "runtime_config": runtime_config,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "timeout_seconds": timeout,
                    "retry_max_attempts": retry_max_attempts,
                    "prompt_version": REAL_API_SMOKE_PROMPT_VERSION,
                    "prompt_hash": prompt_hash,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "error": error,
                }
                set_trace_result_summary(result)

    trace_record = _load_trace(trace_dir, request_id)
    if trace_record:
        result["trace_file"] = str(trace_record.get("trace_file") or "")
    api_response_path = output_dir / "api_response.json"
    result_path = output_dir / "real_api_smoke_result.json"
    token_path = output_dir / "token_report.json"
    latency_path = output_dir / "latency_report.json"
    cost_path = output_dir / "cost_report.json"
    price_snapshot_path = output_dir / "price_snapshot.json"
    manifest_path = output_dir / "real_api_smoke_manifest.json"
    report_path = output_dir / "real_api_smoke_report.md"

    price_snapshot = build_price_snapshot(
        provider=provider,
        model=model,
        mock=False,
    )
    api_response = _build_api_response(result, trace_record)
    token_report = _build_token_report(trace_record)
    latency_report = _build_latency_report(trace_record, fallback_latency_ms=result.get("latency_ms"))
    cost_report = _build_cost_report(trace_record)
    smoke_gate = _build_smoke_gate(
        status=status,
        result=result,
        trace_record=trace_record,
        token_report=token_report,
        cost_report=cost_report,
        price_snapshot=price_snapshot,
    )
    manifest = _build_manifest(
        run_id=run_id,
        status=status,
        smoke_gate=smoke_gate,
        config={
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout_seconds": timeout,
            "retry_max_attempts": retry_max_attempts,
            "reasoning_effort": reasoning_effort,
            "runtime_config": runtime_config,
            "api_key_configured": True,
        },
        api_response_path=api_response_path,
        result_path=result_path,
        token_path=token_path,
        latency_path=latency_path,
        cost_path=cost_path,
        price_snapshot_path=price_snapshot_path,
        report_path=report_path,
        trace_record=trace_record,
        output_dir=output_dir,
    )
    _write_json(result_path, result)
    _write_json(api_response_path, api_response)
    _write_json(token_path, token_report)
    _write_json(latency_path, latency_report)
    _write_json(cost_path, cost_report)
    _write_json(price_snapshot_path, price_snapshot)
    evidence = _build_saved_evidence(
        output_dir=output_dir,
        api_response_path=api_response_path,
        result_path=result_path,
        token_path=token_path,
        latency_path=latency_path,
        cost_path=cost_path,
        price_snapshot_path=price_snapshot_path,
        manifest_path=manifest_path,
        report_path=report_path,
        trace_record=trace_record,
        status=status,
        smoke_gate=smoke_gate,
        require_report=False,
    )
    manifest["saved_evidence"] = evidence
    _write_json(manifest_path, manifest)
    report_path.write_text(
        _render_report(
            run_id=run_id,
            status=status,
            provider=provider,
            base_url=base_url,
            model=model,
            smoke_gate=smoke_gate,
            evidence=evidence,
            token_report=token_report,
            latency_report=latency_report,
            cost_report=cost_report,
            result=result,
            manifest=manifest,
        ),
        encoding="utf-8",
    )
    evidence = _build_saved_evidence(
        output_dir=output_dir,
        api_response_path=api_response_path,
        result_path=result_path,
        token_path=token_path,
        latency_path=latency_path,
        cost_path=cost_path,
        price_snapshot_path=price_snapshot_path,
        manifest_path=manifest_path,
        report_path=report_path,
        trace_record=trace_record,
        status=status,
        smoke_gate=smoke_gate,
        require_report=True,
    )
    _validate_saved_evidence(evidence)
    manifest["saved_evidence"] = evidence
    _write_json(manifest_path, manifest)

    return {
        "status": status,
        "connectivity_gate": smoke_gate,
        "run_id": run_id,
        "output_dir": output_dir.as_posix(),
        "api_response": api_response_path.as_posix(),
        "result": result_path.as_posix(),
        "token_report": token_path.as_posix(),
        "latency_report": latency_path.as_posix(),
        "cost_report": cost_path.as_posix(),
        "price_snapshot": price_snapshot_path.as_posix(),
        "manifest": manifest_path.as_posix(),
        "report": report_path.as_posix(),
        "trace_dir": trace_dir.as_posix(),
        "trace": str(result.get("trace_file") or ""),
        "saved_evidence": evidence,
        "error": error,
    }


def _resolve_config(*, model: Optional[str], base_url: Optional[str]) -> Dict[str, str]:
    return {
        "api_key": os.getenv("LLM_API_KEY") or settings.llm.api_key,
        "base_url": base_url or os.getenv("LLM_BASE_URL") or settings.llm.base_url,
        "model": model or os.getenv("LLM_MODEL") or settings.llm.model,
    }


def _write_skipped_reports(
    *,
    output_dir: Path,
    run_id: str,
    config: Dict[str, str],
    reason: str,
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    status = "skipped"
    runtime_config = _build_runtime_config(
        provider=_provider_name(config.get("base_url")),
        base_url=str(config.get("base_url") or ""),
        model=str(config.get("model") or ""),
        temperature=DEFAULT_TEMPERATURE,
        max_tokens=DEFAULT_MAX_TOKENS,
        timeout=30,
        retry_max_attempts=DEFAULT_RETRY_MAX_ATTEMPTS,
        reasoning_effort=DEFAULT_REASONING_EFFORT,
    )
    result = {
        "schema_version": REAL_API_SMOKE_SCHEMA_VERSION,
        "status": status,
        "run_id": run_id,
        "case_id": DEFAULT_CASE_ID,
        "reason": reason,
        "provider": _provider_name(config.get("base_url")),
        "base_url": config.get("base_url"),
        "model": config.get("model"),
        "runtime_config": runtime_config,
        "api_key_configured": False,
    }
    price_snapshot = build_price_snapshot(
        provider=_provider_name(config.get("base_url")),
        model=config.get("model"),
        mock=False,
    )
    api_response = {
        "schema_version": REAL_API_SMOKE_SCHEMA_VERSION,
        "status": status,
        "run_id": run_id,
        "case_id": DEFAULT_CASE_ID,
        "reason": reason,
        "request_sent": False,
        "response_received": False,
    }
    token_report = {"schema_version": REAL_API_SMOKE_SCHEMA_VERSION, "status": status, "reason": reason}
    latency_report = {"schema_version": REAL_API_SMOKE_SCHEMA_VERSION, "status": status, "reason": reason}
    cost_report = {
        "schema_version": REAL_API_SMOKE_SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "costing_schema_version": COSTING_SCHEMA_VERSION,
        "price_snapshot": price_snapshot,
    }
    smoke_gate = {
        "schema_version": REAL_API_EVIDENCE_SCHEMA_VERSION,
        "status": "skipped",
        "connection_verified": False,
        "reason": reason,
        "checks": {
            "api_key_configured": False,
            "request_completed": False,
            "response_content_received": False,
            "finish_reason_not_length": False,
            "trace_persisted": False,
            "llm_call_recorded": False,
            "usage_tokens_reported": False,
            "latency_recorded": False,
            "price_snapshot_recorded": True,
            "cost_report_recorded": False,
            "mock_false_recorded": False,
            "fallback_false_recorded": False,
        },
    }
    api_response_path = output_dir / "api_response.json"
    result_path = output_dir / "real_api_smoke_result.json"
    token_path = output_dir / "token_report.json"
    latency_path = output_dir / "latency_report.json"
    cost_path = output_dir / "cost_report.json"
    price_snapshot_path = output_dir / "price_snapshot.json"
    manifest_path = output_dir / "real_api_smoke_manifest.json"
    report_path = output_dir / "real_api_smoke_report.md"
    _write_json(result_path, result)
    _write_json(api_response_path, api_response)
    _write_json(token_path, token_report)
    _write_json(latency_path, latency_report)
    _write_json(cost_path, cost_report)
    _write_json(price_snapshot_path, price_snapshot)
    evidence = _build_saved_evidence(
        output_dir=output_dir,
        api_response_path=api_response_path,
        result_path=result_path,
        token_path=token_path,
        latency_path=latency_path,
        cost_path=cost_path,
        price_snapshot_path=price_snapshot_path,
        manifest_path=manifest_path,
        report_path=report_path,
        trace_record=None,
        status=status,
        smoke_gate=smoke_gate,
        require_report=False,
    )
    manifest = _build_manifest(
        run_id=run_id,
        status=status,
        smoke_gate=smoke_gate,
        config={
            "provider": _provider_name(config.get("base_url")),
            "base_url": config.get("base_url"),
            "model": config.get("model"),
            "temperature": DEFAULT_TEMPERATURE,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "timeout_seconds": 30,
            "retry_max_attempts": DEFAULT_RETRY_MAX_ATTEMPTS,
            "runtime_config": runtime_config,
            "api_key_configured": False,
        },
        api_response_path=api_response_path,
        result_path=result_path,
        token_path=token_path,
        latency_path=latency_path,
        cost_path=cost_path,
        price_snapshot_path=price_snapshot_path,
        report_path=report_path,
        trace_record=None,
        output_dir=output_dir,
    )
    manifest["saved_evidence"] = evidence
    _write_json(
        manifest_path,
        manifest,
    )
    report_path.write_text(
        _render_report(
            run_id=run_id,
            status=status,
            provider=_provider_name(config.get("base_url")),
            base_url=str(config.get("base_url") or ""),
            model=str(config.get("model") or ""),
            smoke_gate=smoke_gate,
            evidence=evidence,
            token_report=token_report,
            latency_report=latency_report,
            cost_report=cost_report,
            result=result,
            manifest=manifest,
        ),
        encoding="utf-8",
    )
    evidence = _build_saved_evidence(
        output_dir=output_dir,
        api_response_path=api_response_path,
        result_path=result_path,
        token_path=token_path,
        latency_path=latency_path,
        cost_path=cost_path,
        price_snapshot_path=price_snapshot_path,
        manifest_path=manifest_path,
        report_path=report_path,
        trace_record=None,
        status=status,
        smoke_gate=smoke_gate,
        require_report=True,
    )
    _validate_saved_evidence(evidence)
    manifest["saved_evidence"] = evidence
    _write_json(manifest_path, manifest)
    return {
        "status": status,
        "connectivity_gate": smoke_gate,
        "run_id": run_id,
        "output_dir": output_dir.as_posix(),
        "api_response": api_response_path.as_posix(),
        "result": result_path.as_posix(),
        "token_report": token_path.as_posix(),
        "latency_report": latency_path.as_posix(),
        "cost_report": cost_path.as_posix(),
        "price_snapshot": price_snapshot_path.as_posix(),
        "manifest": manifest_path.as_posix(),
        "report": report_path.as_posix(),
        "trace_dir": "",
        "trace": "",
        "saved_evidence": evidence,
        "reason": reason,
    }


def _smoke_messages() -> List[LLMMessage]:
    return [
        LLMMessage(
            role="system",
            content=(
                "You are a real API connectivity smoke test. "
                "Return exactly one compact JSON object and no Markdown."
            ),
        ),
        LLMMessage(
            role="user",
            content=(
                f'prompt_version={REAL_API_SMOKE_PROMPT_VERSION}\n'
                'Return exactly: {"ok": true, "message": "pong"}'
            ),
        ),
    ]


def _prompt_hash(messages: List[LLMMessage]) -> str:
    payload = [message.to_dict() for message in messages]
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_api_response(
    result: Dict[str, Any],
    trace: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    calls = _llm_calls(trace)
    first_call = calls[0] if calls else {}
    return {
        "schema_version": REAL_API_SMOKE_SCHEMA_VERSION,
        "status": result.get("status"),
        "run_id": result.get("run_id"),
        "case_id": result.get("case_id"),
        "provider": result.get("provider"),
        "base_url": result.get("base_url"),
        "model": result.get("model"),
        "response_model": result.get("response_model"),
        "finish_reason": result.get("finish_reason"),
        "response_received": result.get("status") == "completed",
        "content_received": bool(str(result.get("content_preview") or "").strip()),
        "content_sha256": result.get("content_sha256"),
        "content_preview": result.get("content_preview"),
        "usage": result.get("usage") or {},
        "runtime_config": result.get("runtime_config") or {},
        "latency_ms": result.get("latency_ms"),
        "prompt_version": result.get("prompt_version"),
        "prompt_hash": result.get("prompt_hash"),
        "trace_file": result.get("trace_file") or "",
        "llm_call_id": first_call.get("call_id"),
        "request_options": first_call.get("request_options") or {},
        "retry": first_call.get("retry") or {},
        "mock": first_call.get("mock"),
        "fallback": first_call.get("fallback"),
        "error": result.get("error"),
    }


def _build_smoke_gate(
    *,
    status: str,
    result: Dict[str, Any],
    trace_record: Optional[Dict[str, Any]],
    token_report: Dict[str, Any],
    cost_report: Dict[str, Any],
    price_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    calls = _llm_calls(trace_record)
    total_tokens = _first_float(token_report.get("total_tokens"))
    content_received = bool(str(result.get("content_preview") or "").strip())
    finish_reason = str(result.get("finish_reason") or "").casefold()
    checks = {
        "api_key_configured": True,
        "request_completed": status == "completed" and result.get("status") == "completed",
        "response_content_received": content_received,
        "finish_reason_not_length": finish_reason not in {"length", "content_filter"},
        "trace_persisted": bool(trace_record and trace_record.get("trace_file")),
        "llm_call_recorded": len(calls) == 1,
        "usage_tokens_reported": total_tokens is not None and total_tokens > 0,
        "latency_recorded": _first_float(result.get("latency_ms")) is not None,
        "price_snapshot_recorded": bool(
            price_snapshot.get("price_snapshot_date")
            and price_snapshot.get("price_source_url")
            and price_snapshot.get("input_token_unit_price") is not None
            and price_snapshot.get("output_token_unit_price") is not None
        ),
        "cost_report_recorded": cost_report.get("status") == "completed",
        "mock_false_recorded": bool(calls) and all(call.get("mock") is False for call in calls),
        "fallback_false_recorded": bool(calls) and all(call.get("fallback") is False for call in calls),
        "temperature_zero_recorded": bool(calls)
        and all(_first_float(call.get("temperature")) == 0.0 for call in calls),
        "max_tokens_recorded": bool(calls)
        and all(_first_float(call.get("max_tokens")) is not None for call in calls),
        "timeout_recorded": bool(calls)
        and all(_first_float(call.get("timeout_seconds")) is not None for call in calls),
        "reasoning_effort_recorded": bool(calls)
        and all(call.get("reasoning_effort") == DEFAULT_REASONING_EFFORT for call in calls),
        "retry_policy_recorded": bool(calls)
        and all(isinstance(call.get("retry"), dict) for call in calls)
        and all(_first_float(call.get("retry_max_attempts")) is not None for call in calls),
    }
    passed = all(checks.values())
    return {
        "schema_version": REAL_API_EVIDENCE_SCHEMA_VERSION,
        "status": "passed" if passed else "failed",
        "connection_verified": passed,
        "checks": checks,
        "failed_checks": [key for key, value in checks.items() if not value],
        "usage_total_tokens": total_tokens,
        "estimated_cost": cost_report.get("estimated_cost"),
        "standardized_estimated_cost": cost_report.get("standardized_estimated_cost"),
        "actual_cost": cost_report.get("actual_cost"),
        "actual_cost_available": cost_report.get("actual_cost_available"),
        "actual_cost_statuses": cost_report.get("actual_cost_statuses") or [],
    }


def _build_token_report(trace: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    calls = _llm_calls(trace)
    return {
        "schema_version": REAL_API_SMOKE_SCHEMA_VERSION,
        "status": "completed" if calls else "missing_trace_or_llm_call",
        "llm_call_count": len(calls),
        "prompt_tokens": _sum_usage(calls, "prompt_tokens", "input_tokens"),
        "completion_tokens": _sum_usage(calls, "completion_tokens", "output_tokens"),
        "total_tokens": _sum_usage(calls, "total_tokens", "tokens_used"),
        "calls": [
            {
                "provider": call.get("provider"),
                "model": call.get("model"),
                "prompt_tokens": _usage_value(call, "prompt_tokens", "input_tokens"),
                "completion_tokens": _usage_value(call, "completion_tokens", "output_tokens"),
                "total_tokens": _usage_value(call, "total_tokens", "tokens_used"),
                "prompt_version": call.get("prompt_version"),
                "prompt_hash": call.get("prompt_hash"),
            }
            for call in calls
        ],
    }


def _build_latency_report(
    trace: Optional[Dict[str, Any]],
    *,
    fallback_latency_ms: Any = None,
) -> Dict[str, Any]:
    calls = _llm_calls(trace)
    return {
        "schema_version": REAL_API_SMOKE_SCHEMA_VERSION,
        "status": "completed" if calls else "missing_trace_or_llm_call",
        "latency_ms": _first_float(
            trace.get("total_duration_ms") if isinstance(trace, dict) else None,
            fallback_latency_ms,
        ),
        "first_body_token_ms": (
            trace.get("first_body_token_ms") if isinstance(trace, dict) else None
        ),
        "llm_call_count": len(calls),
        "llm_total_duration_ms": _sum_field(calls, "duration_ms"),
        "calls": [
            {
                "provider": call.get("provider"),
                "model": call.get("model"),
                "duration_ms": call.get("duration_ms"),
                "ttft_ms": call.get("ttft_ms"),
                "success": call.get("success"),
            }
            for call in calls
        ],
    }


def _build_cost_report(trace: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    calls = _llm_calls(trace)
    estimated_values = [_first_float(call.get("estimated_cost")) for call in calls]
    standardized_values = [_first_float(call.get("standardized_estimated_cost")) for call in calls]
    actual_values = [_first_float(call.get("actual_cost")) for call in calls]
    snapshots = _unique_snapshots(calls)
    return {
        "schema_version": REAL_API_SMOKE_SCHEMA_VERSION,
        "status": "completed" if calls else "missing_trace_or_llm_call",
        "costing_schema_version": COSTING_SCHEMA_VERSION,
        "currency": (snapshots[0] or {}).get("currency") if snapshots else None,
        "estimated_cost": _sum_optional(estimated_values),
        "standardized_estimated_cost": _sum_optional(standardized_values),
        "actual_cost": _sum_optional(actual_values),
        "actual_cost_available": all(value is not None for value in actual_values) if calls else False,
        "actual_cost_statuses": _unique_text(
            call.get("actual_cost_status") for call in calls if call.get("actual_cost_status")
        ),
        "price_snapshots": snapshots,
        "calls": [
            {
                "provider": call.get("provider"),
                "model": call.get("model"),
                "estimated_cost": call.get("estimated_cost"),
                "standardized_estimated_cost": call.get("standardized_estimated_cost"),
                "actual_cost": call.get("actual_cost"),
                "actual_cost_status": call.get("actual_cost_status"),
                "input_token_unit_price": call.get("input_token_unit_price"),
                "output_token_unit_price": call.get("output_token_unit_price"),
                "price_snapshot_date": call.get("price_snapshot_date"),
                "price_source_url": call.get("price_source_url"),
                "prompt_version": call.get("prompt_version"),
                "prompt_hash": call.get("prompt_hash"),
            }
            for call in calls
        ],
    }


def _build_manifest(
    *,
    run_id: str,
    status: str,
    smoke_gate: Dict[str, Any],
    config: Dict[str, Any],
    api_response_path: Path,
    result_path: Path,
    token_path: Path,
    latency_path: Path,
    cost_path: Path,
    price_snapshot_path: Path,
    report_path: Path,
    trace_record: Optional[Dict[str, Any]],
    output_dir: Path,
) -> Dict[str, Any]:
    price_snapshot = build_price_snapshot(
        provider=config.get("provider"),
        model=config.get("model"),
        mock=False,
    )
    trace_file = str((trace_record or {}).get("trace_file") or "")
    git_commit = _git_commit()
    git_status = _git_status_short()
    return {
        "schema_version": REAL_API_SMOKE_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "status": status,
        "connectivity_gate": smoke_gate,
        "case_id": DEFAULT_CASE_ID,
        "provider": config.get("provider"),
        "base_url": config.get("base_url"),
        "model": config.get("model"),
        "temperature": config.get("temperature"),
        "max_tokens": config.get("max_tokens"),
        "timeout_seconds": config.get("timeout_seconds"),
        "retry_max_attempts": config.get("retry_max_attempts"),
        "runtime_config": config.get("runtime_config") or {},
        "api_key_configured": bool(config.get("api_key_configured")),
        "git_commit": git_commit,
        "working_tree_clean": len(git_status) == 0,
        "git_status_short": git_status,
        "git": {
            "commit": git_commit,
            "working_tree_clean": len(git_status) == 0,
            "status_short": git_status,
        },
        "prompt_version": REAL_API_SMOKE_PROMPT_VERSION,
        "price_snapshot": price_snapshot,
        "price_snapshot_date": price_snapshot.get("price_snapshot_date"),
        "input_token_unit_price": price_snapshot.get("input_token_unit_price"),
        "output_token_unit_price": price_snapshot.get("output_token_unit_price"),
        "price_unit": price_snapshot.get("price_unit"),
        "price_source_url": price_snapshot.get("price_source_url"),
        "output_dir": output_dir.as_posix(),
        "trace_dir": (output_dir / "traces").as_posix(),
        "trace_file_count": 1 if trace_file else 0,
        "reports": {
            "api_response": api_response_path.as_posix(),
            "result": result_path.as_posix(),
            "token_report": token_path.as_posix(),
            "latency_report": latency_path.as_posix(),
            "cost_report": cost_path.as_posix(),
            "price_snapshot": price_snapshot_path.as_posix(),
            "report": report_path.as_posix(),
            "trace": trace_file,
        },
    }


def _build_saved_evidence(
    *,
    output_dir: Path,
    api_response_path: Path,
    result_path: Path,
    token_path: Path,
    latency_path: Path,
    cost_path: Path,
    price_snapshot_path: Path,
    manifest_path: Path,
    report_path: Path,
    trace_record: Optional[Dict[str, Any]],
    status: str,
    smoke_gate: Dict[str, Any],
    require_report: bool,
) -> Dict[str, Any]:
    trace_file = str((trace_record or {}).get("trace_file") or "")
    required_files = {
        "api_response": api_response_path,
        "result": result_path,
        "token_report": token_path,
        "latency_report": latency_path,
        "cost_report": cost_path,
        "price_snapshot": price_snapshot_path,
        "manifest": manifest_path,
        "report": report_path,
    }
    required_for_check = dict(required_files)
    if not require_report:
        required_for_check.pop("report", None)
        required_for_check.pop("manifest", None)
    missing_required_files = [
        key for key, path in required_for_check.items() if not Path(path).exists()
    ]
    trace_required = status != "skipped"
    missing_trace = bool(trace_required and (not trace_file or not Path(trace_file).exists()))
    complete = not missing_required_files and not missing_trace
    return {
        "schema_version": REAL_API_EVIDENCE_SCHEMA_VERSION,
        "status": "saved" if complete else "incomplete",
        "smoke_status": status,
        "connection_verified": bool(smoke_gate.get("connection_verified")),
        "output_dir": output_dir.as_posix(),
        "required_files": {
            key: Path(path).as_posix()
            for key, path in required_files.items()
        },
        "missing_required_files": missing_required_files,
        "trace_required": trace_required,
        "trace_dir": (output_dir / "traces").as_posix(),
        "trace_file": trace_file,
        "trace_file_count": 1 if trace_file and Path(trace_file).exists() else 0,
        "missing_trace": missing_trace,
    }


def _validate_saved_evidence(evidence: Dict[str, Any]) -> None:
    if evidence.get("status") != "saved":
        raise RuntimeError(
            "real API smoke evidence is incomplete: "
            f"missing_files={evidence.get('missing_required_files') or []}; "
            f"missing_trace={evidence.get('missing_trace')}"
        )
    if evidence.get("trace_required") and int(evidence.get("trace_file_count") or 0) != 1:
        raise RuntimeError("real API smoke evidence must include exactly one trace file")


def _render_report(
    *,
    run_id: str,
    status: str,
    provider: str,
    base_url: str,
    model: str,
    smoke_gate: Dict[str, Any],
    evidence: Dict[str, Any],
    token_report: Dict[str, Any],
    latency_report: Dict[str, Any],
    cost_report: Dict[str, Any],
    result: Dict[str, Any],
    manifest: Dict[str, Any],
) -> str:
    price_snapshot = manifest.get("price_snapshot") if isinstance(manifest.get("price_snapshot"), dict) else {}
    lines = [
        "# Real API smoke test report",
        "",
        "## Run conclusion",
        "",
        f"- run_id: `{run_id}`",
        f"- status: `{status}`",
        f"- connectivity_gate: `{smoke_gate.get('status')}`",
        f"- connection_verified: `{smoke_gate.get('connection_verified')}`",
        f"- provider: `{provider}`",
        f"- base_url: `{base_url}`",
        f"- model: `{model}`",
        f"- response_model: `{result.get('response_model')}`",
        f"- temperature: `{manifest.get('temperature')}`",
        f"- max_tokens: `{manifest.get('max_tokens')}`",
        f"- timeout_seconds: `{manifest.get('timeout_seconds')}`",
        f"- retry_max_attempts: `{manifest.get('retry_max_attempts')}`",
        f"- finish_reason: `{result.get('finish_reason')}`",
        f"- latency_ms: `{latency_report.get('latency_ms')}`",
        f"- llm_total_duration_ms: `{latency_report.get('llm_total_duration_ms')}`",
        f"- prompt_tokens: `{token_report.get('prompt_tokens')}`",
        f"- completion_tokens: `{token_report.get('completion_tokens')}`",
        f"- total_tokens: `{token_report.get('total_tokens')}`",
        f"- estimated_cost: `{cost_report.get('estimated_cost')}`",
        f"- standardized_estimated_cost: `{cost_report.get('standardized_estimated_cost')}`",
        f"- actual_cost: `{cost_report.get('actual_cost')}`",
        f"- actual_cost_available: `{cost_report.get('actual_cost_available')}`",
        f"- price_snapshot_date: `{price_snapshot.get('price_snapshot_date')}`",
        f"- input_token_unit_price: `{price_snapshot.get('input_token_unit_price')}`",
        f"- output_token_unit_price: `{price_snapshot.get('output_token_unit_price')}`",
        f"- price_unit: `{price_snapshot.get('price_unit')}`",
        f"- price_source_url: `{price_snapshot.get('price_source_url')}`",
        f"- prompt_version: `{manifest.get('prompt_version')}`",
        f"- git_commit: `{manifest.get('git_commit')}`",
        f"- working_tree_clean: `{manifest.get('working_tree_clean')}`",
        f"- trace_file_count: `{evidence.get('trace_file_count')}`",
        f"- trace_file: `{evidence.get('trace_file')}`",
        "",
        "## Connectivity gate checks",
        "",
        "| check | passed |",
        "|---|---:|",
    ]
    for key, value in (smoke_gate.get("checks") or {}).items():
        lines.append(f"| {key} | `{value}` |")
    lines.extend(
        [
            "",
            "## Saved evidence files",
            "",
            "| artifact | path |",
            "|---|---|",
        ]
    )
    for key, path in (evidence.get("required_files") or {}).items():
        lines.append(f"| {key} | `{path}` |")
    if smoke_gate.get("status") != "passed":
        lines.extend(
            [
                "",
                "## Failure details",
                "",
                f"- failed_checks: `{smoke_gate.get('failed_checks') or []}`",
                f"- error: `{result.get('error')}`",
            ]
        )
    return "\n".join(lines) + "\n"


def _provider_name(base_url: Any) -> str:
    text = str(base_url or "").casefold()
    if "vectorengine" in text:
        return "vectorengine_openai_compatible"
    if "openrouter" in text:
        return "openrouter"
    if "openai" in text:
        return "openai"
    return "openai_compatible"


def _build_runtime_config(
    *,
    provider: str,
    base_url: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
    retry_max_attempts: int,
    reasoning_effort: str,
) -> Dict[str, Any]:
    return {
        "schema_version": REAL_API_RUNTIME_CONFIG_SCHEMA_VERSION,
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "timeout_seconds": int(timeout),
        "retry_max_attempts": int(retry_max_attempts),
        "reasoning_effort": str(reasoning_effort or "").strip().lower() or None,
        "strict_mode": True,
        "cache_disabled": True,
        "trace_save_user_message": False,
        "mock_fallback_allowed": False,
    }


def _retry_audit(
    *,
    max_attempts: int,
    attempts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    error_count = sum(1 for attempt in attempts if attempt.get("success") is False)
    return {
        "schema_version": REAL_API_RETRY_AUDIT_SCHEMA_VERSION,
        "max_attempts": int(max_attempts),
        "attempt_count": len(attempts),
        "retry_count": max(0, len(attempts) - 1),
        "error_count": error_count,
        "succeeded": bool(attempts and attempts[-1].get("success") is True),
        "attempts": attempts,
    }


def _llm_audit_metadata(value: Any) -> Dict[str, Any]:
    metadata = getattr(value, "metadata", None)
    if isinstance(metadata, dict):
        return metadata
    metadata = getattr(value, "llm_audit_metadata", None)
    return metadata if isinstance(metadata, dict) else {}


def _load_trace(trace_dir: Path, request_id: str) -> Optional[Dict[str, Any]]:
    for path in sorted(trace_dir.glob("*.jsonl")):
        try:
            record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        except (OSError, IndexError, json.JSONDecodeError):
            continue
        if record.get("request_id") == request_id:
            record["trace_file"] = path.as_posix()
            return record
    return None


def _llm_calls(trace: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(trace, dict):
        return []
    return [call for call in trace.get("llm_calls") or [] if isinstance(call, dict)]


def _sum_usage(calls: List[Dict[str, Any]], *keys: str) -> Optional[float]:
    return _sum_optional([_usage_value(call, *keys) for call in calls])


def _usage_value(call: Dict[str, Any], *keys: str) -> Optional[float]:
    usage = call.get("usage") if isinstance(call.get("usage"), dict) else call.get("tokens")
    usage = usage if isinstance(usage, dict) else {}
    return _first_float(*(usage.get(key) for key in keys))


def _sum_field(calls: List[Dict[str, Any]], field: str) -> Optional[float]:
    return _sum_optional([_first_float(call.get(field)) for call in calls])


def _sum_optional(values: List[Optional[float]]) -> Optional[float]:
    present = [value for value in values if value is not None]
    return None if not present else round(sum(present), 8)


def _first_float(*values: Any) -> Optional[float]:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _unique_snapshots(calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    snapshots: List[Dict[str, Any]] = []
    for call in calls:
        snapshot = call.get("price_snapshot")
        if not isinstance(snapshot, dict):
            continue
        key = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        snapshots.append(snapshot)
    return snapshots


def _unique_text(values: Any) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _git_status_short() -> List[str]:
    try:
        output = subprocess.check_output(
            ["git", "status", "--short"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return []
    return [line for line in output.splitlines() if line.strip()]


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@contextmanager
def _temporary_env(values: Dict[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
