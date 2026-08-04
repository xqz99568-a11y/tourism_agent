"""Paper result pack exporter for completed experiment runs.

The paper analysis artifact answers whether a run is usable and summarizes the
numbers.  This module reshapes that evidence into copy-ready paper material:
RQ-oriented tables, cautious result statements, claim boundaries, and artifact
references.  It never runs an experiment, calls an LLM, or re-scores outputs.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.core.experiment_paper_analysis import (
    PAPER_ANALYSIS_JSON_NAME,
    build_experiment_paper_analysis,
)


PAPER_RESULT_PACK_SCHEMA_VERSION = "ctp-paper-result-pack-v1"
PAPER_RESULT_PACK_JSON_NAME = "paper_result_pack.json"
PAPER_RESULT_PACK_MD_NAME = "paper_result_pack.md"
FORMAL_EXPERIMENT_GATE_NAME = "formal_experiment_gate.json"

_METHOD_LABELS = {
    "llm_direct": "M0 Direct LLM",
    "single_agent": "M1 Single Agent",
    "fixed_multi_agent": "M2 Fixed Multi-Agent",
    "adaptive_multi_agent": "M3 Proposed",
}
_QUALITY_METRICS = (
    "stsr",
    "evaluation_hcsr",
    "agent_selection_f1",
    "tool_selection_f1",
)
_EFFICIENCY_METRICS = (
    "llm_call_count",
    "agent_call_count",
    "tool_call_count",
    "total_tokens",
    "standardized_estimated_cost",
    "latency_ms",
)
_RESOURCE_METRICS = {
    "llm_call_count",
    "agent_call_count",
    "tool_call_count",
    "total_tokens",
    "standardized_estimated_cost",
    "latency_ms",
}


def build_paper_result_pack(
    run_dir: str | Path,
    *,
    profile: str = "auto",
    min_cases: Optional[int] = None,
    required_methods: Optional[Iterable[str]] = None,
    allow_mock_llm: bool = False,
) -> Dict[str, Any]:
    """Build a paper-writing package from an existing experiment run.

    The returned payload is intentionally derived from persisted artifacts only.
    For formal paper claims, both ``paper_analysis`` and
    ``formal_experiment_gate`` must allow claims.  Pilot runs can still produce
    a pack for debugging, but their ``paper_claims_allowed`` flag is always
    false.
    """
    root = Path(run_dir)
    analysis = build_experiment_paper_analysis(
        root,
        profile=profile,
        min_cases=min_cases,
        required_methods=required_methods,
        allow_mock_llm=allow_mock_llm,
    )
    gate = _read_json_object(root / FORMAL_EXPERIMENT_GATE_NAME)
    readiness = _pack_readiness(analysis, gate)
    tables = _build_tables(analysis)
    rq_map = _build_rq_map(readiness, tables, analysis)
    pack = {
        "schema_version": PAPER_RESULT_PACK_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": root.as_posix(),
        "profile": analysis.get("profile"),
        "readiness": readiness,
        "research_questions": rq_map,
        "tables": tables,
        "copy_ready_text": _copy_ready_text(readiness, rq_map, tables, analysis),
        "writing_boundaries": _writing_boundaries(readiness),
        "artifact_evidence": _artifact_evidence(root, analysis, gate),
        "source_artifacts": {
            "paper_analysis": (root / PAPER_ANALYSIS_JSON_NAME).as_posix(),
            "formal_experiment_gate": (root / FORMAL_EXPERIMENT_GATE_NAME).as_posix(),
        },
    }
    return pack


def write_paper_result_pack(
    run_dir: str | Path,
    *,
    output_dir: str | Path | None = None,
    profile: str = "auto",
    min_cases: Optional[int] = None,
    required_methods: Optional[Iterable[str]] = None,
    allow_mock_llm: bool = False,
    attach_to_manifest: bool = True,
) -> Dict[str, Any]:
    """Write ``paper_result_pack.json`` and ``paper_result_pack.md``."""
    root = Path(run_dir)
    output = Path(output_dir) if output_dir is not None else root
    output.mkdir(parents=True, exist_ok=True)
    pack = build_paper_result_pack(
        root,
        profile=profile,
        min_cases=min_cases,
        required_methods=required_methods,
        allow_mock_llm=allow_mock_llm,
    )
    json_path = output / PAPER_RESULT_PACK_JSON_NAME
    markdown_path = output / PAPER_RESULT_PACK_MD_NAME
    pack["artifact_evidence"]["paper_result_pack_json"] = json_path.as_posix()
    pack["artifact_evidence"]["paper_result_pack_md"] = markdown_path.as_posix()
    json_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_paper_result_pack_markdown(pack), encoding="utf-8")
    if attach_to_manifest:
        _attach_to_manifest(root, pack=pack, json_path=json_path, markdown_path=markdown_path)
    return {
        "status": "completed",
        "pack": pack,
        "json": json_path.as_posix(),
        "markdown": markdown_path.as_posix(),
        "paper_claims_allowed": pack["readiness"]["paper_claims_allowed"],
        "failed_checks": pack["readiness"]["failed_checks"],
    }


def render_paper_result_pack_markdown(pack: Dict[str, Any]) -> str:
    """Render a concise Markdown paper material package."""
    readiness = _dict(pack.get("readiness"))
    tables = _dict(pack.get("tables"))
    text = _dict(pack.get("copy_ready_text"))
    boundaries = _dict(pack.get("writing_boundaries"))
    evidence = _dict(pack.get("artifact_evidence"))
    lines = [
        "# Paper result pack",
        "",
        "## Conclusion guard",
        "",
        f"- profile: `{pack.get('profile')}`",
        f"- paper_claims_allowed: `{readiness.get('paper_claims_allowed')}`",
        f"- source_status: `{readiness.get('source_status')}`",
        f"- failed_checks: `{readiness.get('failed_checks') or []}`",
        f"- interpretation: {readiness.get('interpretation')}",
        "",
        "## Research question map",
        "",
        "| RQ | Purpose | Main evidence | Suggested statement |",
        "|---|---|---|---|",
    ]
    for row in pack.get("research_questions") or []:
        if not isinstance(row, dict):
            continue
        lines.append(
            f"| {row.get('rq_id')} | {row.get('purpose')} "
            f"| {', '.join(_as_list(row.get('evidence_tables')))} "
            f"| {row.get('suggested_statement')} |"
        )

    lines.extend(_render_table_section("RQ1 scheduling correctness", tables.get("rq1_scheduler")))
    lines.extend(_render_table_section("RQ2 task success", tables.get("rq2_task_success")))
    lines.extend(_render_table_section("RQ3 efficiency", tables.get("rq3_efficiency")))
    lines.extend(_render_table_section("M3 vs M2 paired evidence", tables.get("m3_m2_paired")))
    lines.extend(_render_table_section("Failure diagnosis", tables.get("failure_diagnosis")))

    lines.extend(
        [
            "",
            "## Copy-ready paper text",
            "",
            "### Experiment result paragraph",
            "",
            str(text.get("result_paragraph") or ""),
            "",
            "### Method comparison paragraph",
            "",
            str(text.get("method_comparison_paragraph") or ""),
            "",
            "### Limitation paragraph",
            "",
            str(text.get("limitation_paragraph") or ""),
            "",
            "## Writing boundaries",
            "",
            "### Allowed claims",
            "",
        ]
    )
    for item in _as_list(boundaries.get("allowed_claims")):
        lines.append(f"- {item}")
    lines.extend(["", "### Forbidden claims", ""])
    for item in _as_list(boundaries.get("forbidden_claims")):
        lines.append(f"- {item}")
    lines.extend(["", "## Artifact evidence", "", "| Key | Value |", "|---|---|"])
    for key, value in evidence.items():
        lines.append(f"| {key} | `{value}` |")
    return "\n".join(lines) + "\n"


def _pack_readiness(analysis: Dict[str, Any], gate: Dict[str, Any]) -> Dict[str, Any]:
    analysis_readiness = _dict(analysis.get("readiness"))
    profile = str(analysis.get("profile") or "formal")
    analysis_claims = analysis_readiness.get("paper_claims_allowed") is True
    gate_claims = gate.get("paper_claims_allowed") is True
    gate_present = bool(gate)
    failed_checks = _ordered_unique(
        _as_list(analysis_readiness.get("failed_checks"))
        + _as_list(gate.get("failed_checks"))
    )
    if profile == "formal" and not gate_present:
        failed_checks.append("formal_experiment_gate_missing")
    paper_claims_allowed = (
        profile == "formal"
        and analysis_claims
        and gate_present
        and gate_claims
        and not failed_checks
    )
    return {
        "profile": profile,
        "paper_claims_allowed": paper_claims_allowed,
        "source_status": {
            "paper_analysis": analysis_readiness.get("status"),
            "formal_experiment_gate": gate.get("status") if gate_present else "missing",
        },
        "failed_checks": failed_checks,
        "independent_case_count": _nested(analysis, "run", "independent_case_count"),
        "raw_result_count": _nested(analysis, "run", "raw_result_count"),
        "paired_m3_m2_count": _nested(analysis, "m3_vs_m2", "pair_count"),
        "interpretation": _readiness_interpretation(profile, paper_claims_allowed, failed_checks),
    }


def _build_tables(analysis: Dict[str, Any]) -> Dict[str, Any]:
    methods = [
        row for row in analysis.get("method_comparison") or [] if isinstance(row, dict)
    ]
    m3_vs_m2 = _dict(analysis.get("m3_vs_m2"))
    failures = _dict(_dict(analysis.get("failure_analysis")).get("methods"))
    return {
        "rq1_scheduler": _table(
            columns=["method", "agent_selection_f1", "tool_selection_f1"],
            rows=[
                {
                    "method": _label(row.get("method")),
                    "agent_selection_f1": row.get("agent_selection_f1"),
                    "tool_selection_f1": row.get("tool_selection_f1"),
                }
                for row in methods
            ],
        ),
        "rq2_task_success": _table(
            columns=["method", "case_count", "stsr", "evaluation_hcsr"],
            rows=[
                {
                    "method": _label(row.get("method")),
                    "case_count": row.get("case_count"),
                    "stsr": row.get("stsr"),
                    "evaluation_hcsr": row.get("evaluation_hcsr"),
                }
                for row in methods
            ],
        ),
        "rq3_efficiency": _table(
            columns=[
                "method",
                "llm_call_count",
                "agent_call_count",
                "tool_call_count",
                "total_tokens",
                "standardized_estimated_cost",
                "latency_ms",
            ],
            rows=[
                {
                    "method": _label(row.get("method")),
                    "llm_call_count": row.get("llm_call_count"),
                    "agent_call_count": row.get("agent_call_count"),
                    "tool_call_count": row.get("called_tool_count")
                    if row.get("called_tool_count") is not None
                    else row.get("tool_call_count"),
                    "total_tokens": row.get("total_tokens"),
                    "standardized_estimated_cost": row.get("standardized_estimated_cost"),
                    "latency_ms": row.get("latency_ms"),
                }
                for row in methods
            ],
        ),
        "m3_m2_paired": _table(
            columns=[
                "metric",
                "m3_mean",
                "m2_mean",
                "delta_mean",
                "delta_ci_95",
                "test",
                "p_value",
                "relative_saving_rate",
            ],
            rows=_paired_rows(m3_vs_m2),
        ),
        "failure_diagnosis": _table(
            columns=["method", "failed_case_count", "top_failed_rules"],
            rows=[
                {
                    "method": _label(method),
                    "failed_case_count": _dict(row).get("failed_case_count"),
                    "top_failed_rules": _counter_text(_dict(row).get("top_failed_rules")),
                }
                for method, row in failures.items()
            ],
        ),
    }


def _build_rq_map(
    readiness: Dict[str, Any],
    tables: Dict[str, Any],
    analysis: Dict[str, Any],
) -> List[Dict[str, Any]]:
    claims_allowed = readiness.get("paper_claims_allowed") is True
    return [
        {
            "rq_id": "RQ1",
            "purpose": "验证目标—状态调度是否能正确选择 Agent 与工具",
            "primary_metrics": ["agent_selection_f1", "tool_selection_f1"],
            "evidence_tables": ["rq1_scheduler", "m3_m2_paired"],
            "suggested_statement": _rq1_statement(claims_allowed, analysis),
        },
        {
            "rq_id": "RQ2",
            "purpose": "验证生成结果是否满足任务与硬约束",
            "primary_metrics": ["stsr", "evaluation_hcsr"],
            "evidence_tables": ["rq2_task_success", "failure_diagnosis"],
            "suggested_statement": _rq2_statement(claims_allowed, analysis),
        },
        {
            "rq_id": "RQ3",
            "purpose": "验证 M3 相比固定多 Agent 链路是否降低执行开销",
            "primary_metrics": list(_EFFICIENCY_METRICS),
            "evidence_tables": ["rq3_efficiency", "m3_m2_paired"],
            "suggested_statement": _rq3_statement(claims_allowed, tables),
        },
    ]


def _copy_ready_text(
    readiness: Dict[str, Any],
    rq_map: List[Dict[str, Any]],
    tables: Dict[str, Any],
    analysis: Dict[str, Any],
) -> Dict[str, str]:
    claims_allowed = readiness.get("paper_claims_allowed") is True
    if not claims_allowed:
        return {
            "result_paragraph": (
                "当前实验结果尚未通过正式论文证据门禁，因此只能用于链路调试和问题定位，"
                "不能作为论文中支持方法优越性的正式实验结论。"
            ),
            "method_comparison_paragraph": (
                "结果包已生成 RQ 对应表格，但写作时必须先处理 failed_checks 中列出的阻塞项。"
            ),
            "limitation_paragraph": _limitation_text(),
        }
    rq_text = " ".join(str(item.get("suggested_statement") or "") for item in rq_map)
    resource_summary = _best_resource_savings_text(tables)
    return {
        "result_paragraph": (
            f"在 {readiness.get('independent_case_count')} 个独立测试案例上，"
            f"四种方法均按统一实验协议完成比较。{rq_text}"
        ),
        "method_comparison_paragraph": (
            "M2 与 M3 使用相同业务 Agent、离线工具和评价器，二者差异集中在固定全链路执行"
            f"与目标—状态驱动调度。{resource_summary}"
        ),
        "limitation_paragraph": _limitation_text(),
    }


def _writing_boundaries(readiness: Dict[str, Any]) -> Dict[str, List[str]]:
    if readiness.get("paper_claims_allowed") is True:
        allowed = [
            "报告四种方法在已测指标上的差异",
            "报告 M3 相对 M2 的配对差异、置信区间与统计检验结果",
            "讨论 M3 在调用次数、Token、成本和时延上的资源变化",
            "基于失败规则统计分析方法短板",
        ]
    else:
        allowed = [
            "用于调试实验链路",
            "用于检查缺失 artifact、mock/fallback、样本量或 trace 问题",
            "用于准备正式实验前的写作框架",
        ]
    forbidden = [
        "不要把 pilot 或未过门禁的结果写成正式结论",
        "不要声称使用实时、完整、商业级旅游数据",
        "不要声称真实用户满意度或商业部署可用性",
        "不要声称实验没有测量过的能力优势",
        "不要手工修改原始结果后再生成论文数字",
    ]
    return {"allowed_claims": allowed, "forbidden_claims": forbidden}


def _artifact_evidence(root: Path, analysis: Dict[str, Any], gate: Dict[str, Any]) -> Dict[str, Any]:
    artifact_paths = _dict(analysis.get("artifact_paths"))
    result = {
        "run_dir": root.as_posix(),
        "paper_analysis_status": _nested(analysis, "readiness", "status"),
        "formal_gate_status": gate.get("status") if gate else "missing",
        "artifact_paths": artifact_paths,
    }
    artifact_index = gate.get("artifact_index") if isinstance(gate.get("artifact_index"), dict) else None
    if artifact_index:
        result["artifact_index_schema_version"] = artifact_index.get("schema_version")
        result["trace_file_count"] = artifact_index.get("trace_file_count")
        result["trace_combined_sha256"] = artifact_index.get("trace_combined_sha256")
        result["hashed_file_count"] = len(artifact_index.get("files") or [])
    return result


def _attach_to_manifest(
    run_dir: Path,
    *,
    pack: Dict[str, Any],
    json_path: Path,
    markdown_path: Path,
) -> None:
    manifest_path = run_dir / "experiment_manifest.json"
    manifest = _read_json_object(manifest_path)
    if not manifest:
        return
    results = _dict(manifest.get("results"))
    results.update(
        {
            "paper_result_pack_json": json_path.as_posix(),
            "paper_result_pack_md": markdown_path.as_posix(),
        }
    )
    manifest["results"] = results
    manifest["paper_result_pack"] = {
        "schema_version": PAPER_RESULT_PACK_SCHEMA_VERSION,
        "paper_claims_allowed": _nested(pack, "readiness", "paper_claims_allowed"),
        "failed_checks": _nested(pack, "readiness", "failed_checks") or [],
        "json": json_path.as_posix(),
        "markdown": markdown_path.as_posix(),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _paired_rows(m3_vs_m2: Dict[str, Any]) -> List[Dict[str, Any]]:
    metrics = _dict(m3_vs_m2.get("metrics"))
    rows = []
    for metric in list(_QUALITY_METRICS) + list(_EFFICIENCY_METRICS):
        stat = _dict(metrics.get(metric))
        if not stat:
            continue
        rows.append(
            {
                "metric": metric,
                "m3_mean": stat.get("m3_mean"),
                "m2_mean": stat.get("m2_mean"),
                "delta_mean": stat.get("delta_mean"),
                "delta_ci_95": stat.get("delta_ci_95"),
                "test": stat.get("test"),
                "p_value": stat.get("p_value"),
                "relative_saving_rate": stat.get("relative_saving_rate"),
            }
        )
    return rows


def _rq1_statement(claims_allowed: bool, analysis: Dict[str, Any]) -> str:
    if not claims_allowed:
        return "RQ1 暂不形成正式结论；需先通过正式证据门禁。"
    m3 = _method_row(analysis, "adaptive_multi_agent")
    return (
        "M3 的调度正确性由 Agent Selection F1="
        f"{_fmt(m3.get('agent_selection_f1'))}、Tool Selection F1={_fmt(m3.get('tool_selection_f1'))} 支持。"
    )


def _rq2_statement(claims_allowed: bool, analysis: Dict[str, Any]) -> str:
    if not claims_allowed:
        return "RQ2 暂不形成正式结论；需先通过正式证据门禁。"
    m3 = _method_row(analysis, "adaptive_multi_agent")
    return (
        f"M3 的 STSR={_fmt(m3.get('stsr'))}，HCSR={_fmt(m3.get('evaluation_hcsr'))}，"
        "可用于说明任务成功率与硬约束满足情况。"
    )


def _rq3_statement(claims_allowed: bool, tables: Dict[str, Any]) -> str:
    if not claims_allowed:
        return "RQ3 暂不形成正式结论；需先通过正式证据门禁。"
    return _best_resource_savings_text(tables)


def _best_resource_savings_text(tables: Dict[str, Any]) -> str:
    rows = _dict(tables.get("m3_m2_paired")).get("rows") or []
    resource_rows = [
        row for row in rows
        if isinstance(row, dict)
        and row.get("metric") in _RESOURCE_METRICS
        and _number(row.get("relative_saving_rate")) is not None
    ]
    if not resource_rows:
        return "资源开销指标未形成可报告的相对节省率。"
    best = max(resource_rows, key=lambda row: _number(row.get("relative_saving_rate")) or 0.0)
    return (
        f"M3 在 {best.get('metric')} 上相对 M2 的平均节省率为 "
        f"{_fmt_percent(best.get('relative_saving_rate'))}。"
    )


def _method_row(analysis: Dict[str, Any], method: str) -> Dict[str, Any]:
    for row in analysis.get("method_comparison") or []:
        if isinstance(row, dict) and row.get("method") == method:
            return row
    return {}


def _readiness_interpretation(
    profile: str,
    paper_claims_allowed: bool,
    failed_checks: List[str],
) -> str:
    if paper_claims_allowed:
        return "This pack can be used as measured formal experiment evidence."
    if profile == "pilot":
        return "Pilot packs are for pipeline debugging only, not paper conclusions."
    if failed_checks:
        return "This formal pack is blocked by failed_checks and cannot support paper claims yet."
    return "This pack is not authorized for paper claims."


def _limitation_text() -> str:
    return (
        "本实验基于固定受控离线旅游数据与人工标注任务金标，结论仅覆盖已定义任务类型、"
        "指标和数据范围；本文不声称实时旅游数据准确性、真实用户满意度优势或商业部署可用性。"
    )


def _table(*, columns: List[str], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"columns": columns, "rows": rows}


def _render_table_section(title: str, table: Any) -> List[str]:
    table_dict = _dict(table)
    columns = _as_list(table_dict.get("columns"))
    rows = [row for row in table_dict.get("rows") or [] if isinstance(row, dict)]
    lines = ["", f"## {title}", ""]
    if not columns:
        lines.append("_No table data._")
        return lines
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("|" + "|".join("---" for _ in columns) + "|")
    for row in rows:
        lines.append("| " + " | ".join(_fmt_table(row.get(column)) for column in columns) + " |")
    return lines


def _counter_text(value: Any) -> str:
    items = value if isinstance(value, list) else []
    parts = []
    for item in items[:5]:
        data = _dict(item)
        identifier = data.get("id") or data.get("rule_id") or data.get("failure_type")
        if identifier:
            parts.append(f"{identifier}({data.get('count', 0)})")
    return ", ".join(parts)


def _label(method: Any) -> str:
    return _METHOD_LABELS.get(str(method), str(method or ""))


def _read_json_object(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _ordered_unique(values: Iterable[str]) -> List[str]:
    result = []
    seen = set()
    for value in values:
        text = str(value)
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [value] if value else []
    return [str(value)]


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


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


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return str(round(value, 4))
    return str(value)


def _fmt_table(value: Any) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_fmt(item) for item in value) + "]"
    return _fmt(value)


def _fmt_percent(value: Any) -> str:
    number = _number(value)
    if number is None:
        return ""
    return f"{round(number * 100, 2)}%"
