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
import subprocess
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

from app.core.config import settings
from app.core.experiment_metrics import (
    CollaborationMode,
    ExperimentContext,
    ExperimentMetrics,
    ReviewModeExperiment,
    build_experiment_metrics,
    build_experiment_record,
    constraint_metrics_from_report,
)
from app.core.fixed_data import fixed_data_file_manifest
from app.core.llm.client import LLMMessage, ToolDefinition, get_llm
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
    set_trace_selected_agents,
    start_agent_run,
    trace_component,
)
from app.schemas.experiment import normalize_experiment_output
from app.tools.research_tools import (
    GENERATION_TOOL_NAMES,
    ResearchConstraintCheckerTool,
    generation_tools,
)


ExperimentMethod = str
MethodHandler = Callable[[Dict[str, Any]], Awaitable[Any] | Any]


class ExperimentRunner:
    """Run benchmark cases and export paper-ready trace/CSV records."""

    METHODS = ("llm_direct", "single_agent", "fixed_multi_agent", "adaptive_multi_agent")
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
                output = await self._dispatch_method(normalized_case, method, request_id)
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
        manifest_path: Optional[str | Path] = None,
    ) -> List[Dict[str, Any]]:
        benchmark_file = Path(benchmark_path)
        cases = self.load_benchmark(benchmark_file)
        selected_methods = [self._normalize_method(method) for method in (methods or self.METHODS)]
        effective_repeats = self.repeats if repeats is None else _validate_repeats(repeats)
        effective_run_id = str(run_id or self.run_id)

        results: List[Dict[str, Any]] = []
        for repeat_offset in range(effective_repeats):
            repeat_index = self.repeat_index + repeat_offset
            for case in cases:
                for method in selected_methods:
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

        if csv_path is None:
            csv_path = self.output_dir / "benchmark_results.csv"
        if json_path is None:
            json_path = self.output_dir / "benchmark_results.json"
        if manifest_path is None:
            manifest_path = self.output_dir / "experiment_manifest.json"
        self.export_csv(results, csv_path)
        self.export_json(results, json_path)
        self.write_experiment_manifest(
            benchmark_path=benchmark_file,
            output_path=manifest_path,
            run_id=effective_run_id,
            repeats=effective_repeats,
            methods=selected_methods,
            system_variant=system_variant,
            model_config_name=model_config_name,
            result_paths={"csv": csv_path, "json": json_path},
        )
        return results

    def write_experiment_manifest(
        self,
        *,
        benchmark_path: str | Path,
        output_path: str | Path,
        run_id: Optional[str] = None,
        repeats: Optional[int] = None,
        methods: Optional[Iterable[ExperimentMethod]] = None,
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
        dataset_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        cache_disabled = is_experiment_cache_disabled()
        strict_mode = is_experiment_strict_mode()
        model = os.getenv("LLM_MODEL") or settings.llm.model
        temperature = _environment_float("LLM_TEMPERATURE", settings.llm.temperature)
        resolved_system_variant = _optional_text(system_variant) or self.system_variant
        resolved_model_config = (
            _optional_text(model_config_name) or self.model_config_name
        )
        commit = _git_commit()
        manifest = {
            "schema_version": "1.0",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "run_id": str(run_id or self.run_id),
            "dataset_id": str(dataset_id),
            "dataset_version": str(dataset_version),
            "dataset_path": benchmark_file.as_posix(),
            "dataset_sha256": dataset_sha256,
            "dataset": {
                "id": str(dataset_id),
                "version": str(dataset_version),
                "path": benchmark_file.as_posix(),
                "sha256": dataset_sha256,
            },
            "git_commit": commit,
            "git": {"commit": commit},
            "methods": list(methods or self.METHODS),
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
            "cache": {"enabled": not cache_disabled, "disabled": cache_disabled},
            "offline_data": {
                "enabled": True,
                "env": "TOURISM_FORMAL_EXPERIMENT_OFFLINE",
                "policy": "formal experiments use frozen local datasets and forbid real-time tourism APIs",
                "snapshot": self._offline_data_summary(),
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
                cases.append(json.loads(case_path.read_text(encoding="utf-8")))
            return cases
        raise ValueError(f"Unsupported benchmark format: {path}")

    def export_csv(self, results: List[Dict[str, Any]], output_path: str | Path) -> None:
        """Export one row per case/method run."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
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
        session_id = f"exp-{case['case_id']}-{method}-{uuid.uuid4().hex[:8]}"
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
        session_id = f"exp-{case['case_id']}-{uuid.uuid4().hex[:8]}"
        session = app.get_or_create_session(session_id)
        final_content = ""
        async for event in app.orchestrator.process(session, case["user_input"], request_id):
            if event.get("status") == "completed" and isinstance(event.get("content"), str):
                final_content = event["content"]
            if event.get("event") == "final" and event.get("data"):
                final_content = _extract_final_content(event.get("data")) or final_content
        return final_content

    async def _run_llm_direct(self, case: Dict[str, Any], request_id: str) -> str:
        prompt = case["user_input"]
        return await self._run_llm_baseline(
            case=case,
            request_id=request_id,
            method="llm_direct",
            system_prompt="你是一个通用大语言模型。请直接回答用户的旅游问题，不调用外部工具。",
            user_prompt=prompt,
            selected_agents=[],
        )

    async def _run_single_agent(self, case: Dict[str, Any], request_id: str) -> str:
        prompt = (
            "请作为单一旅游规划 Agent 独立完成任务。不要调度其他 Agent，"
            "但需要尽量给出结构化、可执行的旅游建议。\n\n用户请求："
            f"{case['user_input']}"
        )
        session_id = f"exp-{case['case_id']}-single_agent-{uuid.uuid4().hex[:8]}"
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
                            finish_agent_run(
                                agent_run,
                                agent_name="single_agent",
                                status="completed",
                                tokens=usage.get("total_tokens"),
                                tool_count=executed_call_count,
                            )
                            set_trace_result_summary(
                                response.content,
                                offline_data=self._offline_data_summary(compact=True),
                            )
                            return response.content

                        for call in response.tool_calls:
                            if not call.id:
                                call.id = uuid.uuid4().hex
                        record_planned_tools(
                            [call.name for call in response.tool_calls if call.name]
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
                                executed_call_count += 1
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
                                if call.is_completed and not call.error:
                                    tool_content = _json_tool_result(call.result)
                                else:
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

    def _build_single_agent_tools(self) -> List[Any]:
        """Build the shared generation tool catalog used by M1/M2/M3."""
        return generation_tools()

    async def _run_fixed_multi_agent(self, case: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        agents = ["attraction", "weather", "itinerary", "budget"] if self._is_tourism_case(case) else []
        tools = list(GENERATION_TOOL_NAMES) if agents else []
        return await self._run_research_multi_agent(
            case=case,
            request_id=request_id,
            method="fixed_multi_agent",
            planned_agents=agents,
            planned_tools=tools,
        )

    async def _run_adaptive_multi_agent(self, case: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        plan = self._select_adaptive_research_plan(case)
        return await self._run_research_multi_agent(
            case=case,
            request_id=request_id,
            method="adaptive_multi_agent",
            planned_agents=plan["agents"],
            planned_tools=plan["tools"],
        )

    async def _run_research_multi_agent(
        self,
        *,
        case: Dict[str, Any],
        request_id: str,
        method: ExperimentMethod,
        planned_agents: List[str],
        planned_tools: List[str],
    ) -> Dict[str, Any]:
        session_id = f"exp-{case['case_id']}-{method}-{uuid.uuid4().hex[:8]}"
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

            tool_results = await self._execute_research_tool_plan(
                case=case,
                agents=planned_agents,
                tools=planned_tools,
            )
            result = await self._build_research_method_output(
                case=case,
                method=method,
                planned_agents=planned_agents,
                planned_tools=planned_tools,
                tool_results=tool_results,
            )
            set_trace_result_summary(result, offline_data=self._offline_data_summary(compact=True))
            return result

    async def _execute_research_tool_plan(
        self,
        *,
        case: Dict[str, Any],
        agents: List[str],
        tools: List[str],
    ) -> Dict[str, Any]:
        catalog = {tool.name: tool for tool in generation_tools()}
        executor = ToolExecutor(tools=catalog)
        tool_results: Dict[str, Any] = {}
        planned_tool_set = set(tools)

        for agent_name in agents:
            agent_tools = [
                tool_name
                for tool_name in self._tools_for_research_agent(agent_name)
                if tool_name in planned_tool_set
            ]
            agent_run = start_agent_run(agent_name)
            agent_error: Optional[str] = None
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
                finish_agent_run(
                    agent_run,
                    agent_name=agent_name,
                    status="failed" if agent_error else "completed",
                    tool_count=len(agent_tools),
                    error=agent_error,
                )
            except BaseException as exc:
                finish_agent_run(
                    agent_run,
                    agent_name=agent_name,
                    status="failed",
                    tool_count=len(agent_tools),
                    error=exc,
                )
                raise
        return tool_results

    def _tools_for_research_agent(self, agent_name: str) -> List[str]:
        mapping = {
            "attraction": ["poi_search"],
            "weather": ["weather_query"],
            "itinerary": [],
            "budget": ["budget_calculator"],
        }
        return mapping.get(agent_name, [])

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
    ) -> Dict[str, Any]:
        attractions = self._attractions_from_tool_result(tool_results.get("poi_search"))
        weather = self._tool_data(tool_results.get("weather_query"))
        budget = self._tool_data(tool_results.get("budget_calculator"))
        trip_days = self._case_duration(case)
        daily_itinerary = self._build_daily_itinerary(trip_days, attractions)
        weather_adjustments = self._build_weather_adjustments(weather, attractions)
        final_answer = await self._compose_research_answer(
            case=case,
            method=method,
            planned_agents=planned_agents,
            planned_tools=planned_tools,
            tool_results=tool_results,
            daily_itinerary=daily_itinerary,
            budget=budget,
            weather_adjustments=weather_adjustments,
        )
        return {
            "task_type": self._infer_research_task_type(case),
            "used_agents": planned_agents,
            "planned_tools": planned_tools,
            "trip_days": trip_days,
            "daily_itinerary": daily_itinerary,
            "budget": budget or None,
            "weather": weather or None,
            "weather_adjustments": weather_adjustments,
            "execution_status": self._execution_status_from_tool_results(tool_results),
            "final_answer": final_answer,
            "tool_results": tool_results,
        }

    async def _compose_research_answer(
        self,
        *,
        case: Dict[str, Any],
        method: ExperimentMethod,
        planned_agents: List[str],
        planned_tools: List[str],
        tool_results: Dict[str, Any],
        daily_itinerary: List[Dict[str, Any]],
        budget: Dict[str, Any],
        weather_adjustments: List[Dict[str, Any]],
    ) -> str:
        llm = self.llm_factory()
        context = {
            "case_id": case["case_id"],
            "method": method,
            "planned_agents": planned_agents,
            "planned_tools": planned_tools,
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

    def _select_adaptive_research_plan(self, case: Dict[str, Any]) -> Dict[str, List[str]]:
        if not self._is_tourism_case(case):
            return {"agents": [], "tools": []}

        task_type = self._infer_research_task_type(case)
        if task_type == "weather_adjustment":
            return {"agents": ["weather", "itinerary"], "tools": ["weather_query"]}
        if task_type == "budget_control":
            return {"agents": ["budget"], "tools": ["budget_calculator"]}
        if task_type == "attraction_recommendation":
            return {"agents": ["attraction"], "tools": ["poi_search"]}
        if task_type == "general_chat":
            return {"agents": [], "tools": []}
        return {
            "agents": ["attraction", "weather", "itinerary", "budget"],
            "tools": list(GENERATION_TOOL_NAMES),
        }

    def _infer_research_task_type(self, case: Dict[str, Any]) -> str:
        text = str(case.get("user_input") or "")
        slots = case.get("slots") if isinstance(case.get("slots"), dict) else {}
        constraints = " ".join(str(item) for item in case.get("constraints") or [])
        combined = f"{text} {constraints}"
        has_trip_signal = bool(self._case_city(case)) or any(
            word in combined for word in ("旅游", "行程", "规划", "游", "旅行")
        )
        if not has_trip_signal:
            return "general_chat"
        if any(word in combined for word in ("天气", "下雨", "雨天", "高温", "低温", "改行程")):
            return "weather_adjustment"
        if any(word in combined for word in ("预算", "费用", "花费", "多少钱", "省钱")) or slots.get("budget"):
            if not any(word in combined for word in ("行程", "规划", "旅游", "游")):
                return "budget_control"
        if any(word in combined for word in ("景点", "推荐", "打卡", "去哪")) and not any(
            word in combined for word in ("行程", "规划")
        ):
            return "attraction_recommendation"
        return "trip_planning"

    def _is_tourism_case(self, case: Dict[str, Any]) -> bool:
        return self._infer_research_task_type(case) != "general_chat"

    def _case_city(self, case: Dict[str, Any]) -> str:
        slots = case.get("slots") if isinstance(case.get("slots"), dict) else {}
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
        slots = case.get("slots") if isinstance(case.get("slots"), dict) else {}
        structured = case.get("structured_request") if isinstance(case.get("structured_request"), dict) else {}
        for value in (
            slots.get("duration"),
            slots.get("days"),
            structured.get("days"),
            structured.get("duration"),
            case.get("days"),
            case.get("duration"),
        ):
            if value is None or value == "":
                continue
            try:
                return max(1, min(int(value), 5))
            except (TypeError, ValueError):
                continue
        return 3

    def _case_start_date(self, case: Dict[str, Any]) -> Optional[str]:
        slots = case.get("slots") if isinstance(case.get("slots"), dict) else {}
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
        structured = case.get("structured_request") if isinstance(case.get("structured_request"), dict) else {}
        preferences = structured.get("preferences") or case.get("preferences") or []
        constraints = case.get("constraints") or structured.get("constraints") or []
        return [*_as_list(preferences), *_as_list(constraints)]

    def _case_people(self, case: Dict[str, Any]) -> str:
        slots = case.get("slots") if isinstance(case.get("slots"), dict) else {}
        structured = case.get("structured_request") if isinstance(case.get("structured_request"), dict) else {}
        return str(
            slots.get("traveler_type")
            or structured.get("traveler_type")
            or case.get("traveler_type")
            or "general"
        )

    def _case_traveler_count(self, case: Dict[str, Any]) -> int:
        slots = case.get("slots") if isinstance(case.get("slots"), dict) else {}
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
        slots = case.get("slots") if isinstance(case.get("slots"), dict) else {}
        structured = case.get("structured_request") if isinstance(case.get("structured_request"), dict) else {}
        value = (
            slots.get("budget_level")
            or structured.get("budget_level")
            or case.get("budget_level")
        )
        if value:
            return str(value)
        budget = slots.get("budget") or structured.get("budget") or case.get("budget")
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
        slots = case.get("slots") if isinstance(case.get("slots"), dict) else {}
        structured = case.get("structured_request") if isinstance(case.get("structured_request"), dict) else {}
        for value in (
            slots.get("budget_limit"),
            slots.get("budget"),
            structured.get("budget_limit"),
            structured.get("budget"),
            case.get("budget_limit"),
            case.get("budget"),
        ):
            if value is None or value == "":
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    def _offline_data_summary(self, *, compact: bool = False) -> Dict[str, Any]:
        manifest = fixed_data_file_manifest()
        if not compact:
            return manifest
        return {
            "schema_version": manifest["schema_version"],
            "city_ids": manifest["city_ids"],
            "file_count": manifest["file_count"],
            "combined_sha256": manifest["combined_sha256"],
        }

    def _case_poi_limit(self, case: Dict[str, Any]) -> int:
        return max(3, min(self._case_duration(case) * 2, 10))

    def _case_weather_scenario(self, case: Dict[str, Any]) -> str:
        slots = case.get("slots") if isinstance(case.get("slots"), dict) else {}
        structured = case.get("structured_request") if isinstance(case.get("structured_request"), dict) else {}
        explicit = (
            slots.get("weather_scenario")
            or structured.get("weather_scenario")
            or case.get("weather_scenario")
            or case.get("scenario_type")
        )
        if explicit:
            return str(explicit)
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
    ) -> List[Dict[str, Any]]:
        if not weather:
            return []
        scenario = str(weather.get("scenario_type") or "")
        risky = scenario in {"rain", "high_temperature", "low_temperature", "continuous_change"}
        if not risky and not weather.get("weather_adjustment_required"):
            return []
        indoor_candidates = [
            item
            for item in attractions
            if str(item.get("indoor_outdoor") or "").lower() == "indoor"
        ]
        return [
            {
                "reason": scenario or "weather_risk",
                "action": "减少长时间户外活动，优先安排室内或低风险景点",
                "candidate_indoor_pois": [
                    {"poi_id": item.get("poi_id"), "name": item.get("name")}
                    for item in indoor_candidates[:3]
                ],
            }
        ]

    def _execution_status_from_tool_results(self, tool_results: Dict[str, Any]) -> str:
        for result in tool_results.values():
            if isinstance(result, dict) and result.get("status") == "failed":
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
        session_id = f"exp-{case['case_id']}-{method}-{uuid.uuid4().hex[:8]}"
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
        constraint_report = await self._run_constraint_checker(case, preliminary_output)
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
            "status": "failed" if error else structured_output.get("execution_status") or trace_record.get("status", "completed"),
            "metrics": metrics,
            "error": error,
        }

    async def _run_constraint_checker(
        self,
        case: Dict[str, Any],
        structured_output: Dict[str, Any],
    ) -> Dict[str, Any]:
        checker = ResearchConstraintCheckerTool()
        plan = {
            key: value
            for key, value in structured_output.items()
            if key not in {"method", "used_agents", "called_tools", "metadata"}
        }
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

    def _flatten_result_for_csv(self, result: Dict[str, Any]) -> Dict[str, Any]:
        trace = result.get("trace") or {}
        metrics = result.get("metrics") or {}
        output = result.get("output")
        output_text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
        return {
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
        "traveler_type": "traveler_type",
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


def _json_tool_result(value: Any) -> str:
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    return json.dumps(value, ensure_ascii=False, default=str)


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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
