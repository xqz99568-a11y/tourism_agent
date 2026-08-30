"""Offline CTP100 M2/M3 repeat-stability analysis.

This module only reads completed experiment artifacts. It does not call an LLM
or change any experiment method behavior.
"""
from __future__ import annotations

import csv
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from app.core.independent_evaluator import (
    render_paper_tables,
    summarize_evaluation_results,
)


CTP100_STABILITY_ANALYSIS_SCHEMA_VERSION = (
    "ctp100-m2-m3-stability-combined-analysis-v1"
)
CTP100_STABILITY_MANIFEST_SCHEMA_VERSION = (
    "ctp100-m2-m3-stability-analysis-manifest-v1"
)

M2_METHOD = "fixed_multi_agent"
M3_METHOD = "adaptive_multi_agent"
METHODS = (M2_METHOD, M3_METHOD)
METHOD_LABELS = {
    M2_METHOD: "M2 Fixed Multi-Agent",
    M3_METHOD: "M3 Adaptive Multi-Agent",
}

ANALYSIS_JSON_NAME = "ctp100_m2_m3_stability_combined_analysis.json"
ANALYSIS_MD_NAME = "ctp100_m2_m3_stability_combined_analysis.md"
COMBINED_SUMMARY_JSON_NAME = "combined_evaluation_summary.json"
COMBINED_PAPER_TABLES_MD_NAME = "combined_paper_tables.md"
REPEAT_METRICS_CSV_NAME = "repeat_method_metrics.csv"
PAIR_DELTAS_CSV_NAME = "repeat_pair_deltas.csv"
MANIFEST_JSON_NAME = "analysis_manifest.json"


def write_ctp100_m2_m3_stability_analysis(
    *,
    v6_run_dir: str | Path,
    stability_run_dir: str | Path,
    output_dir: str | Path,
    expected_quality_units_per_method_repeat: int = 100,
    expected_raw_rows_per_method_repeat: int = 130,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Build and write offline repeat-stability analysis artifacts."""

    output = Path(output_dir)
    v6 = Path(v6_run_dir)
    stability = Path(stability_run_dir)
    _validate_output_dir(output, source_dirs=(v6, stability), overwrite=overwrite)

    analysis = build_ctp100_m2_m3_stability_analysis(
        v6_run_dir=v6,
        stability_run_dir=stability,
        expected_quality_units_per_method_repeat=expected_quality_units_per_method_repeat,
        expected_raw_rows_per_method_repeat=expected_raw_rows_per_method_repeat,
    )

    output.mkdir(parents=True, exist_ok=True)
    summary_path = output / COMBINED_SUMMARY_JSON_NAME
    paper_tables_path = output / COMBINED_PAPER_TABLES_MD_NAME
    repeat_csv_path = output / REPEAT_METRICS_CSV_NAME
    pair_csv_path = output / PAIR_DELTAS_CSV_NAME
    analysis_json_path = output / ANALYSIS_JSON_NAME
    analysis_md_path = output / ANALYSIS_MD_NAME
    manifest_path = output / MANIFEST_JSON_NAME

    summary = analysis["combined_evaluation_summary"]
    summary_path.write_text(_json_dumps(summary), encoding="utf-8")
    paper_tables_path.write_text(render_paper_tables(summary), encoding="utf-8")
    _write_csv(repeat_csv_path, analysis["repeat_method_metrics"])
    _write_csv(pair_csv_path, analysis["repeat_pair_deltas"])

    analysis["artifact_paths"] = {
        "analysis_json": analysis_json_path.as_posix(),
        "analysis_md": analysis_md_path.as_posix(),
        "combined_evaluation_summary": summary_path.as_posix(),
        "combined_paper_tables": paper_tables_path.as_posix(),
        "repeat_method_metrics_csv": repeat_csv_path.as_posix(),
        "repeat_pair_deltas_csv": pair_csv_path.as_posix(),
        "manifest": manifest_path.as_posix(),
    }
    analysis_json_path.write_text(_json_dumps(analysis), encoding="utf-8")
    analysis_md_path.write_text(render_ctp100_m2_m3_stability_analysis(analysis), encoding="utf-8")

    manifest = build_ctp100_m2_m3_stability_analysis_manifest(
        analysis=analysis,
        output_dir=output,
        artifact_paths=[
            analysis_json_path,
            analysis_md_path,
            summary_path,
            paper_tables_path,
            repeat_csv_path,
            pair_csv_path,
        ],
    )
    manifest_path.write_text(_json_dumps(manifest), encoding="utf-8")
    analysis["artifact_hashes"] = manifest["artifact_hashes"]
    analysis_json_path.write_text(_json_dumps(analysis), encoding="utf-8")
    manifest = build_ctp100_m2_m3_stability_analysis_manifest(
        analysis=analysis,
        output_dir=output,
        artifact_paths=[
            analysis_json_path,
            analysis_md_path,
            summary_path,
            paper_tables_path,
            repeat_csv_path,
            pair_csv_path,
        ],
    )
    manifest_path.write_text(_json_dumps(manifest), encoding="utf-8")

    return {
        "analysis_status": analysis["status"],
        "output_dir": output.as_posix(),
        "analysis_json": analysis_json_path.as_posix(),
        "analysis_md": analysis_md_path.as_posix(),
        "combined_evaluation_summary": summary_path.as_posix(),
        "combined_paper_tables": paper_tables_path.as_posix(),
        "repeat_method_metrics_csv": repeat_csv_path.as_posix(),
        "repeat_pair_deltas_csv": pair_csv_path.as_posix(),
        "manifest": manifest_path.as_posix(),
        "failed_checks": analysis["failed_checks"],
    }


def build_ctp100_m2_m3_stability_analysis(
    *,
    v6_run_dir: str | Path,
    stability_run_dir: str | Path,
    expected_quality_units_per_method_repeat: int = 100,
    expected_raw_rows_per_method_repeat: int = 130,
) -> Dict[str, Any]:
    """Merge CTP100 v6 repeat 0 with stability repeats 1/2 and summarize."""

    v6 = Path(v6_run_dir)
    stability = Path(stability_run_dir)
    v6_results_path = v6 / "benchmark_results.json"
    stability_results_path = stability / "benchmark_results.json"

    v6_rows = _load_json_list(v6_results_path)
    stability_rows = _load_json_list(stability_results_path)
    selected_rows = _select_m2_m3_repeats(
        v6_rows=v6_rows,
        stability_rows=stability_rows,
    )

    validations = _validate_selected_rows(
        selected_rows,
        expected_quality_units_per_method_repeat=expected_quality_units_per_method_repeat,
        expected_raw_rows_per_method_repeat=expected_raw_rows_per_method_repeat,
    )
    failed_checks = [
        item["check"]
        for item in validations
        if not item.get("passed")
    ]

    combined_summary = summarize_evaluation_results(selected_rows)
    repeat_summaries = {
        str(repeat): summarize_evaluation_results(
            [row for row in selected_rows if _repeat_index(row) == repeat]
        )
        for repeat in (0, 1, 2)
    }
    repeat_method_metrics = _repeat_method_metrics(selected_rows)
    repeat_pair_deltas = _repeat_pair_deltas(repeat_summaries)
    aggregate_repeat_stats = _aggregate_repeat_stats(
        repeat_method_metrics=repeat_method_metrics,
        repeat_pair_deltas=repeat_pair_deltas,
    )
    source_artifacts = _source_artifacts(
        v6_run_dir=v6,
        stability_run_dir=stability,
        v6_results_path=v6_results_path,
        stability_results_path=stability_results_path,
    )

    combined_stsr = _nested(combined_summary, "paired_statistics", "metrics", "stsr")
    combined_summary_shape_valid = _combined_summary_shape_is_valid(
        combined_summary,
        expected_quality_units_per_method_repeat=expected_quality_units_per_method_repeat,
        expected_raw_rows_per_method_repeat=expected_raw_rows_per_method_repeat,
    )
    if not combined_summary_shape_valid and "combined_summary_shape" not in failed_checks:
        failed_checks.append("combined_summary_shape")
    status = "passed" if not failed_checks else "failed"

    return {
        "schema_version": CTP100_STABILITY_ANALYSIS_SCHEMA_VERSION,
        "status": status,
        "failed_checks": failed_checks,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "analysis_scope": {
            "analysis_type": "offline_ctp100_m2_m3_repeat_stability",
            "llm_calls_performed": 0,
            "source_repeats": {
                "formal_ctp100_v6": [0],
                "ctp100_m2_m3_stability": [1, 2],
            },
            "methods": list(METHODS),
            "quality_evaluation_scope": "target turn only for multi-turn scenarios",
            "raw_resource_scope": "all 130 run rows per method per repeat",
        },
        "source_artifacts": source_artifacts,
        "validation_checks": validations,
        "row_counts": _row_counts(selected_rows),
        "repeat_method_metrics": repeat_method_metrics,
        "repeat_pair_deltas": repeat_pair_deltas,
        "aggregate_repeat_stats": aggregate_repeat_stats,
        "combined_key_results": _combined_key_results(combined_summary, combined_stsr),
        "combined_evaluation_summary": combined_summary,
        "paper_claim_guidance": _paper_claim_guidance(
            status=status,
            combined_stsr=combined_stsr,
            repeat_pair_deltas=repeat_pair_deltas,
        ),
    }


def build_ctp100_m2_m3_stability_analysis_manifest(
    *,
    analysis: Mapping[str, Any],
    output_dir: str | Path,
    artifact_paths: Sequence[str | Path],
) -> Dict[str, Any]:
    """Build a manifest for generated offline-analysis artifacts."""

    output = Path(output_dir)
    artifacts = {Path(path).name: Path(path) for path in artifact_paths}
    return {
        "schema_version": CTP100_STABILITY_MANIFEST_SCHEMA_VERSION,
        "status": analysis.get("status"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "output_dir": output.as_posix(),
        "source_artifacts": analysis.get("source_artifacts"),
        "analysis_json": (output / ANALYSIS_JSON_NAME).as_posix(),
        "artifact_hashes": {
            name: _file_sha256(path)
            for name, path in sorted(artifacts.items())
        },
        "files_combined_sha256": _combined_file_sha256(artifacts.values()),
    }


def render_ctp100_m2_m3_stability_analysis(analysis: Mapping[str, Any]) -> str:
    """Render a paper-facing Markdown summary for the offline analysis."""

    combined = analysis.get("combined_key_results") or {}
    stsr = combined.get("stsr") or {}
    rows_by_repeat = {
        row["repeat_index"]: row
        for row in analysis.get("repeat_pair_deltas") or []
    }
    method_rows = analysis.get("repeat_method_metrics") or []
    method_by_key = {
        (row["repeat_index"], row["method"]): row
        for row in method_rows
    }
    lines = [
        "# CTP100 M2/M3 Repeat-Stability Analysis",
        "",
        "## Scope",
        "",
        f"- status: `{analysis.get('status')}`",
        f"- failed_checks: `{analysis.get('failed_checks') or []}`",
        "- analysis type: offline only; no LLM/API call is performed.",
        "- source repeats: formal CTP100 v6 repeat 0 + stability repeats 1 and 2.",
        "- quality metrics use target turns only for multi-turn cases; resource metrics use all raw run rows.",
        "",
        "## Combined key result after three repeats",
        "",
        "| Metric | M2 | M3 | M3-M2 | 95% CI | McNemar p |",
        "|---|---:|---:|---:|---:|---:|",
        (
            f"| STSR | {_fmt(stsr.get('m2_mean'))} | {_fmt(stsr.get('m3_mean'))} "
            f"| {_fmt(stsr.get('delta_mean'))} | {_fmt_range(stsr.get('delta_ci_95'))} "
            f"| {_fmt(stsr.get('mcnemar_p_value'))} |"
        ),
        "",
        "## Repeat-level STSR stability",
        "",
        "| Repeat | M2 STSR | M3 STSR | M3-M2 | 95% CI | McNemar p | M2 std. cost | M3 std. cost | M2 latency mean ms | M3 latency mean ms |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for repeat in sorted(rows_by_repeat):
        delta = rows_by_repeat[repeat]
        m2 = method_by_key.get((repeat, M2_METHOD), {})
        m3 = method_by_key.get((repeat, M3_METHOD), {})
        lines.append(
            f"| {repeat} | {_fmt(delta.get('m2_stsr'))} | {_fmt(delta.get('m3_stsr'))} "
            f"| {_fmt(delta.get('stsr_delta'))} | {_fmt_range(delta.get('stsr_delta_ci_95'))} "
            f"| {_fmt(delta.get('stsr_mcnemar_p_value'))} "
            f"| {_fmt(m2.get('raw_standardized_estimated_cost_sum'))} "
            f"| {_fmt(m3.get('raw_standardized_estimated_cost_sum'))} "
            f"| {_fmt(m2.get('raw_latency_ms_mean'))} "
            f"| {_fmt(m3.get('raw_latency_ms_mean'))} |"
        )
    guidance = analysis.get("paper_claim_guidance") or {}
    lines.extend(
        [
            "",
            "## Paper-use guidance",
            "",
            f"- claim_level: `{guidance.get('claim_level')}`",
            f"- suggested_wording: {guidance.get('suggested_wording')}",
            "",
            "## Source files",
            "",
        ]
    )
    for key, value in (analysis.get("source_artifacts") or {}).items():
        if isinstance(value, Mapping):
            lines.append(f"- {key}: `{value.get('path')}`")
    return "\n".join(lines) + "\n"


def _select_m2_m3_repeats(
    *,
    v6_rows: Iterable[Mapping[str, Any]],
    stability_rows: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    for row in v6_rows:
        if row.get("method") in METHODS and _repeat_index(row) == 0:
            copied = dict(row)
            copied["stability_source_role"] = "formal_ctp100_v6_repeat_0"
            selected.append(copied)
    for row in stability_rows:
        if row.get("method") in METHODS and _repeat_index(row) in {1, 2}:
            copied = dict(row)
            copied["stability_source_role"] = "ctp100_m2_m3_stability_repeat_1_2"
            selected.append(copied)
    return selected


def _validate_selected_rows(
    rows: List[Dict[str, Any]],
    *,
    expected_quality_units_per_method_repeat: int,
    expected_raw_rows_per_method_repeat: int,
) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    expected_repeats = {0, 1, 2}
    repeats = sorted({_repeat_index(row) for row in rows})
    methods = sorted({str(row.get("method") or "") for row in rows})
    expected_raw_total = (
        len(METHODS) * len(expected_repeats) * expected_raw_rows_per_method_repeat
    )
    expected_quality_total = (
        len(METHODS) * len(expected_repeats) * expected_quality_units_per_method_repeat
    )

    checks.append(_check("methods_are_m2_m3_only", set(methods) == set(METHODS), {"methods": methods}))
    checks.append(_check("repeat_indices_are_0_1_2", set(repeats) == expected_repeats, {"repeat_indices": repeats}))
    checks.append(_check("raw_row_count", len(rows) == expected_raw_total, {"actual": len(rows), "expected": expected_raw_total}))

    allowed_statuses = {"completed", "success", "passed", "clarification"}
    allowed_count = sum(_status(row) in allowed_statuses for row in rows)
    status_counts = Counter(_status(row) for row in rows)
    checks.append(
        _check(
            "all_rows_have_allowed_experiment_status",
            allowed_count == len(rows),
            {
                "allowed": sorted(allowed_statuses),
                "allowed_count": allowed_count,
                "total": len(rows),
                "status_counts": dict(sorted(status_counts.items())),
            },
        )
    )

    quality_rows = [row for row in rows if _is_quality_evaluation_row(row)]
    checks.append(
        _check(
            "quality_row_count",
            len(quality_rows) == expected_quality_total,
            {"actual": len(quality_rows), "expected": expected_quality_total},
        )
    )

    raw_counts = Counter((str(row.get("method") or ""), _repeat_index(row)) for row in rows)
    quality_counts = Counter(
        (str(row.get("method") or ""), _repeat_index(row))
        for row in quality_rows
    )
    raw_count_failures = {
        f"{method}:{repeat}": raw_counts[(method, repeat)]
        for method in METHODS
        for repeat in expected_repeats
        if raw_counts[(method, repeat)] != expected_raw_rows_per_method_repeat
    }
    quality_count_failures = {
        f"{method}:{repeat}": quality_counts[(method, repeat)]
        for method in METHODS
        for repeat in expected_repeats
        if quality_counts[(method, repeat)] != expected_quality_units_per_method_repeat
    }
    checks.append(_check("raw_count_per_method_repeat", not raw_count_failures, {"failures": raw_count_failures}))
    checks.append(_check("quality_count_per_method_repeat", not quality_count_failures, {"failures": quality_count_failures}))

    duplicate_quality_units = _duplicate_quality_units(quality_rows)
    checks.append(
        _check(
            "no_duplicate_quality_units_per_method_repeat",
            not duplicate_quality_units,
            {"duplicates": duplicate_quality_units[:20], "duplicate_count": len(duplicate_quality_units)},
        )
    )

    pair_failures = _pair_key_failures(quality_rows)
    checks.append(_check("m2_m3_quality_unit_pairs_match_each_repeat", not pair_failures, {"failures": pair_failures}))
    return checks


def _repeat_method_metrics(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results = []
    for repeat in (0, 1, 2):
        for method in METHODS:
            raw_rows = [
                row
                for row in rows
                if row.get("method") == method and _repeat_index(row) == repeat
            ]
            quality_rows = [row for row in raw_rows if _is_quality_evaluation_row(row)]
            stsr_values = [_num(_metric_value(row, "stsr")) for row in quality_rows]
            stsr_clean = [value for value in stsr_values if value is not None]
            success_count = sum(value >= 0.5 for value in stsr_clean)
            result = {
                "repeat_index": repeat,
                "method": method,
                "method_label": METHOD_LABELS[method],
                "raw_row_count": len(raw_rows),
                "quality_row_count": len(quality_rows),
                "successful_quality_count": success_count,
                "stsr_rate": _rate(success_count, len(stsr_clean)),
                "evaluation_hcsr_mean": _mean(_metric_value(row, "evaluation_hcsr") for row in quality_rows),
                "itcsr_mean": _mean(_metric_value(row, "itcsr") for row in quality_rows),
                "bpcr_mean": _mean(_metric_value(row, "bpcr") for row in quality_rows),
                "agent_selection_f1_mean": _mean(_metric_value(row, "agent_selection_f1") for row in quality_rows),
                "tool_selection_f1_mean": _mean(_metric_value(row, "tool_selection_f1") for row in quality_rows),
                "raw_latency_ms_sum": _sum(_latency_value(row) for row in raw_rows),
                "raw_latency_ms_mean": _mean(_latency_value(row) for row in raw_rows),
            }
            for metric in (
                "total_tokens",
                "prompt_tokens",
                "completion_tokens",
                "estimated_cost",
                "standardized_estimated_cost",
                "actual_cost",
                "llm_call_count",
                "agent_call_count",
                "tool_call_count",
                "api_call_count",
            ):
                result[f"raw_{metric}_sum"] = _sum(_metric_value(row, metric) for row in raw_rows)
                result[f"raw_{metric}_mean"] = _mean(_metric_value(row, metric) for row in raw_rows)
            results.append(result)
    return results


def _repeat_pair_deltas(repeat_summaries: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for repeat in (0, 1, 2):
        summary = repeat_summaries[str(repeat)]
        stsr = _nested(summary, "paired_statistics", "metrics", "stsr") or {}
        mcnemar = stsr.get("mcnemar") if isinstance(stsr.get("mcnemar"), Mapping) else {}
        row = {
            "repeat_index": repeat,
            "pair_count": stsr.get("pair_count"),
            "m2_stsr": _nested(stsr, "m2", "mean"),
            "m3_stsr": _nested(stsr, "m3", "mean"),
            "stsr_delta": _nested(stsr, "delta", "mean"),
            "stsr_delta_ci_95": _nested(stsr, "delta", "bootstrap_ci_95"),
            "stsr_mcnemar_p_value": mcnemar.get("p_value"),
            "m3_only_success": mcnemar.get("m3_only_success"),
            "m2_only_success": mcnemar.get("m2_only_success"),
            "discordant_pairs": mcnemar.get("discordant_pairs"),
        }
        for metric in (
            "evaluation_hcsr",
            "bpcr",
            "agent_selection_f1",
            "tool_selection_f1",
            "total_tokens",
            "standardized_estimated_cost",
            "latency_ms",
            "agent_call_count",
            "tool_call_count",
        ):
            stat = _nested(summary, "paired_statistics", "metrics", metric) or {}
            row[f"{metric}_m2"] = _nested(stat, "m2", "mean")
            row[f"{metric}_m3"] = _nested(stat, "m3", "mean")
            row[f"{metric}_delta"] = _nested(stat, "delta", "mean")
            row[f"{metric}_delta_ci_95"] = _nested(stat, "delta", "bootstrap_ci_95")
            test = stat.get("wilcoxon_signed_rank") if isinstance(stat.get("wilcoxon_signed_rank"), Mapping) else None
            row[f"{metric}_p_value"] = test.get("p_value") if isinstance(test, Mapping) else None
        rows.append(row)
    return rows


def _aggregate_repeat_stats(
    *,
    repeat_method_metrics: Sequence[Mapping[str, Any]],
    repeat_pair_deltas: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    by_method: Dict[str, Dict[str, Any]] = {}
    for method in METHODS:
        rows = [row for row in repeat_method_metrics if row.get("method") == method]
        by_method[method] = {
            metric: _series_stats([row.get(metric) for row in rows])
            for metric in (
                "stsr_rate",
                "evaluation_hcsr_mean",
                "bpcr_mean",
                "raw_total_tokens_sum",
                "raw_standardized_estimated_cost_sum",
                "raw_latency_ms_mean",
                "raw_llm_call_count_sum",
                "raw_agent_call_count_sum",
                "raw_tool_call_count_sum",
            )
        }
    return {
        "by_method": by_method,
        "m3_vs_m2": {
            metric: _series_stats([row.get(metric) for row in repeat_pair_deltas])
            for metric in (
                "stsr_delta",
                "evaluation_hcsr_delta",
                "bpcr_delta",
                "total_tokens_delta",
                "standardized_estimated_cost_delta",
                "latency_ms_delta",
                "agent_call_count_delta",
                "tool_call_count_delta",
            )
        },
    }


def _combined_key_results(
    combined_summary: Mapping[str, Any],
    combined_stsr: Any,
) -> Dict[str, Any]:
    stsr = combined_stsr if isinstance(combined_stsr, Mapping) else {}
    mcnemar = stsr.get("mcnemar") if isinstance(stsr.get("mcnemar"), Mapping) else {}
    return {
        "result_count": combined_summary.get("result_count"),
        "quality_result_count": combined_summary.get("quality_result_count"),
        "unique_case_count": combined_summary.get("unique_case_count"),
        "method_case_count": combined_summary.get("method_case_count"),
        "stsr": {
            "pair_count": stsr.get("pair_count"),
            "m2_mean": _nested(stsr, "m2", "mean"),
            "m3_mean": _nested(stsr, "m3", "mean"),
            "delta_mean": _nested(stsr, "delta", "mean"),
            "delta_ci_95": _nested(stsr, "delta", "bootstrap_ci_95"),
            "mcnemar_p_value": mcnemar.get("p_value"),
            "m3_only_success": mcnemar.get("m3_only_success"),
            "m2_only_success": mcnemar.get("m2_only_success"),
            "discordant_pairs": mcnemar.get("discordant_pairs"),
        },
    }


def _paper_claim_guidance(
    *,
    status: str,
    combined_stsr: Any,
    repeat_pair_deltas: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    if status != "passed":
        return {
            "claim_level": "not_allowed",
            "suggested_wording": "分析门禁未通过，不能据此撰写稳定性结论。",
        }
    stsr = combined_stsr if isinstance(combined_stsr, Mapping) else {}
    delta = _num(_nested(stsr, "delta", "mean"))
    p_value = _num(_nested(stsr, "mcnemar", "p_value"))
    repeat_deltas = [
        _num(row.get("stsr_delta"))
        for row in repeat_pair_deltas
        if _num(row.get("stsr_delta")) is not None
    ]
    min_delta = min(repeat_deltas) if repeat_deltas else None
    if delta is not None and p_value is not None and delta > 0 and p_value < 0.05 and min_delta is not None and min_delta >= 0:
        return {
            "claim_level": "repeat_stability_supported",
            "suggested_wording": "在CTP100三次重复实验中，M3相对M2保持了正向STSR差值，说明主实验中的优势具有重复稳定性证据。",
            "caution": "该结论仍限于冻结CTP100数据集、冻结Prompt和同一模型配置。",
        }
    return {
        "claim_level": "cautious_or_mixed",
        "suggested_wording": "重复实验显示M3相对M2的效果存在波动，论文应报告逐次结果，而不能只强调单次主实验优势。",
        "caution": "应结合CTP30-v1/v2边界验证一起讨论。",
    }


def _source_artifacts(
    *,
    v6_run_dir: Path,
    stability_run_dir: Path,
    v6_results_path: Path,
    stability_results_path: Path,
) -> Dict[str, Any]:
    return {
        "formal_ctp100_v6_benchmark_results": _artifact_record(v6_results_path),
        "formal_ctp100_v6_evaluation_summary": _artifact_record(v6_run_dir / "evaluation_summary.json"),
        "formal_ctp100_v6_manifest": _artifact_record(v6_run_dir / "experiment_manifest.json"),
        "formal_ctp100_v6_gate": _artifact_record(v6_run_dir / "formal_experiment_gate.json"),
        "stability_benchmark_results": _artifact_record(stability_results_path),
        "stability_evaluation_summary": _artifact_record(stability_run_dir / "evaluation_summary.json"),
        "stability_manifest": _artifact_record(stability_run_dir / "experiment_manifest.json"),
        "stability_gate": _artifact_record(stability_run_dir / "ctp100_m2_m3_stability_report.json"),
    }


def _artifact_record(path: Path) -> Dict[str, Any]:
    return {
        "path": path.as_posix(),
        "exists": path.exists(),
        "sha256": _file_sha256(path) if path.exists() else None,
        "size_bytes": path.stat().st_size if path.exists() else None,
    }


def _row_counts(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    quality_rows = [row for row in rows if _is_quality_evaluation_row(row)]
    by_method_repeat: Dict[str, Dict[str, Dict[str, int]]] = {}
    for method in METHODS:
        by_method_repeat[method] = {}
        for repeat in (0, 1, 2):
            raw = [row for row in rows if row.get("method") == method and _repeat_index(row) == repeat]
            quality = [row for row in raw if _is_quality_evaluation_row(row)]
            by_method_repeat[method][str(repeat)] = {
                "raw": len(raw),
                "quality": len(quality),
            }
    return {
        "raw_total": len(rows),
        "quality_total": len(quality_rows),
        "by_method_repeat": by_method_repeat,
    }


def _combined_summary_shape_is_valid(
    summary: Mapping[str, Any],
    *,
    expected_quality_units_per_method_repeat: int,
    expected_raw_rows_per_method_repeat: int,
) -> bool:
    methods = summary.get("methods") if isinstance(summary.get("methods"), Mapping) else {}
    repeat_count = 3
    expected_raw_total = len(METHODS) * repeat_count * expected_raw_rows_per_method_repeat
    expected_quality_total = len(METHODS) * repeat_count * expected_quality_units_per_method_repeat
    expected_method_raw = repeat_count * expected_quality_units_per_method_repeat
    return (
        summary.get("result_count") == expected_raw_total
        and summary.get("quality_result_count") == expected_quality_total
        and summary.get("unique_case_count") == expected_quality_units_per_method_repeat
        and summary.get("method_case_count") == len(METHODS) * expected_quality_units_per_method_repeat
        and _nested(summary, "paired_statistics", "pair_count") == expected_quality_units_per_method_repeat
        and _nested(methods, M2_METHOD, "case_count") == expected_quality_units_per_method_repeat
        and _nested(methods, M3_METHOD, "case_count") == expected_quality_units_per_method_repeat
        and _nested(methods, M2_METHOD, "raw_run_count") == expected_method_raw
        and _nested(methods, M3_METHOD, "raw_run_count") == expected_method_raw
    )


def _duplicate_quality_units(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    counts = Counter(
        f"{row.get('method')}::{_repeat_index(row)}::{_evaluation_unit_id(row)}"
        for row in rows
    )
    return sorted(key for key, count in counts.items() if count > 1)


def _pair_key_failures(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    failures: Dict[str, Any] = {}
    for repeat in (0, 1, 2):
        m2_units = {
            _evaluation_unit_id(row)
            for row in rows
            if row.get("method") == M2_METHOD and _repeat_index(row) == repeat
        }
        m3_units = {
            _evaluation_unit_id(row)
            for row in rows
            if row.get("method") == M3_METHOD and _repeat_index(row) == repeat
        }
        if m2_units != m3_units:
            failures[str(repeat)] = {
                "missing_from_m2": sorted(m3_units - m2_units)[:20],
                "missing_from_m3": sorted(m2_units - m3_units)[:20],
            }
    return failures


def _is_scenario_row(row: Mapping[str, Any]) -> bool:
    return bool(row.get("scenario_id")) or _first_int(row.get("scenario_turn_count")) is not None


def _is_quality_evaluation_row(row: Mapping[str, Any]) -> bool:
    if not _is_scenario_row(row):
        return True
    if "target_turn" in row:
        return _bool(row.get("target_turn"))
    turn_index = _first_int(row.get("turn_index"))
    turn_count = _first_int(row.get("scenario_turn_count"))
    if turn_index is None or turn_count is None:
        return True
    return turn_index == turn_count - 1


def _evaluation_unit_id(row: Mapping[str, Any]) -> str:
    scenario_id = str(row.get("scenario_id") or "")
    if scenario_id:
        turn_id = str(row.get("turn_id") or row.get("turn_index") or "target")
        return f"{scenario_id}:{turn_id}"
    return str(row.get("case_id") or "")


def _status(row: Mapping[str, Any]) -> str:
    output = row.get("output") if isinstance(row.get("output"), Mapping) else {}
    return str(row.get("status") or output.get("execution_status") or "").lower()


def _repeat_index(row: Mapping[str, Any]) -> Optional[int]:
    return _first_int(row.get("repeat_index"))


def _metric_value(row: Mapping[str, Any], metric: str) -> Any:
    if metric == "latency_ms":
        return _latency_value(row)
    metrics = row.get("metrics") if isinstance(row.get("metrics"), Mapping) else {}
    if metric in metrics:
        return metrics.get(metric)
    trace = row.get("trace") if isinstance(row.get("trace"), Mapping) else {}
    if metric in trace:
        return trace.get(metric)
    run_audit_metrics = _nested(row, "run_audit", "metrics")
    if isinstance(run_audit_metrics, Mapping) and metric in run_audit_metrics:
        return run_audit_metrics.get(metric)
    return None


def _latency_value(row: Mapping[str, Any]) -> Any:
    return row.get("latency_ms") if row.get("latency_ms") is not None else row.get("latency")


def _load_json_list(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"benchmark_results.json does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"expected JSON list in {path}")
    return [dict(item) for item in payload if isinstance(item, Mapping)]


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _validate_output_dir(
    output_dir: Path,
    *,
    source_dirs: Sequence[Path],
    overwrite: bool,
) -> None:
    resolved_output = output_dir.resolve()
    for source in source_dirs:
        if resolved_output == source.resolve():
            raise ValueError("output_dir must not be the same as a source run directory")
    if not output_dir.exists():
        return
    target_names = {
        ANALYSIS_JSON_NAME,
        ANALYSIS_MD_NAME,
        COMBINED_SUMMARY_JSON_NAME,
        COMBINED_PAPER_TABLES_MD_NAME,
        REPEAT_METRICS_CSV_NAME,
        PAIR_DELTAS_CSV_NAME,
        MANIFEST_JSON_NAME,
    }
    existing = [name for name in target_names if (output_dir / name).exists()]
    if existing and not overwrite:
        raise FileExistsError(
            f"analysis artifacts already exist in {output_dir}; pass --overwrite to replace them"
        )


def _file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _combined_file_sha256(paths: Iterable[Path]) -> str:
    import hashlib

    digest = hashlib.sha256()
    for path in sorted(Path(item) for item in paths):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_file_sha256(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _check(check: str, passed: bool, details: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "check": check,
        "passed": bool(passed),
        "details": dict(details),
    }


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _first_int(*values: Any) -> Optional[int]:
    for value in values:
        if isinstance(value, bool) or value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n", ""}:
        return False
    return bool(value)


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _mean(values: Iterable[Any]) -> Optional[float]:
    clean = [_num(value) for value in values]
    numbers = [value for value in clean if value is not None]
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 4)


def _sum(values: Iterable[Any]) -> Optional[float]:
    clean = [_num(value) for value in values]
    numbers = [value for value in clean if value is not None]
    if not numbers:
        return None
    return round(sum(numbers), 4)


def _rate(numerator: int | float, denominator: int | float) -> Optional[float]:
    if not denominator:
        return None
    return round(float(numerator) / float(denominator), 4)


def _series_stats(values: Iterable[Any]) -> Dict[str, Any]:
    numbers = [_num(value) for value in values]
    clean = [float(value) for value in numbers if value is not None]
    if not clean:
        return {"n": 0, "mean": None, "sample_sd": None, "min": None, "max": None}
    mean = sum(clean) / len(clean)
    if len(clean) < 2:
        sample_sd = 0.0
    else:
        sample_sd = math.sqrt(sum((value - mean) ** 2 for value in clean) / (len(clean) - 1))
    return {
        "n": len(clean),
        "mean": round(mean, 4),
        "sample_sd": round(sample_sd, 4),
        "min": round(min(clean), 4),
        "max": round(max(clean), 4),
    }


def _fmt(value: Any) -> str:
    number = _num(value)
    if number is not None:
        return str(round(number, 4))
    if value is None:
        return ""
    return str(value)


def _fmt_range(value: Any) -> str:
    if not isinstance(value, list) or len(value) != 2:
        return ""
    return f"[{_fmt(value[0])}, {_fmt(value[1])}]"


def _json_dumps(value: Mapping[str, Any] | Sequence[Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
