"""
Experiment runner for thesis-style benchmark execution.

The runner keeps the original metric collection helpers, and adds a unified
entry point for running the same case through four comparable methods:
llm_direct, single_agent, fixed_multi_agent, and adaptive_multi_agent.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import os
import random
import subprocess
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

from app.core.config import settings
from app.core.experiment_method_contract import (
    EXPERIMENT_METHODS,
    build_method_fairness_contract,
    method_fairness_contract_hash,
    validate_method_fairness_contract,
)
from app.core.experiment_method_input import build_generation_case
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
    validate_fixed_data_snapshot,
)
from app.core.goal_state_scheduler import (
    RESULT_DEPENDENCIES,
    build_goal_state_result_fingerprints,
    build_goal_state_ticket,
    is_goal_state_agent_reusable,
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
from app.core.llm.client import LLMMessage, ToolDefinition, get_llm
from app.core.llm_costing import COSTING_SCHEMA_VERSION, build_price_snapshot
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
RESEARCH_AGENT_PROMPT_VERSION = "ctp-research-agent-prompts-v1"
STRUCTURED_LLM_OUTPUT_PROMPT_VERSION = "ctp-structured-llm-output-prompts-v1"
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
}


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
    ) -> None:
        self.trace_dir = Path(trace_dir)
        self.output_dir = Path(output_dir)
        self.method_handlers = method_handlers or {}
        self.app_factory = app_factory
        self.llm_factory = llm_factory or get_llm
        self.repeats = _validate_repeats(repeats)
        self.run_id = str(run_id or f"run_{uuid.uuid4().hex[:12]}")
        self.repeat_index = _validate_repeat_index(repeat_index)
        self.system_variant = _optional_text(system_variant)
        self.model_config_name = _optional_text(model_config_name) or "default"
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
    ) -> Dict[str, Any]:
        """Asynchronously run one case through one method."""
        method = self._normalize_method(method)
        normalized_case = self._normalize_case(case)
        case_id = normalized_case["case_id"]
        request_id = f"{case_id}_{method}_{uuid.uuid4().hex[:8]}"
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
                output = await self._dispatch_method(generation_case, method, request_id)
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
    ) -> List[Dict[str, Any]]:
        benchmark_file = Path(benchmark_path)
        cases = self.load_benchmark(benchmark_file)
        selected_methods = [
            self._normalize_method(method) for method in (methods or self.METHODS)
        ]
        validate_method_fairness_contract(selected_methods)
        effective_repeats = self.repeats if repeats is None else _validate_repeats(repeats)
        effective_run_id = str(run_id or self.run_id)

        results: List[Dict[str, Any]] = []
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
                        results.extend(
                            await self._arun_scenario_case(
                                case,
                                method=method,
                                run_id=effective_run_id,
                                repeat_index=repeat_index,
                                system_variant=system_variant,
                                model_config_name=model_config_name,
                            )
                        )
                    continue

                for method in case_methods:
                    results.append(
                        await self.arun(
                            case,
                            method=method,
                            run_id=effective_run_id,
                            repeat_index=repeat_index,
                            system_variant=system_variant,
                            model_config_name=model_config_name,
                        )
                    )

        benchmark_output_dir = self._benchmark_output_dir(effective_run_id)
        if csv_path is None:
            csv_path = benchmark_output_dir / "benchmark_results.csv"
        if json_path is None:
            json_path = benchmark_output_dir / "benchmark_results.json"
        if summary_path is None:
            summary_path = benchmark_output_dir / "evaluation_summary.json"
        if paper_tables_path is None:
            paper_tables_path = benchmark_output_dir / "paper_tables.md"
        if manifest_path is None:
            manifest_path = benchmark_output_dir / "experiment_manifest.json"
        self.export_csv(results, csv_path)
        self.export_json(results, json_path)
        summary = self.export_evaluation_summary(results, summary_path)
        self.export_paper_tables(summary, paper_tables_path)
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
            },
        )
        return results

    async def _arun_scenario_case(
        self,
        scenario: Dict[str, Any],
        *,
        method: ExperimentMethod,
        run_id: str,
        repeat_index: int,
        system_variant: Optional[str],
        model_config_name: Optional[str],
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
            )
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
    ) -> None:
        result["scenario_id"] = scenario_id
        result["turn_id"] = turn_id
        result["turn_index"] = turn_index
        result["scenario_turn_count"] = turn_count
        result["target_turn"] = target_turn

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
        model = os.getenv("LLM_MODEL") or settings.llm.model
        temperature = _environment_float("LLM_TEMPERATURE", settings.llm.temperature)
        resolved_system_variant = _optional_text(system_variant) or self.system_variant
        resolved_model_config = (
            _optional_text(model_config_name) or self.model_config_name
        )
        mock_pricing = "fake" in str(model).lower() or "offline" in str(resolved_model_config).lower()
        price_snapshot = build_price_snapshot(
            provider="experiment_llm",
            model=model,
            mock=mock_pricing,
        )
        rule_catalog = load_rule_catalog()
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
            "model": str(model),
            "temperature": temperature,
            "cache_enabled": not cache_disabled,
            "cache_disabled": cache_disabled,
            "strict_mode": strict_mode,
            "model_config": {
                "name": resolved_model_config,
                "model": str(model),
                "temperature": temperature,
            },
            "prompt_versions": {
                "structured_llm_output": STRUCTURED_LLM_OUTPUT_PROMPT_VERSION,
                "research_agent": RESEARCH_AGENT_PROMPT_VERSION,
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
            },
            "evaluation": {
                "schema_version": EVALUATION_SCHEMA_VERSION,
                "summary_schema_version": EVALUATION_SUMMARY_SCHEMA_VERSION,
                "catalog_id": rule_catalog.get("catalog_id"),
                "catalog_path": DEFAULT_RULE_CATALOG_PATH.as_posix(),
                "catalog_sha256": canonical_json_sha256(rule_catalog),
                "catalog_hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
                "guards": rule_catalog.get("evaluator_guards") or [],
            },
            "results": {
                key: Path(value).as_posix()
                for key, value in (result_paths or {}).items()
            },
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
            "case_id",
            "method",
            "request_id",
            "run_id",
            "repeat_index",
            "system_variant",
            "model_config_name",
            "evaluation_mode",
            "status",
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
            try:
                with trace_component("single_agent", agent_name="single_agent"):
                    for _ in range(self.SINGLE_AGENT_MAX_TOOL_ROUNDS):
                        response = await llm.chat(messages, tools=definitions)
                        if not response.tool_calls:
                            usage = getattr(response, "usage", None) or {}
                            model_payload, json_error = self._parse_strict_structured_llm_json(
                                response.content
                            )
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
            "If information is unavailable, use null or an empty list/object in the correct field."
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
        try:
            parsed = json.loads(raw_content.strip())
        except json.JSONDecodeError as exc:
            return None, f"structured LLM output is not strict JSON: {exc.msg}"
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
        final_status = (
            "failed"
            if failure_items or str(execution_status or "").lower() == "failed" or model_status == "failed"
            else model_status
        )
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

    async def _run_fixed_multi_agent(self, case: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        execution_case = self._case_for_fixed_multi_agent(case)
        agents = (
            ["attraction", "weather", "itinerary", "budget"]
            if self._is_tourism_case(execution_case)
            else []
        )
        tools = list(GENERATION_TOOL_NAMES) if agents else []
        return await self._run_research_multi_agent(
            case=execution_case,
            request_id=request_id,
            method="fixed_multi_agent",
            planned_agents=agents,
            planned_tools=tools,
        )

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
                if scheduler_metadata is not None:
                    set_trace_scheduler_info(scheduler_metadata)

            reused_agent_outputs = self._reused_research_agent_outputs(
                previous_state=self._goal_state_previous_state(case),
                reused_agents=self._actual_reused_agents_from_scheduler(scheduler_metadata),
            )
            tool_results, agent_outputs = await self._execute_research_tool_plan(
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
                scheduler_metadata=scheduler_metadata,
                called_tools=list(trace.tool_calls) if trace is not None else [],
            )
            result_scheduler = _nested_mapping(result, "metadata", "adaptive_scheduler")
            if isinstance(result_scheduler, dict):
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
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        catalog = {tool.name: tool for tool in generation_tools()}
        executor = ToolExecutor(tools=catalog)
        tool_results: Dict[str, Any] = dict(initial_tool_results or {})
        agent_outputs: Dict[str, Any] = dict(initial_agent_outputs or {})
        planned_tool_set = set(tools)
        failed_agents: set[str] = set()

        for agent_name in agents:
            blocked_by = self._blocked_upstream_agents(
                agent_name,
                tool_results,
                failed_agents,
                scheduler_metadata=scheduler_metadata,
            )
            if blocked_by:
                mark_trace_status(
                    "failed",
                    error=(
                        f"{agent_name} skipped because upstream result is unavailable: "
                        f"{', '.join(blocked_by)}"
                    ),
                )
                failed_agents.add(agent_name)
                continue
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
                        arguments = self._research_tool_arguments(tool_name, case, tool_results)
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
        return tool_results, agent_outputs

    def _blocked_upstream_agents(
        self,
        agent_name: str,
        tool_results: Dict[str, Any],
        failed_agents: set[str],
        *,
        scheduler_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        blocked: List[str] = []
        dependencies = RESULT_DEPENDENCIES.get(agent_name, ())
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
        return True

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
            return self._is_successful_reusable_tool_result(
                tool_results.get("weather_query")
            ) and bool(self._tool_data(tool_results.get("weather_query")).get("daily_weather"))
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

    def _evidence_tools_for_research_agent(self, agent_name: str) -> List[str]:
        mapping = {
            "attraction": ["poi_search"],
            "weather": ["weather_query"],
            "itinerary": ["poi_search", "weather_query"],
            "budget": ["poi_search", "budget_calculator"],
        }
        return mapping.get(agent_name, [])

    async def _run_research_agent_llm(
        self,
        *,
        agent_name: str,
        case: Dict[str, Any],
        tool_results: Dict[str, Any],
        upstream_agent_outputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        llm = self.llm_factory()
        messages = self._research_agent_prompt_messages(
            agent_name=agent_name,
            case=case,
            tool_results=tool_results,
            upstream_agent_outputs=upstream_agent_outputs,
        )
        started = time.perf_counter()
        response = await llm.chat(messages)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        usage = dict(getattr(response, "usage", None) or {})
        content = str(getattr(response, "content", "") or "")
        decision, parse_error = self._parse_research_agent_decision(content)
        validation_errors = self._research_agent_decision_validation_errors(
            agent_name=agent_name,
            decision=decision,
            case=case,
            tool_results=tool_results,
        )
        decision_errors = [
            error
            for error in [parse_error, *validation_errors]
            if error
        ]
        decision_valid = not decision_errors
        status = "completed" if decision_valid else "failed"
        return {
            "schema_version": RESEARCH_AGENT_OUTPUT_SCHEMA_VERSION,
            "agent_name": agent_name,
            "status": status,
            "success": decision_valid,
            "reused": False,
            "prompt_version": RESEARCH_AGENT_PROMPT_VERSION,
            "evidence_tools": self._evidence_tools_for_research_agent(agent_name),
            "upstream_agents": list(RESULT_DEPENDENCIES.get(agent_name, ())),
            "content": content,
            "decision_schema_version": RESEARCH_AGENT_DECISION_SCHEMA_VERSION,
            "decision": _jsonable_value(decision or {}),
            "decision_parse_status": "passed" if parse_error is None else "failed",
            "decision_validation_status": "passed" if not validation_errors else "failed",
            "decision_errors": decision_errors,
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
        day_count = len(self._weather_day_items(weather))
        risk_days = _int_list(decisions.get("risk_days"))
        errors: List[str] = []
        if day_count and any(day < 1 or day > day_count for day in risk_days):
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
        evidence_ids = set(self._poi_ids_from_result(tool_results.get("poi_search")))
        trip_days = self._case_duration(case)
        errors: List[str] = []
        seen_days: set[int] = set()
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
            if evidence_ids and not poi_ids:
                errors.append("daily_itinerary items must include attraction_poi_ids")
            unknown = sorted(set(poi_ids) - evidence_ids)
            if unknown:
                errors.append(f"daily_itinerary references non-evidence POI ids: {unknown}")
        if len(seen_days) < trip_days:
            errors.append("daily_itinerary must cover every trip day")
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

    def _research_agent_prompt_messages(
        self,
        *,
        agent_name: str,
        case: Dict[str, Any],
        tool_results: Dict[str, Any],
        upstream_agent_outputs: Dict[str, Any],
    ) -> List[LLMMessage]:
        role = {
            "attraction": "Attraction Agent: assess POI evidence and select reliable attraction evidence.",
            "weather": "Weather Agent: assess weather evidence and identify travel risks.",
            "itinerary": "Itinerary Agent: combine attraction and weather evidence into a day-level plan.",
            "budget": "Budget Agent: assess budget evidence and explain cost feasibility.",
        }.get(agent_name, f"{agent_name} Agent")
        context = self._research_agent_prompt_context(
            agent_name=agent_name,
            case=case,
            tool_results=tool_results,
            upstream_agent_outputs=upstream_agent_outputs,
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
    ) -> Dict[str, Any]:
        evidence_tools = self._evidence_tools_for_research_agent(agent_name)
        upstream_agents = list(RESULT_DEPENDENCIES.get(agent_name, ()))
        return {
            "prompt_version": RESEARCH_AGENT_PROMPT_VERSION,
            "agent_name": agent_name,
            "user_request": str(case.get("user_input") or ""),
            "task_slots": {
                "city": self._case_city(case),
                "duration_days": self._case_duration(case),
                "start_date": self._case_start_date(case),
                "people_count": self._case_traveler_count(case),
                "preferences": self._case_preferences(case),
                "budget_level": self._case_budget_level(case),
            },
            "tool_evidence": {
                tool_name: self._compact_prompt_value(tool_results.get(tool_name))
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
                    self._attractions_from_tool_result(tool_results.get("poi_search")),
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
            if not is_goal_state_agent_reusable(
                agent_name,
                current_slots=current_slots,
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
    ) -> List[str]:
        actual: List[str] = []
        reused_tool_set = set(reused_tool_results)
        for agent_name in expected_agents:
            if not is_goal_state_agent_reusable(
                agent_name,
                current_slots=current_slots,
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
                "decision_parse_status": output.get("decision_parse_status"),
                "decision_validation_status": output.get("decision_validation_status"),
                "decision_error_count": len(output.get("decision_errors") or []),
                "has_applicable_decision": bool(self._agent_decision(str(agent_name), agent_outputs)),
            }
        return audit

    def _attractions_for_research_output(
        self,
        *,
        tool_results: Dict[str, Any],
        agent_outputs: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        tool_attractions = self._attractions_from_tool_result(tool_results.get("poi_search"))
        selected_ids = _as_list(
            self._agent_decision_payload("attraction", agent_outputs).get("selected_poi_ids")
        )
        if not selected_ids:
            return tool_attractions
        by_id = {
            str(item.get("poi_id")): item
            for item in tool_attractions
            if item.get("poi_id")
        }
        selected = [
            {
                **_jsonable_value(by_id[poi_id]),
                "agent_selected": True,
                "agent_decision_source": "attraction",
                "agent_rank": rank,
            }
            for rank, poi_id in enumerate(selected_ids, start=1)
            if poi_id in by_id
        ]
        return selected or tool_attractions

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

    def _daily_itinerary_for_research_output(
        self,
        *,
        trip_days: int,
        attractions: List[Dict[str, Any]],
        weather: Dict[str, Any],
        planned_agents: List[str],
        reused_agents: List[str],
        agent_outputs: Dict[str, Any],
        previous_state: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if (
            "itinerary" in planned_agents
            and self._agent_output_available("itinerary", agent_outputs)
            and attractions
            and weather
        ):
            agent_itinerary = self._daily_itinerary_from_agent_decision(
                trip_days=trip_days,
                attractions=attractions,
                agent_outputs=agent_outputs,
            )
            return agent_itinerary or self._build_daily_itinerary(trip_days, attractions)
        if "itinerary" in reused_agents and self._agent_output_available(
            "itinerary",
            agent_outputs,
        ):
            previous_itinerary = self._previous_daily_itinerary_from_state(previous_state)
            return previous_itinerary or self._daily_itinerary_from_agent_decision(
                trip_days=trip_days,
                attractions=attractions,
                agent_outputs=agent_outputs,
            )
        return []

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
        for item in daily:
            if not isinstance(item, dict):
                continue
            day = _first_positive_int(item.get("day"), item.get("day_index"), default=0)
            if day < 1 or day > trip_days:
                continue
            poi_ids = _as_list(item.get("attraction_poi_ids"))
            selected = [by_id[poi_id] for poi_id in poi_ids if poi_id in by_id]
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
            return {
                "city": city,
                "people_count": self._case_traveler_count(case),
                "days": duration,
                "attractions": self._poi_ids_from_result(tool_results.get("poi_search")),
                "spending_level": self._case_budget_level(case),
            }
        return {}

    async def _build_research_method_output(
        self,
        *,
        case: Dict[str, Any],
        method: ExperimentMethod,
        planned_agents: List[str],
        planned_tools: List[str],
        tool_results: Dict[str, Any],
        agent_outputs: Optional[Dict[str, Any]] = None,
        scheduler_metadata: Optional[Dict[str, Any]] = None,
        called_tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        called_tools = called_tools or []
        agent_outputs = agent_outputs or {}
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
        attractions = self._attractions_for_research_output(
            tool_results=tool_results,
            agent_outputs=agent_outputs,
        )
        weather = self._weather_for_research_output(
            tool_results=tool_results,
            agent_outputs=agent_outputs,
        )
        budget = self._budget_for_research_output(
            tool_results=tool_results,
            agent_outputs=agent_outputs,
        )
        trip_days = self._case_duration(case)
        daily_itinerary = self._daily_itinerary_for_research_output(
            trip_days=trip_days,
            attractions=attractions,
            weather=weather,
            planned_agents=planned_agents,
            reused_agents=actual_reused_agents,
            agent_outputs=agent_outputs,
            previous_state=previous_state,
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
        task_type = self._research_output_task_type(case, scheduler_metadata)
        metadata = self._research_method_metadata(
            method=method,
            scheduler_metadata=enriched_scheduler_metadata,
            case=case,
            result_agents=result_agents,
            agent_outputs=agent_outputs,
        )
        execution_status = self._execution_status_from_research_artifacts(
            tool_results=tool_results,
            agent_outputs=agent_outputs,
        )
        raw_snapshot = {
            "task_type": task_type,
            "planned_agents": planned_agents,
            "used_agents": planned_agents,
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
            "used_agents": planned_agents,
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
        response = await llm.chat(
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
            ]
        )
        return response.content

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
        parsed_slots = self._case_slots(case)
        if parsed_slots:
            slots.update(parsed_slots)
        if isinstance(case.get("structured_request"), dict):
            slots.update(_slots_from_mapping(case["structured_request"]))
        if isinstance(case.get("slots"), dict):
            slots.update(case["slots"])
        slots.update(_slots_from_mapping(case))
        if case.get("preferences") is not None:
            slots.setdefault("preferences", case.get("preferences"))
        if case.get("constraints"):
            slots.setdefault("special_requirements", case.get("constraints"))
        return slots

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
            normalized["result_fingerprints"] = build_goal_state_result_fingerprints(
                slots=normalized.get("slots") if isinstance(normalized.get("slots"), dict) else {},
                tool_results=tool_results,
                daily_itinerary=(
                    previous_state.get("daily_itinerary")
                    or _nested_mapping(previous_state, "raw_output", "daily_itinerary")
                    or _nested_mapping(previous_state, "output", "daily_itinerary")
                    or _nested_mapping(previous_state, "output", "raw_output", "daily_itinerary")
                ),
                result_agents=self._previous_result_agents_from_state(previous_state),
            )

        available_results = normalized.get("available_results")
        if not isinstance(available_results, dict):
            normalized["available_results"] = self._infer_available_results_from_previous_state(
                previous_state=previous_state,
                tool_results=tool_results,
            )
        return normalized

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
            metadata["adaptive_scheduler"] = scheduler_metadata
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
        slots = self._case_slots(case)
        return [
            slot
            for slot in ("destination", "start_date", "duration_days")
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
        slots = self._case_slots(case)
        structured = case.get("structured_request") if isinstance(case.get("structured_request"), dict) else {}
        value = (
            slots.get("budget_level")
            or structured.get("budget_level")
            or case.get("budget_level")
        )
        if value:
            return str(value)
        budget = slots.get("budget") or structured.get("budget") or case.get("budget")
        budget = budget or slots.get("budget_amount") or structured.get("budget_amount") or case.get("budget_amount")
        try:
            budget_value = float(budget)
        except (TypeError, ValueError):
            return "medium"
        if budget_value <= 1500:
            return "economy"
        if budget_value >= 6000:
            return "luxury"
        return "medium"

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
        return max(3, min(self._case_duration(case) * 2, 10))

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
            response = await llm.chat(
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

        slots = dict(case.get("slots") or {})
        structured = case.get("structured_request") or {}
        if isinstance(structured, dict):
            slots.update(_slots_from_mapping(structured))
        slots.update(_slots_from_mapping(case))

        expected = dict(case.get("expected") or case.get("standard_answer") or {})
        expected_goal = case.get("expected_goal")
        if isinstance(expected_goal, dict):
            expected.update(expected_goal)
        if "selected_agents" not in expected and "agents" in expected:
            expected["selected_agents"] = expected.get("agents")
        if "selected_tools" not in expected and "tools" in expected:
            expected["selected_tools"] = expected.get("tools")
        evaluation_mode = self._normalize_evaluation_mode(case.get("evaluation_mode"))

        return {
            **case,
            "case_id": case_id,
            "user_input": user_input,
            "slots": slots,
            "constraints": list(case.get("constraints") or structured.get("constraints") or []),
            "expected": expected,
            "evaluation_mode": evaluation_mode,
        }

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
        structured_output: Dict[str, Any],
        raw_output: Any = None,
    ) -> Dict[str, Any]:
        plan = {
            key: value
            for key, value in structured_output.items()
            if key not in {"method", "used_agents", "called_tools", "tool_results", "metadata"}
        }
        tool_results = self._tool_results_for_constraint_checker(
            structured_output=structured_output,
            raw_output=raw_output,
        )
        if isinstance(tool_results, dict) and tool_results:
            plan["tool_results"] = tool_results
        return plan

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
                "days": self._case_duration(case),
                "budget": self._case_budget_limit(case),
            }
        )
        return payload

    def _constraint_payload(self, case: Dict[str, Any]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        budget = self._case_budget_limit(case)
        if budget is not None:
            payload["budget_limit"] = budget
        payload["days"] = self._case_duration(case)
        raw_constraints = case.get("constraints") or []
        if raw_constraints:
            payload["raw_constraints"] = raw_constraints
        text = " ".join([str(case.get("user_input") or ""), *[str(item) for item in raw_constraints]])
        if any(word in text for word in ("雨", "下雨", "天气", "高温", "低温", "室内")):
            payload["weather_adjustment_required"] = True
        expected = case.get("expected") or {}
        if isinstance(expected.get("hard_constraints"), dict):
            payload.update(expected["hard_constraints"])
        return payload

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
        task_type = str(ticket.get("task_type") or "")
        if task_type == "general_chat":
            return 0, 0
        return 4, len(GENERATION_TOOL_NAMES)

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
            "case_id": result.get("case_id"),
            "method": result.get("method"),
            "request_id": result.get("request_id"),
            "run_id": result.get("run_id"),
            "repeat_index": result.get("repeat_index"),
            "system_variant": result.get("system_variant"),
            "model_config_name": result.get("model_config_name"),
            "evaluation_mode": result.get("evaluation_mode"),
            "status": result.get("status"),
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
