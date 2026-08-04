"""Day 7 development issue and final-fix report generation.

The report is built from persisted pilot artifacts.  It does not call models,
does not re-score outputs, and does not repair method results.  Its purpose is
to turn Day 7 smoke evidence into a concrete audit trail: what was broken, how
the engineering/experiment-link issues were fixed, and which method failures
remain open before a formal paper run.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.core.day7_m3_ablation import DAY7_M3_ABLATION_REPORT_JSON_NAME


DAY7_FIX_REPORT_SCHEMA_VERSION = "ctp-day7-fix-report-v1"
DAY7_ISSUE_REPORT_JSON_NAME = "day7_issue_report.json"
DAY7_FIX_REPORT_MD_NAME = "day7_fix_report.md"
DEFAULT_M3_DEV_STSR_MIN_FOR_CLOSURE = 0.70

ISSUE_CATEGORIES = (
    "infrastructure_errors",
    "experiment_implementation_errors",
    "method_real_failures",
)

_METHOD_LABELS = {
    "llm_direct": "M0 Direct LLM",
    "single_agent": "M1 Single Agent",
    "fixed_multi_agent": "M2 Fixed Multi-Agent",
    "adaptive_multi_agent": "M3 Proposed",
}


def build_day7_fix_report(
    run_dir: str | Path,
    *,
    development_run_dir: str | Path | None = None,
    m3_ablation_run_dir: str | Path | None = None,
) -> Dict[str, Any]:
    """Build a Day 7 issue/fix report from saved pilot/development evidence."""
    root = Path(run_dir)
    artifacts = _load_artifacts(root)
    results = artifacts["results"]
    quality_results = _quality_results(results)
    development_root = Path(development_run_dir) if development_run_dir is not None else None
    development_artifacts = (
        _load_artifacts(development_root)
        if development_root is not None
        else {"summary": {}, "results": [], "manifest": {}, "day7_gate": {}, "paths": {}}
    )
    development_results = _as_dict_list(development_artifacts.get("results"))
    development_quality_results = _quality_results(development_results)
    m3_ablation_evidence = _m3_no_decision_normalizer_ablation_evidence(
        Path(m3_ablation_run_dir) if m3_ablation_run_dir is not None else None
    )
    traces = _load_traces_from_results(root, results)
    llm_calls = [
        call
        for trace in traces
        for call in _as_dict_list(trace.get("llm_calls"))
    ]
    runtime_audit = _runtime_audit(artifacts["manifest"], llm_calls)
    method_quality = _method_quality_summary(quality_results)
    m3_analysis = _m3_systemic_failure_analysis(quality_results)
    development_readiness = _m3_development_readiness_analysis(
        development_artifacts,
        development_quality_results,
    )
    decision_assistance = _decision_assistance_analysis(
        pilot_results=results,
        development_results=development_results,
        development_run_dir=development_root,
    )
    m3_method_readiness = _m3_method_readiness(
        pilot_analysis=m3_analysis,
        development_readiness=development_readiness,
        decision_assistance=decision_assistance,
        m3_ablation_evidence=m3_ablation_evidence,
    )

    issues = {
        "infrastructure_errors": _infrastructure_issues(
            artifacts=artifacts,
            llm_calls=llm_calls,
            runtime_audit=runtime_audit,
        ),
        "experiment_implementation_errors": _experiment_issues(
            artifacts=artifacts,
            results=results,
            quality_results=quality_results,
        ),
        "method_real_failures": _method_failure_issues(
            method_quality=method_quality,
            m3_analysis=m3_analysis,
            development_readiness=development_readiness,
            decision_assistance=decision_assistance,
            m3_method_readiness=m3_method_readiness,
            m3_ablation_evidence=m3_ablation_evidence,
        ),
    }
    issue_counts = {
        category: {
            "total": len(rows),
            "fixed": sum(1 for row in rows if row.get("status") == "fixed"),
            "open": sum(1 for row in rows if row.get("status") == "open"),
            "deferred": sum(1 for row in rows if row.get("status") == "deferred"),
        }
        for category, rows in issues.items()
    }
    flat_issues = [issue for rows in issues.values() for issue in rows]
    checks = {
        "run_dir_exists": root.exists(),
        "core_artifacts_loaded": bool(results)
        and bool(artifacts["summary"])
        and bool(artifacts["manifest"]),
        "pilot_gate_loaded": bool(artifacts["day7_gate"]),
        "three_issue_categories_present": all(category in issues for category in ISSUE_CATEGORIES),
        "each_issue_has_modification": all(bool(issue.get("modification")) for issue in flat_issues),
        "each_issue_has_before_after": all(
            bool(issue.get("before_run")) and bool(issue.get("after_run"))
            for issue in flat_issues
        ),
        "each_issue_has_regression_or_diagnostic_test": all(
            bool(issue.get("regression_tests")) for issue in flat_issues
        ),
        "m3_systemic_analysis_present": bool(m3_analysis),
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    report = {
        "schema_version": DAY7_FIX_REPORT_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "completed" if not failed_checks else "incomplete",
        "run_dir": root.as_posix(),
        "run": _run_summary(root, artifacts, results, quality_results, traces, llm_calls),
        "checks": checks,
        "failed_checks": failed_checks,
        "issue_counts": issue_counts,
        "issues": issues,
        "runtime_audit": runtime_audit,
        "method_quality_summary": method_quality,
        "m3_systemic_failure_analysis": m3_analysis,
        "m3_development_readiness_analysis": development_readiness,
        "agent_decision_assistance_analysis": decision_assistance,
        "m3_no_decision_normalizer_ablation": m3_ablation_evidence,
        "m3_method_readiness": m3_method_readiness,
        "paper_use_policy": _paper_use_policy(m3_method_readiness),
        "artifact_paths": _artifact_paths(root, artifacts),
    }
    return report


def write_day7_fix_report(
    run_dir: str | Path,
    *,
    development_run_dir: str | Path | None = None,
    m3_ablation_run_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
    attach_to_manifest: bool = True,
) -> Dict[str, Any]:
    """Write ``day7_issue_report.json`` and ``day7_fix_report.md``."""
    root = Path(run_dir)
    output = Path(output_dir) if output_dir is not None else root
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / DAY7_ISSUE_REPORT_JSON_NAME
    markdown_path = output / DAY7_FIX_REPORT_MD_NAME
    report = build_day7_fix_report(
        root,
        development_run_dir=development_run_dir,
        m3_ablation_run_dir=m3_ablation_run_dir,
    )
    report["artifact_paths"]["day7_issue_report_json"] = json_path.as_posix()
    report["artifact_paths"]["day7_fix_report_md"] = markdown_path.as_posix()
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_day7_fix_report_markdown(report), encoding="utf-8")
    if attach_to_manifest and output == root:
        _attach_to_manifest(
            run_dir=root,
            json_path=json_path,
            markdown_path=markdown_path,
            report=report,
        )
    return {
        "status": report["status"],
        "report": report,
        "json": json_path.as_posix(),
        "markdown": markdown_path.as_posix(),
        "failed_checks": report["failed_checks"],
        "issue_counts": report["issue_counts"],
        "m3_systemic_failure": report["m3_systemic_failure_analysis"].get("systemic_failure"),
        "m3_method_formal_run_blocked": _nested(
            report,
            "m3_method_readiness",
            "formal_run_blocked",
        ),
        "m3_programmatic_decision_rate": _nested(
            report,
            "m3_method_readiness",
            "programmatic_decision_rate",
        ),
        "m3_ablation_closed": _nested(
            report,
            "m3_method_readiness",
            "ablation_closed",
        ),
        "m3_ablation_status": _nested(
            report,
            "m3_method_readiness",
            "ablation_status",
        ),
    }


def render_day7_fix_report_markdown(report: Dict[str, Any]) -> str:
    """Render the issue/fix report as a human-readable Markdown document."""
    run = _dict(report.get("run"))
    counts = _dict(report.get("issue_counts"))
    m3 = _dict(report.get("m3_systemic_failure_analysis"))
    m3_readiness = _dict(report.get("m3_method_readiness"))
    decision_assistance = _dict(report.get("agent_decision_assistance_analysis"))
    m3_ablation = _dict(report.get("m3_no_decision_normalizer_ablation"))
    runtime = _dict(report.get("runtime_audit"))
    lines = [
        "# Day 7 开发期问题清单与最后修正报告",
        "",
        "## 结论",
        "",
        f"- report_status: `{report.get('status')}`",
        f"- run_id: `{run.get('run_id')}`",
        f"- pilot_gate_status: `{run.get('pilot_gate_status')}`",
        f"- raw_result_count: `{run.get('raw_result_count')}`",
        f"- quality_result_count: `{run.get('quality_result_count')}`",
        f"- llm_call_count: `{run.get('llm_call_count')}`",
        f"- runtime_consistent_with_manifest: `{runtime.get('consistent_with_manifest')}`",
        f"- M3_systemic_failure: `{m3.get('systemic_failure')}`",
        f"- M3_method_formal_run_blocked: `{m3_readiness.get('formal_run_blocked')}`",
        f"- M3_programmatic_decision_rate: `{_fmt(m3_readiness.get('programmatic_decision_rate'))}`",
        f"- M3_no_decision_normalizer_ablation: `{m3_ablation.get('status')}`",
        f"- failed_checks: `{report.get('failed_checks') or []}`",
        "",
        "## 三类问题统计",
        "",
        "| 类别 | 总数 | 已修正 | 未关闭 | 延后 |",
        "|---|---:|---:|---:|---:|",
    ]
    for category in ISSUE_CATEGORIES:
        row = _dict(counts.get(category))
        lines.append(
            f"| {category} | {row.get('total', 0)} | {row.get('fixed', 0)} "
            f"| {row.get('open', 0)} | {row.get('deferred', 0)} |"
        )

    lines.extend(
        [
            "",
            "## 问题清单与修改对照",
            "",
        ]
    )
    issues = _dict(report.get("issues"))
    for category in ISSUE_CATEGORIES:
        lines.extend(
            [
                f"### {category}",
                "",
                "| ID | 状态 | 严重度 | 问题 | 修改说明 | 修改后证据 | 回归/诊断测试 |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for issue in _as_dict_list(issues.get(category)):
            lines.append(
                "| {issue_id} | `{status}` | `{severity}` | {summary} | {modification} "
                "| {after_run} | {tests} |".format(
                    issue_id=issue.get("issue_id"),
                    status=issue.get("status"),
                    severity=issue.get("severity"),
                    summary=_md(issue.get("summary")),
                    modification=_md(issue.get("modification")),
                    after_run=_md(issue.get("after_run")),
                    tests=_md(", ".join(issue.get("regression_tests") or [])),
                )
            )
        if not _as_dict_list(issues.get(category)):
            lines.append("| - | - | - | 当前报告未发现该类问题 | - | - | - |")
        lines.append("")

    lines.extend(
        [
            "## M3 是否存在整类任务系统性失败",
            "",
            f"- quality_unit_count: `{m3.get('quality_unit_count')}`",
            f"- failed_quality_unit_count: `{m3.get('failed_quality_unit_count')}`",
            f"- failure_rate: `{_fmt(m3.get('failure_rate'))}`",
            f"- affected_task_type_count: `{m3.get('affected_task_type_count')}`",
            f"- systemic_failure: `{m3.get('systemic_failure')}`",
            f"- interpretation: {m3.get('interpretation')}",
            "",
            "| 任务类型 | 总数 | 失败数 | 失败率 | Top failed rules |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for row in _as_dict_list(m3.get("task_type_breakdown")):
        lines.append(
            f"| {row.get('task_type')} | {row.get('total')} | {row.get('failed')} "
            f"| {_fmt(row.get('failure_rate'))} | {_fmt_counter(row.get('top_failed_rules'))} |"
        )

    lines.extend(
        [
            "",
            "## M3 程序性 Agent 决策补全披露",
            "",
            "- 口径：programmatic_decision_count = deterministic normalizer 决策 + reused/synthetic 决策；它不属于 LLM fallback，但属于论文必须披露的系统机制。",
            f"- ablation_required: `{m3_readiness.get('ablation_required')}`",
            f"- ablation_closed: `{m3_readiness.get('ablation_closed')}`",
            f"- ablation_status: `{m3_readiness.get('ablation_status')}`",
            f"- ablation_run_dir: `{m3_readiness.get('ablation_run_dir')}`",
            f"- formal_run_blocked: `{m3_readiness.get('formal_run_blocked')}`",
            "",
            "| scope | method | agent outputs | programmatic | rate | normalizer | reused/synthetic | valid LLM |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for scope, payload in sorted(decision_assistance.items()):
        for method, row in sorted(_dict(_dict(payload).get("methods")).items()):
            lines.append(
                f"| {scope} | {method} | {row.get('agent_decision_output_count')} "
                f"| {row.get('programmatic_decision_count')} "
                f"| {_fmt(row.get('programmatic_decision_rate'))} "
                f"| {row.get('deterministic_normalizer_count')} "
                f"| {row.get('reused_or_synthetic_decision_count')} "
                f"| {row.get('llm_valid_decision_count')} |"
            )

    lines.extend(
        [
            "",
            "## 后续论文使用边界",
            "",
            f"- {(_dict(report.get('paper_use_policy'))).get('summary')}",
            "",
            "## 产物路径",
            "",
            "| Artifact | Path |",
            "|---|---|",
        ]
    )
    for key, value in _dict(report.get("artifact_paths")).items():
        lines.append(f"| {key} | `{value}` |")
    return "\n".join(lines) + "\n"


def _load_artifacts(run_dir: Path) -> Dict[str, Any]:
    return {
        "summary": _read_json_object(run_dir / "evaluation_summary.json"),
        "results": _read_json_list(run_dir / "benchmark_results.json"),
        "manifest": _read_json_object(run_dir / "experiment_manifest.json"),
        "day7_gate": _read_json_object(run_dir / "day7_pilot_gate.json"),
        "paper_analysis": _read_json_object(run_dir / "paper_analysis.json"),
        "paths": {
            "benchmark_results_json": run_dir / "benchmark_results.json",
            "benchmark_results_csv": run_dir / "benchmark_results.csv",
            "evaluation_summary": run_dir / "evaluation_summary.json",
            "experiment_manifest": run_dir / "experiment_manifest.json",
            "day7_pilot_gate": run_dir / "day7_pilot_gate.json",
            "day7_pilot_report": run_dir / "day7_pilot_report.md",
            "paper_analysis_json": run_dir / "paper_analysis.json",
            "paper_analysis_md": run_dir / "paper_analysis.md",
            "trace_dir": run_dir / "traces",
        },
    }


def _run_summary(
    run_dir: Path,
    artifacts: Dict[str, Any],
    results: List[Dict[str, Any]],
    quality_results: List[Dict[str, Any]],
    traces: List[Dict[str, Any]],
    llm_calls: List[Dict[str, Any]],
) -> Dict[str, Any]:
    manifest = _dict(artifacts.get("manifest"))
    gate = _dict(artifacts.get("day7_gate"))
    summary = _dict(artifacts.get("summary"))
    structure = _dict(gate.get("pilot_structure"))
    return {
        "run_dir": run_dir.as_posix(),
        "run_id": manifest.get("run_id") or gate.get("run_id"),
        "dataset_id": manifest.get("dataset_id") or _nested(manifest, "dataset", "id"),
        "dataset_version": manifest.get("dataset_version") or _nested(manifest, "dataset", "version"),
        "pilot_gate_status": gate.get("status"),
        "raw_result_count": len(results),
        "quality_result_count": len(quality_results),
        "summary_quality_result_count": summary.get("quality_result_count"),
        "trace_count": len(traces),
        "llm_call_count": len(llm_calls),
        "case_count": structure.get("case_count"),
        "total_turn_count": structure.get("total_turn_count"),
        "expected_result_count": gate.get("expected_result_count"),
        "model": manifest.get("model") or _nested(manifest, "model_config", "model"),
        "temperature": manifest.get("temperature") or _nested(manifest, "runtime_config", "temperature"),
        "max_tokens": manifest.get("max_tokens") or _nested(manifest, "runtime_config", "max_tokens"),
        "timeout_seconds": manifest.get("timeout_seconds")
        or _nested(manifest, "runtime_config", "timeout_seconds"),
        "retry_max_attempts": manifest.get("retry_max_attempts")
        or _nested(manifest, "runtime_config", "retry_max_attempts"),
    }


def _infrastructure_issues(
    *,
    artifacts: Dict[str, Any],
    llm_calls: List[Dict[str, Any]],
    runtime_audit: Dict[str, Any],
) -> List[Dict[str, Any]]:
    manifest = _dict(artifacts.get("manifest"))
    gate = _dict(artifacts.get("day7_gate"))
    trace_summary = _dict(gate.get("trace_summary"))
    return [
        _issue(
            issue_id="INFRA-001",
            category="infrastructure_error",
            severity="high",
            status="fixed",
            summary="报告参数和真实 LLM 请求参数曾可能不一致。",
            before_run="配置模块先加载 settings.temperature=0.2 / timeout=90，pilot/preflight 后置写入环境变量，可能导致 manifest 写 0/60 但 API 实际用 0.2/90。",
            modification="运行时参数改为每次请求解析并写入 request_options，temperature=0 不再被当成空值；trace、manifest、preflight 使用同一套冻结参数。",
            after_run=(
                f"当前 pilot manifest: model={manifest.get('model')}, "
                f"temperature={_nested(manifest, 'runtime_config', 'temperature')}, "
                f"timeout={_nested(manifest, 'runtime_config', 'timeout_seconds')}, "
                f"max_tokens={_nested(manifest, 'runtime_config', 'max_tokens')}; "
                f"LLM 调用参数不一致数={runtime_audit.get('mismatch_count')}。"
            ),
            evidence=runtime_audit,
            regression_tests=[
                "tests/test_tracing.py::test_openrouter_client_preserves_zero_temperature_and_records_retry_metadata",
                "tests/test_tracing.py::test_openrouter_client_uses_runtime_env_after_settings_loaded",
                "tests/test_day6_formal_run_preflight.py::test_day6_formal_preflight_rejects_nonzero_temperature",
            ],
            paper_risk="如果不修，论文中的温度、超时和成本/时延统计不可复现。",
            next_action="正式实验继续使用 manifest 与 trace 的运行参数一致性作为硬门禁。",
        ),
        _issue(
            issue_id="INFRA-002",
            category="infrastructure_error",
            severity="high",
            status="fixed",
            summary="重试范围曾过宽，并且 SDK 内部重试可能形成隐藏调用。",
            before_run="客户端会对所有异常重试，OpenAI SDK 自身也可能自动重试；协议要求只允许 429、5xx 和网络超时，且初次请求+最多额外两次重试。",
            modification="禁用 SDK 内部重试；自定义重试限制在 HTTP 429、HTTP 5xx、网络超时；最大尝试次数统一为 3，并完整写入 retry audit。",
            after_run=(
                f"当前 pilot retry_max_attempts={_nested(manifest, 'runtime_config', 'retry_max_attempts')}，"
                f"trace 记录 retry_count={trace_summary.get('retry_count')}，"
                f"LLM 调用数={len(llm_calls)}。"
            ),
            evidence={
                "manifest_retry_max_attempts": _nested(
                    manifest,
                    "runtime_config",
                    "retry_max_attempts",
                ),
                "trace_retry_count": trace_summary.get("retry_count"),
                "retry_values_in_calls": runtime_audit.get("retry_max_attempts_values"),
            },
            regression_tests=[
                "tests/test_tracing.py::test_openrouter_client_preserves_zero_temperature_and_records_retry_metadata",
                "tests/test_tracing.py::test_openrouter_client_does_not_retry_non_protocol_errors",
            ],
            paper_risk="如果不修，真实 API 调用次数、Token、成本和失败率都会被隐藏重试污染。",
            next_action="正式实验不允许绕过自定义 retry audit。",
        ),
        _issue(
            issue_id="INFRA-003",
            category="infrastructure_error",
            severity="medium",
            status="fixed",
            summary="严格模式下 Mock fallback 可能污染真实实验证据。",
            before_run="旧链路存在真实 API 不可用时隐式退回 Mock 的风险。",
            modification="严格模式阻止 Mock fallback，pilot gate 检查所有 LLM 调用均非 mock、非 fallback。",
            after_run=(
                f"当前 pilot mock_llm_call_count={trace_summary.get('mock_llm_call_count')}，"
                f"fallback_llm_call_count={trace_summary.get('fallback_llm_call_count')}。"
            ),
            evidence={
                "mock_llm_call_count": trace_summary.get("mock_llm_call_count"),
                "fallback_llm_call_count": trace_summary.get("fallback_llm_call_count"),
                "strict_mode": _nested(manifest, "runtime_config", "strict_mode"),
            },
            regression_tests=[
                "tests/test_tracing.py::test_strict_mode_rejects_already_initialized_mock_client",
                "tests/test_tracing.py::test_mock_fallback_and_strict_mode_are_recorded",
                "tests/test_day7_pilot.py::test_day7_pilot_runs_subset_and_writes_gate_report",
            ],
            paper_risk="如果不修，论文可能把 Mock 结果误报为真实模型结果。",
            next_action="正式实验继续保持 EXPERIMENT_STRICT_MODE=true。",
        ),
        _issue(
            issue_id="INFRA-004",
            category="infrastructure_error",
            severity="medium",
            status="fixed",
            summary="Day7 pilot 初次真实运行暴露过 LLM 客户端局部 import 导致的运行时错误。",
            before_run="LLMManager 初始化中局部 import os 造成作用域遮蔽，真实 pilot 未能进入有效 LLM 调用。",
            modification="移除局部 import，复用模块级 os 导入，使真实 API 初始化路径恢复。",
            after_run=(
                f"当前 pilot 已产生 {trace_summary.get('llm_call_count')} 次真实 LLM 调用，"
                f"result_error_count={_nested(gate, 'result_status_summary', 'error_count')}。"
            ),
            evidence={
                "llm_call_count": trace_summary.get("llm_call_count"),
                "result_error_count": _nested(gate, "result_status_summary", "error_count"),
            },
            regression_tests=[
                "tests/test_day6_real_api_smoke.py::test_real_api_smoke_writes_trace_token_latency_and_cost_reports",
                "tests/test_day7_pilot.py::test_day7_pilot_runs_subset_and_writes_gate_report",
            ],
            paper_risk="如果不修，无法产生真实 pilot 的请求级 trace 证据。",
            next_action="保持真实运行前先执行 preflight，再执行小规模 pilot。",
        ),
    ]


def _experiment_issues(
    *,
    artifacts: Dict[str, Any],
    results: List[Dict[str, Any]],
    quality_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    gate = _dict(artifacts.get("day7_gate"))
    structure = _dict(gate.get("pilot_structure"))
    result_status = _dict(gate.get("result_status_summary"))
    return [
        _issue(
            issue_id="EXP-001",
            category="experiment_implementation_error",
            severity="high",
            status="fixed",
            summary="数据解析门禁曾只展示解析结果，不检查解析值是否等于金标。",
            before_run="“改成3人”案例会被解析成上一轮 2 人，旧验证器仍显示 passed。",
            modification="新增自然语言解析值与金标一致性检查；changed_slots 新值必须出现在当前话语中；preserved_slots 必须保持上一轮状态。",
            after_run="ctp120_dev 与 benchmark_test 均通过中文解析门禁；people_count 当前轮覆盖历史值。",
            evidence={
                "dataset_version": "2026-07-31-zh",
                "quality_result_count": len(quality_results),
            },
            regression_tests=[
                "tests/test_day6_benchmark_dataset_quality.py::test_dataset_gate_prefers_current_turn_value_over_history_for_people_change",
                "tests/test_day6_benchmark_dataset_quality.py::test_dataset_gate_blocks_parse_gold_mismatch_for_changed_slot",
                "tests/test_day6_benchmark_dataset_quality.py::test_dataset_gate_requires_changed_slot_value_in_current_utterance",
                "tests/test_day6_benchmark_dataset_quality.py::test_dataset_gate_blocks_preserved_slot_conflict",
            ],
            paper_risk="如果不修，正式实验的多轮任务标签不可信，M3 的状态复用评价会失真。",
            next_action="扩展到 100-150 例时继续使用同一 validator 作为数据入库门禁。",
        ),
        _issue(
            issue_id="EXP-002",
            category="experiment_implementation_error",
            severity="high",
            status="fixed",
            summary="开发集、烟雾集、正式测试集曾缺少重复、近似重复和中文口径检查。",
            before_run="烟雾集和开发集之间存在完全相同输入，且旧数据主要为英文。",
            modification="开发集和烟雾集切换为中文口径；新增跨 split 重复/近似重复、中文输入、离线可行性门禁。",
            after_run="benchmark_test 当前作为 8 个顶层案例、10 个实际轮次的中文 smoke 草稿，不再使用旧英文重复输入。",
            evidence={
                "pilot_case_count": structure.get("case_count"),
                "pilot_turn_count": structure.get("total_turn_count"),
                "selected_case_ids": structure.get("selected_case_ids"),
            },
            regression_tests=[
                "tests/test_day6_benchmark_dataset_quality.py::test_dataset_gate_blocks_cross_split_duplicate_and_near_duplicate",
                "tests/test_day6_benchmark_dataset_quality.py::test_dataset_gate_blocks_non_chinese_visible_inputs",
                "tests/test_day6_benchmark_dataset_quality.py::test_dataset_gate_blocks_offline_infeasible_constraints",
                "tests/test_day6_benchmark_dataset_quality.py::test_benchmark_test_smoke_dataset_has_strict_gold_labels",
            ],
            paper_risk="如果不修，测试集可能泄漏开发集样本，论文实验会被认为不独立。",
            next_action="正式测试集冻结前必须再次运行跨 split 检查。",
        ),
        _issue(
            issue_id="EXP-003",
            category="experiment_implementation_error",
            severity="medium",
            status="fixed",
            summary="Day7 pilot 默认规模曾不是完整 8 条 smoke 链路。",
            before_run="pilot 默认只抽 3 个案例，无法得到协议要求的 8 个顶层案例、10 个轮次、4 种方法、40 条结果。",
            modification="DEFAULT_MAX_CASES 调整为 8；gate 校验 case_count、turn_count、result_count、trace_count。",
            after_run=(
                f"当前 pilot case_count={structure.get('case_count')}，"
                f"turn_count={structure.get('total_turn_count')}，"
                f"expected_result_count={gate.get('expected_result_count')}，"
                f"actual_result_count={gate.get('actual_result_count')}。"
            ),
            evidence={
                "pilot_structure": structure,
                "expected_result_count": gate.get("expected_result_count"),
                "actual_result_count": gate.get("actual_result_count"),
            },
            regression_tests=[
                "tests/test_day7_pilot.py::test_day7_pilot_default_scope_matches_full_smoke_set",
                "tests/test_day7_pilot.py::test_day7_pilot_runs_subset_and_writes_gate_report",
            ],
            paper_risk="如果不修，pilot 不能覆盖完整 smoke 协议，后续问题清单不充分。",
            next_action="正式实验不使用 pilot 规模；pilot 只作扩跑前健康检查。",
        ),
        _issue(
            issue_id="EXP-004",
            category="experiment_implementation_error",
            severity="medium",
            status="fixed",
            summary="pilot gate 曾容易把证据完整性和方法质量混在一起。",
            before_run="方法失败或无业务 Agent 的澄清/闲聊轮次可能导致证据 gate 被误判失败。",
            modification="pilot gate 只硬检查证据完整性、真实运行参数、无 Mock/fallback；方法质量作为诊断字段输出。",
            after_run=(
                f"当前 pilot gate={gate.get('status')}；result_status_counts="
                f"{result_status.get('status_counts')}；quality_gated="
                f"{result_status.get('quality_gated')}。"
            ),
            evidence={
                "pilot_gate_status": gate.get("status"),
                "quality_policy": gate.get("quality_policy"),
                "result_status_summary": result_status,
            },
            regression_tests=[
                "tests/test_day7_pilot.py::test_day7_pilot_runs_subset_and_writes_gate_report",
            ],
            paper_risk="如果不修，真实方法失败会被误当成基础设施失败，问题定位混乱。",
            next_action="正式实验 gate 与质量阈值仍需分层：先证据有效，再谈方法指标。",
        ),
    ]


def _method_failure_issues(
    *,
    method_quality: Dict[str, Any],
    m3_analysis: Dict[str, Any],
    development_readiness: Dict[str, Any],
    decision_assistance: Dict[str, Any],
    m3_method_readiness: Dict[str, Any],
    m3_ablation_evidence: Dict[str, Any],
) -> List[Dict[str, Any]]:
    m3_rules = _fmt_counter(m3_analysis.get("top_failed_rules"))
    m3_reasons = _fmt_counter(m3_analysis.get("top_failure_reasons"))
    m3_quality_open = bool(m3_method_readiness.get("quality_formal_run_blocked"))
    normalizer_ablation_open = bool(m3_method_readiness.get("ablation_required"))
    dev = _dict(development_readiness.get("adaptive_multi_agent"))
    dev_m2 = _dict(development_readiness.get("fixed_multi_agent"))
    m3_programmatic = _dict(
        _nested(decision_assistance, "development", "methods", "adaptive_multi_agent")
        or _nested(decision_assistance, "pilot", "methods", "adaptive_multi_agent")
    )
    readiness_reasons = _fmt_counter(m3_method_readiness.get("blocking_reasons"))
    ablation_summary = _dict(m3_ablation_evidence.get("summary"))
    issues = [
        _issue(
            issue_id="METHOD-001",
            category="method_real_failure",
            severity="critical",
            status="open" if m3_quality_open else "fixed",
            summary="M3 在真实 smoke 质量评价中存在整类任务系统性失败。",
            before_run="Day7 之前没有真实 smoke 结果，无法判断 M3 是否只是脚手架可跑，还是方法真的可用。",
            modification="本任务不美化结果；新增按任务类型、规则、失败原因的诊断报告，把 M3 真实失败显式列入后续修正入口。",
            after_run=(
                f"M3 quality_unit_count={m3_analysis.get('quality_unit_count')}，"
                f"failed={m3_analysis.get('failed_quality_unit_count')}，"
                f"failure_rate={_fmt(m3_analysis.get('failure_rate'))}，"
                f"systemic_failure={m3_analysis.get('systemic_failure')}，"
                f"dev_stsr={_fmt(dev.get('stsr_rate'))}，"
                f"dev_hcsr={_fmt(dev.get('evaluation_hcsr_mean'))}，"
                f"m2_dev_hcsr={_fmt(dev_m2.get('evaluation_hcsr_mean'))}，"
                f"formal_run_blocked={m3_method_readiness.get('quality_formal_run_blocked')}。"
            ),
            evidence={
                "pilot_smoke_analysis": m3_analysis,
                "development_quality_analysis": development_readiness,
                "m3_method_readiness": m3_method_readiness,
            },
            regression_tests=[
                "tests/test_day7_fix_report.py::test_day7_fix_report_classifies_m3_systemic_failures",
                "tests/test_day7_fix_report.py::test_day7_fix_report_keeps_method_open_when_dev_quality_is_low",
            ],
            paper_risk="该问题未关闭前，不能用当前 pilot 支撑 M3 优于 M2 的论文结论。",
            next_action="Day8 优先修 M3 输出结构、任务类型稳定性、工具证据和多轮状态复用。",
        )
    ]
    issues.append(
        _issue(
            issue_id="METHOD-002",
            category="method_real_failure",
            severity="high",
            status="open" if m3_quality_open else "fixed",
            summary="M3 失败集中在任务类型/执行状态/最终答案一致性与工具证据规则。",
            before_run="只有总体 STSR 或 HCSR 时，看不出是调度错、工具证据错，还是最终结构化输出错。",
            modification="报告从 evaluation_failed_rule_ids 和输出失败原因中抽取 Top 规则，形成可落地的修正入口。",
            after_run=(
                f"M3 top_failed_rules={m3_rules or 'none'}；"
                f"top_failure_reasons={m3_reasons or 'none'}；"
                f"readiness_blocking_reasons={readiness_reasons or 'none'}；"
                f"quality_recovered={not m3_quality_open}。"
            ),
            evidence={
                "top_failed_rules": m3_analysis.get("top_failed_rules"),
                "top_failure_reasons": m3_analysis.get("top_failure_reasons"),
                "task_type_breakdown": m3_analysis.get("task_type_breakdown"),
                "development_top_failed_rules": dev.get("top_failed_rules"),
                "development_agent_set_exact_match_mean": dev.get("agent_set_exact_match_mean"),
                "development_tool_set_exact_match_mean": dev.get("tool_set_exact_match_mean"),
                "blocking_reasons": m3_method_readiness.get("blocking_reasons"),
            },
            regression_tests=[
                "tests/test_day7_fix_report.py::test_day7_fix_report_classifies_m3_systemic_failures",
                "tests/test_day7_fix_report.py::test_day7_fix_report_keeps_method_open_when_dev_quality_is_low",
            ],
            paper_risk="如果直接扩跑 100+ 案例，会把同一类错误复制成大规模失败，浪费免费 API 额度。",
            next_action="先做小规模回归：每修一类规则，跑 8 条 smoke；通过后再扩展正式集。",
        )
    )
    issues.append(
        _issue(
            issue_id="METHOD-003",
            category="method_real_failure",
            severity="high" if normalizer_ablation_open else "medium",
            status="open" if normalizer_ablation_open else "fixed",
            summary=(
                "M3 的 Agent 决策存在程序性补全；必须在论文中披露，并设置无补全消融。"
            ),
            before_run=(
                "LLM fallback=0 只能说明没有模型层降级；它不能说明每个 Agent 决策都由模型直接生成。"
                "此前问题报告没有聚合 decision_fallback_used、decision_source 和 reused Agent 输出。"
            ),
            modification=(
                "新增 agent_decision_assistance_analysis，逐 scope、逐方法统计 LLM 有效决策、"
                "deterministic normalizer、reused/synthetic 决策和 programmatic_decision_rate。"
            ),
            after_run=(
                f"M3 programmatic_decision_count={m3_programmatic.get('programmatic_decision_count')} / "
                f"{m3_programmatic.get('agent_decision_output_count')}，"
                f"rate={_fmt(m3_programmatic.get('programmatic_decision_rate'))}，"
                f"ablation_required={m3_method_readiness.get('ablation_required')}，"
                f"ablation_status={m3_ablation_evidence.get('status')}。"
            ),
            evidence={
                "decision_assistance_analysis": decision_assistance,
                "m3_programmatic_decision_summary": m3_programmatic,
                "m3_no_decision_normalizer_ablation": m3_ablation_evidence,
                "required_ablation": {
                    "name": "M3-no-decision-normalizer",
                    "controlled_change": (
                        "disable deterministic agent decision normalizer and report failures "
                        "instead of repairing invalid or empty Agent decisions"
                    ),
                    "must_report": [
                        "STSR/HCSR without normalizer",
                        "agent/task/tool errors without normalizer",
                        "programmatic_decision_rate",
                    ],
                    "closed": bool(ablation_summary.get("ablation_closed")),
                },
            },
            regression_tests=[
                "tests/test_day7_fix_report.py::test_day7_fix_report_discloses_programmatic_agent_decisions",
            ],
            paper_risk=(
                "若不披露和消融，论文读者会误以为 M3 的 Agent 决策全部来自大模型，"
                "从而高估多 Agent 协作本身的贡献。"
            ),
            next_action=(
                "Day8 设计 M3-no-decision-normalizer 消融；正文方法部分披露 normalizer/reuse 机制，"
                "实验表中单列触发比例。"
            ),
        )
    )
    return issues


def _m3_systemic_failure_analysis(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = [row for row in results if row.get("method") == "adaptive_multi_agent"]
    failed_rows = [row for row in rows if _is_failed_quality_result(row)]
    by_task: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_task[_task_type(row)].append(row)
    task_breakdown = []
    systemic_task_types = []
    for task_type, task_rows in sorted(by_task.items()):
        failed = [row for row in task_rows if _is_failed_quality_result(row)]
        rate = _safe_rate(len(failed), len(task_rows))
        if rate == 1.0:
            systemic_task_types.append(task_type)
        task_breakdown.append(
            {
                "task_type": task_type,
                "total": len(task_rows),
                "failed": len(failed),
                "failure_rate": rate,
                "status_counts": dict(Counter(str(row.get("status") or "unknown") for row in task_rows)),
                "top_failed_rules": _counter_payload(_failed_rules(failed), limit=8),
            }
        )
    failure_rate = _safe_rate(len(failed_rows), len(rows))
    systemic_failure = bool(rows) and (
        failure_rate >= 0.8
        or (len(systemic_task_types) >= max(2, len(task_breakdown) // 2) and failure_rate >= 0.5)
    )
    return {
        "method": "adaptive_multi_agent",
        "label": _METHOD_LABELS["adaptive_multi_agent"],
        "quality_unit_count": len(rows),
        "failed_quality_unit_count": len(failed_rows),
        "failure_rate": failure_rate,
        "status_counts": dict(Counter(str(row.get("status") or "unknown") for row in rows)),
        "affected_task_type_count": len(systemic_task_types),
        "systemic_task_types": systemic_task_types,
        "systemic_failure": systemic_failure,
        "top_failed_rules": _counter_payload(_failed_rules(failed_rows), limit=10),
        "top_failure_reasons": _counter_payload(_failure_reasons(failed_rows), limit=10),
        "task_type_breakdown": task_breakdown,
        "interpretation": (
            "M3 在当前真实 smoke 中覆盖的质量单元全部失败，说明失败不是个别案例波动，"
            "而是输出结构、任务类型识别、工具证据或多轮状态复用链路仍需修正。"
            if systemic_failure
            else "当前证据未显示 M3 存在整类任务系统性失败。"
        ),
        "formal_run_blocked": systemic_failure,
    }


def _m3_development_readiness_analysis(
    artifacts: Dict[str, Any],
    quality_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    summary = _dict(artifacts.get("summary"))
    methods = _dict(summary.get("methods"))
    available = bool(methods) or bool(quality_results)
    if not available:
        return {
            "available": False,
            "formal_run_blocked": False,
            "blocking_reasons": [],
            "thresholds": {
                "m3_stsr_min_for_closure": DEFAULT_M3_DEV_STSR_MIN_FOR_CLOSURE,
            },
        }

    m3 = _development_method_payload(methods, quality_results, "adaptive_multi_agent")
    m2 = _development_method_payload(methods, quality_results, "fixed_multi_agent")
    blocking_reasons: Counter[str] = Counter()
    m3_stsr = _number(m3.get("stsr_rate"))
    m3_hcsr = _number(m3.get("evaluation_hcsr_mean"))
    m2_hcsr = _number(m2.get("evaluation_hcsr_mean"))
    if m3_stsr is not None and m3_stsr < DEFAULT_M3_DEV_STSR_MIN_FOR_CLOSURE:
        blocking_reasons["development_m3_stsr_below_threshold"] += 1
    if m3_hcsr is not None and m2_hcsr is not None and m3_hcsr < m2_hcsr:
        blocking_reasons["development_m3_hcsr_below_m2"] += 1

    return {
        "available": True,
        "formal_run_blocked": bool(blocking_reasons),
        "blocking_reasons": _counter_payload(blocking_reasons, limit=10),
        "thresholds": {
            "m3_stsr_min_for_closure": DEFAULT_M3_DEV_STSR_MIN_FOR_CLOSURE,
            "m3_hcsr_should_not_be_below_m2": True,
        },
        "adaptive_multi_agent": m3,
        "fixed_multi_agent": m2,
        "interpretation": (
            "20-case development evidence still blocks method closure."
            if blocking_reasons
            else "20-case development evidence does not block method closure."
        ),
    }


def _development_method_payload(
    methods: Dict[str, Any],
    quality_results: List[Dict[str, Any]],
    method: str,
) -> Dict[str, Any]:
    summary_row = _dict(methods.get(method))
    rows = [row for row in quality_results if row.get("method") == method]
    if summary_row:
        return {
            "case_count": summary_row.get("case_count"),
            "stsr_rate": summary_row.get("stsr_rate"),
            "evaluation_hcsr_mean": summary_row.get("evaluation_hcsr_mean"),
            "agent_set_exact_match_mean": summary_row.get("agent_set_exact_match_mean"),
            "tool_set_exact_match_mean": summary_row.get("tool_set_exact_match_mean"),
            "successful_case_count": summary_row.get("successful_case_count"),
            "top_failed_rules": summary_row.get("top_failed_rules") or [],
            "top_tool_failure_types": summary_row.get("top_tool_failure_types") or [],
        }
    failed_rows = [row for row in rows if _is_failed_quality_result(row)]
    return {
        "case_count": len(rows),
        "stsr_rate": _safe_rate(len(rows) - len(failed_rows), len(rows)),
        "evaluation_hcsr_mean": _mean_number(
            _nested(row, "metrics", "evaluation_hcsr") for row in rows
        ),
        "agent_set_exact_match_mean": _mean_number(
            _nested(row, "metrics", "agent_set_exact_match") for row in rows
        ),
        "tool_set_exact_match_mean": _mean_number(
            _nested(row, "metrics", "tool_set_exact_match") for row in rows
        ),
        "successful_case_count": len(rows) - len(failed_rows),
        "top_failed_rules": _counter_payload(_failed_rules(failed_rows), limit=10),
        "top_tool_failure_types": [],
    }


def _decision_assistance_analysis(
    *,
    pilot_results: List[Dict[str, Any]],
    development_results: List[Dict[str, Any]],
    development_run_dir: Optional[Path],
) -> Dict[str, Any]:
    payload = {
        "pilot": _decision_assistance_scope(
            scope="pilot",
            results=pilot_results,
            run_dir=None,
        )
    }
    if development_run_dir is not None or development_results:
        payload["development"] = _decision_assistance_scope(
            scope="development",
            results=development_results,
            run_dir=development_run_dir,
        )
    return payload


def _decision_assistance_scope(
    *,
    scope: str,
    results: List[Dict[str, Any]],
    run_dir: Optional[Path],
) -> Dict[str, Any]:
    by_method: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for result in results:
        by_method[str(result.get("method") or "unknown")].append(result)
    methods = {
        method: _decision_assistance_method(rows)
        for method, rows in sorted(by_method.items())
    }
    return {
        "scope": scope,
        "run_dir": run_dir.as_posix() if run_dir is not None else None,
        "available": bool(results),
        "result_count": len(results),
        "methods": methods,
    }


def _decision_assistance_method(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    agent_count = 0
    llm_valid = 0
    normalizer = 0
    reused_or_synthetic = 0
    other_non_llm = 0
    invalid_llm = 0
    rows_with_agent_outputs = 0
    rows_with_programmatic = 0
    by_agent: Dict[str, Counter[str]] = defaultdict(Counter)
    by_task: Dict[str, Counter[str]] = defaultdict(Counter)

    for row in rows:
        agent_outputs = _agent_outputs_from_result(row)
        if agent_outputs:
            rows_with_agent_outputs += 1
        row_has_programmatic = False
        for agent_name, output in sorted(agent_outputs.items()):
            if not isinstance(output, dict):
                continue
            status = _agent_decision_status(agent_name, output)
            agent_count += 1
            by_agent[status["agent_name"]]["total"] += 1
            by_task[_task_type(row)]["total"] += 1
            if status["llm_valid"]:
                llm_valid += 1
                by_agent[status["agent_name"]]["llm_valid"] += 1
                by_task[_task_type(row)]["llm_valid"] += 1
            if status["deterministic_normalizer"]:
                normalizer += 1
                by_agent[status["agent_name"]]["deterministic_normalizer"] += 1
                by_task[_task_type(row)]["deterministic_normalizer"] += 1
            if status["reused_or_synthetic"]:
                reused_or_synthetic += 1
                by_agent[status["agent_name"]]["reused_or_synthetic"] += 1
                by_task[_task_type(row)]["reused_or_synthetic"] += 1
            if status["other_non_llm"]:
                other_non_llm += 1
                by_agent[status["agent_name"]]["other_non_llm"] += 1
                by_task[_task_type(row)]["other_non_llm"] += 1
            if status["invalid_llm"]:
                invalid_llm += 1
                by_agent[status["agent_name"]]["invalid_llm"] += 1
                by_task[_task_type(row)]["invalid_llm"] += 1
            if status["programmatic"]:
                row_has_programmatic = True
                by_agent[status["agent_name"]]["programmatic"] += 1
                by_task[_task_type(row)]["programmatic"] += 1
        if row_has_programmatic:
            rows_with_programmatic += 1

    programmatic = normalizer + reused_or_synthetic + other_non_llm
    return {
        "result_count": len(rows),
        "rows_with_agent_outputs_count": rows_with_agent_outputs,
        "rows_with_programmatic_decision_count": rows_with_programmatic,
        "agent_decision_output_count": agent_count,
        "llm_valid_decision_count": llm_valid,
        "deterministic_normalizer_count": normalizer,
        "reused_or_synthetic_decision_count": reused_or_synthetic,
        "other_non_llm_decision_count": other_non_llm,
        "invalid_llm_decision_count": invalid_llm,
        "programmatic_decision_count": programmatic,
        "programmatic_decision_rate": _safe_rate(programmatic, agent_count),
        "llm_valid_decision_rate": _safe_rate(llm_valid, agent_count),
        "requires_disclosure": programmatic > 0,
        "requires_ablation": programmatic > 0,
        "by_agent": _counter_mapping_payload(by_agent),
        "by_task_type": _counter_mapping_payload(by_task),
        "definition": {
            "programmatic_decision_count": (
                "deterministic_normalizer_count + reused_or_synthetic_decision_count "
                "+ other_non_llm_decision_count"
            ),
            "note": "This is separate from model/provider-level LLM fallback.",
        },
    }


def _agent_decision_status(agent_name: str, output: Dict[str, Any]) -> Dict[str, Any]:
    source = str(output.get("decision_source") or "").strip()
    reused = bool(output.get("reused")) or str(output.get("status") or "").lower() == "reused"
    deterministic = (not reused) and (
        bool(output.get("decision_fallback_used"))
        or source == "deterministic_evidence_normalizer"
        or bool(output.get("decision_normalizer_version"))
    )
    llm_valid = (
        not reused
        and source == "llm"
        and output.get("llm_decision_parse_status") == "passed"
        and output.get("llm_decision_validation_status") == "passed"
        and output.get("decision_validation_status") == "passed"
    )
    other_non_llm = bool(source and source != "llm" and not deterministic and not reused)
    programmatic = deterministic or reused or other_non_llm
    invalid_llm = bool(source == "llm" and not llm_valid)
    return {
        "agent_name": str(output.get("agent_name") or agent_name),
        "llm_valid": llm_valid,
        "deterministic_normalizer": deterministic,
        "reused_or_synthetic": reused,
        "other_non_llm": other_non_llm,
        "programmatic": programmatic,
        "invalid_llm": invalid_llm,
    }


def _agent_outputs_from_result(result: Dict[str, Any]) -> Dict[str, Any]:
    candidates = (
        _nested(result, "output", "metadata", "agent_outputs"),
        _nested(result, "output", "agent_outputs"),
        _nested(result, "raw_output", "metadata", "agent_outputs"),
        _nested(result, "raw_output", "agent_outputs"),
        _nested(result, "output", "raw_output", "metadata", "agent_outputs"),
        _nested(result, "output", "raw_output", "agent_outputs"),
    )
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate:
            return candidate
    return {}


def _m3_no_decision_normalizer_ablation_evidence(
    run_dir: Optional[Path],
) -> Dict[str, Any]:
    if run_dir is None:
        return {
            "available": False,
            "status": "missing",
            "ablation_closed": False,
            "run_dir": None,
            "path": None,
            "failed_checks": ["m3_ablation_run_dir_not_provided"],
        }
    report_path = run_dir / DAY7_M3_ABLATION_REPORT_JSON_NAME
    report = _read_json_object(report_path)
    if not report:
        return {
            "available": False,
            "status": "missing",
            "ablation_closed": False,
            "run_dir": run_dir.as_posix(),
            "path": report_path.as_posix(),
            "failed_checks": ["m3_ablation_report_missing_or_unreadable"],
        }
    summary = _dict(report.get("summary"))
    checks = _dict(report.get("checks"))
    failed_checks = _as_list(report.get("failed_checks"))
    ablation_closed = (
        report.get("status") == "passed"
        and summary.get("ablation_closed") is True
        and checks.get("manifest_decision_normalizer_disabled") is True
        and checks.get("deterministic_normalizer_not_used") is True
        and checks.get("agent_outputs_do_not_enable_normalizer") is True
    )
    return {
        "available": True,
        "status": report.get("status"),
        "ablation_closed": ablation_closed,
        "run_dir": run_dir.as_posix(),
        "path": report_path.as_posix(),
        "failed_checks": failed_checks,
        "summary": summary,
        "checks": checks,
        "controlled_change": _dict(report.get("controlled_change")),
    }


def _m3_ablation_closed(evidence: Dict[str, Any]) -> bool:
    return bool(evidence.get("available") and evidence.get("ablation_closed"))


def _m3_method_readiness(
    *,
    pilot_analysis: Dict[str, Any],
    development_readiness: Dict[str, Any],
    decision_assistance: Dict[str, Any],
    m3_ablation_evidence: Dict[str, Any],
) -> Dict[str, Any]:
    reasons: Counter[str] = Counter()
    if pilot_analysis.get("systemic_failure"):
        reasons["pilot_m3_systemic_failure"] += 1
    for reason in _as_dict_list(development_readiness.get("blocking_reasons")):
        reason_id = str(reason.get("id") or "")
        if reason_id:
            reasons[reason_id] += int(reason.get("count") or 1)

    preferred_m3_assistance = _dict(
        _nested(decision_assistance, "development", "methods", "adaptive_multi_agent")
        or _nested(decision_assistance, "pilot", "methods", "adaptive_multi_agent")
    )
    programmatic_count = int(_number(preferred_m3_assistance.get("programmatic_decision_count")) or 0)
    ablation_closed = _m3_ablation_closed(m3_ablation_evidence)
    ablation_required = programmatic_count > 0 and not ablation_closed
    if ablation_required:
        reasons["m3_programmatic_decision_ablation_missing"] += 1

    quality_blocked = bool(
        pilot_analysis.get("systemic_failure")
        or development_readiness.get("formal_run_blocked")
    )
    return {
        "quality_formal_run_blocked": quality_blocked,
        "ablation_required": ablation_required,
        "ablation_closed": ablation_closed,
        "ablation_status": m3_ablation_evidence.get("status"),
        "ablation_run_dir": m3_ablation_evidence.get("run_dir"),
        "formal_run_blocked": bool(reasons),
        "blocking_reasons": _counter_payload(reasons, limit=10),
        "programmatic_decision_count": preferred_m3_assistance.get("programmatic_decision_count"),
        "agent_decision_output_count": preferred_m3_assistance.get("agent_decision_output_count"),
        "programmatic_decision_rate": preferred_m3_assistance.get("programmatic_decision_rate"),
        "llm_valid_decision_count": preferred_m3_assistance.get("llm_valid_decision_count"),
        "development_available": development_readiness.get("available"),
        "interpretation": (
            "M3 method issues remain open; formal paper run should wait for repair/disclosure/ablation."
            if reasons
            else "M3 method issues are not blocked by current pilot/development/decision-assistance evidence."
        ),
    }


def _method_quality_summary(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_method: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for result in results:
        by_method[str(result.get("method") or "unknown")].append(result)
    payload: Dict[str, Any] = {}
    for method, rows in sorted(by_method.items()):
        failed = [row for row in rows if _is_failed_quality_result(row)]
        payload[method] = {
            "label": _METHOD_LABELS.get(method, method),
            "quality_unit_count": len(rows),
            "failed_quality_unit_count": len(failed),
            "failure_rate": _safe_rate(len(failed), len(rows)),
            "status_counts": dict(Counter(str(row.get("status") or "unknown") for row in rows)),
            "top_failed_rules": _counter_payload(_failed_rules(failed), limit=10),
            "top_failure_reasons": _counter_payload(_failure_reasons(failed), limit=10),
        }
    return payload


def _runtime_audit(manifest: Dict[str, Any], llm_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    runtime = _dict(manifest.get("runtime_config"))
    expected = {
        "model": runtime.get("model") or manifest.get("model"),
        "temperature": runtime.get("temperature") if "temperature" in runtime else manifest.get("temperature"),
        "max_tokens": runtime.get("max_tokens") if "max_tokens" in runtime else manifest.get("max_tokens"),
        "timeout_seconds": runtime.get("timeout_seconds")
        if "timeout_seconds" in runtime
        else manifest.get("timeout_seconds"),
        "retry_max_attempts": runtime.get("retry_max_attempts")
        if "retry_max_attempts" in runtime
        else manifest.get("retry_max_attempts"),
        "reasoning_effort": runtime.get("reasoning_effort")
        if "reasoning_effort" in runtime
        else manifest.get("reasoning_effort"),
    }
    mismatches = []
    retry_values = set()
    option_values: Dict[str, set[str]] = defaultdict(set)
    for index, call in enumerate(llm_calls):
        options = _dict(call.get("request_options"))
        retry = _dict(call.get("retry"))
        observed = {
            "model": options.get("model") or call.get("model"),
            "temperature": options.get("temperature") if "temperature" in options else call.get("temperature"),
            "max_tokens": options.get("max_tokens") if "max_tokens" in options else call.get("max_tokens"),
            "timeout_seconds": options.get("timeout_seconds")
            if "timeout_seconds" in options
            else call.get("timeout_seconds"),
            "retry_max_attempts": retry.get("max_attempts")
            or options.get("retry_max_attempts")
            or call.get("retry_max_attempts"),
            "reasoning_effort": options.get("reasoning_effort")
            if "reasoning_effort" in options
            else call.get("reasoning_effort"),
        }
        for key, value in observed.items():
            if value is not None:
                option_values[key].add(str(value))
            if key == "retry_max_attempts" and value is not None:
                retry_values.add(str(value))
            if expected.get(key) is not None and not _same_value(expected.get(key), value):
                mismatches.append(
                    {
                        "call_index": index,
                        "field": key,
                        "manifest_value": expected.get(key),
                        "call_value": value,
                    }
                )
    return {
        "manifest_runtime": expected,
        "llm_call_count": len(llm_calls),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:20],
        "consistent_with_manifest": bool(llm_calls) and not mismatches,
        "request_option_values": {key: sorted(values) for key, values in sorted(option_values.items())},
        "retry_max_attempts_values": sorted(retry_values),
    }


def _paper_use_policy(m3_method_readiness: Dict[str, Any]) -> Dict[str, Any]:
    if m3_method_readiness.get("formal_run_blocked"):
        return {
            "summary": (
                "当前 Day7 pilot/dev 只能作为链路审计和失败诊断证据；"
                "方法质量、程序性决策补全披露和无补全消融未完成前，不能作为论文正式效果结论。"
            ),
            "allowed_uses": [
                "说明实验链路已能生成真实请求级证据",
                "列出开发期修正、剩余方法问题和程序性补全触发比例",
                "指导 Day8 小规模修正回归和消融实验设计",
            ],
            "forbidden_uses": [
                "声称 M3 优于 M2",
                "把 pilot/dev 指标写成正式实验结论",
                "跳过 M3-no-decision-normalizer 消融直接扩跑正式集",
            ],
        }
    return {
        "summary": "当前 Day7 pilot/dev 未发现阻断性 M3 方法问题；仍只能作为开发证据，不替代正式论文结论。",
        "allowed_uses": ["链路审计", "扩跑前健康检查", "消融设计依据"],
        "forbidden_uses": ["替代正式测试集结论"],
    }


def _issue(
    *,
    issue_id: str,
    category: str,
    severity: str,
    status: str,
    summary: str,
    before_run: str,
    modification: str,
    after_run: str,
    evidence: Dict[str, Any],
    regression_tests: List[str],
    paper_risk: str,
    next_action: str,
) -> Dict[str, Any]:
    return {
        "issue_id": issue_id,
        "category": category,
        "severity": severity,
        "status": status,
        "summary": summary,
        "before_run": before_run,
        "modification": modification,
        "after_run": after_run,
        "evidence": evidence,
        "regression_tests": regression_tests,
        "paper_risk": paper_risk,
        "next_action": next_action,
    }


def _attach_to_manifest(
    *,
    run_dir: Path,
    json_path: Path,
    markdown_path: Path,
    report: Dict[str, Any],
) -> None:
    manifest_path = run_dir / "experiment_manifest.json"
    manifest = _read_json_object(manifest_path)
    if not manifest:
        return
    results = _dict(manifest.get("results"))
    results.update(
        {
            "day7_issue_report_json": json_path.as_posix(),
            "day7_fix_report_md": markdown_path.as_posix(),
        }
    )
    manifest["results"] = results
    manifest["day7_fix_report"] = {
        "schema_version": DAY7_FIX_REPORT_SCHEMA_VERSION,
        "status": report.get("status"),
        "failed_checks": report.get("failed_checks") or [],
        "issue_counts": report.get("issue_counts"),
        "m3_systemic_failure": _nested(
            report,
            "m3_systemic_failure_analysis",
            "systemic_failure",
        ),
        "m3_method_formal_run_blocked": _nested(
            report,
            "m3_method_readiness",
            "formal_run_blocked",
        ),
        "m3_programmatic_decision_rate": _nested(
            report,
            "m3_method_readiness",
            "programmatic_decision_rate",
        ),
        "json": json_path.as_posix(),
        "markdown": markdown_path.as_posix(),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _artifact_paths(run_dir: Path, artifacts: Dict[str, Any]) -> Dict[str, str]:
    payload = {"run_dir": run_dir.as_posix()}
    for key, value in _dict(artifacts.get("paths")).items():
        path = Path(value)
        if path.exists():
            payload[key] = path.as_posix()
    return payload


def _quality_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [result for result in results if result.get("target_turn") is not False]


def _is_failed_quality_result(result: Dict[str, Any]) -> bool:
    metrics = _dict(result.get("metrics"))
    return metrics.get("stsr") is not True


def _task_type(result: Dict[str, Any]) -> str:
    return str(
        _nested(result, "evaluation", "task_type")
        or _nested(result, "output", "task_type")
        or _nested(result, "raw_output", "task_type")
        or "unknown"
    )


def _failed_rules(results: Iterable[Dict[str, Any]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for result in results:
        counter.update(_as_text_list(_nested(result, "metrics", "evaluation_failed_rule_ids")))
    return counter


def _failure_reasons(results: Iterable[Dict[str, Any]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for result in results:
        source = _dict(result.get("raw_output")) or _dict(result.get("output"))
        reason = _nested(source, "metadata", "structured_llm_output", "failure_reason")
        if reason:
            counter[str(reason)] += 1
        for agent_output in _dict(source.get("agent_outputs")).values():
            if isinstance(agent_output, dict) and agent_output.get("error"):
                counter[str(agent_output.get("error"))] += 1
    return counter


def _counter_payload(counter: Counter[str], *, limit: int) -> List[Dict[str, Any]]:
    return [{"id": key, "count": count} for key, count in counter.most_common(limit)]


def _counter_mapping_payload(counters: Dict[str, Counter[str]]) -> Dict[str, Dict[str, int]]:
    return {
        key: {name: int(count) for name, count in sorted(counter.items())}
        for key, counter in sorted(counters.items())
    }


def _mean_number(values: Iterable[Any]) -> Optional[float]:
    numbers = [_number(value) for value in values]
    clean = [value for value in numbers if value is not None]
    if not clean:
        return None
    return round(sum(clean) / len(clean), 4)


def _load_traces_from_results(run_dir: Path, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    traces: List[Dict[str, Any]] = []
    for result in results:
        trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
        if trace:
            traces.append(trace)
            continue
        path = _resolve_path(run_dir, result.get("trace_file"))
        if path:
            loaded = _read_jsonl_first(path)
            if loaded:
                traces.append(loaded)
    return traces


def _resolve_path(run_dir: Path, value: Any) -> Optional[Path]:
    if not value:
        return None
    path = Path(str(value))
    if path.is_absolute():
        return path
    candidates = [run_dir / path, Path.cwd() / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return path


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


def _as_dict_list(value: Any) -> List[Dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _as_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def _as_text_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]
    return [str(value)]


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _safe_rate(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _same_value(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    left_number = _number(left)
    right_number = _number(right)
    if left_number is not None and right_number is not None:
        return abs(left_number - right_number) < 1e-9
    return str(left) == str(right)


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


def _fmt_counter(value: Any) -> str:
    rows = _as_dict_list(value)
    return ", ".join(f"{row.get('id')}({row.get('count')})" for row in rows[:5])


def _md(value: Any) -> str:
    text = str(value or "")
    return text.replace("|", "\\|").replace("\n", " ")
