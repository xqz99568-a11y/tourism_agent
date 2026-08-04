"""Run a small Day 7 pilot benchmark with formal-style evidence gates.

The pilot is deliberately smaller than the formal 100-case experiment.  It
uses the same ExperimentRunner/preflight path, writes the same core artifacts,
and adds a Day 7 gate that checks evidence completeness rather than task
quality thresholds.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.experiment_run_audit import RUN_AUDIT_SCHEMA_VERSION
from app.core.day7_fix_report import write_day7_fix_report
from app.core.experiment_paper_analysis import write_experiment_paper_analysis
from app.core.experiment_runner import ExperimentRunner
from app.core.fixed_data import (
    CANONICAL_JSON_SHA256_STRATEGY,
    canonical_json_sha256,
)
from app.core.formal_experiment_preflight import (
    DEFAULT_FORMAL_METHOD_ORDER_SEED,
    build_formal_preflight_report,
    load_benchmark_document,
    resolve_run_output_dir,
    write_preflight_report,
)


DAY7_PILOT_SCHEMA_VERSION = "ctp-day7-pilot-v1"
DAY7_PILOT_GATE_SCHEMA_VERSION = "ctp-day7-pilot-gate-v1"
DAY7_PILOT_BENCHMARK_SCHEMA_VERSION = "ctp-day7-pilot-benchmark-v1"
DEFAULT_BENCHMARK_PATH = ROOT / "experiments" / "benchmark_test.json"
DEFAULT_OUTPUT_ROOT = ROOT / "experiments" / "results" / "day7_pilot"
DEFAULT_MAX_CASES = 8
DEFAULT_MODEL_CONFIG_NAME = "day7-pilot"
PILOT_BENCHMARK_NAME = "day7_pilot_benchmark.json"
PILOT_PREFLIGHT_REPORT_NAME = "day7_pilot_preflight_report.json"
PILOT_GATE_NAME = "day7_pilot_gate.json"
PILOT_REPORT_NAME = "day7_pilot_report.md"
REQUIRED_RESULT_FILES = (
    "benchmark_results.csv",
    "benchmark_results.json",
    "evaluation_summary.json",
    "paper_tables.md",
    "experiment_manifest.json",
)
REQUIRED_RESULT_METRIC_FIELDS = (
    "stsr",
    "evaluation_hcsr",
    "agent_selection_f1",
    "tool_selection_f1",
    "agent_set_exact_match",
    "tool_set_exact_match",
    "llm_call_count",
    "agent_call_count",
    "called_tool_count",
    "total_tokens",
)
RUNTIME_DEFAULTS = {
    "EXPERIMENT_STRICT_MODE": "true",
    "EXPERIMENT_DISABLE_CACHE": "true",
    "TRACE_SAVE_USER_MESSAGE": "false",
    "LLM_TEMPERATURE": "0",
    "LLM_MAX_TOKENS": "4096",
    "LLM_TIMEOUT": "60",
    "LLM_RETRY_MAX_ATTEMPTS": "3",
    "LLM_REASONING_EFFORT": "minimal",
    "EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER": "true",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--max-cases", type=int, default=DEFAULT_MAX_CASES)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--methods", type=str, default=",".join(ExperimentRunner.METHODS))
    parser.add_argument("--method-order-seed", type=int, default=DEFAULT_FORMAL_METHOD_ORDER_SEED)
    parser.add_argument("--model-config-name", type=str, default=DEFAULT_MODEL_CONFIG_NAME)
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Build the pilot benchmark and run preflight only; do not call an LLM.",
    )
    parser.add_argument(
        "--skip-llm-config-check",
        action="store_true",
        help="Allow preflight without configured LLM credentials. Intended for dry checks only.",
    )
    parser.add_argument(
        "--allow-mock-llm",
        action="store_true",
        help="Permit mock LLM trace calls in the pilot gate. Intended for local tests only.",
    )
    args = parser.parse_args()

    payload = run_day7_pilot(
        benchmark_path=args.benchmark,
        output_dir=args.output_dir,
        run_id=args.run_id,
        max_cases=args.max_cases,
        repeats=args.repeats,
        methods=_parse_methods(args.methods),
        method_order_seed=args.method_order_seed,
        model_config_name=args.model_config_name,
        preflight_only=args.preflight_only,
        require_llm_config=not args.skip_llm_config_check,
        allow_mock_llm=args.allow_mock_llm,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload.get("status") == "preflight_failed":
        return 2
    if payload.get("status") == "preflight_passed":
        return 0
    gate = payload.get("pilot_gate") if isinstance(payload.get("pilot_gate"), dict) else {}
    return 0 if payload.get("status") == "completed" and gate.get("status") == "passed" else 1


def run_day7_pilot(
    *,
    benchmark_path: str | Path = DEFAULT_BENCHMARK_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_ROOT,
    run_id: Optional[str] = None,
    max_cases: int = DEFAULT_MAX_CASES,
    repeats: int = 1,
    methods: Optional[Iterable[str]] = None,
    method_order_seed: int = DEFAULT_FORMAL_METHOD_ORDER_SEED,
    model_config_name: str = DEFAULT_MODEL_CONFIG_NAME,
    preflight_only: bool = False,
    require_llm_config: bool = True,
    allow_mock_llm: bool = False,
    runner_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run the Day 7 pilot and return a machine-readable payload.

    ``runner_kwargs`` is intentionally not exposed in the CLI.  Tests can use it
    to inject deterministic handlers without changing production behavior.
    """
    selected_methods = _normalize_methods(methods or ExperimentRunner.METHODS)
    run_id = run_id or f"day7_pilot_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    output_root = Path(output_dir)
    run_output_dir = resolve_run_output_dir(output_root, run_id)
    pilot_input_dir = _pilot_input_dir(output_root, run_id)
    pilot_benchmark_path = pilot_input_dir / f"{run_id}_{PILOT_BENCHMARK_NAME}"

    with _temporary_env_defaults(RUNTIME_DEFAULTS):
        pilot_benchmark = build_pilot_benchmark_document(
            benchmark_path=benchmark_path,
            max_cases=max_cases,
        )
        _write_new_json(pilot_benchmark_path, pilot_benchmark)
        expected_case_count = len(pilot_benchmark["cases"])
        preflight_report = build_formal_preflight_report(
            benchmark_path=pilot_benchmark_path,
            output_dir=output_root,
            run_id=run_id,
            methods=selected_methods,
            repeats=repeats,
            method_order_seed=method_order_seed,
            expected_case_count=expected_case_count,
            require_llm_config=require_llm_config,
            strict_formal=True,
        )
        preflight_payload = {
            "status": (
                "preflight_passed"
                if preflight_report.get("status") == "passed"
                else "preflight_failed"
            ),
            "schema_version": DAY7_PILOT_SCHEMA_VERSION,
            "run_id": run_id,
            "output_dir": run_output_dir.as_posix(),
            "pilot_benchmark": pilot_benchmark_path.as_posix(),
            "preflight": preflight_report,
        }
        if preflight_only or preflight_report.get("status") != "passed":
            return preflight_payload

        run_output_dir.mkdir(parents=True, exist_ok=True)
        preflight_path = write_preflight_report(
            preflight_report,
            run_output_dir / PILOT_PREFLIGHT_REPORT_NAME,
        )
        runner = ExperimentRunner(
            trace_dir=run_output_dir / "traces",
            output_dir=run_output_dir,
            repeats=repeats,
            run_id=run_id,
            model_config_name=model_config_name,
            method_order_seed=method_order_seed,
            **(runner_kwargs or {}),
        )
        results = runner.run_benchmark(
            pilot_benchmark_path,
            methods=selected_methods,
            repeats=repeats,
            run_id=run_id,
            model_config_name=model_config_name,
        )

    gate = build_day7_pilot_gate(
        results=results,
        output_dir=run_output_dir,
        preflight_report=preflight_report,
        selected_methods=selected_methods,
        allow_mock_llm=allow_mock_llm,
        pilot_benchmark_path=pilot_benchmark_path,
        preflight_path=preflight_path,
    )
    gate_path = run_output_dir / PILOT_GATE_NAME
    report_path = run_output_dir / PILOT_REPORT_NAME
    _write_json(gate_path, gate)
    report_path.write_text(_render_report(gate), encoding="utf-8")
    _attach_day7_pilot_manifest(
        manifest_path=run_output_dir / "experiment_manifest.json",
        gate=gate,
        pilot_benchmark_path=pilot_benchmark_path,
        preflight_path=preflight_path,
        gate_path=gate_path,
        report_path=report_path,
    )
    paper_analysis = write_experiment_paper_analysis(
        run_output_dir,
        profile="pilot",
        min_cases=1,
        allow_mock_llm=allow_mock_llm,
    )
    fix_report = write_day7_fix_report(run_output_dir)

    return {
        "status": "completed",
        "schema_version": DAY7_PILOT_SCHEMA_VERSION,
        "run_id": run_id,
        "output_dir": run_output_dir.as_posix(),
        "result_count": len(results),
        "expected_count": gate["expected_result_count"],
        "pilot_gate": gate,
        "pilot_benchmark": pilot_benchmark_path.as_posix(),
        "preflight": preflight_path.as_posix(),
        "gate": gate_path.as_posix(),
        "report": report_path.as_posix(),
        "csv": (run_output_dir / "benchmark_results.csv").as_posix(),
        "json": (run_output_dir / "benchmark_results.json").as_posix(),
        "summary": (run_output_dir / "evaluation_summary.json").as_posix(),
        "paper_tables": (run_output_dir / "paper_tables.md").as_posix(),
        "paper_analysis_json": paper_analysis["json"],
        "paper_analysis_md": paper_analysis["markdown"],
        "paper_readiness_status": paper_analysis["readiness_status"],
        "day7_issue_report_json": fix_report["json"],
        "day7_fix_report_md": fix_report["markdown"],
        "day7_fix_report_status": fix_report["status"],
        "m3_systemic_failure": fix_report["m3_systemic_failure"],
        "manifest": (run_output_dir / "experiment_manifest.json").as_posix(),
        "trace_dir": (run_output_dir / "traces").as_posix(),
    }


def build_pilot_benchmark_document(
    *,
    benchmark_path: str | Path,
    max_cases: int,
) -> Dict[str, Any]:
    if isinstance(max_cases, bool) or int(max_cases) < 1:
        raise ValueError("max_cases must be a positive integer")
    source_path = Path(benchmark_path)
    source_document, cases = load_benchmark_document(source_path)
    selected_cases = list(cases[: int(max_cases)])
    if not selected_cases:
        raise ValueError("pilot benchmark source contains no cases")
    source_metadata = source_document if isinstance(source_document, dict) else {}
    source_sha256 = canonical_json_sha256(source_document)
    dataset_id = str(source_metadata.get("dataset_id") or source_path.stem)
    return {
        "schema_version": DAY7_PILOT_BENCHMARK_SCHEMA_VERSION,
        "dataset_id": f"{dataset_id}_day7_pilot",
        "dataset_version": str(source_metadata.get("dataset_version") or dataset_id),
        "split": "day7_pilot",
        "description": (
            "Automatically derived small pilot subset for Day 7 infrastructure "
            "verification. It must not replace the frozen formal test set."
        ),
        "source_dataset": {
            "path": source_path.as_posix(),
            "sha256": source_sha256,
            "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
            "dataset_id": dataset_id,
            "dataset_version": source_metadata.get("dataset_version"),
            "case_count": len(cases),
        },
        "selection": {
            "policy": "preserve_source_order_first_n_cases",
            "max_cases": int(max_cases),
            "selected_case_count": len(selected_cases),
            "selected_case_ids": [_case_id(case) for case in selected_cases],
        },
        "cases": selected_cases,
    }


def build_day7_pilot_gate(
    *,
    results: List[Dict[str, Any]],
    output_dir: str | Path,
    preflight_report: Dict[str, Any],
    selected_methods: Iterable[str],
    allow_mock_llm: bool,
    pilot_benchmark_path: str | Path,
    preflight_path: str | Path,
) -> Dict[str, Any]:
    output = Path(output_dir)
    selected_method_list = list(selected_methods)
    result_files = {name: output / name for name in REQUIRED_RESULT_FILES}
    csv_rows = _read_csv_rows(result_files["benchmark_results.csv"])
    traces = _load_result_traces(results)
    trace_file_count = _result_trace_file_count(results)
    pilot_benchmark = _read_json_or_empty(Path(pilot_benchmark_path))
    pilot_structure = _pilot_benchmark_structure(pilot_benchmark)
    llm_calls = [
        call
        for trace in traces
        for call in (trace.get("llm_calls") if isinstance(trace.get("llm_calls"), list) else [])
        if isinstance(call, dict)
    ]
    expected_count = int((preflight_report.get("run") or {}).get("expected_raw_run_count") or 0)
    manifest = _read_json_or_empty(result_files["experiment_manifest.json"])
    checks = {
        "preflight_passed": preflight_report.get("status") == "passed",
        "result_count_matches": len(results) == expected_count,
        "csv_row_count_matches": len(csv_rows) == expected_count,
        "pilot_case_count_matches_preflight": pilot_structure["case_count"]
        == int((preflight_report.get("benchmark") or {}).get("case_count") or 0),
        "pilot_turn_count_matches_preflight": pilot_structure["total_turn_count"]
        == int((preflight_report.get("benchmark") or {}).get("total_turn_count") or 0),
        "request_level_trace_count_matches": trace_file_count == expected_count,
        "loaded_trace_count_matches": len(traces) == expected_count,
        "required_result_files_saved": all(path.exists() for path in result_files.values()),
        "preflight_report_saved": Path(preflight_path).exists(),
        "pilot_benchmark_saved": Path(pilot_benchmark_path).exists(),
        "trace_files_saved": bool(results)
        and all(_trace_reference_exists(result.get("trace_file")) for result in results),
        "run_audit_attached": _all_results_have_run_audit(results),
        "metric_fields_present": _all_results_have_metrics(results),
        "llm_call_recorded": bool(llm_calls),
        "runtime_audit_recorded": bool(llm_calls)
        and all(_llm_call_has_runtime_audit(call) for call in llm_calls),
        "no_llm_fallback_recorded": all(
            call.get("fallback") is False and call.get("fallback_used") is False
            for call in llm_calls
        ),
        "mock_policy_satisfied": bool(allow_mock_llm)
        or all(call.get("mock") is False and call.get("mock_used") is False for call in llm_calls),
        "strict_runtime_recorded": (manifest.get("runtime_config") or {}).get("strict_mode") is True,
        "cache_disabled_recorded": (manifest.get("runtime_config") or {}).get("cache_disabled") is True,
        "user_message_not_persisted": all(not trace.get("user_message") for trace in traces),
    }
    failed_checks = [key for key, value in checks.items() if not value]
    gate = {
        "schema_version": DAY7_PILOT_GATE_SCHEMA_VERSION,
        "status": "passed" if not failed_checks else "failed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_id": str((preflight_report.get("run") or {}).get("run_id") or ""),
        "output_dir": output.as_posix(),
        "selected_methods": selected_method_list,
        "expected_result_count": expected_count,
        "actual_result_count": len(results),
        "pilot_structure": {
            **pilot_structure,
            "method_count": len(selected_method_list),
            "repeats": int((preflight_report.get("run") or {}).get("repeats") or 0),
            "expected_trace_count": expected_count,
            "actual_trace_file_count": trace_file_count,
            "loaded_trace_count": len(traces),
        },
        "checks": checks,
        "failed_checks": failed_checks,
        "quality_policy": {
            "quality_threshold_enforced": False,
            "reason": (
                "Day 7 pilot checks evidence completeness and runtime auditability. "
                "Task quality metrics are reported but do not gate the pilot."
            ),
        },
        "artifact_paths": {
            "pilot_benchmark": Path(pilot_benchmark_path).as_posix(),
            "preflight": Path(preflight_path).as_posix(),
            **{key: path.as_posix() for key, path in result_files.items()},
            "trace_dir": (output / "traces").as_posix(),
        },
        "trace_summary": _trace_summary(traces, llm_calls),
        "result_status_summary": _result_status_summary(results),
        "metric_summary": _metric_summary(results),
    }
    return gate


def _attach_day7_pilot_manifest(
    *,
    manifest_path: Path,
    gate: Dict[str, Any],
    pilot_benchmark_path: Path,
    preflight_path: Path,
    gate_path: Path,
    report_path: Path,
) -> None:
    manifest = _read_json_or_empty(manifest_path)
    results = dict(manifest.get("results") or {})
    results.update(
        {
            "day7_pilot_benchmark": pilot_benchmark_path.as_posix(),
            "day7_pilot_preflight": preflight_path.as_posix(),
            "day7_pilot_gate": gate_path.as_posix(),
            "day7_pilot_report": report_path.as_posix(),
        }
    )
    manifest["results"] = results
    manifest["day7_pilot"] = {
        "schema_version": DAY7_PILOT_SCHEMA_VERSION,
        "gate_schema_version": DAY7_PILOT_GATE_SCHEMA_VERSION,
        "status": gate.get("status"),
        "expected_result_count": gate.get("expected_result_count"),
        "actual_result_count": gate.get("actual_result_count"),
        "failed_checks": gate.get("failed_checks") or [],
        "quality_threshold_enforced": False,
        "artifact_paths": gate.get("artifact_paths") or {},
    }
    _write_json(manifest_path, manifest)


def _render_report(gate: Dict[str, Any]) -> str:
    metrics = gate.get("metric_summary") if isinstance(gate.get("metric_summary"), dict) else {}
    trace = gate.get("trace_summary") if isinstance(gate.get("trace_summary"), dict) else {}
    structure = gate.get("pilot_structure") if isinstance(gate.get("pilot_structure"), dict) else {}
    result_status = gate.get("result_status_summary") if isinstance(gate.get("result_status_summary"), dict) else {}
    lines = [
        "# Day 7 pilot report",
        "",
        "## Conclusion",
        "",
        f"- status: `{gate.get('status')}`",
        f"- run_id: `{gate.get('run_id')}`",
        f"- top_level_case_count: `{structure.get('case_count')}`",
        f"- total_turn_count: `{structure.get('total_turn_count')}`",
        f"- method_count: `{structure.get('method_count')}`",
        f"- expected_trace_count: `{structure.get('expected_trace_count')}`",
        f"- actual_trace_file_count: `{structure.get('actual_trace_file_count')}`",
        f"- expected_result_count: `{gate.get('expected_result_count')}`",
        f"- actual_result_count: `{gate.get('actual_result_count')}`",
        f"- llm_call_count: `{trace.get('llm_call_count')}`",
        f"- total_tokens: `{trace.get('total_tokens')}`",
        f"- estimated_cost: `{trace.get('estimated_cost')}`",
        f"- result_status_counts: `{result_status.get('status_counts')}`",
        f"- result_error_count: `{result_status.get('error_count')}`",
        f"- failed_checks: `{gate.get('failed_checks') or []}`",
        "",
        "## Gate checks",
        "",
        "| check | passed |",
        "|---|---:|",
    ]
    for key, value in (gate.get("checks") or {}).items():
        lines.append(f"| {key} | `{value}` |")
    lines.extend(
        [
            "",
            "## Method metric summary",
            "",
            "| method | runs | STSR | Agent F1 | Tool F1 | LLM calls | Tokens | Cost |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for method, row in sorted((metrics.get("methods") or {}).items()):
        lines.append(
            f"| {method} | {row.get('run_count', 0)} | {_fmt(row.get('stsr_rate'))} "
            f"| {_fmt(row.get('agent_selection_f1_mean'))} "
            f"| {_fmt(row.get('tool_selection_f1_mean'))} "
            f"| {_fmt(row.get('llm_call_count_sum'))} "
            f"| {_fmt(row.get('total_tokens_sum'))} "
            f"| {_fmt(row.get('estimated_cost_sum'))} |"
        )
    lines.extend(
        [
            "",
            "## Artifact paths",
            "",
            "| artifact | path |",
            "|---|---|",
        ]
    )
    for key, path in (gate.get("artifact_paths") or {}).items():
        lines.append(f"| {key} | `{path}` |")
    return "\n".join(lines) + "\n"


def _trace_summary(traces: List[Dict[str, Any]], llm_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "trace_count": len(traces),
        "trace_without_llm_call_count": sum(
            1 for trace in traces if not _trace_has_llm_call(trace)
        ),
        "llm_call_count": len(llm_calls),
        "mock_llm_call_count": sum(call.get("mock") is True or call.get("mock_used") is True for call in llm_calls),
        "fallback_llm_call_count": sum(
            call.get("fallback") is True or call.get("fallback_used") is True for call in llm_calls
        ),
        "retry_count": _sum_number(call.get("retry_count") for call in llm_calls),
        "prompt_tokens": _sum_usage(llm_calls, "prompt_tokens", "input_tokens"),
        "completion_tokens": _sum_usage(llm_calls, "completion_tokens", "output_tokens"),
        "reasoning_tokens": _sum_nested_usage(
            llm_calls,
            "completion_tokens_details",
            "reasoning_tokens",
        ),
        "total_tokens": _sum_usage(llm_calls, "total_tokens", "tokens_used"),
        "estimated_cost": _sum_number(call.get("estimated_cost") for call in llm_calls),
        "standardized_estimated_cost": _sum_number(
            call.get("standardized_estimated_cost") for call in llm_calls
        ),
        "actual_cost": _sum_number(call.get("actual_cost") for call in llm_calls),
    }


def _pilot_benchmark_structure(document: Dict[str, Any]) -> Dict[str, Any]:
    cases = document.get("cases") if isinstance(document.get("cases"), list) else []
    scenario_count = sum(1 for case in cases if isinstance(case, dict) and isinstance(case.get("turns"), list))
    total_turn_count = sum(_case_turn_count(case) for case in cases if isinstance(case, dict))
    return {
        "case_count": len(cases),
        "single_turn_case_count": len(cases) - scenario_count,
        "scenario_case_count": scenario_count,
        "total_turn_count": total_turn_count,
        "selected_case_ids": list(
            ((document.get("selection") or {}).get("selected_case_ids") or [])
            if isinstance(document.get("selection"), dict)
            else []
        ),
    }


def _case_turn_count(case: Dict[str, Any]) -> int:
    turns = case.get("turns")
    if isinstance(turns, list) and turns:
        return len(turns)
    return 1


def _result_trace_file_count(results: List[Dict[str, Any]]) -> int:
    trace_files = {
        str(result.get("trace_file") or "").strip()
        for result in results
        if str(result.get("trace_file") or "").strip()
    }
    return len(trace_files)


def _trace_has_llm_call(trace: Dict[str, Any]) -> bool:
    calls = trace.get("llm_calls")
    return isinstance(calls, list) and any(isinstance(call, dict) for call in calls)


def _result_status_summary(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    status_counts: Dict[str, int] = {}
    error_count = 0
    for result in results:
        status = str(result.get("status") or "unknown").strip().lower() or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        if result.get("error"):
            error_count += 1
    return {
        "status_counts": status_counts,
        "error_count": error_count,
        "quality_gated": False,
        "note": (
            "Pilot gates evidence completeness and runtime auditability. "
            "Method failures are reported here for diagnosis but are not hard-gated."
        ),
    }


def _metric_summary(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_method: Dict[str, List[Dict[str, Any]]] = {}
    for result in results:
        by_method.setdefault(str(result.get("method") or "unknown"), []).append(result)
    return {
        "run_count": len(results),
        "methods": {
            method: _method_metric_summary(rows)
            for method, rows in sorted(by_method.items())
        },
    }


def _method_metric_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    metrics = [row.get("metrics") if isinstance(row.get("metrics"), dict) else {} for row in rows]
    return {
        "run_count": len(rows),
        "stsr_rate": _mean_bool(item.get("stsr") for item in metrics),
        "agent_selection_f1_mean": _mean_number(item.get("agent_selection_f1") for item in metrics),
        "tool_selection_f1_mean": _mean_number(item.get("tool_selection_f1") for item in metrics),
        "llm_call_count_sum": _sum_number(item.get("llm_call_count") for item in metrics),
        "agent_call_count_sum": _sum_number(item.get("agent_call_count") for item in metrics),
        "called_tool_count_sum": _sum_number(item.get("called_tool_count") for item in metrics),
        "total_tokens_sum": _sum_number(item.get("total_tokens") for item in metrics),
        "estimated_cost_sum": _sum_number(item.get("estimated_cost") for item in metrics),
    }


def _llm_call_has_runtime_audit(call: Dict[str, Any]) -> bool:
    request_options = call.get("request_options")
    retry = call.get("retry")
    return (
        isinstance(request_options, dict)
        and isinstance(retry, dict)
        and _first_number(call.get("temperature")) == 0.0
        and _first_number(call.get("max_tokens")) is not None
        and _first_number(call.get("timeout_seconds")) is not None
        and request_options.get("reasoning_effort") == "minimal"
        and call.get("reasoning_effort") == "minimal"
        and _first_number(call.get("retry_max_attempts")) is not None
        and _first_number(call.get("retry_attempt_count")) is not None
    )


def _all_results_have_run_audit(results: List[Dict[str, Any]]) -> bool:
    if not results:
        return False
    for result in results:
        audit = result.get("run_audit")
        if not isinstance(audit, dict) or audit.get("schema_version") != RUN_AUDIT_SCHEMA_VERSION:
            return False
        if not isinstance(audit.get("metrics"), dict):
            return False
    return True


def _all_results_have_metrics(results: List[Dict[str, Any]]) -> bool:
    if not results:
        return False
    for result in results:
        metrics = result.get("metrics")
        if not isinstance(metrics, dict):
            return False
        if any(key not in metrics for key in REQUIRED_RESULT_METRIC_FIELDS):
            return False
    return True


def _load_result_traces(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    traces: List[Dict[str, Any]] = []
    for result in results:
        trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
        trace_path = _resolve_trace_path(result.get("trace_file"))
        if trace_path and trace_path.exists():
            loaded = _read_jsonl_first(trace_path)
            if loaded:
                loaded["trace_file"] = trace_path.as_posix()
                traces.append(loaded)
                continue
        if trace:
            traces.append(trace)
    return traces


def _read_jsonl_first(path: Path) -> Dict[str, Any]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        return json.loads(lines[0]) if lines else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _read_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _trace_reference_exists(value: Any) -> bool:
    path = _resolve_trace_path(value)
    return bool(path and path.exists())


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


def _pilot_input_dir(output_root: Path, run_id: str) -> Path:
    if output_root.name == run_id:
        return output_root.parent / "_day7_pilot_inputs"
    return output_root / "_day7_pilot_inputs"


def _parse_methods(value: str) -> List[str]:
    return [item.strip() for item in str(value or "").replace(";", ",").split(",") if item.strip()]


def _normalize_methods(methods: Iterable[str]) -> List[str]:
    normalized = [str(method).strip().lower() for method in methods if str(method).strip()]
    if not normalized:
        raise ValueError("methods must not be empty")
    return normalized


def _case_id(case: Dict[str, Any]) -> str:
    return str(case.get("case_id") or case.get("scenario_id") or case.get("id") or "")


def _write_new_json(path: Path, payload: Dict[str, Any]) -> None:
    if path.exists():
        raise RuntimeError(f"Day7 pilot input already exists: {path}")
    _write_json(path, payload)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json_or_empty(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _sum_usage(calls: List[Dict[str, Any]], *keys: str) -> Optional[float]:
    values = []
    for call in calls:
        usage = call.get("usage") if isinstance(call.get("usage"), dict) else call.get("tokens")
        usage = usage if isinstance(usage, dict) else {}
        values.append(_first_number(*(usage.get(key) for key in keys)))
    return _sum_number(values)


def _sum_nested_usage(calls: List[Dict[str, Any]], *keys: str) -> Optional[float]:
    values = []
    for call in calls:
        usage = call.get("usage") if isinstance(call.get("usage"), dict) else call.get("tokens")
        current: Any = usage if isinstance(usage, dict) else {}
        for key in keys:
            current = current.get(key) if isinstance(current, dict) else None
        values.append(_first_number(current))
    return _sum_number(values)


def _sum_number(values: Iterable[Any]) -> Optional[float]:
    numbers = [_first_number(value) for value in values]
    numbers = [value for value in numbers if value is not None]
    return None if not numbers else round(sum(numbers), 4)


def _mean_number(values: Iterable[Any]) -> Optional[float]:
    numbers = [_first_number(value) for value in values]
    numbers = [value for value in numbers if value is not None]
    return None if not numbers else round(sum(numbers) / len(numbers), 4)


def _mean_bool(values: Iterable[Any]) -> Optional[float]:
    numbers = [1.0 if value is True else 0.0 for value in values if isinstance(value, bool)]
    return None if not numbers else round(sum(numbers) / len(numbers), 4)


def _first_number(*values: Any) -> Optional[float]:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return str(round(value, 4))
    return str(value)


@contextmanager
def _temporary_env_defaults(defaults: Dict[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in defaults}
    try:
        for key, value in defaults.items():
            os.environ.setdefault(key, value)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
