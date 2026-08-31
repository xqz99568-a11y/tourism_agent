"""Final offline paper analysis across frozen Tourism Agent experiments.

This module only reads completed experiment artifacts.  It does not call an
LLM, does not access online APIs, and does not mutate source run directories.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


FINAL_PAPER_ANALYSIS_SCHEMA_VERSION = "tourism-agent-final-paper-analysis-v1"
FINAL_PAPER_ANALYSIS_JSON = "final_paper_offline_analysis.json"
FINAL_PAPER_ANALYSIS_MD = "final_paper_offline_analysis.md"
FINAL_PAPER_TABLES_MD = "final_paper_tables.md"
FINAL_PAPER_MANIFEST_JSON = "final_paper_analysis_manifest.json"
RUN_OVERVIEW_CSV = "run_overview.csv"
MAIN_METHOD_METRICS_CSV = "ctp100_main_method_metrics.csv"
STABILITY_REPEAT_METRICS_CSV = "ctp100_stability_repeat_metrics.csv"
ABLATION_PAIR_METRICS_CSV = "ctp100_m3_reuse_ablation_pair_metrics.csv"
SEALED_VALIDATION_METRICS_CSV = "sealed_validation_metrics.csv"
HOLM_SECONDARY_CSV = "holm_secondary_metrics.csv"

M0_METHOD = "llm_direct"
M1_METHOD = "single_agent"
M2_METHOD = "fixed_multi_agent"
M3_METHOD = "adaptive_multi_agent"
M3_NO_REUSE_METHOD = "adaptive_multi_agent_no_reuse"

METHOD_LABELS = {
    M0_METHOD: "M0 直接大模型",
    M1_METHOD: "M1 单Agent工具型",
    M2_METHOD: "M2 固定多Agent",
    M3_METHOD: "M3 自适应多Agent",
    M3_NO_REUSE_METHOD: "M3-no-reuse 消融",
}

_BOOTSTRAP_SAMPLES = 2000
_BOOTSTRAP_SEED = 20260725
_DEFAULT_METRICS = (
    "stsr",
    "evaluation_hcsr",
    "bpcr",
    "agent_selection_f1",
    "tool_selection_f1",
    "total_tokens",
    "standardized_estimated_cost",
    "latency_ms",
    "llm_call_count",
    "agent_call_count",
    "tool_call_count",
)


def write_final_paper_offline_analysis(
    *,
    output_dir: str | Path,
    ctp100_v6_run_dir: str | Path,
    ctp100_stability_run_dir: str | Path,
    ctp100_stability_analysis_dir: str | Path,
    m3_no_reuse_run_dir: str | Path,
    ctp30_v1_run_dir: str | Path,
    ctp30_v2_run_dir: str | Path,
    holm_secondary_dir: str | Path,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Build and write the final paper-facing offline analysis artifacts."""

    output = Path(output_dir)
    _validate_output_dir(output, overwrite=overwrite)
    analysis = build_final_paper_offline_analysis(
        ctp100_v6_run_dir=ctp100_v6_run_dir,
        ctp100_stability_run_dir=ctp100_stability_run_dir,
        ctp100_stability_analysis_dir=ctp100_stability_analysis_dir,
        m3_no_reuse_run_dir=m3_no_reuse_run_dir,
        ctp30_v1_run_dir=ctp30_v1_run_dir,
        ctp30_v2_run_dir=ctp30_v2_run_dir,
        holm_secondary_dir=holm_secondary_dir,
    )

    output.mkdir(parents=True, exist_ok=True)
    analysis_json = output / FINAL_PAPER_ANALYSIS_JSON
    analysis_md = output / FINAL_PAPER_ANALYSIS_MD
    tables_md = output / FINAL_PAPER_TABLES_MD
    manifest_json = output / FINAL_PAPER_MANIFEST_JSON
    run_overview_csv = output / RUN_OVERVIEW_CSV
    main_metrics_csv = output / MAIN_METHOD_METRICS_CSV
    stability_metrics_csv = output / STABILITY_REPEAT_METRICS_CSV
    ablation_metrics_csv = output / ABLATION_PAIR_METRICS_CSV
    sealed_metrics_csv = output / SEALED_VALIDATION_METRICS_CSV
    holm_csv = output / HOLM_SECONDARY_CSV

    _write_json(analysis_json, analysis)
    analysis_md.write_text(render_final_paper_offline_analysis(analysis), encoding="utf-8")
    tables_md.write_text(render_final_paper_tables(analysis), encoding="utf-8")
    _write_csv(run_overview_csv, analysis["run_overview"])
    _write_csv(main_metrics_csv, analysis["ctp100_main"]["method_metrics"])
    _write_csv(stability_metrics_csv, analysis["ctp100_stability"]["repeat_method_metrics"])
    _write_csv(ablation_metrics_csv, analysis["m3_reuse_ablation"]["metric_rows"])
    _write_csv(sealed_metrics_csv, analysis["sealed_validations"]["method_metrics"])
    _write_csv(holm_csv, analysis["holm_secondary"]["metrics"])

    manifest = _build_manifest(
        output_dir=output,
        analysis=analysis,
        artifact_paths=[
            analysis_json,
            analysis_md,
            tables_md,
            run_overview_csv,
            main_metrics_csv,
            stability_metrics_csv,
            ablation_metrics_csv,
            sealed_metrics_csv,
            holm_csv,
        ],
    )
    _write_json(manifest_json, manifest)
    return {
        "status": analysis["status"],
        "output_dir": output.as_posix(),
        "analysis_json": analysis_json.as_posix(),
        "analysis_md": analysis_md.as_posix(),
        "paper_tables": tables_md.as_posix(),
        "manifest": manifest_json.as_posix(),
        "failed_checks": analysis["failed_checks"],
    }


def build_final_paper_offline_analysis(
    *,
    ctp100_v6_run_dir: str | Path,
    ctp100_stability_run_dir: str | Path,
    ctp100_stability_analysis_dir: str | Path,
    m3_no_reuse_run_dir: str | Path,
    ctp30_v1_run_dir: str | Path,
    ctp30_v2_run_dir: str | Path,
    holm_secondary_dir: str | Path,
) -> Dict[str, Any]:
    """Build the final cross-run paper analysis payload."""

    paths = {
        "ctp100_v6": Path(ctp100_v6_run_dir),
        "ctp100_stability": Path(ctp100_stability_run_dir),
        "ctp100_stability_analysis": Path(ctp100_stability_analysis_dir),
        "m3_no_reuse": Path(m3_no_reuse_run_dir),
        "ctp30_v1": Path(ctp30_v1_run_dir),
        "ctp30_v2": Path(ctp30_v2_run_dir),
        "holm_secondary": Path(holm_secondary_dir),
    }
    inputs = _load_inputs(paths)
    validations = _validation_checks(paths, inputs)
    failed_checks = [item["check"] for item in validations if not item["passed"]]

    ctp100_main = _ctp100_main_section(inputs["ctp100_v6_summary"])
    stability = _ctp100_stability_section(inputs["stability_analysis"])
    ablation = _m3_reuse_ablation_section(
        ctp100_v6_rows=inputs["ctp100_v6_results"],
        stability_rows=inputs["ctp100_stability_results"],
        no_reuse_rows=inputs["m3_no_reuse_results"],
        no_reuse_summary=inputs["m3_no_reuse_summary"],
    )
    sealed = _sealed_validation_section(
        ctp30_v1_summary=inputs["ctp30_v1_summary"],
        ctp30_v2_summary=inputs["ctp30_v2_summary"],
    )
    holm = _holm_secondary_section(inputs["holm_secondary"])
    run_overview = _run_overview(paths, inputs)

    analysis = {
        "schema_version": FINAL_PAPER_ANALYSIS_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if not failed_checks else "failed",
        "failed_checks": failed_checks,
        "analysis_scope": {
            "analysis_type": "final_offline_paper_result_integration",
            "llm_calls_performed": 0,
            "online_api_calls_performed": 0,
            "source_run_directories_are_not_mutated": True,
            "paper_usage": "tables, claims guidance, and reproducibility evidence for Chinese journal manuscript",
        },
        "validation_checks": validations,
        "source_artifacts": _source_artifacts(paths),
        "run_overview": run_overview,
        "ctp100_main": ctp100_main,
        "ctp100_stability": stability,
        "m3_reuse_ablation": ablation,
        "sealed_validations": sealed,
        "holm_secondary": holm,
    }
    analysis["paper_claim_guidance"] = _paper_claim_guidance(analysis)
    return analysis


def render_final_paper_offline_analysis(analysis: Mapping[str, Any]) -> str:
    """Render a concise human-readable final analysis report."""

    claims = analysis.get("paper_claim_guidance") or {}
    lines = [
        "# Tourism Agent Final Offline Paper Analysis",
        "",
        f"- status: `{analysis.get('status')}`",
        f"- failed_checks: `{analysis.get('failed_checks') or []}`",
        "- analysis mode: offline only; no LLM/API calls.",
        "",
        "## Allowed paper claims",
        "",
    ]
    for item in claims.get("allowed_claims") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Required cautions", ""])
    for item in claims.get("required_cautions") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Next writing use", ""])
    for item in claims.get("paper_table_usage") or []:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def render_final_paper_tables(analysis: Mapping[str, Any]) -> str:
    """Render final paper-facing Markdown tables."""

    lines = [
        "# Final Paper Tables",
        "",
        "## Table 1. 实验数据与运行产物总览",
        "",
        "| 实验 | 角色 | 方法 | 原始结果数 | 质量评价数 | 状态 | 关键提交 |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for row in analysis.get("run_overview") or []:
        lines.append(
            "| {name} | {role} | {methods} | {raw} | {quality} | {status} | `{commit}` |".format(
                name=row.get("run_name"),
                role=row.get("paper_role"),
                methods=row.get("methods"),
                raw=_fmt(row.get("raw_result_count")),
                quality=_fmt(row.get("quality_result_count")),
                status=row.get("gate_status"),
                commit=str(row.get("git_commit") or "")[:8],
            )
        )

    lines.extend(
        [
            "",
            "## Table 2. CTP100主实验四方法结果",
            "",
            "| 方法 | STSR | HCSR | BPCR | Agent F1 | Tool F1 | Tokens/例 | 成本/例 | 时延ms |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in analysis.get("ctp100_main", {}).get("method_metrics") or []:
        lines.append(
            "| {method} | {stsr} | {hcsr} | {bpcr} | {af1} | {tf1} | {tokens} | {cost} | {latency} |".format(
                method=row.get("method_label"),
                stsr=_fmt(row.get("stsr_rate")),
                hcsr=_fmt(row.get("evaluation_hcsr_mean")),
                bpcr=_fmt(row.get("bpcr_mean")),
                af1=_fmt(row.get("agent_selection_f1_mean")),
                tf1=_fmt(row.get("tool_selection_f1_mean")),
                tokens=_fmt(row.get("total_tokens_mean")),
                cost=_fmt(row.get("standardized_estimated_cost_mean")),
                latency=_fmt(row.get("latency_ms_mean")),
            )
        )

    key = analysis.get("ctp100_stability", {}).get("combined_key_results", {}).get("stsr") or {}
    lines.extend(
        [
            "",
            "## Table 3. CTP100上M2/M3三次重复稳定性",
            "",
            "| 口径 | M2 STSR | M3 STSR | M3-M2 | 95% CI | McNemar p |",
            "|---|---:|---:|---:|---:|---:|",
            (
                f"| 三次重复合并 | {_fmt(key.get('m2_mean'))} | {_fmt(key.get('m3_mean'))} "
                f"| {_fmt(key.get('delta_mean'))} | {_fmt_range(key.get('delta_ci_95'))} "
                f"| {_fmt(key.get('mcnemar_p_value'))} |"
            ),
            "",
            "| Repeat | M2 STSR | M3 STSR | M3-M2 | McNemar p |",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    for row in analysis.get("ctp100_stability", {}).get("repeat_pair_deltas") or []:
        lines.append(
            f"| {row.get('repeat_index')} | {_fmt(row.get('m2_stsr'))} | {_fmt(row.get('m3_stsr'))} "
            f"| {_fmt(row.get('stsr_delta'))} | {_fmt(row.get('stsr_mcnemar_p_value'))} |"
        )

    lines.extend(
        [
            "",
            "## Table 4. M3结果复用消融：M3-full vs M3-no-reuse",
            "",
            "| 指标 | 配对数 | M3-full | M3-no-reuse | full-no-reuse | 95% CI | 检验p值 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in analysis.get("m3_reuse_ablation", {}).get("metric_rows") or []:
        lines.append(
            "| {metric} | {pairs} | {full} | {nr} | {delta} | {ci} | {p} |".format(
                metric=row.get("label"),
                pairs=_fmt(row.get("pair_count")),
                full=_fmt(row.get("m3_full_mean")),
                nr=_fmt(row.get("m3_no_reuse_mean")),
                delta=_fmt(row.get("delta_full_minus_no_reuse_mean")),
                ci=_fmt_range(row.get("delta_ci_95")),
                p=_fmt(row.get("p_value")),
            )
        )

    lines.extend(
        [
            "",
            "## Table 5. CTP30封闭验证与边界分析",
            "",
            "| 数据集 | 方法 | STSR | HCSR | Agent F1 | Tool F1 | Tokens/例 | 成本/例 | 时延ms |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in analysis.get("sealed_validations", {}).get("method_metrics") or []:
        lines.append(
            "| {dataset} | {method} | {stsr} | {hcsr} | {af1} | {tf1} | {tokens} | {cost} | {latency} |".format(
                dataset=row.get("dataset"),
                method=row.get("method_label"),
                stsr=_fmt(row.get("stsr_rate")),
                hcsr=_fmt(row.get("evaluation_hcsr_mean")),
                af1=_fmt(row.get("agent_selection_f1_mean")),
                tf1=_fmt(row.get("tool_selection_f1_mean")),
                tokens=_fmt(row.get("total_tokens_mean")),
                cost=_fmt(row.get("standardized_estimated_cost_mean")),
                latency=_fmt(row.get("latency_ms_mean")),
            )
        )

    lines.extend(
        [
            "",
            "## Table 6. CTP100主实验二级指标Holm校正",
            "",
            "| 指标 | 原始p值 | Holm校正p值 | 校正后显著 |",
            "|---|---:|---:|---|",
        ]
    )
    for row in analysis.get("holm_secondary", {}).get("metrics") or []:
        lines.append(
            f"| {row.get('label') or row.get('metric')} | {_fmt(row.get('raw_p_value'))} "
            f"| {_fmt(row.get('holm_adjusted_p_value'))} | `{row.get('significant_after_correction')}` |"
        )
    return "\n".join(lines) + "\n"


def _load_inputs(paths: Mapping[str, Path]) -> Dict[str, Any]:
    return {
        "ctp100_v6_results": _read_json_list(paths["ctp100_v6"] / "benchmark_results.json"),
        "ctp100_v6_summary": _read_json_object(paths["ctp100_v6"] / "evaluation_summary.json"),
        "ctp100_v6_manifest": _read_json_object(paths["ctp100_v6"] / "experiment_manifest.json"),
        "ctp100_v6_gate": _read_json_object(paths["ctp100_v6"] / "formal_experiment_gate.json"),
        "ctp100_stability_results": _read_json_list(paths["ctp100_stability"] / "benchmark_results.json"),
        "ctp100_stability_manifest": _read_json_object(paths["ctp100_stability"] / "experiment_manifest.json"),
        "ctp100_stability_gate": _read_json_object(paths["ctp100_stability"] / "ctp100_m2_m3_stability_report.json"),
        "stability_analysis": _read_json_object(paths["ctp100_stability_analysis"] / "ctp100_m2_m3_stability_combined_analysis.json"),
        "m3_no_reuse_results": _read_json_list(paths["m3_no_reuse"] / "benchmark_results.json"),
        "m3_no_reuse_summary": _read_json_object(paths["m3_no_reuse"] / "evaluation_summary.json"),
        "m3_no_reuse_manifest": _read_json_object(paths["m3_no_reuse"] / "experiment_manifest.json"),
        "m3_no_reuse_gate": _read_json_object(paths["m3_no_reuse"] / "ctp100_m3_no_reuse_ablation_report.json"),
        "ctp30_v1_summary": _read_json_object(paths["ctp30_v1"] / "evaluation_summary.json"),
        "ctp30_v1_manifest": _read_json_object(paths["ctp30_v1"] / "sealed_validation_manifest.json"),
        "ctp30_v1_gate": _read_json_object(paths["ctp30_v1"] / "sealed_validation_gate.json"),
        "ctp30_v2_summary": _read_json_object(paths["ctp30_v2"] / "evaluation_summary.json"),
        "ctp30_v2_manifest": _read_json_object(paths["ctp30_v2"] / "multiturn_sealed_validation_manifest.json"),
        "ctp30_v2_gate": _read_json_object(paths["ctp30_v2"] / "multiturn_sealed_validation_gate.json"),
        "holm_secondary": _read_json_object(paths["holm_secondary"] / "holm_secondary_results.json"),
    }


def _validation_checks(paths: Mapping[str, Path], inputs: Mapping[str, Any]) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    for key, path in paths.items():
        checks.append(_check(f"{key}_dir_exists", path.exists(), {"path": path.as_posix()}))
    expected_status = {
        "ctp100_v6_gate": "passed",
        "ctp100_stability_gate": "passed",
        "stability_analysis": "passed",
        "m3_no_reuse_gate": "passed",
        "ctp30_v1_gate": "passed",
        "ctp30_v2_gate": "passed",
        "holm_secondary": "passed",
    }
    for key, status in expected_status.items():
        checks.append(
            _check(
                f"{key}_status_passed",
                (inputs.get(key) or {}).get("status") == status,
                {"actual": (inputs.get(key) or {}).get("status"), "expected": status},
            )
        )
    expected_counts = {
        "ctp100_v6_results": 520,
        "ctp100_stability_results": 520,
        "m3_no_reuse_results": 180,
    }
    for key, expected in expected_counts.items():
        checks.append(
            _check(
                f"{key}_row_count",
                len(inputs.get(key) or []) == expected,
                {"actual": len(inputs.get(key) or []), "expected": expected},
            )
        )
    summary_expectations = {
        "ctp100_v6_summary": (520, 400),
        "m3_no_reuse_summary": (180, 90),
        "ctp30_v1_summary": (60, 60),
        "ctp30_v2_summary": (120, 60),
    }
    for key, (raw, quality) in summary_expectations.items():
        summary = inputs.get(key) or {}
        checks.append(
            _check(
                f"{key}_shape",
                summary.get("result_count") == raw and summary.get("quality_result_count") == quality,
                {
                    "actual_result_count": summary.get("result_count"),
                    "expected_result_count": raw,
                    "actual_quality_result_count": summary.get("quality_result_count"),
                    "expected_quality_result_count": quality,
                },
            )
        )
    checks.append(
        _check(
            "m3_no_reuse_audit_clean",
            _nested(inputs, "m3_no_reuse_gate", "no_reuse_audit", "reused_agent_violation_count") == 0
            and _nested(inputs, "m3_no_reuse_gate", "no_reuse_audit", "reused_tool_result_violation_count") == 0,
            {
                "reused_agent_violation_count": _nested(inputs, "m3_no_reuse_gate", "no_reuse_audit", "reused_agent_violation_count"),
                "reused_tool_result_violation_count": _nested(inputs, "m3_no_reuse_gate", "no_reuse_audit", "reused_tool_result_violation_count"),
            },
        )
    )
    return checks


def _ctp100_main_section(summary: Mapping[str, Any]) -> Dict[str, Any]:
    methods = summary.get("methods") if isinstance(summary.get("methods"), Mapping) else {}
    return {
        "role": "main_four_method_benchmark",
        "result_count": summary.get("result_count"),
        "quality_result_count": summary.get("quality_result_count"),
        "method_metrics": [
            _method_metric_row("CTP100主实验", method, methods.get(method) or {})
            for method in (M0_METHOD, M1_METHOD, M2_METHOD, M3_METHOD)
        ],
        "paired_m3_vs_m2_stsr": _stsr_pair_row(
            _nested(summary, "paired_statistics", "metrics", "stsr") or {}
        ),
    }


def _ctp100_stability_section(stability_analysis: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "role": "repeat_stability_analysis_for_m2_m3",
        "status": stability_analysis.get("status"),
        "combined_key_results": stability_analysis.get("combined_key_results"),
        "aggregate_repeat_stats": stability_analysis.get("aggregate_repeat_stats"),
        "repeat_method_metrics": list(stability_analysis.get("repeat_method_metrics") or []),
        "repeat_pair_deltas": list(stability_analysis.get("repeat_pair_deltas") or []),
        "paper_claim_guidance": stability_analysis.get("paper_claim_guidance"),
    }


def _m3_reuse_ablation_section(
    *,
    ctp100_v6_rows: Sequence[Mapping[str, Any]],
    stability_rows: Sequence[Mapping[str, Any]],
    no_reuse_rows: Sequence[Mapping[str, Any]],
    no_reuse_summary: Mapping[str, Any],
) -> Dict[str, Any]:
    full_rows = _select_full_m3_two_turn_target_rows(ctp100_v6_rows, stability_rows, no_reuse_rows)
    no_reuse_quality_rows = [
        dict(row)
        for row in no_reuse_rows
        if row.get("method") == M3_NO_REUSE_METHOD and _is_quality_row(row)
    ]
    pairs = _paired_by_key(
        full_rows,
        no_reuse_quality_rows,
        left_name="m3_full",
        right_name="m3_no_reuse",
    )
    metric_rows = [
        _paired_metric_row(label, metric, pairs, binary=(metric == "stsr"))
        for metric, label in (
            ("stsr", "STSR"),
            ("evaluation_hcsr", "HCSR"),
            ("bpcr", "BPCR"),
            ("agent_selection_f1", "Agent F1"),
            ("tool_selection_f1", "Tool F1"),
            ("total_tokens", "Tokens"),
            ("standardized_estimated_cost", "标准化成本"),
            ("latency_ms", "时延ms"),
            ("llm_call_count", "LLM调用数"),
            ("agent_call_count", "Agent调用数"),
            ("tool_call_count", "Tool调用数"),
        )
    ]
    return {
        "role": "result_reuse_ablation_on_ctp100_two_turn_scenarios",
        "comparison": "M3-full minus M3-no-reuse",
        "selection_policy": "all 30 CTP100 scenarios with exactly two turns; target turn only; repeats 0/1/2",
        "pair_count": len(pairs),
        "full_m3_target_row_count": len(full_rows),
        "m3_no_reuse_target_row_count": len(no_reuse_quality_rows),
        "paired_key_missing": _missing_pair_keys(full_rows, no_reuse_quality_rows),
        "m3_no_reuse_summary": {
            "result_count": no_reuse_summary.get("result_count"),
            "quality_result_count": no_reuse_summary.get("quality_result_count"),
            "method_summary": _nested(no_reuse_summary, "methods", M3_NO_REUSE_METHOD),
        },
        "metric_rows": metric_rows,
        "interpretation": _ablation_interpretation(metric_rows),
    }


def _sealed_validation_section(
    *,
    ctp30_v1_summary: Mapping[str, Any],
    ctp30_v2_summary: Mapping[str, Any],
) -> Dict[str, Any]:
    rows = []
    for dataset, summary, role in (
        ("CTP30-v1", ctp30_v1_summary, "boundary_case_sealed_validation"),
        ("CTP30-v2", ctp30_v2_summary, "sealed_real_multiturn_validation"),
    ):
        methods = summary.get("methods") if isinstance(summary.get("methods"), Mapping) else {}
        for method in (M2_METHOD, M3_METHOD):
            rows.append(_method_metric_row(dataset, method, methods.get(method) or {}, role=role))
    return {
        "role": "sealed_validation_and_boundary_analysis",
        "method_metrics": rows,
        "ctp30_v1_paired_stsr": _stsr_pair_row(
            _nested(ctp30_v1_summary, "paired_statistics", "metrics", "stsr") or {}
        ),
        "ctp30_v2_paired_stsr": _stsr_pair_row(
            _nested(ctp30_v2_summary, "paired_statistics", "metrics", "stsr") or {}
        ),
    }


def _holm_secondary_section(holm: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "role": "holm_bonferroni_secondary_statistics_for_ctp100_main",
        "status": holm.get("status"),
        "primary_stsr_reference": holm.get("primary_stsr_reference"),
        "metrics": list(holm.get("metrics") or []),
    }


def _run_overview(paths: Mapping[str, Path], inputs: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [
        _overview_row(
            "CTP100主实验v6",
            "四方法主实验",
            paths["ctp100_v6"],
            inputs["ctp100_v6_summary"],
            inputs["ctp100_v6_manifest"],
            inputs["ctp100_v6_gate"],
            "M0/M1/M2/M3",
        ),
        _overview_row(
            "CTP100 M2/M3稳定性复跑",
            "重复稳定性",
            paths["ctp100_stability"],
            {"result_count": 520, "quality_result_count": 400},
            inputs["ctp100_stability_manifest"],
            inputs["ctp100_stability_gate"],
            "M2/M3",
        ),
        _overview_row(
            "M3-no-reuse消融",
            "结果复用消融",
            paths["m3_no_reuse"],
            inputs["m3_no_reuse_summary"],
            inputs["m3_no_reuse_manifest"],
            inputs["m3_no_reuse_gate"],
            "M3-no-reuse",
        ),
        _overview_row(
            "CTP30-v1",
            "封闭边界分析",
            paths["ctp30_v1"],
            inputs["ctp30_v1_summary"],
            inputs["ctp30_v1_manifest"],
            inputs["ctp30_v1_gate"],
            "M2/M3",
        ),
        _overview_row(
            "CTP30-v2",
            "封闭真实多轮验证",
            paths["ctp30_v2"],
            inputs["ctp30_v2_summary"],
            inputs["ctp30_v2_manifest"],
            inputs["ctp30_v2_gate"],
            "M2/M3",
        ),
    ]


def _overview_row(
    run_name: str,
    paper_role: str,
    path: Path,
    summary: Mapping[str, Any],
    manifest: Mapping[str, Any],
    gate: Mapping[str, Any],
    methods: str,
) -> Dict[str, Any]:
    return {
        "run_name": run_name,
        "paper_role": paper_role,
        "path": path.as_posix(),
        "methods": methods,
        "raw_result_count": summary.get("result_count"),
        "quality_result_count": summary.get("quality_result_count"),
        "gate_status": gate.get("status"),
        "failed_checks": json.dumps(gate.get("failed_checks") or [], ensure_ascii=False),
        "git_commit": manifest.get("git_commit"),
        "working_tree_clean": manifest.get("working_tree_clean"),
    }


def _method_metric_row(
    dataset: str,
    method: str,
    row: Mapping[str, Any],
    *,
    role: str = "",
) -> Dict[str, Any]:
    return {
        "dataset": dataset,
        "role": role,
        "method": method,
        "method_label": METHOD_LABELS.get(method, method),
        "case_count": row.get("case_count"),
        "raw_run_count": row.get("raw_run_count"),
        "stsr_rate": row.get("stsr_rate"),
        "evaluation_hcsr_mean": row.get("evaluation_hcsr_mean"),
        "itcsr_mean": row.get("itcsr_mean"),
        "bpcr_mean": row.get("bpcr_mean"),
        "agent_selection_f1_mean": row.get("agent_selection_f1_mean"),
        "tool_selection_f1_mean": row.get("tool_selection_f1_mean"),
        "total_tokens_mean": row.get("total_tokens_mean"),
        "standardized_estimated_cost_mean": row.get("standardized_estimated_cost_mean"),
        "latency_ms_mean": row.get("latency_ms_mean"),
        "llm_call_count_mean": row.get("llm_call_count_mean"),
        "agent_call_count_mean": row.get("agent_call_count_mean"),
        "tool_call_count_mean": row.get("tool_call_count_mean"),
        "successful_case_count": row.get("successful_case_count"),
    }


def _stsr_pair_row(stsr: Mapping[str, Any]) -> Dict[str, Any]:
    mcnemar = stsr.get("mcnemar") if isinstance(stsr.get("mcnemar"), Mapping) else {}
    return {
        "pair_count": stsr.get("pair_count"),
        "m2_mean": _nested(stsr, "m2", "mean"),
        "m3_mean": _nested(stsr, "m3", "mean"),
        "delta_mean": _nested(stsr, "delta", "mean"),
        "delta_ci_95": _nested(stsr, "delta", "bootstrap_ci_95"),
        "mcnemar_p_value": mcnemar.get("p_value"),
        "m3_only_success": mcnemar.get("m3_only_success"),
        "m2_only_success": mcnemar.get("m2_only_success"),
    }


def _select_full_m3_two_turn_target_rows(
    v6_rows: Sequence[Mapping[str, Any]],
    stability_rows: Sequence[Mapping[str, Any]],
    no_reuse_rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    no_reuse_target_scenarios = {
        str(row.get("scenario_id") or "")
        for row in no_reuse_rows
        if row.get("method") == M3_NO_REUSE_METHOD and _is_quality_row(row)
    }
    source_rows = list(v6_rows) + list(stability_rows)
    selected = []
    for row in source_rows:
        if row.get("method") != M3_METHOD:
            continue
        if _repeat_index(row) not in {0, 1, 2}:
            continue
        if str(row.get("scenario_id") or "") not in no_reuse_target_scenarios:
            continue
        if not _is_quality_row(row):
            continue
        selected.append(dict(row))
    return selected


def _paired_by_key(
    left_rows: Sequence[Mapping[str, Any]],
    right_rows: Sequence[Mapping[str, Any]],
    *,
    left_name: str,
    right_name: str,
) -> List[Dict[str, Any]]:
    left = {_pair_key(row): row for row in left_rows}
    right = {_pair_key(row): row for row in right_rows}
    pairs = []
    for key in sorted(set(left) & set(right)):
        pairs.append({"key": key, left_name: left[key], right_name: right[key]})
    return pairs


def _missing_pair_keys(
    left_rows: Sequence[Mapping[str, Any]],
    right_rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    left = {_pair_key(row) for row in left_rows}
    right = {_pair_key(row) for row in right_rows}
    return {
        "missing_from_m3_full": sorted(right - left)[:20],
        "missing_from_m3_no_reuse": sorted(left - right)[:20],
        "missing_from_m3_full_count": len(right - left),
        "missing_from_m3_no_reuse_count": len(left - right),
    }


def _paired_metric_row(
    label: str,
    metric: str,
    pairs: Sequence[Mapping[str, Any]],
    *,
    binary: bool,
) -> Dict[str, Any]:
    full_values: List[float] = []
    no_reuse_values: List[float] = []
    deltas: List[float] = []
    for pair in pairs:
        full_value = _metric_value(pair["m3_full"], metric)
        no_reuse_value = _metric_value(pair["m3_no_reuse"], metric)
        if full_value is None or no_reuse_value is None:
            continue
        full_values.append(full_value)
        no_reuse_values.append(no_reuse_value)
        deltas.append(full_value - no_reuse_value)
    p_value = None
    test_name = None
    binary_counts = None
    if binary:
        binary_counts = _binary_pair_counts(full_values, no_reuse_values)
        p_value = _mcnemar_exact_p_value(
            binary_counts["full_only_success"],
            binary_counts["no_reuse_only_success"],
        )
        test_name = "exact_binomial_mcnemar"
    return {
        "metric": metric,
        "label": label,
        "pair_count": len(deltas),
        "m3_full_mean": _mean(full_values),
        "m3_no_reuse_mean": _mean(no_reuse_values),
        "delta_full_minus_no_reuse_mean": _mean(deltas),
        "delta_median": _median(deltas),
        "delta_ci_95": _bootstrap_ci(deltas, seed=_BOOTSTRAP_SEED),
        "test": test_name,
        "p_value": p_value,
        "binary_pair_counts": binary_counts,
    }


def _binary_pair_counts(full_values: Sequence[float], no_reuse_values: Sequence[float]) -> Dict[str, int]:
    full_only = 0
    no_reuse_only = 0
    both_success = 0
    both_failure = 0
    for full, no_reuse in zip(full_values, no_reuse_values):
        full_success = full >= 0.5
        no_reuse_success = no_reuse >= 0.5
        if full_success and no_reuse_success:
            both_success += 1
        elif full_success and not no_reuse_success:
            full_only += 1
        elif no_reuse_success and not full_success:
            no_reuse_only += 1
        else:
            both_failure += 1
    return {
        "both_success": both_success,
        "both_failure": both_failure,
        "full_only_success": full_only,
        "no_reuse_only_success": no_reuse_only,
        "discordant_pairs": full_only + no_reuse_only,
    }


def _mcnemar_exact_p_value(full_only_success: int, no_reuse_only_success: int) -> float:
    discordant = full_only_success + no_reuse_only_success
    if discordant == 0:
        return 1.0
    k = min(full_only_success, no_reuse_only_success)
    tail = sum(math.comb(discordant, i) for i in range(k + 1)) / (2 ** discordant)
    return round(min(1.0, 2 * tail), 6)


def _ablation_interpretation(metric_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    by_metric = {row.get("metric"): row for row in metric_rows}
    stsr_delta = _num((by_metric.get("stsr") or {}).get("delta_full_minus_no_reuse_mean"))
    token_delta = _num((by_metric.get("total_tokens") or {}).get("delta_full_minus_no_reuse_mean"))
    cost_delta = _num((by_metric.get("standardized_estimated_cost") or {}).get("delta_full_minus_no_reuse_mean"))
    latency_delta = _num((by_metric.get("latency_ms") or {}).get("delta_full_minus_no_reuse_mean"))
    return {
        "stsr_delta_full_minus_no_reuse": stsr_delta,
        "token_delta_full_minus_no_reuse": token_delta,
        "cost_delta_full_minus_no_reuse": cost_delta,
        "latency_delta_full_minus_no_reuse": latency_delta,
        "summary": _ablation_summary_sentence(
            stsr_delta=stsr_delta,
            token_delta=token_delta,
            cost_delta=cost_delta,
            latency_delta=latency_delta,
        ),
    }


def _ablation_summary_sentence(
    *,
    stsr_delta: Optional[float],
    token_delta: Optional[float],
    cost_delta: Optional[float],
    latency_delta: Optional[float],
) -> str:
    quality = "质量差异需要结合表格报告"
    if stsr_delta is not None:
        if abs(stsr_delta) < 0.01:
            quality = "在目标轮STSR上二者基本持平"
        elif stsr_delta > 0:
            quality = "M3-full在目标轮STSR上高于M3-no-reuse"
        else:
            quality = "M3-no-reuse在目标轮STSR上高于M3-full"
    resource = "资源差异需要结合表格报告"
    resource_deltas = [value for value in (token_delta, cost_delta, latency_delta) if value is not None]
    if resource_deltas:
        if all(value < 0 for value in resource_deltas):
            resource = "M3-full资源开销低于M3-no-reuse"
        elif all(value > 0 for value in resource_deltas):
            resource = "M3-full资源开销高于M3-no-reuse"
        else:
            resource = "资源指标呈现混合差异"
    return f"{quality}；{resource}。"


def _paper_claim_guidance(analysis: Mapping[str, Any]) -> Dict[str, Any]:
    stability_stsr = _nested(analysis, "ctp100_stability", "combined_key_results", "stsr") or {}
    ablation_interp = _nested(analysis, "m3_reuse_ablation", "interpretation") or {}
    ctp30_v2 = _nested(analysis, "sealed_validations", "ctp30_v2_paired_stsr") or {}
    allowed = [
        "CTP100主实验可作为四方法主结果；M3相对M2在STSR上有正向提升。",
        (
            "CTP100三次重复稳定性分析可用于支撑M3相对M2的稳定优势："
            f"平均差值为{_fmt(stability_stsr.get('delta_mean'))}，"
            f"McNemar p={_fmt(stability_stsr.get('mcnemar_p_value'))}。"
        ),
        f"M3-no-reuse消融可用于分析结果复用机制：{ablation_interp.get('summary')}",
        (
            "CTP30-v1/v2应作为封闭验证和边界分析使用；"
            f"CTP30-v2中M3-M2 STSR差值为{_fmt(ctp30_v2.get('delta_mean'))}。"
        ),
    ]
    cautions = [
        "不能声称CTP30-v2中M3显著优于M2；该验证显示严格封闭多轮下优势不明显。",
        "M3-no-reuse是补充消融，不是主实验第五种正式方法；正文应单独放在消融实验小节。",
        "成本为标准化估算成本，不能等同于中转API真实账单。",
        "天气和城际交通数据是冻结快照，不应写成实时在线数据。",
    ]
    usage = [
        "Table 1用于实验设置和可追溯性说明。",
        "Table 2用于主实验结果。",
        "Table 3用于稳定性实验结果。",
        "Table 4用于消融实验。",
        "Table 5用于封闭验证和局限性讨论。",
        "Table 6用于二级指标多重比较校正。",
    ]
    return {
        "allowed_claims": allowed,
        "required_cautions": cautions,
        "paper_table_usage": usage,
    }


def _source_artifacts(paths: Mapping[str, Path]) -> Dict[str, Any]:
    artifacts = {}
    source_files = {
        "ctp100_v6_results": paths["ctp100_v6"] / "benchmark_results.json",
        "ctp100_v6_summary": paths["ctp100_v6"] / "evaluation_summary.json",
        "ctp100_v6_manifest": paths["ctp100_v6"] / "experiment_manifest.json",
        "ctp100_v6_gate": paths["ctp100_v6"] / "formal_experiment_gate.json",
        "ctp100_stability_results": paths["ctp100_stability"] / "benchmark_results.json",
        "ctp100_stability_analysis": paths["ctp100_stability_analysis"] / "ctp100_m2_m3_stability_combined_analysis.json",
        "m3_no_reuse_results": paths["m3_no_reuse"] / "benchmark_results.json",
        "m3_no_reuse_report": paths["m3_no_reuse"] / "ctp100_m3_no_reuse_ablation_report.json",
        "ctp30_v1_summary": paths["ctp30_v1"] / "evaluation_summary.json",
        "ctp30_v1_gate": paths["ctp30_v1"] / "sealed_validation_gate.json",
        "ctp30_v2_summary": paths["ctp30_v2"] / "evaluation_summary.json",
        "ctp30_v2_gate": paths["ctp30_v2"] / "multiturn_sealed_validation_gate.json",
        "holm_secondary": paths["holm_secondary"] / "holm_secondary_results.json",
    }
    for key, path in source_files.items():
        artifacts[key] = _artifact_record(path)
    return artifacts


def _build_manifest(
    *,
    output_dir: Path,
    analysis: Mapping[str, Any],
    artifact_paths: Sequence[Path],
) -> Dict[str, Any]:
    return {
        "schema_version": "tourism-agent-final-paper-analysis-manifest-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": analysis.get("status"),
        "output_dir": output_dir.as_posix(),
        "source_artifacts": analysis.get("source_artifacts"),
        "artifact_hashes": {
            path.name: _file_sha256(path)
            for path in artifact_paths
        },
        "files_combined_sha256": _combined_file_sha256(artifact_paths),
    }


def _artifact_record(path: Path) -> Dict[str, Any]:
    return {
        "path": path.as_posix(),
        "exists": path.exists(),
        "sha256": _file_sha256(path) if path.exists() else None,
        "size_bytes": path.stat().st_size if path.exists() else None,
    }


def _read_json_object(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _read_json_list(path: Path) -> List[Dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"expected JSON list: {path}")
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _validate_output_dir(output_dir: Path, *, overwrite: bool) -> None:
    if not output_dir.exists():
        return
    target_files = {
        FINAL_PAPER_ANALYSIS_JSON,
        FINAL_PAPER_ANALYSIS_MD,
        FINAL_PAPER_TABLES_MD,
        FINAL_PAPER_MANIFEST_JSON,
        RUN_OVERVIEW_CSV,
        MAIN_METHOD_METRICS_CSV,
        STABILITY_REPEAT_METRICS_CSV,
        ABLATION_PAIR_METRICS_CSV,
        SEALED_VALIDATION_METRICS_CSV,
        HOLM_SECONDARY_CSV,
    }
    existing = [name for name in target_files if (output_dir / name).exists()]
    if existing and not overwrite:
        raise FileExistsError(
            f"final paper analysis artifacts already exist in {output_dir}; pass --overwrite to replace them"
        )


def _check(check: str, passed: bool, details: Mapping[str, Any]) -> Dict[str, Any]:
    return {"check": check, "passed": bool(passed), "details": dict(details)}


def _is_quality_row(row: Mapping[str, Any]) -> bool:
    if not row.get("scenario_id"):
        return True
    if "target_turn" in row:
        return _bool(row.get("target_turn"))
    turn_index = _first_int(row.get("turn_index"))
    turn_count = _first_int(row.get("scenario_turn_count"))
    if turn_index is None or turn_count is None:
        return str(row.get("turn_id") or "").lower() in {"t2", "2", "target"}
    return turn_index == turn_count - 1


def _pair_key(row: Mapping[str, Any]) -> str:
    return "::".join(
        [
            str(row.get("scenario_id") or row.get("case_id") or ""),
            str(row.get("turn_id") or row.get("turn_index") or "target"),
            str(_repeat_index(row)),
        ]
    )


def _repeat_index(row: Mapping[str, Any]) -> Optional[int]:
    return _first_int(row.get("repeat_index"))


def _metric_value(row: Mapping[str, Any], metric: str) -> Optional[float]:
    if metric == "latency_ms":
        return _num(row.get("latency_ms") if row.get("latency_ms") is not None else row.get("latency"))
    metrics = row.get("metrics") if isinstance(row.get("metrics"), Mapping) else {}
    if metric in metrics:
        return _num(metrics.get(metric))
    trace = row.get("trace") if isinstance(row.get("trace"), Mapping) else {}
    if metric == "agent_call_count":
        return _num(trace.get("agent_call_count"))
    if metric == "tool_call_count":
        return _num(trace.get("tool_call_count"))
    if metric in trace:
        return _num(trace.get(metric))
    return None


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _first_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
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
    numbers = [_num(value) for value in values]
    clean = [value for value in numbers if value is not None]
    if not clean:
        return None
    return round(sum(clean) / len(clean), 4)


def _median(values: Iterable[Any]) -> Optional[float]:
    numbers = sorted(value for value in (_num(item) for item in values) if value is not None)
    if not numbers:
        return None
    mid = len(numbers) // 2
    if len(numbers) % 2:
        return round(numbers[mid], 4)
    return round((numbers[mid - 1] + numbers[mid]) / 2, 4)


def _bootstrap_ci(values: Sequence[float], *, seed: int) -> Optional[List[float]]:
    clean = [float(value) for value in values if _num(value) is not None]
    if not clean:
        return None
    if len(clean) == 1:
        value = round(clean[0], 4)
        return [value, value]
    rng = random.Random(seed)
    means = []
    size = len(clean)
    for _ in range(_BOOTSTRAP_SAMPLES):
        sample = [clean[rng.randrange(size)] for _ in range(size)]
        means.append(sum(sample) / size)
    means.sort()
    lower = means[int(0.025 * (_BOOTSTRAP_SAMPLES - 1))]
    upper = means[int(0.975 * (_BOOTSTRAP_SAMPLES - 1))]
    return [round(lower, 4), round(upper, 4)]


def _fmt(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "" if value is None else str(value)
    return str(round(number, 4))


def _fmt_range(value: Any) -> str:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 2:
        return ""
    return f"[{_fmt(value[0])}, {_fmt(value[1])}]"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _combined_file_sha256(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_file_sha256(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


__all__ = [
    "FINAL_PAPER_ANALYSIS_SCHEMA_VERSION",
    "build_final_paper_offline_analysis",
    "render_final_paper_offline_analysis",
    "render_final_paper_tables",
    "write_final_paper_offline_analysis",
]
