"""Paper-oriented analysis artifacts for saved experiment runs.

This module intentionally works from persisted experiment outputs.  It does
not run methods, call models, or re-score cases.  Its job is to turn the
already-saved benchmark results, evaluation summary, manifest, and traces into
a compact evidence package that can be inspected before writing the paper.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.core.independent_evaluator import EVALUATION_SUMMARY_SCHEMA_VERSION


PAPER_ANALYSIS_SCHEMA_VERSION = "ctp-paper-analysis-v1"
PAPER_ANALYSIS_JSON_NAME = "paper_analysis.json"
PAPER_ANALYSIS_MD_NAME = "paper_analysis.md"
DEFAULT_REQUIRED_METHODS = (
    "llm_direct",
    "single_agent",
    "fixed_multi_agent",
    "adaptive_multi_agent",
)

_METHOD_LABELS = {
    "llm_direct": "M0 Direct LLM",
    "single_agent": "M1 Single Agent",
    "fixed_multi_agent": "M2 Fixed Multi-Agent",
    "adaptive_multi_agent": "M3 Proposed",
}
_CORE_RESULT_ARTIFACTS = {
    "csv": "benchmark_results.csv",
    "json": "benchmark_results.json",
    "summary": "evaluation_summary.json",
    "paper_tables": "paper_tables.md",
    "manifest": "experiment_manifest.json",
}
_PRIMARY_METHOD_METRICS = (
    "stsr",
    "evaluation_hcsr",
    "agent_selection_f1",
    "tool_selection_f1",
    "llm_call_count",
    "agent_call_count",
    "called_tool_count",
    "tool_call_count",
    "total_tokens",
    "standardized_estimated_cost",
    "latency_ms",
)
_M3_M2_METRICS = (
    "stsr",
    "evaluation_hcsr",
    "agent_selection_f1",
    "tool_selection_f1",
    "llm_call_count",
    "agent_call_count",
    "tool_call_count",
    "total_tokens",
    "standardized_estimated_cost",
    "latency_ms",
)
_RESOURCE_SAVING_METRICS = {
    "llm_call_count",
    "agent_call_count",
    "tool_call_count",
    "total_tokens",
    "standardized_estimated_cost",
    "latency_ms",
}


def build_experiment_paper_analysis(
    run_dir: str | Path,
    *,
    profile: str = "auto",
    min_cases: Optional[int] = None,
    required_methods: Optional[Iterable[str]] = None,
    allow_mock_llm: bool = False,
) -> Dict[str, Any]:
    """Build a machine-readable analysis package from an experiment run dir.

    ``profile`` controls how readiness is interpreted:

    - ``pilot``: evidence can be analyzed, but paper conclusions are forbidden.
    - ``formal``: the run is checked against paper-readiness requirements.
    - ``auto``: chooses ``pilot`` when Day7 pilot evidence is present, otherwise
      ``formal``.
    """
    root = Path(run_dir)
    artifacts = _load_artifacts(root)
    resolved_profile = _resolve_profile(profile, artifacts)
    methods = artifacts["summary"].get("methods")
    methods = methods if isinstance(methods, dict) else {}
    effective_required_methods = _effective_required_methods(
        resolved_profile,
        required_methods,
        methods.keys(),
    )
    effective_min_cases = _effective_min_cases(resolved_profile, min_cases)
    csv_rows = _read_csv_rows(root / _CORE_RESULT_ARTIFACTS["csv"])
    results = artifacts["results"]
    traces = _load_traces_from_results(results)
    llm_calls = [
        call
        for trace in traces
        for call in _as_dict_list(trace.get("llm_calls"))
    ]
    readiness = _build_readiness(
        run_dir=root,
        profile=resolved_profile,
        artifacts=artifacts,
        csv_rows=csv_rows,
        results=results,
        traces=traces,
        llm_calls=llm_calls,
        min_cases=effective_min_cases,
        required_methods=effective_required_methods,
        allow_mock_llm=allow_mock_llm,
    )
    analysis = {
        "schema_version": PAPER_ANALYSIS_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": root.as_posix(),
        "profile": resolved_profile,
        "readiness": readiness,
        "run": _run_overview(root, artifacts, csv_rows, results, traces, llm_calls),
        "method_comparison": _method_comparison(artifacts["summary"]),
        "m3_vs_m2": _m3_vs_m2(artifacts["summary"]),
        "failure_analysis": _failure_analysis(artifacts["summary"], results),
        "trace_summary": _trace_summary(traces, llm_calls),
        "artifact_paths": _artifact_paths(root, artifacts),
        "paper_use_policy": _paper_use_policy(resolved_profile, readiness),
    }
    return analysis


def write_experiment_paper_analysis(
    run_dir: str | Path,
    *,
    output_dir: str | Path | None = None,
    profile: str = "auto",
    min_cases: Optional[int] = None,
    required_methods: Optional[Iterable[str]] = None,
    allow_mock_llm: bool = False,
    attach_to_manifest: bool = True,
) -> Dict[str, Any]:
    """Write ``paper_analysis.json`` and ``paper_analysis.md`` for a run."""
    root = Path(run_dir)
    output = Path(output_dir) if output_dir is not None else root
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / PAPER_ANALYSIS_JSON_NAME
    markdown_path = output / PAPER_ANALYSIS_MD_NAME
    analysis = build_experiment_paper_analysis(
        root,
        profile=profile,
        min_cases=min_cases,
        required_methods=required_methods,
        allow_mock_llm=allow_mock_llm,
    )
    analysis["artifact_paths"]["paper_analysis_json"] = json_path.as_posix()
    analysis["artifact_paths"]["paper_analysis_md"] = markdown_path.as_posix()
    json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_paper_analysis_markdown(analysis), encoding="utf-8")
    if attach_to_manifest:
        _attach_to_manifest(
            run_dir=root,
            json_path=json_path,
            markdown_path=markdown_path,
            analysis=analysis,
        )
    return {
        "status": "completed",
        "analysis": analysis,
        "json": json_path.as_posix(),
        "markdown": markdown_path.as_posix(),
        "readiness_status": analysis["readiness"]["status"],
        "paper_claims_allowed": analysis["readiness"]["paper_claims_allowed"],
    }


def render_paper_analysis_markdown(analysis: Dict[str, Any]) -> str:
    """Render a concise Markdown report from ``paper_analysis.json``."""
    readiness = _dict(analysis.get("readiness"))
    run = _dict(analysis.get("run"))
    method_rows = analysis.get("method_comparison")
    method_rows = method_rows if isinstance(method_rows, list) else []
    m3_vs_m2 = _dict(analysis.get("m3_vs_m2"))
    failure = _dict(analysis.get("failure_analysis"))
    trace = _dict(analysis.get("trace_summary"))
    policy = _dict(analysis.get("paper_use_policy"))

    lines = [
        "# Experiment paper analysis",
        "",
        "## Readiness",
        "",
        f"- profile: `{analysis.get('profile')}`",
        f"- status: `{readiness.get('status')}`",
        f"- paper_claims_allowed: `{readiness.get('paper_claims_allowed')}`",
        f"- run_id: `{run.get('run_id')}`",
        f"- independent_case_count: `{run.get('independent_case_count')}`",
        f"- raw_result_count: `{run.get('raw_result_count')}`",
        f"- failed_checks: `{readiness.get('failed_checks') or []}`",
        f"- policy: {policy.get('summary')}",
        "",
        "## Method comparison",
        "",
        "| Method | Cases | STSR | HCSR | Agent F1 | Tool F1 | LLM calls | Agent calls | Tool calls | Tokens | Std. cost | Latency ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in method_rows:
        lines.append(
            f"| {row.get('label')} | {_fmt(row.get('case_count'))} "
            f"| {_fmt(row.get('stsr'))} | {_fmt(row.get('evaluation_hcsr'))} "
            f"| {_fmt(row.get('agent_selection_f1'))} | {_fmt(row.get('tool_selection_f1'))} "
            f"| {_fmt(row.get('llm_call_count'))} | {_fmt(row.get('agent_call_count'))} "
            f"| {_fmt(row.get('called_tool_count') if row.get('called_tool_count') is not None else row.get('tool_call_count'))} "
            f"| {_fmt(row.get('total_tokens'))} | {_fmt(row.get('standardized_estimated_cost'))} "
            f"| {_fmt(row.get('latency_ms'))} |"
        )

    lines.extend(
        [
            "",
            "## M3 vs M2 paired comparison",
            "",
            f"- pair_count: `{m3_vs_m2.get('pair_count')}`",
            f"- comparison: `{m3_vs_m2.get('comparison')}`",
            "",
            "| Metric | M3 mean | M2 mean | Delta | 95% CI | p-value | Relative saving |",
            "|---|---:|---:|---:|---|---:|---:|",
        ]
    )
    for metric, row in _dict(m3_vs_m2.get("metrics")).items():
        lines.append(
            f"| {metric} | {_fmt(row.get('m3_mean'))} | {_fmt(row.get('m2_mean'))} "
            f"| {_fmt(row.get('delta_mean'))} | {_fmt_range(row.get('delta_ci_95'))} "
            f"| {_fmt(row.get('p_value'))} | {_fmt(row.get('relative_saving_rate'))} |"
        )

    lines.extend(
        [
            "",
            "## Failure analysis",
            "",
            "| Method | Failed cases | Top failed rules | Top tool failures |",
            "|---|---:|---|---|",
        ]
    )
    for method, row in _dict(failure.get("methods")).items():
        lines.append(
            f"| {_method_label(method)} | {_fmt(row.get('failed_case_count'))} "
            f"| {_fmt_counter(row.get('top_failed_rules'))} "
            f"| {_fmt_counter(row.get('top_tool_failure_types'))} |"
        )

    lines.extend(
        [
            "",
            "## Trace/runtime summary",
            "",
            f"- trace_count: `{trace.get('trace_count')}`",
            f"- llm_call_count: `{trace.get('llm_call_count')}`",
            f"- mock_llm_call_count: `{trace.get('mock_llm_call_count')}`",
            f"- fallback_llm_call_count: `{trace.get('fallback_llm_call_count')}`",
            f"- total_tokens: `{trace.get('total_tokens')}`",
            f"- standardized_estimated_cost: `{trace.get('standardized_estimated_cost')}`",
            "",
            "## Artifact paths",
            "",
            "| Artifact | Path |",
            "|---|---|",
        ]
    )
    for key, value in _dict(analysis.get("artifact_paths")).items():
        lines.append(f"| {key} | `{value}` |")
    return "\n".join(lines) + "\n"


def _load_artifacts(run_dir: Path) -> Dict[str, Any]:
    summary_path = run_dir / _CORE_RESULT_ARTIFACTS["summary"]
    results_path = run_dir / _CORE_RESULT_ARTIFACTS["json"]
    manifest_path = run_dir / _CORE_RESULT_ARTIFACTS["manifest"]
    day7_gate_path = run_dir / "day7_pilot_gate.json"
    formal_preflight_path = run_dir / "formal_preflight_report.json"
    return {
        "summary": _read_json_object(summary_path),
        "results": _read_json_list(results_path),
        "manifest": _read_json_object(manifest_path),
        "day7_gate": _read_json_object(day7_gate_path),
        "formal_preflight": _read_json_object(formal_preflight_path),
        "paths": {
            "summary": summary_path,
            "json": results_path,
            "manifest": manifest_path,
            "csv": run_dir / _CORE_RESULT_ARTIFACTS["csv"],
            "paper_tables": run_dir / _CORE_RESULT_ARTIFACTS["paper_tables"],
            "day7_gate": day7_gate_path,
            "formal_preflight": formal_preflight_path,
            "trace_dir": run_dir / "traces",
        },
    }


def _build_readiness(
    *,
    run_dir: Path,
    profile: str,
    artifacts: Dict[str, Any],
    csv_rows: List[Dict[str, str]],
    results: List[Dict[str, Any]],
    traces: List[Dict[str, Any]],
    llm_calls: List[Dict[str, Any]],
    min_cases: int,
    required_methods: List[str],
    allow_mock_llm: bool,
) -> Dict[str, Any]:
    summary = _dict(artifacts.get("summary"))
    manifest = _dict(artifacts.get("manifest"))
    methods = _dict(summary.get("methods"))
    expected_count = _expected_result_count(artifacts, summary)
    independent_case_count = _int(
        summary.get("independent_case_count"),
        summary.get("unique_case_count"),
        default=0,
    )
    missing_methods = [method for method in required_methods if method not in methods]
    checks: Dict[str, bool] = {
        "run_dir_exists": run_dir.exists(),
        "required_artifacts_exist": all(
            (run_dir / name).exists() for name in _CORE_RESULT_ARTIFACTS.values()
        ),
        "summary_schema_valid": summary.get("schema_version") == EVALUATION_SUMMARY_SCHEMA_VERSION,
        "manifest_present": bool(manifest),
        "csv_row_count_matches_results": not csv_rows or len(csv_rows) == len(results),
        "result_count_matches_expected": expected_count is None or len(results) == expected_count,
        "required_methods_present": not missing_methods,
        "m3_m2_pairs_present": _int(_nested(summary, "paired_statistics", "pair_count"), default=0) > 0,
        "minimum_case_count_met": independent_case_count >= min_cases,
        "strict_runtime_recorded": _nested(manifest, "runtime_config", "strict_mode") is True,
        "cache_disabled_recorded": _nested(manifest, "runtime_config", "cache_disabled") is True,
        "llm_calls_recorded": bool(llm_calls),
        "no_mock_llm": bool(allow_mock_llm) or not _has_mock_llm(llm_calls),
        "no_llm_fallback": not _has_fallback_llm(llm_calls),
        "user_message_not_persisted": all(not trace.get("user_message") for trace in traces),
    }
    if profile == "pilot":
        checks["day7_pilot_gate_passed"] = _dict(artifacts.get("day7_gate")).get("status") == "passed"
    if profile == "formal" and (run_dir / "formal_preflight_report.json").exists():
        checks["formal_preflight_passed"] = (
            _dict(artifacts.get("formal_preflight")).get("status") == "passed"
        )

    failed_checks = [key for key, value in checks.items() if not value]
    if profile == "pilot":
        status = "analysis_only" if not failed_checks else "failed"
        paper_claims_allowed = False
    else:
        status = "ready" if not failed_checks else "not_ready"
        paper_claims_allowed = status == "ready"
    return {
        "status": status,
        "profile": profile,
        "paper_claims_allowed": paper_claims_allowed,
        "failed_checks": failed_checks,
        "checks": checks,
        "required_methods": required_methods,
        "missing_methods": missing_methods,
        "min_cases": min_cases,
        "independent_case_count": independent_case_count,
        "expected_result_count": expected_count,
        "actual_result_count": len(results),
        "interpretation": _readiness_interpretation(profile, status),
    }


def _run_overview(
    run_dir: Path,
    artifacts: Dict[str, Any],
    csv_rows: List[Dict[str, str]],
    results: List[Dict[str, Any]],
    traces: List[Dict[str, Any]],
    llm_calls: List[Dict[str, Any]],
) -> Dict[str, Any]:
    summary = _dict(artifacts.get("summary"))
    manifest = _dict(artifacts.get("manifest"))
    methods = _dict(summary.get("methods"))
    return {
        "run_dir": run_dir.as_posix(),
        "run_id": manifest.get("run_id") or _nested(artifacts.get("day7_gate"), "run_id"),
        "dataset_id": manifest.get("dataset_id") or _nested(manifest, "dataset", "id"),
        "dataset_version": manifest.get("dataset_version") or _nested(manifest, "dataset", "version"),
        "method_count": len(methods),
        "methods": list(methods.keys()),
        "raw_result_count": len(results),
        "csv_row_count": len(csv_rows),
        "summary_raw_run_count": summary.get("raw_run_count") or summary.get("result_count"),
        "independent_case_count": _int(
            summary.get("independent_case_count"),
            summary.get("unique_case_count"),
            default=0,
        ),
        "paired_m3_m2_count": _int(_nested(summary, "paired_statistics", "pair_count"), default=0),
        "trace_count": len(traces),
        "llm_call_count": len(llm_calls),
        "strict_mode": _nested(manifest, "runtime_config", "strict_mode"),
        "cache_disabled": _nested(manifest, "runtime_config", "cache_disabled"),
        "model_config_name": manifest.get("model_config_name") or _nested(manifest, "model_config", "name"),
        "model": manifest.get("model") or _nested(manifest, "model_config", "model"),
    }


def _method_comparison(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    methods = _dict(summary.get("methods"))
    rows: List[Dict[str, Any]] = []
    for method in _method_order(methods):
        source = _dict(methods.get(method))
        row = {
            "method": method,
            "label": _method_label(method),
            "case_count": source.get("case_count"),
            "raw_run_count": source.get("raw_run_count"),
        }
        for metric in _PRIMARY_METHOD_METRICS:
            row[metric] = _method_metric_value(source, metric)
        rows.append(row)
    return rows


def _m3_vs_m2(summary: Dict[str, Any]) -> Dict[str, Any]:
    paired = _dict(summary.get("paired_statistics"))
    metric_stats = _dict(paired.get("metrics"))
    metrics = {}
    for metric in _M3_M2_METRICS:
        stat = _dict(metric_stats.get(metric))
        m3_mean = _number(_nested(stat, "m3", "mean"))
        m2_mean = _number(_nested(stat, "m2", "mean"))
        delta_mean = _number(_nested(stat, "delta", "mean"))
        metrics[metric] = {
            "pair_count": _int(stat.get("pair_count"), default=0),
            "m3_mean": m3_mean,
            "m2_mean": m2_mean,
            "delta_mean": delta_mean,
            "delta_median": _nested(stat, "delta", "median"),
            "delta_iqr": _nested(stat, "delta", "iqr"),
            "delta_ci_95": _nested(stat, "delta", "bootstrap_ci_95"),
            "p_value": _paired_p_value(stat),
            "test": _paired_test_name(stat),
            "relative_saving_rate": _relative_saving_rate(metric, m3_mean, m2_mean),
        }
    return {
        "comparison": paired.get("comparison") or "adaptive_multi_agent_vs_fixed_multi_agent",
        "pair_count": _int(paired.get("pair_count"), default=0),
        "metrics": metrics,
        "interpretation": (
            "Negative deltas on resource metrics mean M3 uses less resource than M2. "
            "Relative saving is computed as (M2 mean - M3 mean) / M2 mean."
        ),
    }


def _failure_analysis(summary: Dict[str, Any], results: List[Dict[str, Any]]) -> Dict[str, Any]:
    methods = _dict(summary.get("methods"))
    failed_cases: Dict[str, List[Dict[str, Any]]] = {}
    for result in results:
        if result.get("target_turn") is False:
            continue
        method = str(result.get("method") or "unknown")
        metrics = _dict(result.get("metrics"))
        failed_rules = _as_list(metrics.get("evaluation_failed_rule_ids"))
        stsr = _number(metrics.get("stsr"))
        if failed_rules or stsr == 0.0:
            failed_cases.setdefault(method, []).append(
                {
                    "case_id": result.get("case_id"),
                    "turn_id": result.get("turn_id"),
                    "failed_rule_ids": failed_rules,
                    "stsr": metrics.get("stsr"),
                    "task_type": _nested(result, "evaluation", "task_type")
                    or _nested(result, "output", "task_type"),
                }
            )
    method_payload: Dict[str, Any] = {}
    for method in _method_order(methods):
        source = _dict(methods.get(method))
        method_payload[method] = {
            "failed_case_count": len(failed_cases.get(method, [])),
            "sample_failed_cases": failed_cases.get(method, [])[:10],
            "top_failed_rules": _counter_items(source.get("top_failed_rules")),
            "top_tool_failure_types": _counter_items(source.get("top_tool_failure_types")),
        }
    return {
        "methods": method_payload,
        "total_failed_case_count": sum(len(items) for items in failed_cases.values()),
        "failure_count_by_rule": _failure_count_by_rule(failed_cases),
    }


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


def _artifact_paths(run_dir: Path, artifacts: Dict[str, Any]) -> Dict[str, str]:
    paths = _dict(artifacts.get("paths"))
    result = {}
    for key, value in paths.items():
        path = Path(value)
        if path.exists():
            result[key] = path.as_posix()
    result["run_dir"] = run_dir.as_posix()
    return result


def _paper_use_policy(profile: str, readiness: Dict[str, Any]) -> Dict[str, Any]:
    if profile == "pilot":
        return {
            "summary": (
                "Pilot analysis may be used to debug the pipeline, but must not be "
                "reported as final academic evidence."
            ),
            "allowed_uses": [
                "pipeline verification",
                "artifact completeness inspection",
                "small-sample failure diagnosis",
            ],
            "forbidden_uses": [
                "formal paper conclusion",
                "claiming model superiority",
                "reporting pilot scores as final experiment results",
            ],
        }
    if readiness.get("paper_claims_allowed") is True:
        return {
            "summary": "Formal run passes reproducibility/readiness checks for paper drafting.",
            "allowed_uses": [
                "method comparison table",
                "M3 vs M2 statistical comparison",
                "cost and token analysis",
                "failure analysis",
            ],
            "forbidden_uses": ["claims outside measured metrics"],
        }
    return {
        "summary": "Formal run is not ready for paper claims until failed checks are fixed.",
        "allowed_uses": ["debugging", "internal diagnosis"],
        "forbidden_uses": ["paper conclusion", "method superiority claim"],
    }


def _attach_to_manifest(
    *,
    run_dir: Path,
    json_path: Path,
    markdown_path: Path,
    analysis: Dict[str, Any],
) -> None:
    manifest_path = run_dir / _CORE_RESULT_ARTIFACTS["manifest"]
    manifest = _read_json_object(manifest_path)
    if not manifest:
        return
    results = _dict(manifest.get("results"))
    results.update(
        {
            "paper_analysis_json": json_path.as_posix(),
            "paper_analysis_md": markdown_path.as_posix(),
        }
    )
    manifest["results"] = results
    manifest["paper_analysis"] = {
        "schema_version": PAPER_ANALYSIS_SCHEMA_VERSION,
        "status": _nested(analysis, "readiness", "status"),
        "paper_claims_allowed": _nested(analysis, "readiness", "paper_claims_allowed"),
        "profile": analysis.get("profile"),
        "failed_checks": _nested(analysis, "readiness", "failed_checks") or [],
        "json": json_path.as_posix(),
        "markdown": markdown_path.as_posix(),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_profile(profile: str, artifacts: Dict[str, Any]) -> str:
    normalized = str(profile or "auto").strip().lower()
    if normalized not in {"auto", "pilot", "formal"}:
        raise ValueError("profile must be one of: auto, pilot, formal")
    if normalized != "auto":
        return normalized
    manifest = _dict(artifacts.get("manifest"))
    if artifacts.get("day7_gate") or manifest.get("day7_pilot"):
        return "pilot"
    return "formal"


def _effective_required_methods(
    profile: str,
    required_methods: Optional[Iterable[str]],
    observed_methods: Iterable[str],
) -> List[str]:
    if required_methods is not None:
        return _normalize_methods(required_methods)
    if profile == "formal":
        return list(DEFAULT_REQUIRED_METHODS)
    return sorted(str(method) for method in observed_methods)


def _effective_min_cases(profile: str, min_cases: Optional[int]) -> int:
    if min_cases is not None:
        if isinstance(min_cases, bool) or int(min_cases) < 0:
            raise ValueError("min_cases must be a non-negative integer")
        return int(min_cases)
    return 100 if profile == "formal" else 1


def _expected_result_count(artifacts: Dict[str, Any], summary: Dict[str, Any]) -> Optional[int]:
    for value in (
        _nested(artifacts.get("day7_gate"), "expected_result_count"),
        _nested(artifacts.get("formal_preflight"), "run", "expected_raw_run_count"),
        summary.get("raw_run_count"),
        summary.get("result_count"),
    ):
        number = _int(value)
        if number is not None:
            return number
    return None


def _readiness_interpretation(profile: str, status: str) -> str:
    if profile == "pilot":
        if status == "analysis_only":
            return "Pilot evidence is complete enough for debugging, not for paper conclusions."
        return "Pilot evidence has failed checks and should be fixed before expanding the run."
    if status == "ready":
        return "Formal run is ready to support paper-level result tables within measured claims."
    return "Formal run is not ready for paper claims; inspect failed_checks first."


def _method_metric_value(source: Dict[str, Any], metric: str) -> Any:
    if metric == "stsr":
        return source.get("stsr_rate")
    candidates = (f"{metric}_mean", metric)
    for key in candidates:
        if key in source:
            return source.get(key)
    stats = _nested(source, "descriptive_statistics", metric, "mean")
    return stats


def _relative_saving_rate(metric: str, m3_mean: Optional[float], m2_mean: Optional[float]) -> Optional[float]:
    if metric not in _RESOURCE_SAVING_METRICS:
        return None
    if m3_mean is None or m2_mean in (None, 0):
        return None
    return round((m2_mean - m3_mean) / m2_mean, 4)


def _paired_p_value(stat: Dict[str, Any]) -> Any:
    for key in ("mcnemar", "wilcoxon_signed_rank"):
        value = stat.get(key)
        if isinstance(value, dict) and value.get("p_value") is not None:
            return value.get("p_value")
    return None


def _paired_test_name(stat: Dict[str, Any]) -> str:
    if isinstance(stat.get("mcnemar"), dict):
        return "McNemar"
    if isinstance(stat.get("wilcoxon_signed_rank"), dict):
        return "Wilcoxon"
    return ""


def _failure_count_by_rule(failed_cases: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    counter: Counter[str] = Counter()
    for cases in failed_cases.values():
        for case in cases:
            counter.update(_as_list(case.get("failed_rule_ids")))
    return [{"id": rule_id, "count": count} for rule_id, count in counter.most_common()]


def _load_traces_from_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    traces: List[Dict[str, Any]] = []
    for result in results:
        trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
        if trace:
            traces.append(trace)
            continue
        trace_file = result.get("trace_file")
        if trace_file:
            loaded = _read_jsonl_first(Path(str(trace_file)))
            if loaded:
                traces.append(loaded)
    return traces


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
    if not path.exists():
        return {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def _has_mock_llm(llm_calls: List[Dict[str, Any]]) -> bool:
    return any(_bool(call.get("mock")) or _bool(call.get("mock_used")) for call in llm_calls)


def _has_fallback_llm(llm_calls: List[Dict[str, Any]]) -> bool:
    return any(_bool(call.get("fallback")) or _bool(call.get("fallback_used")) for call in llm_calls)


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


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_dict_list(value: Any) -> List[Dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]
    return [str(value)]


def _counter_items(value: Any) -> List[Dict[str, Any]]:
    items = value if isinstance(value, list) else []
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        identifier = item.get("rule_id") or item.get("failure_type") or item.get("id")
        count = item.get("count")
        if identifier:
            result.append({"id": str(identifier), "count": _int(count, default=0)})
    return result


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _normalize_methods(methods: Iterable[str]) -> List[str]:
    normalized = [str(method).strip() for method in methods if str(method).strip()]
    if not normalized:
        raise ValueError("required_methods must not be empty")
    return normalized


def _method_order(methods: Dict[str, Any]) -> List[str]:
    preferred = [method for method in DEFAULT_REQUIRED_METHODS if method in methods]
    return preferred + sorted(method for method in methods if method not in DEFAULT_REQUIRED_METHODS)


def _method_label(method: str) -> str:
    return _METHOD_LABELS.get(method, method)


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return str(round(value, 4))
    return str(value)


def _fmt_range(value: Any) -> str:
    items = value if isinstance(value, list) else []
    return "" if len(items) != 2 else f"[{_fmt(items[0])}, {_fmt(items[1])}]"


def _fmt_counter(value: Any) -> str:
    items = value if isinstance(value, list) else []
    if not items:
        return ""
    return ", ".join(
        f"{item.get('id')}({item.get('count')})"
        for item in items[:5]
        if isinstance(item, dict)
    )
