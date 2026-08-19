"""Run Day 6 four-method pipeline acceptance without external LLM/API calls."""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, Iterator, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.experiment_method_contract import (
    METHOD_FAIRNESS_CONTRACT_SCHEMA_VERSION,
)
from app.core.experiment_method_input import METHOD_INPUT_SCHEMA_VERSION
from app.core.experiment_run_audit import RUN_AUDIT_SCHEMA_VERSION
from app.core.experiment_runner import (
    RESEARCH_AGENT_DECISION_SCHEMA_VERSION,
    STRUCTURED_LLM_OUTPUT_PROMPT_VERSION,
    ExperimentRunner,
)
from app.core.fixed_data import canonical_json_sha256
from app.core.independent_evaluator import EVALUATION_SUMMARY_SCHEMA_VERSION
from app.core.llm.client import ToolCall
from app.core.tracing import (
    finish_llm_call,
    get_current_trace,
    start_llm_call,
)
from app.schemas.experiment import EXPERIMENT_OUTPUT_SCHEMA_VERSION
from app.tools.research_tools import GENERATION_TOOL_NAMES


DEFAULT_OUTPUT_ROOT = ROOT / "experiments" / "results" / "day6_acceptance"
SOURCE_BENCHMARK_PATH = ROOT / "experiments" / "day6_acceptance_cases.json"
GENERATED_BENCHMARK_NAME = "day6_acceptance_benchmark.json"
GOLD_LEAK_MARKER = "DAY6_GOLD_SHOULD_NOT_LEAK"
DAY6_REQUIRED_TASK_TYPES = {
    "trip_planning",
    "attraction_recommendation",
    "weather_query",
    "budget_query",
    "partial_replan",
    "weather_adjustment",
    "clarification",
    "general_chat",
}
DAY6_ACCEPTANCE_GATE_SCHEMA_VERSION = "day6-acceptance-gate-v1"
DAY6_ACCEPTANCE_LEVEL = "infrastructure_acceptance"
DAY6_ACADEMIC_QUALITY_STATUS = "not_evaluated_with_fake_llm"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", type=str, default=None)
    args = parser.parse_args()

    run_id = args.run_id or f"day6_acceptance_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    output_dir = args.output_dir if args.output_dir.name == run_id else args.output_dir / run_id
    if output_dir.exists() and any(output_dir.iterdir()):
        raise RuntimeError(f"Day6 acceptance output directory is not empty: {output_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    benchmark_path = output_dir / GENERATED_BENCHMARK_NAME
    benchmark_doc = asyncio.run(_prepare_benchmark_document())
    benchmark_path.write_text(
        json.dumps(benchmark_doc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    env = {
        "EXPERIMENT_STRICT_MODE": "true",
        "EXPERIMENT_DISABLE_CACHE": "true",
        "LLM_MODEL": "day6-offline-fake-llm",
        "LLM_TEMPERATURE": "0",
        "TRACE_SAVE_USER_MESSAGE": "false",
    }
    with _temporary_env(env):
        runner = ExperimentRunner(
            trace_dir=output_dir / "traces",
            output_dir=output_dir,
            llm_factory=Day6OfflineLLM,
            run_id=run_id,
            model_config_name="day6-acceptance-offline",
        )
        results = runner.run_benchmark(benchmark_path, repeats=1)

    manifest = _read_json(output_dir / "experiment_manifest.json")
    summary = _read_json(output_dir / "evaluation_summary.json")
    csv_rows = _read_csv(output_dir / "benchmark_results.csv")
    paper_tables = (output_dir / "paper_tables.md").read_text(encoding="utf-8")
    acceptance_gate = _validate_acceptance(
        results=results,
        manifest=manifest,
        summary=summary,
        csv_rows=csv_rows,
        paper_tables=paper_tables,
        benchmark_doc=benchmark_doc,
    )

    report_path = output_dir / "day6_acceptance_report.md"
    saved_evidence = _build_saved_evidence(
        output_dir=output_dir,
        benchmark_path=benchmark_path,
        report_path=report_path,
        results=results,
        expected_count=_expected_count(benchmark_doc),
        require_report=False,
    )
    report_path.write_text(
        _render_report(run_id, results, manifest, summary, acceptance_gate, saved_evidence),
        encoding="utf-8",
    )
    saved_evidence = _build_saved_evidence(
        output_dir=output_dir,
        benchmark_path=benchmark_path,
        report_path=report_path,
        results=results,
        expected_count=_expected_count(benchmark_doc),
        require_report=True,
    )
    _validate_saved_evidence(saved_evidence)
    manifest = _attach_acceptance_evidence(
        manifest=manifest,
        acceptance_gate=acceptance_gate,
        saved_evidence=saved_evidence,
        result_count=len(results),
        expected_count=_expected_count(benchmark_doc),
    )
    (output_dir / "experiment_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    payload = {
        "status": "passed",
        "acceptance_level": acceptance_gate["acceptance_level"],
        "academic_quality_status": acceptance_gate["academic_quality_status"],
        "quality_gate": acceptance_gate,
        "saved_evidence": saved_evidence,
        "run_id": run_id,
        "output_dir": output_dir.as_posix(),
        "result_count": len(results),
        "expected_count": _expected_count(benchmark_doc),
        "benchmark": benchmark_path.as_posix(),
        "csv": (output_dir / "benchmark_results.csv").as_posix(),
        "json": (output_dir / "benchmark_results.json").as_posix(),
        "summary": (output_dir / "evaluation_summary.json").as_posix(),
        "paper_tables": (output_dir / "paper_tables.md").as_posix(),
        "manifest": (output_dir / "experiment_manifest.json").as_posix(),
        "report": report_path.as_posix(),
        "trace_dir": saved_evidence["trace_dir"],
        "trace_file_count": saved_evidence["trace_file_count"],
        "representative_trace": saved_evidence["representative_trace"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


class Day6OfflineLLM:
    """Deterministic fake LLM that still records trace-level LLM audit data."""

    model = "day6-offline-fake-llm"

    async def chat(self, messages: List[Any], tools: Optional[List[Any]] = None, **_: Any) -> Any:
        text = _messages_text(messages)
        tool_messages_seen = any(str(getattr(message, "role", "")).lower() == "tool" for message in messages)
        tool_calls = [] if tool_messages_seen else self._planned_tool_calls(text, tools)
        content = "" if tool_calls else (_agent_decision_answer(messages) or self._final_answer(text))
        usage = self._record_llm_call(messages, tools, content)
        return SimpleNamespace(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            model=self.model,
            finish_reason="tool_calls" if tool_calls else "stop",
        )

    def _planned_tool_calls(self, text: str, tools: Optional[List[Any]]) -> List[ToolCall]:
        if not tools:
            return []
        available = {str(getattr(tool, "name", "")) for tool in tools}
        lowered = text.casefold()
        if _contains_any(lowered, ("你好", "hello", "打个招呼")):
            return []

        names: List[str] = []
        full_plan = _contains_any(lowered, ("规划", "行程", "旅游", "trip", "plan"))
        if "poi_search" in available and (
            full_plan or _contains_any(lowered, ("景点", "推荐", "attraction"))
        ):
            names.append("poi_search")
        if "weather_query" in available and (
            full_plan or _contains_any(lowered, ("天气", "weather"))
        ):
            names.append("weather_query")
        if "budget_calculator" in available and (
            full_plan or _contains_any(lowered, ("预算", "费用", "budget", "cost"))
        ):
            names.append("budget_calculator")

        return [
            ToolCall(
                id=f"day6-{name}",
                name=name,
                arguments=json.dumps(_tool_arguments(name, lowered), ensure_ascii=False),
            )
            for name in names
        ]

    def _final_answer(self, text: str) -> str:
        structured_answer = _structured_llm_acceptance_answer(text)
        if structured_answer is not None:
            return structured_answer
        if _contains_any(text.casefold(), ("你好", "hello", "打个招呼")):
            return "你好。该请求不需要旅游业务 Agent 或工具。"
        return "Day6 离线验收回答：已基于固定实验工具证据生成结构化旅游结果。"

    def _record_llm_call(
        self,
        messages: List[Any],
        tools: Optional[List[Any]],
        content: str,
    ) -> Dict[str, int]:
        message_chars = sum(len(str(getattr(message, "content", "") or "")) for message in messages)
        usage = {
            "prompt_tokens": max(1, message_chars // 4),
            "completion_tokens": max(1, len(content or "tool_call") // 4),
        }
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]

        trace_call = start_llm_call(
            provider="day6_acceptance",
            model=self.model,
            streaming=False,
            mock=True,
            fallback=False,
            message_count=len(messages),
            message_chars=message_chars,
            tool_count=len(tools or []),
            prompt_version=_prompt_version(messages),
            prompt_hash=_prompt_hash(messages, tools),
        )
        trace = get_current_trace()
        if trace is not None:
            trace.mark_first_body_token()
        finish_llm_call(
            trace_call,
            provider="day6_acceptance",
            model=self.model,
            usage=usage,
            success=True,
            mock=True,
            fallback=False,
            output_chars=len(content or ""),
        )
        return usage


async def _prepare_benchmark_document() -> Dict[str, Any]:
    source = _read_json(SOURCE_BENCHMARK_PATH)
    return {
        **source,
        "source_path": SOURCE_BENCHMARK_PATH.as_posix(),
        "source_sha256": canonical_json_sha256(source),
        "cases": list(source.get("cases") or []),
    }


def _validate_acceptance(
    *,
    results: List[Dict[str, Any]],
    manifest: Dict[str, Any],
    summary: Dict[str, Any],
    csv_rows: List[Dict[str, str]],
    paper_tables: str,
    benchmark_doc: Dict[str, Any],
) -> Dict[str, Any]:
    expected_count = _expected_count(benchmark_doc)
    if len(results) != expected_count:
        raise RuntimeError("Day6 acceptance result count mismatch")
    if len(csv_rows) != expected_count:
        raise RuntimeError("Day6 acceptance CSV row count mismatch")
    if any(result.get("status") not in {"completed", "clarification"} for result in results):
        raise RuntimeError("Day6 acceptance has failed infrastructure runs")

    _validate_manifest(manifest, benchmark_doc)
    _validate_summary(summary)
    _validate_paper_tables(paper_tables)
    _validate_outputs(results)
    acceptance_gate = _build_acceptance_gate(results)
    _validate_acceptance_gate(acceptance_gate)
    _validate_csv(csv_rows)
    _validate_fake_llm_acceptance_scope(results, benchmark_doc)
    _validate_fake_llm_trace_audit(results)
    _validate_m3_full_plan(results)
    _validate_m3_clarification(results)
    _validate_formal_turn_scenarios(results, benchmark_doc)
    return acceptance_gate


def _validate_manifest(manifest: Dict[str, Any], benchmark_doc: Dict[str, Any]) -> None:
    contract = manifest.get("method_fairness_contract") or {}
    if contract.get("schema_version") != METHOD_FAIRNESS_CONTRACT_SCHEMA_VERSION:
        raise RuntimeError("Day6 manifest fairness contract schema mismatch")
    if set(contract.get("active_methods") or []) != set(ExperimentRunner.METHODS):
        raise RuntimeError("Day6 manifest active methods mismatch")
    if len(str(contract.get("contract_sha256") or "")) != 64:
        raise RuntimeError("Day6 manifest fairness contract hash missing")
    if manifest.get("dataset_sha256") != canonical_json_sha256(benchmark_doc):
        raise RuntimeError("Day6 manifest dataset hash mismatch")
    if manifest.get("method_order_seed") is None:
        raise RuntimeError("Day6 manifest method order seed missing")
    for key in ("csv", "json", "summary", "paper_tables"):
        path = (manifest.get("results") or {}).get(key)
        if not path or not Path(path).exists():
            raise RuntimeError(f"Day6 manifest missing result path: {key}")


def _validate_summary(summary: Dict[str, Any]) -> None:
    if summary.get("schema_version") != EVALUATION_SUMMARY_SCHEMA_VERSION:
        raise RuntimeError("Day6 evaluation summary schema mismatch")
    if set(summary.get("methods") or {}) != set(ExperimentRunner.METHODS):
        raise RuntimeError("Day6 evaluation summary missing method rows")
    if (summary.get("paired_statistics") or {}).get("pair_count") != _case_count(summary):
        raise RuntimeError("Day6 paired statistics count mismatch")
    repeat_aggregation = summary.get("repeat_aggregation") or {}
    if repeat_aggregation.get("unit") != "evaluation_unit_id":
        raise RuntimeError("Day6 summary must aggregate repeats by evaluation_unit_id")
    if repeat_aggregation.get("scenario_turns_are_repeats") is not False:
        raise RuntimeError("Day6 summary is treating scenario turns as repeats")
    if (summary.get("quality_evaluation_scope") or {}).get("multi_turn") != "target_turn_only":
        raise RuntimeError("Day6 summary must evaluate multi-turn quality on target turns")
    scenario_costs = summary.get("scenario_costs") or {}
    if scenario_costs.get("scenario_count", 0) < 3:
        raise RuntimeError("Day6 summary missing multi-turn scenario cost accounting")
    m3_costs = (scenario_costs.get("methods") or {}).get("adaptive_multi_agent") or {}
    for key in (
        "target_increment_llm_call_count_mean",
        "scenario_total_llm_call_count_mean",
        "target_increment_total_tokens_mean",
        "scenario_total_total_tokens_mean",
        "target_increment_called_tool_count_mean",
        "scenario_total_called_tool_count_mean",
    ):
        if key not in m3_costs:
            raise RuntimeError(f"Day6 summary missing scenario cost metric: {key}")
    m3 = (summary.get("methods") or {}).get("adaptive_multi_agent") or {}
    for key in (
        "llm_call_count_mean",
        "prompt_tokens_mean",
        "planned_agent_count_mean",
        "called_tool_count_mean",
        "successful_tool_call_count_mean",
    ):
        if key not in m3:
            raise RuntimeError(f"Day6 summary missing audit metric: {key}")


def _validate_paper_tables(paper_tables: str) -> None:
    required = [
        "M0 Direct LLM",
        "M1 Single Agent",
        "M2 Fixed Template Multi-Agent",
        "M3 Proposed",
        "Agent/tool diagnostics",
        "Token and cost",
        "Multi-turn scenario costs",
        "Target turn incremental",
        "Scenario total",
        "LLM calls",
        "Prompt tokens",
    ]
    missing = [item for item in required if item not in paper_tables]
    if missing:
        raise RuntimeError(f"Day6 paper tables missing sections: {missing}")


def _validate_fake_llm_acceptance_scope(
    results: List[Dict[str, Any]],
    benchmark_doc: Dict[str, Any],
) -> None:
    raw_units = _generation_unit_count(benchmark_doc)
    quality_units = _quality_units(benchmark_doc)
    if raw_units * len(ExperimentRunner.METHODS) <= 32:
        raise RuntimeError("Day6 FakeLLM raw run count must exceed 32 after multi-turn prep turns")
    if len(quality_units) * len(ExperimentRunner.METHODS) < 32:
        raise RuntimeError("Day6 FakeLLM quality scope must cover at least 8 task types x 4 methods")
    task_types = {
        str((unit.get("expected") or {}).get("task_type") or "")
        for unit in quality_units
        if isinstance(unit, dict)
    }
    missing = sorted(DAY6_REQUIRED_TASK_TYPES - task_types)
    if missing:
        raise RuntimeError(f"Day6 FakeLLM acceptance missing task types: {missing}")


def _validate_fake_llm_trace_audit(results: List[Dict[str, Any]]) -> None:
    for result in results:
        trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
        for call in trace.get("llm_calls") or []:
            if not isinstance(call, dict):
                continue
            if call.get("mock") is not True or call.get("mock_used") is not True:
                raise RuntimeError("Day6 FakeLLM trace must record mock=true")
            if call.get("fallback") is not False or call.get("fallback_used") is not False:
                raise RuntimeError("Day6 FakeLLM trace must not be marked as fallback")
            for key in (
                "estimated_cost",
                "standardized_estimated_cost",
                "actual_cost",
                "input_token_unit_price",
                "output_token_unit_price",
                "price_snapshot_date",
                "price_source_url",
                "prompt_version",
                "prompt_hash",
            ):
                if call.get(key) is None:
                    raise RuntimeError(f"Day6 LLM trace missing audit field: {key}")
            if len(str(call.get("prompt_hash") or "")) != 64:
                raise RuntimeError("Day6 LLM trace prompt_hash must be a SHA-256 digest")


def _validate_outputs(results: List[Dict[str, Any]]) -> None:
    for result in results:
        output = result.get("output") or {}
        audit = result.get("run_audit") or {}
        if output.get("schema_version") != EXPERIMENT_OUTPUT_SCHEMA_VERSION:
            raise RuntimeError("Day6 output schema mismatch")
        if audit.get("schema_version") != RUN_AUDIT_SCHEMA_VERSION:
            raise RuntimeError("Day6 run_audit schema mismatch")
        if result.get("audit") != audit:
            raise RuntimeError("Day6 audit alias mismatch")
        if output.get("metadata", {}).get("run_audit_schema_version") != RUN_AUDIT_SCHEMA_VERSION:
            raise RuntimeError("Day6 output audit metadata missing")
        if output.get("metadata", {}).get("method_input_schema_version") != METHOD_INPUT_SCHEMA_VERSION:
            raise RuntimeError("Day6 method input schema metadata missing")
        if GOLD_LEAK_MARKER in json.dumps(
            {
                "output": result.get("output"),
                "raw_output": result.get("raw_output"),
                "trace": result.get("trace"),
            },
            ensure_ascii=False,
            default=str,
        ):
            raise RuntimeError("Day6 generation output leaked evaluator-only gold marker")

        method = result.get("method")
        raw_output = result.get("raw_output")
        if method in {"llm_direct", "single_agent"}:
            if not isinstance(raw_output, dict) or raw_output.get("schema_version") != EXPERIMENT_OUTPUT_SCHEMA_VERSION:
                raise RuntimeError("Day6 M0/M1 raw output schema mismatch")
            structured_meta = (raw_output.get("metadata") or {}).get("structured_llm_output") or {}
            single_agent_no_business_output = (
                method == "single_agent"
                and raw_output.get("task_type") in {"general_chat", "clarification"}
                and not raw_output.get("planned_agents")
                and not raw_output.get("used_agents")
                and not raw_output.get("planned_tools")
                and not raw_output.get("called_tools")
            )
            if (
                not single_agent_no_business_output
                and (
                    structured_meta.get("parse_status") != "passed"
                    or structured_meta.get("validation_status") != "passed"
                )
            ):
                raise RuntimeError("Day6 M0/M1 structured JSON validation failed")
        if method == "llm_direct":
            if audit.get("planned_agents") or audit.get("called_tools"):
                raise RuntimeError("Day6 M0 must remain no-agent/no-tool")
        if method in {"fixed_multi_agent", "adaptive_multi_agent"}:
            if not isinstance(raw_output, dict) or raw_output.get("schema_version") != EXPERIMENT_OUTPUT_SCHEMA_VERSION:
                raise RuntimeError("Day6 M2/M3 raw output schema mismatch")


def _validate_task_type_alignment(results: List[Dict[str, Any]]) -> None:
    _validate_task_type_alignment_report(_task_type_alignment_report(results))


def _build_acceptance_gate(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    task_type_alignment = _task_type_alignment_report(results)
    stsr = _stsr_report(results)
    return {
        "schema_version": DAY6_ACCEPTANCE_GATE_SCHEMA_VERSION,
        "acceptance_level": DAY6_ACCEPTANCE_LEVEL,
        "academic_quality_status": DAY6_ACADEMIC_QUALITY_STATUS,
        "task_type_alignment": task_type_alignment,
        "stsr": stsr,
        "notes": [
            "Day6 FakeLLM acceptance validates experiment infrastructure and routing sanity.",
            "STSR is recorded for audit only under FakeLLM and must not be reported as real model quality.",
            "Task type mismatch is a blocking failure because it invalidates downstream evaluation units.",
        ],
    }


def _validate_acceptance_gate(gate: Dict[str, Any]) -> None:
    if gate.get("schema_version") != DAY6_ACCEPTANCE_GATE_SCHEMA_VERSION:
        raise RuntimeError("Day6 acceptance gate schema mismatch")
    if gate.get("acceptance_level") != DAY6_ACCEPTANCE_LEVEL:
        raise RuntimeError("Day6 acceptance must be marked as infrastructure_acceptance")
    if gate.get("academic_quality_status") != DAY6_ACADEMIC_QUALITY_STATUS:
        raise RuntimeError("Day6 FakeLLM acceptance must not claim academic quality")
    _validate_task_type_alignment_report(gate.get("task_type_alignment") or {})
    stsr = gate.get("stsr") or {}
    if stsr.get("status") != "informational_only":
        raise RuntimeError("Day6 FakeLLM STSR must be marked informational_only")
    if stsr.get("total_count") != (gate.get("task_type_alignment") or {}).get("checked_unit_count"):
        raise RuntimeError("Day6 acceptance gate STSR count mismatch")


def _task_type_alignment_report(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    mismatches: List[str] = []
    illegal_types: List[str] = []
    missing_expected: List[str] = []
    checked = _target_quality_results(results)
    for result in checked:
        output_task_type = str(((result.get("output") or {}).get("task_type")) or "")
        expected_task_type = str(((result.get("evaluation") or {}).get("task_type")) or "")
        result_id = f"{result.get('method')}:{result.get('case_id')}:{result.get('turn_id') or '-'}"
        if output_task_type not in DAY6_REQUIRED_TASK_TYPES:
            illegal_types.append(f"{result_id}={output_task_type}")
        if not expected_task_type:
            missing_expected.append(result_id)
        elif output_task_type != expected_task_type:
            mismatches.append(f"{result_id} expected={expected_task_type} got={output_task_type}")
    failed = bool(mismatches or illegal_types or missing_expected)
    return {
        "status": "failed" if failed else "passed",
        "checked_unit_count": len(checked),
        "mismatch_count": len(mismatches),
        "non_frozen_task_type_count": len(illegal_types),
        "missing_expected_task_type_count": len(missing_expected),
        "mismatches": mismatches,
        "non_frozen_task_types": illegal_types,
        "missing_expected_task_types": missing_expected,
    }


def _validate_task_type_alignment_report(report: Dict[str, Any]) -> None:
    if report.get("status") != "passed":
        raise RuntimeError(
            "Day6 task type alignment failed: "
            f"mismatches={report.get('mismatches') or []}; "
            f"non_frozen={report.get('non_frozen_task_types') or []}; "
            f"missing_expected={report.get('missing_expected_task_types') or []}"
        )
    if int(report.get("checked_unit_count") or 0) <= 0:
        raise RuntimeError("Day6 task type alignment checked no quality units")


def _stsr_report(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    checked = _target_quality_results(results)
    true_count = sum(1 for result in checked if ((result.get("evaluation") or {}).get("metrics") or {}).get("stsr") is True)
    by_method: Dict[str, Dict[str, Any]] = {}
    for result in checked:
        method = str(result.get("method") or "unknown")
        row = by_method.setdefault(method, {"true_count": 0, "total_count": 0, "rate": 0.0})
        row["total_count"] += 1
        if ((result.get("evaluation") or {}).get("metrics") or {}).get("stsr") is True:
            row["true_count"] += 1
    for row in by_method.values():
        total = int(row["total_count"] or 0)
        row["rate"] = round(float(row["true_count"]) / total, 4) if total else 0.0
    total_count = len(checked)
    return {
        "status": "informational_only",
        "true_count": true_count,
        "total_count": total_count,
        "rate": round(true_count / total_count, 4) if total_count else 0.0,
        "by_method": by_method,
        "blocking_threshold": None,
        "interpretation": "fake_llm_not_model_quality",
    }


def _validate_csv(rows: List[Dict[str, str]]) -> None:
    required_columns = {
        "run_audit_schema_version",
        "planned_agent_count",
        "agent_call_count",
        "called_tool_count",
        "successful_tool_call_count",
        "llm_call_count",
        "prompt_tokens",
        "completion_tokens",
        "target_turn",
    }
    missing = sorted(required_columns - set(rows[0]))
    if missing:
        raise RuntimeError(f"Day6 CSV missing audit columns: {missing}")
    if any(row["run_audit_schema_version"] != RUN_AUDIT_SCHEMA_VERSION for row in rows):
        raise RuntimeError("Day6 CSV audit schema value mismatch")


def _validate_m3_full_plan(results: List[Dict[str, Any]]) -> None:
    m3 = _result_for(results, "day6_full_plan", "adaptive_multi_agent")
    audit = m3.get("run_audit") or {}
    audit_metrics = audit.get("metrics") or {}
    scheduler = ((m3.get("output") or {}).get("metadata") or {}).get("adaptive_scheduler") or {}
    ticket = scheduler.get("ticket") if isinstance(scheduler.get("ticket"), dict) else {}
    decision = scheduler.get("decision") if isinstance(scheduler.get("decision"), dict) else {}

    expected_agents = {"attraction", "weather", "itinerary", "budget"}
    expected_tools = set(GENERATION_TOOL_NAMES)
    if ticket.get("task_type") not in {"trip_planning", "weather_aware_trip_plan"}:
        raise RuntimeError(
            "Day6 M3 full plan case was not recognized as a weather-aware full plan"
        )
    if set(decision.get("planned_agents") or []) != expected_agents:
        raise RuntimeError("Day6 M3 full plan case did not plan all four agents")
    if set(decision.get("planned_tools") or []) != expected_tools:
        raise RuntimeError("Day6 M3 full plan case did not plan all generation tools")
    if set(audit.get("planned_agents") or []) != expected_agents:
        raise RuntimeError("Day6 M3 full plan audit did not record all four planned agents")
    if set(audit.get("called_tools") or []) != expected_tools:
        raise RuntimeError("Day6 M3 full plan audit did not record all three called tools")
    if audit_metrics.get("planned_agent_count") != 4:
        raise RuntimeError("Day6 M3 full plan planned_agent_count is not 4")
    if audit_metrics.get("called_tool_count") != 3:
        raise RuntimeError("Day6 M3 full plan called_tool_count is not 3")


def _validate_m3_clarification(results: List[Dict[str, Any]]) -> None:
    result = _result_for(
        results,
        "day6_clarification_missing_date_days",
        "adaptive_multi_agent",
    )
    output = result.get("output") or {}
    audit = result.get("run_audit") or {}
    metrics = audit.get("metrics") if isinstance(audit.get("metrics"), dict) else {}
    scheduler = (output.get("metadata") or {}).get("adaptive_scheduler") or {}
    ticket = scheduler.get("ticket") if isinstance(scheduler.get("ticket"), dict) else {}
    decision = scheduler.get("decision") if isinstance(scheduler.get("decision"), dict) else {}
    if output.get("execution_status") != "clarification":
        raise RuntimeError("Day6 M3 clarification case must return clarification status")
    if ticket.get("task_type") != "clarification":
        raise RuntimeError("Day6 M3 clarification ticket must be clarification")
    if decision.get("planned_agents") or decision.get("planned_tools"):
        raise RuntimeError("Day6 M3 clarification must not plan agents or tools")
    if metrics.get("planned_agent_count") != 0 or metrics.get("called_tool_count") != 0:
        raise RuntimeError("Day6 M3 clarification audit must not record business execution")


def _validate_formal_turn_scenarios(
    results: List[Dict[str, Any]],
    benchmark_doc: Dict[str, Any],
) -> None:
    if "previous_state_fixture" in json.dumps(benchmark_doc, ensure_ascii=False):
        raise RuntimeError("Day6 benchmark must not contain previous_state_fixture")
    scenarios = [
        case
        for case in benchmark_doc.get("cases") or []
        if isinstance(case, dict) and isinstance(case.get("turns"), list)
    ]
    if len(scenarios) < 3:
        raise RuntimeError("Day6 acceptance must include at least three formal turn scenarios")
    required = {
        "day6_scenario_people_change",
        "day6_scenario_rain_day2",
        "day6_scenario_repeat_request",
    }
    if required - {str(case.get("case_id") or "") for case in scenarios}:
        raise RuntimeError("Day6 acceptance missing required formal turn scenarios")
    for scenario in scenarios:
        scenario_id = str(scenario.get("case_id") or "")
        turns = scenario.get("turns") or []
        if len(turns) < 2:
            raise RuntimeError(f"Day6 scenario must contain at least two turns: {scenario_id}")
        target_turns = [
            str(turn.get("turn_id") or "")
            for turn in turns
            if turn.get("target_turn") is True
        ]
        if len(target_turns) != 1:
            raise RuntimeError(f"Day6 scenario must mark exactly one target turn: {scenario_id}")
        for method in ExperimentRunner.METHODS:
            method_results = [
                result
                for result in results
                if result.get("case_id") == scenario_id and result.get("method") == method
            ]
            if len(method_results) != len(turns):
                raise RuntimeError(f"Day6 scenario did not run all turns for {method}: {scenario_id}")
            first = _result_for(results, scenario_id, method, turn_id=str(turns[0].get("turn_id")))
            second = _result_for(results, scenario_id, method, turn_id=target_turns[0])
            if first.get("target_turn") is not False or second.get("target_turn") is not True:
                raise RuntimeError(f"Day6 scenario target_turn metadata mismatch: {scenario_id}/{method}")
    _validate_m0_m1_turn_history(results)
    _validate_people_change_reuse(results)
    _validate_rain_turn_reuse(results)
    _validate_repeat_turn_reuse(results)


def _validate_m0_m1_turn_history(results: List[Dict[str, Any]]) -> None:
    for scenario_id, turn_id in (
        ("day6_scenario_people_change", "t2_people_change"),
        ("day6_scenario_rain_day2", "t2_rain_day2"),
        ("day6_scenario_repeat_request", "t2_repeat_same"),
    ):
        for method in ("llm_direct", "single_agent"):
            result = _result_for(results, scenario_id, method, turn_id=turn_id)
            model_meta = (
                ((result.get("raw_output") or {}).get("metadata") or {})
                .get("model_metadata")
                or {}
            )
            if model_meta.get("dialogue_history_count", 0) < 2:
                raise RuntimeError(f"Day6 {method} target turn did not receive dialogue history")
            if model_meta.get("assistant_history_seen") is not True:
                raise RuntimeError(f"Day6 {method} target turn did not receive its own previous answer")
            if model_meta.get("previous_state_method") != method:
                raise RuntimeError(f"Day6 {method} target turn did not receive method-local previous state")
            if not str(model_meta.get("previous_state_turn_id") or "").startswith("t1"):
                raise RuntimeError(f"Day6 {method} previous state did not come from turn 1")


def _validate_people_change_reuse(results: List[Dict[str, Any]]) -> None:
    m2 = _result_for(results, "day6_scenario_people_change", "fixed_multi_agent", turn_id="t2_people_change")
    m3 = _result_for(results, "day6_scenario_people_change", "adaptive_multi_agent", turn_id="t2_people_change")
    m2_audit = (m2.get("run_audit") or {}).get("metrics") or {}
    m3_audit = (m3.get("run_audit") or {}).get("metrics") or {}
    m3_metrics = m3.get("metrics") or {}
    m2_scheduler = ((m2.get("output") or {}).get("metadata") or {}).get("fixed_template_scheduler") or {}
    m2_decision = m2_scheduler.get("decision") if isinstance(m2_scheduler.get("decision"), dict) else {}

    if m2_scheduler.get("name") != "fixed_template_scheduler":
        raise RuntimeError("Day6 M2 people-change case did not record fixed-template scheduler metadata")
    if m2_decision.get("planned_agents") != ["itinerary", "budget"]:
        raise RuntimeError("Day6 M2 people-change case did not use the fixed people-change template")
    if m2_decision.get("planned_tools") != ["budget_calculator"]:
        raise RuntimeError("Day6 M2 people-change case did not use the fixed people-change tool template")
    if m2_decision.get("reused_agents") not in ([], None):
        raise RuntimeError("Day6 M2 people-change case must not reuse previous agents")
    if "budget" not in set(m3_metrics.get("m3_planned_agents") or []):
        raise RuntimeError("Day6 M3 people-change case did not plan budget agent")
    if "attraction" not in set(m3_metrics.get("m3_reused_agents") or []):
        raise RuntimeError("Day6 M3 people-change case did not reuse attraction result")
    if m3_audit.get("planned_agent_count", 0) > m2_audit.get("planned_agent_count", 0):
        raise RuntimeError("Day6 M3 people-change case planned more agents than the M2 fixed template")
    if m3_audit.get("called_tool_count", 0) > m2_audit.get("called_tool_count", 0):
        raise RuntimeError("Day6 M3 people-change case called more tools than the M2 fixed template")


def _validate_rain_turn_reuse(results: List[Dict[str, Any]]) -> None:
    m3 = _result_for(results, "day6_scenario_rain_day2", "adaptive_multi_agent", turn_id="t2_rain_day2")
    scheduler = ((m3.get("output") or {}).get("metadata") or {}).get("adaptive_scheduler") or {}
    ticket = scheduler.get("ticket") if isinstance(scheduler.get("ticket"), dict) else {}
    decision = scheduler.get("decision") if isinstance(scheduler.get("decision"), dict) else {}
    metrics = m3.get("metrics") or {}
    if ticket.get("task_type") != "weather_adjustment":
        raise RuntimeError("Day6 rain target turn was not recognized as weather_adjustment")
    if set(decision.get("planned_agents") or []) != {"itinerary", "budget"}:
        raise RuntimeError("Day6 rain target turn must plan itinerary and budget agents")
    if set(decision.get("planned_tools") or []) != {"budget_calculator"}:
        raise RuntimeError("Day6 rain target turn must call only budget_calculator")
    if "attraction" not in set(metrics.get("m3_reused_agents") or []):
        raise RuntimeError("Day6 rain target turn did not reuse attraction")
    if "weather" not in set(metrics.get("m3_reused_agents") or []):
        raise RuntimeError("Day6 rain target turn did not reuse weather")
    adjustments = (m3.get("output") or {}).get("weather_adjustments") or []
    if not any(
        isinstance(item, dict) and item.get("day") == 2 and item.get("day_index") == 2
        for item in adjustments
    ):
        raise RuntimeError("Day6 rain target turn must report weather_adjustments day/day_index=2")


def _validate_repeat_turn_reuse(results: List[Dict[str, Any]]) -> None:
    m2 = _result_for(results, "day6_scenario_repeat_request", "fixed_multi_agent", turn_id="t2_repeat_same")
    m3 = _result_for(results, "day6_scenario_repeat_request", "adaptive_multi_agent", turn_id="t2_repeat_same")
    m2_audit = (m2.get("run_audit") or {}).get("metrics") or {}
    m3_audit = (m3.get("run_audit") or {}).get("metrics") or {}
    metrics = m3.get("metrics") or {}
    if set(metrics.get("m3_reused_agents") or []) != {"attraction", "weather", "itinerary", "budget"}:
        raise RuntimeError("Day6 repeat target turn did not reuse all M3 agent results")
    if m3_audit.get("planned_agent_count") != 0 or m3_audit.get("called_tool_count") != 0:
        raise RuntimeError("Day6 repeat target turn must not re-run M3 agents or tools")
    if m2_audit.get("planned_agent_count", 0) <= m3_audit.get("planned_agent_count", 0):
        raise RuntimeError("Day6 repeat target turn did not reduce agents vs M2")
    if m2_audit.get("called_tool_count", 0) <= m3_audit.get("called_tool_count", 0):
        raise RuntimeError("Day6 repeat target turn did not reduce tools vs M2")


def _render_report(
    run_id: str,
    results: List[Dict[str, Any]],
    manifest: Dict[str, Any],
    summary: Dict[str, Any],
    acceptance_gate: Dict[str, Any],
    saved_evidence: Dict[str, Any],
) -> str:
    methods = summary.get("methods") or {}
    alignment = acceptance_gate.get("task_type_alignment") or {}
    stsr = acceptance_gate.get("stsr") or {}
    git = manifest.get("git") if isinstance(manifest.get("git"), dict) else {}
    people_reuse = _result_for(
        results,
        "day6_scenario_people_change",
        "adaptive_multi_agent",
        turn_id="t2_people_change",
    )
    people_metrics = people_reuse.get("metrics") or {}
    m3_costs = (
        ((summary.get("scenario_costs") or {}).get("methods") or {})
        .get("adaptive_multi_agent")
        or {}
    )
    lines = [
        "# Day 6 离线验收运行报告",
        "",
        "## Run conclusion",
        "",
        "# Day 6 验收报告",
        "",
        "- status: `passed`",
        f"- run_id: `{run_id}`",
        f"- result_count: {len(results)}",
        f"- expected_count: {saved_evidence.get('expected_count')}",
        f"- output_dir: `{saved_evidence.get('output_dir')}`",
        f"- git_commit: `{manifest.get('git_commit') or git.get('commit')}`",
        f"- working_tree_clean: `{manifest.get('working_tree_clean')}`",
        f"- method_contract: `{manifest.get('method_fairness_contract', {}).get('contract_id')}`",
        f"- run_audit_schema: `{RUN_AUDIT_SCHEMA_VERSION}`",
        f"- output_schema: `{EXPERIMENT_OUTPUT_SCHEMA_VERSION}`",
        f"- method_input_schema: `{METHOD_INPUT_SCHEMA_VERSION}`",
        f"- acceptance_level: `{acceptance_gate.get('acceptance_level')}`",
        f"- academic_quality_status: `{acceptance_gate.get('academic_quality_status')}`",
        f"- saved_evidence_status: `{saved_evidence.get('status')}`",
        f"- trace_dir: `{saved_evidence.get('trace_dir')}`",
        f"- trace_file_count: `{saved_evidence.get('trace_file_count')}`",
        f"- representative_trace: `{saved_evidence.get('representative_trace')}`",
        f"- task_type_alignment: `{alignment.get('status')}` "
        f"({alignment.get('checked_unit_count')} checked, {alignment.get('mismatch_count')} mismatches)",
        f"- fake_llm_stsr: `{stsr.get('true_count')}/{stsr.get('total_count')}` "
        f"({stsr.get('rate')}); `{stsr.get('interpretation')}`",
        f"- multi_turn_quality_scope: `{(summary.get('quality_evaluation_scope') or {}).get('multi_turn')}`",
        f"- m3_people_change_planned_agents: `{people_metrics.get('m3_planned_agents')}`",
        f"- m3_people_change_reused_agents: `{people_metrics.get('m3_reused_agents')}`",
        f"- m3_target_increment_llm_calls_mean: `{m3_costs.get('target_increment_llm_call_count_mean')}`",
        f"- m3_scenario_total_llm_calls_mean: `{m3_costs.get('scenario_total_llm_call_count_mean')}`",
        "",
        "> STSR values in this Day6 report are FakeLLM diagnostics only, not academic-quality model results.",
        "",
    ]
    lines.extend(
        [
            "## Saved evidence files",
            "",
            "| artifact | path |",
            "|---|---|",
        ]
    )
    for key, path in (saved_evidence.get("required_files") or {}).items():
        lines.append(f"| {key} | `{path}` |")
    lines.extend(
        [
            "",
            "## Method summary",
            "",
            "| method | cases | STSR | LLM calls | Prompt tokens | Called tools |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for method in ExperimentRunner.METHODS:
        row = methods.get(method) or {}
        lines.append(
            f"| {method} | {row.get('case_count')} | {_fmt(row.get('stsr_rate'))} "
            f"| {_fmt(row.get('llm_call_count_mean'))} | {_fmt(row.get('prompt_tokens_mean'))} "
            f"| {_fmt(row.get('called_tool_count_mean'))} |"
        )
    return "\n".join(lines) + "\n"


def _tool_arguments(name: str, text: str) -> Dict[str, Any]:
    days = 2 if _contains_any(text, ("两天", "2天", "two-day", "two day")) else 3
    people_count = 3 if _contains_any(text, ("3人", "三人", "three people")) else 2
    if name == "poi_search":
        return {"city": "Hangzhou", "preferences": [], "people": "general", "limit": max(3, days * 2)}
    if name == "weather_query":
        scenario_type = "rain" if _contains_any(text, ("rain", "rainy", "涓嬮洦", "闆ㄥぉ")) else "sunny"
        return {
            "city": "Hangzhou",
            "date": "2026-08-07",
            "days": days,
            "scenario_type": scenario_type,
        }
    if name == "budget_calculator":
        return {
            "city": "Hangzhou",
            "people_count": people_count,
            "days": days,
            "attractions": ["hz001", "hz002"],
            "spending_level": "medium",
        }
    return {}


def _result_for(
    results: List[Dict[str, Any]],
    case_id: str,
    method: str,
    *,
    turn_id: Optional[str] = None,
) -> Dict[str, Any]:
    for result in results:
        if result.get("case_id") != case_id or result.get("method") != method:
            continue
        if turn_id is not None and result.get("turn_id") != turn_id:
            continue
        return result
    suffix = f"/{turn_id}" if turn_id else ""
    raise RuntimeError(f"Day6 result not found: {case_id}/{method}{suffix}")


def _expected_count(benchmark_doc: Dict[str, Any]) -> int:
    return _generation_unit_count(benchmark_doc) * len(ExperimentRunner.METHODS)


def _case_count(summary_or_doc: Dict[str, Any]) -> int:
    if "cases" in summary_or_doc:
        return _quality_unit_count(summary_or_doc)
    return int(summary_or_doc.get("unique_case_count") or 0)


def _generation_unit_count(benchmark_doc: Dict[str, Any]) -> int:
    count = 0
    for case in benchmark_doc.get("cases") or []:
        turns = case.get("turns") if isinstance(case, dict) else None
        count += len(turns) if isinstance(turns, list) and turns else 1
    return count


def _quality_unit_count(benchmark_doc: Dict[str, Any]) -> int:
    return len(_quality_units(benchmark_doc))


def _quality_units(benchmark_doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    units: List[Dict[str, Any]] = []
    for case in benchmark_doc.get("cases") or []:
        if not isinstance(case, dict):
            continue
        turns = case.get("turns")
        if isinstance(turns, list) and turns:
            targets = [
                turn
                for turn in turns
                if isinstance(turn, dict) and turn.get("target_turn") is True
            ]
            units.extend(targets or [turn for turn in turns if isinstance(turn, dict)][-1:])
        else:
            units.append(case)
    return units


def _target_quality_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [result for result in results if result.get("target_turn") is not False]


def _build_saved_evidence(
    *,
    output_dir: Path,
    benchmark_path: Path,
    report_path: Path,
    results: List[Dict[str, Any]],
    expected_count: int,
    require_report: bool,
) -> Dict[str, Any]:
    required_files = {
        "benchmark": benchmark_path,
        "benchmark_results_json": output_dir / "benchmark_results.json",
        "benchmark_results_csv": output_dir / "benchmark_results.csv",
        "evaluation_summary": output_dir / "evaluation_summary.json",
        "paper_tables": output_dir / "paper_tables.md",
        "experiment_manifest": output_dir / "experiment_manifest.json",
        "day6_acceptance_report": report_path,
    }
    required_for_check = dict(required_files)
    if not require_report:
        required_for_check.pop("day6_acceptance_report", None)
    missing_files = [
        key
        for key, path in required_for_check.items()
        if not Path(path).exists()
    ]

    trace_dir = output_dir / "traces"
    trace_files = sorted(trace_dir.glob("*.jsonl")) if trace_dir.exists() else []
    result_trace_files = [_resolve_trace_path(result.get("trace_file")) for result in results]
    result_trace_files = [path for path in result_trace_files if path is not None]
    missing_result_traces = [
        str(result.get("trace_file") or "")
        for result in results
        if not _trace_reference_exists(result.get("trace_file"))
    ]
    trace_file_paths = [path.as_posix() for path in trace_files]
    return {
        "schema_version": "day6-saved-evidence-v1",
        "status": "saved" if not missing_files and not missing_result_traces and trace_files else "incomplete",
        "output_dir": output_dir.as_posix(),
        "required_files": {
            key: Path(path).as_posix()
            for key, path in required_files.items()
        },
        "missing_required_files": missing_files,
        "result_count": len(results),
        "expected_count": expected_count,
        "trace_dir": trace_dir.as_posix(),
        "trace_file_count": len(trace_files),
        "result_trace_reference_count": len(result_trace_files),
        "missing_result_traces": missing_result_traces,
        "representative_trace": trace_file_paths[0] if trace_file_paths else None,
        "trace_files": trace_file_paths,
    }


def _validate_saved_evidence(evidence: Dict[str, Any]) -> None:
    if evidence.get("status") != "saved":
        raise RuntimeError(
            "Day6 saved evidence is incomplete: "
            f"missing_files={evidence.get('missing_required_files') or []}; "
            f"missing_traces={evidence.get('missing_result_traces') or []}"
        )
    if evidence.get("result_count") != evidence.get("expected_count"):
        raise RuntimeError("Day6 saved evidence result count mismatch")
    if int(evidence.get("trace_file_count") or 0) < int(evidence.get("result_count") or 0):
        raise RuntimeError("Day6 saved evidence must include at least one trace per result")
    if int(evidence.get("result_trace_reference_count") or 0) != int(evidence.get("result_count") or 0):
        raise RuntimeError("Day6 saved evidence missing per-result trace references")
    if not evidence.get("representative_trace"):
        raise RuntimeError("Day6 saved evidence missing representative trace")


def _attach_acceptance_evidence(
    *,
    manifest: Dict[str, Any],
    acceptance_gate: Dict[str, Any],
    saved_evidence: Dict[str, Any],
    result_count: int,
    expected_count: int,
) -> Dict[str, Any]:
    updated = dict(manifest)
    results = dict(updated.get("results") or {})
    for key, value in (saved_evidence.get("required_files") or {}).items():
        results[key] = value
    results["trace_dir"] = saved_evidence.get("trace_dir")
    results["representative_trace"] = saved_evidence.get("representative_trace")
    updated["results"] = results
    updated["day6_acceptance"] = {
        "schema_version": DAY6_ACCEPTANCE_GATE_SCHEMA_VERSION,
        "status": "passed",
        "acceptance_level": acceptance_gate.get("acceptance_level"),
        "academic_quality_status": acceptance_gate.get("academic_quality_status"),
        "result_count": result_count,
        "expected_count": expected_count,
        "quality_gate": acceptance_gate,
        "saved_evidence": saved_evidence,
    }
    return updated


def _resolve_trace_path(value: Any) -> Optional[Path]:
    if not value:
        return None
    path = Path(str(value))
    if path.is_absolute():
        return path
    candidate = ROOT / path
    if candidate.exists():
        return candidate
    return path


def _trace_reference_exists(value: Any) -> bool:
    path = _resolve_trace_path(value)
    return bool(path and path.exists())


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _agent_decision_answer(messages: List[Any]) -> Optional[str]:
    context = _agent_context_from_messages(messages)
    if not context:
        return None
    agent_name = str(context.get("agent_name") or "")
    tool_evidence = context.get("tool_evidence") if isinstance(context.get("tool_evidence"), dict) else {}
    poi_data = _tool_data(tool_evidence.get("poi_search"))
    attractions = [
        item
        for item in (poi_data.get("attractions") if isinstance(poi_data, dict) else []) or []
        if isinstance(item, dict)
    ]
    selected_ids = [str(item.get("poi_id")) for item in attractions[:4] if item.get("poi_id")]
    weather_data = _tool_data(tool_evidence.get("weather_query"))
    daily_weather = (
        weather_data.get("daily_weather")
        if isinstance(weather_data.get("daily_weather"), list)
        else []
    )
    risk_days = []
    for index, item in enumerate(daily_weather, start=1):
        if not isinstance(item, dict):
            continue
        weather_text = json.dumps(item, ensure_ascii=False).casefold()
        if _contains_any(
            weather_text,
            ("rain", "rainy", "high_temperature", "low_temperature", "continuous_change"),
        ):
            risk_days.append(int(item.get("day_index") or item.get("day") or index))
    days = _positive_int(
        ((context.get("task_slots") or {}).get("duration_days") if isinstance(context.get("task_slots"), dict) else None),
        default=max(1, len(daily_weather) or 2),
    )
    if not risk_days and weather_data.get("weather_adjustment_required"):
        risk_days = [1]

    decisions: Dict[str, Any]
    if agent_name == "attraction":
        decisions = {"selected_poi_ids": selected_ids, "ranking_reason": "offline evidence order"}
    elif agent_name == "weather":
        decisions = {
            "risk_days": risk_days,
            "adjustment_required": bool(risk_days or weather_data.get("weather_adjustment_required")),
        }
    elif agent_name == "itinerary":
        decisions = {
            "daily_itinerary": [
                {
                    "day": day,
                    "attraction_poi_ids": selected_ids[(day - 1) * 2 : day * 2] or selected_ids[:1],
                    "notes": "fake LLM assigns evidence-backed POIs to this day",
                }
                for day in range(1, days + 1)
            ]
        }
    elif agent_name == "budget":
        budget_data = _tool_data(tool_evidence.get("budget_calculator"))
        decisions = {
            "feasibility": "feasible",
            "budget_notes": "based on offline budget calculator evidence",
            "recommended_total": budget_data.get("total"),
        }
    else:
        return None

    return json.dumps(
        {
            "schema_version": RESEARCH_AGENT_DECISION_SCHEMA_VERSION,
            "agent_name": agent_name,
            "summary": f"{agent_name} decision generated by Day6OfflineLLM",
            "decisions": decisions,
            "risks": [],
            "confidence": 1.0,
        },
        ensure_ascii=False,
    )


def _agent_context_from_messages(messages: List[Any]) -> Dict[str, Any]:
    for message in reversed(messages):
        content = str(getattr(message, "content", "") or "")
        if not content.strip().startswith("{"):
            continue
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("agent_name"):
            return payload
    return {}


def _tool_data(result: Any) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    data = result.get("data")
    return data if isinstance(data, dict) else {}


def _structured_llm_acceptance_answer(text: str) -> Optional[str]:
    prompt = _structured_prompt_payload(text)
    if not prompt:
        return None
    method = str(prompt.get("method") or "llm_direct")
    case_id = str(prompt.get("case_id") or "")
    slots = prompt.get("visible_slots") if isinstance(prompt.get("visible_slots"), dict) else {}
    dialogue_history = prompt.get("dialogue_history") if isinstance(prompt.get("dialogue_history"), list) else []
    previous_state = (
        prompt.get("method_previous_state")
        if isinstance(prompt.get("method_previous_state"), dict)
        else {}
    )
    previous_summary = (
        prompt.get("method_previous_state_summary")
        if isinstance(prompt.get("method_previous_state_summary"), dict)
        else {}
    )
    days = _positive_int(
        slots.get("duration_days"),
        slots.get("duration"),
        slots.get("days"),
        default=2,
    )
    city = str(slots.get("destination") or "hangzhou")
    people = _positive_int(
        slots.get("people_count"),
        slots.get("num_travelers"),
        default=2,
    )
    budget_total = min(
        _positive_int(slots.get("budget_amount"), default=5000),
        4800,
    )
    attractions = [
        {"name": "West Lake", "city": city, "source": "structured_llm"},
        {"name": "Lingyin Temple", "city": city, "source": "structured_llm"},
    ]
    daily_itinerary = [
        {
            "day": day,
            "attractions": [attractions[(day - 1) % len(attractions)]],
            "notes": "offline structured single-method decision",
        }
        for day in range(1, days + 1)
    ]
    task_type = str((prompt.get("output_template") or {}).get("task_type") or "trip_planning")
    user_request = str(prompt.get("user_request") or "").casefold()
    clarification_fields = _clarification_fields(slots)
    weather_adjustments = []
    if task_type == "weather_adjustment" or "rain" in user_request or "rainy" in user_request:
        weather_adjustments = [
            {
                "day": 2 if "second day" in user_request else 1,
                "day_index": 2 if "second day" in user_request else 1,
                "reason": "rain",
                "action": "prefer indoor or lower-risk attractions for the affected day",
            }
        ]
    execution_status = "clarification" if task_type == "clarification" else "completed"
    final_answer = "Day6 离线验收结构化回答：已输出可评价 JSON。"
    if task_type == "clarification":
        final_answer = (
            "Please provide "
            + ", ".join(field.replace("_", " ") for field in clarification_fields)
            + " before I generate the travel plan."
        )

    payload = {
        "schema_version": EXPERIMENT_OUTPUT_SCHEMA_VERSION,
        "case_id": case_id,
        "method": method,
        "task_type": task_type,
        "planned_agents": ["single_agent"] if method == "single_agent" else [],
        "used_agents": ["single_agent"] if method == "single_agent" else [],
        "planned_tools": [],
        "called_tools": [],
        "tool_results": {},
        "attractions": attractions,
        "trip_days": days,
        "daily_itinerary": daily_itinerary,
        "budget": {
            "city": city,
            "people_count": people,
            "days": days,
            "total": budget_total,
        },
        "weather": {
            "city": city,
            "scenario_type": str(slots.get("weather_scenario") or "sunny"),
            "daily_weather": [
                {"day": day, "condition": str(slots.get("weather_scenario") or "sunny")}
                for day in range(1, days + 1)
            ],
        },
        "weather_adjustments": weather_adjustments,
        "execution_status": execution_status,
        "final_answer": final_answer,
        "metadata": {
            "structured_by_llm": True,
            "prompt_version": STRUCTURED_LLM_OUTPUT_PROMPT_VERSION,
            "clarification_fields": clarification_fields if task_type == "clarification" else [],
            "dialogue_history_count": len(dialogue_history),
            "assistant_history_seen": any(
                isinstance(item, dict) and str(item.get("role") or "").lower() == "assistant"
                for item in dialogue_history
            ),
            "previous_state_method": previous_summary.get("method") or previous_state.get("method"),
            "previous_state_turn_id": previous_summary.get("turn_id") or previous_state.get("turn_id"),
        },
    }
    if _contains_any(str(prompt.get("user_request") or "").casefold(), ("你好", "hello", "打个招呼")):
        payload.update(
            {
                "task_type": "general_chat",
                "attractions": [],
                "trip_days": None,
                "daily_itinerary": [],
                "budget": None,
                "weather": None,
                "final_answer": "你好。该请求不需要旅游业务 Agent 或工具。",
            }
        )
    if task_type == "clarification":
        payload.update(
            {
                "attractions": [],
                "trip_days": None,
                "daily_itinerary": [],
                "budget": None,
                "weather": None,
                "weather_adjustments": [],
            }
        )
    return json.dumps(payload, ensure_ascii=False)


def _structured_prompt_payload(text: str) -> Dict[str, Any]:
    marker = f'"prompt_version": "{STRUCTURED_LLM_OUTPUT_PROMPT_VERSION}"'
    marker_index = text.find(marker)
    if marker_index < 0:
        return {}
    start = text.rfind("{", 0, marker_index)
    if start < 0:
        return {}
    try:
        parsed, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _positive_int(*values: Any, default: int) -> int:
    for value in values:
        if value is None or value == "":
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return default


def _clarification_fields(slots: Dict[str, Any]) -> List[str]:
    return [
        field
        for field in ("destination", "start_date", "duration_days")
        if not slots.get(field)
    ]


def _messages_text(messages: Iterable[Any]) -> str:
    return "\n".join(str(getattr(message, "content", "") or "") for message in messages)


def _prompt_hash(messages: List[Any], tools: Optional[List[Any]]) -> str:
    payload = {
        "messages": [
            message.to_dict() if hasattr(message, "to_dict") else {
                "role": getattr(message, "role", None),
                "content": getattr(message, "content", None),
            }
            for message in messages
        ],
        "tools": [
            tool.to_dict() if hasattr(tool, "to_dict") else str(tool)
            for tool in (tools or [])
        ],
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _prompt_version(messages: List[Any]) -> str:
    versions: List[str] = []
    for message in messages:
        content = str(getattr(message, "content", "") or "")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("prompt_version"):
            versions.append(str(parsed["prompt_version"]))
        for marker in (
            STRUCTURED_LLM_OUTPUT_PROMPT_VERSION,
            "ctp-research-agent-prompts-v1",
        ):
            if marker in content and marker not in versions:
                versions.append(marker)
    return "+".join(versions) if versions else "day6-offline-unversioned"


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(term.casefold() in text for term in terms)


def _fmt(value: Any) -> str:
    return "" if value is None else str(value)


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
