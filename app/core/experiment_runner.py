"""
Experiment runner for thesis-style benchmark execution.

The runner keeps the original metric collection helpers, and adds a unified
entry point for running the same case through four comparable methods:
llm_direct, single_agent, fixed_multi_agent, and adaptive_multi_agent.
"""
from __future__ import annotations

import asyncio
import ast
import csv
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Mapping, Optional

from app.core.config import settings
from app.core.experiment_method_contract import (
    EXPERIMENT_METHODS,
    build_method_fairness_contract,
    method_fairness_contract_hash,
    validate_method_fairness_contract,
)
from app.core.experiment_method_input import build_generation_case, parse_visible_request_slots
from app.core.experiment_run_audit import (
    RUN_AUDIT_SCHEMA_VERSION,
    build_run_audit,
)
from app.core.experiment_metrics import (
    CollaborationMode,
    ExperimentContext,
    ExperimentMetrics,
    ReviewModeExperiment,
    build_experiment_metrics,
    build_experiment_record,
    constraint_metrics_from_report,
)
from app.core.fixed_data import (
    CANONICAL_JSON_SHA256_STRATEGY,
    canonical_json_sha256,
    get_fixed_tourism_data,
    validate_fixed_data_snapshot,
)
from app.core.formal_artifact_integrity import build_formal_artifact_integrity_report
from app.core.budget_gold import (
    BudgetGoldError,
    DEFAULT_CTP100_BUDGET_GOLD_PATH,
    validate_budget_gold,
)
from app.core.qweather_snapshot import qweather_snapshot_summary
from app.core.intercity_transport_snapshot import intercity_transport_snapshot_summary
from app.core.goal_state_scheduler import (
    RESULT_DEPENDENCIES,
    build_goal_state_result_fingerprints,
    build_goal_state_ticket,
    is_goal_state_agent_reusable,
    is_goal_state_agent_reusable_for_ticket,
    schedule_goal_state_ticket,
)
from app.core.independent_evaluator import (
    DEFAULT_RULE_CATALOG_PATH,
    EVALUATION_SUMMARY_SCHEMA_VERSION,
    EVALUATION_SCHEMA_VERSION,
    evaluate_case,
    load_rule_catalog,
    render_paper_tables,
    summarize_evaluation_results,
)
from app.core.llm.client import LLMMessage, ToolDefinition, get_llm, llm_provider_from_base_url
from app.core.llm_costing import COSTING_SCHEMA_VERSION, build_price_snapshot
from app.core.no_date_weather_policy import (
    append_no_date_weather_reminder,
    gold_requires_no_date_weather_reminder,
)
from app.core.tool_executor import ToolExecutor
from app.core.tracing import (
    DEFAULT_TRACE_DIR,
    DEFAULT_EVALUATION_MODE,
    finish_agent_run,
    is_experiment_cache_disabled,
    is_experiment_strict_mode,
    mark_trace_status,
    record_planned_tools,
    record_tool_call,
    request_trace,
    set_trace_intent_info,
    set_trace_result_summary,
    set_trace_scheduler_info,
    set_trace_selected_agents,
    start_agent_run,
    trace_component,
)
from app.schemas.experiment import (
    EXPERIMENT_OUTPUT_SCHEMA_VERSION,
    ExperimentMethodOutput,
    normalize_experiment_output,
)
from app.tools.research_tools import (
    GENERATION_TOOL_NAMES,
    ResearchConstraintCheckerTool,
    generation_tools,
)


ExperimentMethod = str
MethodHandler = Callable[[Dict[str, Any]], Awaitable[Any] | Any]
METHOD_PREVIOUS_STATE_SCHEMA_VERSION = "ctp-method-previous-state-v1"
RESEARCH_AGENT_OUTPUT_SCHEMA_VERSION = "ctp-research-agent-output-v1"
RESEARCH_AGENT_DECISION_SCHEMA_VERSION = "ctp-research-agent-decision-v1"
RESEARCH_AGENT_DECISION_NORMALIZER_VERSION = "ctp-research-agent-decision-normalizer-v1"
RESEARCH_AGENT_PROMPT_VERSION = "ctp-research-agent-prompts-v2"
STRUCTURED_LLM_OUTPUT_PROMPT_VERSION = "ctp-structured-llm-output-prompts-v2"
STRUCTURED_LLM_CONTENT_FIELDS = (
    "task_type",
    "attractions",
    "trip_days",
    "daily_itinerary",
    "budget",
    "weather",
    "weather_adjustments",
    "execution_status",
    "final_answer",
)
STRUCTURED_LLM_M0_METHOD_FIELDS = (
    "schema_version",
    "case_id",
    "method",
    "planned_agents",
    "used_agents",
    "planned_tools",
    "called_tools",
    "tool_results",
)
EXPERIMENT_RESUME_SCHEMA_VERSION = "ctp-experiment-resume-v1"
EXPERIMENT_RESUME_CONTRACT_SCHEMA_VERSION = "ctp-experiment-resume-contract-v1"
BENCHMARK_RESULTS_CSV_NAME = "benchmark_results.csv"
BENCHMARK_RESULTS_JSON_NAME = "benchmark_results.json"
BENCHMARK_CHECKPOINT_CSV_NAME = "benchmark_results.checkpoint.csv"
BENCHMARK_CHECKPOINT_JSON_NAME = "benchmark_results.checkpoint.json"
BENCHMARK_RESUME_STATE_NAME = "benchmark_resume_state.json"
SINGLE_TURN_RESUME_ID = ""
EXPERIMENT_LLM_CALL_TIMEOUT_ENV = "EXPERIMENT_LLM_CALL_TIMEOUT_SECONDS"
EXPERIMENT_RESULT_HARD_TIMEOUT_ENV = "EXPERIMENT_RESULT_HARD_TIMEOUT_SECONDS"
EXPERIMENT_RESULT_HARD_TIMEOUT_CHILD_ENV = "EXPERIMENT_RESULT_HARD_TIMEOUT_CHILD"
EXPERIMENT_RESULT_WORKER_STARTUP_DELAY_ENV = (
    "EXPERIMENT_RESULT_WORKER_STARTUP_DELAY_SECONDS"
)
EXPERIMENT_RESULT_HARD_TIMEOUT_SCHEMA_VERSION = (
    "ctp-experiment-result-hard-timeout-v1"
)
EXPERIMENT_AGENT_DECISION_NORMALIZER_ENV = "EXPERIMENT_AGENT_DECISION_NORMALIZER"
FROZEN_RESEARCH_TASK_TYPES = {
    "trip_planning",
    "attraction_recommendation",
    "weather_query",
    "budget_query",
    "partial_replan",
    "weather_adjustment",
    "clarification",
    "general_chat",
}
RESEARCH_TASK_TYPE_ALIASES = {
    "budget_control": "budget_query",
    "planning": "trip_planning",
    "trip_plan": "trip_planning",
    "weather_aware_trip_plan": "trip_planning",
    "weather_forecast_query": "weather_query",
    "weather_climate_question": "general_chat",
    "destination_recommendation": "general_chat",
}
_JSON_ARITHMETIC_VALUE_PATTERN = re.compile(
    r'(?P<prefix>"[A-Za-z0-9_]+"[ \t\r\n]*:[ \t\r\n]*)'
    r'(?P<expr>[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?:[ \t\r\n]*[+\-*/][ \t\r\n]*[-+]?(?:\d+(?:\.\d+)?|\.\d+))+)'  # noqa: E501
    r'(?P<suffix>[ \t\r\n]*(?:[,}\]]))'
)


class ExperimentRunner:
    """Run benchmark cases and export paper-ready trace/CSV records."""

    METHODS = EXPERIMENT_METHODS
    METHOD_ALIASES = {
        "full_system": "adaptive_multi_agent",
        "m0": "llm_direct",
        "m1": "single_agent",
        "m2": "fixed_multi_agent",
        "m3": "adaptive_multi_agent",
    }
    EVALUATION_MODES = (DEFAULT_EVALUATION_MODE, "oracle_slots")
    SINGLE_AGENT_MAX_TOOL_ROUNDS = 8

    TEST_CASES = [
        {
            "id": "case_001",
            "input": {
                "destination": "杭州",
                "duration": 3,
                "num_travelers": 2,
                "budget_level": "medium",
            },
        },
        {
            "id": "case_002",
            "input": {
                "destination": "成都",
                "duration": 4,
                "num_travelers": 2,
                "budget_level": "medium",
            },
        },
        {
            "id": "case_003",
            "input": {
                "destination": "北京",
                "duration": 5,
                "num_travelers": 3,
                "budget_level": "luxury",
            },
        },
    ]

    def __init__(
        self,
        *,
        trace_dir: str | Path = DEFAULT_TRACE_DIR,
        output_dir: str | Path = "experiments/results",
        method_handlers: Optional[Dict[ExperimentMethod, MethodHandler]] = None,
        app_factory: Optional[Callable[[], Any]] = None,
        llm_factory: Optional[Callable[[], Any]] = None,
        repeats: int = 1,
        run_id: Optional[str] = None,
        repeat_index: int = 0,
        system_variant: Optional[str] = None,
        model_config_name: Optional[str] = None,
        method_order_seed: Optional[int] = None,
        enable_research_agent_decision_normalizer: Optional[bool] = None,
    ) -> None:
        self.trace_dir = Path(trace_dir)
        self.output_dir = Path(output_dir)
        self.method_handlers = method_handlers or {}
        self._has_custom_method_handlers = bool(method_handlers)
        self._has_custom_app_factory = app_factory is not None
        self._has_custom_llm_factory = llm_factory is not None
        self.app_factory = app_factory
        self.llm_factory = llm_factory or get_llm
        self.repeats = _validate_repeats(repeats)
        self.run_id = str(run_id or f"run_{uuid.uuid4().hex[:12]}")
        self.repeat_index = _validate_repeat_index(repeat_index)
        self.system_variant = _optional_text(system_variant)
        self.model_config_name = _optional_text(model_config_name) or "default"
        self.enable_research_agent_decision_normalizer = (
            _environment_bool(EXPERIMENT_AGENT_DECISION_NORMALIZER_ENV, True)
            if enable_research_agent_decision_normalizer is None
            else bool(enable_research_agent_decision_normalizer)
        )
        self.method_order_seed = (
            method_order_seed
            if method_order_seed is not None
            else _environment_int("EXPERIMENT_METHOD_ORDER_SEED", 20260718)
        )
        self.git_status_short_at_start = _git_status_short()
        self.fixed_data_manifest = validate_fixed_data_snapshot()
        self.experiment_records: List[Dict[str, Any]] = []
        self.current_context: Optional[ExperimentContext] = None

    # ------------------------------------------------------------------
    # New thesis benchmark API
    # ------------------------------------------------------------------
    def run(
        self,
        case: Dict[str, Any],
        method: ExperimentMethod = "adaptive_multi_agent",
        *,
        run_id: Optional[str] = None,
        repeat_index: Optional[int] = None,
        system_variant: Optional[str] = None,
        model_config_name: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Synchronously run one case through one method."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.arun(
                    case,
                    method=method,
                    run_id=run_id,
                    repeat_index=repeat_index,
                    system_variant=system_variant,
                    model_config_name=model_config_name,
                    request_id=request_id,
                )
            )
        raise RuntimeError("ExperimentRunner.run() cannot be used inside a running event loop; use arun().")

    async def arun(
        self,
        case: Dict[str, Any],
        method: ExperimentMethod = "adaptive_multi_agent",
        *,
        run_id: Optional[str] = None,
        repeat_index: Optional[int] = None,
        system_variant: Optional[str] = None,
        model_config_name: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Asynchronously run one case through one method."""
        method = self._normalize_method(method)
        normalized_case = self._normalize_case(case)
        case_id = normalized_case["case_id"]
        request_id = _optional_text(request_id) or f"{case_id}_{method}_{uuid.uuid4().hex[:8]}"
        effective_run_id = str(run_id or self.run_id)
        effective_repeat_index = (
            self.repeat_index
            if repeat_index is None
            else _validate_repeat_index(repeat_index)
        )
        effective_system_variant = (
            _optional_text(system_variant) or self.system_variant or method
        )
        effective_model_config_name = (
            _optional_text(model_config_name) or self.model_config_name
        )

        hard_timeout_seconds = _experiment_result_hard_timeout_seconds()
        if self._should_use_result_hard_timeout_worker(hard_timeout_seconds):
            result = await self._arun_with_result_hard_timeout_worker(
                case=case,
                normalized_case=normalized_case,
                method=method,
                request_id=request_id,
                run_id=effective_run_id,
                repeat_index=effective_repeat_index,
                system_variant=effective_system_variant,
                model_config_name=effective_model_config_name,
                timeout_seconds=float(hard_timeout_seconds or 0.0),
            )
            self.experiment_records.append(result)
            return result

        started = time.perf_counter()
        output: Any = None
        error: Optional[str] = None
        generation_case = self._case_visible_to_generation(normalized_case, method)

        env = {
            "ENABLE_TRACING": "true",
            "TRACE_OUTPUT_DIR": str(self.trace_dir),
            "EXPERIMENT_CASE_ID": case_id,
            "EXPERIMENT_METHOD": method,
            "EXPERIMENT_EVALUATION_MODE": normalized_case["evaluation_mode"],
            "EXPERIMENT_RUN_ID": effective_run_id,
            "EXPERIMENT_REPEAT_INDEX": str(effective_repeat_index),
            "SYSTEM_VARIANT": effective_system_variant,
            "MODEL_CONFIG_NAME": effective_model_config_name,
            "TOURISM_FORMAL_EXPERIMENT_OFFLINE": "true",
        }
        self.trace_dir.mkdir(parents=True, exist_ok=True)

        with _temporary_env(env):
            try:
                output = await asyncio.wait_for(
                    self._dispatch_method(generation_case, method, request_id),
                    timeout=_experiment_result_timeout_seconds(),
                )
            except TimeoutError as exc:
                error = f"experiment result timeout: {exc}"
                output = {"error": error, "execution_status": "failed"}
            except Exception as exc:  # keep benchmark runs table-shaped
                error = str(exc)
                output = {"error": error}

        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        trace = self._load_trace_by_request_id(request_id)
        result = await self._build_unified_result(
            case=normalized_case,
            method=method,
            output=output,
            latency_ms=latency_ms,
            trace=trace,
            error=error,
        )
        self.experiment_records.append(result)
        return result

    def _should_use_result_hard_timeout_worker(
        self,
        timeout_seconds: Optional[float],
    ) -> bool:
        if timeout_seconds is None or timeout_seconds <= 0:
            return False
        if _environment_bool(EXPERIMENT_RESULT_HARD_TIMEOUT_CHILD_ENV, False):
            return False
        if (
            self._has_custom_method_handlers
            or self._has_custom_app_factory
            or self._has_custom_llm_factory
        ):
            return False
        return True

    async def _arun_with_result_hard_timeout_worker(
        self,
        *,
        case: Dict[str, Any],
        normalized_case: Dict[str, Any],
        method: ExperimentMethod,
        request_id: str,
        run_id: str,
        repeat_index: int,
        system_variant: str,
        model_config_name: str,
        timeout_seconds: float,
    ) -> Dict[str, Any]:
        started = time.perf_counter()
        worker_payload = {
            "case": _jsonable_value(case),
            "method": method,
            "request_id": request_id,
            "trace_dir": self.trace_dir.as_posix(),
            "output_dir": self.output_dir.as_posix(),
            "run_id": run_id,
            "repeat_index": repeat_index,
            "system_variant": system_variant,
            "model_config_name": model_config_name,
            "repeats": self.repeats,
            "method_order_seed": self.method_order_seed,
            "enable_research_agent_decision_normalizer": (
                self.enable_research_agent_decision_normalizer
            ),
        }
        worker_result = await asyncio.to_thread(
            self._run_result_hard_timeout_worker_process,
            worker_payload,
            timeout_seconds,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        if worker_result.get("status") == "completed" and isinstance(
            worker_result.get("result"),
            dict,
        ):
            result = worker_result["result"]
            self._attach_result_hard_timeout_metadata(
                result,
                timeout_seconds=timeout_seconds,
                triggered=False,
                worker_status="completed",
                worker_elapsed_ms=elapsed_ms,
                worker_pid=worker_result.get("pid"),
                worker_returncode=worker_result.get("returncode"),
            )
            return result

        worker_status = str(worker_result.get("status") or "failed")
        triggered = worker_status == "timeout"
        if triggered:
            error = (
                f"experiment result hard timeout after {timeout_seconds:g}s; "
                "worker process was terminated"
            )
        else:
            error = (
                "experiment result worker failed before producing a valid result: "
                f"{worker_result.get('error') or worker_status}"
            )
        trace = {
            "request_id": request_id,
            "run_id": run_id,
            "repeat_index": repeat_index,
            "system_variant": system_variant,
            "model_config_name": model_config_name,
            "status": "failed",
            "error": error,
            "trace_file": None,
        }
        output = {
            "error": error,
            "execution_status": "failed",
            "final_answer": "该条实验因执行超时或子进程失败而中止，系统已保存失败原因并继续后续实验。",
            "metadata": {
                "result_hard_timeout": self._result_hard_timeout_metadata(
                    timeout_seconds=timeout_seconds,
                    triggered=triggered,
                    worker_status=worker_status,
                    worker_elapsed_ms=elapsed_ms,
                    worker_pid=worker_result.get("pid"),
                    worker_returncode=worker_result.get("returncode"),
                    worker_stdout=worker_result.get("stdout"),
                    worker_stderr=worker_result.get("stderr"),
                )
            },
        }
        result = await self._build_unified_result(
            case=normalized_case,
            method=method,
            output=output,
            latency_ms=elapsed_ms,
            trace=trace,
            error=error,
        )
        self._attach_result_hard_timeout_metadata(
            result,
            timeout_seconds=timeout_seconds,
            triggered=triggered,
            worker_status=worker_status,
            worker_elapsed_ms=elapsed_ms,
            worker_pid=worker_result.get("pid"),
            worker_returncode=worker_result.get("returncode"),
            worker_stdout=worker_result.get("stdout"),
            worker_stderr=worker_result.get("stderr"),
        )
        return result

    def _run_result_hard_timeout_worker_process(
        self,
        payload: Dict[str, Any],
        timeout_seconds: float,
    ) -> Dict[str, Any]:
        run_id = str(payload.get("run_id") or self.run_id)
        request_id = str(payload.get("request_id") or uuid.uuid4().hex)
        worker_dir = self._benchmark_output_dir(run_id) / "worker_io"
        worker_dir.mkdir(parents=True, exist_ok=True)
        file_stem = _session_component(request_id)
        request_path = worker_dir / f"{file_stem}.request.json"
        response_path = worker_dir / f"{file_stem}.response.json"
        request_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        repo_root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env[EXPERIMENT_RESULT_HARD_TIMEOUT_CHILD_ENV] = "true"
        env.setdefault("PYTHONIOENCODING", "utf-8")
        command = [
            sys.executable,
            "-m",
            "app.core.experiment_result_worker",
            request_path.as_posix(),
            response_path.as_posix(),
        ]
        process = subprocess.Popen(
            command,
            cwd=repo_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        timed_out, stdout, stderr = self._wait_result_worker_process(
            process,
            timeout_seconds=timeout_seconds,
        )
        if timed_out:
            return {
                "status": "timeout",
                "pid": process.pid,
                "returncode": process.returncode,
                "stdout": _truncate_text(stdout),
                "stderr": _truncate_text(stderr),
                "request_path": request_path.as_posix(),
                "response_path": response_path.as_posix(),
            }

        if process.returncode != 0:
            return {
                "status": "failed",
                "pid": process.pid,
                "returncode": process.returncode,
                "stdout": _truncate_text(stdout),
                "stderr": _truncate_text(stderr),
                "error": f"worker exited with code {process.returncode}",
                "request_path": request_path.as_posix(),
                "response_path": response_path.as_posix(),
            }
        if not response_path.exists():
            return {
                "status": "failed",
                "pid": process.pid,
                "returncode": process.returncode,
                "stdout": _truncate_text(stdout),
                "stderr": _truncate_text(stderr),
                "error": "worker did not write response file",
                "request_path": request_path.as_posix(),
                "response_path": response_path.as_posix(),
            }
        try:
            response = json.loads(response_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "status": "failed",
                "pid": process.pid,
                "returncode": process.returncode,
                "stdout": _truncate_text(stdout),
                "stderr": _truncate_text(stderr),
                "error": f"worker response is invalid JSON: {exc}",
                "request_path": request_path.as_posix(),
                "response_path": response_path.as_posix(),
            }
        if not isinstance(response, dict):
            return {
                "status": "failed",
                "pid": process.pid,
                "returncode": process.returncode,
                "stdout": _truncate_text(stdout),
                "stderr": _truncate_text(stderr),
                "error": "worker response must be a JSON object",
                "request_path": request_path.as_posix(),
                "response_path": response_path.as_posix(),
            }
        response.setdefault("stdout", _truncate_text(stdout))
        response.setdefault("stderr", _truncate_text(stderr))
        response.setdefault("pid", process.pid)
        response.setdefault("returncode", process.returncode)
        response.setdefault("request_path", request_path.as_posix())
        response.setdefault("response_path", response_path.as_posix())
        return response

    def _wait_result_worker_process(
        self,
        process: subprocess.Popen[str],
        *,
        timeout_seconds: float,
    ) -> tuple[bool, str, str]:
        """Wait for a worker with an explicit monotonic watchdog.

        ``subprocess.communicate(timeout=...)`` is normally sufficient, but the
        real VectorEngine/OpenAI-compatible run exposed a Windows case where a
        long child process was not interrupted at the configured deadline.  This
        loop keeps the deadline in our own code and terminates the worker process
        tree as soon as the monotonic clock crosses it.
        """
        deadline = time.monotonic() + max(0.001, float(timeout_seconds))
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._terminate_result_worker_process(process)
                stdout, stderr = self._communicate_after_worker_termination(process)
                return True, stdout, stderr
            time.sleep(min(0.25, max(0.001, remaining)))
        stdout, stderr = process.communicate()
        return False, stdout, stderr

    def _terminate_result_worker_process(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5,
                    check=False,
                )
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        else:
            try:
                process.kill()
            except Exception:
                pass

    def _communicate_after_worker_termination(
        self,
        process: subprocess.Popen[str],
    ) -> tuple[str, str]:
        try:
            return process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except Exception:
                pass
            try:
                return process.communicate(timeout=5)
            except Exception:
                return "", ""

    def _result_hard_timeout_metadata(
        self,
        *,
        timeout_seconds: float,
        triggered: bool,
        worker_status: str,
        worker_elapsed_ms: float,
        worker_pid: Any = None,
        worker_returncode: Any = None,
        worker_stdout: Any = None,
        worker_stderr: Any = None,
    ) -> Dict[str, Any]:
        metadata = {
            "schema_version": EXPERIMENT_RESULT_HARD_TIMEOUT_SCHEMA_VERSION,
            "enabled": True,
            "mode": "subprocess_per_result",
            "timeout_seconds": float(timeout_seconds),
            "triggered": bool(triggered),
            "worker_status": str(worker_status or ""),
            "worker_elapsed_ms": float(worker_elapsed_ms),
            "worker_pid": worker_pid,
            "worker_returncode": worker_returncode,
        }
        if worker_stdout:
            metadata["worker_stdout"] = _truncate_text(worker_stdout)
        if worker_stderr:
            metadata["worker_stderr"] = _truncate_text(worker_stderr)
        return metadata

    def _attach_result_hard_timeout_metadata(
        self,
        result: Dict[str, Any],
        *,
        timeout_seconds: float,
        triggered: bool,
        worker_status: str,
        worker_elapsed_ms: float,
        worker_pid: Any = None,
        worker_returncode: Any = None,
        worker_stdout: Any = None,
        worker_stderr: Any = None,
    ) -> None:
        metadata = self._result_hard_timeout_metadata(
            timeout_seconds=timeout_seconds,
            triggered=triggered,
            worker_status=worker_status,
            worker_elapsed_ms=worker_elapsed_ms,
            worker_pid=worker_pid,
            worker_returncode=worker_returncode,
            worker_stdout=worker_stdout,
            worker_stderr=worker_stderr,
        )
        result["result_isolation"] = "subprocess"
        result["hard_timeout_triggered"] = bool(triggered)
        result["result_hard_timeout"] = metadata
        metrics = result.setdefault("metrics", {})
        if isinstance(metrics, dict):
            metrics["hard_timeout_triggered"] = bool(triggered)
            metrics["result_isolation"] = "subprocess"
        output = result.get("output")
        if isinstance(output, dict):
            output_metadata = output.setdefault("metadata", {})
            if isinstance(output_metadata, dict):
                output_metadata["result_hard_timeout"] = metadata

    def run_benchmark(
        self,
        benchmark_path: str | Path = "experiments/benchmark.json",
        *,
        methods: Optional[Iterable[ExperimentMethod]] = None,
        repeats: Optional[int] = None,
        run_id: Optional[str] = None,
        system_variant: Optional[str] = None,
        model_config_name: Optional[str] = None,
        csv_path: Optional[str | Path] = None,
        json_path: Optional[str | Path] = None,
        summary_path: Optional[str | Path] = None,
        paper_tables_path: Optional[str | Path] = None,
        manifest_path: Optional[str | Path] = None,
        resume: bool = False,
    ) -> List[Dict[str, Any]]:
        """Run all benchmark cases through all requested methods."""
        return asyncio.run(
            self.arun_benchmark(
                benchmark_path,
                methods=methods,
                repeats=repeats,
                run_id=run_id,
                system_variant=system_variant,
                model_config_name=model_config_name,
                csv_path=csv_path,
                json_path=json_path,
                summary_path=summary_path,
                paper_tables_path=paper_tables_path,
                manifest_path=manifest_path,
                resume=resume,
            )
        )

    async def arun_benchmark(
        self,
        benchmark_path: str | Path = "experiments/benchmark.json",
        *,
        methods: Optional[Iterable[ExperimentMethod]] = None,
        repeats: Optional[int] = None,
        run_id: Optional[str] = None,
        system_variant: Optional[str] = None,
        model_config_name: Optional[str] = None,
        csv_path: Optional[str | Path] = None,
        json_path: Optional[str | Path] = None,
        summary_path: Optional[str | Path] = None,
        paper_tables_path: Optional[str | Path] = None,
        manifest_path: Optional[str | Path] = None,
        resume: bool = False,
    ) -> List[Dict[str, Any]]:
        benchmark_file = Path(benchmark_path)
        benchmark_document = json.loads(benchmark_file.read_text(encoding="utf-8"))
        cases = self.load_benchmark(benchmark_file)
        selected_methods = [
            self._normalize_method(method) for method in (methods or self.METHODS)
        ]
        validate_method_fairness_contract(selected_methods)
        effective_repeats = self.repeats if repeats is None else _validate_repeats(repeats)
        effective_run_id = str(run_id or self.run_id)

        benchmark_output_dir = self._benchmark_output_dir(effective_run_id)
        if csv_path is None:
            csv_path = benchmark_output_dir / BENCHMARK_RESULTS_CSV_NAME
        if json_path is None:
            json_path = benchmark_output_dir / BENCHMARK_RESULTS_JSON_NAME
        if summary_path is None:
            summary_path = benchmark_output_dir / "evaluation_summary.json"
        if paper_tables_path is None:
            paper_tables_path = benchmark_output_dir / "paper_tables.md"
        if manifest_path is None:
            manifest_path = benchmark_output_dir / "experiment_manifest.json"
        checkpoint_csv_path = benchmark_output_dir / BENCHMARK_CHECKPOINT_CSV_NAME
        checkpoint_json_path = benchmark_output_dir / BENCHMARK_CHECKPOINT_JSON_NAME
        resume_state_path = benchmark_output_dir / BENCHMARK_RESUME_STATE_NAME
        resume_contract = self._build_benchmark_resume_contract(
            benchmark_path=benchmark_file,
            benchmark_document=benchmark_document,
            run_id=effective_run_id,
            methods=selected_methods,
            repeats=effective_repeats,
            system_variant=system_variant,
            model_config_name=model_config_name,
        )
        planned_keys = self._planned_benchmark_resume_keys(
            cases,
            methods=selected_methods,
            repeats=effective_repeats,
            repeat_index_start=self.repeat_index,
        )
        planned_key_index = {key: index for index, key in enumerate(planned_keys)}

        results: List[Dict[str, Any]] = []
        completed_by_key: Dict[tuple[str, str, str, int], Dict[str, Any]] = {}
        resume_events: List[Dict[str, Any]] = []
        if resume:
            resume_load = self._load_resume_checkpoint(
                checkpoint_json_path=checkpoint_json_path,
                final_json_path=Path(json_path),
                resume_state_path=resume_state_path,
                current_contract=resume_contract,
                planned_keys=planned_keys,
            )
            results = list(resume_load["results"])
            completed_by_key = {
                self._resume_key_from_result(result): result
                for result in results
            }
            resume_events.extend(resume_load.get("resume_events") or [])
            resume_events.append(
                {
                    "event": "resume_started",
                    "created_at": datetime.utcnow().isoformat() + "Z",
                    "loaded_result_count": len(results),
                    "source": resume_load.get("source"),
                }
            )
        self._write_benchmark_resume_state(
            resume_state_path,
            contract=resume_contract,
            status="running",
            completed_results=results,
            expected_result_count=len(planned_keys),
            resume_enabled=bool(resume),
            resume_events=resume_events,
        )
        for repeat_offset in range(effective_repeats):
            repeat_index = self.repeat_index + repeat_offset
            for case in cases:
                case_methods = self._ordered_methods_for_case(
                    selected_methods,
                    case_id=self._benchmark_case_order_id(case),
                    repeat_index=repeat_index,
                )
                if self._is_scenario_case(case):
                    for method in case_methods:
                        def _checkpoint_scenario_result(result: Dict[str, Any]) -> None:
                            self._record_new_resume_result(
                                result,
                                results=results,
                                completed_by_key=completed_by_key,
                            )
                            self._export_benchmark_checkpoint(
                                self._sort_results_for_resume(results, planned_key_index),
                                csv_path=checkpoint_csv_path,
                                json_path=checkpoint_json_path,
                            )
                            self._write_benchmark_resume_state(
                                resume_state_path,
                                contract=resume_contract,
                                status="running",
                                completed_results=results,
                                expected_result_count=len(planned_keys),
                                resume_enabled=bool(resume),
                                resume_events=resume_events,
                            )

                        scenario_results = await self._arun_scenario_case(
                            case,
                            method=method,
                            run_id=effective_run_id,
                            repeat_index=repeat_index,
                            system_variant=system_variant,
                            model_config_name=model_config_name,
                            completed_results_by_key=completed_by_key,
                            on_new_result=_checkpoint_scenario_result,
                        )
                        for result in scenario_results:
                            self._record_new_resume_result(
                                result,
                                results=results,
                                completed_by_key=completed_by_key,
                            )
                        self._export_benchmark_checkpoint(
                            self._sort_results_for_resume(results, planned_key_index),
                            csv_path=checkpoint_csv_path,
                            json_path=checkpoint_json_path,
                        )
                        self._write_benchmark_resume_state(
                            resume_state_path,
                            contract=resume_contract,
                            status="running",
                            completed_results=results,
                            expected_result_count=len(planned_keys),
                            resume_enabled=bool(resume),
                            resume_events=resume_events,
                        )
                    continue

                for method in case_methods:
                    planned_key = self._resume_key_for_case(
                        case,
                        method=method,
                        repeat_index=repeat_index,
                    )
                    if planned_key in completed_by_key:
                        continue
                    result = await self.arun(
                        case,
                        method=method,
                        run_id=effective_run_id,
                        repeat_index=repeat_index,
                        system_variant=system_variant,
                        model_config_name=model_config_name,
                    )
                    self._record_new_resume_result(
                        result,
                        results=results,
                        completed_by_key=completed_by_key,
                    )
                    self._export_benchmark_checkpoint(
                        self._sort_results_for_resume(results, planned_key_index),
                        csv_path=checkpoint_csv_path,
                        json_path=checkpoint_json_path,
                    )
                    self._write_benchmark_resume_state(
                        resume_state_path,
                        contract=resume_contract,
                        status="running",
                        completed_results=results,
                        expected_result_count=len(planned_keys),
                        resume_enabled=bool(resume),
                        resume_events=resume_events,
                    )

        results = self._sort_results_for_resume(results, planned_key_index)
        self.export_csv(results, csv_path)
        self.export_json(results, json_path)
        summary = self.export_evaluation_summary(results, summary_path)
        self.export_paper_tables(summary, paper_tables_path)
        self._write_benchmark_resume_state(
            resume_state_path,
            contract=resume_contract,
            status="completed",
            completed_results=results,
            expected_result_count=len(planned_keys),
            resume_enabled=bool(resume),
            resume_events=resume_events,
        )
        self.write_experiment_manifest(
            benchmark_path=benchmark_file,
            output_path=manifest_path,
            run_id=effective_run_id,
            repeats=effective_repeats,
            methods=selected_methods,
            method_order_seed=self.method_order_seed,
            system_variant=system_variant,
            model_config_name=model_config_name,
            result_paths={
                "csv": csv_path,
                "json": json_path,
                "summary": summary_path,
                "paper_tables": paper_tables_path,
                "resume_state": resume_state_path,
                "checkpoint_csv": checkpoint_csv_path,
                "checkpoint_json": checkpoint_json_path,
            },
            resume_state_path=resume_state_path,
        )
        return results

    def _build_benchmark_resume_contract(
        self,
        *,
        benchmark_path: Path,
        benchmark_document: Any,
        run_id: str,
        methods: List[ExperimentMethod],
        repeats: int,
        system_variant: Optional[str],
        model_config_name: Optional[str],
    ) -> Dict[str, Any]:
        base_url = os.getenv("LLM_BASE_URL") or settings.llm.base_url
        model = os.getenv("LLM_MODEL") or settings.llm.model
        resolved_system_variant = _optional_text(system_variant) or self.system_variant or "per_method"
        resolved_model_config = _optional_text(model_config_name) or self.model_config_name
        qweather_snapshot = qweather_snapshot_summary()
        intercity_snapshot = intercity_transport_snapshot_summary()
        budget_gold_manifest = _budget_gold_manifest_summary()
        return {
            "schema_version": EXPERIMENT_RESUME_CONTRACT_SCHEMA_VERSION,
            "run_id": str(run_id),
            "git_commit": _git_commit(),
            "dataset": {
                "path": benchmark_path.as_posix(),
                "sha256": canonical_json_sha256(benchmark_document),
                "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
            },
            "methods": list(methods),
            "method_contract_sha256": method_fairness_contract_hash(methods),
            "repeats": _validate_repeats(repeats),
            "repeat_index_start": self.repeat_index,
            "method_order_seed": self.method_order_seed,
            "system_variant": resolved_system_variant,
            "model_config_name": resolved_model_config,
            "model_config": {
                "provider": _llm_provider_from_base_url(base_url),
                "base_url": str(base_url),
                "model": str(model),
                "temperature": _environment_float("LLM_TEMPERATURE", settings.llm.temperature),
                "max_tokens": _environment_int("LLM_MAX_TOKENS", settings.llm.max_tokens),
                "timeout_seconds": _environment_int("LLM_TIMEOUT", settings.llm.timeout),
                "result_soft_timeout_seconds": _experiment_result_timeout_seconds(),
                "result_hard_timeout_seconds": _experiment_result_hard_timeout_seconds(),
                "result_hard_timeout_mode": (
                    "subprocess_per_result"
                    if _experiment_result_hard_timeout_seconds()
                    else "disabled"
                ),
                "retry_max_attempts": _environment_int(
                    "LLM_RETRY_MAX_ATTEMPTS",
                    settings.llm.retry_max_attempts,
                ),
                "reasoning_effort": _environment_text("LLM_REASONING_EFFORT"),
                "deterministic_research_final_answer": _environment_bool(
                    "EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER",
                    False,
                ),
            },
            "runtime_config": {
                "strict_mode": is_experiment_strict_mode(),
                "cache_disabled": is_experiment_cache_disabled(),
                "trace_save_user_message": _environment_bool("TRACE_SAVE_USER_MESSAGE", False),
            },
            "prompt_versions": {
                "structured_llm_output": STRUCTURED_LLM_OUTPUT_PROMPT_VERSION,
                "research_agent": RESEARCH_AGENT_PROMPT_VERSION,
            },
            "method_controls": {
                "research_agent_decision_normalizer_enabled": (
                    self.enable_research_agent_decision_normalizer
                ),
                "research_agent_decision_normalizer_version": (
                    RESEARCH_AGENT_DECISION_NORMALIZER_VERSION
                ),
            },
            "offline_data": {
                "fixed_data_combined_sha256": self.fixed_data_manifest.get("combined_sha256"),
                "qweather_snapshot_id": qweather_snapshot.get("snapshot_id"),
                "qweather_combined_sha256": qweather_snapshot.get("combined_sha256"),
                "intercity_snapshot_id": intercity_snapshot.get("snapshot_id"),
                "intercity_combined_sha256": intercity_snapshot.get("combined_sha256"),
                "budget_gold_path": budget_gold_manifest.get("path"),
                "budget_gold_file_sha256": budget_gold_manifest.get("file_sha256"),
                "budget_gold_review_status": budget_gold_manifest.get("review_status"),
                "budget_gold_artifact_hashes": budget_gold_manifest.get("artifact_hashes") or {},
            },
        }

    def _planned_benchmark_resume_keys(
        self,
        cases: List[Dict[str, Any]],
        *,
        methods: List[ExperimentMethod],
        repeats: int,
        repeat_index_start: int,
    ) -> List[tuple[str, str, str, int]]:
        keys: List[tuple[str, str, str, int]] = []
        for repeat_offset in range(repeats):
            repeat_index = repeat_index_start + repeat_offset
            for case in cases:
                case_methods = self._ordered_methods_for_case(
                    methods,
                    case_id=self._benchmark_case_order_id(case),
                    repeat_index=repeat_index,
                )
                if self._is_scenario_case(case):
                    scenario_id = self._scenario_id(case)
                    turns = self._scenario_turns(case)
                    for method in case_methods:
                        for turn_index, turn in enumerate(turns):
                            turn_id = self._scenario_resume_turn_id(
                                case,
                                turn,
                                turn_index=turn_index,
                            )
                            keys.append(
                                self._resume_key(
                                    scenario_id,
                                    turn_id,
                                    method,
                                    repeat_index,
                                )
                            )
                    continue
                for method in case_methods:
                    keys.append(
                        self._resume_key_for_case(
                            case,
                            method=method,
                            repeat_index=repeat_index,
                        )
                    )
        return keys

    def _load_resume_checkpoint(
        self,
        *,
        checkpoint_json_path: Path,
        final_json_path: Path,
        resume_state_path: Path,
        current_contract: Mapping[str, Any],
        planned_keys: List[tuple[str, str, str, int]],
    ) -> Dict[str, Any]:
        if not resume_state_path.exists():
            raise RuntimeError(
                f"benchmark resume state is missing: {resume_state_path}"
            )
        try:
            resume_state = json.loads(resume_state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"benchmark resume state is invalid: {exc}") from exc
        if not isinstance(resume_state, dict):
            raise RuntimeError("benchmark resume state must be a JSON object")
        if resume_state.get("schema_version") != EXPERIMENT_RESUME_SCHEMA_VERSION:
            raise RuntimeError(
                "benchmark resume state schema mismatch: "
                f"{resume_state.get('schema_version')}"
            )
        mismatches = self._resume_contract_mismatches(
            resume_state.get("contract"),
            current_contract,
        )
        if mismatches:
            details = "\n".join(f"- {item}" for item in mismatches)
            raise RuntimeError(f"benchmark resume contract mismatch:\n{details}")

        checkpoint_results = self._read_resume_results(checkpoint_json_path)
        final_results = self._read_resume_results(final_json_path)
        source = None
        results: List[Dict[str, Any]] = []
        if checkpoint_results or final_results:
            if len(final_results) > len(checkpoint_results):
                source = final_json_path.as_posix()
                results = final_results
            else:
                source = checkpoint_json_path.as_posix()
                results = checkpoint_results
        else:
            source = "resume_state_only"
        self._validate_resume_results(
            results,
            planned_keys=planned_keys,
            run_id=str(current_contract.get("run_id") or ""),
        )
        return {
            "results": results,
            "source": source,
            "resume_events": list(resume_state.get("resume_events") or []),
        }

    def _read_resume_results(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"benchmark resume results are invalid: {path}: {exc}") from exc
        if not isinstance(value, list):
            raise RuntimeError(f"benchmark resume results must be a JSON list: {path}")
        return [item for item in value if isinstance(item, dict)]

    def _validate_resume_results(
        self,
        results: List[Dict[str, Any]],
        *,
        planned_keys: List[tuple[str, str, str, int]],
        run_id: str,
    ) -> None:
        planned = set(planned_keys)
        seen: set[tuple[str, str, str, int]] = set()
        errors: List[str] = []
        for index, result in enumerate(results, start=1):
            if str(result.get("run_id") or "") != run_id:
                errors.append(f"row {index}: run_id mismatch")
                continue
            try:
                key = self._resume_key_from_result(result)
            except ValueError as exc:
                errors.append(f"row {index}: {exc}")
                continue
            if key in seen:
                errors.append(f"row {index}: duplicate result key {self._resume_key_label(key)}")
            seen.add(key)
            if key not in planned:
                errors.append(f"row {index}: result key is not part of this benchmark plan {self._resume_key_label(key)}")
        if len(results) > len(planned_keys):
            errors.append(
                f"completed result count exceeds planned count: {len(results)} > {len(planned_keys)}"
            )
        if errors:
            details = "\n".join(f"- {error}" for error in errors)
            raise RuntimeError(f"benchmark resume checkpoint is not reusable:\n{details}")

    def _resume_contract_mismatches(
        self,
        previous_contract: Any,
        current_contract: Mapping[str, Any],
    ) -> List[str]:
        if not isinstance(previous_contract, Mapping):
            return ["previous resume contract is missing or invalid"]
        checks = (
            ("run_id",),
            ("git_commit",),
            ("dataset", "sha256"),
            ("method_contract_sha256",),
            ("methods",),
            ("repeats",),
            ("repeat_index_start",),
            ("method_order_seed",),
            ("system_variant",),
            ("model_config_name",),
            ("model_config", "base_url"),
            ("model_config", "model"),
            ("model_config", "temperature"),
            ("model_config", "max_tokens"),
            ("model_config", "timeout_seconds"),
            ("model_config", "retry_max_attempts"),
            ("model_config", "reasoning_effort"),
            ("model_config", "deterministic_research_final_answer"),
            ("runtime_config", "strict_mode"),
            ("runtime_config", "cache_disabled"),
            ("runtime_config", "trace_save_user_message"),
            ("method_controls", "research_agent_decision_normalizer_enabled"),
            ("method_controls", "research_agent_decision_normalizer_version"),
            ("offline_data", "fixed_data_combined_sha256"),
            ("offline_data", "qweather_snapshot_id"),
            ("offline_data", "qweather_combined_sha256"),
            ("offline_data", "intercity_snapshot_id"),
            ("offline_data", "intercity_combined_sha256"),
            ("offline_data", "budget_gold_file_sha256"),
            ("offline_data", "budget_gold_review_status"),
            ("offline_data", "budget_gold_artifact_hashes"),
        )
        mismatches: List[str] = []
        for path in checks:
            previous = _nested_get(previous_contract, path)
            current = _nested_get(current_contract, path)
            if previous != current:
                mismatches.append(
                    f"{'.'.join(path)} changed: previous={previous!r}, current={current!r}"
                )
        return mismatches

    def _write_benchmark_resume_state(
        self,
        path: Path,
        *,
        contract: Mapping[str, Any],
        status: str,
        completed_results: List[Dict[str, Any]],
        expected_result_count: int,
        resume_enabled: bool,
        resume_events: List[Dict[str, Any]],
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        sorted_keys = [
            self._resume_key_to_document(self._resume_key_from_result(result))
            for result in completed_results
        ]
        completed_key_count = len({self._resume_key_from_result(result) for result in completed_results})
        state = {
            "schema_version": EXPERIMENT_RESUME_SCHEMA_VERSION,
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "status": status,
            "resume_enabled_for_this_invocation": bool(resume_enabled),
            "contract": dict(contract),
            "progress": {
                "completed_result_count": len(completed_results),
                "completed_unique_key_count": completed_key_count,
                "expected_result_count": expected_result_count,
                "remaining_result_count": max(0, expected_result_count - completed_key_count),
            },
            "completed_keys": sorted_keys,
            "resume_events": list(resume_events),
            "policy": {
                "unique_key": ["case_id", "turn_id", "method", "repeat_index"],
                "skip_completed_results": True,
                "failed_results_are_preserved": True,
                "contract_mismatch_requires_new_run_id": True,
            },
        }
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _record_new_resume_result(
        self,
        result: Dict[str, Any],
        *,
        results: List[Dict[str, Any]],
        completed_by_key: Dict[tuple[str, str, str, int], Dict[str, Any]],
    ) -> None:
        key = self._resume_key_from_result(result)
        if key in completed_by_key:
            raise RuntimeError(
                f"benchmark resume duplicate result key: {self._resume_key_label(key)}"
            )
        completed_by_key[key] = result
        results.append(result)

    def _sort_results_for_resume(
        self,
        results: List[Dict[str, Any]],
        planned_key_index: Mapping[tuple[str, str, str, int], int],
    ) -> List[Dict[str, Any]]:
        fallback = len(planned_key_index) + 1

        def _order(item: tuple[int, Dict[str, Any]]) -> tuple[int, int]:
            original_index, result = item
            try:
                key = self._resume_key_from_result(result)
            except ValueError:
                return (fallback, original_index)
            return (planned_key_index.get(key, fallback), original_index)

        return [result for _, result in sorted(enumerate(results), key=_order)]

    def _resume_key_for_case(
        self,
        case: Mapping[str, Any],
        *,
        method: ExperimentMethod,
        repeat_index: int,
    ) -> tuple[str, str, str, int]:
        case_id = str(case.get("case_id") or case.get("id") or canonical_json_sha256(case))
        return self._resume_key(case_id, SINGLE_TURN_RESUME_ID, method, repeat_index)

    def _resume_key_from_result(
        self,
        result: Mapping[str, Any],
    ) -> tuple[str, str, str, int]:
        case_id = str(result.get("case_id") or result.get("scenario_id") or "").strip()
        if not case_id:
            raise ValueError("missing case_id")
        method = self._normalize_method(str(result.get("method") or ""))
        return self._resume_key(
            case_id,
            result.get("turn_id"),
            method,
            _validate_repeat_index(result.get("repeat_index")),
        )

    def _resume_key(
        self,
        case_id: Any,
        turn_id: Any,
        method: ExperimentMethod,
        repeat_index: int,
    ) -> tuple[str, str, str, int]:
        normalized_turn_id = (
            SINGLE_TURN_RESUME_ID
            if turn_id is None
            else str(turn_id).strip()
        )
        return (
            str(case_id).strip(),
            normalized_turn_id,
            self._normalize_method(method),
            _validate_repeat_index(repeat_index),
        )

    def _resume_key_to_document(
        self,
        key: tuple[str, str, str, int],
    ) -> Dict[str, Any]:
        case_id, turn_id, method, repeat_index = key
        return {
            "case_id": case_id,
            "turn_id": turn_id or None,
            "method": method,
            "repeat_index": repeat_index,
        }

    def _resume_key_label(self, key: tuple[str, str, str, int]) -> str:
        case_id, turn_id, method, repeat_index = key
        turn_part = turn_id or "<single>"
        return f"{case_id}::{turn_part}::{method}::r{repeat_index}"

    def _scenario_resume_turn_id(
        self,
        scenario: Mapping[str, Any],
        turn: Mapping[str, Any],
        *,
        turn_index: int,
    ) -> str:
        base = {
            key: value
            for key, value in scenario.items()
            if key not in {"turns", "previous_state", "method_previous_state"}
        }
        turn_case = {**base, **turn}
        return str(
            turn_case.get("turn_id")
            or turn_case.get("id")
            or f"turn_{turn_index + 1:02d}"
        )

    def _manifest_resume_summary(
        self,
        resume_state_path: Optional[str | Path],
    ) -> Dict[str, Any]:
        if resume_state_path is None:
            return {
                "schema_version": EXPERIMENT_RESUME_SCHEMA_VERSION,
                "state_saved": False,
                "resume_supported": True,
            }
        path = Path(resume_state_path)
        summary: Dict[str, Any] = {
            "schema_version": EXPERIMENT_RESUME_SCHEMA_VERSION,
            "state_saved": path.exists(),
            "path": path.as_posix(),
            "resume_supported": True,
        }
        if not path.exists():
            return summary
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            summary["error"] = str(exc)
            return summary
        if isinstance(state, dict):
            summary.update(
                {
                    "status": state.get("status"),
                    "resume_enabled_for_this_invocation": state.get(
                        "resume_enabled_for_this_invocation"
                    ),
                    "progress": state.get("progress") or {},
                    "resume_event_count": len(state.get("resume_events") or []),
                    "unique_key": _nested_get(state, ("policy", "unique_key")),
                    "contract_sha256": canonical_json_sha256(state.get("contract") or {}),
                }
            )
        return summary

    def _export_benchmark_checkpoint(
        self,
        results: List[Dict[str, Any]],
        *,
        csv_path: str | Path,
        json_path: str | Path,
    ) -> None:
        if not results:
            return
        self.export_csv(results, csv_path)
        self.export_json(results, json_path)

    async def _arun_scenario_case(
        self,
        scenario: Dict[str, Any],
        *,
        method: ExperimentMethod,
        run_id: str,
        repeat_index: int,
        system_variant: Optional[str],
        model_config_name: Optional[str],
        completed_results_by_key: Optional[Mapping[tuple[str, str, str, int], Dict[str, Any]]] = None,
        on_new_result: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> List[Dict[str, Any]]:
        """Run a multi-turn scenario with method-local state transfer.

        Formal multi-turn cases must not inject an oracle ``previous_state``.
        Instead, every method receives only the state produced by its own
        immediately preceding turn.  This keeps M3 reuse auditable while M2
        still has enough prior context to rerun the full chain against changed
        slots.
        """
        scenario_id = self._scenario_id(scenario)
        turns = self._scenario_turns(scenario)
        previous_state: Optional[Dict[str, Any]] = None
        dialogue_history = self._scenario_initial_history(scenario)
        results: List[Dict[str, Any]] = []
        completed = completed_results_by_key or {}

        for turn_index, turn in enumerate(turns):
            turn_case = self._scenario_turn_case(
                scenario,
                turn,
                scenario_id=scenario_id,
                turn_index=turn_index,
                turn_count=len(turns),
                dialogue_history=dialogue_history,
                previous_state=previous_state,
            )
            planned_key = self._resume_key(
                scenario_id,
                turn_case.get("turn_id"),
                method,
                repeat_index,
            )
            if planned_key in completed:
                result = completed[planned_key]
            else:
                result = await self.arun(
                    turn_case,
                    method=method,
                    run_id=run_id,
                    repeat_index=repeat_index,
                    system_variant=system_variant,
                    model_config_name=model_config_name,
                )
                self._attach_scenario_result_metadata(
                    result,
                    scenario_id=scenario_id,
                    turn_id=str(turn_case["turn_id"]),
                    turn_index=turn_index,
                    turn_count=len(turns),
                    target_turn=bool(turn_case.get("target_turn")),
                    previous_state=previous_state,
                    method=method,
                )
                if on_new_result is not None:
                    on_new_result(result)
                else:
                    results.append(result)
            previous_state = self._method_previous_state_from_result(result)
            dialogue_history = self._append_scenario_dialogue_history(
                dialogue_history,
                turn_case,
                result,
            )
        return results

    def _is_scenario_case(self, case: Dict[str, Any]) -> bool:
        return isinstance(case.get("turns"), list) and bool(case.get("turns"))

    def _scenario_id(self, scenario: Dict[str, Any]) -> str:
        return str(
            scenario.get("scenario_id")
            or scenario.get("case_id")
            or scenario.get("id")
            or self.generate_experiment_id("scenario")
        )

    def _scenario_turns(self, scenario: Dict[str, Any]) -> List[Dict[str, Any]]:
        turns = scenario.get("turns")
        if not isinstance(turns, list) or not turns:
            raise ValueError("scenario case must contain a non-empty turns list")
        normalized: List[Dict[str, Any]] = []
        for index, turn in enumerate(turns):
            if not isinstance(turn, dict):
                raise ValueError(f"scenario turn {index + 1} must be an object")
            normalized.append(turn)
        return normalized

    def _scenario_initial_history(self, scenario: Dict[str, Any]) -> List[Any]:
        for key in ("dialogue_history", "history"):
            value = scenario.get(key)
            if isinstance(value, list):
                return list(value)
        return []

    def _scenario_turn_case(
        self,
        scenario: Dict[str, Any],
        turn: Dict[str, Any],
        *,
        scenario_id: str,
        turn_index: int,
        turn_count: int,
        dialogue_history: List[Any],
        previous_state: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        base = {
            key: value
            for key, value in scenario.items()
            if key not in {"turns", "previous_state", "method_previous_state"}
        }
        turn_case = {**base, **turn}
        turn_id = str(turn_case.get("turn_id") or turn_case.get("id") or f"turn_{turn_index + 1:02d}")
        turn_history = list(dialogue_history)
        for key in ("dialogue_history", "history"):
            value = turn.get(key)
            if isinstance(value, list):
                turn_history.extend(value)

        turn_case.update(
            {
                "case_id": scenario_id,
                "scenario_id": scenario_id,
                "turn_id": turn_id,
                "turn_index": turn_index,
                "scenario_turn_count": turn_count,
                "target_turn": _scenario_turn_is_target(turn_case, turn_index, turn_count),
                "dialogue_history": turn_history,
            }
        )
        if previous_state is not None:
            turn_case["previous_state"] = previous_state
            turn_case["method_previous_state"] = previous_state
        return turn_case

    def _attach_scenario_result_metadata(
        self,
        result: Dict[str, Any],
        *,
        scenario_id: str,
        turn_id: str,
        turn_index: int,
        turn_count: int,
        target_turn: bool,
        previous_state: Optional[Dict[str, Any]],
        method: ExperimentMethod,
    ) -> None:
        previous_state_audit = self._scenario_previous_state_audit(
            previous_state,
            method=method,
            turn_index=turn_index,
        )
        result["scenario_id"] = scenario_id
        result["turn_id"] = turn_id
        result["turn_index"] = turn_index
        result["scenario_turn_count"] = turn_count
        result["target_turn"] = target_turn
        result["method_previous_state_policy"] = (
            "method_local_previous_state_from_prior_turn_output"
        )
        result["method_previous_state_audit"] = previous_state_audit
        result["previous_state_provided"] = previous_state_audit["previous_state_provided"]
        result["previous_state_schema_version"] = previous_state_audit.get("schema_version")
        result["previous_state_method"] = previous_state_audit.get("method")
        result["previous_state_turn_id"] = previous_state_audit.get("turn_id")
        result["previous_state_turn_index"] = previous_state_audit.get("turn_index")
        result["previous_state_is_method_local"] = previous_state_audit[
            "is_method_local"
        ]
        result["previous_state_is_prior_turn"] = previous_state_audit["is_prior_turn"]
        result["previous_state_has_evaluation"] = previous_state_audit["has_evaluation"]
        result["previous_state_has_metrics"] = previous_state_audit["has_metrics"]

    def _scenario_previous_state_audit(
        self,
        previous_state: Optional[Dict[str, Any]],
        *,
        method: ExperimentMethod,
        turn_index: int,
    ) -> Dict[str, Any]:
        if not isinstance(previous_state, dict):
            return {
                "previous_state_provided": False,
                "schema_version": None,
                "method": None,
                "turn_id": None,
                "turn_index": None,
                "is_method_local": turn_index == 0,
                "is_prior_turn": turn_index == 0,
                "has_evaluation": False,
                "has_metrics": False,
            }
        previous_turn_index = _optional_int(previous_state.get("turn_index"))
        return {
            "previous_state_provided": True,
            "schema_version": previous_state.get("schema_version"),
            "method": previous_state.get("method"),
            "turn_id": previous_state.get("turn_id"),
            "turn_index": previous_turn_index,
            "is_method_local": str(previous_state.get("method") or "") == str(method),
            "is_prior_turn": (
                previous_turn_index is not None
                and previous_turn_index == turn_index - 1
            ),
            "has_evaluation": "evaluation" in previous_state,
            "has_metrics": "metrics" in previous_state,
        }

    def _append_scenario_dialogue_history(
        self,
        dialogue_history: List[Any],
        turn_case: Dict[str, Any],
        result: Dict[str, Any],
    ) -> List[Any]:
        output = result.get("output") if isinstance(result.get("output"), dict) else {}
        assistant_item = {
            "role": "assistant",
            "turn_id": turn_case.get("turn_id"),
            "method": result.get("method"),
            "content": str(output.get("final_answer") or ""),
            "output": {
                key: output.get(key)
                for key in (
                    "schema_version",
                    "task_type",
                    "attractions",
                    "trip_days",
                    "daily_itinerary",
                    "budget",
                    "weather",
                    "weather_adjustments",
                    "execution_status",
                )
                if output.get(key) is not None
            },
        }
        return [
            *dialogue_history,
            {
                "role": "user",
                "turn_id": turn_case.get("turn_id"),
                "content": str(turn_case.get("user_input") or ""),
            },
            assistant_item,
        ]

    def _method_previous_state_from_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        output = result.get("output") if isinstance(result.get("output"), dict) else {}
        raw_output = result.get("raw_output") if isinstance(result.get("raw_output"), dict) else {}
        trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
        trace_snapshot = {
            key: trace.get(key)
            for key in (
                "request_id",
                "session_id",
                "case_id",
                "run_id",
                "repeat_index",
                "method",
                "status",
                "planned_agents",
                "executed_agents",
                "planned_tools",
                "executed_tools",
                "tool_calls",
                "adaptive_scheduler",
            )
            if trace.get(key) is not None
        }
        previous_state = {
            "schema_version": METHOD_PREVIOUS_STATE_SCHEMA_VERSION,
            "case_id": result.get("case_id"),
            "scenario_id": result.get("scenario_id"),
            "turn_id": result.get("turn_id"),
            "turn_index": result.get("turn_index"),
            "method": result.get("method"),
            "status": result.get("status"),
            "execution_status": output.get("execution_status"),
            "output": output,
            "raw_output": raw_output,
            "trace": trace_snapshot,
        }
        recovered_slots = self._previous_goal_state_slots_from_state(previous_state)
        if recovered_slots:
            previous_state["slots"] = recovered_slots
        return previous_state

    def write_experiment_manifest(
        self,
        *,
        benchmark_path: str | Path,
        output_path: str | Path,
        run_id: Optional[str] = None,
        repeats: Optional[int] = None,
        methods: Optional[Iterable[ExperimentMethod]] = None,
        method_order_seed: Optional[int] = None,
        system_variant: Optional[str] = None,
        model_config_name: Optional[str] = None,
        result_paths: Optional[Dict[str, str | Path]] = None,
        resume_state_path: Optional[str | Path] = None,
    ) -> Dict[str, Any]:
        """Write reproducibility metadata for one benchmark run."""
        benchmark_file = Path(benchmark_path)
        raw_bytes = benchmark_file.read_bytes()
        document = json.loads(raw_bytes.decode("utf-8"))
        metadata = document if isinstance(document, dict) else {}
        dataset_id = metadata.get("dataset_id") or benchmark_file.stem
        dataset_version = (
            metadata.get("dataset_version")
            or metadata.get("version")
            or dataset_id
        )
        dataset_sha256 = canonical_json_sha256(document)
        cache_disabled = is_experiment_cache_disabled()
        strict_mode = is_experiment_strict_mode()
        base_url = os.getenv("LLM_BASE_URL") or settings.llm.base_url
        model = os.getenv("LLM_MODEL") or settings.llm.model
        temperature = _environment_float("LLM_TEMPERATURE", settings.llm.temperature)
        max_tokens = _environment_int("LLM_MAX_TOKENS", settings.llm.max_tokens)
        timeout_seconds = _environment_int("LLM_TIMEOUT", settings.llm.timeout)
        result_soft_timeout_seconds = _experiment_result_timeout_seconds()
        result_hard_timeout_seconds = _experiment_result_hard_timeout_seconds()
        result_hard_timeout_mode = (
            "subprocess_per_result" if result_hard_timeout_seconds else "disabled"
        )
        retry_max_attempts = _environment_int(
            "LLM_RETRY_MAX_ATTEMPTS",
            settings.llm.retry_max_attempts,
        )
        reasoning_effort = _environment_text("LLM_REASONING_EFFORT")
        deterministic_research_final_answer = _environment_bool(
            "EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER",
            False,
        )
        resolved_system_variant = _optional_text(system_variant) or self.system_variant
        resolved_model_config = (
            _optional_text(model_config_name) or self.model_config_name
        )
        mock_pricing = "fake" in str(model).lower() or "offline" in str(resolved_model_config).lower()
        llm_provider = _llm_provider_from_base_url(base_url)
        price_snapshot = build_price_snapshot(
            provider=llm_provider,
            model=model,
            mock=mock_pricing,
        )
        rule_catalog = load_rule_catalog()
        budget_gold_manifest = _budget_gold_manifest_summary()
        commit = _git_commit()
        git_status_short = list(self.git_status_short_at_start)
        working_tree_clean = len(git_status_short) == 0
        selected_methods = list(methods or self.METHODS)
        validate_method_fairness_contract(selected_methods)
        method_contract = build_method_fairness_contract(selected_methods)
        manifest = {
            "schema_version": "1.0",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "run_id": str(run_id or self.run_id),
            "dataset_id": str(dataset_id),
            "dataset_version": str(dataset_version),
            "dataset_path": benchmark_file.as_posix(),
            "dataset_sha256": dataset_sha256,
            "dataset_hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
            "dataset": {
                "id": str(dataset_id),
                "version": str(dataset_version),
                "path": benchmark_file.as_posix(),
                "sha256": dataset_sha256,
                "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
            },
            "benchmark_structure": _benchmark_structure_summary(document),
            "git_commit": commit,
            "working_tree_clean": working_tree_clean,
            "git_status_short": git_status_short,
            "git": {
                "commit": commit,
                "working_tree_clean": working_tree_clean,
                "status_short": git_status_short,
            },
            "formal_artifact_integrity": build_formal_artifact_integrity_report(),
            "methods": selected_methods,
            "method_fairness_contract": {
                **method_contract,
                "contract_sha256": method_fairness_contract_hash(selected_methods),
            },
            "method_order_seed": self.method_order_seed if method_order_seed is None else method_order_seed,
            "repeats": self.repeats if repeats is None else _validate_repeats(repeats),
            "repeat_index_start": self.repeat_index,
            "system_variant": resolved_system_variant or "per_method",
            "model_config_name": resolved_model_config,
            "provider": llm_provider,
            "base_url": str(base_url),
            "model": str(model),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout_seconds": timeout_seconds,
            "result_soft_timeout_seconds": result_soft_timeout_seconds,
            "result_hard_timeout_seconds": result_hard_timeout_seconds,
            "result_hard_timeout_mode": result_hard_timeout_mode,
            "retry_max_attempts": retry_max_attempts,
            "reasoning_effort": reasoning_effort,
            "deterministic_research_final_answer": deterministic_research_final_answer,
            "cache_enabled": not cache_disabled,
            "cache_disabled": cache_disabled,
            "strict_mode": strict_mode,
            "model_config": {
                "name": resolved_model_config,
                "provider": llm_provider,
                "base_url": str(base_url),
                "model": str(model),
                "temperature": temperature,
                "max_tokens": max_tokens,
                "timeout_seconds": timeout_seconds,
                "result_soft_timeout_seconds": result_soft_timeout_seconds,
                "result_hard_timeout_seconds": result_hard_timeout_seconds,
                "result_hard_timeout_mode": result_hard_timeout_mode,
                "retry_max_attempts": retry_max_attempts,
                "reasoning_effort": reasoning_effort,
                "deterministic_research_final_answer": deterministic_research_final_answer,
            },
            "runtime_config": {
                "schema_version": "ctp-experiment-runtime-config-v1",
                "provider": llm_provider,
                "base_url": str(base_url),
                "model": str(model),
                "temperature": temperature,
                "max_tokens": max_tokens,
                "timeout_seconds": timeout_seconds,
                "result_soft_timeout_seconds": result_soft_timeout_seconds,
                "result_hard_timeout_seconds": result_hard_timeout_seconds,
                "result_hard_timeout_mode": result_hard_timeout_mode,
                "retry_max_attempts": retry_max_attempts,
                "reasoning_effort": reasoning_effort,
                "deterministic_research_final_answer": deterministic_research_final_answer,
                "final_answer_generation_mode": (
                    "deterministic_research_evidence_renderer"
                    if deterministic_research_final_answer
                    else "llm_final_answer_generation"
                ),
                "strict_mode": strict_mode,
                "cache_disabled": cache_disabled,
                "trace_save_user_message": _environment_bool("TRACE_SAVE_USER_MESSAGE", False),
                "api_key_configured": bool(os.getenv("LLM_API_KEY") or settings.llm.is_configured),
                "mock_fallback_allowed": not strict_mode,
            },
            "prompt_versions": {
                "structured_llm_output": STRUCTURED_LLM_OUTPUT_PROMPT_VERSION,
                "research_agent": RESEARCH_AGENT_PROMPT_VERSION,
            },
            "method_controls": {
                "schema_version": "ctp-method-controls-v1",
                "research_agent_decision_normalizer_enabled": (
                    self.enable_research_agent_decision_normalizer
                ),
                "research_agent_decision_normalizer_version": (
                    RESEARCH_AGENT_DECISION_NORMALIZER_VERSION
                ),
                "deterministic_research_final_answer": deterministic_research_final_answer,
                "final_answer_generation_mode": (
                    "deterministic_research_evidence_renderer"
                    if deterministic_research_final_answer
                    else "llm_final_answer_generation"
                ),
            },
            "costing": {
                "schema_version": COSTING_SCHEMA_VERSION,
                "price_snapshot": price_snapshot,
                "price_snapshot_date": price_snapshot.get("price_snapshot_date"),
                "price_source_url": price_snapshot.get("price_source_url"),
                "input_token_unit_price": price_snapshot.get("input_token_unit_price"),
                "output_token_unit_price": price_snapshot.get("output_token_unit_price"),
                "price_unit": price_snapshot.get("price_unit"),
                "currency": price_snapshot.get("currency"),
                "actual_cost_policy": (
                    "provider-reported when available; mock calls record zero; "
                    "otherwise actual_cost is marked not_reported_by_provider"
                ),
            },
            "cache": {"enabled": not cache_disabled, "disabled": cache_disabled},
            "offline_data": {
                "enabled": True,
                "env": "TOURISM_FORMAL_EXPERIMENT_OFFLINE",
                "policy": "formal experiments use frozen local datasets and forbid real-time tourism APIs",
                "snapshot": self._offline_data_summary(),
                "qweather_snapshot": qweather_snapshot_summary(),
                "intercity_transport_snapshot": intercity_transport_snapshot_summary(),
            },
            "evaluation": {
                "schema_version": EVALUATION_SCHEMA_VERSION,
                "summary_schema_version": EVALUATION_SUMMARY_SCHEMA_VERSION,
                "catalog_id": rule_catalog.get("catalog_id"),
                "catalog_path": DEFAULT_RULE_CATALOG_PATH.as_posix(),
                "catalog_sha256": canonical_json_sha256(rule_catalog),
                "catalog_hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
                "guards": rule_catalog.get("evaluator_guards") or [],
                "budget_gold": budget_gold_manifest,
            },
            "results": {
                key: Path(value).as_posix()
                for key, value in (result_paths or {}).items()
            },
            "resume": self._manifest_resume_summary(resume_state_path),
        }
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    def _ordered_methods_for_benchmark(self, methods: List[ExperimentMethod]) -> List[ExperimentMethod]:
        """Backward-compatible helper for a synthetic benchmark-level order.

        Formal benchmark execution uses ``_ordered_methods_for_case`` so every
        case/repeat gets an independent deterministic shuffle.
        """
        return self._ordered_methods_for_case(
            methods,
            case_id="benchmark",
            repeat_index=self.repeat_index,
        )

    def _ordered_methods_for_case(
        self,
        methods: List[ExperimentMethod],
        *,
        case_id: str,
        repeat_index: int,
    ) -> List[ExperimentMethod]:
        ordered = list(methods)
        seed_material = f"{self.method_order_seed}:{repeat_index}:{case_id}"
        seed = int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:16], 16)
        random.Random(seed).shuffle(ordered)
        return ordered

    def _benchmark_case_order_id(self, case: Dict[str, Any]) -> str:
        return str(
            case.get("scenario_id")
            or case.get("case_id")
            or case.get("id")
            or canonical_json_sha256(case)
        )

    def _benchmark_output_dir(self, run_id: str) -> Path:
        if self.output_dir.name == run_id:
            return self.output_dir
        return self.output_dir / run_id

    def load_benchmark(self, benchmark_path: str | Path) -> List[Dict[str, Any]]:
        """Load benchmark.json or the existing data/cases thesis index."""
        path = Path(benchmark_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("cases"), list):
            return data["cases"]
        if isinstance(data, dict) and isinstance(data.get("case_files"), list):
            base = path.parent
            if path.name == "thesis_cases.json":
                base = path.parent
            cases = []
            for file_name in data["case_files"]:
                case_path = base / str(file_name)
                loaded = json.loads(case_path.read_text(encoding="utf-8"))
                cases.extend(self._cases_from_loaded_case_file(loaded))
            return cases
        raise ValueError(f"Unsupported benchmark format: {path}")

    @staticmethod
    def _cases_from_loaded_case_file(value: Any) -> List[Dict[str, Any]]:
        if isinstance(value, list):
            return [case for case in value if isinstance(case, dict)]
        if isinstance(value, dict) and isinstance(value.get("cases"), list):
            return [case for case in value["cases"] if isinstance(case, dict)]
        if isinstance(value, dict):
            return [value]
        return []

    def export_csv(self, results: List[Dict[str, Any]], output_path: str | Path) -> None:
        """Export one row per case/method run."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "scenario_id",
            "turn_id",
            "turn_index",
            "scenario_turn_count",
            "target_turn",
            "method_previous_state_policy",
            "previous_state_provided",
            "previous_state_schema_version",
            "previous_state_method",
            "previous_state_turn_id",
            "previous_state_turn_index",
            "previous_state_is_method_local",
            "previous_state_is_prior_turn",
            "previous_state_has_evaluation",
            "previous_state_has_metrics",
            "case_id",
            "method",
            "request_id",
            "run_id",
            "repeat_index",
            "system_variant",
            "model_config_name",
            "evaluation_mode",
            "status",
            "result_isolation",
            "hard_timeout_enabled",
            "hard_timeout_triggered",
            "hard_timeout_seconds",
            "hard_timeout_worker_status",
            "latency_ms",
            "ttft_ms",
            "intent",
            "route",
            "planned_agents",
            "executed_agents",
            "planned_tools",
            "executed_tools",
            "selected_agents",
            "selected_tools",
            "expected_tools",
            "tool_selection_accuracy",
            "intent_correct",
            "route_correct",
            "agents_correct",
            "hard_constraint_applicable_count",
            "hard_constraint_passed_count",
            "hard_constraint_failed_count",
            "hard_constraints_all_satisfied",
            "hcsr",
            "stsr",
            "evaluation_hcsr",
            "itcsr",
            "itcsr_applicable_count",
            "itcsr_passed_count",
            "itcsr_failed_count",
            "evaluation_failed_rule_count",
            "evaluation_failed_rule_ids",
            "agent_set_exact_match",
            "necessary_agent_coverage",
            "agent_selection_f1",
            "extra_agent_count",
            "duplicate_agent_count",
            "planned_actual_agent_consistency",
            "agent_execution_success_rate",
            "tool_set_exact_match",
            "necessary_tool_coverage",
            "tool_selection_f1",
            "extra_tool_count",
            "duplicate_tool_count",
            "forbidden_tool_call_count",
            "planned_actual_tool_consistency",
            "tool_call_success_rate",
            "tool_failure_count",
            "tool_failure_types",
            "total_tokens",
            "estimated_cost",
            "standardized_estimated_cost",
            "actual_cost",
            "cost_per_success",
            "m3_scheduler_name",
            "m3_task_type",
            "m3_clarification_required",
            "m3_clarification_field_count",
            "m3_decision_reasons",
            "m3_planned_agents",
            "m3_reused_agents",
            "m3_invalidated_agents",
            "m3_planned_tools",
            "m3_reused_tool_results",
            "m3_missing_reused_tool_results",
            "m3_m2_reference_agent_count",
            "m3_m2_reference_tool_count",
            "m3_planned_agent_count",
            "m3_executed_agent_count",
            "m3_reused_agent_count",
            "m3_invalidated_agent_count",
            "m3_planned_tool_count",
            "m3_executed_tool_count",
            "m3_expected_reused_tool_count",
            "m3_reused_tool_result_count",
            "m3_missing_reused_tool_result_count",
            "m3_agent_reuse_rate",
            "m3_tool_reuse_rate",
            "m3_reuse_hit_rate",
            "m3_agent_call_savings_vs_m2",
            "m3_tool_call_savings_vs_m2",
            "m3_agent_call_reduction_rate_vs_m2",
            "m3_tool_call_reduction_rate_vs_m2",
            "run_audit_schema_version",
            "planned_agent_count",
            "used_agent_count",
            "executed_agent_count",
            "agent_call_count",
            "successful_agent_call_count",
            "failed_agent_call_count",
            "duplicate_agent_call_count",
            "planned_executed_agent_coverage",
            "planned_tool_count",
            "called_tool_count",
            "executed_tool_count",
            "successful_tool_call_count",
            "failed_tool_call_count",
            "duplicate_tool_call_count",
            "planned_executed_tool_coverage",
            "llm_call_count",
            "llm_retry_attempt_count",
            "llm_retry_count",
            "llm_retry_error_count",
            "agent_llm_call_count",
            "api_call_count",
            "prompt_tokens",
            "completion_tokens",
            "agent_prompt_tokens",
            "agent_completion_tokens",
            "agent_total_tokens",
            "audit_standardized_estimated_cost",
            "audit_actual_cost",
            "llm_total_duration_ms",
            "agent_total_duration_ms",
            "tool_total_duration_ms",
            "api_total_duration_ms",
            "stage_total_duration_ms",
            "input_hash",
            "result_hash",
            "offline_data_sha256",
            "trace_file",
            "output_preview",
            "error",
        ]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for result in results:
                writer.writerow(self._flatten_result_for_csv(result))

    def export_json(self, results: List[Dict[str, Any]], output_path: str | Path) -> None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    def export_evaluation_summary(self, results: List[Dict[str, Any]], output_path: str | Path) -> Dict[str, Any]:
        summary = summarize_evaluation_results(results)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary

    def export_paper_tables(self, summary: Dict[str, Any], output_path: str | Path) -> str:
        table_text = render_paper_tables(summary)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(table_text, encoding="utf-8")
        return table_text

    # ------------------------------------------------------------------
    # Original metric helper API kept for compatibility
    # ------------------------------------------------------------------
    def create_experiment_context(
        self,
        experiment_case_id: str,
        collaboration_mode: str,
        review_mode: str,
        experiment_group: str = "",
    ) -> ExperimentContext:
        ctx = ExperimentContext(
            experiment_case_id=experiment_case_id,
            experiment_group=experiment_group,
            collaboration_mode=collaboration_mode,
            review_mode=review_mode,
            timestamp=datetime.utcnow().isoformat(),
        )
        ctx.structured_modules_enabled = {
            "poi_list": collaboration_mode == CollaborationMode.STRUCTURED_COLLABORATION.value,
            "daily_plans": collaboration_mode == CollaborationMode.STRUCTURED_COLLABORATION.value,
            "structured_budget": collaboration_mode == CollaborationMode.STRUCTURED_COLLABORATION.value,
            "structured_review": review_mode != ReviewModeExperiment.NO_REVIEW.value,
        }
        self.current_context = ctx
        return ctx

    def collect_experiment_metrics(
        self,
        attraction_result: Optional[Any] = None,
        itinerary_result: Optional[Any] = None,
        budget_result: Optional[Any] = None,
        review_result: Optional[Any] = None,
    ) -> ExperimentMetrics:
        return build_experiment_metrics(
            attraction_result=attraction_result,
            itinerary_result=itinerary_result,
            budget_result=budget_result,
            review_result=review_result,
            experiment_ctx=self.current_context,
        )

    def record_experiment(
        self,
        input_case: Dict[str, Any],
        result_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.current_context:
            return {}

        metrics = self.collect_experiment_metrics()
        record = build_experiment_record(
            experiment_case_id=self.current_context.experiment_case_id,
            collaboration_mode=self.current_context.collaboration_mode,
            review_mode=self.current_context.review_mode,
            input_case=input_case,
            metrics=metrics,
            result_snapshot=result_snapshot,
            experiment_group=self.current_context.experiment_group,
        )
        self.experiment_records.append(record)
        return record

    def generate_experiment_id(self, prefix: str = "exp") -> str:
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    def export_results(self, output_path: Optional[str] = None) -> List[Dict[str, Any]]:
        results = self.experiment_records
        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        return results

    def generate_comparison_table(
        self,
        records: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        records = records if records is not None else self.experiment_records
        if not records:
            return "暂无实验数据"

        if any("method" in record for record in records):
            lines = [
                "| Case ID | Method | Intent | Route | Tool Accuracy | TTFT(ms) | Latency(ms) |",
                "|--------|--------|--------|-------|---------------|----------|-------------|",
            ]
            for record in records:
                trace = record.get("trace") or {}
                metrics = record.get("metrics") or {}
                accuracy = metrics.get("tool_selection_accuracy")
                accuracy_text = "" if accuracy is None else f"{accuracy:.2f}"
                ttft = record.get("ttft_ms")
                ttft_text = "" if ttft is None else f"{ttft:.2f}"
                lines.append(
                    f"| {record.get('case_id', '')} "
                    f"| {record.get('method', '')} "
                    f"| {trace.get('intent', '')} "
                    f"| {trace.get('route', '')} "
                    f"| {accuracy_text} "
                    f"| {ttft_text} "
                    f"| {record.get('latency_ms', 0):.2f} |"
                )
            return "\n".join(lines)

        lines = [
            "| 案例ID | 协作模式 | Review模式 | POI数量 | 天数 | 预算超限 | Overall评分 | 问题数 | 警告数 | 修正 |",
            "|--------|----------|------------|---------|------|----------|-------------|--------|--------|------|",
        ]
        for record in records:
            metrics = record.get("metrics", {})
            lines.append(
                f"| {record.get('experiment_case_id', '')} "
                f"| {record.get('collaboration_mode', '')} "
                f"| {record.get('review_mode', '')} "
                f"| {metrics.get('poi_count', 0)} "
                f"| {metrics.get('day_count', 0)} "
                f"| {'是' if metrics.get('is_over_budget') else '否'} "
                f"| {metrics.get('overall_review_score', 0):.1f} "
                f"| {metrics.get('issue_count', 0)} "
                f"| {metrics.get('warning_count', 0)} "
                f"| {'是' if metrics.get('has_fix_applied') else '否'} |"
            )
        return "\n".join(lines)

    def generate_statistics_summary(self) -> Dict[str, Any]:
        if not self.experiment_records:
            return {"total_experiments": 0, "message": "暂无实验数据"}

        records = self.experiment_records
        method_records = [record for record in records if "method" in record]
        if method_records:
            by_method: Dict[str, Dict[str, Any]] = {}
            for method in self.METHODS:
                rows = [record for record in method_records if record.get("method") == method]
                if not rows:
                    continue
                accuracies = [
                    row.get("metrics", {}).get("tool_selection_accuracy")
                    for row in rows
                    if row.get("metrics", {}).get("tool_selection_accuracy") is not None
                ]
                by_method[method] = {
                    "count": len(rows),
                    "avg_latency_ms": round(sum(row.get("latency_ms", 0) for row in rows) / len(rows), 2),
                    "avg_ttft_ms": _average_numeric(row.get("ttft_ms") for row in rows),
                    "avg_tool_selection_accuracy": (
                        round(sum(accuracies) / len(accuracies), 2) if accuracies else None
                    ),
                }
            return {
                "total_experiments": len(method_records),
                "method_stats": by_method,
                "generated_at": datetime.utcnow().isoformat(),
            }

        collab_stats: Dict[str, Dict[str, Any]] = {}
        for mode in CollaborationMode:
            mode_records = [r for r in records if r.get("collaboration_mode") == mode.value]
            if mode_records:
                scores = [r.get("metrics", {}).get("overall_review_score", 0) for r in mode_records]
                issue_counts = [r.get("metrics", {}).get("issue_count", 0) for r in mode_records]
                collab_stats[mode.value] = {
                    "count": len(mode_records),
                    "avg_score": sum(scores) / len(scores) if scores else 0,
                    "avg_issues": sum(issue_counts) / len(issue_counts) if issue_counts else 0,
                }

        review_stats: Dict[str, Dict[str, Any]] = {}
        for mode in ReviewModeExperiment:
            mode_records = [r for r in records if r.get("review_mode") == mode.value]
            if mode_records:
                scores = [r.get("metrics", {}).get("overall_review_score", 0) for r in mode_records]
                issue_counts = [r.get("metrics", {}).get("issue_count", 0) for r in mode_records]
                review_stats[mode.value] = {
                    "count": len(mode_records),
                    "avg_score": sum(scores) / len(scores) if scores else 0,
                    "avg_issues": sum(issue_counts) / len(issue_counts) if issue_counts else 0,
                }

        has_poi_rate = sum(1 for r in records if r.get("metrics", {}).get("has_poi_list")) / len(records)
        has_daily_rate = sum(1 for r in records if r.get("metrics", {}).get("has_daily_plans")) / len(records)
        has_budget_rate = sum(1 for r in records if r.get("metrics", {}).get("has_structured_budget")) / len(records)
        over_budget_count = sum(1 for r in records if r.get("metrics", {}).get("is_over_budget") is True)

        return {
            "total_experiments": len(records),
            "collaboration_mode_stats": collab_stats,
            "review_mode_stats": review_stats,
            "structure_completeness": {
                "poi_list_rate": round(has_poi_rate, 2),
                "daily_plans_rate": round(has_daily_rate, 2),
                "structured_budget_rate": round(has_budget_rate, 2),
            },
            "over_budget_rate": round(over_budget_count / len(records), 2),
            "generated_at": datetime.utcnow().isoformat(),
        }

    # ------------------------------------------------------------------
    # Method implementations and result shaping
    # ------------------------------------------------------------------
    def _case_visible_to_generation(
        self,
        case: Dict[str, Any],
        method: ExperimentMethod,
    ) -> Dict[str, Any]:
        if method in self.method_handlers or case.get("evaluation_mode") == "oracle_slots":
            return case
        return build_generation_case(case, method)

    async def _dispatch_method(
        self,
        case: Dict[str, Any],
        method: ExperimentMethod,
        request_id: str,
    ) -> Any:
        if method in self.method_handlers:
            return await self._run_custom_handler(case, method, request_id)
        if method == "adaptive_multi_agent":
            return await self._run_adaptive_multi_agent(case, request_id)
        if method == "fixed_multi_agent":
            return await self._run_fixed_multi_agent(case, request_id)
        if method == "single_agent":
            return await self._run_single_agent(case, request_id)
        if method == "llm_direct":
            return await self._run_llm_direct(case, request_id)
        raise ValueError(f"Unsupported method: {method}")

    async def _run_custom_handler(
        self,
        case: Dict[str, Any],
        method: ExperimentMethod,
        request_id: str,
    ) -> Any:
        session_id = self._case_session_id(case, method)
        with request_trace(
            request_id,
            session_id,
            user_message=case["user_input"],
            experiment_case_id=case["case_id"],
            method=method,
            evaluation_mode=case["evaluation_mode"],
        ) as trace:
            if trace is not None:
                self._initialize_trace_for_evaluation(case)
            result = await _maybe_await(self.method_handlers[method](case))
            set_trace_result_summary(result, offline_data=self._offline_data_summary(compact=True))
            return result

    async def _run_full_system(self, case: Dict[str, Any], request_id: str) -> str:
        from app.main import TourismSystemApp

        app = self.app_factory() if self.app_factory else TourismSystemApp()
        app.ensure_runtime_initialized()
        session_id = self._case_session_id(case, "full_system")
        session = app.get_or_create_session(session_id)
        final_content = ""
        async for event in app.orchestrator.process(session, case["user_input"], request_id):
            if event.get("status") == "completed" and isinstance(event.get("content"), str):
                final_content = event["content"]
            if event.get("event") == "final" and event.get("data"):
                final_content = _extract_final_content(event.get("data")) or final_content
        return final_content

    async def _run_llm_direct(self, case: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        prompt = self._structured_llm_user_prompt(
            case=case,
            method="llm_direct",
            task_prompt=case["user_input"],
            planned_agents=[],
            planned_tools=[],
            tool_results={},
        )
        final_answer = await self._run_llm_baseline(
            case=case,
            request_id=request_id,
            method="llm_direct",
            system_prompt=self._structured_llm_system_prompt("llm_direct"),
            user_prompt=prompt,
            selected_agents=[],
        )
        model_payload, json_error = self._parse_strict_structured_llm_json(final_answer)
        return self._build_structured_llm_method_output(
            case=case,
            method="llm_direct",
            planned_agents=[],
            used_agents=[],
            planned_tools=[],
            called_tools=[],
            tool_results={},
            final_answer=final_answer,
            execution_status="completed",
            model_payload=model_payload,
            json_error=json_error,
            metadata={
                "generation_policy": "direct_llm_no_tools",
                "method_input_schema_version": case.get("method_input_schema_version"),
                "visible_slots": self._case_slots(case),
                "goal_state_slots": self._goal_state_current_slots(case),
            },
        )

    async def _run_single_agent(self, case: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        if self._infer_research_task_type(case) in {"general_chat", "clarification"}:
            return await self._run_research_multi_agent(
                case=case,
                request_id=request_id,
                method="single_agent",
                planned_agents=[],
                planned_tools=[],
            )

        prompt = (
            "请作为单一旅游规划 Agent 独立完成任务。不要调度其他 Agent，"
            "但需要尽量给出结构化、可执行的旅游建议。\n\n用户请求："
            f"{case['user_input']}"
        )
        prompt = self._structured_llm_user_prompt(
            case=case,
            method="single_agent",
            task_prompt=prompt,
            planned_agents=["single_agent"],
            planned_tools=list(GENERATION_TOOL_NAMES),
            tool_results={},
        )
        session_id = self._case_session_id(case, "single_agent")
        with request_trace(
            request_id,
            session_id,
            user_message=case["user_input"],
            experiment_case_id=case["case_id"],
            method="single_agent",
            evaluation_mode=case["evaluation_mode"],
        ) as trace:
            if trace is not None:
                self._initialize_trace_for_evaluation(case)
                set_trace_selected_agents(["single_agent"])

            llm = self.llm_factory()
            tools = self._build_single_agent_tools()
            executor = ToolExecutor(tools={tool.name: tool for tool in tools})
            planned_tools: List[str] = []
            called_tools: List[Dict[str, Any]] = []
            tool_results: Dict[str, Any] = {}
            method_failed = False
            definitions = [
                ToolDefinition(
                    name=tool.name,
                    description=tool.description,
                    parameters=tool.parameters,
                )
                for tool in tools
            ]
            messages = [
                LLMMessage(
                    role="system",
                    content=(
                        "你是一个单 Agent 旅游规划助手。你只能根据需要调用统一实验工具："
                        "poi_search、weather_query、budget_calculator。请优先使用工具返回的"
                        "固定离线数据，不要调度其他 Agent，也不要假装调用未提供的工具。"
                        "最终回答必须是一个严格 JSON 对象，不要输出 Markdown 或解释文字。"
                    ),
                ),
                LLMMessage(role="user", content=prompt),
            ]

            agent_run = start_agent_run("single_agent")
            executed_call_count = 0
            missing_tool_retry_count = 0
            structured_repair_retry_count = 0
            try:
                with trace_component("single_agent", agent_name="single_agent"):
                    for _ in range(self.SINGLE_AGENT_MAX_TOOL_ROUNDS):
                        if self._single_agent_deterministic_output_ready(
                            case=case,
                            tool_results=tool_results,
                            executed_call_count=executed_call_count,
                        ):
                            method_output = await self._build_research_method_output(
                                case=case,
                                method="single_agent",
                                planned_agents=["single_agent"],
                                planned_tools=planned_tools,
                                tool_results=tool_results,
                                called_tools=called_tools,
                            )
                            method_output.setdefault("metadata", {})[
                                "single_agent_final_answer_mode"
                            ] = "deterministic_after_tool_evidence"
                            finish_agent_run(
                                agent_run,
                                agent_name="single_agent",
                                status=(
                                    "failed"
                                    if method_output.get("execution_status") == "failed"
                                    else "completed"
                                ),
                                tool_count=executed_call_count,
                            )
                            set_trace_result_summary(
                                method_output,
                                offline_data=self._offline_data_summary(compact=True),
                            )
                            return method_output

                        response = await self._llm_chat_with_experiment_timeout(
                            llm,
                            messages,
                            tools=definitions,
                        )
                        if not response.tool_calls:
                            missing_required_tools = self._single_agent_missing_required_tools(
                                case=case,
                                tool_results=tool_results,
                            )
                            if missing_required_tools and missing_tool_retry_count < 2:
                                missing_tool_retry_count += 1
                                messages.append(
                                    LLMMessage(
                                        role="assistant",
                                        content=response.content or "",
                                    )
                                )
                                messages.append(
                                    LLMMessage(
                                        role="user",
                                        content=self._single_agent_missing_tools_retry_prompt(
                                            case=case,
                                            missing_tools=missing_required_tools,
                                            tool_results=tool_results,
                                        ),
                                    )
                                )
                                continue

                            usage = getattr(response, "usage", None) or {}
                            model_payload, json_error = self._parse_strict_structured_llm_json(
                                response.content
                            )
                            validation_errors = self._structured_llm_validation_errors(
                                payload=model_payload,
                                case=case,
                                method="single_agent",
                            )
                            if (
                                not missing_required_tools
                                and (json_error or validation_errors)
                                and structured_repair_retry_count < 1
                            ):
                                structured_repair_retry_count += 1
                                messages.append(
                                    LLMMessage(
                                        role="assistant",
                                        content=response.content or "",
                                    )
                                )
                                messages.append(
                                    LLMMessage(
                                        role="user",
                                        content=self._single_agent_structured_repair_prompt(
                                            json_error=json_error,
                                            validation_errors=validation_errors,
                                        ),
                                    )
                                )
                                continue

                            method_output = self._build_structured_llm_method_output(
                                case=case,
                                method="single_agent",
                                planned_agents=["single_agent"],
                                used_agents=["single_agent"],
                                planned_tools=planned_tools,
                                called_tools=called_tools,
                                tool_results=tool_results,
                                final_answer=response.content,
                                execution_status=(
                                    "failed"
                                    if method_failed
                                    or missing_required_tools
                                    or self._execution_status_from_tool_results(tool_results)
                                    == "failed"
                                    else "completed"
                                ),
                                model_payload=model_payload,
                                json_error=json_error,
                                metadata={
                                    "generation_policy": "single_agent_tool_loop",
                                    "generation_tool_contract": "ctp-research-tools-v1.0",
                                    "method_input_schema_version": case.get("method_input_schema_version"),
                                    "single_agent_max_tool_rounds": self.SINGLE_AGENT_MAX_TOOL_ROUNDS,
                                    "single_agent_missing_tool_retry_count": missing_tool_retry_count,
                                    "single_agent_structured_repair_retry_count": structured_repair_retry_count,
                                    "missing_required_tools": missing_required_tools,
                                    "visible_slots": self._case_slots(case),
                                    "goal_state_slots": self._goal_state_current_slots(case),
                                },
                            )
                            failure_reason = _nested_mapping(
                                method_output,
                                "metadata",
                                "structured_llm_output",
                                "failure_reason",
                            )
                            if failure_reason:
                                mark_trace_status("failed", error=str(failure_reason))
                            finish_agent_run(
                                agent_run,
                                agent_name="single_agent",
                                status="failed" if method_output["execution_status"] == "failed" else "completed",
                                tokens=usage.get("total_tokens"),
                                tool_count=executed_call_count,
                            )
                            set_trace_result_summary(
                                method_output,
                                offline_data=self._offline_data_summary(compact=True),
                            )
                            return method_output

                        for call in response.tool_calls:
                            if not call.id:
                                call.id = uuid.uuid4().hex
                        record_planned_tools(
                            [call.name for call in response.tool_calls if call.name]
                        )
                        planned_tools = _ordered_unique(
                            [
                                *planned_tools,
                                *[call.name for call in response.tool_calls if call.name],
                            ]
                        )
                        messages.append(
                            LLMMessage(
                                role="assistant",
                                content=response.content or "",
                                tool_calls=response.tool_calls,
                            )
                        )

                        for tool_call in response.tool_calls:
                            try:
                                arguments = json.loads(tool_call.arguments or "{}")
                                if not isinstance(arguments, dict):
                                    raise ValueError("tool arguments must be a JSON object")
                            except (json.JSONDecodeError, ValueError) as exc:
                                tool_content = f"Tool arguments error: {exc}"
                                method_failed = True
                                executed_call_count += 1
                                failed_payload = self._failed_single_agent_tool_result(
                                    tool_name=tool_call.name,
                                    arguments={"raw_arguments": tool_call.arguments},
                                    code="invalid_tool_arguments",
                                    message=tool_content,
                                )
                                tool_results[tool_call.name] = failed_payload
                                called_tools.append(
                                    self._single_agent_tool_call_summary(
                                        tool_name=tool_call.name,
                                        status="failed",
                                        success=False,
                                        arguments={"raw_arguments": tool_call.arguments},
                                        duration_ms=0,
                                        error=tool_content,
                                    )
                                )
                                record_tool_call(
                                    tool_call.name,
                                    params={"raw_arguments": tool_call.arguments},
                                    duration_ms=0,
                                    status="failed",
                                    success=False,
                                    error=tool_content,
                                    call_id=tool_call.id,
                                )
                                mark_trace_status("failed", error=tool_content)
                            else:
                                arguments = self._single_agent_tool_arguments_with_visible_defaults(
                                    tool_name=tool_call.name,
                                    arguments=arguments,
                                    case=case,
                                    tool_results=tool_results,
                                )
                                call = await executor.execute(
                                    tool_name=tool_call.name,
                                    arguments=arguments,
                                    call_id=tool_call.id,
                                )
                                executed_call_count += 1
                                called_tools.append(
                                    self._single_agent_tool_call_summary(
                                        tool_name=tool_call.name,
                                        status=call.status.value,
                                        success=call.is_completed and not call.error,
                                        arguments=arguments,
                                        duration_ms=call.execution_time_ms,
                                        error=call.error,
                                    )
                                )
                                tool_results[tool_call.name] = self._single_agent_tool_result_payload(
                                    tool_name=tool_call.name,
                                    arguments=arguments,
                                    result=call.result,
                                    success=call.is_completed and not call.error,
                                    error=call.error,
                                )
                                if call.is_completed and not call.error:
                                    tool_content = _json_tool_result(call.result)
                                else:
                                    method_failed = True
                                    tool_content = (
                                        f"Tool execution error: {call.error or call.status.value}"
                                    )
                                    mark_trace_status("failed", error=tool_content)

                            messages.append(
                                LLMMessage(
                                    role="tool",
                                    content=tool_content,
                                    name=tool_call.name,
                                    tool_call_id=tool_call.id,
                                )
                            )

                raise RuntimeError("single-agent tool loop exceeded maximum rounds")
            except BaseException as exc:
                finish_agent_run(
                    agent_run,
                    agent_name="single_agent",
                    status="failed",
                    tool_count=executed_call_count,
                    error=exc,
                )
                raise

    def _single_agent_deterministic_output_ready(
        self,
        *,
        case: Dict[str, Any],
        tool_results: Dict[str, Any],
        executed_call_count: int,
    ) -> bool:
        if not _environment_bool("EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER", False):
            return False
        if executed_call_count <= 0:
            return False
        required_tools = self._single_agent_required_tools(case)
        if not required_tools:
            return True
        successful_tools = {
            name
            for name, result in (tool_results or {}).items()
            if isinstance(result, dict) and result.get("success") is not False
        }
        return set(required_tools).issubset(successful_tools)

    def _single_agent_missing_required_tools(
        self,
        *,
        case: Dict[str, Any],
        tool_results: Dict[str, Any],
    ) -> List[str]:
        required_tools = self._single_agent_required_tools(case)
        if not required_tools:
            return []
        successful_tools = {
            name
            for name, result in (tool_results or {}).items()
            if isinstance(result, dict) and result.get("success") is not False
        }
        return [tool for tool in required_tools if tool not in successful_tools]

    def _single_agent_missing_tools_retry_prompt(
        self,
        *,
        case: Dict[str, Any],
        missing_tools: List[str],
        tool_results: Dict[str, Any],
    ) -> str:
        defaults = {
            tool_name: self._research_tool_arguments(tool_name, case, tool_results)
            for tool_name in missing_tools
        }
        return json.dumps(
            {
                "instruction": (
                    "You have not collected the required frozen-tool evidence yet. "
                    "Do not answer directly. Call the missing tools first, using only "
                    "the visible slot defaults below when your arguments are incomplete."
                ),
                "missing_required_tools": missing_tools,
                "visible_slot_argument_defaults": defaults,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _single_agent_structured_repair_prompt(
        *,
        json_error: Optional[str],
        validation_errors: List[str],
    ) -> str:
        return json.dumps(
            {
                "instruction": (
                    "Your previous response was not a valid experiment JSON object. "
                    "Return exactly one corrected JSON object only. Preserve the same "
                    "answer content where possible, but make every schema field valid."
                ),
                "json_error": json_error,
                "validation_errors": validation_errors,
                "required_repairs": {
                    "weather_adjustments": "must be a list of objects, e.g. [] or [{'day': 1, 'reason': 'rain'}]",
                    "attractions": "must be a list of objects",
                    "daily_itinerary": "must be a list of objects",
                    "execution_status": "must be completed, failed, or clarification",
                },
            },
            ensure_ascii=False,
        )

    def _single_agent_tool_arguments_with_visible_defaults(
        self,
        *,
        tool_name: str,
        arguments: Dict[str, Any],
        case: Dict[str, Any],
        tool_results: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized = dict(arguments or {})
        defaults = self._research_tool_arguments(tool_name, case, tool_results)
        aliases = self._single_agent_argument_aliases(tool_name)
        for key, value in defaults.items():
            if (
                self._single_agent_argument_missing(normalized.get(key))
                and not self._single_agent_argument_missing(value)
                and not self._single_agent_equivalent_argument_present(
                    normalized,
                    aliases.get(key, []),
                )
            ):
                normalized[key] = value
        return normalized

    @staticmethod
    def _single_agent_argument_missing(value: Any) -> bool:
        return value in (None, "", [], {})

    @classmethod
    def _single_agent_equivalent_argument_present(
        cls,
        arguments: Dict[str, Any],
        aliases: List[str],
    ) -> bool:
        return any(
            not cls._single_agent_argument_missing(arguments.get(alias))
            for alias in aliases
        )

    @staticmethod
    def _single_agent_argument_aliases(tool_name: str) -> Dict[str, List[str]]:
        common_city = {"city": ["destination"], "destination": ["city"]}
        if tool_name == "poi_search":
            return common_city
        if tool_name == "weather_query":
            return {
                **common_city,
                "date": ["start_date"],
                "start_date": ["date"],
                "days": ["duration"],
                "duration": ["days"],
                "scenario_type": ["weather_scenario"],
                "weather_scenario": ["scenario_type"],
            }
        if tool_name == "budget_calculator":
            return {
                **common_city,
                "origin": ["from_city"],
                "from_city": ["origin"],
                "people_count": ["num_travelers"],
                "num_travelers": ["people_count"],
                "days": ["duration"],
                "duration": ["days"],
                "spending_level": ["budget_level"],
                "budget_level": ["spending_level"],
                "attractions": ["poi_ids"],
                "poi_ids": ["attractions"],
            }
        return {}

    def _single_agent_required_tools(self, case: Dict[str, Any]) -> List[str]:
        required = [
            str(item)
            for item in _as_list(_nested_mapping(case, "expected", "required_tools"))
            if str(item) in GENERATION_TOOL_NAMES
        ]
        if required:
            return _ordered_unique(required)
        task_type = self._case_constraint_task_type(case)
        by_task = {
            "trip_planning": list(GENERATION_TOOL_NAMES),
            "partial_replan": list(GENERATION_TOOL_NAMES),
            "weather_adjustment": list(GENERATION_TOOL_NAMES),
            "attraction_recommendation": ["poi_search"],
            "weather_query": ["weather_query"],
            "budget_query": ["budget_calculator"],
        }
        return by_task.get(task_type, [])

    def _structured_llm_system_prompt(self, method: ExperimentMethod) -> str:
        role = (
            "You are the M0 direct LLM tourism baseline. You must not call tools or claim tool use."
            if method == "llm_direct"
            else "You are the M1 single tourism Agent. Use only the provided tools when needed."
        )
        return (
            f"{role}\n"
            "Return exactly one valid JSON object that follows the experiment output schema. "
            "Do not wrap it in Markdown. Do not add explanatory text outside JSON. "
            "If information is unavailable, use null or an empty list/object in the correct field. "
            "Fields attractions, daily_itinerary, and weather_adjustments must always be arrays "
            "of JSON objects; never return arrays of strings for these fields. "
            "Fields budget and weather must be JSON objects or null; never return arrays or strings "
            "for budget or weather. Field trip_days must be an integer or null. "
            "Keep the JSON compact and shallow: avoid deeply nested step-by-step arrays, "
            "limit attractions to at most five items, keep final_answer concise, and check "
            "all brackets and commas before returning."
        )

    def _structured_llm_user_prompt(
        self,
        *,
        case: Dict[str, Any],
        method: ExperimentMethod,
        task_prompt: str,
        planned_agents: List[str],
        planned_tools: List[str],
        tool_results: Dict[str, Any],
    ) -> str:
        payload = {
            "prompt_version": STRUCTURED_LLM_OUTPUT_PROMPT_VERSION,
            "instruction": (
                "Generate the task content fields yourself. The program will inject authoritative "
                "agent/tool evidence fields after parsing, so do not fabricate tool calls."
            ),
            "case_id": str(case.get("case_id") or ""),
            "method": method,
            "user_request": str(case.get("user_input") or ""),
            "dialogue_history": _jsonable_value(case.get("dialogue_history") or []),
            "method_previous_state_summary": self._method_previous_state_prompt_summary(
                case.get("method_previous_state") or case.get("previous_state")
            ),
            "method_previous_state": self._compact_prompt_value(
                case.get("method_previous_state") or case.get("previous_state") or {}
            ),
            "visible_slots": self._case_slots(case),
            "task_prompt": str(task_prompt or ""),
            "tool_results_available_to_program": _jsonable_value(tool_results or {}),
            "required_output_fields": [
                *STRUCTURED_LLM_M0_METHOD_FIELDS,
                *STRUCTURED_LLM_CONTENT_FIELDS,
                "metadata",
            ],
            "field_type_contract": {
                "trip_days": "integer|null; never string",
                "budget": "object|null; never array/string",
                "weather": "object|null; never array/string",
                "attractions": "array<object>; use [] when no attraction is recommended",
                "daily_itinerary": (
                    "array<object>; use [] when no day-level itinerary is needed; "
                    "prefer shallow day objects with day/day_index, summary, attraction_names or "
                    "attraction_poi_ids, and notes; avoid nested steps arrays"
                ),
                "weather_adjustments": (
                    "array<object>; use [] when no weather adjustment is needed; "
                    "never use string items"
                ),
                "final_answer": "string; concise Chinese summary, preferably under 240 characters",
                "weather_adjustment_object_example": {
                    "day": 1,
                    "day_index": 1,
                    "reason": "rain",
                    "action": "prefer indoor or rain-suitable attractions",
                    "candidate_indoor_pois": [],
                },
            },
            "output_template": {
                "schema_version": EXPERIMENT_OUTPUT_SCHEMA_VERSION,
                "case_id": str(case.get("case_id") or ""),
                "method": method,
                "task_type": self._infer_research_task_type(case),
                "planned_agents": _ordered_unique(planned_agents),
                "used_agents": _ordered_unique(planned_agents),
                "planned_tools": _ordered_unique(planned_tools),
                "called_tools": [],
                "tool_results": {},
                "attractions": [],
                "trip_days": None,
                "daily_itinerary": [],
                "budget": None,
                "weather": None,
                "weather_adjustments": [],
                "execution_status": "completed",
                "final_answer": "",
                "metadata": {
                    "structured_by_llm": True,
                    "prompt_version": STRUCTURED_LLM_OUTPUT_PROMPT_VERSION,
                },
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str)

    def _method_previous_state_prompt_summary(self, previous_state: Any) -> Dict[str, Any]:
        if not isinstance(previous_state, dict):
            return {}
        output = previous_state.get("output") if isinstance(previous_state.get("output"), dict) else {}
        return {
            "schema_version": previous_state.get("schema_version"),
            "method": previous_state.get("method"),
            "case_id": previous_state.get("case_id"),
            "scenario_id": previous_state.get("scenario_id"),
            "turn_id": previous_state.get("turn_id"),
            "turn_index": previous_state.get("turn_index"),
            "status": previous_state.get("status"),
            "execution_status": previous_state.get("execution_status"),
            "output_task_type": output.get("task_type"),
            "output_final_answer": str(output.get("final_answer") or "")[:1200],
        }

    def _parse_strict_structured_llm_json(
        self,
        raw_content: Any,
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        if not isinstance(raw_content, str) or not raw_content.strip():
            return None, "structured LLM output is empty or not text"
        raw_text = raw_content.strip()
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            repaired_text, repair_count = _repair_unquoted_json_arithmetic_values(raw_text)
            if repair_count <= 0:
                return None, f"structured LLM output is not strict JSON: {exc.msg}"
            try:
                parsed = json.loads(repaired_text)
            except json.JSONDecodeError:
                return None, f"structured LLM output is not strict JSON: {exc.msg}"
            if isinstance(parsed, dict):
                metadata = parsed.setdefault("metadata", {})
                if isinstance(metadata, dict):
                    metadata["structured_json_arithmetic_repair"] = {
                        "applied": True,
                        "replacement_count": repair_count,
                    }
        if not isinstance(parsed, dict):
            return None, "structured LLM output must be a JSON object"
        return parsed, None

    def _structured_llm_validation_errors(
        self,
        *,
        payload: Optional[Dict[str, Any]],
        case: Dict[str, Any],
        method: ExperimentMethod,
    ) -> List[str]:
        if payload is None:
            return []

        errors: List[str] = []
        for field in (*STRUCTURED_LLM_M0_METHOD_FIELDS, *STRUCTURED_LLM_CONTENT_FIELDS):
            if field not in payload:
                errors.append(f"missing required field: {field}")

        if payload.get("schema_version") != EXPERIMENT_OUTPUT_SCHEMA_VERSION:
            errors.append("schema_version mismatch")
        if str(payload.get("case_id") or "") != str(case.get("case_id") or ""):
            errors.append("case_id mismatch")
        if str(payload.get("method") or "") != str(method or ""):
            errors.append("method mismatch")

        for field in ("planned_agents", "used_agents", "planned_tools", "called_tools"):
            value = payload.get(field)
            if field in payload and not isinstance(value, list):
                errors.append(f"{field} must be a list")
            if method == "llm_direct" and isinstance(value, list) and value:
                errors.append(f"M0 must not contain {field}")

        tool_results = payload.get("tool_results")
        if "tool_results" in payload and not isinstance(tool_results, dict):
            errors.append("tool_results must be an object")
        if method == "llm_direct" and isinstance(tool_results, dict) and tool_results:
            errors.append("M0 must not contain tool_results")

        if "task_type" in payload:
            if not isinstance(payload.get("task_type"), str):
                errors.append("task_type must be a string")
            elif self._normalized_research_task_type(payload.get("task_type")) not in FROZEN_RESEARCH_TASK_TYPES:
                errors.append("task_type must be one of the frozen evaluation task types")
        for field in ("attractions", "daily_itinerary", "weather_adjustments"):
            if field in payload and not self._is_dict_list_or_empty(payload.get(field)):
                errors.append(f"{field} must be a list of objects")
        if "trip_days" in payload and not self._is_optional_int(payload.get("trip_days")):
            errors.append("trip_days must be an integer or null")
        if "budget" in payload and not self._is_optional_mapping(payload.get("budget")):
            errors.append("budget must be an object or null")
        if "weather" in payload and not self._is_optional_mapping(payload.get("weather")):
            errors.append("weather must be an object or null")
        if "execution_status" in payload and str(payload.get("execution_status") or "").lower() not in {
            "completed",
            "failed",
            "clarification",
        }:
            errors.append("execution_status must be completed, failed, or clarification")
        if "final_answer" in payload and not isinstance(payload.get("final_answer"), str):
            errors.append("final_answer must be a string")
        return errors

    @staticmethod
    def _is_dict_list_or_empty(value: Any) -> bool:
        return isinstance(value, list) and all(isinstance(item, dict) for item in value)

    @staticmethod
    def _is_optional_mapping(value: Any) -> bool:
        return value is None or isinstance(value, dict)

    @staticmethod
    def _is_optional_int(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        if isinstance(value, str) and value.strip().isdigit():
            return True
        return False

    @staticmethod
    def _optional_int(value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _dict_list(value: Any) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [_jsonable_value(item) for item in value if isinstance(item, dict)]

    def _build_structured_llm_method_output(
        self,
        *,
        case: Dict[str, Any],
        method: ExperimentMethod,
        planned_agents: List[str],
        used_agents: List[str],
        planned_tools: List[str],
        called_tools: List[Dict[str, Any]],
        tool_results: Dict[str, Any],
        final_answer: str,
        execution_status: str,
        model_payload: Optional[Dict[str, Any]] = None,
        json_error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_tool_results = {
            str(name): _jsonable_value(result)
            for name, result in (tool_results or {}).items()
            if name
        }
        payload = model_payload if isinstance(model_payload, dict) else {}
        validation_errors = self._structured_llm_validation_errors(
            payload=model_payload,
            case=case,
            method=method,
        )
        failure_items = [item for item in [json_error, *validation_errors] if item]
        model_status = str(payload.get("execution_status") or execution_status or "completed").lower()
        if model_status not in {"completed", "failed", "clarification"}:
            model_status = "failed"
        runtime_status = str(execution_status or "").lower()
        final_status = "failed" if failure_items or runtime_status == "failed" else model_status
        if final_status == "failed" and not failure_items and runtime_status != "failed":
            final_status = "completed"
        final_answer_text = str(payload.get("final_answer") or "")
        output_metadata = {
            "research_method": method,
            "output_contract": EXPERIMENT_OUTPUT_SCHEMA_VERSION,
            "structured_llm_output": {
                "prompt_version": STRUCTURED_LLM_OUTPUT_PROMPT_VERSION,
                "json_required": True,
                "parse_status": "failed" if json_error else "passed",
                "validation_status": "failed" if validation_errors else "passed",
                "validation_errors": validation_errors,
                "failure_reason": "; ".join(failure_items) if failure_items else None,
            },
        }
        model_metadata = payload.get("metadata")
        if isinstance(model_metadata, dict):
            output_metadata["model_metadata"] = _jsonable_value(model_metadata)
        output_metadata = {
            key: value
            for key, value in output_metadata.items()
            if value is not None
        }
        if metadata:
            output_metadata.update(metadata)

        output_task_type = self._canonical_research_task_type(
            payload.get("task_type") or self._infer_research_task_type(case)
        )
        output = {
            "schema_version": EXPERIMENT_OUTPUT_SCHEMA_VERSION,
            "case_id": str(case.get("case_id") or ""),
            "method": method,
            "task_type": output_task_type,
            "planned_agents": _ordered_unique(planned_agents),
            "used_agents": _ordered_unique(used_agents),
            "planned_tools": _ordered_unique(planned_tools),
            "called_tools": [_jsonable_value(call) for call in called_tools],
            "tool_results": normalized_tool_results,
            "agent_outputs": {},
            "attractions": self._dict_list(payload.get("attractions")),
            "trip_days": self._optional_int(payload.get("trip_days")),
            "daily_itinerary": self._dict_list(payload.get("daily_itinerary")),
            "budget": payload.get("budget") if isinstance(payload.get("budget"), dict) else None,
            "weather": payload.get("weather") if isinstance(payload.get("weather"), dict) else None,
            "weather_adjustments": self._dict_list(payload.get("weather_adjustments")),
            "execution_status": final_status,
            "final_answer": final_answer_text,
            "raw_output": _jsonable_value(model_payload) if model_payload is not None else str(final_answer or ""),
            "metadata": output_metadata,
        }
        return ExperimentMethodOutput.model_validate(output).model_dump(mode="json")

    def _single_agent_tool_call_summary(
        self,
        *,
        tool_name: str,
        status: str,
        success: bool,
        arguments: Dict[str, Any],
        duration_ms: Optional[float],
        error: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "tool_name": str(tool_name or ""),
            "status": str(status or "unknown"),
            "success": bool(success),
            "arguments": _jsonable_value(arguments or {}),
            "duration_ms": duration_ms if isinstance(duration_ms, (int, float)) else None,
            "error": None if error is None else str(error),
        }

    def _single_agent_tool_result_payload(
        self,
        *,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Any,
        success: bool,
        error: Optional[str],
    ) -> Dict[str, Any]:
        payload = _jsonable_value(result)
        if isinstance(payload, dict):
            payload.setdefault("schema_version", "research_tool_result_v1")
            payload.setdefault("tool_contract_version", "ctp-research-tools-v1.0")
            payload.setdefault("tool_name", str(tool_name or ""))
            payload.setdefault("input", _jsonable_value(arguments or {}))
            payload.setdefault("data", {})
            payload.setdefault("metadata", {})
            payload["success"] = bool(success) and payload.get("success") is not False
            payload["status"] = (
                "failed"
                if not payload["success"]
                else str(payload.get("status") or "success")
            )
            if not payload["success"] and not isinstance(payload.get("error"), dict):
                payload["error"] = {
                    "code": "tool_execution_error",
                    "message": str(error or "Tool returned unsuccessful result"),
                    "retryable": False,
                }
            return payload

        if success:
            return {
                "schema_version": "research_tool_result_v1",
                "tool_contract_version": "ctp-research-tools-v1.0",
                "tool_name": str(tool_name or ""),
                "status": "success",
                "success": True,
                "input": _jsonable_value(arguments or {}),
                "data": {"value": payload},
                "metadata": {
                    "offline": True,
                    "source_mode": "single_agent_tool_loop",
                    "real_time_api_allowed": False,
                },
            }

        return self._failed_single_agent_tool_result(
            tool_name=tool_name,
            arguments=arguments,
            code="tool_execution_error",
            message=str(error or "Tool execution failed"),
        )

    def _failed_single_agent_tool_result(
        self,
        *,
        tool_name: str,
        arguments: Dict[str, Any],
        code: str,
        message: str,
    ) -> Dict[str, Any]:
        return {
            "schema_version": "research_tool_result_v1",
            "tool_contract_version": "ctp-research-tools-v1.0",
            "tool_name": str(tool_name or ""),
            "status": "failed",
            "success": False,
            "input": _jsonable_value(arguments or {}),
            "data": {},
            "error": {
                "code": str(code or "tool_error"),
                "message": str(message or "Tool execution failed"),
                "retryable": False,
            },
            "metadata": {
                "offline": True,
                "source_mode": "single_agent_tool_loop",
                "real_time_api_allowed": False,
            },
        }

    def _build_single_agent_tools(self) -> List[Any]:
        """Build the shared generation tool catalog used by M1/M2/M3."""
        return generation_tools()

    async def _llm_chat_with_experiment_timeout(
        self,
        llm: Any,
        messages: List[LLMMessage],
        **kwargs: Any,
    ) -> Any:
        timeout_seconds = _experiment_llm_call_timeout_seconds()
        try:
            return await asyncio.wait_for(
                llm.chat(messages, **kwargs),
                timeout=timeout_seconds,
            )
        except TimeoutError as exc:
            raise TimeoutError(
                f"LLM call exceeded experiment watchdog timeout "
                f"({timeout_seconds:g}s)"
            ) from exc

    async def _run_fixed_multi_agent(self, case: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        execution_case = self._case_for_fixed_multi_agent(case)
        scheduler_metadata = self._fixed_multi_agent_scheduler_metadata(execution_case)
        decision = self._scheduler_decision(scheduler_metadata)
        agents = _as_list(decision.get("planned_agents"))
        tools = _as_list(decision.get("planned_tools"))
        return await self._run_research_multi_agent(
            case=execution_case,
            request_id=request_id,
            method="fixed_multi_agent",
            planned_agents=agents,
            planned_tools=tools,
            scheduler_metadata=scheduler_metadata,
        )

    def _fixed_multi_agent_plan(self, case: Dict[str, Any]) -> tuple[List[str], List[str]]:
        scheduler_metadata = self._fixed_multi_agent_scheduler_metadata(case)
        decision = self._scheduler_decision(scheduler_metadata)
        return _as_list(decision.get("planned_agents")), _as_list(decision.get("planned_tools"))

    def _fixed_multi_agent_scheduler_metadata(self, case: Dict[str, Any]) -> Dict[str, Any]:
        ticket = build_goal_state_ticket(
            user_input=str(case.get("user_input") or ""),
            current_slots=self._goal_state_current_slots(case),
            previous_state=self._goal_state_previous_state(case),
        )
        ticket_payload = ticket.to_dict()
        agents, tools, reasons = self._m2_fixed_template_for_ticket(ticket_payload)
        return {
            "name": "fixed_template_scheduler",
            "policy": "m2_task_relevant_fixed_template_v2",
            "state_reuse": False,
            "dynamic_goal_state_scheduling": False,
            "template_source": "app.core.experiment_method_contract.M2_FIXED_TEMPLATE_POLICY",
            "ticket": ticket_payload,
            "decision": {
                "schema_version": "ctp-fixed-template-decision-v1",
                "planned_agents": agents,
                "planned_tools": tools,
                "reused_agents": [],
                "invalidated_agents": [],
                "clarification_required": bool(ticket_payload.get("clarification_required")),
                "clarification_fields": _as_list(ticket_payload.get("clarification_fields")),
                "decision_reasons": reasons,
                "reuse_validation": {},
            },
        }

    def _m2_fixed_template_for_ticket(
        self,
        ticket: Dict[str, Any],
    ) -> tuple[List[str], List[str], List[str]]:
        task_type = str(ticket.get("task_type") or "").strip()
        canonical_task_type = self._canonical_research_task_type(task_type)

        if canonical_task_type in {"general_chat", "clarification"}:
            reason = (
                "fixed_template_clarification_no_business_agents"
                if canonical_task_type == "clarification"
                else "fixed_template_general_chat_no_business_agents"
            )
            return [], [], [reason]

        if canonical_task_type == "attraction_recommendation":
            return ["attraction"], ["poi_search"], ["fixed_template_attraction_only"]

        if canonical_task_type == "weather_query":
            return ["weather"], ["weather_query"], ["fixed_template_weather_only"]

        if canonical_task_type == "budget_query":
            return ["budget"], ["budget_calculator"], ["fixed_template_budget_only"]

        if canonical_task_type == "trip_planning":
            if self._m2_trip_plan_without_weather(ticket):
                agents = ["attraction", "itinerary", "budget"]
                return (
                    agents,
                    self._tools_for_agents(agents),
                    ["fixed_template_trip_plan_without_weather"],
                )
            agents = ["attraction", "weather", "itinerary", "budget"]
            return agents, self._tools_for_agents(agents), ["fixed_template_full_trip_plan"]

        if canonical_task_type == "partial_replan":
            return self._m2_partial_replan_template(ticket)

        if canonical_task_type == "weather_adjustment":
            agents = ["itinerary", "budget"]
            return agents, self._tools_for_agents(agents), ["fixed_template_weather_adjustment"]

        return [], [], ["fixed_template_non_executable_task"]

    def _m2_trip_plan_without_weather(self, ticket: Dict[str, Any]) -> bool:
        task_type = str(ticket.get("task_type") or "").strip()
        current_slots = (
            ticket.get("current_slots")
            if isinstance(ticket.get("current_slots"), dict)
            else {}
        )
        if task_type == "trip_plan":
            return True
        if str(current_slots.get("weather_date_policy") or "") == (
            "no_date_no_specific_weather_for_trip_plan"
        ):
            return True
        return not bool(current_slots.get("start_date") or current_slots.get("weather_scenario"))

    def _m2_partial_replan_template(
        self,
        ticket: Dict[str, Any],
    ) -> tuple[List[str], List[str], List[str]]:
        changed_slots = set(_as_list(ticket.get("changed_slots")))
        dependency_policy = (
            ticket.get("dependency_policy")
            if isinstance(ticket.get("dependency_policy"), dict)
            else {}
        )
        goal_change_type = str(ticket.get("goal_change_type") or "")

        if not changed_slots:
            agents = (
                ["attraction", "itinerary", "budget"]
                if self._m2_trip_plan_without_weather(ticket)
                else ["attraction", "weather", "itinerary", "budget"]
            )
            reason = (
                "fixed_template_explicit_replan"
                if goal_change_type == "explicit_replan"
                else "fixed_template_identical_followup_rerun"
            )
            return agents, self._tools_for_agents(agents), [reason]

        if "destination" in changed_slots:
            agents = (
                ["attraction", "itinerary", "budget"]
                if self._m2_trip_plan_without_weather(ticket)
                else ["attraction", "weather", "itinerary", "budget"]
            )
            return agents, self._tools_for_agents(agents), ["fixed_template_destination_changed"]

        agents: List[str] = []
        reasons: List[str] = []

        if "origin" in changed_slots:
            if dependency_policy.get("origin_change_scope") == "itinerary_budget":
                agents.extend(["itinerary", "budget"])
                reasons.append("fixed_template_origin_changed_itinerary_budget")
            else:
                agents.append("budget")
                reasons.append("fixed_template_origin_changed_budget_only")

        if changed_slots & {"preferences", "special_requirements", "traveler_group"}:
            agents.extend(["attraction", "itinerary", "budget"])
            reasons.append("fixed_template_preference_or_traveler_changed")

        if "start_date" in changed_slots or "weather_scenario" in changed_slots:
            agents.extend(["weather", "itinerary", "budget"])
            reasons.append("fixed_template_date_or_weather_changed")

        if "duration_days" in changed_slots:
            duration_agents = (
                ["weather", "itinerary", "budget"]
                if not self._m2_trip_plan_without_weather(ticket)
                else ["itinerary", "budget"]
            )
            agents.extend(duration_agents)
            reasons.append("fixed_template_duration_changed")

        if "people_count" in changed_slots:
            agents.extend(["itinerary", "budget"])
            reasons.append("fixed_template_people_count_changed")

        if changed_slots & {"budget_amount", "budget_level"}:
            if goal_change_type == "explicit_replan":
                agents.extend(["itinerary", "budget"])
                reasons.append("fixed_template_budget_changed_itinerary_budget")
            else:
                agents.append("budget")
                reasons.append("fixed_template_budget_changed_budget_only")

        agents = _ordered_unique([agent for agent in agents if agent in {"attraction", "weather", "itinerary", "budget"}])
        if not agents:
            agents = (
                ["attraction", "itinerary", "budget"]
                if self._m2_trip_plan_without_weather(ticket)
                else ["attraction", "weather", "itinerary", "budget"]
            )
            reasons.append("fixed_template_partial_replan_default")
        return agents, self._tools_for_agents(agents), _ordered_unique(reasons)

    async def _run_adaptive_multi_agent(self, case: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        plan = self._select_adaptive_research_plan(case)
        previous_state = self._goal_state_previous_state(case)
        reused_tool_results = self._reused_research_tool_results(
            previous_state=previous_state,
            scheduler_metadata=plan.get("scheduler"),
        )
        scheduler_metadata = self._scheduler_metadata_with_reuse_execution(
            scheduler_metadata=plan.get("scheduler"),
            previous_state=previous_state,
            reused_tool_results=reused_tool_results,
        )
        execution_case = self._case_with_goal_state_slots(
            case,
            scheduler_metadata=scheduler_metadata,
        )
        return await self._run_research_multi_agent(
            case=execution_case,
            request_id=request_id,
            method="adaptive_multi_agent",
            planned_agents=plan["agents"],
            planned_tools=plan["tools"],
            scheduler_metadata=scheduler_metadata,
            initial_tool_results=reused_tool_results,
        )

    async def _run_research_multi_agent(
        self,
        *,
        case: Dict[str, Any],
        request_id: str,
        method: ExperimentMethod,
        planned_agents: List[str],
        planned_tools: List[str],
        scheduler_metadata: Optional[Dict[str, Any]] = None,
        initial_tool_results: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        session_id = self._case_session_id(case, method)
        with request_trace(
            request_id,
            session_id,
            user_message=case["user_input"],
            experiment_case_id=case["case_id"],
            method=method,
            evaluation_mode=case["evaluation_mode"],
        ) as trace:
            if trace is not None:
                self._initialize_trace_for_evaluation(case)
                set_trace_selected_agents(planned_agents)
                record_planned_tools(planned_tools)
                if method == "adaptive_multi_agent" and scheduler_metadata is not None:
                    set_trace_scheduler_info(scheduler_metadata)

            reused_agent_outputs = self._reused_research_agent_outputs(
                previous_state=self._goal_state_previous_state(case),
                reused_agents=self._actual_reused_agents_from_scheduler(scheduler_metadata),
            )
            tool_results, agent_outputs, executed_agents = await self._execute_research_tool_plan(
                case=case,
                agents=planned_agents,
                tools=planned_tools,
                initial_tool_results=initial_tool_results,
                initial_agent_outputs=reused_agent_outputs,
                scheduler_metadata=scheduler_metadata,
            )
            result = await self._build_research_method_output(
                case=case,
                method=method,
                planned_agents=planned_agents,
                planned_tools=planned_tools,
                tool_results=tool_results,
                agent_outputs=agent_outputs,
                executed_agents=executed_agents,
                scheduler_metadata=scheduler_metadata,
                called_tools=list(trace.tool_calls) if trace is not None else [],
            )
            result_scheduler = _nested_mapping(result, "metadata", "adaptive_scheduler")
            if method == "adaptive_multi_agent" and isinstance(result_scheduler, dict):
                set_trace_scheduler_info(result_scheduler)
            set_trace_result_summary(result, offline_data=self._offline_data_summary(compact=True))
            return result

    async def _execute_research_tool_plan(
        self,
        *,
        case: Dict[str, Any],
        agents: List[str],
        tools: List[str],
        initial_tool_results: Optional[Dict[str, Any]] = None,
        initial_agent_outputs: Optional[Dict[str, Any]] = None,
        scheduler_metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any], List[str]]:
        catalog = {tool.name: tool for tool in generation_tools()}
        executor = ToolExecutor(tools=catalog)
        tool_results: Dict[str, Any] = dict(initial_tool_results or {})
        agent_outputs: Dict[str, Any] = dict(initial_agent_outputs or {})
        executed_agents: List[str] = []
        planned_tool_set = set(tools)
        failed_agents: set[str] = set()

        for agent_name in agents:
            blocked_by = self._blocked_upstream_agents(
                agent_name,
                tool_results,
                failed_agents,
                case=case,
                scheduler_metadata=scheduler_metadata,
            )
            if blocked_by:
                if self._can_skip_blocked_itinerary_with_previous_state(
                    agent_name=agent_name,
                    case=case,
                    previous_state=self._goal_state_previous_state(case),
                ):
                    continue
                mark_trace_status(
                    "failed",
                    error=(
                        f"{agent_name} skipped because upstream result is unavailable: "
                        f"{', '.join(blocked_by)}"
                    ),
                )
                failed_agents.add(agent_name)
                continue
            if agent_name not in executed_agents:
                executed_agents.append(agent_name)
            agent_tools = [
                tool_name
                for tool_name in self._tools_for_research_agent(agent_name)
                if tool_name in planned_tool_set
            ]
            agent_run = start_agent_run(agent_name)
            agent_error: Optional[str] = None
            agent_usage: Dict[str, Any] = {}
            agent_llm_call_count = 0
            try:
                with trace_component(agent_name, agent_name=agent_name):
                    for tool_name in agent_tools:
                        arguments = self._research_tool_arguments(
                            tool_name,
                            case,
                            tool_results,
                            agent_outputs=agent_outputs,
                            scheduler_metadata=scheduler_metadata,
                        )
                        call = await executor.execute(
                            tool_name=tool_name,
                            arguments=arguments,
                            call_id=f"{agent_name}-{tool_name}-{uuid.uuid4().hex[:6]}",
                        )
                        tool_results[tool_name] = call.result
                        if call.is_failed or call.error:
                            agent_error = f"{tool_name}: {call.error or call.status.value}"
                            mark_trace_status("failed", error=agent_error)
                            break
                    if not agent_error:
                        try:
                            agent_llm_call_count = 1
                            agent_output = await self._run_research_agent_llm(
                                agent_name=agent_name,
                                case=case,
                                tool_results=tool_results,
                                upstream_agent_outputs=agent_outputs,
                                scheduler_metadata=scheduler_metadata,
                            )
                            agent_outputs[agent_name] = agent_output
                            agent_usage = dict(agent_output.get("usage") or {})
                            if not self._agent_output_available(agent_name, agent_outputs):
                                agent_error = str(
                                    agent_output.get("error")
                                    or f"{agent_name}_decision_invalid"
                                )
                                mark_trace_status("failed", error=agent_error)
                        except Exception as exc:
                            agent_error = f"{agent_name}_llm: {exc}"
                            agent_outputs[agent_name] = self._failed_research_agent_output(
                                agent_name=agent_name,
                                error=agent_error,
                            )
                            mark_trace_status("failed", error=agent_error)
                finish_agent_run(
                    agent_run,
                    agent_name=agent_name,
                    status="failed" if agent_error else "completed",
                    tokens=agent_usage.get("total_tokens"),
                    usage=agent_usage if agent_usage else None,
                    llm_call_count=agent_llm_call_count,
                    tool_count=len(agent_tools),
                    error=agent_error,
                )
                if agent_error:
                    failed_agents.add(agent_name)
            except BaseException as exc:
                finish_agent_run(
                    agent_run,
                    agent_name=agent_name,
                    status="failed",
                    llm_call_count=agent_llm_call_count,
                    tool_count=len(agent_tools),
                    error=exc,
                )
                raise
        return tool_results, agent_outputs, executed_agents

    def _can_skip_blocked_itinerary_with_previous_state(
        self,
        *,
        agent_name: str,
        case: Dict[str, Any],
        previous_state: Optional[Dict[str, Any]],
    ) -> bool:
        return (
            agent_name == "itinerary"
            and self._case_constraint_task_type(case) == "weather_adjustment"
            and bool(self._previous_daily_itinerary_from_state(previous_state))
        )

    def _blocked_upstream_agents(
        self,
        agent_name: str,
        tool_results: Dict[str, Any],
        failed_agents: set[str],
        *,
        case: Dict[str, Any],
        scheduler_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        blocked: List[str] = []
        dependencies = self._dependencies_for_research_agent(
            agent_name,
            scheduler_metadata=scheduler_metadata,
        )
        if agent_name == "budget" and not self._budget_requires_attraction_evidence(
            scheduler_metadata
        ):
            dependencies = ()
        for upstream in dependencies:
            if upstream in failed_agents or not self._agent_result_available_for_execution(
                upstream,
                tool_results,
            ):
                blocked.append(upstream)
        return blocked

    def _dependencies_for_research_agent(
        self,
        agent_name: str,
        *,
        scheduler_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        dependencies = list(RESULT_DEPENDENCIES.get(agent_name, ()))
        if (
            agent_name == "itinerary"
            and "weather" in dependencies
            and scheduler_metadata is not None
            and not self._scheduler_requires_weather_for_itinerary(scheduler_metadata)
        ):
            dependencies.remove("weather")
        if (
            agent_name == "itinerary"
            and "attraction" in dependencies
            and self._is_fixed_template_scheduler(scheduler_metadata)
            and "attraction" not in set(
                _as_list(self._scheduler_decision(scheduler_metadata).get("planned_agents"))
            )
        ):
            dependencies.remove("attraction")
        if (
            agent_name == "budget"
            and "itinerary" not in dependencies
            and self._scheduler_requires_itinerary_for_budget(scheduler_metadata)
        ):
            dependencies.append("itinerary")
        return dependencies

    def _scheduler_requires_itinerary_for_budget(
        self,
        scheduler_metadata: Optional[Dict[str, Any]],
    ) -> bool:
        ticket = scheduler_metadata.get("ticket") if isinstance(scheduler_metadata, dict) else None
        if not isinstance(ticket, dict):
            return False
        if self._is_fixed_template_scheduler(scheduler_metadata):
            decision = self._scheduler_decision(scheduler_metadata)
            return "itinerary" in set(_as_list(decision.get("planned_agents")))
        task_type = str(ticket.get("task_type") or "").strip()
        if task_type == "budget_query":
            return False
        if task_type in {
            "trip_planning",
            "trip_plan",
            "weather_aware_trip_plan",
            "partial_replan",
            "weather_adjustment",
        }:
            return True
        capabilities = set(_as_list(ticket.get("required_capabilities")))
        return "itinerary_generation" in capabilities

    def _scheduler_requires_weather_for_itinerary(
        self,
        scheduler_metadata: Optional[Dict[str, Any]],
    ) -> bool:
        ticket = scheduler_metadata.get("ticket") if isinstance(scheduler_metadata, dict) else None
        if self._is_fixed_template_scheduler(scheduler_metadata):
            decision = self._scheduler_decision(scheduler_metadata)
            return "weather" in set(_as_list(decision.get("planned_agents")))
        if not isinstance(ticket, dict):
            return True
        task_type = str(ticket.get("task_type") or "").strip()
        if task_type == "trip_plan":
            return False
        current_slots = ticket.get("current_slots") if isinstance(ticket.get("current_slots"), dict) else {}
        if task_type == "partial_replan" and not (
            current_slots.get("start_date") or current_slots.get("weather_scenario")
        ):
            return False
        capabilities = set(_as_list(ticket.get("required_capabilities")))
        if "weather_evidence" in capabilities:
            return True
        if current_slots.get("start_date") or current_slots.get("weather_scenario"):
            return True
        decision = self._scheduler_decision(scheduler_metadata)
        weather_agents = {
            *_as_list(decision.get("planned_agents")),
            *_as_list(decision.get("reused_agents")),
        }
        return "weather" in weather_agents

    def _budget_requires_attraction_evidence(
        self,
        scheduler_metadata: Optional[Dict[str, Any]],
    ) -> bool:
        ticket = scheduler_metadata.get("ticket") if isinstance(scheduler_metadata, dict) else None
        dependency_policy = (
            ticket.get("dependency_policy")
            if isinstance(ticket, dict) and isinstance(ticket.get("dependency_policy"), dict)
            else {}
        )
        if "requires_attraction_evidence" in dependency_policy:
            return bool(dependency_policy.get("requires_attraction_evidence"))
        if self._is_fixed_template_scheduler(scheduler_metadata):
            decision = self._scheduler_decision(scheduler_metadata)
            return "attraction" in set(_as_list(decision.get("planned_agents")))
        return True

    def _is_fixed_template_scheduler(
        self,
        scheduler_metadata: Optional[Dict[str, Any]],
    ) -> bool:
        return (
            isinstance(scheduler_metadata, dict)
            and str(scheduler_metadata.get("name") or "") == "fixed_template_scheduler"
        )

    def _agent_result_available_for_execution(
        self,
        agent_name: str,
        tool_results: Dict[str, Any],
    ) -> bool:
        if agent_name == "attraction":
            return self._is_successful_reusable_tool_result(
                tool_results.get("poi_search")
            ) and bool(self._attractions_from_tool_result(tool_results.get("poi_search")))
        if agent_name == "weather":
            weather_result = tool_results.get("weather_query")
            if not self._is_successful_reusable_tool_result(weather_result):
                return False
            weather = self._tool_data(weather_result)
            coverage_status = str(weather.get("coverage_status") or "").lower()
            if coverage_status in {"full", "partial", "out_of_range"}:
                return True
            return bool(weather.get("daily_weather"))
        if agent_name == "budget":
            return self._is_successful_reusable_tool_result(
                tool_results.get("budget_calculator")
            )
        return True

    def _tools_for_research_agent(self, agent_name: str) -> List[str]:
        mapping = {
            "attraction": ["poi_search"],
            "weather": ["weather_query"],
            "itinerary": [],
            "budget": ["budget_calculator"],
        }
        return mapping.get(agent_name, [])

    def _evidence_tools_for_research_agent(
        self,
        agent_name: str,
        *,
        scheduler_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        mapping = {
            "attraction": ["poi_search"],
            "weather": ["weather_query"],
            "itinerary": ["poi_search", "weather_query"],
            "budget": ["poi_search", "budget_calculator"],
        }
        evidence_tools = list(mapping.get(agent_name, []))
        if (
            agent_name == "itinerary"
            and "weather_query" in evidence_tools
            and scheduler_metadata is not None
            and not self._scheduler_requires_weather_for_itinerary(scheduler_metadata)
        ):
            evidence_tools.remove("weather_query")
        return evidence_tools

    async def _run_research_agent_llm(
        self,
        *,
        agent_name: str,
        case: Dict[str, Any],
        tool_results: Dict[str, Any],
        upstream_agent_outputs: Dict[str, Any],
        scheduler_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        llm = self.llm_factory()
        messages = self._research_agent_prompt_messages(
            agent_name=agent_name,
            case=case,
            tool_results=tool_results,
            upstream_agent_outputs=upstream_agent_outputs,
            scheduler_metadata=scheduler_metadata,
        )
        started = time.perf_counter()
        try:
            response = await self._llm_chat_with_experiment_timeout(llm, messages)
        except TimeoutError as exc:
            response = type(
                "ExperimentTimeoutResponse",
                (),
                {"content": "", "usage": {}, "tool_calls": []},
            )()
            parse_timeout_error = f"agent decision llm timeout: {exc}"
        except Exception as exc:
            transport_reason = _agent_llm_transport_error_reason(exc)
            if transport_reason is None:
                raise
            response = type(
                "ExperimentTransportErrorResponse",
                (),
                {"content": "", "usage": {}, "tool_calls": []},
            )()
            parse_timeout_error = (
                f"agent decision llm transport error: {transport_reason}: {exc}"
            )
        else:
            parse_timeout_error = None
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        usage = dict(getattr(response, "usage", None) or {})
        content = str(getattr(response, "content", "") or "")
        decision, parse_error = self._parse_research_agent_decision(content)
        parse_error = parse_timeout_error or parse_error
        validation_errors = self._research_agent_decision_validation_errors(
            agent_name=agent_name,
            decision=decision,
            case=case,
            tool_results=tool_results,
        )
        llm_parse_error = parse_error
        llm_validation_errors = list(validation_errors)
        llm_decision_errors = [
            error
            for error in [parse_error, *validation_errors]
            if error
        ]
        decision_source = "llm"
        decision_fallback_used = False
        decision_fallback_errors: List[str] = []
        decision_normalizer_enabled = self.enable_research_agent_decision_normalizer
        decision_normalizer_skipped = False

        if llm_decision_errors and decision_normalizer_enabled:
            fallback_decision = self._normalized_research_agent_decision_from_evidence(
                agent_name=agent_name,
                case=case,
                tool_results=tool_results,
                original_errors=llm_decision_errors,
            )
            if fallback_decision is not None:
                decision_fallback_errors = self._research_agent_decision_validation_errors(
                    agent_name=agent_name,
                    decision=fallback_decision,
                    case=case,
                    tool_results=tool_results,
                )
                if not decision_fallback_errors:
                    decision = fallback_decision
                    parse_error = None
                    validation_errors = []
                    decision_source = "deterministic_evidence_normalizer"
                    decision_fallback_used = True
        elif llm_decision_errors:
            decision_normalizer_skipped = True

        decision_errors = [
            error
            for error in [parse_error, *validation_errors]
            if error
        ]
        decision_valid = not decision_errors
        status = "completed" if decision_valid else "failed"
        output = {
            "schema_version": RESEARCH_AGENT_OUTPUT_SCHEMA_VERSION,
            "agent_name": agent_name,
            "status": status,
            "success": decision_valid,
            "reused": False,
            "prompt_version": RESEARCH_AGENT_PROMPT_VERSION,
            "evidence_tools": self._evidence_tools_for_research_agent(
                agent_name,
                scheduler_metadata=scheduler_metadata,
            ),
            "upstream_agents": self._dependencies_for_research_agent(
                agent_name,
                scheduler_metadata=scheduler_metadata,
            ),
            "content": content,
            "decision_schema_version": RESEARCH_AGENT_DECISION_SCHEMA_VERSION,
            "decision": _jsonable_value(decision or {}),
            "decision_source": decision_source,
            "decision_fallback_used": decision_fallback_used,
            "decision_normalizer_enabled": decision_normalizer_enabled,
            "decision_normalizer_skipped": decision_normalizer_skipped,
            "decision_parse_status": "passed" if parse_error is None else "failed",
            "decision_validation_status": "passed" if not validation_errors else "failed",
            "decision_errors": decision_errors,
            "llm_decision_parse_status": "passed" if llm_parse_error is None else "failed",
            "llm_decision_validation_status": (
                "passed" if not llm_validation_errors else "failed"
            ),
            "llm_decision_errors": llm_decision_errors,
            "usage": usage,
            "prompt_tokens": usage.get("prompt_tokens") or usage.get("input_tokens"),
            "completion_tokens": (
                usage.get("completion_tokens") or usage.get("output_tokens")
            ),
            "total_tokens": usage.get("total_tokens") or usage.get("tokens_used"),
            "duration_ms": duration_ms,
            "llm_call_count": 1,
            **({"error": "; ".join(decision_errors)} if decision_errors else {}),
        }
        if decision_fallback_used:
            output["decision_fallback_reason"] = "; ".join(llm_decision_errors)
            output["decision_normalizer_version"] = (
                RESEARCH_AGENT_DECISION_NORMALIZER_VERSION
            )
        elif decision_normalizer_skipped:
            output["decision_normalizer_skip_reason"] = (
                "disabled_for_ablation; original LLM decision errors preserved"
            )
        elif decision_fallback_errors:
            output["decision_fallback_errors"] = decision_fallback_errors
        return output

    def _parse_research_agent_decision(
        self,
        raw_content: Any,
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        if not isinstance(raw_content, str) or not raw_content.strip():
            return None, "agent decision output is empty or not text"
        try:
            parsed = json.loads(raw_content.strip())
        except json.JSONDecodeError as exc:
            return None, f"agent decision output is not strict JSON: {exc.msg}"
        if not isinstance(parsed, dict):
            return None, "agent decision output must be a JSON object"
        return parsed, None

    def _research_agent_decision_validation_errors(
        self,
        *,
        agent_name: str,
        decision: Optional[Dict[str, Any]],
        case: Dict[str, Any],
        tool_results: Dict[str, Any],
    ) -> List[str]:
        if decision is None:
            return []
        errors: List[str] = []
        if decision.get("schema_version") != RESEARCH_AGENT_DECISION_SCHEMA_VERSION:
            errors.append("decision schema_version mismatch")
        if str(decision.get("agent_name") or "") != agent_name:
            errors.append("decision agent_name mismatch")
        decisions = decision.get("decisions")
        if not isinstance(decisions, dict):
            errors.append("decisions must be an object")
            decisions = {}
        risks = decision.get("risks")
        if "risks" in decision and not isinstance(risks, list):
            errors.append("risks must be a list")
        confidence = decision.get("confidence")
        if confidence is not None:
            try:
                parsed_confidence = float(confidence)
            except (TypeError, ValueError):
                errors.append("confidence must be numeric")
            else:
                if parsed_confidence < 0 or parsed_confidence > 1:
                    errors.append("confidence must be between 0 and 1")

        if agent_name == "attraction":
            errors.extend(self._validate_attraction_agent_decision(decisions, tool_results))
        elif agent_name == "weather":
            errors.extend(self._validate_weather_agent_decision(decisions, tool_results))
        elif agent_name == "itinerary":
            errors.extend(self._validate_itinerary_agent_decision(decisions, case, tool_results))
        elif agent_name == "budget":
            errors.extend(self._validate_budget_agent_decision(decisions))
        return errors

    def _validate_attraction_agent_decision(
        self,
        decisions: Dict[str, Any],
        tool_results: Dict[str, Any],
    ) -> List[str]:
        evidence_ids = set(self._poi_ids_from_result(tool_results.get("poi_search")))
        selected = _as_list(decisions.get("selected_poi_ids"))
        if evidence_ids and not selected:
            return ["attraction decision must include selected_poi_ids"]
        unknown = sorted(set(selected) - evidence_ids)
        return [f"selected_poi_ids contain non-evidence ids: {unknown}"] if unknown else []

    def _validate_weather_agent_decision(
        self,
        decisions: Dict[str, Any],
        tool_results: Dict[str, Any],
    ) -> List[str]:
        weather = self._tool_data(tool_results.get("weather_query"))
        weather_days = self._weather_day_items(weather)
        day_count = len(weather_days)
        allowed_days = {
            _first_positive_int(item.get("day_index"), item.get("day"), default=0)
            for item in weather_days
        }
        allowed_days = {day for day in allowed_days if day > 0}
        risk_days = _int_list(decisions.get("risk_days"))
        errors: List[str] = []
        if allowed_days and any(day not in allowed_days for day in risk_days):
            errors.append("risk_days must refer to days present in weather evidence")
        elif day_count and any(day < 1 or day > day_count for day in risk_days):
            errors.append("risk_days must refer to days present in weather evidence")
        if "adjustment_required" in decisions and not isinstance(
            decisions.get("adjustment_required"),
            bool,
        ):
            errors.append("adjustment_required must be boolean")
        return errors

    def _validate_itinerary_agent_decision(
        self,
        decisions: Dict[str, Any],
        case: Dict[str, Any],
        tool_results: Dict[str, Any],
    ) -> List[str]:
        daily = decisions.get("daily_itinerary")
        if not isinstance(daily, list) or not daily:
            return ["itinerary decision must include non-empty daily_itinerary"]
        evidence_ids = set(
            self._poi_ids_from_attractions(
                self._itinerary_evidence_attractions(
                    case=case,
                    tool_results=tool_results,
                )
            )
        )
        trip_days = self._case_duration(case)
        errors: List[str] = []
        seen_days: set[int] = set()
        total_poi_refs = 0
        for item in daily:
            if not isinstance(item, dict):
                errors.append("daily_itinerary items must be objects")
                continue
            day = _first_positive_int(item.get("day"), item.get("day_index"), default=0)
            if day < 1 or day > trip_days:
                errors.append("daily_itinerary day is outside trip duration")
            else:
                seen_days.add(day)
            poi_ids = _as_list(item.get("attraction_poi_ids"))
            total_poi_refs += len(poi_ids)
            unknown = sorted(set(poi_ids) - evidence_ids)
            if unknown:
                errors.append(f"daily_itinerary references non-evidence POI ids: {unknown}")
        if len(seen_days) < trip_days:
            errors.append("daily_itinerary must cover every trip day")
        if evidence_ids and total_poi_refs == 0:
            errors.append("daily_itinerary must include at least one evidence POI")
        return errors

    def _validate_budget_agent_decision(self, decisions: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        if decisions.get("recommended_total") is not None:
            try:
                float(decisions.get("recommended_total"))
            except (TypeError, ValueError):
                errors.append("recommended_total must be numeric when present")
        feasibility = decisions.get("feasibility")
        if feasibility is not None and not isinstance(feasibility, str):
            errors.append("feasibility must be text when present")
        return errors

    def _normalized_research_agent_decision_from_evidence(
        self,
        *,
        agent_name: str,
        case: Dict[str, Any],
        tool_results: Dict[str, Any],
        original_errors: List[str],
    ) -> Optional[Dict[str, Any]]:
        """Build a valid agent decision from already recorded tool evidence.

        The normalizer is deliberately conservative: it never calls extra tools
        and returns ``None`` when the evidence needed by the agent is missing.
        """
        decision: Dict[str, Any] = {
            "schema_version": RESEARCH_AGENT_DECISION_SCHEMA_VERSION,
            "agent_name": agent_name,
            "summary": (
                "LLM decision was invalid; normalized deterministically from "
                "available offline tool evidence."
            ),
            "decisions": {},
            "risks": [
                {
                    "type": "llm_decision_format_repaired",
                    "details": str("; ".join(original_errors))[:500],
                }
            ],
            "confidence": 0.55,
            "metadata": {
                "normalizer_version": RESEARCH_AGENT_DECISION_NORMALIZER_VERSION,
                "source": "offline_tool_evidence",
            },
        }

        if agent_name == "attraction":
            selected_ids = self._poi_ids_from_result(tool_results.get("poi_search"))
            requested_count = self._case_requested_poi_count(case)
            if requested_count is not None:
                selected_ids = selected_ids[:requested_count]
            if not selected_ids:
                return None
            decision["decisions"] = {"selected_poi_ids": selected_ids}
            return decision

        if agent_name == "weather":
            weather = self._tool_data(tool_results.get("weather_query"))
            if not weather:
                return None
            adjustment_required = self._weather_adjustment_required_from_evidence(
                case,
                weather,
            )
            decision["decisions"] = {
                "risk_days": (
                    self._affected_weather_days(case, weather)
                    if adjustment_required
                    else []
                ),
                "adjustment_required": adjustment_required,
            }
            return decision

        if agent_name == "itinerary":
            attractions = self._itinerary_evidence_attractions(
                case=case,
                tool_results=tool_results,
            )
            if not attractions:
                return None
            daily_itinerary = self._normalized_decision_daily_itinerary(
                self._case_duration(case),
                attractions,
                case=case,
                weather=self._tool_data(tool_results.get("weather_query")),
            )
            if not daily_itinerary:
                return None
            decision["decisions"] = {"daily_itinerary": daily_itinerary}
            return decision

        if agent_name == "budget":
            budget = self._tool_data(tool_results.get("budget_calculator"))
            if not budget:
                return None
            decision["decisions"] = {
                "feasibility": self._budget_feasibility_from_evidence(case, budget),
                "budget_notes": "按固定离线预算工具结果生成实验归一化预算判断",
                "recommended_total": self._budget_total_from_evidence(budget),
            }
            return decision

        return None

    def _normalized_decision_daily_itinerary(
        self,
        trip_days: int,
        attractions: List[Dict[str, Any]],
        *,
        case: Optional[Dict[str, Any]] = None,
        weather: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        weather_payload = weather if isinstance(weather, dict) else {}
        attractions = self._select_constraint_aware_attractions(
            attractions,
            case=case or {},
            weather=weather_payload,
        )
        poi_ids = [
            str(item.get("poi_id"))
            for item in attractions
            if item.get("poi_id")
        ]
        if trip_days < 1 or not poi_ids:
            return []
        by_id = {
            str(item.get("poi_id")): item
            for item in attractions
            if item.get("poi_id")
        }
        risk_days = set(
            self._affected_weather_days(case, weather_payload)
            if weather_payload and self._weather_adjustment_required_from_evidence(
                case or {},
                weather_payload,
            )
            else []
        )
        safe_ids = [
            poi_id
            for poi_id in poi_ids
            if self._poi_preferred_for_weather_risk(by_id.get(poi_id) or {})
        ]
        normal_ids = [
            poi_id
            for poi_id in poi_ids
            if poi_id not in set(safe_ids)
        ]
        daily: List[Dict[str, Any]] = []
        used_ids: set[str] = set()
        for day in range(1, trip_days + 1):
            if day in risk_days:
                candidates = [
                    *[poi_id for poi_id in safe_ids if poi_id not in used_ids],
                    *[poi_id for poi_id in normal_ids if poi_id not in used_ids],
                ]
            else:
                future_risk_day_count = sum(
                    1
                    for risk_day in risk_days
                    if day < risk_day <= trip_days
                )
                reserved_safe_ids = set(
                    [
                        poi_id
                        for poi_id in safe_ids
                        if poi_id not in used_ids
                    ][: future_risk_day_count * 2]
                )
                candidates = [
                    poi_id
                    for poi_id in poi_ids
                    if poi_id not in used_ids and poi_id not in reserved_safe_ids
                ] + [
                    poi_id
                    for poi_id in safe_ids
                    if poi_id not in used_ids and poi_id in reserved_safe_ids
                ]
            selected_ids = candidates[:2]
            used_ids.update(selected_ids)
            daily.append(
                {
                    "day": day,
                    "attraction_poi_ids": selected_ids,
                    "notes": "由离线 POI 证据归一化生成的日级行程决策",
                }
            )
        return daily

    def _poi_preferred_for_weather_risk(self, attraction: Dict[str, Any]) -> bool:
        indoor_outdoor = str(attraction.get("indoor_outdoor") or "").lower()
        if indoor_outdoor == "indoor":
            return True
        rain_suitability = str(attraction.get("rain_suitability") or "").lower()
        if rain_suitability == "suitable" and indoor_outdoor != "outdoor":
            return True
        try:
            outdoor_ratio = float(attraction.get("outdoor_ratio"))
        except (TypeError, ValueError):
            outdoor_ratio = 1.0
        return outdoor_ratio < 0.5

    def _case_requires_low_intensity(self, case: Dict[str, Any]) -> bool:
        people = self._case_people(case).casefold()
        slots = self._case_slots(case)
        structured = (
            case.get("structured_request")
            if isinstance(case.get("structured_request"), dict)
            else {}
        )
        text = " ".join(
            [
                str(case.get("user_input") or ""),
                str(people),
                " ".join(str(item) for item in _as_list(slots.get("special_requirements"))),
                " ".join(str(item) for item in _as_list(structured.get("special_requirements"))),
                " ".join(str(item) for item in _as_list(case.get("constraints"))),
            ]
        ).casefold()
        return any(
            term in text
            for term in (
                "senior",
                "elder",
                "老人",
                "长辈",
                "父母",
                "低强度",
                "轻松",
                "少走路",
                "少步行",
                "less_walking",
                "low_intensity",
                "relaxed",
            )
        )

    def _poi_preferred_for_low_intensity(self, attraction: Dict[str, Any]) -> bool:
        intensity = str(attraction.get("visit_intensity") or "").lower()
        walking_level = str(attraction.get("walking_level") or "").lower()
        return intensity != "high" and walking_level != "high"

    def _weather_adjustment_required_from_evidence(
        self,
        case: Dict[str, Any],
        weather: Dict[str, Any],
    ) -> bool:
        scenario = str(
            weather.get("scenario_type")
            or self._case_weather_scenario(case)
            or ""
        )
        if scenario in {
            "rain",
            "high_temperature",
            "low_temperature",
            "continuous_change",
        }:
            return True
        if bool(weather.get("weather_adjustment_required")):
            return True
        return any(self._is_risky_weather_day(item) for item in self._weather_day_items(weather))

    def _budget_total_from_evidence(self, budget: Dict[str, Any]) -> Optional[float]:
        for key in (
            "total",
            "recommended_total",
            "estimated_total",
            "total_cost",
            "total_cost_cny",
        ):
            value = budget.get(key)
            if value is None or value == "":
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    def _budget_feasibility_from_evidence(
        self,
        case: Dict[str, Any],
        budget: Dict[str, Any],
    ) -> str:
        for key in ("feasibility", "status", "budget_status"):
            value = budget.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        total = self._budget_total_from_evidence(budget)
        limit = self._case_budget_limit(case)
        if total is None or limit is None:
            return "unknown"
        return "feasible" if total <= limit else "over_budget"

    def _research_agent_prompt_messages(
        self,
        *,
        agent_name: str,
        case: Dict[str, Any],
        tool_results: Dict[str, Any],
        upstream_agent_outputs: Dict[str, Any],
        scheduler_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[LLMMessage]:
        role = {
            "attraction": "Attraction Agent: assess POI evidence and select reliable attraction evidence.",
            "weather": "Weather Agent: assess weather evidence and identify travel risks.",
            "itinerary": "Itinerary Agent: combine attraction evidence and any available weather evidence into a day-level plan.",
            "budget": "Budget Agent: assess budget evidence and explain cost feasibility.",
        }.get(agent_name, f"{agent_name} Agent")
        context = self._research_agent_prompt_context(
            agent_name=agent_name,
            case=case,
            tool_results=tool_results,
            upstream_agent_outputs=upstream_agent_outputs,
            scheduler_metadata=scheduler_metadata,
        )
        return [
            LLMMessage(
                role="system",
                content=(
                    f"{role}\n"
                    "Use only the supplied offline evidence. Do not invent new attractions, weather, "
                    "prices, or tools. Return strict JSON only. Required top-level keys: "
                    "schema_version, agent_name, summary, decisions, risks, confidence. "
                    f"schema_version must be {RESEARCH_AGENT_DECISION_SCHEMA_VERSION}. "
                    "Attraction decisions use selected_poi_ids. Weather decisions use risk_days "
                    "and adjustment_required. Itinerary decisions use daily_itinerary items with "
                    "day and attraction_poi_ids. Budget decisions use feasibility, budget_notes, "
                    "and optional recommended_total."
                ),
            ),
            LLMMessage(
                role="user",
                content=json.dumps(context, ensure_ascii=False, default=str),
            ),
        ]

    def _research_agent_prompt_context(
        self,
        *,
        agent_name: str,
        case: Dict[str, Any],
        tool_results: Dict[str, Any],
        upstream_agent_outputs: Dict[str, Any],
        scheduler_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        evidence_tools = self._evidence_tools_for_research_agent(
            agent_name,
            scheduler_metadata=scheduler_metadata,
        )
        upstream_agents = self._dependencies_for_research_agent(
            agent_name,
            scheduler_metadata=scheduler_metadata,
        )
        return {
            "prompt_version": RESEARCH_AGENT_PROMPT_VERSION,
            "agent_name": agent_name,
            "user_request": str(case.get("user_input") or ""),
            "task_slots": {
                "city": self._case_city(case),
                "origin": self._case_origin(case),
                "duration_days": self._case_duration(case),
                "start_date": self._case_start_date(case),
                "people_count": self._case_traveler_count(case),
                "preferences": self._case_preferences(case),
                "budget_amount": self._case_budget_limit(case),
                "budget_basis": self._case_budget_basis(case),
                "requested_budget_scope": self._case_requested_budget_scope(case),
                "intercity_transport_included": self._case_intercity_transport_included(case),
                "mandatory_budget_disclaimer": self._case_mandatory_budget_disclaimer(case),
                "budget_level": self._case_budget_level(case),
                "hotel_level": self._case_hotel_level(case),
                "food_level": self._case_food_level(case),
            },
            "tool_evidence": {
                tool_name: self._compact_tool_result_for_prompt(
                    tool_name,
                    tool_results.get(tool_name),
                )
                for tool_name in evidence_tools
                if tool_name in tool_results
            },
            "upstream_agent_outputs": {
                upstream: self._compact_agent_output_for_prompt(
                    upstream_agent_outputs.get(upstream)
                )
                for upstream in upstream_agents
                if upstream in upstream_agent_outputs
            },
            "draft_daily_itinerary": (
                self._build_daily_itinerary(
                    self._case_duration(case),
                    self._itinerary_evidence_attractions(
                        case=case,
                        tool_results=tool_results,
                    ),
                )
                if agent_name == "itinerary"
                else []
            ),
        }

    def _compact_prompt_value(self, value: Any, *, max_chars: int = 3500) -> Any:
        payload = _jsonable_value(value)
        text = json.dumps(payload, ensure_ascii=False, default=str)
        if len(text) <= max_chars:
            return payload
        return {
            "truncated": True,
            "original_chars": len(text),
            "preview": text[:max_chars],
        }

    def _compact_tool_result_for_prompt(self, tool_name: str, value: Any) -> Any:
        payload = _jsonable_value(value)
        if tool_name != "poi_search" or not isinstance(payload, dict):
            return self._compact_prompt_value(payload)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        attractions = data.get("attractions") if isinstance(data, dict) else []
        if not isinstance(attractions, list):
            return self._compact_prompt_value(payload)
        compact_attractions = [
            self._compact_poi_for_agent_prompt(item)
            for item in attractions
            if isinstance(item, dict)
        ]
        compact_payload = {
            **payload,
            "data": {
                **data,
                "attractions": compact_attractions,
            },
        }
        return self._compact_prompt_value(compact_payload, max_chars=12000)

    def _compact_poi_for_agent_prompt(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: item.get(key)
            for key in (
                "poi_id",
                "name",
                "city_id",
                "category",
                "tags",
                "indoor_outdoor",
                "outdoor_ratio",
                "rain_suitability",
                "high_temperature_suitability",
                "low_temperature_suitability",
                "visit_intensity",
                "walking_level",
                "recommended_duration_hours",
                "ticket_price_cny",
                "ticket_price_known",
                "transport_node_id",
            )
            if item.get(key) is not None
        }

    def _compact_agent_output_for_prompt(self, value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        return {
            "agent_name": value.get("agent_name"),
            "status": value.get("status"),
            "reused": bool(value.get("reused")),
            "prompt_version": value.get("prompt_version"),
            "decision_parse_status": value.get("decision_parse_status"),
            "decision_validation_status": value.get("decision_validation_status"),
            "decision": _jsonable_value(value.get("decision") or {}),
            "content": str(value.get("content") or "")[:1200],
        }

    def _compact_agent_outputs_for_answer(
        self,
        agent_outputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            agent_name: self._compact_agent_output_for_prompt(output)
            for agent_name, output in agent_outputs.items()
            if isinstance(output, dict)
        }

    def _agent_output_available(
        self,
        agent_name: str,
        agent_outputs: Dict[str, Any],
    ) -> bool:
        output = agent_outputs.get(agent_name)
        if not isinstance(output, dict):
            return False
        status = str(output.get("status") or "").lower()
        return (
            status in {"completed", "success", "reused"}
            and output.get("success") is not False
            and not output.get("error")
        )

    def _reused_research_tool_results(
        self,
        *,
        previous_state: Optional[Dict[str, Any]],
        scheduler_metadata: Optional[Dict[str, Any]],
        ) -> Dict[str, Any]:
        decision = self._scheduler_decision(scheduler_metadata)
        previous_tool_results = self._previous_tool_results_from_state(previous_state)
        reused_agents = _as_list(decision.get("reused_agents"))
        invalidated_agents = set(_as_list(decision.get("invalidated_agents")))
        ticket = scheduler_metadata.get("ticket") if isinstance(scheduler_metadata, dict) else None
        current_slots = ticket.get("current_slots") if isinstance(ticket, dict) else {}

        reused_tool_results: Dict[str, Any] = {}
        for agent_name in reused_agents:
            if agent_name in invalidated_agents:
                continue
            if not is_goal_state_agent_reusable_for_ticket(
                agent_name,
                ticket=ticket,
                previous_state=previous_state,
            ):
                continue
            for tool_name in self._tools_for_research_agent(agent_name):
                result = previous_tool_results.get(tool_name)
                if self._is_successful_reusable_tool_result(result):
                    reused_tool_results[tool_name] = result
        return reused_tool_results

    def _scheduler_metadata_with_reuse_execution(
        self,
        *,
        scheduler_metadata: Optional[Dict[str, Any]],
        previous_state: Optional[Dict[str, Any]],
        reused_tool_results: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if scheduler_metadata is None:
            return None

        decision = self._scheduler_decision(scheduler_metadata)
        reused_agents = _as_list(decision.get("reused_agents"))
        expected_reused_tools = self._tools_for_agents(reused_agents)
        reused_tools = [tool for tool in expected_reused_tools if tool in reused_tool_results]
        missing_reused_tools = [
            tool for tool in expected_reused_tools if tool not in reused_tool_results
        ]
        ticket = scheduler_metadata.get("ticket") if isinstance(scheduler_metadata, dict) else None
        current_slots = ticket.get("current_slots") if isinstance(ticket, dict) else {}
        actual_reused_agents = self._actual_reused_agents_from_reuse_execution(
            expected_agents=reused_agents,
            reused_tool_results=reused_tool_results,
            previous_state=previous_state,
            current_slots=current_slots,
            scheduler_metadata=scheduler_metadata,
        )
        missing_reused_agents = [
            agent for agent in reused_agents if agent not in set(actual_reused_agents)
        ]
        expected_reused_tool_count = len(expected_reused_tools)
        reused_tool_result_count = len(reused_tools)
        return {
            **scheduler_metadata,
            "reuse_execution": {
                "previous_state_provided": previous_state is not None,
                "expected_reused_agents": reused_agents,
                "reused_agent_results": actual_reused_agents,
                "missing_reused_agent_results": missing_reused_agents,
                "expected_reused_agent_count": len(reused_agents),
                "reused_agent_result_count": len(actual_reused_agents),
                "missing_reused_agent_result_count": len(missing_reused_agents),
                "expected_reused_tools": expected_reused_tools,
                "reused_tool_results": reused_tools,
                "missing_reused_tool_results": missing_reused_tools,
                "expected_reused_tool_count": expected_reused_tool_count,
                "reused_tool_result_count": reused_tool_result_count,
                "missing_reused_tool_result_count": len(missing_reused_tools),
                "reuse_hit_rate": _safe_ratio(
                    reused_tool_result_count,
                    expected_reused_tool_count,
                ),
                "agent_reuse_hit_rate": _safe_ratio(
                    len(actual_reused_agents),
                    len(reused_agents),
                ),
            },
        }

    def _scheduler_decision(self, scheduler_metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(scheduler_metadata, dict):
            return {}
        decision = scheduler_metadata.get("decision")
        return decision if isinstance(decision, dict) else {}

    def _actual_reused_agents_from_reuse_execution(
        self,
        *,
        expected_agents: List[str],
        reused_tool_results: Dict[str, Any],
        previous_state: Optional[Dict[str, Any]],
        current_slots: Dict[str, Any],
        scheduler_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        actual: List[str] = []
        reused_tool_set = set(reused_tool_results)
        ticket = (
            scheduler_metadata.get("ticket")
            if isinstance(scheduler_metadata, dict)
            else None
        )
        for agent_name in expected_agents:
            if not is_goal_state_agent_reusable_for_ticket(
                agent_name,
                ticket=ticket or {"current_slots": current_slots},
                previous_state=previous_state,
            ):
                continue
            agent_tools = self._tools_for_research_agent(agent_name)
            if agent_tools:
                if all(tool_name in reused_tool_set for tool_name in agent_tools):
                    actual.append(agent_name)
                continue
            if agent_name == "itinerary" and self._previous_daily_itinerary_from_state(previous_state):
                actual.append(agent_name)
        return _ordered_unique(actual)

    def _actual_reused_agents_from_scheduler(
        self,
        scheduler_metadata: Optional[Dict[str, Any]],
    ) -> List[str]:
        if not isinstance(scheduler_metadata, dict):
            return []
        reuse_execution = scheduler_metadata.get("reuse_execution")
        if isinstance(reuse_execution, dict):
            return _as_list(reuse_execution.get("reused_agent_results"))
        return []

    def _case_with_goal_state_slots(
        self,
        case: Dict[str, Any],
        *,
        scheduler_metadata: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not isinstance(scheduler_metadata, dict):
            return case
        ticket = scheduler_metadata.get("ticket")
        current_slots = ticket.get("current_slots") if isinstance(ticket, dict) else None
        if not isinstance(current_slots, dict):
            return case
        merged_slots = dict(case.get("slots") if isinstance(case.get("slots"), dict) else {})
        merged_slots.update(current_slots)
        return {**case, "slots": merged_slots}

    def _case_for_fixed_multi_agent(self, case: Dict[str, Any]) -> Dict[str, Any]:
        previous_state = self._goal_state_previous_state(case)
        if previous_state is None:
            return case
        ticket = build_goal_state_ticket(
            user_input=str(case.get("user_input") or ""),
            current_slots=self._goal_state_current_slots(case),
            previous_state=previous_state,
        )
        if ticket.task_type in {"general_chat", "clarification"}:
            return case
        return self._case_with_goal_state_slots(
            case,
            scheduler_metadata={"ticket": ticket.to_dict()},
        )

    def _case_session_id(self, case: Dict[str, Any], method: ExperimentMethod) -> str:
        for value in (
            _nested_mapping(case, "previous_state", "trace", "session_id"),
            _nested_mapping(case, "previous_state", "session_id"),
        ):
            text = _optional_text(value)
            if text:
                return text
        for value in (
            case.get("session_id"),
            case.get("conversation_id"),
            case.get("thread_id"),
        ):
            text = _optional_text(value)
            if text:
                return self._session_id_with_repeat(text)
        return self._session_id_with_repeat(f"exp-{case['case_id']}-{method}")

    def _session_id_with_repeat(self, session_id: str) -> str:
        run_id = os.getenv("EXPERIMENT_RUN_ID")
        if run_id:
            run_suffix = f"-run-{_session_component(run_id)}"
            if not session_id.endswith(run_suffix) and run_suffix not in session_id:
                session_id = f"{session_id}{run_suffix}"
        repeat_index = os.getenv("EXPERIMENT_REPEAT_INDEX")
        if repeat_index is None:
            return session_id
        suffix = f"-r{repeat_index}"
        return session_id if session_id.endswith(suffix) else f"{session_id}{suffix}"

    def _is_successful_reusable_tool_result(self, result: Any) -> bool:
        if not isinstance(result, dict):
            return False
        status = str(result.get("status") or "").lower()
        if status in {
            "failed",
            "error",
            "timeout",
            "cancelled",
            "canceled",
            "aborted",
            "expired",
            "stale",
        }:
            return False
        if result.get("success") is False:
            return False
        return not result.get("error")

    def _previous_tool_results_from_state(
        self,
        previous_state: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not isinstance(previous_state, dict):
            return {}

        candidates = [
            previous_state.get("tool_results"),
            _nested_mapping(previous_state, "raw_output", "tool_results"),
            _nested_mapping(previous_state, "output", "tool_results"),
            _nested_mapping(previous_state, "output", "raw_output", "tool_results"),
        ]
        for candidate in candidates:
            if isinstance(candidate, dict):
                return {
                    str(tool_name): result
                    for tool_name, result in candidate.items()
                    if isinstance(result, dict)
                }
        return {}

    def _previous_agent_outputs_from_state(
        self,
        previous_state: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not isinstance(previous_state, dict):
            return {}

        candidates = [
            previous_state.get("agent_outputs"),
            _nested_mapping(previous_state, "raw_output", "agent_outputs"),
            _nested_mapping(previous_state, "output", "agent_outputs"),
            _nested_mapping(previous_state, "output", "raw_output", "agent_outputs"),
            _nested_mapping(previous_state, "metadata", "agent_outputs"),
            _nested_mapping(previous_state, "raw_output", "metadata", "agent_outputs"),
            _nested_mapping(previous_state, "output", "metadata", "agent_outputs"),
            _nested_mapping(previous_state, "output", "raw_output", "metadata", "agent_outputs"),
        ]
        for candidate in candidates:
            if isinstance(candidate, dict):
                return {
                    str(agent_name): result
                    for agent_name, result in candidate.items()
                    if isinstance(result, dict)
                }
        return {}

    def _reused_research_agent_outputs(
        self,
        *,
        previous_state: Optional[Dict[str, Any]],
        reused_agents: List[str],
    ) -> Dict[str, Any]:
        if not reused_agents:
            return {}
        previous_outputs = self._previous_agent_outputs_from_state(previous_state)
        reused_outputs: Dict[str, Any] = {}
        for agent_name in reused_agents:
            output = previous_outputs.get(agent_name)
            if isinstance(output, dict):
                previous_usage = output.get("usage") if isinstance(output.get("usage"), dict) else {}
                reused_outputs[agent_name] = {
                    **_jsonable_value(output),
                    "status": "reused",
                    "reused": True,
                    "previous_usage": _jsonable_value(previous_usage),
                    "usage": {},
                    "prompt_tokens": None,
                    "completion_tokens": None,
                    "total_tokens": None,
                    "duration_ms": 0,
                    "llm_call_count": 0,
                }
            else:
                reused_outputs[agent_name] = self._synthetic_reused_agent_output(
                    agent_name=agent_name,
                )
        return reused_outputs

    def _synthetic_reused_agent_output(self, *, agent_name: str) -> Dict[str, Any]:
        return {
            "schema_version": RESEARCH_AGENT_OUTPUT_SCHEMA_VERSION,
            "agent_name": agent_name,
            "status": "reused",
            "reused": True,
            "prompt_version": RESEARCH_AGENT_PROMPT_VERSION,
            "evidence_tools": self._evidence_tools_for_research_agent(agent_name),
            "upstream_agents": list(RESULT_DEPENDENCIES.get(agent_name, ())),
            "content": "Reused from previous method-local state.",
            "decision_schema_version": RESEARCH_AGENT_DECISION_SCHEMA_VERSION,
            "decision": {},
            "decision_parse_status": "not_available",
            "decision_validation_status": "not_available",
            "decision_errors": [],
            "usage": {},
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "duration_ms": 0,
            "llm_call_count": 0,
        }

    def _failed_research_agent_output(
        self,
        *,
        agent_name: str,
        error: Any,
    ) -> Dict[str, Any]:
        return {
            "schema_version": RESEARCH_AGENT_OUTPUT_SCHEMA_VERSION,
            "agent_name": agent_name,
            "status": "failed",
            "success": False,
            "reused": False,
            "prompt_version": RESEARCH_AGENT_PROMPT_VERSION,
            "evidence_tools": self._evidence_tools_for_research_agent(agent_name),
            "upstream_agents": list(RESULT_DEPENDENCIES.get(agent_name, ())),
            "content": "",
            "decision_schema_version": RESEARCH_AGENT_DECISION_SCHEMA_VERSION,
            "decision": {},
            "decision_parse_status": "failed",
            "decision_validation_status": "failed",
            "decision_errors": [str(error)],
            "usage": {},
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "duration_ms": None,
            "llm_call_count": 1,
            "error": str(error),
        }

    def _previous_daily_itinerary_from_state(
        self,
        previous_state: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not isinstance(previous_state, dict):
            return []
        for candidate in (
            previous_state.get("daily_itinerary"),
            _nested_mapping(previous_state, "raw_output", "daily_itinerary"),
            _nested_mapping(previous_state, "output", "daily_itinerary"),
            _nested_mapping(previous_state, "output", "raw_output", "daily_itinerary"),
        ):
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
            if isinstance(candidate, dict) and isinstance(candidate.get("days"), list):
                return [item for item in candidate["days"] if isinstance(item, dict)]
        return []

    def _previous_attractions_from_state(
        self,
        previous_state: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not isinstance(previous_state, dict):
            return []
        for candidate in (
            previous_state.get("attractions"),
            _nested_mapping(previous_state, "raw_output", "attractions"),
            _nested_mapping(previous_state, "output", "attractions"),
            _nested_mapping(previous_state, "output", "raw_output", "attractions"),
            self._attractions_from_tool_result(
                self._previous_tool_results_from_state(previous_state).get("poi_search")
            ),
        ):
            if isinstance(candidate, list) and candidate:
                return [
                    _jsonable_value(item)
                    for item in candidate
                    if isinstance(item, dict)
                ]
        return []

    def _itinerary_evidence_attractions(
        self,
        *,
        case: Dict[str, Any],
        tool_results: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Return POI evidence that an itinerary decision may legally use.

        Current ``poi_search`` evidence is preferred.  In multi-turn partial
        replans and weather adjustments, M2 may recompute itinerary and budget
        without rerunning attraction search, so previous-turn POIs remain valid
        context evidence unless the destination changed.
        """
        current = self._attractions_from_tool_result(tool_results.get("poi_search"))
        if current:
            return current
        previous_state = self._goal_state_previous_state(case)
        task_type = self._case_constraint_task_type(case)
        if isinstance(previous_state, dict):
            ticket = build_goal_state_ticket(
                user_input=str(case.get("user_input") or ""),
                current_slots=self._goal_state_current_slots(case),
                previous_state=previous_state,
            )
            ticket_task_type = self._canonical_research_task_type(ticket.task_type)
            if ticket_task_type in {
                "trip_planning",
                "partial_replan",
                "weather_adjustment",
            }:
                task_type = ticket_task_type
        if task_type not in {
            "partial_replan",
            "weather_adjustment",
        }:
            return []
        if self._case_has_destination_change(case):
            return []
        return self._previous_attractions_from_state(previous_state)

    def _poi_ids_from_attractions(self, attractions: Any) -> List[str]:
        if not isinstance(attractions, list):
            return []
        return [
            str(item.get("poi_id"))
            for item in attractions
            if isinstance(item, dict) and item.get("poi_id")
        ]

    def _case_has_destination_change(self, case: Dict[str, Any]) -> bool:
        changed_slots: set[str] = set()
        for candidate in (
            _nested_mapping(case, "expected", "changed_slots"),
            case.get("changed_slots"),
        ):
            changed_slots.update(str(value) for value in _as_list(candidate))
        previous_state = self._goal_state_previous_state(case)
        if isinstance(previous_state, dict):
            ticket = build_goal_state_ticket(
                user_input=str(case.get("user_input") or ""),
                current_slots=self._goal_state_current_slots(case),
                previous_state=previous_state,
            )
            changed_slots.update(str(value) for value in ticket.changed_slots)
        return "destination" in changed_slots

    def _scheduler_requires_clarification(
        self,
        scheduler_metadata: Optional[Dict[str, Any]],
    ) -> bool:
        if not isinstance(scheduler_metadata, dict):
            return False
        ticket = scheduler_metadata.get("ticket") if isinstance(scheduler_metadata.get("ticket"), dict) else {}
        decision = (
            scheduler_metadata.get("decision")
            if isinstance(scheduler_metadata.get("decision"), dict)
            else {}
        )
        return bool(
            decision.get("clarification_required")
            or ticket.get("clarification_required")
            or ticket.get("task_type") == "clarification"
        )

    def _scheduler_clarification_fields(
        self,
        scheduler_metadata: Optional[Dict[str, Any]],
    ) -> List[str]:
        if not isinstance(scheduler_metadata, dict):
            return []
        ticket = scheduler_metadata.get("ticket") if isinstance(scheduler_metadata.get("ticket"), dict) else {}
        decision = (
            scheduler_metadata.get("decision")
            if isinstance(scheduler_metadata.get("decision"), dict)
            else {}
        )
        return _as_list(decision.get("clarification_fields") or ticket.get("clarification_fields"))

    def _compose_clarification_answer(self, clarification_fields: List[str]) -> str:
        field_labels = {
            "destination": "目的地城市",
            "start_date": "出发日期",
            "duration_days": "旅行天数",
            "people_count": "出行人数",
            "budget_amount": "预算",
            "previous_state": "上一轮方案",
        }
        labels = [field_labels.get(field, field) for field in clarification_fields]
        if not labels:
            return "需要先补充关键信息后，才能继续生成旅游方案。"
        return "需要先补充：" + "、".join(labels) + "。请补充后我再生成旅游方案。"

    def _agent_decision(
        self,
        agent_name: str,
        agent_outputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        output = agent_outputs.get(agent_name)
        if not isinstance(output, dict):
            return {}
        if str(output.get("decision_validation_status") or "") != "passed":
            return {}
        decision = output.get("decision")
        return decision if isinstance(decision, dict) else {}

    def _agent_decision_payload(
        self,
        agent_name: str,
        agent_outputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        decision = self._agent_decision(agent_name, agent_outputs)
        payload = decision.get("decisions") if isinstance(decision.get("decisions"), dict) else {}
        return payload if isinstance(payload, dict) else {}

    def _agent_decision_audit(self, agent_outputs: Dict[str, Any]) -> Dict[str, Any]:
        audit: Dict[str, Any] = {}
        for agent_name, output in agent_outputs.items():
            if not isinstance(output, dict):
                continue
            audit[str(agent_name)] = {
                "status": output.get("status"),
                "reused": bool(output.get("reused")),
                "decision_source": output.get("decision_source"),
                "decision_fallback_used": bool(output.get("decision_fallback_used")),
                "decision_normalizer_enabled": output.get("decision_normalizer_enabled"),
                "decision_normalizer_skipped": bool(output.get("decision_normalizer_skipped")),
                "decision_parse_status": output.get("decision_parse_status"),
                "decision_validation_status": output.get("decision_validation_status"),
                "llm_decision_error_count": len(output.get("llm_decision_errors") or []),
                "decision_error_count": len(output.get("decision_errors") or []),
                "has_applicable_decision": bool(self._agent_decision(str(agent_name), agent_outputs)),
            }
        return audit

    def _attractions_for_research_output(
        self,
        *,
        case: Dict[str, Any],
        tool_results: Dict[str, Any],
        agent_outputs: Dict[str, Any],
        weather: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        tool_attractions = self._attractions_from_tool_result(tool_results.get("poi_search"))
        if not tool_attractions:
            tool_attractions = self._itinerary_evidence_attractions(
                case=case,
                tool_results=tool_results,
            )
        selected_ids = _as_list(
            self._agent_decision_payload("attraction", agent_outputs).get("selected_poi_ids")
        )
        selected = self._select_constraint_aware_attractions(
            tool_attractions,
            case=case,
            weather=weather or self._tool_data(tool_results.get("weather_query")),
            preferred_ids=selected_ids,
        )
        minimum = self._case_min_attractions(case)
        if minimum is not None and len(selected) < minimum:
            selected_ids_set = {
                str(item.get("poi_id") or "")
                for item in selected
                if item.get("poi_id")
            }
            for item in tool_attractions:
                poi_id = str(item.get("poi_id") or "")
                if not poi_id or poi_id in selected_ids_set:
                    continue
                selected.append(
                    {
                        **_jsonable_value(item),
                        "agent_selected": False,
                        "agent_decision_source": "evidence_minimum_completion",
                        "agent_rank": len(selected) + 1,
                    }
                )
                selected_ids_set.add(poi_id)
                if len(selected) >= minimum:
                    break
        return self._bounded_attractions_for_case(selected, case=case)

    def _select_constraint_aware_attractions(
        self,
        attractions: List[Dict[str, Any]],
        *,
        case: Dict[str, Any],
        weather: Optional[Dict[str, Any]] = None,
        preferred_ids: Optional[List[Any]] = None,
    ) -> List[Dict[str, Any]]:
        by_id: Dict[str, Dict[str, Any]] = {}
        ordered: List[Dict[str, Any]] = []
        for item in attractions:
            if not isinstance(item, dict) or not item.get("poi_id"):
                continue
            poi_id = str(item.get("poi_id"))
            if poi_id in by_id:
                continue
            by_id[poi_id] = item
            ordered.append(item)
        if not ordered:
            return []

        preferred_order = [
            str(poi_id)
            for poi_id in (preferred_ids or [])
            if str(poi_id) in by_id
        ]
        preferred_rank = {poi_id: rank for rank, poi_id in enumerate(preferred_order)}
        original_rank = {
            str(item.get("poi_id")): rank
            for rank, item in enumerate(ordered, start=len(preferred_rank))
            if item.get("poi_id")
        }
        weather_payload = weather if isinstance(weather, dict) else {}
        risk_active = bool(
            weather_payload
            and self._weather_adjustment_required_from_evidence(case, weather_payload)
        )
        senior_active = self._case_requires_low_intensity(case)

        def score(item: Dict[str, Any]) -> tuple[int, int, int, int]:
            poi_id = str(item.get("poi_id"))
            senior_penalty = (
                1
                if senior_active and not self._poi_preferred_for_low_intensity(item)
                else 0
            )
            weather_penalty = (
                1
                if risk_active and not self._poi_preferred_for_weather_risk(item)
                else 0
            )
            preferred_penalty = 0 if poi_id in preferred_rank else 1
            rank = preferred_rank.get(poi_id, original_rank.get(poi_id, len(original_rank)))
            return senior_penalty, weather_penalty, preferred_penalty, rank

        ranked = sorted(ordered, key=score)
        minimum = self._case_min_attractions(case) or 0
        maximum = self._case_max_attractions(case)
        requested = self._case_requested_poi_count(case)
        daily_capacity = self._case_duration(case) * self._case_max_pois_per_day(case)
        if requested is not None:
            target = requested
        elif senior_active and minimum == 0 and maximum is None:
            low_intensity_count = sum(
                1
                for item in ranked
                if self._poi_preferred_for_low_intensity(item)
            )
            target = max(3, min(low_intensity_count, daily_capacity))
        elif preferred_order:
            target = max(minimum, len(preferred_order))
        elif minimum:
            target = minimum
        elif maximum is not None:
            target = maximum
        else:
            target = max(minimum, min(len(ranked), daily_capacity))
        if maximum is not None and maximum > 0:
            target = min(target, maximum)
        target = max(minimum, target)
        target = min(target, len(ranked), daily_capacity or len(ranked))
        selected = ranked[:target]
        selected_ids = {str(item.get("poi_id")) for item in selected if item.get("poi_id")}
        if len(selected) < minimum:
            for item in ranked[target:]:
                poi_id = str(item.get("poi_id") or "")
                if not poi_id or poi_id in selected_ids:
                    continue
                selected.append(item)
                selected_ids.add(poi_id)
                if len(selected) >= minimum:
                    break
        preferred_set = set(preferred_order)
        minimum_completion_ids = {
            str(item.get("poi_id"))
            for item in selected[:minimum]
            if item.get("poi_id") and str(item.get("poi_id")) not in preferred_set
        }
        return [
            {
                **_jsonable_value(item),
                "agent_selected": str(item.get("poi_id")) in preferred_set,
                "agent_decision_source": (
                    "attraction"
                    if str(item.get("poi_id")) in preferred_set
                    else (
                        "evidence_minimum_completion"
                        if str(item.get("poi_id")) in minimum_completion_ids
                        else "evidence_constraint_selection"
                    )
                ),
                "agent_rank": rank,
            }
            for rank, item in enumerate(selected, start=1)
        ]

    def _bounded_attractions_for_case(
        self,
        attractions: List[Dict[str, Any]],
        *,
        case: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        maximum = self._case_max_attractions(case)
        if maximum is not None and maximum > 0:
            return attractions[:maximum]
        return attractions

    def _weather_for_research_output(
        self,
        *,
        tool_results: Dict[str, Any],
        agent_outputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        weather = dict(self._tool_data(tool_results.get("weather_query")))
        decisions = self._agent_decision_payload("weather", agent_outputs)
        if weather and decisions:
            weather["agent_weather_decision"] = {
                "risk_days": _int_list(decisions.get("risk_days")),
                "adjustment_required": bool(decisions.get("adjustment_required")),
                "source": "weather",
            }
        return weather

    def _budget_for_research_output(
        self,
        *,
        tool_results: Dict[str, Any],
        agent_outputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        budget = dict(self._tool_data(tool_results.get("budget_calculator")))
        decisions = self._agent_decision_payload("budget", agent_outputs)
        if budget and decisions:
            budget["agent_budget_decision"] = {
                "feasibility": decisions.get("feasibility"),
                "budget_notes": decisions.get("budget_notes"),
                "recommended_total": decisions.get("recommended_total"),
                "source": "budget",
            }
        return budget

    def _budget_itinerary_consistency_audit(
        self,
        *,
        budget: Optional[Dict[str, Any]],
        daily_itinerary: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not isinstance(budget, dict) or not budget:
            return {}
        final_poi_ids = _ordered_unique(self._daily_itinerary_poi_ids(daily_itinerary))
        ticket_breakdown = budget.get("ticket_breakdown") if isinstance(budget.get("ticket_breakdown"), dict) else {}
        ticket_summary = (
            ticket_breakdown.get("summary")
            if isinstance(ticket_breakdown.get("summary"), dict)
            else {}
        )
        breakdown = budget.get("breakdown") if isinstance(budget.get("breakdown"), dict) else {}
        ticket_section = breakdown.get("tickets") if isinstance(breakdown.get("tickets"), dict) else {}
        budget_poi_ids = _ordered_unique(
            [
                str(value)
                for value in (
                    ticket_summary.get("selected_poi_ids")
                    or ticket_section.get("selected_poi_ids")
                    or []
                )
                if str(value or "").strip()
            ]
        )
        source = ticket_summary.get("source") or ticket_section.get("source")
        final_poi_id_set = self._normalized_poi_id_set(final_poi_ids)
        budget_poi_id_set = self._normalized_poi_id_set(budget_poi_ids)
        if not final_poi_ids and source == "standard_reference_poi_combo":
            consistency_status = "standard_reference_no_final_itinerary"
            consistent = True
        else:
            consistent = bool(final_poi_id_set) and final_poi_id_set == budget_poi_id_set
            if consistent and final_poi_ids == budget_poi_ids:
                consistency_status = "matched"
            elif consistent:
                consistency_status = "matched_order_insensitive"
            else:
                consistency_status = "mismatched"
        return {
            "schema_version": "budget-itinerary-consistency-audit-v1",
            "status": consistency_status,
            "consistent": consistent,
            "final_itinerary_unique_poi_ids": final_poi_ids,
            "budget_selected_poi_ids": budget_poi_ids,
            "final_itinerary_poi_id_set": final_poi_id_set,
            "budget_selected_poi_id_set": budget_poi_id_set,
            "ticket_source": source,
        }

    @staticmethod
    def _normalized_poi_id_set(values: Any) -> List[str]:
        return sorted(
            {
                str(value or "").strip().lower()
                for value in _as_list(values)
                if str(value or "").strip()
            }
        )

    def _previous_budget_from_state(
        self,
        previous_state: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not isinstance(previous_state, dict):
            return {}
        for candidate in (
            previous_state.get("budget"),
            _nested_mapping(previous_state, "raw_output", "budget"),
            _nested_mapping(previous_state, "output", "budget"),
            _nested_mapping(previous_state, "output", "raw_output", "budget"),
            self._tool_data(
                self._previous_tool_results_from_state(previous_state).get(
                    "budget_calculator"
                )
            ),
        ):
            if isinstance(candidate, dict) and candidate:
                return dict(candidate)
        return {}

    def _daily_itinerary_for_research_output(
        self,
        *,
        case: Dict[str, Any],
        trip_days: int,
        attractions: List[Dict[str, Any]],
        weather: Dict[str, Any],
        planned_agents: List[str],
        reused_agents: List[str],
        agent_outputs: Dict[str, Any],
        previous_state: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if self._case_constraint_task_type(case) == "weather_adjustment":
            previous_itinerary = self._previous_daily_itinerary_from_state(previous_state)
            if previous_itinerary:
                return previous_itinerary
        if (
            "itinerary" in planned_agents
            and attractions
        ):
            agent_itinerary = self._daily_itinerary_from_agent_decision(
                trip_days=trip_days,
                attractions=attractions,
                agent_outputs=agent_outputs,
            )
            return agent_itinerary or self._normalized_decision_daily_itinerary(
                trip_days,
                attractions,
                case=case,
                weather=weather,
            )
        if "itinerary" in reused_agents:
            previous_itinerary = self._previous_daily_itinerary_from_state(previous_state)
            if previous_itinerary:
                return previous_itinerary
            if self._agent_output_available("itinerary", agent_outputs):
                return self._daily_itinerary_from_agent_decision(
                    trip_days=trip_days,
                    attractions=attractions,
                    agent_outputs=agent_outputs,
                )
        previous_itinerary = self._previous_daily_itinerary_for_current_replan(
            case=case,
            trip_days=trip_days,
            attractions=attractions,
            previous_state=previous_state,
        )
        if previous_itinerary:
            return previous_itinerary
        if (
            "single_agent" in planned_agents
            and attractions
            and self._case_constraint_task_type(case)
            in {"trip_planning", "partial_replan", "weather_adjustment"}
        ):
            return self._normalized_decision_daily_itinerary(
                trip_days,
                attractions,
                case=case,
                weather=weather,
            )
        return []

    def _previous_daily_itinerary_for_current_replan(
        self,
        *,
        case: Dict[str, Any],
        trip_days: int,
        attractions: List[Dict[str, Any]],
        previous_state: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if self._case_constraint_task_type(case) != "partial_replan":
            return []
        if self._case_has_destination_change(case):
            return []
        previous_itinerary = self._previous_daily_itinerary_from_state(previous_state)
        if not previous_itinerary:
            return []
        if trip_days > 0 and len(previous_itinerary) != trip_days:
            return []
        previous_poi_ids = set(self._daily_itinerary_poi_ids(previous_itinerary))
        if not previous_poi_ids:
            return []
        attraction_poi_ids = {
            str(item.get("poi_id"))
            for item in attractions
            if isinstance(item, dict) and item.get("poi_id")
        }
        if attraction_poi_ids and not previous_poi_ids <= attraction_poi_ids:
            return []
        return previous_itinerary

    def _normalize_daily_itinerary_for_evidence_constraints(
        self,
        *,
        trip_days: int,
        attractions: List[Dict[str, Any]],
        weather: Dict[str, Any],
        case: Dict[str, Any],
        daily_itinerary: List[Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        audit = {
            "schema_version": "ctp-research-output-evidence-normalizer-v1",
            "applied": False,
            "reasons": [],
            "before_poi_ids": self._daily_itinerary_poi_ids(daily_itinerary),
            "before_day_poi_ids": self._daily_itinerary_day_poi_ids(daily_itinerary),
            "after_poi_ids": [],
            "after_day_poi_ids": [],
        }
        has_visible_normalization_target = bool(
            (weather and self._weather_adjustment_required_from_evidence(case, weather))
            or self._case_requires_low_intensity(case)
            or self._case_has_evidence_normalization_targets(case)
        )
        if not has_visible_normalization_target:
            audit["after_poi_ids"] = audit["before_poi_ids"]
            audit["after_day_poi_ids"] = audit["before_day_poi_ids"]
            return daily_itinerary, audit
        if trip_days < 1 or not attractions:
            audit["after_poi_ids"] = audit["before_poi_ids"]
            audit["after_day_poi_ids"] = audit["before_day_poi_ids"]
            return daily_itinerary, audit

        max_pois_per_day = self._case_max_pois_per_day(case)
        risk_days = set(
            self._affected_weather_days(case, weather)
            if weather and self._weather_adjustment_required_from_evidence(case, weather)
            else []
        )
        minimum = self._case_min_attractions(case)
        maximum = self._case_max_attractions(case)
        current_ids = self._daily_itinerary_poi_ids(daily_itinerary)
        has_risky_day_conflict = bool(
            risk_days
            and self._daily_itinerary_has_weather_risk_conflict(
                daily_itinerary,
                attractions=attractions,
                risk_days=risk_days,
            )
        )
        overloaded_days = [
            day_index
            for day_index, poi_ids in enumerate(audit["before_day_poi_ids"], start=1)
            if len(poi_ids) > max_pois_per_day
        ]
        duplicate_ids = self._duplicate_daily_itinerary_poi_ids(daily_itinerary)
        below_minimum = minimum is not None and len(set(current_ids)) < minimum
        if (
            not has_risky_day_conflict
            and not overloaded_days
            and not duplicate_ids
            and not below_minimum
        ):
            audit["after_poi_ids"] = audit["before_poi_ids"]
            audit["after_day_poi_ids"] = audit["before_day_poi_ids"]
            return daily_itinerary, audit

        if has_risky_day_conflict:
            audit["reasons"].append("weather_risk_day_poi_reordered")
        if overloaded_days:
            audit["reasons"].append("daily_load_limit_enforced")
            audit["overloaded_days"] = overloaded_days
        if duplicate_ids:
            audit["reasons"].append("duplicate_pois_removed")
            audit["duplicate_poi_ids"] = duplicate_ids
        if below_minimum:
            audit["reasons"].append("minimum_attraction_count_completed")

        rebuilt = self._build_constraint_aware_daily_itinerary(
            trip_days=trip_days,
            attractions=attractions,
            risk_days=risk_days,
            minimum_attractions=minimum,
            maximum_attractions=maximum,
            max_pois_per_day=max_pois_per_day,
        )
        if not rebuilt:
            audit["after_poi_ids"] = audit["before_poi_ids"]
            audit["after_day_poi_ids"] = audit["before_day_poi_ids"]
            return daily_itinerary, audit
        audit["after_poi_ids"] = self._daily_itinerary_poi_ids(rebuilt)
        audit["after_day_poi_ids"] = self._daily_itinerary_day_poi_ids(rebuilt)
        audit["applied"] = audit["after_day_poi_ids"] != audit["before_day_poi_ids"]
        return (rebuilt if audit["applied"] else daily_itinerary), audit

    def _daily_itinerary_has_weather_risk_conflict(
        self,
        daily_itinerary: List[Dict[str, Any]],
        *,
        attractions: List[Dict[str, Any]],
        risk_days: set[int],
    ) -> bool:
        by_id = {
            str(item.get("poi_id")): item
            for item in attractions
            if item.get("poi_id")
        }
        for day in daily_itinerary:
            if not isinstance(day, dict):
                continue
            day_index = _first_positive_int(day.get("day"), day.get("day_index"), default=0)
            if day_index not in risk_days:
                continue
            for poi_id in self._day_itinerary_poi_ids(day):
                if not self._poi_preferred_for_weather_risk(by_id.get(poi_id) or {}):
                    return True
        return False

    def _build_constraint_aware_daily_itinerary(
        self,
        *,
        trip_days: int,
        attractions: List[Dict[str, Any]],
        risk_days: set[int],
        minimum_attractions: Optional[int],
        maximum_attractions: Optional[int],
        max_pois_per_day: int,
    ) -> List[Dict[str, Any]]:
        by_id = {
            str(item.get("poi_id")): item
            for item in attractions
            if item.get("poi_id")
        }
        if not by_id:
            return []
        ordered_ids = list(by_id.keys())
        safe_ids = [
            poi_id
            for poi_id in ordered_ids
            if self._poi_preferred_for_weather_risk(by_id[poi_id])
        ]
        normal_ids = [poi_id for poi_id in ordered_ids if poi_id not in set(safe_ids)]
        target_total = len(ordered_ids)
        if minimum_attractions is not None:
            target_total = max(target_total, minimum_attractions)
        if maximum_attractions is not None and maximum_attractions > 0:
            target_total = min(target_total, maximum_attractions)
        target_total = min(target_total, trip_days * max_pois_per_day, len(ordered_ids))

        used: set[str] = set()
        selected_by_day: Dict[int, List[str]] = {
            day_index: []
            for day_index in range(1, trip_days + 1)
        }
        for day_index in sorted(day for day in risk_days if 1 <= day <= trip_days):
            candidates = [poi_id for poi_id in safe_ids if poi_id not in used]
            selected_ids = candidates[:max_pois_per_day]
            selected_by_day[day_index] = selected_ids
            used.update(selected_ids)

        for day_index in range(1, trip_days + 1):
            if day_index in risk_days:
                continue
            candidates = [poi_id for poi_id in ordered_ids if poi_id not in used]
            selected_ids = candidates[:max_pois_per_day]
            selected_by_day[day_index] = selected_ids
            used.update(selected_ids)

        days: List[Dict[str, Any]] = [
            self._daily_itinerary_day_payload(
                day_index,
                selected_by_day.get(day_index, []),
                by_id,
                normalized=True,
            )
            for day_index in range(1, trip_days + 1)
        ]

        if len(used) < target_total:
            for day in days:
                day_index = _first_positive_int(day.get("day"), day.get("day_index"), default=0)
                if day_index in risk_days:
                    continue
                current = self._day_itinerary_poi_ids(day)
                remaining_capacity = max(0, max_pois_per_day - len(current))
                if remaining_capacity <= 0:
                    continue
                additions = [
                    poi_id
                    for poi_id in ordered_ids
                    if poi_id not in used
                ][:remaining_capacity]
                if not additions:
                    continue
                used.update(additions)
                current.extend(additions)
                day.update(
                    self._daily_itinerary_day_payload(
                        day_index,
                        current,
                        by_id,
                        normalized=True,
                    )
                )
                if len(used) >= target_total:
                    break
        return days

    def _daily_itinerary_day_payload(
        self,
        day_index: int,
        poi_ids: List[str],
        by_id: Dict[str, Dict[str, Any]],
        *,
        normalized: bool,
    ) -> Dict[str, Any]:
        return {
            "day": day_index,
            "attractions": [
                {
                    "poi_id": by_id[poi_id].get("poi_id"),
                    "name": by_id[poi_id].get("name"),
                    "category": by_id[poi_id].get("category"),
                    "indoor_outdoor": by_id[poi_id].get("indoor_outdoor"),
                }
                for poi_id in poi_ids
                if poi_id in by_id
            ],
            "notes": (
                "normalized from offline POI and weather evidence"
                if normalized
                else "generated from offline POI evidence"
            ),
            "agent_decision_source": (
                "evidence_constraint_normalizer" if normalized else "itinerary"
            ),
            **({"evidence_normalized": True} if normalized else {}),
        }

    def _canonical_attractions_for_constraint_plan(
        self,
        *,
        task_type: str,
        attractions: List[Dict[str, Any]],
        daily_itinerary: List[Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        itinerary_poi_ids = self._daily_itinerary_poi_ids(daily_itinerary)
        should_carry_pois_in_itinerary_only = bool(
            itinerary_poi_ids
            and task_type
            not in {
                "attraction_recommendation",
                "budget_query",
            }
        )
        audit = {
            "schema_version": "ctp-research-constraint-plan-normalizer-v1",
            "applied": False,
            "reason": None,
            "top_level_attraction_count_before": len(attractions),
            "top_level_attraction_count_after": len(attractions),
            "itinerary_poi_ids": itinerary_poi_ids,
        }
        if not should_carry_pois_in_itinerary_only:
            return attractions, audit
        audit["applied"] = bool(attractions)
        audit["reason"] = "constraint_checker_uses_itinerary_pois_to_avoid_duplicate_counting"
        audit["top_level_attraction_count_after"] = 0
        return [], audit

    def _daily_itinerary_poi_ids(self, daily_itinerary: List[Dict[str, Any]]) -> List[str]:
        ids: List[str] = []
        for day in daily_itinerary:
            if isinstance(day, dict):
                ids.extend(self._day_itinerary_poi_ids(day))
        return _ordered_unique(ids)

    def _daily_itinerary_day_poi_ids(
        self,
        daily_itinerary: List[Dict[str, Any]],
    ) -> List[List[str]]:
        return [
            self._day_itinerary_poi_ids(day) if isinstance(day, dict) else []
            for day in daily_itinerary
        ]

    def _duplicate_daily_itinerary_poi_ids(
        self,
        daily_itinerary: List[Dict[str, Any]],
    ) -> List[str]:
        seen: set[str] = set()
        duplicates: List[str] = []
        for poi_id in [
            poi_id
            for day_ids in self._daily_itinerary_day_poi_ids(daily_itinerary)
            for poi_id in day_ids
        ]:
            if poi_id in seen and poi_id not in duplicates:
                duplicates.append(poi_id)
            seen.add(poi_id)
        return duplicates

    def _day_itinerary_poi_ids(self, day: Dict[str, Any]) -> List[str]:
        ids: List[str] = []
        for field in (
            "attraction_poi_ids",
            "poi_ids",
            "attraction_ids",
            "selected_poi_ids",
        ):
            for value in _as_list(day.get(field)):
                if str(value or "").strip():
                    ids.append(str(value))
        for item in day.get("attractions") or day.get("pois") or day.get("activities") or []:
            if isinstance(item, str):
                ids.append(item)
            elif isinstance(item, dict):
                poi = item.get("poi") if isinstance(item.get("poi"), dict) else {}
                poi_id = item.get("poi_id") or item.get("id") or poi.get("poi_id") or poi.get("id")
                if poi_id:
                    ids.append(str(poi_id))
        return _ordered_unique(ids)

    def _daily_itinerary_from_agent_decision(
        self,
        *,
        trip_days: int,
        attractions: List[Dict[str, Any]],
        agent_outputs: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        daily = self._agent_decision_payload("itinerary", agent_outputs).get("daily_itinerary")
        if not isinstance(daily, list):
            return []
        by_id = {
            str(item.get("poi_id")): item
            for item in attractions
            if item.get("poi_id")
        }
        result: List[Dict[str, Any]] = []
        valid_poi_ref_count = 0
        for item in daily:
            if not isinstance(item, dict):
                continue
            day = _first_positive_int(item.get("day"), item.get("day_index"), default=0)
            if day < 1 or day > trip_days:
                continue
            poi_ids = _as_list(item.get("attraction_poi_ids"))
            selected = [by_id[poi_id] for poi_id in poi_ids if poi_id in by_id]
            valid_poi_ref_count += len(selected)
            result.append(
                {
                    "day": day,
                    "attractions": [
                        {
                            "poi_id": attraction.get("poi_id"),
                            "name": attraction.get("name"),
                            "category": attraction.get("category"),
                            "indoor_outdoor": attraction.get("indoor_outdoor"),
                        }
                        for attraction in selected
                    ],
                    "notes": str(
                        item.get("notes")
                        or "generated from validated itinerary agent decision"
                    ),
                    "agent_decision_source": "itinerary",
                }
            )
        if by_id and valid_poi_ref_count == 0:
            return []
        result.sort(key=lambda item: int(item.get("day") or 0))
        return result

    def _weather_adjustments_for_research_output(
        self,
        *,
        weather: Dict[str, Any],
        attractions: List[Dict[str, Any]],
        case: Dict[str, Any],
        agent_outputs: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        adjustments = self._build_weather_adjustments(
            weather,
            attractions,
            case=case,
        )
        risk_days = _int_list(
            self._agent_decision_payload("weather", agent_outputs).get("risk_days")
        )
        if not risk_days:
            return adjustments
        by_day = {
            int(item.get("day") or item.get("day_index") or 0): item
            for item in adjustments
        }
        for day in risk_days:
            item = by_day.get(day)
            if item is None:
                item = {
                    "day": day,
                    "day_index": day,
                    "reason": str(weather.get("scenario_type") or "agent_weather_risk"),
                    "action": "adjust itinerary according to weather agent risk decision",
                    "candidate_indoor_pois": [],
                }
                adjustments.append(item)
            item["agent_decision_source"] = "weather"
        adjustments.sort(key=lambda item: int(item.get("day") or item.get("day_index") or 0))
        return adjustments

    def _produced_result_agents_from_artifacts(
        self,
        *,
        planned_agents: List[str],
        tool_results: Dict[str, Any],
        daily_itinerary: List[Dict[str, Any]],
        agent_outputs: Dict[str, Any],
    ) -> List[str]:
        produced: List[str] = []
        if (
            "attraction" in planned_agents
            and self._agent_output_available("attraction", agent_outputs)
            and self._agent_result_available_for_execution(
                "attraction",
                tool_results,
            )
        ):
            produced.append("attraction")
        if (
            "weather" in planned_agents
            and self._agent_output_available("weather", agent_outputs)
            and self._agent_result_available_for_execution(
                "weather",
                tool_results,
            )
        ):
            produced.append("weather")
        if (
            "itinerary" in planned_agents
            and self._agent_output_available("itinerary", agent_outputs)
            and daily_itinerary
        ):
            produced.append("itinerary")
        if (
            "budget" in planned_agents
            and self._agent_output_available("budget", agent_outputs)
            and self._agent_result_available_for_execution(
                "budget",
                tool_results,
            )
        ):
            produced.append("budget")
        return produced

    def _tools_for_agents(self, agent_names: List[str]) -> List[str]:
        tool_set: set[str] = set()
        for agent_name in agent_names:
            tool_set.update(self._tools_for_research_agent(agent_name))
        return [tool for tool in GENERATION_TOOL_NAMES if tool in tool_set]

    def _research_tool_arguments(
        self,
        tool_name: str,
        case: Dict[str, Any],
        tool_results: Dict[str, Any],
        *,
        agent_outputs: Optional[Dict[str, Any]] = None,
        scheduler_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        city = self._case_city(case)
        duration = self._case_duration(case)
        if tool_name == "poi_search":
            return {
                "city": city,
                "preferences": self._case_preferences(case),
                "people": self._case_people(case),
                "limit": self._case_poi_limit(case),
            }
        if tool_name == "weather_query":
            return {
                "city": city,
                "date": self._case_start_date(case),
                "days": duration,
                "scenario_type": self._case_weather_scenario(case),
            }
        if tool_name == "budget_calculator":
            people_count = self._case_traveler_count(case)
            origin = self._case_origin(case)
            daily_itinerary = self._daily_itinerary_for_budget_tool(
                case=case,
                tool_results=tool_results,
                agent_outputs=agent_outputs or {},
                scheduler_metadata=scheduler_metadata,
            )
            selected_poi_ids = self._poi_ids_for_budget_tool(
                case=case,
                tool_results=tool_results,
                agent_outputs=agent_outputs or {},
                daily_itinerary=daily_itinerary,
            )
            return {
                "city": city,
                "origin": origin,
                "people_count": people_count,
                "days": duration,
                "attractions": selected_poi_ids,
                "daily_itinerary": daily_itinerary,
                "budget_limit": self._case_budget_limit(case),
                "budget_basis": self._case_budget_basis(case),
                "requested_budget_scope": self._case_requested_budget_scope(case),
                "intercity_transport_included": self._case_intercity_transport_included(case),
                "mandatory_budget_disclaimer": self._case_mandatory_budget_disclaimer(case),
                "spending_level": self._budget_level_for_research_tool(
                    case=case,
                    city=city,
                    origin=origin,
                    people_count=people_count,
                    duration_days=duration,
                    selected_poi_ids=selected_poi_ids,
                ),
                "hotel_level": self._case_hotel_level(case),
                "food_level": self._case_food_level(case),
                "transport_mode": self._case_transport_mode(case),
            }
        return {}

    def _budget_level_for_research_tool(
        self,
        *,
        case: Dict[str, Any],
        city: str,
        people_count: int,
        duration_days: int,
        selected_poi_ids: List[str],
        origin: Optional[str] = None,
    ) -> str:
        explicit_level = self._case_explicit_budget_level(case)
        if explicit_level:
            return explicit_level
        return self._case_budget_level(case)

    def _poi_ids_for_budget_tool(
        self,
        *,
        case: Dict[str, Any],
        tool_results: Dict[str, Any],
        agent_outputs: Dict[str, Any],
        daily_itinerary: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        """Return the bounded POI subset used by the budget tool.

        The budget calculator should price the candidate plan, not every POI
        returned by the broad search tool.  This keeps budget evidence aligned
        with the final itinerary and avoids penalising methods for attractions
        that were never selected.
        """
        if daily_itinerary:
            ids = self._daily_itinerary_poi_ids(daily_itinerary)
            if ids:
                return ids
        attractions = self._attractions_from_tool_result(tool_results.get("poi_search"))
        if not attractions:
            return []
        preferred_ids = _as_list(
            self._agent_decision_payload("attraction", agent_outputs).get(
                "selected_poi_ids"
            )
        )
        selected = self._select_constraint_aware_attractions(
            attractions,
            case=case,
            weather=self._tool_data(tool_results.get("weather_query")),
            preferred_ids=preferred_ids,
        )
        return [
            str(item.get("poi_id"))
            for item in selected
            if item.get("poi_id")
        ]

    def _daily_itinerary_for_budget_tool(
        self,
        *,
        case: Dict[str, Any],
        tool_results: Dict[str, Any],
        agent_outputs: Dict[str, Any],
        scheduler_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        trip_days = self._case_duration(case)
        weather = self._tool_data(tool_results.get("weather_query"))
        attractions = self._attractions_for_research_output(
            case=case,
            tool_results=tool_results,
            agent_outputs=agent_outputs,
            weather=weather,
        )
        if not attractions:
            return []
        daily_itinerary = self._daily_itinerary_from_agent_decision(
            trip_days=trip_days,
            attractions=attractions,
            agent_outputs=agent_outputs,
        )
        if not daily_itinerary and self._scheduler_reuses_agent(
            scheduler_metadata,
            "itinerary",
        ):
            previous_itinerary = self._previous_daily_itinerary_from_state(
                self._goal_state_previous_state(case)
            )
            if previous_itinerary:
                daily_itinerary = previous_itinerary
        if not daily_itinerary:
            daily_itinerary = self._normalized_decision_daily_itinerary(
                trip_days,
                attractions,
                case=case,
                weather=weather,
            )
        if not daily_itinerary:
            return []
        normalized, _audit = self._normalize_daily_itinerary_for_evidence_constraints(
            trip_days=trip_days,
            attractions=attractions,
            weather=weather,
            case=case,
            daily_itinerary=daily_itinerary,
        )
        return normalized

    def _scheduler_reuses_agent(
        self,
        scheduler_metadata: Optional[Dict[str, Any]],
        agent_name: str,
    ) -> bool:
        if not isinstance(scheduler_metadata, dict):
            return False
        return agent_name in set(self._actual_reused_agents_from_scheduler(scheduler_metadata))

    async def _build_research_method_output(
        self,
        *,
        case: Dict[str, Any],
        method: ExperimentMethod,
        planned_agents: List[str],
        planned_tools: List[str],
        tool_results: Dict[str, Any],
        agent_outputs: Optional[Dict[str, Any]] = None,
        executed_agents: Optional[List[str]] = None,
        scheduler_metadata: Optional[Dict[str, Any]] = None,
        called_tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        called_tools = called_tools or []
        agent_outputs = agent_outputs or {}
        actual_used_agents = _ordered_unique(
            executed_agents if executed_agents is not None else planned_agents
        )
        visible_clarification = (
            scheduler_metadata is None
            and self._infer_research_task_type(case) == "clarification"
        )
        if self._scheduler_requires_clarification(scheduler_metadata) or visible_clarification:
            clarification_fields = (
                self._scheduler_clarification_fields(scheduler_metadata)
                if not visible_clarification
                else self._visible_clarification_fields(case)
            )
            mark_trace_status("clarification")
            result_fingerprints = build_goal_state_result_fingerprints(
                slots=self._case_slots(case),
                tool_results=tool_results,
                daily_itinerary=[],
                result_agents=[],
            )
            enriched_scheduler_metadata = self._scheduler_metadata_with_result_fingerprints(
                scheduler_metadata,
                result_fingerprints,
            )
            final_answer = self._compose_clarification_answer(clarification_fields)
            metadata = self._research_method_metadata(
                method=method,
                scheduler_metadata=enriched_scheduler_metadata,
                case=case,
                result_agents=[],
            )
            metadata["clarification_fields"] = clarification_fields
            raw_snapshot = {
                "task_type": "clarification",
                "planned_agents": planned_agents,
                "used_agents": [],
                "planned_tools": planned_tools,
                "called_tools": called_tools,
                "agent_outputs": {},
                "attractions": [],
                "trip_days": None,
                "daily_itinerary": [],
                "budget": None,
                "weather": None,
                "weather_adjustments": [],
                "execution_status": "clarification",
                "final_answer": final_answer,
                "tool_results": tool_results,
                "metadata": metadata,
            }
            return {
                "schema_version": EXPERIMENT_OUTPUT_SCHEMA_VERSION,
                "case_id": str(case.get("case_id") or ""),
                "method": method,
                "task_type": "clarification",
                "planned_agents": planned_agents,
                "used_agents": [],
                "planned_tools": planned_tools,
                "called_tools": called_tools,
                "agent_outputs": {},
                "attractions": [],
                "trip_days": None,
                "daily_itinerary": [],
                "budget": None,
                "weather": None,
                "weather_adjustments": [],
                "execution_status": "clarification",
                "final_answer": final_answer,
                "raw_output": raw_snapshot,
                "tool_results": tool_results,
                "metadata": metadata,
            }

        previous_state = self._goal_state_previous_state(case)
        actual_reused_agents = self._actual_reused_agents_from_scheduler(
            scheduler_metadata,
        )
        task_type = self._research_output_task_type(case, scheduler_metadata)
        weather = self._weather_for_research_output(
            tool_results=tool_results,
            agent_outputs=agent_outputs,
        )
        attractions = self._attractions_for_research_output(
            case=case,
            tool_results=tool_results,
            agent_outputs=agent_outputs,
            weather=weather,
        )
        budget = self._budget_for_research_output(
            tool_results=tool_results,
            agent_outputs=agent_outputs,
        )
        if not budget and task_type == "weather_adjustment":
            budget = self._previous_budget_from_state(previous_state)
        trip_days = self._case_duration(case)
        daily_itinerary = self._daily_itinerary_for_research_output(
            case=case,
            trip_days=trip_days,
            attractions=attractions,
            weather=weather,
            planned_agents=planned_agents,
            reused_agents=actual_reused_agents,
            agent_outputs=agent_outputs,
            previous_state=previous_state,
        )
        daily_itinerary, itinerary_evidence_normalization = (
            self._normalize_daily_itinerary_for_evidence_constraints(
                trip_days=trip_days,
                attractions=attractions,
                weather=weather,
                case=case,
                daily_itinerary=daily_itinerary,
            )
        )
        result_agents = _ordered_unique(
            [
                *self._produced_result_agents_from_artifacts(
                    planned_agents=planned_agents,
                    tool_results=tool_results,
                    daily_itinerary=daily_itinerary,
                    agent_outputs=agent_outputs,
                ),
                *actual_reused_agents,
            ]
        )
        weather_adjustments = self._weather_adjustments_for_research_output(
            weather=weather,
            attractions=attractions,
            case=case,
            agent_outputs=agent_outputs,
        )
        final_answer = await self._compose_research_answer(
            case=case,
            method=method,
            planned_agents=planned_agents,
            planned_tools=planned_tools,
            tool_results=tool_results,
            agent_outputs=agent_outputs,
            daily_itinerary=daily_itinerary,
            budget=budget,
            weather_adjustments=weather_adjustments,
        )
        final_answer = self._answer_with_research_evidence_summary(
            final_answer,
            attractions=attractions,
            budget=budget,
            weather=weather,
            tool_results=tool_results,
        )
        result_fingerprints = build_goal_state_result_fingerprints(
            slots=self._case_slots(case),
            tool_results=tool_results,
            daily_itinerary=daily_itinerary,
            result_agents=result_agents,
        )
        enriched_scheduler_metadata = self._scheduler_metadata_with_result_fingerprints(
            scheduler_metadata,
            result_fingerprints,
        )
        metadata = self._research_method_metadata(
            method=method,
            scheduler_metadata=enriched_scheduler_metadata,
            case=case,
            result_agents=result_agents,
            agent_outputs=agent_outputs,
        )
        if itinerary_evidence_normalization.get("applied"):
            metadata["itinerary_evidence_normalization"] = itinerary_evidence_normalization
        budget_itinerary_consistency = self._budget_itinerary_consistency_audit(
            budget=budget,
            daily_itinerary=daily_itinerary,
        )
        if budget_itinerary_consistency:
            metadata["budget_itinerary_consistency"] = budget_itinerary_consistency
        execution_status = self._execution_status_from_research_artifacts(
            tool_results=tool_results,
            agent_outputs=agent_outputs,
        )
        raw_snapshot = {
            "task_type": task_type,
            "planned_agents": planned_agents,
            "used_agents": actual_used_agents,
            "planned_tools": planned_tools,
            "called_tools": called_tools,
            "agent_outputs": agent_outputs,
            "attractions": attractions,
            "trip_days": trip_days,
            "daily_itinerary": daily_itinerary,
            "budget": budget or None,
            "weather": weather or None,
            "weather_adjustments": weather_adjustments,
            "execution_status": execution_status,
            "final_answer": final_answer,
            "tool_results": tool_results,
            "metadata": metadata,
        }
        return {
            "schema_version": EXPERIMENT_OUTPUT_SCHEMA_VERSION,
            "case_id": str(case.get("case_id") or ""),
            "method": method,
            "task_type": task_type,
            "planned_agents": planned_agents,
            "used_agents": actual_used_agents,
            "planned_tools": planned_tools,
            "called_tools": called_tools,
            "agent_outputs": agent_outputs,
            "attractions": attractions,
            "trip_days": trip_days,
            "daily_itinerary": daily_itinerary,
            "budget": budget or None,
            "weather": weather or None,
            "weather_adjustments": weather_adjustments,
            "execution_status": execution_status,
            "final_answer": final_answer,
            "raw_output": raw_snapshot,
            "tool_results": tool_results,
            "metadata": metadata,
        }

    async def _compose_research_answer(
        self,
        *,
        case: Dict[str, Any],
        method: ExperimentMethod,
        planned_agents: List[str],
        planned_tools: List[str],
        tool_results: Dict[str, Any],
        agent_outputs: Dict[str, Any],
        daily_itinerary: List[Dict[str, Any]],
        budget: Dict[str, Any],
        weather_adjustments: List[Dict[str, Any]],
    ) -> str:
        if _environment_bool("EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER", False):
            if self._infer_research_task_type(case) == "general_chat":
                return self._compose_general_chat_answer(case)
            return ""
        llm = self.llm_factory()
        context = {
            "case_id": case["case_id"],
            "planned_agents": planned_agents,
            "planned_tools": planned_tools,
            "agent_outputs": self._compact_agent_outputs_for_answer(agent_outputs),
            "tool_results": tool_results,
            "daily_itinerary": daily_itinerary,
            "budget": budget,
            "weather_adjustments": weather_adjustments,
        }
        try:
            response = await self._llm_chat_with_experiment_timeout(
                llm,
                [
                    LLMMessage(
                        role="system",
                        content=(
                            "你是旅游实验系统的结果整理器。只能基于给定的固定离线工具结果回答，"
                            "不要新增没有证据的景点、天气或费用。输出应简洁、结构化。"
                        ),
                    ),
                    LLMMessage(
                        role="user",
                        content=(
                            f"用户请求：{case['user_input']}\n\n"
                            f"实验上下文：{json.dumps(context, ensure_ascii=False, default=str)}"
                        ),
                    ),
                ],
            )
            return response.content
        except TimeoutError as exc:
            return f"最终答案整理模型调用超时，已保留结构化工具证据。{exc}"

        except Exception as exc:
            transport_reason = _agent_llm_transport_error_reason(exc)
            if transport_reason is None:
                raise
            return (
                "鏈€缁堢瓟妗堟暣鐞嗘ā鍨嬭皟鐢ㄥ彂鐢熶紶杈撳紓甯革紝"
                f"宸蹭繚鐣欑粨鏋勫寲宸ュ叿璇佹嵁銆倄{transport_reason}: {exc}"
            )

    def _compose_general_chat_answer(self, case: Dict[str, Any]) -> str:
        text = str(case.get("user_input") or "").strip()
        lowered = text.casefold()
        if any(term in lowered for term in ("晚安", "good night", "goodnight")):
            return "晚安，祝你休息愉快。之后如果需要旅游规划、景点、天气或预算建议，我也可以继续帮你。"
        if any(term in lowered for term in ("能力", "能做", "角色", "介绍", "capability", "role")):
            return "我可以帮助整理旅游目的地、景点推荐、天气信息、行程安排和预算估算，并在信息不足时先向你确认关键条件。"
        return "我可以继续帮你处理旅游相关问题；如果你告诉我目的地、日期、天数、人数和偏好，我会给出更具体的建议。"

    def _answer_with_research_evidence_summary(
        self,
        answer: Any,
        *,
        attractions: List[Dict[str, Any]],
        budget: Dict[str, Any],
        weather: Dict[str, Any],
        tool_results: Optional[Dict[str, Any]] = None,
    ) -> str:
        lines: List[str] = []
        if attractions:
            poi_labels = []
            for item in attractions:
                poi_id = str(item.get("poi_id") or "").strip()
                name = str(item.get("name") or "").strip()
                if poi_id and name:
                    poi_labels.append(f"{name}({poi_id})")
                elif poi_id or name:
                    poi_labels.append(poi_id or name)
            if poi_labels:
                lines.append("证据景点：" + "、".join(poi_labels))
        budget_total = self._budget_total_from_evidence(budget)
        if budget_total is not None:
            lines.append(f"预算工具总额：{budget_total:g} 元")
        intercity_line = self._intercity_budget_answer_line(budget)
        if intercity_line:
            lines.append(intercity_line)
        lines.extend(self._weather_answer_evidence_lines(weather))
        body = str(answer or "").strip()
        if lines and self._answer_body_mentions_unselected_poi(
            body,
            selected_attractions=attractions,
            tool_results=tool_results or {},
        ):
            body = ""
        return body if not lines else "\n".join(lines + (["", body] if body else []))

    def _weather_answer_evidence_lines(self, weather: Dict[str, Any]) -> List[str]:
        if not isinstance(weather, dict) or not weather:
            return []
        coverage_status = str(weather.get("coverage_status") or "").strip()
        provider = str(weather.get("provider") or "").strip()
        weather_terms = _ordered_unique(
            [
                str(weather.get("scenario_type") or ""),
                *[
                    str(day.get("state") or day.get("weather") or "")
                    for day in self._weather_day_items(weather)
                    if isinstance(day, dict)
                ],
            ]
        )
        evidence_labels = [
            label
            for label in (
                "QWeather冻结快照" if provider == "qweather_snapshot" else provider,
                f"覆盖状态 {coverage_status}" if coverage_status else "",
                f"天气类型 {'、'.join(weather_terms)}" if weather_terms else "",
            )
            if label
        ]
        lines = ["天气证据：" + "，".join(evidence_labels)] if evidence_labels else []
        missing_dates = [
            str(value)
            for value in weather.get("missing_dates") or []
            if str(value or "").strip()
        ]
        if not missing_dates and coverage_status in {"partial", "out_of_range"}:
            requested_dates = self._weather_requested_dates(weather)
            covered_dates = {
                str(day.get("date") or "")
                for day in self._weather_day_items(weather)
                if isinstance(day, dict) and day.get("date")
            }
            missing_dates = [value for value in requested_dates if value not in covered_dates]
        if coverage_status in {"partial", "out_of_range"} or missing_dates:
            request_start = str(weather.get("start_date") or weather.get("date") or "").strip()
            request_end = str(weather.get("end_date") or "").strip()
            snapshot_start = str(
                weather.get("snapshot_forecast_start_date")
                or weather.get("forecast_start_date")
                or ""
            ).strip()
            snapshot_end = str(
                weather.get("snapshot_forecast_end_date")
                or weather.get("forecast_end_date")
                or ""
            ).strip()
            parts = []
            if request_start and request_end:
                parts.append(f"请求日期 {request_start} 至 {request_end}")
            if snapshot_start and snapshot_end:
                parts.append(f"快照覆盖 {snapshot_start} 至 {snapshot_end}")
            if missing_dates:
                parts.append("缺失日期：" + "、".join(missing_dates))
            if parts:
                lines.append("天气覆盖说明：" + "；".join(parts) + "。")
            lines.append("超出或缺失的日期不能提供逐日天气；系统不编造范围外天气。")
        return lines

    def _weather_requested_dates(self, weather: Dict[str, Any]) -> List[str]:
        start_text = str(weather.get("start_date") or weather.get("date") or "").strip()
        days = self._safe_positive_int(weather.get("requested_days")) or self._safe_positive_int(weather.get("days")) or 0
        if not start_text or days < 1:
            return []
        try:
            start = datetime.fromisoformat(start_text).date()
        except ValueError:
            return []
        return [
            (start + timedelta(days=offset)).isoformat()
            for offset in range(days)
        ]

    @staticmethod
    def _safe_positive_int(value: Any) -> Optional[int]:
        if isinstance(value, bool):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _intercity_budget_answer_line(self, budget: Dict[str, Any]) -> str:
        if not isinstance(budget, dict) or not budget:
            return ""
        intercity = budget.get("intercity_transport")
        if not isinstance(intercity, dict):
            intercity = {}
        included = bool(
            budget.get("intercity_transport_included")
            or intercity.get("intercity_transport_included")
        )
        cost = _float_or_none(
            budget.get("intercity_transport_cost")
            or intercity.get("total_intercity_transport_cost_cny")
        )
        origin = str(intercity.get("origin_label") or intercity.get("origin") or "").strip()
        destination = str(
            intercity.get("destination_label") or intercity.get("destination") or ""
        ).strip()
        if included and cost and cost > 0:
            route = f"{origin}至{destination}" if origin and destination else "城际"
            return (
                f"城际交通说明：预算已包含{route}成人二等座往返费用，"
                f"城际交通约 {cost:g} 元。"
            )
        if bool(budget.get("mandatory_budget_disclaimer")) or bool(
            intercity.get("mandatory_budget_disclaimer")
        ):
            disclaimer = str(
                budget.get("budget_disclaimer")
                or intercity.get("disclaimer")
                or ""
            ).strip()
            if disclaimer:
                return f"城际交通说明：{disclaimer}"
        return ""

    def _answer_body_mentions_unselected_poi(
        self,
        body: str,
        *,
        selected_attractions: List[Dict[str, Any]],
        tool_results: Dict[str, Any],
    ) -> bool:
        if not body:
            return False
        selected_labels = {
            label
            for item in selected_attractions
            for label in self._poi_answer_labels(item)
        }
        for item in self._attractions_from_tool_result(tool_results.get("poi_search")):
            labels = self._poi_answer_labels(item)
            if not labels or any(label in selected_labels for label in labels):
                continue
            if any(self._text_contains_label(body, label) for label in labels):
                return True
        return False

    def _poi_answer_labels(self, attraction: Dict[str, Any]) -> List[str]:
        return [
            str(value).strip()
            for value in (
                attraction.get("poi_id"),
                attraction.get("id"),
                attraction.get("name"),
            )
            if str(value or "").strip()
        ]

    def _text_contains_label(self, text: str, label: str) -> bool:
        haystack = str(text or "").casefold()
        needle = str(label or "").strip().casefold()
        return bool(needle and needle in haystack)

    def _select_adaptive_research_plan(self, case: Dict[str, Any]) -> Dict[str, Any]:
        previous_state = self._goal_state_previous_state(case)
        ticket = build_goal_state_ticket(
            user_input=str(case.get("user_input") or ""),
            current_slots=self._goal_state_current_slots(case),
            previous_state=previous_state,
        )
        decision = schedule_goal_state_ticket(ticket, previous_state=previous_state)
        return {
            "agents": decision.planned_agents,
            "tools": decision.planned_tools,
            "scheduler": {
                "name": "goal_state_scheduler",
                "ticket": ticket.to_dict(),
                "decision": decision.to_dict(),
            },
        }

    def _goal_state_current_slots(self, case: Dict[str, Any]) -> Dict[str, Any]:
        slots: Dict[str, Any] = {}
        previous_state = self._goal_state_previous_state(case)
        if previous_state is not None:
            current_turn_slots = self._case_current_turn_slots(case)
            if current_turn_slots:
                slots.update(current_turn_slots)
            elif isinstance(case.get("current_slots"), dict):
                slots.update(case["current_slots"])
            elif isinstance(case.get("slots"), dict):
                slots.update(case["slots"])
            else:
                slots.update(self._case_slots(case))
        else:
            parsed_slots = self._case_slots(case)
            if parsed_slots:
                slots.update(parsed_slots)
        if isinstance(case.get("structured_request"), dict):
            slots.update(_slots_from_mapping(case["structured_request"]))
        if previous_state is None and isinstance(case.get("slots"), dict):
            slots.update(case["slots"])
        slots.update(_slots_from_mapping(case))
        if case.get("preferences") is not None:
            slots.setdefault("preferences", case.get("preferences"))
        if case.get("constraints"):
            slots.setdefault("special_requirements", case.get("constraints"))
        return slots

    def _case_current_turn_slots(self, case: Dict[str, Any]) -> Dict[str, Any]:
        for candidate in (
            case.get("current_turn_slots"),
            _nested_mapping(case, "method_input", "current_turn_slots"),
            case.get("current_slots"),
        ):
            if isinstance(candidate, dict):
                return dict(candidate)
        return {}

    def _case_slots(self, case: Dict[str, Any]) -> Dict[str, Any]:
        for candidate in (
            case.get("slots"),
            case.get("parsed_slots"),
            _nested_mapping(case, "method_input", "parsed_slots"),
        ):
            if isinstance(candidate, dict):
                return dict(candidate)
        return {}

    def _goal_state_previous_state(self, case: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        previous_state = case.get("previous_state")
        if not isinstance(previous_state, dict):
            return None

        normalized = dict(previous_state)
        slots = normalized.get("slots")
        if not isinstance(slots, dict):
            ticket = self._previous_scheduler_ticket_from_state(previous_state)
            ticket_slots = ticket.get("current_slots") if isinstance(ticket, dict) else None
            if isinstance(ticket_slots, dict):
                normalized["slots"] = ticket_slots
            else:
                recovered_slots = self._previous_goal_state_slots_from_state(previous_state)
                if recovered_slots:
                    normalized["slots"] = recovered_slots

        tool_results = self._previous_tool_results_from_state(previous_state)
        if tool_results:
            normalized["tool_results"] = tool_results

        result_fingerprints = normalized.get("result_fingerprints")
        if not isinstance(result_fingerprints, dict):
            explicit_result_fingerprints = self._previous_result_fingerprints_from_state(
                previous_state
            )
            if explicit_result_fingerprints:
                normalized["result_fingerprints"] = explicit_result_fingerprints

        available_results = normalized.get("available_results")
        if not isinstance(available_results, dict):
            normalized["available_results"] = self._infer_available_results_from_previous_state(
                previous_state=previous_state,
                tool_results=tool_results,
            )
        return normalized

    def _previous_result_fingerprints_from_state(
        self,
        previous_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        candidates = [
            previous_state.get("result_fingerprints"),
            _nested_mapping(previous_state, "metadata", "adaptive_scheduler", "result_fingerprints"),
            _nested_mapping(previous_state, "raw_output", "metadata", "adaptive_scheduler", "result_fingerprints"),
            _nested_mapping(previous_state, "output", "metadata", "adaptive_scheduler", "result_fingerprints"),
            _nested_mapping(
                previous_state,
                "output",
                "raw_output",
                "metadata",
                "adaptive_scheduler",
                "result_fingerprints",
            ),
        ]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate:
                return dict(candidate)
        return {}

    def _previous_goal_state_slots_from_state(self, previous_state: Dict[str, Any]) -> Dict[str, Any]:
        candidates = [
            _nested_mapping(previous_state, "metadata", "goal_state_slots"),
            _nested_mapping(previous_state, "raw_output", "metadata", "goal_state_slots"),
            _nested_mapping(previous_state, "output", "metadata", "goal_state_slots"),
            _nested_mapping(previous_state, "output", "raw_output", "metadata", "goal_state_slots"),
            _nested_mapping(previous_state, "raw_output", "slots"),
            _nested_mapping(previous_state, "output", "raw_output", "slots"),
        ]
        for candidate in candidates:
            if isinstance(candidate, dict):
                normalized = _slots_from_mapping(candidate)
                normalized.update(candidate)
                return normalized
        return {}

    def _previous_result_agents_from_state(self, previous_state: Dict[str, Any]) -> List[str]:
        candidates = [
            _nested_mapping(previous_state, "metadata", "result_agents"),
            _nested_mapping(previous_state, "raw_output", "metadata", "result_agents"),
            _nested_mapping(previous_state, "output", "metadata", "result_agents"),
            _nested_mapping(previous_state, "output", "raw_output", "metadata", "result_agents"),
            previous_state.get("used_agents"),
            _nested_mapping(previous_state, "raw_output", "used_agents"),
            _nested_mapping(previous_state, "output", "used_agents"),
            _nested_mapping(previous_state, "output", "raw_output", "used_agents"),
            _nested_mapping(previous_state, "trace", "executed_agents"),
            _nested_mapping(previous_state, "trace", "planned_agents"),
        ]
        for candidate in candidates:
            values = _as_list(candidate)
            if values:
                return values
        inferred: List[str] = []
        tool_results = self._previous_tool_results_from_state(previous_state)
        if self._is_successful_reusable_tool_result(tool_results.get("poi_search")):
            inferred.append("attraction")
        if self._is_successful_reusable_tool_result(tool_results.get("weather_query")):
            inferred.append("weather")
        if self._previous_daily_itinerary_from_state(previous_state):
            inferred.append("itinerary")
        if self._is_successful_reusable_tool_result(tool_results.get("budget_calculator")):
            inferred.append("budget")
        return _ordered_unique(inferred)

    def _previous_scheduler_ticket_from_state(self, previous_state: Dict[str, Any]) -> Dict[str, Any]:
        candidates = [
            _nested_mapping(previous_state, "metadata", "adaptive_scheduler", "ticket"),
            _nested_mapping(previous_state, "raw_output", "metadata", "adaptive_scheduler", "ticket"),
            _nested_mapping(previous_state, "output", "metadata", "adaptive_scheduler", "ticket"),
            _nested_mapping(previous_state, "output", "raw_output", "metadata", "adaptive_scheduler", "ticket"),
        ]
        for candidate in candidates:
            if isinstance(candidate, dict):
                return candidate
        return {}

    def _infer_available_results_from_previous_state(
        self,
        *,
        previous_state: Dict[str, Any],
        tool_results: Dict[str, Any],
    ) -> Dict[str, bool]:
        previous_result_agents = set(self._previous_result_agents_from_state(previous_state))
        available = {
            "attraction": (
                "attraction" in previous_result_agents
                and self._is_successful_reusable_tool_result(tool_results.get("poi_search"))
            ),
            "weather": (
                "weather" in previous_result_agents
                and self._is_successful_reusable_tool_result(tool_results.get("weather_query"))
            ),
            "budget": (
                "budget" in previous_result_agents
                and self._is_successful_reusable_tool_result(tool_results.get("budget_calculator"))
            ),
            "itinerary": (
                "itinerary" in previous_result_agents
                and bool(self._previous_daily_itinerary_from_state(previous_state))
            ),
        }
        return {agent: has_result for agent, has_result in available.items() if has_result}

    def _research_output_task_type(
        self,
        case: Dict[str, Any],
        scheduler_metadata: Optional[Dict[str, Any]],
    ) -> str:
        ticket = scheduler_metadata.get("ticket") if isinstance(scheduler_metadata, dict) else None
        if isinstance(ticket, dict) and ticket.get("task_type"):
            return self._canonical_research_task_type(ticket["task_type"])
        return self._infer_research_task_type(case)

    def _research_method_metadata(
        self,
        *,
        method: ExperimentMethod,
        scheduler_metadata: Optional[Dict[str, Any]],
        case: Optional[Dict[str, Any]] = None,
        result_agents: Optional[List[str]] = None,
        agent_outputs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {
            "research_method": method,
            "output_contract": EXPERIMENT_OUTPUT_SCHEMA_VERSION,
            "generation_tool_contract": "ctp-research-tools-v1.0",
        }
        if case is not None:
            metadata["method_input_schema_version"] = case.get("method_input_schema_version")
            metadata["goal_state_slots"] = self._goal_state_current_slots(case)
        if result_agents is not None:
            metadata["result_agents"] = _ordered_unique(result_agents)
        if agent_outputs is not None:
            metadata["agent_output_schema_version"] = RESEARCH_AGENT_OUTPUT_SCHEMA_VERSION
            metadata["agent_decision_schema_version"] = RESEARCH_AGENT_DECISION_SCHEMA_VERSION
            metadata["agent_prompt_version"] = RESEARCH_AGENT_PROMPT_VERSION
            metadata["agent_outputs"] = agent_outputs
            metadata["agent_decision_audit"] = self._agent_decision_audit(agent_outputs)
        if scheduler_metadata is not None:
            if method == "adaptive_multi_agent":
                metadata["adaptive_scheduler"] = scheduler_metadata
            elif method == "fixed_multi_agent":
                metadata["fixed_template_scheduler"] = scheduler_metadata
            metadata["scheduler"] = scheduler_metadata
            reuse_execution = scheduler_metadata.get("reuse_execution")
            if isinstance(reuse_execution, dict):
                metadata["reuse_execution"] = reuse_execution
        return metadata

    def _scheduler_metadata_with_result_fingerprints(
        self,
        scheduler_metadata: Optional[Dict[str, Any]],
        result_fingerprints: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if scheduler_metadata is None:
            return None
        return {
            **scheduler_metadata,
            "result_fingerprints": result_fingerprints,
        }

    def _infer_research_task_type(self, case: Dict[str, Any]) -> str:
        ticket = build_goal_state_ticket(
            user_input=str(case.get("user_input") or ""),
            current_slots=self._goal_state_current_slots(case),
            previous_state=self._goal_state_previous_state(case),
        )
        return self._canonical_research_task_type(ticket.task_type)

    def _canonical_research_task_type(self, task_type: Any) -> str:
        normalized = self._normalized_research_task_type(task_type)
        if normalized in FROZEN_RESEARCH_TASK_TYPES:
            return normalized
        return "general_chat"

    def _normalized_research_task_type(self, task_type: Any) -> str:
        normalized = str(task_type or "").strip().casefold()
        return RESEARCH_TASK_TYPE_ALIASES.get(normalized, normalized)

    def _is_tourism_case(self, case: Dict[str, Any]) -> bool:
        return self._infer_research_task_type(case) not in {"general_chat", "clarification"}

    def _needs_visible_clarification(self, case: Dict[str, Any]) -> bool:
        if case.get("previous_state") or case.get("method_previous_state"):
            return False
        slots = self._case_slots(case)
        missing_required = self._visible_clarification_fields(case)
        if not missing_required:
            return False
        text = str(case.get("user_input") or "").casefold()
        if any(term in text for term in ("only weather", "weather only", "only attractions", "attractions only", "budget only")):
            return False
        return bool(
            self._case_city(case)
            or any(term in text for term in ("trip", "plan", "itinerary", "visit", "travel", "旅游", "行程", "规划", "旅行"))
        )

    def _visible_clarification_fields(self, case: Dict[str, Any]) -> List[str]:
        slots = self._goal_state_current_slots(case)
        ticket = build_goal_state_ticket(
            user_input=str(case.get("user_input") or ""),
            current_slots=slots,
            previous_state=self._goal_state_previous_state(case),
        )
        if ticket.task_type == "clarification" and ticket.clarification_fields:
            return list(ticket.clarification_fields)
        return [
            slot
            for slot in ("destination", "duration_days", "people_count")
            if slot not in slots
        ]

    def _case_city(self, case: Dict[str, Any]) -> str:
        slots = self._case_slots(case)
        structured = case.get("structured_request") if isinstance(case.get("structured_request"), dict) else {}
        return str(
            slots.get("destination")
            or slots.get("city")
            or structured.get("city")
            or structured.get("destination")
            or case.get("city")
            or case.get("destination")
            or ""
        ).strip()

    def _case_origin(self, case: Dict[str, Any]) -> str:
        slots = self._case_slots(case)
        structured = case.get("structured_request") if isinstance(case.get("structured_request"), dict) else {}
        return str(
            slots.get("origin")
            or slots.get("departure_city")
            or slots.get("from_city")
            or structured.get("origin")
            or structured.get("departure_city")
            or structured.get("from_city")
            or case.get("origin")
            or case.get("departure_city")
            or case.get("from_city")
            or ""
        ).strip()

    def _case_duration(self, case: Dict[str, Any]) -> int:
        slots = self._case_slots(case)
        structured = case.get("structured_request") if isinstance(case.get("structured_request"), dict) else {}
        for value in (
            slots.get("duration"),
            slots.get("duration_days"),
            slots.get("days"),
            structured.get("days"),
            structured.get("duration"),
            structured.get("duration_days"),
            case.get("days"),
            case.get("duration"),
            case.get("duration_days"),
        ):
            if value is None or value == "":
                continue
            try:
                return max(1, min(int(value), 5))
            except (TypeError, ValueError):
                continue
        return 3

    def _case_start_date(self, case: Dict[str, Any]) -> Optional[str]:
        slots = self._case_slots(case)
        structured = case.get("structured_request") if isinstance(case.get("structured_request"), dict) else {}
        value = (
            slots.get("start_date")
            or slots.get("date")
            or structured.get("start_date")
            or structured.get("date")
            or case.get("start_date")
            or case.get("date")
        )
        return _optional_text(value)

    def _case_preferences(self, case: Dict[str, Any]) -> List[str]:
        slots = self._case_slots(case)
        structured = case.get("structured_request") if isinstance(case.get("structured_request"), dict) else {}
        preferences = slots.get("preferences") or structured.get("preferences") or case.get("preferences") or []
        constraints = case.get("constraints") or structured.get("constraints") or []
        return [*_as_list(preferences), *_as_list(constraints)]

    def _case_people(self, case: Dict[str, Any]) -> str:
        slots = self._case_slots(case)
        structured = case.get("structured_request") if isinstance(case.get("structured_request"), dict) else {}
        return str(
            slots.get("traveler_type")
            or slots.get("traveler_group")
            or structured.get("traveler_type")
            or structured.get("traveler_group")
            or case.get("traveler_type")
            or case.get("traveler_group")
            or "general"
        )

    def _case_traveler_count(self, case: Dict[str, Any]) -> int:
        slots = self._case_slots(case)
        structured = case.get("structured_request") if isinstance(case.get("structured_request"), dict) else {}
        for value in (
            slots.get("num_travelers"),
            slots.get("people_count"),
            structured.get("num_travelers"),
            structured.get("people_count"),
            case.get("num_travelers"),
            case.get("people_count"),
        ):
            if value is None or value == "":
                continue
            try:
                return max(1, int(value))
            except (TypeError, ValueError):
                continue
        people = self._case_people(case)
        if people in {"couple", "情侣"}:
            return 2
        if people in {"family", "family_kids", "family_senior", "亲子", "家庭"}:
            return 3
        return 1

    def _case_budget_level(self, case: Dict[str, Any]) -> str:
        explicit = self._case_explicit_budget_level(case)
        if explicit:
            return explicit
        return "medium"

    def _case_explicit_budget_level(self, case: Dict[str, Any]) -> str:
        slots = self._case_slots(case)
        structured = case.get("structured_request") if isinstance(case.get("structured_request"), dict) else {}
        value = (
            slots.get("budget_level")
            or structured.get("budget_level")
            or case.get("budget_level")
        )
        if value:
            return str(value)
        return ""

    def _case_budget_limit(self, case: Dict[str, Any]) -> Optional[float]:
        slots = self._case_slots(case)
        structured = case.get("structured_request") if isinstance(case.get("structured_request"), dict) else {}
        for value in (
            slots.get("budget_limit"),
            slots.get("budget"),
            slots.get("budget_amount"),
            structured.get("budget_limit"),
            structured.get("budget"),
            structured.get("budget_amount"),
            case.get("budget_limit"),
            case.get("budget"),
            case.get("budget_amount"),
        ):
            if value is None or value == "":
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    def _case_budget_basis(self, case: Dict[str, Any]) -> Optional[str]:
        value = self._case_first_value_slot(case, "budget_basis")
        text = str(value or "").strip().lower()
        if text in {"per_person", "person", "pp", "average"}:
            return "per_person"
        if text in {"total", "overall", "trip_total"}:
            return "total"
        return None

    def _case_requested_budget_scope(self, case: Dict[str, Any]) -> str:
        explicit = self._case_first_value_slot(
            case,
            "requested_budget_scope",
            "budget_scope",
        )
        text = str(explicit or "").strip().lower()
        if text in {"destination_local_only", "local_only", "destination_only", "local"}:
            return "destination_local_only"
        if text in {"local_plus_round_trip_intercity", "full_trip", "complete_trip", "full"}:
            return "local_plus_round_trip_intercity"
        included = self._case_intercity_transport_included(case, derive=False)
        if included is False:
            return "destination_local_only"
        return "local_plus_round_trip_intercity" if self._case_origin(case) else "destination_local_only"

    def _case_intercity_transport_included(
        self,
        case: Dict[str, Any],
        *,
        derive: bool = True,
    ) -> Optional[bool]:
        value = self._case_first_value_slot(case, "intercity_transport_included")
        if isinstance(value, bool):
            return value
        if value is not None and value != "":
            text = str(value).strip().lower()
            if text in {"true", "1", "yes", "y", "included", "include"}:
                return True
            if text in {"false", "0", "no", "n", "excluded", "exclude"}:
                return False
        if not derive:
            return None
        scope = self._case_requested_budget_scope(case)
        if scope == "destination_local_only":
            return False
        return bool(self._case_origin(case))

    def _case_mandatory_budget_disclaimer(self, case: Dict[str, Any]) -> bool:
        value = self._case_first_value_slot(case, "mandatory_budget_disclaimer")
        if isinstance(value, bool):
            return value
        if value is not None and value != "":
            text = str(value).strip().lower()
            if text in {"true", "1", "yes", "y", "required"}:
                return True
            if text in {"false", "0", "no", "n"}:
                return False
        return bool(self._case_budget_limit(case) is not None and not self._case_origin(case))

    def _case_hotel_level(self, case: Dict[str, Any]) -> Optional[str]:
        return self._case_first_text_slot(case, "hotel_level", "accommodation_level", "lodging_level")

    def _case_food_level(self, case: Dict[str, Any]) -> Optional[str]:
        return self._case_first_text_slot(case, "food_level", "dining_level")

    def _case_transport_mode(self, case: Dict[str, Any]) -> Optional[str]:
        return self._case_first_text_slot(case, "transport_mode", "local_transport_mode")

    def _case_first_value_slot(self, case: Dict[str, Any], *keys: str) -> Any:
        slots = self._case_slots(case)
        structured = case.get("structured_request") if isinstance(case.get("structured_request"), dict) else {}
        for container in (slots, structured, case):
            for key in keys:
                if isinstance(container, dict) and key in container and container.get(key) is not None:
                    return container.get(key)
        return None

    def _case_first_text_slot(self, case: Dict[str, Any], *keys: str) -> Optional[str]:
        slots = self._case_slots(case)
        structured = case.get("structured_request") if isinstance(case.get("structured_request"), dict) else {}
        expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
        gold_slots = expected.get("gold_slots") if isinstance(expected.get("gold_slots"), dict) else {}
        for container in (slots, structured, gold_slots, case):
            for key in keys:
                value = container.get(key) if isinstance(container, dict) else None
                text = str(value or "").strip()
                if text:
                    return text
        return None

    def _offline_data_summary(self, *, compact: bool = False) -> Dict[str, Any]:
        manifest = validate_fixed_data_snapshot()
        if not compact:
            return manifest
        return {
            "schema_version": manifest["schema_version"],
            "hash_strategy": manifest["hash_strategy"],
            "city_ids": manifest["city_ids"],
            "file_count": manifest["file_count"],
            "combined_sha256": manifest["combined_sha256"],
        }

    def _case_poi_limit(self, case: Dict[str, Any]) -> int:
        requested_count = self._case_requested_poi_count(case)
        if requested_count is not None:
            return requested_count
        duration_limit = max(3, min(self._case_duration(case) * 2, 10))
        task_type = self._case_constraint_task_type(case)
        if task_type == "attraction_recommendation":
            maximum = self._case_max_attractions(case)
            if maximum is not None and maximum > 0:
                return max(1, min(maximum, 20))
            return 5

        minimum = self._case_min_attractions(case) or 0
        limit = max(duration_limit, minimum)
        if self._case_should_expand_poi_candidates_for_weather(case):
            limit = max(limit, minimum * 3, self._case_duration(case) * 4, 10)
        return max(1, min(limit, 20))

    def _case_should_expand_poi_candidates_for_weather(self, case: Dict[str, Any]) -> bool:
        forbidden_tools = {
            str(item)
            for item in _as_list(_nested_mapping(case, "expected", "forbidden_tools"))
        }
        if "weather_query" in forbidden_tools:
            return False
        required_tools = {
            str(item)
            for item in _as_list(_nested_mapping(case, "expected", "required_tools"))
        }
        if "weather_query" in required_tools:
            return True
        if case.get("weather_change") or _nested_mapping(case, "expected", "weather_change"):
            return True
        return bool(self._case_start_date(case) and self._case_constraint_task_type(case) in {
            "trip_planning",
            "partial_replan",
            "weather_adjustment",
        })

    def _case_requested_poi_count(self, case: Dict[str, Any]) -> Optional[int]:
        text = str(case.get("user_input") or "")
        patterns = (
            r"(?:挑|推荐|选择|选|给我|帮我).*?(\d{1,2}|一|二|两|俩|三|四|五|六|七|八|九|十)\s*(?:个|处|座)?\s*(?:景点|poi|attractions?)",
            r"(\d{1,2}|一|二|两|俩|三|四|五|六|七|八|九|十)\s*(?:个|处|座)?\s*(?:适合[^，。,.]*的)?\s*(?:景点|poi|attractions?)",
            r"(\d{1,2}|一|二|两|俩|三|四|五|六|七|八|九|十)\s*(?:个|处|座)?\s*[^，。,.!?！？；;]{0,16}(?:景点|poi|attractions?)",
            r"\b(?:top|choose|pick|recommend)\s+(\d{1,2})\s+(?:attractions?|pois?)\b",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            value = _number_word_to_int(match.group(1))
            if value is not None:
                return max(1, min(value, 10))
        return None

    def _case_min_attractions(self, case: Dict[str, Any]) -> Optional[int]:
        return _first_positive_int(
            _nested_mapping(case, "expected", "hard_constraints", "min_attractions"),
            _nested_mapping(case, "expected", "min_attractions"),
            case.get("min_attractions"),
            default=0,
        ) or None

    def _case_max_attractions(self, case: Dict[str, Any]) -> Optional[int]:
        return _first_positive_int(
            _nested_mapping(case, "expected", "hard_constraints", "max_attractions"),
            _nested_mapping(case, "expected", "max_attractions"),
            case.get("max_attractions"),
            default=0,
        ) or None

    def _case_max_pois_per_day(self, case: Dict[str, Any]) -> int:
        return _first_positive_int(
            _nested_mapping(case, "expected", "hard_constraints", "max_pois_per_day"),
            _nested_mapping(case, "expected", "max_pois_per_day"),
            case.get("max_pois_per_day"),
            default=2,
        )

    def _case_has_evidence_normalization_targets(self, case: Dict[str, Any]) -> bool:
        constraints = _nested_mapping(case, "expected", "hard_constraints")
        expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
        return bool(
            isinstance(constraints, dict)
            and any(
                key in constraints
                for key in (
                    "min_attractions",
                    "max_attractions",
                    "max_pois_per_day",
                    "weather_adjustment_required",
                    "weather_scenario",
                )
            )
            or case.get("weather_change")
            or expected.get("weather_change")
        )

    def _case_weather_scenario(self, case: Dict[str, Any]) -> str:
        slots = self._case_slots(case)
        structured = case.get("structured_request") if isinstance(case.get("structured_request"), dict) else {}
        weather_change = case.get("weather_change") if isinstance(case.get("weather_change"), dict) else {}
        raw_weather_scenario = (
            slots.get("weather_scenario")
            or structured.get("weather_scenario")
            or weather_change.get("scenario_type")
            or case.get("weather_scenario")
            or case.get("scenario_type")
        )
        if not raw_weather_scenario:
            scenario_text = " ".join(
                [
                    str(case.get("user_input") or ""),
                    " ".join(str(item) for item in case.get("constraints") or []),
                ]
            ).casefold()
            if "rain" in scenario_text or "rainy" in scenario_text:
                return "rain"
            if "high temperature" in scenario_text or "hot" in scenario_text:
                return "high_temperature"
            if "low temperature" in scenario_text or "cold" in scenario_text:
                return "low_temperature"
        explicit = (
            slots.get("weather_scenario")
            or structured.get("weather_scenario")
            or weather_change.get("scenario_type")
            or case.get("weather_scenario")
            or case.get("scenario_type")
        )
        if explicit:
            normalized = self._normalize_weather_scenario(explicit)
            if normalized:
                return normalized
        text = " ".join(
            [
                str(case.get("user_input") or ""),
                " ".join(str(item) for item in case.get("constraints") or []),
            ]
        )
        if "高温" in text:
            return "high_temperature"
        if "低温" in text or "寒冷" in text:
            return "low_temperature"
        if "变化" in text or "忽晴忽雨" in text:
            return "continuous_change"
        if "雨" in text or "下雨" in text:
            return "rain"
        return "sunny"

    def _normalize_weather_scenario(self, value: Any) -> str:
        text = str(value or "").strip().casefold()
        if not text:
            return ""
        if "rain" in text or "雨" in text:
            return "rain"
        if "high_temperature" in text or "high temperature" in text or "hot" in text or "高温" in text:
            return "high_temperature"
        if "low_temperature" in text or "low temperature" in text or "cold" in text or "寒冷" in text or "低温" in text:
            return "low_temperature"
        if "continuous_change" in text or "change" in text:
            return "continuous_change"
        if "sunny" in text or "晴" in text:
            return "sunny"
        return str(value or "").strip()

    def _poi_ids_from_result(self, result: Any) -> List[str]:
        return [
            str(item.get("poi_id"))
            for item in self._attractions_from_tool_result(result)
            if item.get("poi_id")
        ]

    def _attractions_from_tool_result(self, result: Any) -> List[Dict[str, Any]]:
        data = self._tool_data(result)
        attractions = data.get("attractions") if isinstance(data, dict) else []
        return [item for item in attractions if isinstance(item, dict)] if isinstance(attractions, list) else []

    def _tool_data(self, result: Any) -> Dict[str, Any]:
        if not isinstance(result, dict):
            return {}
        data = result.get("data")
        return data if isinstance(data, dict) else {}

    def _build_daily_itinerary(
        self,
        trip_days: int,
        attractions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        days: List[Dict[str, Any]] = []
        if trip_days < 1:
            return days
        for day_index in range(1, trip_days + 1):
            start = (day_index - 1) * 2
            selected = attractions[start : start + 2]
            days.append(
                {
                    "day": day_index,
                    "attractions": [
                        {
                            "poi_id": item.get("poi_id"),
                            "name": item.get("name"),
                            "category": item.get("category"),
                            "indoor_outdoor": item.get("indoor_outdoor"),
                        }
                        for item in selected
                    ],
                    "notes": "由固定离线 POI 结果生成的实验行程骨架",
                }
            )
        return days

    def _build_weather_adjustments(
        self,
        weather: Dict[str, Any],
        attractions: List[Dict[str, Any]],
        *,
        case: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if not weather:
            if (
                isinstance(case, dict)
                and self._case_constraint_task_type(case) == "weather_adjustment"
            ):
                scenario = self._case_weather_scenario(case)
                affected_days = self._explicit_affected_weather_days(case) or [1]
                return [
                    {
                        "day": day,
                        "day_index": day,
                        "reason": scenario or "user_supplied_weather_change",
                        "action": "根据用户提供的天气变化调整受影响日期的行程安排",
                        "candidate_indoor_pois": [
                            {"poi_id": item.get("poi_id"), "name": item.get("name")}
                            for item in attractions
                            if str(item.get("indoor_outdoor") or "").lower() == "indoor"
                        ][:3],
                        "source": "user_supplied_weather_change",
                    }
                    for day in affected_days
                ]
            return []
        scenario = str(weather.get("scenario_type") or "")
        risky = scenario in {"rain", "high_temperature", "low_temperature", "continuous_change"}
        if not risky and not weather.get("weather_adjustment_required"):
            return []
        affected_days = self._affected_weather_days(case, weather)
        indoor_candidates = [
            item
            for item in attractions
            if str(item.get("indoor_outdoor") or "").lower() == "indoor"
        ]
        return [
            {
                "day": day,
                "day_index": day,
                "reason": scenario or "weather_risk",
                "action": "减少长时间户外活动，优先安排室内或低风险景点",
                "candidate_indoor_pois": [
                    {"poi_id": item.get("poi_id"), "name": item.get("name")}
                    for item in indoor_candidates[:3]
                ],
            }
            for day in affected_days
        ]

    def _affected_weather_days(
        self,
        case: Optional[Dict[str, Any]],
        weather: Dict[str, Any],
    ) -> List[int]:
        explicit_days = self._explicit_affected_weather_days(case)
        if explicit_days:
            return explicit_days

        weather_days = self._weather_day_items(weather)
        risky_days: List[int] = []
        for index, day_weather in enumerate(weather_days, start=1):
            day_index = _first_positive_int(
                day_weather.get("day_index"),
                day_weather.get("day"),
                index,
                default=index,
            )
            if self._is_risky_weather_day(day_weather):
                risky_days.append(day_index)
        if risky_days:
            return _ordered_unique_ints(risky_days)

        if weather_days:
            first_day = weather_days[0]
            return [
                _first_positive_int(
                    first_day.get("day_index"),
                    first_day.get("day"),
                    1,
                    default=1,
                )
            ]
        return [1]

    def _explicit_affected_weather_days(
        self,
        case: Optional[Dict[str, Any]],
    ) -> List[int]:
        if not isinstance(case, dict):
            return []
        candidates = [
            _nested_value(case, "weather_change", "affected_days"),
            _nested_value(case, "expected", "weather_change", "affected_days"),
            _nested_value(case, "expected", "hard_constraints", "weather_change", "affected_days"),
            _nested_value(case, "gold", "weather_change", "affected_days"),
        ]
        for candidate in candidates:
            days = _int_list(candidate)
            if days:
                return days
        scenario_text = str(
            _nested_value(case, "weather_change", "scenario")
            or _nested_value(case, "weather_change", "scenario_type")
            or _nested_value(case, "expected", "weather_change", "scenario")
            or _nested_value(case, "expected", "weather_change", "scenario_type")
            or ""
        )
        return _days_from_weather_scenario_text(scenario_text)

    def _weather_day_items(self, weather: Dict[str, Any]) -> List[Dict[str, Any]]:
        for key in ("daily_weather", "daily_forecasts", "forecast"):
            value = weather.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    def _is_risky_weather_day(self, day_weather: Dict[str, Any]) -> bool:
        labels: List[str] = []
        for key in ("state", "condition", "weather", "day_weather", "scenario_type"):
            value = day_weather.get(key)
            if value is not None:
                labels.append(str(value).casefold())
        labels.extend(str(item).casefold() for item in day_weather.get("risk_tags") or [])
        joined = " ".join(labels)
        return any(
            marker in joined
            for marker in (
                "rain",
                "heat",
                "hot",
                "cold",
                "high_temperature",
                "low_temperature",
                "continuous_change",
                "雨",
                "高温",
                "低温",
            )
        )

    def _execution_status_from_tool_results(self, tool_results: Dict[str, Any]) -> str:
        for result in tool_results.values():
            if isinstance(result, dict) and str(result.get("status") or "").lower() in {
                "failed",
                "error",
                "timeout",
                "cancelled",
                "canceled",
                "aborted",
                "expired",
                "stale",
            }:
                return "failed"
        return "completed"

    def _execution_status_from_research_artifacts(
        self,
        *,
        tool_results: Dict[str, Any],
        agent_outputs: Dict[str, Any],
    ) -> str:
        if self._execution_status_from_tool_results(tool_results) == "failed":
            return "failed"
        for output in agent_outputs.values():
            if not isinstance(output, dict):
                continue
            status = str(output.get("status") or "").lower()
            if status in {
                "failed",
                "error",
                "timeout",
                "cancelled",
                "canceled",
                "aborted",
                "expired",
                "stale",
            } or output.get("success") is False or output.get("error"):
                return "failed"
        return "completed"

    async def _run_llm_baseline(
        self,
        *,
        case: Dict[str, Any],
        request_id: str,
        method: ExperimentMethod,
        system_prompt: str,
        user_prompt: str,
        selected_agents: List[str],
    ) -> str:
        session_id = self._case_session_id(case, method)
        with request_trace(
            request_id,
            session_id,
            user_message=case["user_input"],
            experiment_case_id=case["case_id"],
            method=method,
            evaluation_mode=case["evaluation_mode"],
        ) as trace:
            if trace is not None:
                self._initialize_trace_for_evaluation(case)
                set_trace_selected_agents(selected_agents)
            llm = self.llm_factory()
            response = await self._llm_chat_with_experiment_timeout(
                llm,
                [
                    LLMMessage(role="system", content=system_prompt),
                    LLMMessage(role="user", content=user_prompt),
                ]
            )
            set_trace_result_summary(response.content, offline_data=self._offline_data_summary(compact=True))
            return response.content

    def _normalize_case(self, case: Dict[str, Any]) -> Dict[str, Any]:
        case_id = str(case.get("case_id") or case.get("id") or self.generate_experiment_id("case"))
        user_input = (
            case.get("user_input")
            or case.get("query")
            or case.get("prompt")
            or case.get("message")
            or case.get("input")
        )
        if isinstance(user_input, dict):
            user_input = _input_dict_to_text(user_input)
        user_input = str(user_input or "").strip()
        if not user_input:
            user_input = _input_dict_to_text(case.get("structured_request") or case)

        evaluation_mode = self._normalize_evaluation_mode(case.get("evaluation_mode"))
        explicit_slots = dict(case.get("slots") or {})
        structured = case.get("structured_request") or {}
        structured_slots = _slots_from_mapping(structured) if isinstance(structured, dict) else {}
        case_level_slots = _slots_from_mapping(case)
        parsed_visible_slots: Dict[str, Any] = {}
        if evaluation_mode != "oracle_slots" or not (
            explicit_slots or structured_slots or case_level_slots
        ):
            parsed_visible_slots = parse_visible_request_slots(
                user_input,
                dialogue_history=case.get("dialogue_history"),
            )
        slots = self._merge_visible_slots_without_alias_conflict(
            parsed_visible_slots,
            explicit_slots,
        )
        if isinstance(structured, dict):
            slots.update(structured_slots)
        slots.update(case_level_slots)

        expected = dict(case.get("expected") or case.get("standard_answer") or {})
        expected_goal = case.get("expected_goal")
        if isinstance(expected_goal, dict):
            expected.update(expected_goal)
        if "selected_agents" not in expected and "agents" in expected:
            expected["selected_agents"] = expected.get("agents")
        if "selected_tools" not in expected and "tools" in expected:
            expected["selected_tools"] = expected.get("tools")
        return {
            **case,
            "case_id": case_id,
            "user_input": user_input,
            "slots": slots,
            "constraints": list(case.get("constraints") or structured.get("constraints") or []),
            "expected": expected,
            "evaluation_mode": evaluation_mode,
        }

    def _merge_visible_slots_without_alias_conflict(
        self,
        parsed_slots: Dict[str, Any],
        explicit_slots: Dict[str, Any],
    ) -> Dict[str, Any]:
        slots = dict(parsed_slots)
        alias_groups = (
            ("destination", "city"),
            ("duration_days", "duration", "days"),
            ("people_count", "num_travelers"),
            ("budget_amount", "budget", "budget_limit"),
            ("start_date", "date"),
        )
        for canonical, *aliases in alias_groups:
            if any(key in explicit_slots for key in (canonical, *aliases)):
                for key in (canonical, *aliases):
                    slots.pop(key, None)
        slots.update(explicit_slots)
        return slots

    def _normalize_evaluation_mode(self, evaluation_mode: Any) -> str:
        normalized = str(evaluation_mode or DEFAULT_EVALUATION_MODE).strip().lower().replace("-", "_")
        aliases = {
            "e2e": DEFAULT_EVALUATION_MODE,
            "end_to_end": DEFAULT_EVALUATION_MODE,
            "oracle": "oracle_slots",
            "oracle_slot": "oracle_slots",
            "oracle_slots": "oracle_slots",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized not in self.EVALUATION_MODES:
            raise ValueError(f"evaluation_mode must be one of {', '.join(self.EVALUATION_MODES)}")
        return normalized

    def _initialize_trace_for_evaluation(self, case: Dict[str, Any]) -> None:
        if case.get("evaluation_mode") == "oracle_slots":
            expected = case.get("expected") or {}
            set_trace_intent_info(
                mode="planning",
                intent=expected.get("intent"),
                route=expected.get("route"),
                extracted_info=case.get("slots", {}),
                constraints=case.get("constraints", []),
            )
            return
        set_trace_intent_info(mode="planning")

    async def _build_unified_result(
        self,
        *,
        case: Dict[str, Any],
        method: ExperimentMethod,
        output: Any,
        latency_ms: float,
        trace: Optional[Dict[str, Any]],
        error: Optional[str],
    ) -> Dict[str, Any]:
        trace_record = trace or {}
        ttft_ms = trace_record.get("first_body_token_ms")
        preliminary_output = normalize_experiment_output(
            case=case,
            method=method,
            raw_output=output,
            trace=trace_record,
            error=error,
        )
        constraint_report = await self._run_constraint_checker(
            case,
            preliminary_output,
            raw_output=output,
        )
        structured_output = normalize_experiment_output(
            case=case,
            method=method,
            raw_output={
                **preliminary_output,
                "constraint_report": constraint_report,
            },
            trace=trace_record,
            error=error,
            constraint_report=constraint_report,
        )
        structured_output = self._apply_no_date_weather_output_policy(
            case,
            structured_output,
        )
        metrics = self._score_against_expected(case.get("expected") or {}, trace_record)
        metrics.update(constraint_metrics_from_report(constraint_report))
        adaptive_scheduler_metrics = self._adaptive_scheduler_metrics_from_output(
            structured_output,
            trace_record,
        )
        if adaptive_scheduler_metrics:
            metrics.update(adaptive_scheduler_metrics)
            self._attach_adaptive_scheduler_metrics(
                structured_output,
                adaptive_scheduler_metrics,
            )
        evaluation = evaluate_case(
            case=case,
            output=structured_output,
            trace=trace_record,
        )
        metrics.update(evaluation.get("metrics") or {})
        run_audit = build_run_audit(
            method=method,
            output=structured_output,
            trace=trace_record,
            latency_ms=latency_ms,
            ttft_ms=ttft_ms if isinstance(ttft_ms, (int, float)) else None,
        )
        self._merge_run_audit_metrics(metrics, run_audit)
        self._attach_run_audit_metadata(structured_output, run_audit)
        input_hash = _stable_hash({"case_id": case["case_id"], "user_input": case["user_input"], "slots": case.get("slots")})
        result_hash = _stable_hash(structured_output)
        offline_data = self._offline_data_summary()
        trace_record.setdefault("input_hash", trace_record.get("user_message_hash") or input_hash)
        trace_record["result_hash"] = result_hash
        trace_record["offline_data"] = offline_data
        return {
            "case_id": case["case_id"],
            "method": method,
            "request_id": trace_record.get("request_id"),
            "run_id": trace_record.get("run_id"),
            "repeat_index": trace_record.get("repeat_index"),
            "system_variant": trace_record.get("system_variant"),
            "model_config_name": trace_record.get("model_config_name"),
            "evaluation_mode": case["evaluation_mode"],
            "input_hash": trace_record.get("input_hash"),
            "result_hash": result_hash,
            "offline_data": offline_data,
            "output": structured_output,
            "constraint_report": constraint_report,
            "hard_constraint_applicable_count": structured_output.get("hard_constraint_applicable_count"),
            "hard_constraint_passed_count": structured_output.get("hard_constraint_passed_count"),
            "hard_constraint_failed_count": structured_output.get("hard_constraint_failed_count"),
            "hard_constraints_all_satisfied": structured_output.get("hard_constraints_all_satisfied"),
            "hcsr": structured_output.get("hcsr"),
            "raw_output": output,
            "latency": latency_ms,
            "latency_ms": latency_ms,
            "ttft_ms": ttft_ms if isinstance(ttft_ms, (int, float)) else None,
            "trace": trace_record,
            "trace_file": trace_record.get("trace_file"),
            "evaluation": evaluation,
            "run_audit": run_audit,
            "audit": run_audit,
            "status": "failed" if error else structured_output.get("execution_status") or trace_record.get("status", "completed"),
            "metrics": metrics,
            "error": error,
        }

    async def _run_constraint_checker(
        self,
        case: Dict[str, Any],
        structured_output: Dict[str, Any],
        raw_output: Any = None,
    ) -> Dict[str, Any]:
        checker = ResearchConstraintCheckerTool()
        plan = self._constraint_checker_plan(
            case=case,
            structured_output=structured_output,
            raw_output=raw_output,
        )
        result = await checker.execute(
            request=self._constraint_request_payload(case),
            plan=plan,
            constraints=self._constraint_payload(case),
        )
        if isinstance(result.data, dict):
            return result.data
        return {
            "schema_version": "research_tool_result_v1",
            "tool_name": "constraint_checker",
            "status": "failed",
            "success": False,
            "data": {
                "all_passed": False,
                "applicable_count": 0,
                "passed_count": 0,
                "failed_count": 0,
                "checks": [],
            },
            "error": {"code": "checker_output_error", "message": result.error or "invalid checker output"},
            "metadata": {"offline": True, "source_mode": "deterministic_evaluator"},
        }

    def _constraint_checker_plan(
        self,
        *,
        case: Optional[Dict[str, Any]] = None,
        structured_output: Dict[str, Any],
        raw_output: Any = None,
    ) -> Dict[str, Any]:
        plan = {
            key: value
            for key, value in structured_output.items()
            if key not in {"method", "used_agents", "called_tools", "tool_results", "metadata"}
        }
        canonical_attractions, canonical_audit = (
            self._canonical_attractions_for_constraint_plan(
                task_type=str(plan.get("task_type") or ""),
                attractions=[
                    item
                    for item in plan.get("attractions") or []
                    if isinstance(item, dict)
                ],
                daily_itinerary=[
                    item
                    for item in plan.get("daily_itinerary") or []
                    if isinstance(item, dict)
                ],
            )
        )
        if canonical_audit.get("applied"):
            plan["attractions"] = canonical_attractions
            plan["constraint_plan_normalization"] = canonical_audit
        tool_results = self._tool_results_for_constraint_checker(
            structured_output=structured_output,
            raw_output=raw_output,
        )
        if isinstance(tool_results, dict) and tool_results:
            plan["tool_results"] = tool_results
        context_tool_results = self._context_tool_results_for_constraint_checker(
            case=case,
            current_tool_results=tool_results,
        )
        if context_tool_results:
            plan["context_tool_results"] = context_tool_results
        return plan

    def _context_tool_results_for_constraint_checker(
        self,
        *,
        case: Optional[Dict[str, Any]],
        current_tool_results: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not isinstance(case, dict):
            return {}
        if self._case_constraint_task_type(case) not in {"partial_replan", "weather_adjustment"}:
            return {}
        if self._case_has_destination_change(case):
            return {}
        previous_tool_results = self._previous_tool_results_from_state(
            self._goal_state_previous_state(case)
        )
        if not isinstance(previous_tool_results, dict) or not previous_tool_results:
            return {}
        current_tool_results = current_tool_results if isinstance(current_tool_results, dict) else {}
        context: Dict[str, Any] = {}
        for tool_name in GENERATION_TOOL_NAMES:
            if self._is_successful_reusable_tool_result(current_tool_results.get(tool_name)):
                continue
            previous_result = previous_tool_results.get(tool_name)
            if self._is_successful_reusable_tool_result(previous_result):
                context[tool_name] = previous_result
        return context

    def _tool_results_for_constraint_checker(
        self,
        *,
        structured_output: Dict[str, Any],
        raw_output: Any = None,
    ) -> Optional[Dict[str, Any]]:
        for candidate in (
            raw_output,
            structured_output,
            structured_output.get("raw_output"),
            _nested_mapping(structured_output, "raw_output", "raw_output"),
        ):
            if not isinstance(candidate, dict):
                continue
            tool_results = candidate.get("tool_results")
            if isinstance(tool_results, dict) and tool_results:
                return tool_results
        return None

    def _constraint_request_payload(self, case: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(case.get("slots") or {})
        payload.update(
            {
                "case_id": case.get("case_id"),
                "user_input": case.get("user_input"),
                "city": self._case_city(case),
                "budget": self._case_budget_limit(case),
            }
        )
        if self._case_has_itinerary_constraint_scope(case):
            payload["days"] = self._case_duration(case)
        return payload

    def _constraint_payload(self, case: Dict[str, Any]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        budget = self._case_budget_limit(case)
        if budget is not None:
            payload["budget_limit"] = budget
        has_itinerary_scope = self._case_has_itinerary_constraint_scope(case)
        if has_itinerary_scope:
            payload["days"] = self._case_duration(case)
        raw_constraints = case.get("constraints") or []
        if raw_constraints:
            payload["raw_constraints"] = raw_constraints
        text = " ".join([str(case.get("user_input") or ""), *[str(item) for item in raw_constraints]])
        if has_itinerary_scope and any(word in text for word in ("雨", "下雨", "天气", "高温", "低温", "室内")):
            payload["weather_adjustment_required"] = True
        expected = case.get("expected") or {}
        for key in (
            "min_attractions",
            "max_attractions",
            "max_pois_per_day",
            "must_include_pois",
            "forbidden_pois",
        ):
            if key in expected:
                payload[key] = expected[key]
        if isinstance(expected.get("hard_constraints"), dict):
            payload.update(expected["hard_constraints"])
        return payload

    def _case_has_itinerary_constraint_scope(self, case: Dict[str, Any]) -> bool:
        return self._case_constraint_task_type(case) in {
            "trip_planning",
            "partial_replan",
            "weather_adjustment",
        }

    def _case_constraint_task_type(self, case: Dict[str, Any]) -> str:
        expected_task_type = _nested_mapping(case, "expected", "task_type")
        if expected_task_type:
            return self._canonical_research_task_type(expected_task_type)
        direct_task_type = case.get("task_type")
        if direct_task_type:
            return self._canonical_research_task_type(direct_task_type)
        return self._infer_research_task_type(case)

    def _apply_no_date_weather_output_policy(
        self,
        case: Dict[str, Any],
        output: Dict[str, Any],
    ) -> Dict[str, Any]:
        expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
        if not gold_requires_no_date_weather_reminder(expected):
            return output
        task_type = self._canonical_research_task_type(output.get("task_type"))
        if task_type not in {"trip_planning", "partial_replan"}:
            return output

        final_answer = append_no_date_weather_reminder(output.get("final_answer"))
        updated = dict(output)
        updated["final_answer"] = final_answer

        raw_output = updated.get("raw_output")
        if isinstance(raw_output, dict):
            updated["raw_output"] = {
                **raw_output,
                "final_answer": final_answer,
            }

        metadata = updated.get("metadata")
        if isinstance(metadata, dict):
            updated["metadata"] = {
                **metadata,
                "no_date_weather_output_policy": {
                    "applied": True,
                    "source": "deterministic_runner_policy",
                },
            }
        return updated

    def _score_against_expected(self, expected: Dict[str, Any], trace: Dict[str, Any]) -> Dict[str, Any]:
        expected_tools = _as_list(expected.get("selected_tools") or expected.get("tools"))
        selected_tools = _as_list(trace.get("planned_tools") or trace.get("selected_tools"))
        expected_agents = _as_list(expected.get("selected_agents") or expected.get("agents"))
        selected_agents = _as_list(trace.get("planned_agents") or trace.get("selected_agents"))

        tool_accuracy: Optional[float] = None
        if expected_tools:
            tool_accuracy = len(set(expected_tools) & set(selected_tools)) / len(set(expected_tools))

        return {
            "expected_tools": expected_tools,
            "selected_tools": selected_tools,
            "expected_tool_count": len(expected_tools),
            "correct_tool_count": len(set(expected_tools) & set(selected_tools)) if expected_tools else None,
            "tool_selection_accuracy": tool_accuracy,
            "intent_correct": _optional_equal(expected.get("intent"), trace.get("intent")),
            "route_correct": _optional_equal(expected.get("route"), trace.get("route")),
            "agents_correct": (
                None
                if not expected_agents
                else set(expected_agents).issubset(set(selected_agents))
            ),
        }

    def _adaptive_scheduler_metrics_from_output(
        self,
        structured_output: Dict[str, Any],
        trace_record: Dict[str, Any],
    ) -> Dict[str, Any]:
        scheduler = _nested_mapping(structured_output, "metadata", "adaptive_scheduler")
        if not isinstance(scheduler, dict):
            trace_scheduler = trace_record.get("adaptive_scheduler")
            scheduler = trace_scheduler if isinstance(trace_scheduler, dict) else {}
        if not isinstance(scheduler, dict) or not scheduler:
            return {}

        ticket = scheduler.get("ticket") if isinstance(scheduler.get("ticket"), dict) else {}
        decision = scheduler.get("decision") if isinstance(scheduler.get("decision"), dict) else {}
        reuse_execution = (
            scheduler.get("reuse_execution")
            if isinstance(scheduler.get("reuse_execution"), dict)
            else {}
        )

        planned_agents = _as_list(decision.get("planned_agents"))
        planned_tools = _as_list(decision.get("planned_tools"))
        reused_agents = _as_list(reuse_execution.get("reused_agent_results"))
        invalidated_agents = _as_list(decision.get("invalidated_agents"))
        clarification_fields = _as_list(
            decision.get("clarification_fields") or ticket.get("clarification_fields")
        )
        decision_reasons = _as_list(decision.get("decision_reasons"))
        reused_tool_results = _as_list(reuse_execution.get("reused_tool_results"))
        missing_reused_tool_results = _as_list(
            reuse_execution.get("missing_reused_tool_results")
        )
        expected_reused_tools = _as_list(
            reuse_execution.get("expected_reused_tools")
        ) or self._tools_for_agents(reused_agents)

        executed_agents = _as_list(trace_record.get("executed_agents"))
        executed_tools = _as_list(trace_record.get("executed_tools"))
        agent_scope = _ordered_unique([*planned_agents, *reused_agents])
        tool_scope = _ordered_unique([*planned_tools, *expected_reused_tools])

        m2_reference_agent_count, m2_reference_tool_count = self._m2_reference_counts_for_m3(
            ticket=ticket,
        )
        agent_call_savings = max(0, m2_reference_agent_count - len(planned_agents))
        tool_call_savings = max(0, m2_reference_tool_count - len(planned_tools))

        expected_reused_tool_count = len(expected_reused_tools)
        reused_tool_result_count = len(reused_tool_results)

        return {
            "m3_scheduler_name": scheduler.get("name") or "goal_state_scheduler",
            "m3_task_type": ticket.get("task_type"),
            "m3_clarification_required": bool(
                decision.get("clarification_required")
                or ticket.get("clarification_required")
            ),
            "m3_clarification_fields": clarification_fields,
            "m3_clarification_field_count": len(clarification_fields),
            "m3_decision_reasons": decision_reasons,
            "m3_planned_agents": planned_agents,
            "m3_reused_agents": reused_agents,
            "m3_invalidated_agents": invalidated_agents,
            "m3_planned_tools": planned_tools,
            "m3_expected_reused_tools": expected_reused_tools,
            "m3_reused_tool_results": reused_tool_results,
            "m3_missing_reused_tool_results": missing_reused_tool_results,
            "m3_previous_state_provided": bool(
                reuse_execution.get("previous_state_provided")
            ),
            "m3_m2_reference_agent_count": m2_reference_agent_count,
            "m3_m2_reference_tool_count": m2_reference_tool_count,
            "m3_planned_agent_count": len(planned_agents),
            "m3_executed_agent_count": len(executed_agents),
            "m3_reused_agent_count": len(reused_agents),
            "m3_invalidated_agent_count": len(invalidated_agents),
            "m3_planned_tool_count": len(planned_tools),
            "m3_executed_tool_count": len(executed_tools),
            "m3_expected_reused_tool_count": expected_reused_tool_count,
            "m3_reused_tool_result_count": reused_tool_result_count,
            "m3_missing_reused_tool_result_count": len(missing_reused_tool_results),
            "m3_agent_reuse_rate": _safe_ratio(len(reused_agents), len(agent_scope)),
            "m3_tool_reuse_rate": _safe_ratio(reused_tool_result_count, len(tool_scope)),
            "m3_reuse_hit_rate": _safe_ratio(
                reused_tool_result_count,
                expected_reused_tool_count,
            ),
            "m3_agent_call_savings_vs_m2": agent_call_savings,
            "m3_tool_call_savings_vs_m2": tool_call_savings,
            "m3_agent_call_reduction_rate_vs_m2": _safe_ratio(
                agent_call_savings,
                m2_reference_agent_count,
            ),
            "m3_tool_call_reduction_rate_vs_m2": _safe_ratio(
                tool_call_savings,
                m2_reference_tool_count,
            ),
        }

    def _m2_reference_counts_for_m3(
        self,
        *,
        ticket: Dict[str, Any],
    ) -> tuple[int, int]:
        agents, tools, _reasons = self._m2_fixed_template_for_ticket(ticket)
        return len(agents), len(tools)

    def _attach_adaptive_scheduler_metrics(
        self,
        structured_output: Dict[str, Any],
        scheduler_metrics: Dict[str, Any],
    ) -> None:
        metadata = structured_output.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            return
        metadata["adaptive_scheduler_metrics"] = dict(scheduler_metrics)

    def _merge_run_audit_metrics(
        self,
        metrics: Dict[str, Any],
        run_audit: Dict[str, Any],
    ) -> None:
        audit_metrics = run_audit.get("metrics")
        if not isinstance(audit_metrics, dict):
            return
        for key, value in audit_metrics.items():
            if value is None:
                continue
            if metrics.get(key) is None:
                metrics[key] = value

    def _attach_run_audit_metadata(
        self,
        structured_output: Dict[str, Any],
        run_audit: Dict[str, Any],
    ) -> None:
        metadata = structured_output.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            return
        metadata["run_audit_schema_version"] = (
            run_audit.get("schema_version") or RUN_AUDIT_SCHEMA_VERSION
        )

    def _flatten_result_for_csv(self, result: Dict[str, Any]) -> Dict[str, Any]:
        trace = result.get("trace") or {}
        metrics = result.get("metrics") or {}
        hard_timeout = (
            result.get("result_hard_timeout")
            if isinstance(result.get("result_hard_timeout"), dict)
            else {}
        )
        run_audit = result.get("run_audit") if isinstance(result.get("run_audit"), dict) else {}
        audit_metrics = run_audit.get("metrics") if isinstance(run_audit.get("metrics"), dict) else {}
        output = result.get("output")
        output_text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
        return {
            "scenario_id": result.get("scenario_id"),
            "turn_id": result.get("turn_id"),
            "turn_index": result.get("turn_index"),
            "scenario_turn_count": result.get("scenario_turn_count"),
            "target_turn": result.get("target_turn"),
            "method_previous_state_policy": result.get("method_previous_state_policy"),
            "previous_state_provided": result.get("previous_state_provided"),
            "previous_state_schema_version": result.get("previous_state_schema_version"),
            "previous_state_method": result.get("previous_state_method"),
            "previous_state_turn_id": result.get("previous_state_turn_id"),
            "previous_state_turn_index": result.get("previous_state_turn_index"),
            "previous_state_is_method_local": result.get("previous_state_is_method_local"),
            "previous_state_is_prior_turn": result.get("previous_state_is_prior_turn"),
            "previous_state_has_evaluation": result.get("previous_state_has_evaluation"),
            "previous_state_has_metrics": result.get("previous_state_has_metrics"),
            "case_id": result.get("case_id"),
            "method": result.get("method"),
            "request_id": result.get("request_id"),
            "run_id": result.get("run_id"),
            "repeat_index": result.get("repeat_index"),
            "system_variant": result.get("system_variant"),
            "model_config_name": result.get("model_config_name"),
            "evaluation_mode": result.get("evaluation_mode"),
            "status": result.get("status"),
            "result_isolation": result.get("result_isolation"),
            "hard_timeout_enabled": hard_timeout.get("enabled"),
            "hard_timeout_triggered": result.get("hard_timeout_triggered"),
            "hard_timeout_seconds": hard_timeout.get("timeout_seconds"),
            "hard_timeout_worker_status": hard_timeout.get("worker_status"),
            "latency_ms": result.get("latency_ms"),
            "ttft_ms": result.get("ttft_ms"),
            "intent": trace.get("intent"),
            "route": trace.get("route"),
            "planned_agents": "|".join(_as_list(trace.get("planned_agents"))),
            "executed_agents": "|".join(_as_list(trace.get("executed_agents"))),
            "planned_tools": "|".join(_as_list(trace.get("planned_tools"))),
            "executed_tools": "|".join(_as_list(trace.get("executed_tools"))),
            "selected_agents": "|".join(_as_list(trace.get("selected_agents"))),
            "selected_tools": "|".join(_as_list(trace.get("selected_tools"))),
            "expected_tools": "|".join(_as_list(metrics.get("expected_tools") or [])),
            "tool_selection_accuracy": metrics.get("tool_selection_accuracy"),
            "intent_correct": metrics.get("intent_correct"),
            "route_correct": metrics.get("route_correct"),
            "agents_correct": metrics.get("agents_correct"),
            "hard_constraint_applicable_count": metrics.get("hard_constraint_applicable_count"),
            "hard_constraint_passed_count": metrics.get("hard_constraint_passed_count"),
            "hard_constraint_failed_count": metrics.get("hard_constraint_failed_count"),
            "hard_constraints_all_satisfied": metrics.get("hard_constraints_all_satisfied"),
            "hcsr": metrics.get("hcsr"),
            "stsr": metrics.get("stsr"),
            "evaluation_hcsr": metrics.get("evaluation_hcsr"),
            "itcsr": metrics.get("itcsr"),
            "itcsr_applicable_count": metrics.get("itcsr_applicable_count"),
            "itcsr_passed_count": metrics.get("itcsr_passed_count"),
            "itcsr_failed_count": metrics.get("itcsr_failed_count"),
            "evaluation_failed_rule_count": metrics.get("evaluation_failed_rule_count"),
            "evaluation_failed_rule_ids": "|".join(_as_list(metrics.get("evaluation_failed_rule_ids"))),
            "agent_set_exact_match": metrics.get("agent_set_exact_match"),
            "necessary_agent_coverage": metrics.get("necessary_agent_coverage"),
            "agent_selection_f1": metrics.get("agent_selection_f1"),
            "extra_agent_count": metrics.get("extra_agent_count"),
            "duplicate_agent_count": metrics.get("duplicate_agent_count"),
            "planned_actual_agent_consistency": metrics.get("planned_actual_agent_consistency"),
            "agent_execution_success_rate": metrics.get("agent_execution_success_rate"),
            "tool_set_exact_match": metrics.get("tool_set_exact_match"),
            "necessary_tool_coverage": metrics.get("necessary_tool_coverage"),
            "tool_selection_f1": metrics.get("tool_selection_f1"),
            "extra_tool_count": metrics.get("extra_tool_count"),
            "duplicate_tool_count": metrics.get("duplicate_tool_count"),
            "forbidden_tool_call_count": metrics.get("forbidden_tool_call_count"),
            "planned_actual_tool_consistency": metrics.get("planned_actual_tool_consistency"),
            "tool_call_success_rate": metrics.get("tool_call_success_rate"),
            "tool_failure_count": metrics.get("tool_failure_count"),
            "tool_failure_types": "|".join(_as_list(metrics.get("tool_failure_types"))),
            "total_tokens": metrics.get("total_tokens"),
            "estimated_cost": metrics.get("estimated_cost"),
            "standardized_estimated_cost": metrics.get("standardized_estimated_cost"),
            "actual_cost": metrics.get("actual_cost"),
            "cost_per_success": metrics.get("cost_per_success"),
            "m3_scheduler_name": metrics.get("m3_scheduler_name"),
            "m3_task_type": metrics.get("m3_task_type"),
            "m3_clarification_required": metrics.get("m3_clarification_required"),
            "m3_clarification_field_count": metrics.get("m3_clarification_field_count"),
            "m3_decision_reasons": "|".join(_as_list(metrics.get("m3_decision_reasons"))),
            "m3_planned_agents": "|".join(_as_list(metrics.get("m3_planned_agents"))),
            "m3_reused_agents": "|".join(_as_list(metrics.get("m3_reused_agents"))),
            "m3_invalidated_agents": "|".join(_as_list(metrics.get("m3_invalidated_agents"))),
            "m3_planned_tools": "|".join(_as_list(metrics.get("m3_planned_tools"))),
            "m3_reused_tool_results": "|".join(_as_list(metrics.get("m3_reused_tool_results"))),
            "m3_missing_reused_tool_results": "|".join(
                _as_list(metrics.get("m3_missing_reused_tool_results"))
            ),
            "m3_m2_reference_agent_count": metrics.get("m3_m2_reference_agent_count"),
            "m3_m2_reference_tool_count": metrics.get("m3_m2_reference_tool_count"),
            "m3_planned_agent_count": metrics.get("m3_planned_agent_count"),
            "m3_executed_agent_count": metrics.get("m3_executed_agent_count"),
            "m3_reused_agent_count": metrics.get("m3_reused_agent_count"),
            "m3_invalidated_agent_count": metrics.get("m3_invalidated_agent_count"),
            "m3_planned_tool_count": metrics.get("m3_planned_tool_count"),
            "m3_executed_tool_count": metrics.get("m3_executed_tool_count"),
            "m3_expected_reused_tool_count": metrics.get("m3_expected_reused_tool_count"),
            "m3_reused_tool_result_count": metrics.get("m3_reused_tool_result_count"),
            "m3_missing_reused_tool_result_count": metrics.get("m3_missing_reused_tool_result_count"),
            "m3_agent_reuse_rate": metrics.get("m3_agent_reuse_rate"),
            "m3_tool_reuse_rate": metrics.get("m3_tool_reuse_rate"),
            "m3_reuse_hit_rate": metrics.get("m3_reuse_hit_rate"),
            "m3_agent_call_savings_vs_m2": metrics.get("m3_agent_call_savings_vs_m2"),
            "m3_tool_call_savings_vs_m2": metrics.get("m3_tool_call_savings_vs_m2"),
            "m3_agent_call_reduction_rate_vs_m2": metrics.get("m3_agent_call_reduction_rate_vs_m2"),
            "m3_tool_call_reduction_rate_vs_m2": metrics.get("m3_tool_call_reduction_rate_vs_m2"),
            "run_audit_schema_version": run_audit.get("schema_version"),
            "planned_agent_count": audit_metrics.get("planned_agent_count"),
            "used_agent_count": audit_metrics.get("used_agent_count"),
            "executed_agent_count": audit_metrics.get("executed_agent_count"),
            "agent_call_count": audit_metrics.get("agent_call_count"),
            "successful_agent_call_count": audit_metrics.get("successful_agent_call_count"),
            "failed_agent_call_count": audit_metrics.get("failed_agent_call_count"),
            "duplicate_agent_call_count": audit_metrics.get("duplicate_agent_call_count"),
            "planned_executed_agent_coverage": audit_metrics.get("planned_executed_agent_coverage"),
            "planned_tool_count": audit_metrics.get("planned_tool_count"),
            "called_tool_count": audit_metrics.get("called_tool_count"),
            "executed_tool_count": audit_metrics.get("executed_tool_count"),
            "successful_tool_call_count": audit_metrics.get("successful_tool_call_count"),
            "failed_tool_call_count": audit_metrics.get("failed_tool_call_count"),
            "duplicate_tool_call_count": audit_metrics.get("duplicate_tool_call_count"),
            "planned_executed_tool_coverage": audit_metrics.get("planned_executed_tool_coverage"),
            "llm_call_count": audit_metrics.get("llm_call_count"),
            "llm_retry_attempt_count": audit_metrics.get("llm_retry_attempt_count"),
            "llm_retry_count": audit_metrics.get("llm_retry_count"),
            "llm_retry_error_count": audit_metrics.get("llm_retry_error_count"),
            "agent_llm_call_count": audit_metrics.get("agent_llm_call_count"),
            "api_call_count": audit_metrics.get("api_call_count"),
            "prompt_tokens": audit_metrics.get("prompt_tokens"),
            "completion_tokens": audit_metrics.get("completion_tokens"),
            "agent_prompt_tokens": audit_metrics.get("agent_prompt_tokens"),
            "agent_completion_tokens": audit_metrics.get("agent_completion_tokens"),
            "agent_total_tokens": audit_metrics.get("agent_total_tokens"),
            "audit_standardized_estimated_cost": audit_metrics.get("standardized_estimated_cost"),
            "audit_actual_cost": audit_metrics.get("actual_cost"),
            "llm_total_duration_ms": audit_metrics.get("llm_total_duration_ms"),
            "agent_total_duration_ms": audit_metrics.get("agent_total_duration_ms"),
            "tool_total_duration_ms": audit_metrics.get("tool_total_duration_ms"),
            "api_total_duration_ms": audit_metrics.get("api_total_duration_ms"),
            "stage_total_duration_ms": audit_metrics.get("stage_total_duration_ms"),
            "input_hash": result.get("input_hash"),
            "result_hash": result.get("result_hash"),
            "offline_data_sha256": (result.get("offline_data") or {}).get("combined_sha256"),
            "trace_file": result.get("trace_file"),
            "output_preview": output_text[:500],
            "error": result.get("error") or "",
        }

    def _normalize_method(self, method: ExperimentMethod) -> ExperimentMethod:
        normalized = str(method or "").strip().lower()
        normalized = self.METHOD_ALIASES.get(normalized, normalized)
        if normalized not in self.METHODS:
            raise ValueError(f"method must be one of {', '.join(self.METHODS)}")
        return normalized

    def _trace_files(self) -> set[Path]:
        if not self.trace_dir.exists():
            return set()
        return set(self.trace_dir.glob("*.jsonl"))

    def _load_trace_by_request_id(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Load only the trace whose persisted request_id exactly matches."""
        for path in sorted(self._trace_files()):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
                if not lines:
                    continue
                record = json.loads(lines[0])
            except (OSError, json.JSONDecodeError):
                continue
            if record.get("request_id") != request_id:
                continue
            record["trace_file"] = str(path)
            return record
        return None


def _input_dict_to_text(data: Dict[str, Any]) -> str:
    destination = data.get("destination") or data.get("city") or data.get("place")
    duration = data.get("duration") or data.get("duration_days") or data.get("days")
    budget = data.get("budget") or data.get("budget_amount") or data.get("budget_level")
    parts = []
    if destination:
        parts.append(f"目的地{destination}")
    if duration:
        parts.append(f"{duration}天")
    if budget:
        parts.append(f"预算{budget}")
    if not parts:
        return json.dumps(data, ensure_ascii=False)
    return "帮我规划" + "".join(str(part) for part in parts) + "旅游"


def _budget_gold_manifest_summary() -> Dict[str, Any]:
    path = DEFAULT_CTP100_BUDGET_GOLD_PATH
    try:
        document = validate_budget_gold(path)
    except BudgetGoldError as exc:
        return {
            "available": False,
            "path": path.as_posix(),
            "error": str(exc),
        }
    except Exception as exc:  # pragma: no cover - manifest should preserve diagnostics
        return {
            "available": False,
            "path": path.as_posix(),
            "error": str(exc),
        }
    return {
        "available": True,
        "path": str(document.get("path") or path.as_posix()),
        "file_sha256": _raw_file_sha256(path),
        "hash_strategy": "raw_file_sha256_v1",
        "schema_version": document.get("schema_version"),
        "gold_status": document.get("gold_status"),
        "review_status": document.get("review_status"),
        "source_dataset_sha256": document.get("source_dataset_sha256"),
        "budget_policy_version": document.get("budget_policy_version"),
        "summary": document.get("summary") or {},
        "artifact_hashes": document.get("artifact_hashes") or {},
        "visible_to_generation": False,
        "used_by": "independent_evaluator_only",
    }


def _raw_file_sha256(path: Path) -> Optional[str]:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _slots_from_mapping(data: Dict[str, Any]) -> Dict[str, Any]:
    slots: Dict[str, Any] = {}
    mapping = {
        "city": "destination",
        "destination": "destination",
        "days": "duration",
        "duration": "duration",
        "duration_days": "duration",
        "budget": "budget",
        "budget_amount": "budget",
        "budget_level": "budget_level",
        "budget_basis": "budget_basis",
        "requested_budget_scope": "requested_budget_scope",
        "budget_scope": "budget_scope",
        "intercity_transport_included": "intercity_transport_included",
        "mandatory_budget_disclaimer": "mandatory_budget_disclaimer",
        "hotel_level": "hotel_level",
        "accommodation_level": "hotel_level",
        "lodging_level": "hotel_level",
        "food_level": "food_level",
        "dining_level": "food_level",
        "intercity_transport_mode": "intercity_transport_mode",
        "intercity_seat_class": "intercity_seat_class",
        "num_travelers": "num_travelers",
        "people_count": "people_count",
        "traveler_type": "traveler_type",
        "traveler_group": "traveler_group",
        "start_date": "start_date",
        "date": "start_date",
        "preferences": "preferences",
        "special_requirements": "special_requirements",
        "weather_scenario": "weather_scenario",
        "scenario_type": "weather_scenario",
    }
    for source, target in mapping.items():
        if source in data and data[source] is not None:
            slots[target] = data[source]
    return slots


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, tuple | set):
        return [str(item) for item in value if item]
    return [str(value)]


def _benchmark_structure_summary(document: Any) -> Dict[str, Any]:
    cases = _benchmark_cases_for_summary(document)
    scenario_count = sum(
        1 for case in cases if isinstance(case.get("turns"), list) and case.get("turns")
    )
    turn_count = sum(_case_turn_count_for_summary(case) for case in cases)
    return {
        "case_count": len(cases),
        "single_turn_case_count": len(cases) - scenario_count,
        "scenario_case_count": scenario_count,
        "total_turn_count": turn_count,
        "statistical_unit": "evaluation_unit_id",
        "multi_turn_quality_scope": "target_turn_only",
        "multi_turn_state_policy": "method_local_previous_state_from_prior_turn_output",
    }


def _benchmark_cases_for_summary(document: Any) -> List[Dict[str, Any]]:
    if isinstance(document, list):
        return [item for item in document if isinstance(item, dict)]
    if isinstance(document, dict) and isinstance(document.get("cases"), list):
        return [item for item in document["cases"] if isinstance(item, dict)]
    return []


def _scenario_turn_is_target(
    turn_case: Dict[str, Any],
    turn_index: int,
    turn_count: int,
) -> bool:
    for key in ("target_turn", "evaluate_turn", "is_target_turn"):
        if key in turn_case:
            return _bool_value(turn_case.get(key))
    return turn_count <= 1 or turn_index == turn_count - 1


def _case_turn_count_for_summary(case: Dict[str, Any]) -> int:
    turns = case.get("turns")
    if isinstance(turns, list) and turns:
        return len(turns)
    return 1


def _ordered_unique(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _ordered_unique_ints(values: Iterable[int]) -> List[int]:
    seen: set[int] = set()
    result: List[int] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _safe_ratio(numerator: int | float, denominator: int | float) -> Optional[float]:
    if not denominator:
        return None
    return round(float(numerator) / float(denominator), 4)


def _bool_value(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _nested_mapping(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _nested_get(value: Any, keys: Iterable[str]) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _nested_value(value: Any, *keys: str) -> Any:
    return _nested_mapping(value, *keys)


def _first_positive_int(*values: Any, default: int) -> int:
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return default


def _number_word_to_int(value: Any) -> Optional[int]:
    text = str(value or "").strip().casefold()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    return {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "一": 1,
        "二": 2,
        "两": 2,
        "俩": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }.get(text)


def _int_list(value: Any) -> List[int]:
    if isinstance(value, list | tuple | set):
        return _ordered_unique_ints(
            parsed
            for item in value
            for parsed in [_first_positive_int(item, default=0)]
            if parsed > 0
        )
    parsed = _first_positive_int(value, default=0)
    return [parsed] if parsed > 0 else []


def _days_from_weather_scenario_text(value: Any) -> List[int]:
    text = str(value or "").replace("-", "_").casefold()
    days = [
        int(part)
        for part in text.split("_")
        if part.isdigit() and int(part) > 0
    ]
    return _ordered_unique_ints(days)


def _json_tool_result(value: Any) -> str:
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    return json.dumps(value, ensure_ascii=False, default=str)


def _jsonable_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return str(value)


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _session_component(value: Any) -> str:
    text = _optional_text(value) or "run"
    safe = "".join(char if char.isalnum() or char in "_.-" else "_" for char in text)
    return safe.strip("._-") or "run"


def _validate_repeats(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("repeats must be a positive integer")
    try:
        repeats = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("repeats must be a positive integer") from exc
    if repeats < 1:
        raise ValueError("repeats must be a positive integer")
    return repeats


def _validate_repeat_index(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("repeat_index must be a non-negative integer")
    try:
        repeat_index = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("repeat_index must be a non-negative integer") from exc
    if repeat_index < 0:
        raise ValueError("repeat_index must be a non-negative integer")
    return repeat_index


def _environment_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


def _environment_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return int(default)
    try:
        return int(raw)
    except ValueError:
        return int(default)


def _experiment_llm_call_timeout_seconds() -> float:
    explicit = os.getenv(EXPERIMENT_LLM_CALL_TIMEOUT_ENV)
    if explicit is not None:
        try:
            value = float(explicit)
        except ValueError:
            value = 0.0
        if value > 0:
            return value
    request_timeout = max(
        1.0,
        float(_environment_int("LLM_TIMEOUT", settings.llm.timeout)),
    )
    max_attempts = max(
        1,
        _environment_int("LLM_RETRY_MAX_ATTEMPTS", settings.llm.retry_max_attempts),
    )
    return request_timeout * float(max_attempts) + 5.0


def _experiment_result_timeout_seconds() -> float:
    explicit = os.getenv("EXPERIMENT_RESULT_TIMEOUT_SECONDS")
    if explicit is not None:
        try:
            value = float(explicit)
        except ValueError:
            value = 0.0
        if value > 0:
            return value
    return max(120.0, _experiment_llm_call_timeout_seconds() * 8.0)


def _agent_llm_transport_error_reason(exc: BaseException) -> Optional[str]:
    """Classify recoverable transport failures during business-agent decisions.

    M2/M3 first collect deterministic offline tool evidence and then ask a
    business-agent LLM to summarize/select from that evidence.  If the LLM
    transport layer fails after the evidence is already available, the existing
    evidence normalizer may still produce a valid auditable decision.  Ordinary
    program errors intentionally return ``None`` so they are not hidden.
    """
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
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return "network_timeout"

    class_name = exc.__class__.__name__.casefold()
    message = str(exc).casefold()
    if "timeout" in class_name or "timed out" in message:
        return "network_timeout"
    if "connection" in class_name or "transport" in class_name:
        return "network_connection"
    if "connection error" in message or "network" in message:
        return "network_connection"
    return None


def _environment_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _repair_unquoted_json_arithmetic_values(raw_text: str) -> tuple[str, int]:
    """Repair simple numeric expressions emitted as JSON number values.

    The repair is intentionally narrow: it only handles values such as
    ``"amount": 3 * 120`` and refuses names, strings, function calls, and any
    non-arithmetic syntax.  This preserves the strict structured-output
    contract while avoiding a whole-row engineering failure for a trivial
    model formatting mistake.
    """
    repair_count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal repair_count
        value = _safe_arithmetic_value(match.group("expr"))
        if value is None:
            return match.group(0)
        repair_count += 1
        return f"{match.group('prefix')}{_json_number_literal(value)}{match.group('suffix')}"

    repaired = _JSON_ARITHMETIC_VALUE_PATTERN.sub(replace, raw_text)
    return repaired, repair_count


def _safe_arithmetic_value(expression: str) -> Optional[float]:
    try:
        node = ast.parse(expression, mode="eval")
    except SyntaxError:
        return None
    try:
        value = _eval_arithmetic_node(node.body)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _eval_arithmetic_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_arithmetic_node(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and isinstance(
        node.op,
        (ast.Add, ast.Sub, ast.Mult, ast.Div),
    ):
        left = _eval_arithmetic_node(node.left)
        right = _eval_arithmetic_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        return left / right
    raise ValueError("unsupported arithmetic expression")


def _json_number_literal(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return format(round(value, 4), "g")


def _environment_text(name: str) -> Optional[str]:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip().lower()
    return value or None


def _experiment_result_hard_timeout_seconds() -> Optional[float]:
    raw = os.getenv(EXPERIMENT_RESULT_HARD_TIMEOUT_ENV)
    if raw is None or not str(raw).strip():
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _truncate_text(value: Any, limit: int = 4000) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "...<truncated>"


def _llm_provider_from_base_url(base_url: Any) -> str:
    return llm_provider_from_base_url(base_url)


def _git_commit() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return completed.stdout.strip() or "unknown"


def _git_status_short() -> List[str]:
    try:
        completed = subprocess.run(
            ["git", "status", "--short"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return completed.stdout.splitlines()


def _optional_equal(expected: Any, actual: Any) -> Optional[bool]:
    if expected is None:
        return None
    return str(expected) == str(actual)


def _float_or_none(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _average_numeric(values: Iterable[Any]) -> Optional[float]:
    numbers = [float(value) for value in values if isinstance(value, (int, float))]
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 2)


def _extract_final_content(raw: Any) -> str:
    if isinstance(raw, dict):
        return str(raw.get("content") or "")
    if not isinstance(raw, str):
        return ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return str(parsed.get("content") or "")


async def _maybe_await(value: Awaitable[Any] | Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


@contextmanager
def _temporary_env(values: Dict[str, str]):
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            os.environ[key] = str(value)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


_experiment_runner: Optional[ExperimentRunner] = None


def get_experiment_runner() -> ExperimentRunner:
    """Get the global experiment runner instance."""
    global _experiment_runner
    if _experiment_runner is None:
        _experiment_runner = ExperimentRunner()
    return _experiment_runner
