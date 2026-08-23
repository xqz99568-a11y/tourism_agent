"""Final evidence gate for paper-level formal experiment runs.

The preflight gate checks whether a run is allowed to start.  This module
checks the opposite end of the pipeline: after a formal run has finished, are
the saved artifacts complete enough to support paper claims?
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.core.experiment_paper_analysis import (
    DEFAULT_REQUIRED_METHODS,
    PAPER_ANALYSIS_JSON_NAME,
    PAPER_ANALYSIS_MD_NAME,
    PAPER_ANALYSIS_SCHEMA_VERSION,
    write_experiment_paper_analysis,
)
from app.core.experiment_run_audit import RUN_AUDIT_SCHEMA_VERSION
from app.core.formal_artifact_integrity import FORMAL_ARTIFACT_INTEGRITY_SCHEMA_VERSION
from app.core.formal_experiment_preflight import FORMAL_PREFLIGHT_SCHEMA_VERSION
from app.core.independent_evaluator import (
    DECISION_NORMALIZATION_DIAGNOSTIC_SCHEMA_VERSION,
)


FORMAL_EXPERIMENT_GATE_SCHEMA_VERSION = "ctp-formal-experiment-gate-v1"
FORMAL_EXPERIMENT_GATE_NAME = "formal_experiment_gate.json"
FORMAL_EXPERIMENT_REPORT_NAME = "formal_experiment_report.md"

_CORE_ARTIFACTS = {
    "csv": "benchmark_results.csv",
    "json": "benchmark_results.json",
    "summary": "evaluation_summary.json",
    "paper_tables": "paper_tables.md",
    "manifest": "experiment_manifest.json",
    "preflight": "formal_preflight_report.json",
    "paper_analysis_json": PAPER_ANALYSIS_JSON_NAME,
    "paper_analysis_md": PAPER_ANALYSIS_MD_NAME,
}
_REQUIRED_METRIC_FIELDS = (
    "stsr",
    "evaluation_hcsr",
    "bpcr",
    "agent_selection_f1",
    "tool_selection_f1",
    "agent_set_exact_match",
    "tool_set_exact_match",
    "llm_call_count",
    "agent_call_count",
    "called_tool_count",
    "total_tokens",
)


def write_formal_experiment_gate(
    run_dir: str | Path,
    *,
    min_cases: Optional[int] = None,
    required_methods: Optional[Iterable[str]] = None,
    allow_mock_llm: bool = False,
) -> Dict[str, Any]:
    """Write final formal gate artifacts and attach them to the manifest."""
    root = Path(run_dir)
    paper_payload = write_experiment_paper_analysis(
        root,
        profile="formal",
        min_cases=min_cases,
        required_methods=required_methods,
        allow_mock_llm=allow_mock_llm,
    )
    gate = build_formal_experiment_gate(
        root,
        paper_analysis=paper_payload["analysis"],
        min_cases=min_cases,
        required_methods=required_methods,
        allow_mock_llm=allow_mock_llm,
    )
    gate_path = root / FORMAL_EXPERIMENT_GATE_NAME
    report_path = root / FORMAL_EXPERIMENT_REPORT_NAME
    gate["artifact_paths"]["formal_gate"] = gate_path.as_posix()
    gate["artifact_paths"]["formal_report"] = report_path.as_posix()
    gate_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(render_formal_experiment_report(gate), encoding="utf-8")
    _attach_gate_to_manifest(
        root,
        gate=gate,
        gate_path=gate_path,
        report_path=report_path,
    )
    return {
        "status": "completed",
        "gate": gate,
        "json": gate_path.as_posix(),
        "markdown": report_path.as_posix(),
        "gate_status": gate["status"],
        "paper_claims_allowed": gate["paper_claims_allowed"],
        "paper_analysis_json": paper_payload["json"],
        "paper_analysis_md": paper_payload["markdown"],
        "paper_readiness_status": paper_payload["readiness_status"],
    }


def build_formal_experiment_gate(
    run_dir: str | Path,
    *,
    paper_analysis: Optional[Dict[str, Any]] = None,
    min_cases: Optional[int] = None,
    required_methods: Optional[Iterable[str]] = None,
    allow_mock_llm: bool = False,
) -> Dict[str, Any]:
    """Build the machine-readable final gate for a saved formal run."""
    root = Path(run_dir)
    artifacts = _load_artifacts(root)
    results = artifacts["results"]
    summary = artifacts["summary"]
    manifest = artifacts["manifest"]
    preflight = artifacts["preflight"]
    analysis = paper_analysis or artifacts["paper_analysis"]
    csv_rows = _read_csv_rows(root / _CORE_ARTIFACTS["csv"])
    traces = _load_traces(root, results)
    llm_calls = [
        call
        for trace in traces
        for call in _as_dict_list(trace.get("llm_calls"))
    ]
    result_status_summary = _result_status_summary(results)
    api_failure_summary = _api_failure_timeout_summary(traces)
    methods = _dict(summary.get("methods"))
    expected_result_count = _expected_result_count(preflight, summary)
    required = _normalize_methods(required_methods or DEFAULT_REQUIRED_METHODS)
    effective_min_cases = _effective_min_cases(min_cases)
    raw_count_summary = _raw_result_count_summary(
        preflight=preflight,
        manifest=manifest,
        expected_result_count=expected_result_count,
        actual_result_count=len(results),
        min_cases=effective_min_cases,
        required_method_count=len(required),
    )
    method_grid_summary = _method_result_grid_summary(
        results,
        required_methods=required,
        expected_result_count=expected_result_count,
    )
    metric_calculability_summary = _metric_calculability_summary(
        results,
        summary,
        required_methods=required,
    )
    independent_case_count = _int(
        summary.get("independent_case_count"),
        summary.get("unique_case_count"),
        default=0,
    )
    artifact_index = _artifact_index(root)
    checks = {
        "run_dir_exists": root.exists(),
        "required_artifacts_saved": all(
            (root / filename).exists() for filename in _CORE_ARTIFACTS.values()
        ),
        "formal_preflight_saved": bool(preflight),
        "formal_preflight_schema_valid": (
            preflight.get("schema_version") == FORMAL_PREFLIGHT_SCHEMA_VERSION
        ),
        "formal_preflight_passed": preflight.get("status") == "passed",
        "paper_analysis_saved": bool(artifacts["paper_analysis"]),
        "paper_analysis_schema_valid": (
            analysis.get("schema_version") == PAPER_ANALYSIS_SCHEMA_VERSION
        ),
        "paper_analysis_ready": _nested(analysis, "readiness", "status") == "ready",
        "paper_claims_allowed_by_analysis": (
            _nested(analysis, "readiness", "paper_claims_allowed") is True
        ),
        "minimum_case_count_met": independent_case_count >= effective_min_cases,
        "required_methods_present": all(method in methods for method in required),
        "paired_m3_m2_present": _int(_nested(summary, "paired_statistics", "pair_count"), default=0) > 0,
        "preflight_expected_result_count_recorded": expected_result_count is not None,
        "preflight_expected_result_count_matches_structure": raw_count_summary[
            "expected_matches_structure"
        ],
        "result_count_matches_expected": (
            expected_result_count is not None and len(results) == expected_result_count
        ),
        "formal_ctp100_raw_result_count_is_520": raw_count_summary["passed"],
        "method_result_grid_complete": method_grid_summary["passed"],
        "csv_row_count_matches_results": len(csv_rows) == len(results),
        "all_results_have_execution_status": result_status_summary[
            "missing_execution_status_count"
        ]
        == 0,
        "all_results_have_valid_status": result_status_summary[
            "invalid_execution_status_count"
        ]
        == 0,
        "no_failed_results": result_status_summary["failed_result_count"] == 0,
        "api_failure_timeout_count_zero": api_failure_summary["failure_or_timeout_count"] == 0,
        "run_audit_attached": _all_results_have_run_audit(results),
        "metric_fields_present": _all_results_have_metrics(results),
        "bpcr_field_present": _all_results_have_metric_keys(results, ("bpcr",)),
        "stsr_hcsr_bpcr_fields_present": _all_results_have_metric_keys(
            results,
            ("stsr", "evaluation_hcsr", "bpcr"),
        ),
        "metric_values_calculable": metric_calculability_summary[
            "result_metric_values_calculable"
        ],
        "summary_core_metrics_calculable": metric_calculability_summary[
            "summary_core_metrics_calculable"
        ],
        "paired_core_metrics_calculable": metric_calculability_summary[
            "paired_core_metrics_calculable"
        ],
        "decision_normalization_diagnostics_calculable": metric_calculability_summary[
            "decision_normalization_diagnostics_calculable"
        ],
        "trace_evidence_saved": bool(results)
        and all(_result_trace_evidence_exists(root, result) for result in results),
        "trace_count_matches_results": len(traces) == len(results),
        "llm_call_recorded": bool(llm_calls),
        "no_mock_llm": bool(allow_mock_llm) or not _has_mock_llm(llm_calls),
        "no_llm_fallback": not _has_fallback_llm(llm_calls),
        "formal_artifact_integrity_recorded": _nested(
            manifest,
            "formal_artifact_integrity",
            "schema_version",
        )
        == FORMAL_ARTIFACT_INTEGRITY_SCHEMA_VERSION,
        "preflight_artifact_integrity_recorded": _nested(
            preflight,
            "artifact_integrity",
            "schema_version",
        )
        == FORMAL_ARTIFACT_INTEGRITY_SCHEMA_VERSION,
        "commit_matches_preflight": _commit_matches_preflight(manifest, preflight),
        "artifact_integrity_matches_preflight": _artifact_integrity_matches_preflight(
            manifest,
            preflight,
        ),
        "strict_runtime_recorded": _nested(manifest, "runtime_config", "strict_mode") is True,
        "cache_disabled_recorded": _nested(manifest, "runtime_config", "cache_disabled") is True,
        "deterministic_research_final_answer_recorded": _nested(
            manifest,
            "runtime_config",
            "deterministic_research_final_answer",
        )
        is True,
        "user_message_not_persisted": all(not trace.get("user_message") for trace in traces),
        "method_contract_recorded": _method_contract_recorded(manifest),
        "artifact_hashes_recorded": all(item.get("sha256") for item in artifact_index["files"]),
    }
    failed_checks = [key for key, value in checks.items() if not value]
    status = "passed" if not failed_checks else "failed"
    hypothesis_supported = _hypothesis_supported(analysis, summary)
    return {
        "schema_version": FORMAL_EXPERIMENT_GATE_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "experiment_integrity_passed": status == "passed",
        "hypothesis_supported": hypothesis_supported,
        "paper_claims_allowed": status == "passed",
        "run_id": manifest.get("run_id") or _nested(preflight, "run", "run_id"),
        "run_dir": root.as_posix(),
        "expected_result_count": expected_result_count,
        "actual_result_count": len(results),
        "independent_case_count": independent_case_count,
        "min_cases": effective_min_cases,
        "required_methods": required,
        "observed_methods": list(methods.keys()),
        "checks": checks,
        "failed_checks": failed_checks,
        "result_status_summary": result_status_summary,
        "api_failure_summary": api_failure_summary,
        "raw_count_summary": raw_count_summary,
        "method_result_grid_summary": method_grid_summary,
        "metric_calculability_summary": metric_calculability_summary,
        "artifact_index": artifact_index,
        "artifact_paths": {
            key: (root / filename).as_posix()
            for key, filename in _CORE_ARTIFACTS.items()
            if (root / filename).exists()
        },
        "paper_analysis": {
            "status": _nested(analysis, "readiness", "status"),
            "paper_claims_allowed": _nested(analysis, "readiness", "paper_claims_allowed"),
            "failed_checks": _nested(analysis, "readiness", "failed_checks") or [],
        },
        "trace_summary": _trace_summary(traces, llm_calls),
        "method_summary": _method_summary(analysis, summary),
        "m3_vs_m2": _dict(analysis.get("m3_vs_m2")),
        "interpretation": _interpretation(status),
    }


def render_formal_experiment_report(gate: Dict[str, Any]) -> str:
    """Render a concise human-readable formal gate report."""
    trace = _dict(gate.get("trace_summary"))
    methods = _dict(gate.get("method_summary"))
    m3_vs_m2 = _dict(gate.get("m3_vs_m2"))
    lines = [
        "# Formal experiment final gate",
        "",
        "## Conclusion",
        "",
        f"- status: `{gate.get('status')}`",
        f"- experiment_integrity_passed: `{gate.get('experiment_integrity_passed')}`",
        f"- hypothesis_supported: `{gate.get('hypothesis_supported')}`",
        f"- paper_claims_allowed: `{gate.get('paper_claims_allowed')}`",
        f"- run_id: `{gate.get('run_id')}`",
        f"- independent_case_count: `{gate.get('independent_case_count')}`",
        f"- expected_result_count: `{gate.get('expected_result_count')}`",
        f"- actual_result_count: `{gate.get('actual_result_count')}`",
        f"- failed_checks: `{gate.get('failed_checks') or []}`",
        f"- interpretation: {gate.get('interpretation')}",
        "",
        "## Raw result completeness",
        "",
    ]
    raw_count = _dict(gate.get("raw_count_summary"))
    grid = _dict(gate.get("method_result_grid_summary"))
    metrics = _dict(gate.get("metric_calculability_summary"))
    lines.extend(
        [
            f"- requires_ctp100_520_result_count: `{raw_count.get('requires_ctp100_520_result_count')}`",
            f"- formal_ctp100_expected_raw_result_count: `{raw_count.get('formal_ctp100_expected_raw_result_count')}`",
            f"- structure_expected_result_count: `{raw_count.get('structure_expected_result_count')}`",
            f"- expected_matches_structure: `{raw_count.get('expected_matches_structure')}`",
            f"- method_result_grid_complete: `{grid.get('passed')}`",
            f"- expected_group_count: `{grid.get('expected_group_count')}`",
            f"- observed_group_count: `{grid.get('observed_group_count')}`",
            f"- missing_method_group_count: `{grid.get('missing_method_group_count')}`",
            f"- duplicate_method_result_count: `{grid.get('duplicate_method_result_count')}`",
            f"- unexpected_method_result_count: `{grid.get('unexpected_method_result_count')}`",
            "",
            "## Metric calculability",
            "",
            f"- result_metric_values_calculable: `{metrics.get('result_metric_values_calculable')}`",
            f"- summary_core_metrics_calculable: `{metrics.get('summary_core_metrics_calculable')}`",
            f"- paired_core_metrics_calculable: `{metrics.get('paired_core_metrics_calculable')}`",
            f"- result_issue_count: `{metrics.get('result_issue_count')}`",
            f"- summary_issue_count: `{metrics.get('summary_issue_count')}`",
            f"- paired_issue_count: `{metrics.get('paired_issue_count')}`",
            "",
        ]
    )
    lines.extend(
        [
            "## Gate checks",
            "",
            "| Check | Passed |",
            "|---|---:|",
        ]
    )
    for key, value in _dict(gate.get("checks")).items():
        lines.append(f"| {key} | `{value}` |")

    lines.extend(
        [
            "",
            "## Method summary",
            "",
            "| Method | Cases | STSR | HCSR | BPCR | Agent F1 | Tool F1 | LLM calls | Tokens | Std. cost | Latency ms |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in methods.get("rows") or []:
        lines.append(
            f"| {row.get('label')} | {_fmt(row.get('case_count'))} "
            f"| {_fmt(row.get('stsr'))} | {_fmt(row.get('evaluation_hcsr'))} "
            f"| {_fmt(row.get('bpcr'))} | {_fmt(row.get('agent_selection_f1'))} "
            f"| {_fmt(row.get('tool_selection_f1'))} | {_fmt(row.get('llm_call_count'))} "
            f"| {_fmt(row.get('total_tokens'))} | {_fmt(row.get('standardized_estimated_cost'))} "
            f"| {_fmt(row.get('latency_ms'))} |"
        )

    lines.extend(
        [
            "",
            "## M3 vs M2 resource savings",
            "",
            "| Metric | M3 mean | M2 mean | Delta | Relative saving |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for metric, row in _dict(m3_vs_m2.get("metrics")).items():
        if row.get("relative_saving_rate") is None:
            continue
        lines.append(
            f"| {metric} | {_fmt(row.get('m3_mean'))} | {_fmt(row.get('m2_mean'))} "
            f"| {_fmt(row.get('delta_mean'))} | {_fmt(row.get('relative_saving_rate'))} |"
        )

    lines.extend(
        [
            "",
            "## Trace summary",
            "",
            f"- trace_count: `{trace.get('trace_count')}`",
            f"- llm_call_count: `{trace.get('llm_call_count')}`",
            f"- mock_llm_call_count: `{trace.get('mock_llm_call_count')}`",
            f"- fallback_llm_call_count: `{trace.get('fallback_llm_call_count')}`",
            f"- api_failure_timeout_count: `{_nested(gate, 'api_failure_summary', 'failure_or_timeout_count')}`",
            f"- total_tokens: `{trace.get('total_tokens')}`",
            f"- standardized_estimated_cost: `{trace.get('standardized_estimated_cost')}`",
            "",
            "## Artifact hashes",
            "",
            "| Artifact | SHA-256 | Path |",
            "|---|---|---|",
        ]
    )
    for item in _dict(gate.get("artifact_index")).get("files") or []:
        lines.append(f"| {item.get('key')} | `{item.get('sha256')}` | `{item.get('path')}` |")
    return "\n".join(lines) + "\n"


def _load_artifacts(root: Path) -> Dict[str, Any]:
    return {
        "summary": _read_json_object(root / _CORE_ARTIFACTS["summary"]),
        "results": _read_json_list(root / _CORE_ARTIFACTS["json"]),
        "manifest": _read_json_object(root / _CORE_ARTIFACTS["manifest"]),
        "preflight": _read_json_object(root / _CORE_ARTIFACTS["preflight"]),
        "paper_analysis": _read_json_object(root / PAPER_ANALYSIS_JSON_NAME),
    }


def _artifact_index(root: Path) -> Dict[str, Any]:
    files = []
    for key, filename in _CORE_ARTIFACTS.items():
        path = root / filename
        if not path.exists():
            continue
        files.append(
            {
                "key": key,
                "path": path.as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _file_sha256(path),
            }
        )
    trace_dir = root / "traces"
    trace_files = sorted(trace_dir.glob("*.jsonl")) if trace_dir.exists() else []
    trace_hashes = [_file_sha256(path) for path in trace_files]
    return {
        "schema_version": "ctp-formal-artifact-index-v1",
        "hash_strategy": "sha256_file_bytes_v1",
        "files": files,
        "trace_dir": trace_dir.as_posix(),
        "trace_file_count": len(trace_files),
        "trace_combined_sha256": _combined_hash(trace_hashes),
    }


def _attach_gate_to_manifest(
    root: Path,
    *,
    gate: Dict[str, Any],
    gate_path: Path,
    report_path: Path,
) -> None:
    manifest_path = root / _CORE_ARTIFACTS["manifest"]
    manifest = _read_json_object(manifest_path)
    if not manifest:
        return
    results = _dict(manifest.get("results"))
    results.update(
        {
            "formal_experiment_gate": gate_path.as_posix(),
            "formal_experiment_report": report_path.as_posix(),
        }
    )
    manifest["results"] = results
    manifest["formal_experiment_gate"] = {
        "schema_version": FORMAL_EXPERIMENT_GATE_SCHEMA_VERSION,
        "status": gate.get("status"),
        "experiment_integrity_passed": gate.get("experiment_integrity_passed"),
        "hypothesis_supported": gate.get("hypothesis_supported"),
        "paper_claims_allowed": gate.get("paper_claims_allowed"),
        "failed_checks": gate.get("failed_checks") or [],
        "json": gate_path.as_posix(),
        "markdown": report_path.as_posix(),
        "raw_count_summary": gate.get("raw_count_summary"),
        "method_result_grid_summary": gate.get("method_result_grid_summary"),
        "metric_calculability_summary": gate.get("metric_calculability_summary"),
        "artifact_index": gate.get("artifact_index"),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _method_summary(analysis: Dict[str, Any], summary: Dict[str, Any]) -> Dict[str, Any]:
    rows = analysis.get("method_comparison")
    if isinstance(rows, list):
        return {"rows": [row for row in rows if isinstance(row, dict)]}
    methods = _dict(summary.get("methods"))
    fallback_rows = []
    for method, row in methods.items():
        data = _dict(row)
        fallback_rows.append(
            {
                "method": method,
                "label": method,
                "case_count": data.get("case_count"),
                "stsr": data.get("stsr_rate"),
                "agent_selection_f1": data.get("agent_selection_f1_mean"),
                "tool_selection_f1": data.get("tool_selection_f1_mean"),
                "llm_call_count": data.get("llm_call_count_mean"),
                "total_tokens": data.get("total_tokens_mean"),
                "standardized_estimated_cost": data.get("standardized_estimated_cost_mean"),
                "latency_ms": data.get("latency_ms_mean"),
            }
        )
    return {"rows": fallback_rows}


def _trace_summary(traces: List[Dict[str, Any]], llm_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "trace_count": len(traces),
        "llm_call_count": len(llm_calls),
        "mock_llm_call_count": sum(_bool(call.get("mock")) or _bool(call.get("mock_used")) for call in llm_calls),
        "fallback_llm_call_count": sum(
            _bool(call.get("fallback")) or _bool(call.get("fallback_used"))
            for call in llm_calls
        ),
        "retry_attempt_count": _sum_number(call.get("retry_attempt_count") for call in llm_calls),
        "retry_count": _sum_number(call.get("retry_count") for call in llm_calls),
        "prompt_tokens": _sum_usage(llm_calls, "prompt_tokens", "input_tokens"),
        "completion_tokens": _sum_usage(llm_calls, "completion_tokens", "output_tokens"),
        "total_tokens": _sum_usage(llm_calls, "total_tokens", "tokens_used"),
        "estimated_cost": _sum_number(call.get("estimated_cost") for call in llm_calls),
        "standardized_estimated_cost": _sum_number(
            call.get("standardized_estimated_cost") for call in llm_calls
        ),
        "actual_cost": _sum_number(call.get("actual_cost") for call in llm_calls),
    }


def _raw_result_count_summary(
    *,
    preflight: Dict[str, Any],
    manifest: Dict[str, Any],
    expected_result_count: Optional[int],
    actual_result_count: int,
    min_cases: int,
    required_method_count: int,
) -> Dict[str, Any]:
    """Check the CTP100 formal raw-result count required by the paper protocol."""
    benchmark_case_count = _first_int(
        _nested(preflight, "benchmark", "case_count"),
        _nested(manifest, "benchmark_structure", "case_count"),
    )
    benchmark_turn_count = _first_int(
        _nested(preflight, "benchmark", "total_turn_count"),
        _nested(manifest, "benchmark_structure", "total_turn_count"),
    )
    method_count = _first_int(
        _nested(preflight, "run", "method_count"),
        len(_as_list(_nested(preflight, "run", "methods"))),
        required_method_count,
    )
    repeats = _first_int(_nested(preflight, "run", "repeats"), manifest.get("repeats"), 1)
    structure_expected = (
        benchmark_turn_count * method_count * repeats
        if benchmark_turn_count is not None
        and method_count is not None
        and repeats is not None
        else None
    )
    requires_ctp100_520 = _requires_ctp100_520_count(
        preflight=preflight,
        manifest=manifest,
        min_cases=min_cases,
        benchmark_case_count=benchmark_case_count,
        benchmark_turn_count=benchmark_turn_count,
    )
    expected_matches_structure = (
        expected_result_count is not None
        and structure_expected is not None
        and expected_result_count == structure_expected
    )
    ctp100_count_passed = (
        not requires_ctp100_520
        or (expected_result_count == 520 and actual_result_count == 520)
    )
    return {
        "schema_version": "ctp-formal-raw-result-count-v1",
        "requires_ctp100_520_result_count": requires_ctp100_520,
        "benchmark_case_count": benchmark_case_count,
        "benchmark_turn_count": benchmark_turn_count,
        "method_count": method_count,
        "repeats": repeats,
        "expected_result_count": expected_result_count,
        "actual_result_count": actual_result_count,
        "structure_expected_result_count": structure_expected,
        "expected_matches_structure": expected_matches_structure,
        "formal_ctp100_expected_raw_result_count": 520 if requires_ctp100_520 else None,
        "passed": ctp100_count_passed and expected_matches_structure,
    }


def _requires_ctp100_520_count(
    *,
    preflight: Dict[str, Any],
    manifest: Dict[str, Any],
    min_cases: int,
    benchmark_case_count: Optional[int],
    benchmark_turn_count: Optional[int],
) -> bool:
    dataset_id = str(
        manifest.get("dataset_id")
        or _nested(manifest, "dataset", "id")
        or _nested(preflight, "benchmark", "dataset_id")
        or ""
    ).strip()
    benchmark_path = str(
        _nested(preflight, "benchmark", "path")
        or manifest.get("dataset_path")
        or _nested(manifest, "dataset", "path")
        or ""
    ).replace("\\", "/")
    return (
        min_cases >= 100
        or dataset_id == "ctp100_formal_v2"
        or benchmark_path.endswith("experiments/benchmark.json")
        or benchmark_path.endswith("experiments/ctp100_formal_v2.json")
        or (benchmark_case_count == 100 and benchmark_turn_count == 130)
    )


def _method_result_grid_summary(
    results: List[Dict[str, Any]],
    *,
    required_methods: List[str],
    expected_result_count: Optional[int],
) -> Dict[str, Any]:
    required = set(required_methods)
    groups: Dict[tuple[str, str, int], Dict[str, int]] = {}
    duplicate_row_count = 0
    unexpected_method_row_count = 0
    invalid_identity_count = 0
    duplicate_samples: List[Dict[str, Any]] = []
    missing_samples: List[Dict[str, Any]] = []
    unexpected_samples: List[Dict[str, Any]] = []

    for result in results:
        case_id = str(result.get("case_id") or result.get("scenario_id") or "").strip()
        method = str(result.get("method") or "").strip()
        if not case_id or not method:
            invalid_identity_count += 1
            continue
        turn_id = str(result.get("turn_id") or "").strip()
        repeat_index = _int(result.get("repeat_index"), default=0)
        key = (case_id, turn_id, int(repeat_index or 0))
        method_counts = groups.setdefault(key, {})
        method_counts[method] = method_counts.get(method, 0) + 1
        if method not in required:
            unexpected_method_row_count += 1
            if len(unexpected_samples) < 10:
                unexpected_samples.append(
                    {
                        "case_id": case_id,
                        "turn_id": turn_id or None,
                        "repeat_index": int(repeat_index or 0),
                        "method": method,
                    }
                )

    missing_group_count = 0
    duplicate_method_group_count = 0
    for (case_id, turn_id, repeat_index), method_counts in sorted(groups.items()):
        missing = sorted(required - set(method_counts))
        duplicates = {
            method: count
            for method, count in sorted(method_counts.items())
            if count > 1
        }
        if missing:
            missing_group_count += 1
            if len(missing_samples) < 10:
                missing_samples.append(
                    {
                        "case_id": case_id,
                        "turn_id": turn_id or None,
                        "repeat_index": repeat_index,
                        "missing_methods": missing,
                    }
                )
        if duplicates:
            duplicate_method_group_count += 1
            duplicate_row_count += sum(count - 1 for count in duplicates.values())
            if len(duplicate_samples) < 10:
                duplicate_samples.append(
                    {
                        "case_id": case_id,
                        "turn_id": turn_id or None,
                        "repeat_index": repeat_index,
                        "duplicate_methods": duplicates,
                    }
                )

    expected_group_count = None
    expected_result_count_divisible = True
    if expected_result_count is not None and required_methods:
        expected_result_count_divisible = expected_result_count % len(required_methods) == 0
        if expected_result_count_divisible:
            expected_group_count = expected_result_count // len(required_methods)

    observed_group_count = len(groups)
    observed_group_count_matches_expected = (
        expected_group_count is None or observed_group_count == expected_group_count
    )
    passed = (
        bool(results)
        and invalid_identity_count == 0
        and unexpected_method_row_count == 0
        and missing_group_count == 0
        and duplicate_row_count == 0
        and expected_result_count_divisible
        and observed_group_count_matches_expected
    )
    return {
        "schema_version": "ctp-method-result-grid-v1",
        "required_methods": required_methods,
        "expected_result_count": expected_result_count,
        "expected_group_count": expected_group_count,
        "observed_group_count": observed_group_count,
        "expected_result_count_divisible_by_method_count": expected_result_count_divisible,
        "observed_group_count_matches_expected": observed_group_count_matches_expected,
        "invalid_identity_count": invalid_identity_count,
        "missing_method_group_count": missing_group_count,
        "duplicate_method_group_count": duplicate_method_group_count,
        "duplicate_method_result_count": duplicate_row_count,
        "unexpected_method_result_count": unexpected_method_row_count,
        "missing_samples": missing_samples,
        "duplicate_samples": duplicate_samples,
        "unexpected_samples": unexpected_samples,
        "passed": passed,
    }


def _metric_calculability_summary(
    results: List[Dict[str, Any]],
    summary: Dict[str, Any],
    *,
    required_methods: List[str],
) -> Dict[str, Any]:
    result_issues = _result_metric_calculability_issues(results)
    summary_issues = _summary_metric_calculability_issues(summary, required_methods)
    paired_issues = _paired_metric_calculability_issues(summary)
    decision_issues = _decision_normalization_summary_issues(summary, required_methods)
    return {
        "schema_version": "ctp-formal-metric-calculability-v1",
        "result_metric_values_calculable": not result_issues,
        "summary_core_metrics_calculable": not summary_issues and not decision_issues,
        "paired_core_metrics_calculable": not paired_issues,
        "decision_normalization_diagnostics_calculable": not decision_issues,
        "result_issue_count": len(result_issues),
        "summary_issue_count": len(summary_issues),
        "paired_issue_count": len(paired_issues),
        "decision_normalization_issue_count": len(decision_issues),
        "sample_result_issues": result_issues[:10],
        "sample_summary_issues": summary_issues[:10],
        "sample_paired_issues": paired_issues[:10],
        "sample_decision_normalization_issues": decision_issues[:10],
    }


def _result_metric_calculability_issues(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for result in results:
        metrics = _dict(result.get("metrics"))
        identity = {
            "case_id": result.get("case_id") or result.get("scenario_id"),
            "turn_id": result.get("turn_id"),
            "method": result.get("method"),
            "repeat_index": result.get("repeat_index"),
        }
        if not _is_rate(metrics.get("stsr")):
            issues.append({**identity, "metric": "stsr", "value": metrics.get("stsr")})
        hcsr_applicable = _int(metrics.get("evaluation_hcsr_applicable_count"), default=None)
        if hcsr_applicable is None:
            if not _is_rate(metrics.get("evaluation_hcsr")):
                issues.append(
                    {
                        **identity,
                        "metric": "evaluation_hcsr",
                        "value": metrics.get("evaluation_hcsr"),
                    }
                )
        elif hcsr_applicable > 0 and not _is_rate(metrics.get("evaluation_hcsr")):
            issues.append(
                {
                    **identity,
                    "metric": "evaluation_hcsr",
                    "value": metrics.get("evaluation_hcsr"),
                    "evaluation_hcsr_applicable_count": hcsr_applicable,
                }
            )
        bpcr_applicable = _int(metrics.get("bpcr_applicable_count"), default=None)
        if bpcr_applicable is None:
            if not _is_rate(metrics.get("bpcr")):
                issues.append({**identity, "metric": "bpcr", "value": metrics.get("bpcr")})
        elif bpcr_applicable > 0 and not _is_rate(metrics.get("bpcr")):
            issues.append(
                {
                    **identity,
                    "metric": "bpcr",
                    "value": metrics.get("bpcr"),
                    "bpcr_applicable_count": bpcr_applicable,
                }
            )
        for metric in (
            "agent_selection_f1",
            "tool_selection_f1",
            "llm_call_count",
            "agent_call_count",
            "called_tool_count",
            "total_tokens",
        ):
            if not _is_number(metrics.get(metric)):
                issues.append({**identity, "metric": metric, "value": metrics.get(metric)})
        if not _is_number(result.get("latency_ms")):
            issues.append({**identity, "metric": "latency_ms", "value": result.get("latency_ms")})
        standardized_cost = (
            metrics.get("standardized_estimated_cost")
            if metrics.get("standardized_estimated_cost") is not None
            else _nested(result, "run_audit", "metrics", "standardized_estimated_cost")
        )
        if not _is_number(standardized_cost) and not _is_zero_call_zero_token_result(
            result,
            metrics,
        ):
            issues.append(
                {
                    **identity,
                    "metric": "standardized_estimated_cost",
                    "value": metrics.get("standardized_estimated_cost"),
                }
            )
    return issues


def _is_zero_call_zero_token_result(
    result: Dict[str, Any],
    metrics: Dict[str, Any],
) -> bool:
    """Return true when a no-op row has no billable model/API work.

    Some formal rows are intentionally answered by deterministic routing
    without an LLM/API call, for example simple general-chat or clarification
    turns.  For those rows, a missing standardized cost means zero work rather
    than an uncalculated metric.
    """
    llm_calls = _number(metrics.get("llm_call_count"))
    api_calls = _number(metrics.get("api_call_count"))
    tokens = _number(metrics.get("total_tokens"))
    trace = _dict(result.get("trace"))
    trace_llm_calls = _number(trace.get("llm_call_count"))
    trace_api_calls = _number(trace.get("api_call_count"))
    trace_tokens = _number(trace.get("total_tokens"))
    return (
        (llm_calls in (None, 0.0))
        and (api_calls in (None, 0.0))
        and (tokens in (None, 0.0))
        and (trace_llm_calls in (None, 0.0))
        and (trace_api_calls in (None, 0.0))
        and (trace_tokens in (None, 0.0))
    )


def _summary_metric_calculability_issues(
    summary: Dict[str, Any],
    required_methods: List[str],
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    methods = _dict(summary.get("methods"))
    metric_keys = (
        "stsr_rate",
        "evaluation_hcsr_mean",
        "bpcr_mean",
        "agent_selection_f1_mean",
        "tool_selection_f1_mean",
        "llm_call_count_mean",
        "agent_call_count_mean",
        "total_tokens_mean",
        "standardized_estimated_cost_mean",
        "latency_ms_mean",
    )
    for method in required_methods:
        row = _dict(methods.get(method))
        for metric in metric_keys:
            if not _is_number(row.get(metric)):
                issues.append({"method": method, "metric": metric, "value": row.get(metric)})
        if not (
            _is_number(row.get("called_tool_count_mean"))
            or _is_number(row.get("tool_call_count_mean"))
        ):
            issues.append(
                {
                    "method": method,
                    "metric": "called_tool_count_mean/tool_call_count_mean",
                    "value": {
                        "called_tool_count_mean": row.get("called_tool_count_mean"),
                        "tool_call_count_mean": row.get("tool_call_count_mean"),
                    },
                }
            )
    return issues


def _decision_normalization_summary_issues(
    summary: Dict[str, Any],
    required_methods: List[str],
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    diagnostics = _dict(summary.get("decision_normalization"))
    if not diagnostics:
        return [{"section": "decision_normalization", "issue": "missing"}]
    if diagnostics.get("schema_version") != DECISION_NORMALIZATION_DIAGNOSTIC_SCHEMA_VERSION:
        issues.append(
            {
                "section": "decision_normalization",
                "metric": "schema_version",
                "value": diagnostics.get("schema_version"),
            }
        )
    for metric in (
        "result_count",
        "pipeline_completion_count",
        "agent_decision_total",
        "raw_decision_success_count",
        "normalizer_recovery_count",
    ):
        if not _is_number(diagnostics.get(metric)):
            issues.append(
                {
                    "section": "decision_normalization",
                    "metric": metric,
                    "value": diagnostics.get(metric),
                }
            )
    if not _is_rate(diagnostics.get("pipeline_completion_rate")):
        issues.append(
            {
                "section": "decision_normalization",
                "metric": "pipeline_completion_rate",
                "value": diagnostics.get("pipeline_completion_rate"),
            }
        )
    total = _int(diagnostics.get("agent_decision_total"), default=0) or 0
    if total > 0:
        for metric in ("raw_decision_success_rate", "normalizer_recovery_rate"):
            if not _is_rate(diagnostics.get(metric)):
                issues.append(
                    {
                        "section": "decision_normalization",
                        "metric": metric,
                        "value": diagnostics.get(metric),
                    }
                )

    by_method = _dict(diagnostics.get("by_method"))
    methods = _dict(summary.get("methods"))
    for method in required_methods:
        method_diag = _dict(_nested(methods.get(method), "decision_normalization"))
        if not method_diag:
            method_diag = _dict(by_method.get(method))
        if not method_diag:
            issues.append(
                {
                    "section": "decision_normalization.by_method",
                    "method": method,
                    "issue": "missing",
                }
            )
            continue
        for metric in (
            "result_count",
            "pipeline_completion_count",
            "agent_decision_total",
            "raw_decision_success_count",
            "normalizer_recovery_count",
        ):
            if not _is_number(method_diag.get(metric)):
                issues.append(
                    {
                        "section": "decision_normalization.by_method",
                        "method": method,
                        "metric": metric,
                        "value": method_diag.get(metric),
                    }
                )
        if not _is_rate(method_diag.get("pipeline_completion_rate")):
            issues.append(
                {
                    "section": "decision_normalization.by_method",
                    "method": method,
                    "metric": "pipeline_completion_rate",
                    "value": method_diag.get("pipeline_completion_rate"),
                }
            )
        method_total = _int(method_diag.get("agent_decision_total"), default=0) or 0
        if method_total > 0:
            for metric in ("raw_decision_success_rate", "normalizer_recovery_rate"):
                if not _is_rate(method_diag.get(metric)):
                    issues.append(
                        {
                            "section": "decision_normalization.by_method",
                            "method": method,
                            "metric": metric,
                            "value": method_diag.get(metric),
                        }
                    )
    return issues


def _paired_metric_calculability_issues(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    paired = _dict(summary.get("paired_statistics"))
    metrics = _dict(paired.get("metrics"))
    if _int(paired.get("pair_count"), default=0) <= 0:
        issues.append({"metric": "paired_statistics.pair_count", "value": paired.get("pair_count")})
        return issues
    for metric in (
        "stsr",
        "evaluation_hcsr",
        "bpcr",
        "llm_call_count",
        "agent_call_count",
        "tool_call_count",
        "total_tokens",
        "standardized_estimated_cost",
        "latency_ms",
    ):
        row = _dict(metrics.get(metric))
        values = {
            "m3_mean": _nested(row, "m3", "mean"),
            "m2_mean": _nested(row, "m2", "mean"),
            "delta_mean": _nested(row, "delta", "mean"),
        }
        for key, value in values.items():
            if not _is_number(value):
                issues.append({"metric": metric, "field": key, "value": value})
    return issues


def _is_rate(value: Any) -> bool:
    number = _number(value)
    return number is not None and 0.0 <= number <= 1.0


def _is_number(value: Any) -> bool:
    return _number(value) is not None


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
        if any(key not in metrics for key in _REQUIRED_METRIC_FIELDS):
            return False
    return True


def _all_results_have_metric_keys(
    results: List[Dict[str, Any]],
    keys: tuple[str, ...],
) -> bool:
    if not results:
        return False
    for result in results:
        metrics = result.get("metrics")
        if not isinstance(metrics, dict):
            return False
        if any(key not in metrics for key in keys):
            return False
    return True


def _result_status_summary(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    allowed = {"completed", "clarification", "failed"}
    missing = 0
    invalid = 0
    failed = 0
    statuses: Dict[str, int] = {}
    for result in results:
        status = (
            _nested(result, "output", "execution_status")
            or result.get("execution_status")
            or result.get("status")
        )
        status_text = str(status or "").strip().lower()
        if not status_text:
            missing += 1
            status_text = "missing"
        elif status_text not in allowed:
            invalid += 1
        if status_text == "failed" or result.get("status") == "failed" or result.get("error"):
            failed += 1
        statuses[status_text] = statuses.get(status_text, 0) + 1
    return {
        "status_counts": statuses,
        "missing_execution_status_count": missing,
        "invalid_execution_status_count": invalid,
        "failed_result_count": failed,
    }


def _api_failure_timeout_summary(traces: List[Dict[str, Any]]) -> Dict[str, Any]:
    failures = []
    for trace in traces:
        for group in ("llm_calls", "tool_calls", "api_calls"):
            for call in _as_dict_list(trace.get(group)):
                if _call_failed_or_timed_out(call):
                    failures.append(
                        {
                            "group": group,
                            "name": call.get("name")
                            or call.get("tool_name")
                            or call.get("model"),
                            "status": call.get("status"),
                            "error": call.get("error"),
                        }
                    )
    return {
        "failure_or_timeout_count": len(failures),
        "sample_failures": failures[:10],
    }


def _call_failed_or_timed_out(call: Dict[str, Any]) -> bool:
    if call.get("success") is False:
        return True
    if call.get("error"):
        return True
    status = str(call.get("status") or "").strip().lower()
    if status in {"failed", "error", "timeout", "timed_out"}:
        return True
    retry = call.get("retry") if isinstance(call.get("retry"), dict) else {}
    return retry.get("succeeded") is False


def _result_trace_evidence_exists(root: Path, result: Dict[str, Any]) -> bool:
    if isinstance(result.get("trace"), dict) and result["trace"]:
        return True
    path = _resolve_trace_path(root, result.get("trace_file"))
    return bool(path and path.exists())


def _load_traces(root: Path, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    traces = []
    for result in results:
        trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
        if trace:
            traces.append(trace)
            continue
        path = _resolve_trace_path(root, result.get("trace_file"))
        if path and path.exists():
            loaded = _read_jsonl_first(path)
            if loaded:
                traces.append(loaded)
    return traces


def _resolve_trace_path(root: Path, value: Any) -> Optional[Path]:
    if not value:
        return None
    path = Path(str(value))
    if path.is_absolute():
        return path
    for candidate in (root / path, root.parent / path, Path.cwd() / path):
        if candidate.exists():
            return candidate
    return path


def _method_contract_recorded(manifest: Dict[str, Any]) -> bool:
    contract = manifest.get("method_fairness_contract")
    return (
        isinstance(contract, dict)
        and bool(contract.get("schema_version"))
        and isinstance(contract.get("contract_sha256"), str)
        and len(contract.get("contract_sha256")) == 64
    )


def _commit_matches_preflight(
    manifest: Dict[str, Any],
    preflight: Dict[str, Any],
) -> bool:
    manifest_commit = manifest.get("git_commit") or _nested(manifest, "git", "commit")
    preflight_commit = _nested(preflight, "artifact_integrity", "git", "commit")
    return bool(manifest_commit and preflight_commit and manifest_commit == preflight_commit)


def _artifact_integrity_matches_preflight(
    manifest: Dict[str, Any],
    preflight: Dict[str, Any],
) -> bool:
    manifest_hash = _nested(manifest, "formal_artifact_integrity", "combined_sha256")
    preflight_hash = _nested(preflight, "artifact_integrity", "combined_sha256")
    return bool(manifest_hash and preflight_hash and manifest_hash == preflight_hash)


def _hypothesis_supported(analysis: Dict[str, Any], summary: Dict[str, Any]) -> bool:
    m3_vs_m2 = _dict(analysis.get("m3_vs_m2")) or _dict(summary.get("paired_statistics"))
    metrics = _dict(m3_vs_m2.get("metrics"))
    quality_non_decreasing = all(
        _metric_delta(metrics, metric) is not None
        and (_metric_delta(metrics, metric) or 0.0) >= 0
        for metric in ("stsr", "evaluation_hcsr", "bpcr")
    )
    resource_saving = any(
        _relative_saving(metrics, metric) is not None
        and (_relative_saving(metrics, metric) or 0.0) > 0
        for metric in (
            "llm_call_count",
            "agent_call_count",
            "tool_call_count",
            "total_tokens",
            "standardized_estimated_cost",
            "latency_ms",
        )
    )
    return bool(quality_non_decreasing and resource_saving)


def _metric_delta(metrics: Dict[str, Any], metric: str) -> Optional[float]:
    row = _dict(metrics.get(metric))
    value = row.get("delta_mean")
    if value is None:
        value = _nested(row, "delta", "mean")
    return _number(value)


def _relative_saving(metrics: Dict[str, Any], metric: str) -> Optional[float]:
    row = _dict(metrics.get(metric))
    value = row.get("relative_saving_rate")
    if value is not None:
        return _number(value)
    m3 = _number(_nested(row, "m3", "mean"))
    m2 = _number(_nested(row, "m2", "mean"))
    if m3 is None or m2 in (None, 0):
        return None
    return round((m2 - m3) / m2, 4)


def _expected_result_count(preflight: Dict[str, Any], summary: Dict[str, Any]) -> Optional[int]:
    for value in (
        _nested(preflight, "run", "expected_raw_run_count"),
        summary.get("raw_run_count"),
        summary.get("result_count"),
    ):
        number = _int(value)
        if number is not None:
            return number
    return None


def _effective_min_cases(min_cases: Optional[int]) -> int:
    if min_cases is None:
        return 100
    if isinstance(min_cases, bool) or int(min_cases) < 0:
        raise ValueError("min_cases must be a non-negative integer")
    return int(min_cases)


def _normalize_methods(methods: Iterable[str]) -> List[str]:
    normalized = [str(method).strip() for method in methods if str(method).strip()]
    if not normalized:
        raise ValueError("required_methods must not be empty")
    return normalized


def _has_mock_llm(llm_calls: List[Dict[str, Any]]) -> bool:
    return any(_bool(call.get("mock")) or _bool(call.get("mock_used")) for call in llm_calls)


def _has_fallback_llm(llm_calls: List[Dict[str, Any]]) -> bool:
    return any(_bool(call.get("fallback")) or _bool(call.get("fallback_used")) for call in llm_calls)


def _read_json_object(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_json_list(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _read_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_jsonl_first(path: Path) -> Dict[str, Any]:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _combined_hash(hashes: List[str]) -> Optional[str]:
    if not hashes:
        return None
    return hashlib.sha256("\n".join(sorted(hashes)).encode("utf-8")).hexdigest()


def _sum_usage(calls: List[Dict[str, Any]], *keys: str) -> Optional[float]:
    values = []
    for call in calls:
        usage = call.get("usage") if isinstance(call.get("usage"), dict) else call.get("tokens")
        usage = usage if isinstance(usage, dict) else {}
        values.append(_first_number(*(usage.get(key) for key in keys)))
    return _sum_number(values)


def _sum_number(values: Iterable[Any]) -> Optional[float]:
    numbers = [_first_number(value) for value in values]
    numbers = [value for value in numbers if value is not None]
    return None if not numbers else round(sum(numbers), 4)


def _first_number(*values: Any) -> Optional[float]:
    for value in values:
        number = _number(value)
        if number is not None:
            return number
    return None


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _int(*values: Any, default: Optional[int] = None) -> Optional[int]:
    for value in values:
        number = _number(value)
        if number is not None:
            return int(number)
    return default


def _first_int(*values: Any, default: Optional[int] = None) -> Optional[int]:
    return _int(*values, default=default)


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_dict_list(value: Any) -> List[Dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _interpretation(status: str) -> str:
    if status == "passed":
        return "Formal evidence package is complete enough for measured paper claims."
    return "Formal evidence package is not ready for paper claims; inspect failed_checks."


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return str(round(value, 4))
    return str(value)
