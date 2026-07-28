"""Run Day 5 independent-evaluation acceptance without LLM or external APIs."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.experiment_runner import ExperimentRunner
from app.core.independent_evaluator import (
    EVALUATION_SCHEMA_VERSION,
    EVALUATION_SUMMARY_SCHEMA_VERSION,
    load_rule_catalog,
)
from app.core.tracing import (
    finish_agent_run,
    get_current_trace,
    record_planned_tools,
    record_tool_call,
    set_trace_planned_agents,
    start_agent_run,
)
from app.tools.research_tools import GENERATION_TOOL_NAMES


DEFAULT_OUTPUT_ROOT = ROOT / "experiments" / "results" / "day5_acceptance"
BENCHMARK_PATH = ROOT / "experiments" / "day5_evaluation_acceptance_cases.json"
AGENTS = ["attraction", "weather", "itinerary", "budget"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", type=str, default=None)
    args = parser.parse_args()

    run_id = args.run_id or f"day5_acceptance_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    output_dir = args.output_dir if args.output_dir.name == run_id else args.output_dir / run_id
    if output_dir.exists() and any(output_dir.iterdir()):
        raise RuntimeError(f"Day5 acceptance output directory is not empty: {output_dir}")

    os.environ["EXPERIMENT_STRICT_MODE"] = "true"
    os.environ["EXPERIMENT_DISABLE_CACHE"] = "true"
    os.environ["LLM_MODEL"] = "offline-static-model"
    os.environ["LLM_TEMPERATURE"] = "0"

    runner = ExperimentRunner(
        trace_dir=output_dir / "traces",
        output_dir=output_dir,
        method_handlers={method: _handler_for(method) for method in ExperimentRunner.METHODS},
        run_id=run_id,
        model_config_name="day5-acceptance-offline",
    )
    results = runner.run_benchmark(BENCHMARK_PATH, repeats=1)
    manifest = _read_json(output_dir / "experiment_manifest.json")
    summary = _read_json(output_dir / "evaluation_summary.json")
    _validate_acceptance(results, manifest, summary)

    report_path = output_dir / "day5_acceptance_report.md"
    report_path.write_text(_render_report(run_id, results, manifest, summary), encoding="utf-8")
    payload = {
        "status": "passed",
        "run_id": run_id,
        "output_dir": output_dir.as_posix(),
        "result_count": len(results),
        "expected_count": _expected_count(),
        "summary": (output_dir / "evaluation_summary.json").as_posix(),
        "paper_tables": (output_dir / "paper_tables.md").as_posix(),
        "manifest": (output_dir / "experiment_manifest.json").as_posix(),
        "report": report_path.as_posix(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _handler_for(method: str):
    async def _handler(case: Dict[str, Any]) -> Dict[str, Any]:
        task_type = str(case.get("task_type") or "trip_planning")
        agents, tools = _method_scope(method, task_type)
        _record_trace(agents, tools)

        output: Dict[str, Any] = {
            "task_type": task_type,
            "planned_agents": agents,
            "used_agents": agents,
            "planned_tools": tools,
            "called_tools": [_tool_call(name) for name in tools],
            "tool_results": {},
            "attractions": [],
            "daily_itinerary": [],
            "budget": None,
            "weather": None,
            "weather_adjustments": [],
            "constraint_report": _constraint_report(),
            "final_answer": "Offline Day5 acceptance answer.",
        }
        _fill_task_output(output, case)
        output["tool_results"] = _tool_results(tools, output)
        return output

    return _handler


def _method_scope(method: str, task_type: str) -> tuple[List[str], List[str]]:
    task_agents, task_tools = _task_scope(task_type)
    if task_type in {"clarification", "general_chat"} or method == "llm_direct":
        return [], []
    if method == "single_agent":
        return ["single_agent"], task_tools
    return task_agents, task_tools


def _task_scope(task_type: str) -> tuple[List[str], List[str]]:
    scopes = {
        "trip_planning": (list(AGENTS), list(GENERATION_TOOL_NAMES)),
        "attraction_recommendation": (["attraction"], ["poi_search"]),
        "weather_query": (["weather"], ["weather_query"]),
        "budget_query": (["budget"], ["budget_calculator"]),
        "partial_replan": (["attraction", "itinerary", "budget"], ["poi_search", "budget_calculator"]),
        "weather_adjustment": (["weather", "itinerary"], ["weather_query"]),
    }
    return scopes.get(task_type, ([], []))


def _fill_task_output(output: Dict[str, Any], case: Dict[str, Any]) -> None:
    task_type = output["task_type"]
    if task_type == "general_chat":
        output["final_answer"] = "Hello. No travel execution is needed."
        return
    if task_type == "clarification":
        missing = (case.get("expected") or {}).get("missing_slots") or []
        output["execution_status"] = "clarification"
        output["metadata"] = {"clarification_fields": missing}
        output["final_answer"] = "Please provide start_date and duration_days before planning."
        return
    if task_type == "attraction_recommendation":
        output["attractions"] = _attractions()[:2]
        output["final_answer"] = "Recommended attractions: West Lake and Lingyin Temple."
        return
    if task_type == "weather_query":
        output["weather"] = _weather()
        output["final_answer"] = "Hangzhou weather evidence: day 1 sunny and day 2 sunny."
        return
    if task_type == "budget_query":
        output["budget"] = {"total": 900, "spending_level": "standard"}
        output["final_answer"] = "The estimated budget total is 900, within the 1000 limit."
        return
    if task_type == "partial_replan":
        output["attractions"] = _attractions()
        output["trip_days"] = 3
        output["daily_itinerary"] = [
            {"day": 1, "attractions": [_attractions()[0]]},
            {"day": 2, "attractions": [_attractions()[1]]},
            {"day": 3, "attractions": [_attractions()[2]]},
        ]
        output["budget"] = {"total": 950, "spending_level": "standard"}
        output["metadata"] = {"scheduler": {"ticket": {"changed_slots": ["duration_days"], "preserved_slots": ["budget_level"]}}}
        output["final_answer"] = "Three-day replan: West Lake, Lingyin Temple and Hefang Street. Budget total 950, standard level."
        return
    if task_type == "weather_adjustment":
        output["attractions"] = _attractions()[:2]
        output["trip_days"] = 2
        output["daily_itinerary"] = [
            {"day": 1, "attractions": [_attractions()[0]]},
            {"day": 2, "attractions": [_attractions()[1]]},
        ]
        output["budget"] = {"total": 900, "spending_level": "standard"}
        output["weather"] = _weather(day2="rain")
        output["weather_adjustments"] = [{"day": 2, "reason": "rain", "action": "keep indoor-friendly timing"}]
        output["final_answer"] = "Weather rain adjustment on day 2 keeps West Lake and Lingyin Temple. Budget total 900."
        return
    output["attractions"] = _attractions()[:2]
    output["trip_days"] = 2
    output["daily_itinerary"] = [
        {"day": 1, "attractions": [_attractions()[0]]},
        {"day": 2, "attractions": [_attractions()[1]]},
    ]
    output["budget"] = {"total": 900, "spending_level": "standard"}
    output["weather"] = _weather()
    output["final_answer"] = "Two-day trip: West Lake and Lingyin Temple. Budget total 900, weather sunny."


def _record_trace(agents: List[str], tools: List[str]) -> None:
    trace = get_current_trace()
    if trace is not None:
        trace.mark_first_body_token()
    set_trace_planned_agents(agents)
    record_planned_tools(tools)
    for agent in agents:
        run = start_agent_run(agent)
        finish_agent_run(run, agent_name=agent, tool_count=0, status="completed")
    for tool in tools:
        record_tool_call(
            tool,
            params={},
            duration_ms=0,
            status="completed",
            success=True,
            agent=_tool_agent(tool),
        )


def _tool_agent(tool: str) -> str:
    return {
        "poi_search": "attraction",
        "weather_query": "weather",
        "budget_calculator": "budget",
    }.get(tool, "unknown")


def _attractions() -> List[Dict[str, str]]:
    return [
        {"poi_id": "hz001", "name": "West Lake"},
        {"poi_id": "hz002", "name": "Lingyin Temple"},
        {"poi_id": "hz003", "name": "Hefang Street"},
    ]


def _weather(day2: str = "sunny") -> Dict[str, Any]:
    return {
        "city": "hangzhou",
        "daily_weather": [
            {"day_index": 1, "state": "sunny"},
            {"day_index": 2, "state": day2},
        ],
    }


def _tool_call(name: str) -> Dict[str, Any]:
    return {"tool_name": name, "status": "completed", "success": True, "arguments": {}}


def _tool_results(tools: List[str], output: Dict[str, Any]) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    for name in tools:
        if name == "poi_search":
            data = {"city": "hangzhou", "attractions": output.get("attractions") or _attractions()}
        elif name == "weather_query":
            data = output.get("weather") or _weather()
        elif name == "budget_calculator":
            data = output.get("budget") or {"total": 900, "spending_level": "standard"}
        else:
            data = {}
        results[name] = _tool_result(name, data)
    return results


def _tool_result(name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    result = {
        "schema_version": "research_tool_result_v1",
        "tool_name": name,
        "status": "success",
        "success": True,
        "data": data,
        "metadata": {"offline": True, "source_mode": "day5_acceptance_fixture"},
    }
    if name == "budget_calculator":
        result["input"] = {"spending_level": data.get("spending_level"), "days": data.get("days")}
    return result


def _constraint_report() -> Dict[str, Any]:
    return {
        "data": {
            "checks": [
                {"name": "poi_existence", "status": "passed", "details": {}},
                {"name": "rain_attraction_suitability", "status": "NA", "details": {}},
                {"name": "senior_accessibility", "status": "NA", "details": {}},
            ]
        }
    }


def _validate_acceptance(results: List[Dict[str, Any]], manifest: Dict[str, Any], summary: Dict[str, Any]) -> None:
    catalog = load_rule_catalog()
    catalog_tasks = set(catalog.get("task_types") or [])
    case_tasks = {str(case.get("task_type") or "") for case in (_read_json(BENCHMARK_PATH).get("cases") or [])}
    result_tasks = {str((result.get("output") or {}).get("task_type") or "") for result in results}
    if case_tasks != catalog_tasks or not catalog_tasks <= result_tasks:
        raise RuntimeError("Day5 acceptance must cover every catalog task type end to end")
    if len(results) != _expected_count():
        raise RuntimeError("Day5 acceptance result count mismatch")
    bad_statuses = [result.get("status") for result in results if result.get("status") not in {"completed", "clarification"}]
    if bad_statuses:
        raise RuntimeError(f"Day5 acceptance has failed runs: {bad_statuses}")
    if any((result.get("evaluation") or {}).get("schema_version") != EVALUATION_SCHEMA_VERSION for result in results):
        raise RuntimeError("Day5 evaluation records are missing or invalid")
    if summary.get("schema_version") != EVALUATION_SUMMARY_SCHEMA_VERSION:
        raise RuntimeError("Day5 evaluation summary schema mismatch")
    if set(summary.get("methods") or {}) != set(ExperimentRunner.METHODS):
        raise RuntimeError("Day5 evaluation summary missing method rows")
    if (summary.get("paired_m3_vs_m2") or {}).get("pair_count") != _case_count():
        raise RuntimeError("Day5 M3/M2 paired summary mismatch")
    paired_stats = summary.get("paired_statistics") or {}
    if paired_stats.get("pair_count") != _case_count():
        raise RuntimeError("Day5 paired statistics mismatch")
    if "stsr" not in (paired_stats.get("metrics") or {}):
        raise RuntimeError("Day5 paired statistics missing STSR metric")
    paper_tables_path = (manifest.get("results") or {}).get("paper_tables")
    if not paper_tables_path or not Path(paper_tables_path).exists():
        raise RuntimeError("Day5 paper tables file missing")
    evaluation = manifest.get("evaluation") or {}
    if evaluation.get("catalog_id") != catalog.get("catalog_id"):
        raise RuntimeError("Day5 manifest evaluation catalog mismatch")
    if len(str(evaluation.get("catalog_sha256") or "")) != 64:
        raise RuntimeError("Day5 manifest catalog hash missing")


def _expected_count() -> int:
    return _case_count() * len(ExperimentRunner.METHODS)


def _case_count() -> int:
    return len((_read_json(BENCHMARK_PATH).get("cases") or []))


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _render_report(
    run_id: str,
    results: List[Dict[str, Any]],
    manifest: Dict[str, Any],
    summary: Dict[str, Any],
) -> str:
    methods = summary.get("methods") or {}
    lines = [
        "# Day 5 验收报告",
        "",
        f"- run_id: `{run_id}`",
        f"- result_count: {len(results)}",
        f"- evaluator: `{manifest.get('evaluation', {}).get('schema_version')}`",
        f"- rule_catalog: `{manifest.get('evaluation', {}).get('catalog_id')}`",
        f"- paired_m3_vs_m2_count: {(summary.get('paired_m3_vs_m2') or {}).get('pair_count')}",
        f"- paired_statistics_count: {(summary.get('paired_statistics') or {}).get('pair_count')}",
        "",
        "| method | cases | STSR | HCSR | Agent F1 | Tool F1 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for method in ExperimentRunner.METHODS:
        row = methods.get(method) or {}
        lines.append(
            f"| {method} | {row.get('case_count')} | {_fmt(row.get('stsr_rate'))} "
            f"| {_fmt(row.get('evaluation_hcsr_mean'))} | {_fmt(row.get('agent_selection_f1_mean'))} "
            f"| {_fmt(row.get('tool_selection_f1_mean'))} |"
        )
    return "\n".join(lines) + "\n"


def _fmt(value: Any) -> str:
    return "" if value is None else str(value)


if __name__ == "__main__":
    raise SystemExit(main())
