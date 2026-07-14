"""
Experiment runner for thesis-style benchmark execution.

The runner keeps the original metric collection helpers, and adds a unified
entry point for running the same case through three comparable methods:
llm_direct, single_agent, and full_system.
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

from app.core.experiment_metrics import (
    CollaborationMode,
    ExperimentContext,
    ExperimentMetrics,
    ReviewModeExperiment,
    build_experiment_metrics,
    build_experiment_record,
)
from app.core.llm.client import LLMMessage, ToolDefinition, get_llm
from app.core.tool_executor import ToolExecutor
from app.core.tracing import (
    DEFAULT_TRACE_DIR,
    DEFAULT_EVALUATION_MODE,
    finish_agent_run,
    record_planned_tools,
    request_trace,
    set_trace_intent_info,
    set_trace_selected_agents,
    start_agent_run,
    trace_component,
)


ExperimentMethod = str
MethodHandler = Callable[[Dict[str, Any]], Awaitable[Any] | Any]


class ExperimentRunner:
    """Run benchmark cases and export paper-ready trace/CSV records."""

    METHODS = ("llm_direct", "single_agent", "full_system")
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
    ) -> None:
        self.trace_dir = Path(trace_dir)
        self.output_dir = Path(output_dir)
        self.method_handlers = method_handlers or {}
        self.app_factory = app_factory
        self.llm_factory = llm_factory or get_llm
        self.experiment_records: List[Dict[str, Any]] = []
        self.current_context: Optional[ExperimentContext] = None

    # ------------------------------------------------------------------
    # New thesis benchmark API
    # ------------------------------------------------------------------
    def run(self, case: Dict[str, Any], method: ExperimentMethod = "full_system") -> Dict[str, Any]:
        """Synchronously run one case through one method."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.arun(case, method=method))
        raise RuntimeError("ExperimentRunner.run() cannot be used inside a running event loop; use arun().")

    async def arun(self, case: Dict[str, Any], method: ExperimentMethod = "full_system") -> Dict[str, Any]:
        """Asynchronously run one case through one method."""
        method = self._normalize_method(method)
        normalized_case = self._normalize_case(case)
        case_id = normalized_case["case_id"]
        request_id = f"{case_id}_{method}_{uuid.uuid4().hex[:8]}"

        before = self._trace_files()
        started = time.perf_counter()
        output: Any = None
        error: Optional[str] = None

        env = {
            "ENABLE_TRACING": "true",
            "TRACE_OUTPUT_DIR": str(self.trace_dir),
            "EXPERIMENT_CASE_ID": case_id,
            "EXPERIMENT_METHOD": method,
            "EXPERIMENT_EVALUATION_MODE": normalized_case["evaluation_mode"],
        }
        self.trace_dir.mkdir(parents=True, exist_ok=True)

        with _temporary_env(env):
            try:
                output = await self._dispatch_method(normalized_case, method, request_id)
            except Exception as exc:  # keep benchmark runs table-shaped
                error = str(exc)
                output = {"error": error}

        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        trace = self._load_newest_trace(before)
        result = self._build_unified_result(
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
        csv_path: Optional[str | Path] = None,
        json_path: Optional[str | Path] = None,
    ) -> List[Dict[str, Any]]:
        """Run all benchmark cases through all requested methods."""
        return asyncio.run(
            self.arun_benchmark(
                benchmark_path,
                methods=methods,
                csv_path=csv_path,
                json_path=json_path,
            )
        )

    async def arun_benchmark(
        self,
        benchmark_path: str | Path = "experiments/benchmark.json",
        *,
        methods: Optional[Iterable[ExperimentMethod]] = None,
        csv_path: Optional[str | Path] = None,
        json_path: Optional[str | Path] = None,
    ) -> List[Dict[str, Any]]:
        benchmark_file = Path(benchmark_path)
        cases = self.load_benchmark(benchmark_file)
        selected_methods = [self._normalize_method(method) for method in (methods or self.METHODS)]

        results: List[Dict[str, Any]] = []
        for case in cases:
            for method in selected_methods:
                results.append(await self.arun(case, method=method))

        if csv_path is None:
            csv_path = self.output_dir / "benchmark_results.csv"
        if json_path is None:
            json_path = self.output_dir / "benchmark_results.json"
        self.export_csv(results, csv_path)
        self.export_json(results, json_path)
        return results

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
        if method == "full_system":
            return await self._run_full_system(case, request_id)
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
            return await _maybe_await(self.method_handlers[method](case))

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
                        "你是一个单 Agent 旅游规划助手。你可以根据需要调用 POI、天气、"
                        "路线和预算工具。请优先使用工具返回的真实数据，不要调度其他 Agent。"
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
        """Build the repository's shared POI, weather, route, and budget tools."""
        from app.tools.budget_calc import BudgetCalculatorTool, BudgetOptimizerTool
        from app.tools.poi_search import POIDetailTool, POISearchTool
        from app.tools.route_plan import RoutePlanningTool
        from app.tools.weather import WeatherTool

        return [
            POISearchTool(),
            POIDetailTool(),
            WeatherTool(),
            RoutePlanningTool(),
            BudgetCalculatorTool(),
            BudgetOptimizerTool(),
        ]

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

    def _build_unified_result(
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
        metrics = self._score_against_expected(case.get("expected") or {}, trace_record)
        ttft_ms = trace_record.get("first_body_token_ms")
        return {
            "case_id": case["case_id"],
            "method": method,
            "evaluation_mode": case["evaluation_mode"],
            "output": output,
            "latency": latency_ms,
            "latency_ms": latency_ms,
            "ttft_ms": ttft_ms if isinstance(ttft_ms, (int, float)) else None,
            "trace": trace_record,
            "trace_file": trace_record.get("trace_file"),
            "status": "failed" if error else trace_record.get("status", "completed"),
            "metrics": metrics,
            "error": error,
        }

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
            "trace_file": result.get("trace_file"),
            "output_preview": output_text[:500],
            "error": result.get("error") or "",
        }

    def _normalize_method(self, method: ExperimentMethod) -> ExperimentMethod:
        normalized = str(method or "").strip().lower()
        if normalized not in self.METHODS:
            raise ValueError(f"method must be one of {', '.join(self.METHODS)}")
        return normalized

    def _trace_files(self) -> set[Path]:
        if not self.trace_dir.exists():
            return set()
        return set(self.trace_dir.glob("*.jsonl"))

    def _load_newest_trace(self, before: set[Path]) -> Optional[Dict[str, Any]]:
        candidates = [path for path in self._trace_files() if path not in before]
        if not candidates:
            return None
        path = max(candidates, key=lambda item: item.stat().st_mtime)
        line = path.read_text(encoding="utf-8").splitlines()[0]
        record = json.loads(line)
        record["trace_file"] = str(path)
        return record


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
