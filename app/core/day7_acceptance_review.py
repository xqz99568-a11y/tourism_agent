"""Day 7 first-round review and stage acceptance package.

This module is deliberately offline-only.  It turns the existing Day 7
evidence into reviewer-facing artifacts:

- a pre-filled annotation review sheet;
- a 100-case human-readable review table;
- a cross-dataset duplicate/leakage report;
- an offline feasibility report;
- a Day 7 stage acceptance report;
- a Day 7 delivery pack/report for handing the project to Day 8.

The package is a stage acceptance artifact, not a final paper-result package.
It must not call LLMs and must not imply that the low-quality Day 7 development
run can be used as final academic evidence.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
from contextlib import contextmanager
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence

from app.core.benchmark_dataset_validator import build_benchmark_dataset_quality_report
from app.core.day7_cost_forecast import DAY7_COST_FORECAST_JSON_NAME
from app.core.day7_dev_experiment_gate import DAY7_DEV_EXPERIMENT_GATE_NAME
from app.core.day7_m3_ablation import (
    DAY7_M3_ABLATION_REPORT_JSON_NAME,
    DAY7_M3_ABLATION_REPORT_MD_NAME,
)
from app.core.day7_test_draft import (
    DEFAULT_EXPECTED_CASE_COUNT,
    DEFAULT_EXPECTED_SCENARIO_CASE_COUNT,
    DEFAULT_EXPECTED_TURN_COUNT,
    TEST_DRAFT_CASE_TASK_QUOTAS,
)
from app.core.fixed_data import canonical_json_sha256
from app.core.formal_experiment_preflight import (
    DEFAULT_FORMAL_METHOD_ORDER_SEED,
    build_formal_preflight_report,
    load_benchmark_document,
)


DAY7_ACCEPTANCE_REVIEW_SCHEMA_VERSION = "ctp-day7-acceptance-review-v1"
DAY7_STAGE_DELIVERY_PACK_SCHEMA_VERSION = "ctp-day7-stage-delivery-pack-v1"

DAY7_ANNOTATION_REVIEW_JSON_NAME = "day7_annotation_review_round1.json"
DAY7_ANNOTATION_REVIEW_CSV_NAME = "day7_annotation_review_round1.csv"
DAY7_CASE_REVIEW_TABLE_MD_NAME = "day7_case_review_table.md"
DAY7_LEAKAGE_REPORT_JSON_NAME = "day7_cross_dataset_leakage_report.json"
DAY7_LEAKAGE_REPORT_MD_NAME = "day7_cross_dataset_leakage_report.md"
DAY7_OFFLINE_FEASIBILITY_JSON_NAME = "day7_offline_feasibility_report.json"
DAY7_OFFLINE_FEASIBILITY_MD_NAME = "day7_offline_feasibility_report.md"
DAY7_ACCEPTANCE_REPORT_MD_NAME = "Day7_acceptance_report.md"
DAY7_DELIVERY_PACK_JSON_NAME = "day7_delivery_pack.json"
DAY7_DELIVERY_REPORT_MD_NAME = "day7_delivery_report.md"
DAY7_ARTIFACT_SHA256_JSON_NAME = "day7_artifact_sha256.json"

DEFAULT_TEST_DRAFT_PATH = Path("experiments") / "ctp120_test_draft.json"
DEFAULT_QUOTA_REPORT_PATH = Path("experiments") / "ctp120_test_draft_quota_report.json"
DEFAULT_FEASIBILITY_REPORT_PATH = (
    Path("experiments") / "ctp120_test_draft_feasibility_report.json"
)
DEFAULT_BENCHMARK_MANIFEST_PATH = Path("experiments") / "benchmark.json"
DEFAULT_PILOT_RESULTS_ROOT = Path("experiments") / "results" / "day7_pilot"
DEFAULT_DEV_RESULTS_ROOT = Path("experiments") / "results" / "day7_dev"
DEFAULT_ACCEPTANCE_ROOT = Path("experiments") / "results" / "day7_acceptance"
DEFAULT_DOCS_ACCEPTANCE_REPORT_PATH = Path("docs") / DAY7_ACCEPTANCE_REPORT_MD_NAME
AUDITED_REVIEW_PARSE_SLOT_KEYS = {
    "destination",
    "start_date",
    "duration_days",
    "people_count",
    "budget_amount",
}
DEFAULT_METHODS = (
    "llm_direct",
    "single_agent",
    "fixed_multi_agent",
    "adaptive_multi_agent",
)
PREFLIGHT_RUNTIME_DEFAULTS = {
    "EXPERIMENT_STRICT_MODE": "true",
    "EXPERIMENT_DISABLE_CACHE": "true",
    "TRACE_SAVE_USER_MESSAGE": "false",
    "LLM_TEMPERATURE": "0",
    "LLM_MAX_TOKENS": "4096",
    "LLM_TIMEOUT": "60",
    "LLM_RETRY_MAX_ATTEMPTS": "3",
    "EXPERIMENT_RESULT_HARD_TIMEOUT_SECONDS": "720",
    "LLM_REASONING_EFFORT": "minimal",
    "EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER": "true",
}

HUMAN_REVIEW_FIELDS = (
    "human_review_status",
    "human_reviewer",
    "human_decision",
    "human_notes",
)
APPROVED_HUMAN_REVIEW_STATUSES = {
    "approved",
    "accepted",
    "confirmed",
    "reviewed",
    "reviewed_passed",
    "pass",
    "passed",
    "ok",
    "已确认",
    "已通过",
    "通过",
    "确认",
}
APPROVED_HUMAN_DECISIONS = {
    "approved",
    "accepted",
    "confirm",
    "confirmed",
    "pass",
    "passed",
    "gold_ok",
    "gold_correct",
    "minor_fix_applied",
    "ok",
    "同意",
    "接受",
    "通过",
    "确认",
    "金标正确",
    "已修正",
}
BLOCKING_HUMAN_REVIEW_STATUSES = {
    "needs_revision",
    "rejected",
    "failed",
    "需修改",
    "拒绝",
    "不通过",
}
BLOCKING_HUMAN_DECISIONS = {
    "reject",
    "rejected",
    "fail",
    "failed",
    "needs_revision",
    "needs_fix",
    "revise",
    "拒绝",
    "不通过",
    "需修改",
}
DEFAULT_DAY7_FREEZE_TAG_NAME = "day7-acceptance-20260801"
REQUIRED_METHOD_REAL_FAILURE_ISSUE_IDS = (
    "METHOD-001",
    "METHOD-002",
    "METHOD-003",
)


def build_day7_acceptance_pack(
    *,
    test_draft_path: str | Path = DEFAULT_TEST_DRAFT_PATH,
    quota_report_path: str | Path = DEFAULT_QUOTA_REPORT_PATH,
    feasibility_report_path: str | Path = DEFAULT_FEASIBILITY_REPORT_PATH,
    benchmark_manifest_path: str | Path = DEFAULT_BENCHMARK_MANIFEST_PATH,
    annotation_review_path: str | Path | None = None,
    pilot_run_dir: str | Path | None = None,
    dev_run_dir: str | Path | None = None,
    expected_case_count: int = DEFAULT_EXPECTED_CASE_COUNT,
    expected_turn_count: int = DEFAULT_EXPECTED_TURN_COUNT,
    expected_scenario_case_count: int = DEFAULT_EXPECTED_SCENARIO_CASE_COUNT,
    required_methods: Optional[Iterable[str]] = None,
    run_id: str | None = None,
    freeze_tag_name: str | None = None,
) -> Dict[str, Any]:
    """Build the complete Day 7 stage acceptance package in memory."""
    created_at = datetime.now(timezone.utc).isoformat()
    run_id = run_id or f"day7_acceptance_{_timestamp_for_id(created_at)}"
    methods = _normalize_methods(required_methods or DEFAULT_METHODS)

    dataset_path = Path(test_draft_path)
    quota_path = Path(quota_report_path)
    feasibility_path = Path(feasibility_report_path)
    benchmark_path = Path(benchmark_manifest_path)
    pilot_root = Path(pilot_run_dir) if pilot_run_dir is not None else _latest_run_dir(
        DEFAULT_PILOT_RESULTS_ROOT,
        required_file="day7_pilot_gate.json",
    )
    dev_root = Path(dev_run_dir) if dev_run_dir is not None else _latest_run_dir(
        DEFAULT_DEV_RESULTS_ROOT,
        required_file=DAY7_DEV_EXPERIMENT_GATE_NAME,
    )

    document, cases = load_benchmark_document(dataset_path)
    comparison_splits = _load_comparison_splits(dataset_path, document)
    quality_report = build_benchmark_dataset_quality_report(
        document=document,
        cases=cases,
        expected_case_count=expected_case_count,
        strict_formal=True,
        comparison_splits=comparison_splits,
    )
    with _temporary_env_defaults(PREFLIGHT_RUNTIME_DEFAULTS):
        benchmark_preflight = build_formal_preflight_report(
            benchmark_path=benchmark_path,
            output_dir=DEFAULT_ACCEPTANCE_ROOT / "_preflight_probe",
            run_id=f"{run_id}_preflight_probe",
            methods=methods,
            repeats=1,
            method_order_seed=DEFAULT_FORMAL_METHOD_ORDER_SEED,
            expected_case_count=expected_case_count,
            require_llm_config=False,
            strict_formal=True,
            require_day8_delivery_pack=False,
            require_clean_git=False,
        )

    units = _flatten_case_units(cases)
    quality_units = _quality_units_by_label(quality_report)
    generated_annotation_rows = _annotation_review_rows(units, quality_units)
    annotation_rows, annotation_source = _load_annotation_review_overlay(
        annotation_review_path,
        generated_annotation_rows,
    )
    annotation_summary = _annotation_review_completion(
        annotation_rows,
        expected_turn_count=expected_turn_count,
        source_errors=annotation_source.get("errors") or [],
    )
    case_rows = _case_review_rows(cases, annotation_rows)
    leakage_report = _cross_dataset_leakage_report(
        quality_report=quality_report,
        comparison_splits=comparison_splits,
        dataset_path=dataset_path,
    )
    feasibility_report = _offline_feasibility_review(
        quality_report=quality_report,
        saved_feasibility_report=_read_json_object(feasibility_path),
    )
    evidence = _day7_evidence_summary(
        quota_path=quota_path,
        feasibility_path=feasibility_path,
        benchmark_path=benchmark_path,
        pilot_run_dir=pilot_root,
        dev_run_dir=dev_root,
    )
    git_snapshot = _git_snapshot(freeze_tag_name=freeze_tag_name)
    acceptance = _acceptance_decision(
        quality_report=quality_report,
        leakage_report=leakage_report,
        feasibility_report=feasibility_report,
        benchmark_preflight=benchmark_preflight,
        evidence=evidence,
        annotation_rows=annotation_rows,
        annotation_summary=annotation_summary,
        case_rows=case_rows,
        git_snapshot=git_snapshot,
        expected_case_count=expected_case_count,
        expected_turn_count=expected_turn_count,
        expected_scenario_case_count=expected_scenario_case_count,
        required_method_count=len(methods),
    )
    source_artifacts = _source_artifact_inventory(
        dataset_path=dataset_path,
        quota_path=quota_path,
        feasibility_path=feasibility_path,
        benchmark_path=benchmark_path,
        pilot_run_dir=pilot_root,
        dev_run_dir=dev_root,
    )
    delivery_pack = _stage_delivery_pack(
        created_at=created_at,
        run_id=run_id,
        acceptance=acceptance,
        evidence=evidence,
        source_artifacts=source_artifacts,
        git_snapshot=git_snapshot,
    )
    return {
        "schema_version": DAY7_ACCEPTANCE_REVIEW_SCHEMA_VERSION,
        "created_at": created_at,
        "run_id": run_id,
        "dataset": {
            "path": dataset_path.as_posix(),
            "dataset_id": _document_value(document, "dataset_id"),
            "dataset_version": _document_value(document, "dataset_version"),
            "split": _document_value(document, "split"),
            "sha256": canonical_json_sha256(document),
        },
        "expected": {
            "case_count": expected_case_count,
            "turn_count": expected_turn_count,
            "scenario_case_count": expected_scenario_case_count,
            "raw_formal_result_count": expected_turn_count * len(methods),
            "methods": methods,
            "case_task_quotas": dict(TEST_DRAFT_CASE_TASK_QUOTAS),
        },
        "actual": {
            "case_count": len(cases),
            "turn_count": len(units),
            "scenario_case_count": sum(1 for case in cases if _is_scenario_case(case)),
            "annotation_review_row_count": len(annotation_rows),
            "case_review_row_count": len(case_rows),
            "machine_needs_attention_row_count": annotation_summary.get(
                "machine_needs_attention_count"
            ),
            "pending_human_confirmation_row_count": annotation_summary.get(
                "pending_human_confirmation_count"
            ),
        },
        "acceptance": acceptance,
        "quality_report": _compact_quality_report(quality_report),
        "benchmark_preflight": _compact_preflight_report(benchmark_preflight),
        "annotation_review": {
            "schema_version": "ctp-day7-annotation-review-round1-v1",
            "round": 1,
            "human_review_completed": annotation_summary.get("human_review_completed"),
            "status": annotation_summary.get("status"),
            "source": annotation_source,
            "summary": annotation_summary,
            "row_count": len(annotation_rows),
            "rows": annotation_rows,
            "policy": {
                "do_not_expose_gold_to_generation": True,
                "manual_columns_are_blank_by_design": True,
                "purpose": "让人工逐轮确认任务类型、城市、硬约束、changed/preserved slots 和可行性。",
            },
        },
        "case_review": {
            "schema_version": "ctp-day7-case-review-table-v1",
            "status": "ready",
            "row_count": len(case_rows),
            "rows": case_rows,
        },
        "cross_dataset_leakage": leakage_report,
        "offline_feasibility": feasibility_report,
        "day7_evidence": evidence,
        "git_freeze_snapshot": git_snapshot,
        "source_artifacts": source_artifacts,
        "delivery_pack": delivery_pack,
        "writing_boundaries": _writing_boundaries(),
    }


def write_day7_acceptance_pack(
    *,
    output_dir: str | Path,
    docs_report_path: str | Path | None = DEFAULT_DOCS_ACCEPTANCE_REPORT_PATH,
    test_draft_path: str | Path = DEFAULT_TEST_DRAFT_PATH,
    quota_report_path: str | Path = DEFAULT_QUOTA_REPORT_PATH,
    feasibility_report_path: str | Path = DEFAULT_FEASIBILITY_REPORT_PATH,
    benchmark_manifest_path: str | Path = DEFAULT_BENCHMARK_MANIFEST_PATH,
    annotation_review_path: str | Path | None = None,
    pilot_run_dir: str | Path | None = None,
    dev_run_dir: str | Path | None = None,
    expected_case_count: int = DEFAULT_EXPECTED_CASE_COUNT,
    expected_turn_count: int = DEFAULT_EXPECTED_TURN_COUNT,
    expected_scenario_case_count: int = DEFAULT_EXPECTED_SCENARIO_CASE_COUNT,
    required_methods: Optional[Iterable[str]] = None,
    run_id: str | None = None,
    freeze_tag_name: str | None = None,
) -> Dict[str, Any]:
    """Write all Day 7 acceptance artifacts and return a compact payload."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    pack = build_day7_acceptance_pack(
        test_draft_path=test_draft_path,
        quota_report_path=quota_report_path,
        feasibility_report_path=feasibility_report_path,
        benchmark_manifest_path=benchmark_manifest_path,
        annotation_review_path=annotation_review_path,
        pilot_run_dir=pilot_run_dir,
        dev_run_dir=dev_run_dir,
        expected_case_count=expected_case_count,
        expected_turn_count=expected_turn_count,
        expected_scenario_case_count=expected_scenario_case_count,
        required_methods=required_methods,
        run_id=run_id,
        freeze_tag_name=freeze_tag_name,
    )

    paths = {
        "annotation_review_json": output / DAY7_ANNOTATION_REVIEW_JSON_NAME,
        "annotation_review_csv": output / DAY7_ANNOTATION_REVIEW_CSV_NAME,
        "case_review_table_md": output / DAY7_CASE_REVIEW_TABLE_MD_NAME,
        "cross_dataset_leakage_json": output / DAY7_LEAKAGE_REPORT_JSON_NAME,
        "cross_dataset_leakage_md": output / DAY7_LEAKAGE_REPORT_MD_NAME,
        "offline_feasibility_json": output / DAY7_OFFLINE_FEASIBILITY_JSON_NAME,
        "offline_feasibility_md": output / DAY7_OFFLINE_FEASIBILITY_MD_NAME,
        "acceptance_report_md": output / DAY7_ACCEPTANCE_REPORT_MD_NAME,
        "day7_delivery_pack_json": output / DAY7_DELIVERY_PACK_JSON_NAME,
        "day7_delivery_report_md": output / DAY7_DELIVERY_REPORT_MD_NAME,
    }
    artifact_hashes_path = output / DAY7_ARTIFACT_SHA256_JSON_NAME
    pack["post_write_artifact_hashes_path"] = artifact_hashes_path.as_posix()
    pack["delivery_pack"]["post_write_artifact_hashes_path"] = artifact_hashes_path.as_posix()
    _write_json(paths["annotation_review_json"], pack["annotation_review"])
    _write_csv(paths["annotation_review_csv"], pack["annotation_review"]["rows"])
    _write_text(paths["case_review_table_md"], render_case_review_table(pack))
    _write_json(paths["cross_dataset_leakage_json"], pack["cross_dataset_leakage"])
    _write_text(paths["cross_dataset_leakage_md"], render_cross_dataset_leakage_report(pack))
    _write_json(paths["offline_feasibility_json"], pack["offline_feasibility"])
    _write_text(paths["offline_feasibility_md"], render_offline_feasibility_report(pack))

    generated_artifacts = _generated_artifact_inventory(paths)
    pack["generated_artifacts"] = generated_artifacts
    pack["delivery_pack"]["generated_artifacts"] = generated_artifacts
    pack["delivery_pack"]["outputs"] = {
        key: path.as_posix() for key, path in paths.items()
    }

    _write_text(paths["acceptance_report_md"], render_day7_acceptance_report(pack))
    _write_text(paths["day7_delivery_report_md"], render_day7_stage_delivery_report(pack))
    _write_json(paths["day7_delivery_pack_json"], pack["delivery_pack"])

    generated_artifacts = _generated_artifact_inventory(paths)
    pack["generated_artifacts"] = generated_artifacts
    pack["delivery_pack"]["generated_artifacts"] = generated_artifacts
    _write_json(paths["day7_delivery_pack_json"], pack["delivery_pack"])
    _write_text(paths["acceptance_report_md"], render_day7_acceptance_report(pack))
    _write_text(paths["day7_delivery_report_md"], render_day7_stage_delivery_report(pack))

    docs_path: Path | None = None
    if docs_report_path is not None:
        docs_path = Path(docs_report_path)
        _write_text(docs_path, render_day7_acceptance_report(pack))

    post_write_paths = {key: path for key, path in paths.items()}
    if docs_path is not None:
        post_write_paths["docs_acceptance_report_md"] = docs_path
    _write_json(
        artifact_hashes_path,
        _post_write_artifact_hashes(
            run_id=str(pack.get("run_id") or ""),
            paths=post_write_paths,
        ),
    )

    acceptance = _dict(pack.get("acceptance"))
    artifact_paths = {key: path.as_posix() for key, path in paths.items()}
    artifact_paths["artifact_sha256_json"] = artifact_hashes_path.as_posix()
    return {
        "status": "completed",
        "acceptance_status": acceptance.get("status"),
        "ready_for_day8": acceptance.get("ready_for_day8"),
        "prepared_for_manual_review": acceptance.get("prepared_for_manual_review"),
        "paper_claims_allowed": acceptance.get("paper_claims_allowed"),
        "failed_checks": acceptance.get("failed_checks") or [],
        "run_id": pack.get("run_id"),
        "output_dir": output.as_posix(),
        "docs_report": docs_path.as_posix() if docs_path else None,
        "artifacts": artifact_paths,
        "pack": pack,
    }


def render_day7_acceptance_report(pack: Mapping[str, Any]) -> str:
    """Render the human-facing Day 7 acceptance report."""
    acceptance = _dict(pack.get("acceptance"))
    actual = _dict(pack.get("actual"))
    expected = _dict(pack.get("expected"))
    leakage = _dict(pack.get("cross_dataset_leakage"))
    feasibility = _dict(pack.get("offline_feasibility"))
    evidence = _dict(pack.get("day7_evidence"))
    dev = _dict(evidence.get("development_run"))
    pilot = _dict(evidence.get("pilot_run"))
    cost = _dict(evidence.get("cost_forecast"))
    fix = _dict(evidence.get("fix_report"))
    m3_ablation = _dict(evidence.get("m3_ablation"))
    manual = _dict(acceptance.get("manual_review_summary"))
    git_freeze = _dict(acceptance.get("git_freeze_summary"))
    git_snapshot = _dict(pack.get("git_freeze_snapshot"))
    generated = _as_dict_list(pack.get("generated_artifacts"))

    lines = [
        "# Day 7 第一轮复核与阶段验收报告",
        "",
        "## 总结论",
        "",
        f"- acceptance_status: `{acceptance.get('status')}`",
        f"- ready_for_day8: `{acceptance.get('ready_for_day8')}`",
        f"- prepared_for_manual_review: `{acceptance.get('prepared_for_manual_review')}`",
        f"- human_review_completed: `{acceptance.get('human_review_completed')}`",
        f"- paper_claims_allowed: `{acceptance.get('paper_claims_allowed')}`",
        f"- failed_checks: `{acceptance.get('failed_checks') or []}`",
        f"- preparation_failed_checks: `{acceptance.get('preparation_failed_checks') or []}`",
        f"- final_acceptance_failed_checks: `{acceptance.get('final_acceptance_failed_checks') or []}`",
        f"- 解释：{acceptance.get('interpretation')}",
        "",
        "这份报告把“材料已准备”和“最终验收通过”分开记录；只有人工复核、机器异常处理、方法问题关闭和 Git 冻结全部满足时，才允许写 accepted_for_day8。",
        "",
        "## 核心规模",
        "",
        "| 项目 | 目标 | 实际 |",
        "|---|---:|---:|",
        f"| 统计案例 | {expected.get('case_count')} | {actual.get('case_count')} |",
        f"| 实际对话轮次 | {expected.get('turn_count')} | {actual.get('turn_count')} |",
        f"| 两轮场景 | {expected.get('scenario_case_count')} | {actual.get('scenario_case_count')} |",
        f"| 复核表行数 | {expected.get('turn_count')} | {actual.get('annotation_review_row_count')} |",
        f"| 逐案例审查行数 | {expected.get('case_count')} | {actual.get('case_review_row_count')} |",
        "",
        "## Day 7 证据链",
        "",
        "| 证据 | 状态 | 关键数字 | 路径 |",
        "|---|---|---|---|",
        _evidence_row(
            "8 条真实烟雾实验",
            pilot.get("status"),
            f"{pilot.get('raw_result_count')} rows / {pilot.get('trace_count')} traces",
            pilot.get("run_dir"),
        ),
        _evidence_row(
            "20 条开发集真实实验",
            dev.get("status"),
            (
                f"{dev.get('raw_result_count')} rows / {dev.get('trace_count')} traces; "
                f"max_tokens_ok={dev.get('runtime_matches_day7_max_tokens_protocol')}; "
                f"cap_rate={dev.get('completion_token_cap_hit_rate')}"
            ),
            dev.get("run_dir"),
        ),
        _evidence_row(
            "成本预测与模型冻结",
            cost.get("status"),
            (
                f"formal≈{_formal_cost_display(cost)} CNY; "
                f"rerun_required={cost.get('rerun_required')}"
            ),
            cost.get("path"),
        ),
        _evidence_row(
            "M3 no-normalizer 消融证据",
            m3_ablation.get("status"),
            (
                f"report={m3_ablation.get('report_status')}; "
                f"manifest_hash_ok={m3_ablation.get('hash_consistent')}"
            ),
            m3_ablation.get("report_json"),
        ),
        _evidence_row(
            "测试集配额/中文/重复门禁",
            _nested(pack, "quality_report", "status"),
            f"{actual.get('case_count')} cases / {actual.get('turn_count')} turns",
            _nested(pack, "dataset", "path"),
        ),
        "",
        "## 第一轮标注复核",
        "",
        "- 已生成逐轮复核表：`day7_annotation_review_round1.csv` 与 `day7_annotation_review_round1.json`。",
        "- 复核表已经由机器预填任务类型、城市、硬约束、解析槽位、changed_slots、preserved_slots 和可行性状态。",
        f"- human_review_completed: `{manual.get('human_review_completed')}`",
        f"- pending_human_confirmation_count: `{manual.get('pending_human_confirmation_count')}`",
        f"- machine_needs_attention_count: `{manual.get('machine_needs_attention_count')}`",
        f"- unresolved_machine_attention_count: `{manual.get('unresolved_machine_attention_count')}`",
        f"- rejected_or_needs_revision_count: `{manual.get('rejected_or_needs_revision_count')}`",
        f"- unique_human_reviewer_count: `{manual.get('unique_human_reviewer_count')}`",
        f"- same_manual_values_across_all_rows: `{manual.get('same_manual_values_across_all_rows')}`",
        f"- authenticity_verification_status: `{manual.get('authenticity_verification_status')}`",
        "- 说明：系统只能验证复核表是否填写完整，不能证明审核人是否逐行肉眼检查；如果 130 行使用相同审核人、结论和备注，论文中只有在审核人确实逐行看过时，才能写“逐例人工复核”。",
        "- 如果没有提供已人工确认的 `--annotation-review` 文件，复核表会保持 pending；系统不会冒充人工签字。",
        "",
        "## 泄漏与重复检查",
        "",
        f"- leakage_status: `{leakage.get('status')}`",
        f"- internal_duplicate_count: `{_nested(leakage, 'counts', 'internal_duplicate_count')}`",
        f"- cross_split_duplicate_count: `{_nested(leakage, 'counts', 'cross_split_duplicate_count')}`",
        f"- near_duplicate_count: `{_nested(leakage, 'counts', 'near_duplicate_count')}`",
        "",
        "## 离线可行性检查",
        "",
        f"- feasibility_status: `{feasibility.get('status')}`",
        f"- checked_tourism_unit_count: `{feasibility.get('checked_tourism_unit_count')}`",
        f"- failed_tourism_unit_count: `{feasibility.get('failed_tourism_unit_count')}`",
        "",
        "## Git 冻结口径",
        "",
        f"- head_commit: `{git_snapshot.get('head_commit')}`",
        f"- branch: `{git_snapshot.get('branch')}`",
        f"- worktree_dirty: `{git_snapshot.get('worktree_dirty')}`",
        f"- changed_file_count: `{git_snapshot.get('changed_file_count')}`",
        f"- freeze_object_created: `{git_snapshot.get('freeze_object_created')}`",
        f"- freeze_tag_name: `{git_freeze.get('freeze_tag_name')}`",
        f"- freeze_matches_head: `{git_freeze.get('freeze_matches_head')}`",
        "",
        "自动验收只检查 Git 冻结证据，不会自动创建 commit/tag；没有冻结 tag 或工作树不干净时，Day 7 必须保持 blocked。",
        "",
        "## 方法问题关闭状态",
        "",
        f"- fix_report_status: `{fix.get('status')}`",
        f"- method_open_issue_count: `{fix.get('method_open_issue_count')}`",
        f"- required_method_issue_statuses: `{fix.get('required_method_issue_statuses')}`",
        f"- missing_required_method_issue_ids: `{fix.get('missing_required_method_issue_ids')}`",
        f"- non_fixed_required_method_issue_ids: `{fix.get('non_fixed_required_method_issue_ids')}`",
        f"- m3_systemic_failure: `{fix.get('m3_systemic_failure')}`",
        f"- m3_method_formal_run_blocked: `{fix.get('m3_method_formal_run_blocked')}`",
        f"- m3_programmatic_decision_count: `{fix.get('m3_programmatic_decision_count')}` / `{fix.get('m3_agent_decision_output_count')}`",
        f"- m3_programmatic_decision_rate: `{fix.get('m3_programmatic_decision_rate')}`",
        f"- agent_decision_ablation_required: `{fix.get('agent_decision_ablation_required')}`",
        f"- formal_run_blocked: `{fix.get('formal_run_blocked')}`",
        "",
        "## M3 消融证据哈希一致性",
        "",
        f"- m3_ablation_status: `{m3_ablation.get('status')}`",
        f"- m3_ablation_report_status: `{m3_ablation.get('report_status')}`",
        f"- m3_ablation_gate_status: `{m3_ablation.get('gate_status')}`",
        f"- gate_manifest_sha256: `{m3_ablation.get('gate_manifest_sha256')}`",
        f"- current_manifest_sha256: `{m3_ablation.get('current_manifest_sha256')}`",
        f"- hash_consistent: `{m3_ablation.get('hash_consistent')}`",
        f"- failed_checks: `{m3_ablation.get('failed_checks') or []}`",
        f"- manifest: `{m3_ablation.get('manifest')}`",
        f"- report_json: `{m3_ablation.get('report_json')}`",
        f"- day7_dev_gate: `{m3_ablation.get('day7_dev_gate')}`",
        "",
        "## 生成的交付文件",
        "",
        "| 文件 | Exists | SHA-256 |",
        "|---|---:|---|",
    ]
    for item in generated:
        lines.append(
            f"| `{item.get('path')}` | `{item.get('exists')}` | `{item.get('sha256') or ''}` |"
        )
    artifact_hashes_path = pack.get("post_write_artifact_hashes_path")
    if artifact_hashes_path:
        lines.extend(
            [
                "",
                f"完整 post-write SHA-256 清单见：`{artifact_hashes_path}`。",
            ]
        )
    lines.extend(
        [
            "",
            "## 下一步",
            "",
            "1. 若 130 行确实已经逐行检查，请保留当前 confirmed review 文件；若只是批量填入 approved，需要重新逐行复核后再导出验收包。",
            "2. 非 Git 验收项已关闭；如需完整 Day 7 冻结证据，请创建 Git freeze/tag 并保持验收时工作树干净。",
            "3. 若暂不做 Git 冻结，可将当前验收包理解为“非 Git 项已通过、Git 项仍 blocked”的交付版本。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def render_case_review_table(pack: Mapping[str, Any]) -> str:
    rows = _as_dict_list(_nested(pack, "case_review", "rows"))
    lines = [
        "# Day 7 人类可读逐案例审查表",
        "",
        "| # | case_id | 轮次 | 任务类型 | 城市 | 可行性 | 人工复核状态 | 备注 |",
        "|---:|---|---:|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {index} | `{case_id}` | {turn_count} | {task_types} | {city_id} | `{feasibility_status}` | `{manual_review_status}` | {notes} |".format(
                index=row.get("index"),
                case_id=row.get("case_id"),
                turn_count=row.get("turn_count"),
                task_types=", ".join(_as_list(row.get("task_types"))),
                city_id=row.get("city_id") or "",
                feasibility_status=row.get("feasibility_status"),
                manual_review_status=row.get("manual_review_status"),
                notes=row.get("review_notes") or "",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def render_cross_dataset_leakage_report(pack: Mapping[str, Any]) -> str:
    report = _dict(pack.get("cross_dataset_leakage"))
    counts = _dict(report.get("counts"))
    lines = [
        "# Day 7 跨数据集重复与泄漏报告",
        "",
        f"- status: `{report.get('status')}`",
        f"- checked_comparison_splits: `{report.get('checked_comparison_splits')}`",
        f"- internal_duplicate_count: `{counts.get('internal_duplicate_count')}`",
        f"- cross_split_duplicate_count: `{counts.get('cross_split_duplicate_count')}`",
        f"- near_duplicate_count: `{counts.get('near_duplicate_count')}`",
        "",
        "## 结论",
        "",
        str(report.get("interpretation") or ""),
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_offline_feasibility_report(pack: Mapping[str, Any]) -> str:
    report = _dict(pack.get("offline_feasibility"))
    city_counts = _dict(report.get("city_unit_distribution"))
    task_counts = _dict(report.get("task_unit_distribution"))
    lines = [
        "# Day 7 离线事实与约束可行性报告",
        "",
        f"- status: `{report.get('status')}`",
        f"- checked_tourism_unit_count: `{report.get('checked_tourism_unit_count')}`",
        f"- failed_tourism_unit_count: `{report.get('failed_tourism_unit_count')}`",
        "",
        "## 城市覆盖",
        "",
        "| 城市 | 已检查轮次 |",
        "|---|---:|",
    ]
    for key, value in sorted(city_counts.items()):
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "## 任务覆盖", "", "| 任务类型 | 已检查轮次 |", "|---|---:|"])
    for key, value in sorted(task_counts.items()):
        lines.append(f"| {key} | {value} |")
    if report.get("failed_units"):
        lines.extend(["", "## 失败样例", ""])
        for item in _as_dict_list(report.get("failed_units"))[:20]:
            lines.append(f"- `{item.get('label')}`: {item.get('status')}")
    return "\n".join(lines).rstrip() + "\n"


def render_day7_stage_delivery_report(pack: Mapping[str, Any]) -> str:
    delivery = _dict(pack.get("delivery_pack"))
    acceptance = _dict(pack.get("acceptance"))
    boundaries = _dict(pack.get("writing_boundaries"))
    lines = [
        "# Day 7 阶段交付包",
        "",
        f"- schema_version: `{delivery.get('schema_version')}`",
        f"- delivery_status: `{delivery.get('delivery_status')}`",
        f"- ready_for_day8: `{acceptance.get('ready_for_day8')}`",
        f"- prepared_for_manual_review: `{acceptance.get('prepared_for_manual_review')}`",
        f"- human_review_completed: `{acceptance.get('human_review_completed')}`",
        f"- paper_claims_allowed: `{acceptance.get('paper_claims_allowed')}`",
        f"- final_acceptance_failed_checks: `{acceptance.get('final_acceptance_failed_checks') or []}`",
        "",
        "## 可以使用的结论",
        "",
    ]
    for item in _as_list(boundaries.get("allowed_claims")):
        lines.append(f"- {item}")
    lines.extend(["", "## 暂时不能使用的结论", ""])
    for item in _as_list(boundaries.get("forbidden_claims")):
        lines.append(f"- {item}")
    lines.extend(["", "## Day 8 最短路径", ""])
    for item in _as_list(delivery.get("day8_next_steps")):
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def default_acceptance_output_dir(*, run_id: str | None = None) -> Path:
    """Return the default Day 7 acceptance output directory."""
    return DEFAULT_ACCEPTANCE_ROOT / (
        run_id or f"day7_acceptance_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    )


def _annotation_review_rows(
    units: Sequence[Mapping[str, Any]],
    quality_units: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, unit in enumerate(units, start=1):
        label = str(unit.get("label") or "")
        expected = _dict(unit.get("expected"))
        quality = _dict(quality_units.get(label))
        hard_constraints = _dict(expected.get("hard_constraints"))
        parsed_slots = _dict(quality.get("visible_slots"))
        current_parsed_slots = _dict(quality.get("current_visible_slots"))
        gold_slots = _dict(quality.get("gold_slots"))
        feasibility = _dict(quality.get("offline_feasibility"))
        parse_match = _slot_subset_matches(gold_slots, parsed_slots)
        rows.append(
            {
                "review_round": 1,
                "row_index": index,
                "review_unit_id": label,
                "case_id": unit.get("case_id"),
                "turn_id": unit.get("turn_id") or "",
                "is_scenario_turn": bool(unit.get("turn_id")),
                "target_turn": bool(unit.get("target_turn")),
                "task_type": expected.get("task_type") or quality.get("task_type"),
                "city_id": quality.get("city_id") or hard_constraints.get("destination"),
                "user_input": unit.get("user_input"),
                "gold_slots_json": _compact_json(gold_slots),
                "parsed_slots_json": _compact_json(parsed_slots),
                "current_parsed_slots_json": _compact_json(current_parsed_slots),
                "parse_gold_match": parse_match,
                "changed_slots_json": _compact_json(expected.get("changed_slots") or {}),
                "preserved_slots_json": _compact_json(expected.get("preserved_slots") or {}),
                "required_tools": ",".join(_as_list(expected.get("required_tools"))),
                "accepted_agent_sets_json": _compact_json(expected.get("accepted_agent_sets") or []),
                "accepted_tool_sets_json": _compact_json(expected.get("accepted_tool_sets") or []),
                "offline_feasibility_status": feasibility.get("status") or "not_checked",
                "machine_review_status": (
                    "passed" if parse_match and feasibility.get("status") != "failed" else "needs_attention"
                ),
                "human_review_status": "pending_human_confirmation",
                "human_reviewer": "",
                "human_decision": "",
                "human_notes": "",
            }
        )
    return rows


def _load_annotation_review_overlay(
    annotation_review_path: str | Path | None,
    generated_rows: Sequence[Mapping[str, Any]],
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Overlay human review columns onto the regenerated machine prefill.

    The generated rows remain the source of truth for task labels, gold slots,
    parser output and feasibility evidence.  A user/teacher-completed review
    file is allowed to fill only the human-review columns, which avoids using a
    stale manual sheet to overwrite refreshed benchmark evidence.
    """
    base_rows = [dict(row) for row in generated_rows]
    if annotation_review_path is None:
        return base_rows, {
            "mode": "machine_prefill",
            "source_path": None,
            "errors": [],
        }

    path = Path(annotation_review_path)
    source: Dict[str, Any] = {
        "mode": "manual_review_overlay",
        "source_path": path.as_posix(),
        "errors": [],
    }
    if not path.exists():
        source["errors"].append("annotation_review_file_missing")
        return base_rows, source

    try:
        loaded_rows = _read_annotation_review_rows(path)
    except (OSError, json.JSONDecodeError, csv.Error, ValueError) as exc:
        source["errors"].append(f"annotation_review_file_unreadable:{type(exc).__name__}")
        return base_rows, source

    loaded_by_id = {
        str(row.get("review_unit_id") or ""): row
        for row in loaded_rows
        if str(row.get("review_unit_id") or "")
    }
    expected_ids = [str(row.get("review_unit_id") or "") for row in base_rows]
    expected_id_set = set(expected_ids)
    if len(loaded_rows) != len(base_rows):
        source["errors"].append("annotation_review_row_count_mismatch")
    missing_ids = [unit_id for unit_id in expected_ids if unit_id not in loaded_by_id]
    extra_ids = sorted(set(loaded_by_id) - expected_id_set)
    if missing_ids:
        source["errors"].append("annotation_review_missing_unit_ids")
        source["missing_unit_id_sample"] = missing_ids[:20]
    if extra_ids:
        source["errors"].append("annotation_review_extra_unit_ids")
        source["extra_unit_id_sample"] = extra_ids[:20]

    merged_rows: List[Dict[str, Any]] = []
    for row in base_rows:
        merged = dict(row)
        loaded = loaded_by_id.get(str(row.get("review_unit_id") or ""))
        if loaded:
            for field in HUMAN_REVIEW_FIELDS:
                if field in loaded:
                    merged[field] = _clean_manual_cell(loaded.get(field))
        merged_rows.append(merged)
    return merged_rows, source


def _read_annotation_review_rows(path: Path) -> List[Dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, Mapping):
        rows = payload.get("rows")
    else:
        rows = payload
    if not isinstance(rows, list):
        raise ValueError("annotation review file must contain a rows list")
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _annotation_review_completion(
    rows: Sequence[Mapping[str, Any]],
    *,
    expected_turn_count: int,
    source_errors: Sequence[Any] = (),
) -> Dict[str, Any]:
    row_count = len(rows)
    machine_attention = [
        row
        for row in rows
        if str(row.get("machine_review_status") or "").strip() == "needs_attention"
    ]
    pending_rows: List[Mapping[str, Any]] = []
    unresolved_attention_rows: List[Mapping[str, Any]] = []
    rejected_rows: List[Mapping[str, Any]] = []
    blank_reviewer_rows: List[Mapping[str, Any]] = []
    blank_decision_rows: List[Mapping[str, Any]] = []
    reviewers: List[str] = []
    decisions: List[str] = []
    notes_values: List[str] = []

    for row in rows:
        reviewer = _clean_manual_cell(row.get("human_reviewer"))
        decision = _clean_manual_cell(row.get("human_decision"))
        notes = _clean_manual_cell(row.get("human_notes"))
        if reviewer:
            reviewers.append(reviewer)
        if decision:
            decisions.append(decision)
        if notes:
            notes_values.append(notes)
        approved = _human_row_approved(row)
        rejected = _human_row_blocked(row)
        if not reviewer:
            blank_reviewer_rows.append(row)
        if not decision:
            blank_decision_rows.append(row)
        if rejected:
            rejected_rows.append(row)
        if not approved:
            pending_rows.append(row)
        if row in machine_attention and (not approved or not notes):
            unresolved_attention_rows.append(row)

    source_error_list = [str(error) for error in source_errors if str(error)]
    completed = (
        row_count == expected_turn_count
        and not source_error_list
        and not pending_rows
        and not unresolved_attention_rows
        and not rejected_rows
        and not blank_reviewer_rows
        and not blank_decision_rows
    )
    unique_reviewer_count = len(set(reviewers))
    unique_decision_count = len(set(decisions))
    unique_notes_count = len(set(notes_values))
    same_manual_values_across_all_rows = (
        completed
        and row_count > 1
        and unique_reviewer_count <= 1
        and unique_decision_count <= 1
        and unique_notes_count <= 1
    )
    return {
        "status": "human_review_completed" if completed else "pending_human_confirmation",
        "human_review_completed": completed,
        "expected_row_count": expected_turn_count,
        "row_count": row_count,
        "row_count_matches_expected": row_count == expected_turn_count,
        "approved_row_count": row_count - len(pending_rows),
        "pending_human_confirmation_count": len(pending_rows),
        "machine_needs_attention_count": len(machine_attention),
        "unresolved_machine_attention_count": len(unresolved_attention_rows),
        "rejected_or_needs_revision_count": len(rejected_rows),
        "blank_reviewer_count": len(blank_reviewer_rows),
        "blank_decision_count": len(blank_decision_rows),
        "source_error_count": len(source_error_list),
        "source_errors": source_error_list,
        "unique_human_reviewer_count": unique_reviewer_count,
        "unique_human_decision_count": unique_decision_count,
        "unique_human_notes_count": unique_notes_count,
        "same_manual_values_across_all_rows": same_manual_values_across_all_rows,
        "line_by_line_authenticity_machine_verifiable": False,
        "authenticity_verification_status": (
            "reviewer_attestation_required_for_line_by_line_claim"
            if same_manual_values_across_all_rows
            else "not_machine_verifiable"
            if completed
            else "not_applicable_until_review_completed"
        ),
        "paper_claim_policy": (
            "The exporter verifies declared review completion, but it cannot prove "
            "that the reviewer inspected every row. The paper may claim line-by-line "
            "manual review only if the named reviewer actually checked the 130 rows."
        ),
        "pending_unit_id_sample": _row_unit_sample(pending_rows),
        "unresolved_attention_unit_id_sample": _row_unit_sample(unresolved_attention_rows),
        "rejected_unit_id_sample": _row_unit_sample(rejected_rows),
        "policy": {
            "all_rows_require_human_reviewer": True,
            "all_rows_require_human_decision": True,
            "machine_needs_attention_rows_require_notes": True,
            "machine_needs_attention_rows_block_acceptance_until_resolved": True,
        },
    }


def _human_row_approved(row: Mapping[str, Any]) -> bool:
    status = _manual_token(row.get("human_review_status"))
    decision = _manual_token(row.get("human_decision"))
    reviewer = _clean_manual_cell(row.get("human_reviewer"))
    return (
        bool(reviewer)
        and status in APPROVED_HUMAN_REVIEW_STATUSES
        and decision in APPROVED_HUMAN_DECISIONS
        and not _human_row_blocked(row)
    )


def _human_row_blocked(row: Mapping[str, Any]) -> bool:
    status = _manual_token(row.get("human_review_status"))
    decision = _manual_token(row.get("human_decision"))
    return status in BLOCKING_HUMAN_REVIEW_STATUSES or decision in BLOCKING_HUMAN_DECISIONS


def _manual_token(value: Any) -> str:
    return _clean_manual_cell(value).lower()


def _clean_manual_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _row_unit_sample(rows: Sequence[Mapping[str, Any]], limit: int = 20) -> List[str]:
    return [str(row.get("review_unit_id") or "") for row in rows[:limit]]


def _case_review_rows(
    cases: Sequence[Mapping[str, Any]],
    annotation_rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    rows_by_case: Dict[str, List[Mapping[str, Any]]] = {}
    for row in annotation_rows:
        rows_by_case.setdefault(str(row.get("case_id") or ""), []).append(row)

    case_rows: List[Dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        case_id = str(case.get("case_id") or "")
        rows = rows_by_case.get(case_id, [])
        task_types = sorted({str(row.get("task_type")) for row in rows if row.get("task_type")})
        city_ids = sorted({str(row.get("city_id")) for row in rows if row.get("city_id")})
        feasibility_status = "passed"
        if any(row.get("offline_feasibility_status") == "failed" for row in rows):
            feasibility_status = "failed"
        elif not any(row.get("offline_feasibility_status") == "passed" for row in rows):
            feasibility_status = "not_applicable"
        case_rows.append(
            {
                "index": index,
                "case_id": case_id,
                "turn_count": len(rows),
                "case_type": "scenario" if _is_scenario_case(case) else "single_turn",
                "task_types": task_types,
                "city_id": ",".join(city_ids),
                "feasibility_status": feasibility_status,
                "manual_review_status": _case_manual_review_status(rows),
                "review_notes": _case_review_note(rows),
            }
        )
    return case_rows


def _case_manual_review_status(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return "missing_review_rows"
    if any(_human_row_blocked(row) for row in rows):
        return "needs_revision"
    if all(_human_row_approved(row) for row in rows):
        return "confirmed"
    return "pending_human_confirmation"


def _cross_dataset_leakage_report(
    *,
    quality_report: Mapping[str, Any],
    comparison_splits: Mapping[str, Sequence[Mapping[str, Any]]],
    dataset_path: Path,
) -> Dict[str, Any]:
    coverage = _dict(quality_report.get("coverage"))
    internal = _as_dict_list(coverage.get("duplicate_visible_input_groups"))
    cross = _as_dict_list(coverage.get("cross_split_duplicate_visible_input_groups"))
    near = _as_dict_list(coverage.get("near_duplicate_visible_input_pairs"))
    counts = {
        "internal_duplicate_count": len(internal),
        "cross_split_duplicate_count": len(cross),
        "near_duplicate_count": len(near),
    }
    passed = all(value == 0 for value in counts.values())
    return {
        "schema_version": "ctp-day7-cross-dataset-leakage-v1",
        "status": "passed" if passed else "failed",
        "dataset_path": dataset_path.as_posix(),
        "checked_comparison_splits": sorted(comparison_splits.keys()),
        "counts": counts,
        "internal_duplicates": internal,
        "cross_split_duplicates": cross,
        "near_duplicates": near,
        "policy": {
            "exact_duplicate_blocking": True,
            "near_duplicate_blocking": True,
            "gold_visible_to_generation_allowed": False,
        },
        "interpretation": (
            "未发现测试集内部重复、跨开发/烟雾集重复或高度近似泄漏。"
            if passed
            else "发现重复或近似泄漏，正式测试集草稿不能冻结。"
        ),
    }


def _offline_feasibility_review(
    *,
    quality_report: Mapping[str, Any],
    saved_feasibility_report: Mapping[str, Any],
) -> Dict[str, Any]:
    units = _as_dict_list(quality_report.get("units"))
    checked = [
        unit
        for unit in units
        if _nested(unit, "offline_feasibility", "checked") is True
    ]
    failed = [
        unit
        for unit in checked
        if _nested(unit, "offline_feasibility", "status") != "passed"
    ]
    city_counter: Counter[str] = Counter()
    task_counter: Counter[str] = Counter()
    rows: List[Dict[str, Any]] = []
    for unit in checked:
        city_id = str(unit.get("city_id") or "")
        task_type = str(unit.get("task_type") or "")
        if city_id:
            city_counter.update([city_id])
        if task_type:
            task_counter.update([task_type])
        rows.append(
            {
                "label": unit.get("label"),
                "case_id": unit.get("case_id"),
                "turn_id": unit.get("turn_id") or "",
                "task_type": task_type,
                "city_id": city_id,
                "status": _nested(unit, "offline_feasibility", "status"),
                "checks": _nested(unit, "offline_feasibility", "checks") or {},
            }
        )
    status = "passed" if not failed and quality_report.get("status") == "passed" else "failed"
    return {
        "schema_version": "ctp-day7-offline-feasibility-review-v1",
        "status": status,
        "quality_status": quality_report.get("status"),
        "saved_report_status": saved_feasibility_report.get("status"),
        "unit_count": len(units),
        "checked_tourism_unit_count": len(checked),
        "passed_tourism_unit_count": len(checked) - len(failed),
        "failed_tourism_unit_count": len(failed),
        "city_unit_distribution": dict(sorted(city_counter.items())),
        "task_unit_distribution": dict(sorted(task_counter.items())),
        "fixed_data_snapshot": saved_feasibility_report.get("fixed_data_snapshot") or {},
        "rows": rows,
        "failed_units": [
            {
                "label": unit.get("label"),
                "case_id": unit.get("case_id"),
                "turn_id": unit.get("turn_id") or "",
                "status": _nested(unit, "offline_feasibility", "status"),
            }
            for unit in failed
        ],
    }


def _day7_evidence_summary(
    *,
    quota_path: Path,
    feasibility_path: Path,
    benchmark_path: Path,
    pilot_run_dir: Path,
    dev_run_dir: Path,
) -> Dict[str, Any]:
    quota = _read_json_object(quota_path)
    saved_feasibility = _read_json_object(feasibility_path)
    benchmark = _read_json_object(benchmark_path)
    pilot_gate = _read_json_object(pilot_run_dir / "day7_pilot_gate.json")
    pilot_summary = _read_json_object(pilot_run_dir / "evaluation_summary.json")
    dev_gate = _read_json_object(dev_run_dir / DAY7_DEV_EXPERIMENT_GATE_NAME)
    dev_summary = _read_json_object(dev_run_dir / "evaluation_summary.json")
    cost_path = dev_run_dir / DAY7_COST_FORECAST_JSON_NAME
    cost = _read_json_object(cost_path)
    fix_path = pilot_run_dir / "day7_issue_report.json"
    fix = _read_json_object(fix_path)
    issue_counts = _dict(fix.get("issue_counts"))
    open_issue_counts = _issue_status_counts(issue_counts, "open")
    deferred_issue_counts = _issue_status_counts(issue_counts, "deferred")
    required_method_issue_statuses = _required_method_issue_statuses(fix)
    missing_required_method_issue_ids = [
        issue_id
        for issue_id in REQUIRED_METHOD_REAL_FAILURE_ISSUE_IDS
        if required_method_issue_statuses.get(issue_id) is None
    ]
    non_fixed_required_method_issue_ids = [
        issue_id
        for issue_id in REQUIRED_METHOD_REAL_FAILURE_ISSUE_IDS
        if required_method_issue_statuses.get(issue_id) != "fixed"
    ]
    m3_analysis = _dict(
        fix.get("m3_systemic_failure_analysis") or fix.get("m3_systemic_analysis")
    )
    m3_ablation = _m3_ablation_evidence_from_fix(fix)
    return {
        "quota_gate": {
            "status": quota.get("status"),
            "path": quota_path.as_posix(),
            "case_count": _nested(quota, "actual", "case_count"),
            "turn_count": _nested(quota, "actual", "total_turn_count"),
            "failed_checks": quota.get("failed_checks") or [],
        },
        "saved_feasibility": {
            "status": saved_feasibility.get("status"),
            "path": feasibility_path.as_posix(),
            "checked_tourism_unit_count": saved_feasibility.get("checked_tourism_unit_count"),
            "failed_tourism_unit_count": saved_feasibility.get("failed_tourism_unit_count"),
        },
        "benchmark_manifest": {
            "path": benchmark_path.as_posix(),
            "case_files": benchmark.get("case_files") or [],
            "comparison_files": benchmark.get("comparison_files") or [],
            "expected": benchmark.get("expected") or {},
        },
        "pilot_run": {
            "status": pilot_gate.get("status"),
            "run_id": pilot_gate.get("run_id"),
            "run_dir": pilot_run_dir.as_posix(),
            "raw_result_count": pilot_gate.get("actual_result_count")
            or pilot_summary.get("raw_run_count"),
            "trace_count": _nested(pilot_gate, "pilot_structure", "actual_trace_file_count"),
            "failed_checks": pilot_gate.get("failed_checks") or [],
            "quality_gated": _nested(pilot_gate, "quality_policy", "quality_threshold_enforced"),
        },
        "development_run": {
            "status": dev_gate.get("status"),
            "run_id": dev_gate.get("run_id"),
            "run_dir": dev_run_dir.as_posix(),
            "raw_result_count": _nested(dev_gate, "actual", "raw_result_count")
            or dev_summary.get("raw_run_count"),
            "trace_count": _nested(dev_gate, "trace_summary", "trace_file_count"),
            "failed_checks": dev_gate.get("failed_checks") or [],
            "method_stsr": _method_stsr_summary(dev_summary),
            "runtime_matches_day7_max_tokens_protocol": _nested(
                dev_gate,
                "runtime_audit",
                "matches_day7_max_tokens_protocol",
            ),
            "completion_token_cap_hit_rate": _nested(
                dev_gate,
                "output_length_risk",
                "completion_token_cap_hit_rate",
            ),
            "completion_token_cap_hit_rate_below_limit": _nested(
                dev_gate,
                "output_length_risk",
                "completion_token_cap_hit_rate_below_limit",
            ),
            "empty_and_token_capped_call_count": _nested(
                dev_gate,
                "output_length_risk",
                "empty_and_token_capped_call_count",
            ),
        },
        "cost_forecast": {
            "status": cost.get("status"),
            "freeze_status": _nested(cost, "freeze_decision", "status"),
            "rerun_required": _nested(cost, "freeze_decision", "rerun_required"),
            "rerun_required_checks": _nested(
                cost,
                "freeze_decision",
                "rerun_required_checks",
            ),
            "quality_rerun_recommended": _nested(
                cost,
                "freeze_decision",
                "quality_rerun_recommended",
            ),
            "quality_advisory_failed_checks": cost.get(
                "quality_advisory_failed_checks"
            )
            or [],
            "path": cost_path.as_posix(),
            "formal_projection": _dict(cost.get("formal_projection")),
            "budget_gate": _dict(cost.get("budget_gate")),
            "runtime_max_tokens_matches_day7_protocol": _nested(
                cost,
                "runtime_freeze",
                "matches_day7_max_tokens_protocol",
            ),
            "completion_token_cap_hit_rate": _nested(
                cost,
                "evidence_quality",
                "output_length_risk",
                "completion_token_cap_hit_rate",
            ),
            "empty_and_token_capped_call_count": _nested(
                cost,
                "evidence_quality",
                "output_length_risk",
                "empty_and_token_capped_call_count",
            ),
            "failed_checks": cost.get("failed_checks") or [],
        },
        "fix_report": {
            "status": fix.get("status"),
            "path": fix_path.as_posix(),
            "open_issue_counts": open_issue_counts,
            "deferred_issue_counts": deferred_issue_counts,
            "total_open_issue_count": sum(open_issue_counts.values()),
            "total_deferred_issue_count": sum(deferred_issue_counts.values()),
            "method_open_issue_count": _nested(
                fix,
                "issue_counts",
                "method_real_failures",
                "open",
            ),
            "required_method_issue_ids": list(REQUIRED_METHOD_REAL_FAILURE_ISSUE_IDS),
            "required_method_issue_statuses": required_method_issue_statuses,
            "missing_required_method_issue_ids": missing_required_method_issue_ids,
            "non_fixed_required_method_issue_ids": non_fixed_required_method_issue_ids,
            "required_method_issues_present": not missing_required_method_issue_ids,
            "required_method_issues_fixed": not non_fixed_required_method_issue_ids,
            "m3_systemic_failure": m3_analysis.get("systemic_failure"),
            "m3_method_formal_run_blocked": _nested(
                fix,
                "m3_method_readiness",
                "formal_run_blocked",
            ),
            "m3_programmatic_decision_count": _nested(
                fix,
                "m3_method_readiness",
                "programmatic_decision_count",
            ),
            "m3_agent_decision_output_count": _nested(
                fix,
                "m3_method_readiness",
                "agent_decision_output_count",
            ),
            "m3_programmatic_decision_rate": _nested(
                fix,
                "m3_method_readiness",
                "programmatic_decision_rate",
            ),
            "agent_decision_ablation_required": _nested(
                fix,
                "m3_method_readiness",
                "ablation_required",
            ),
            "formal_run_blocked": _formal_run_blocked(fix),
            "failed_checks": fix.get("failed_checks") or [],
        },
        "m3_ablation": m3_ablation,
    }


def _m3_ablation_evidence_from_fix(fix_report: Mapping[str, Any]) -> Dict[str, Any]:
    """Summarize direct M3 ablation artifacts and manifest-hash consistency."""
    evidence = _dict(fix_report.get("m3_no_decision_normalizer_ablation"))
    raw_report_path = evidence.get("path")
    run_dir = Path(str(evidence.get("run_dir") or "")).resolve() if evidence.get("run_dir") else None
    report_path = _resolve_existing_path(raw_report_path, base_dir=run_dir)
    if report_path is None and run_dir is not None:
        report_path = run_dir / DAY7_M3_ABLATION_REPORT_JSON_NAME
    if run_dir is None and report_path is not None:
        run_dir = report_path.parent
    manifest_path = run_dir / "experiment_manifest.json" if run_dir is not None else None
    gate_path = run_dir / DAY7_DEV_EXPERIMENT_GATE_NAME if run_dir is not None else None
    report_md_path = run_dir / DAY7_M3_ABLATION_REPORT_MD_NAME if run_dir is not None else None

    report = _read_json_object(report_path) if report_path is not None else {}
    manifest = _read_json_object(manifest_path) if manifest_path is not None else {}
    gate = _read_json_object(gate_path) if gate_path is not None else {}
    gate_manifest_sha256 = _artifact_index_sha256(gate, key="manifest")
    current_manifest_sha256 = (
        _file_sha256(manifest_path)
        if manifest_path is not None and manifest_path.exists()
        else None
    )
    manifest_report_json = _nested(
        manifest,
        "m3_no_decision_normalizer_ablation",
        "json",
    )
    manifest_report_md = _nested(
        manifest,
        "m3_no_decision_normalizer_ablation",
        "markdown",
    )
    checks = {
        "ablation_report_declared_in_issue_report": bool(evidence.get("available")),
        "ablation_report_passed": report.get("status") == "passed",
        "ablation_run_dir_exists": run_dir is not None and run_dir.exists(),
        "ablation_report_json_exists": report_path is not None and report_path.exists(),
        "ablation_report_md_exists": report_md_path is not None and report_md_path.exists(),
        "ablation_manifest_exists": manifest_path is not None and manifest_path.exists(),
        "ablation_dev_gate_exists": gate_path is not None and gate_path.exists(),
        "gate_manifest_sha256_recorded": bool(gate_manifest_sha256),
        "gate_manifest_sha256_matches_current_manifest": bool(
            gate_manifest_sha256
            and current_manifest_sha256
            and gate_manifest_sha256 == current_manifest_sha256
        ),
        "manifest_links_ablation_report_json": _same_existing_path(
            manifest_report_json,
            report_path,
            base_dir=run_dir,
        ),
        "manifest_links_ablation_report_md": _same_existing_path(
            manifest_report_md,
            report_md_path,
            base_dir=run_dir,
        ),
    }
    failed_checks = [key for key, passed in checks.items() if not passed]
    return {
        "status": "passed" if not failed_checks else "failed",
        "available": bool(evidence.get("available")),
        "run_dir": run_dir.as_posix() if run_dir is not None else evidence.get("run_dir"),
        "report_json": report_path.as_posix() if report_path is not None else raw_report_path,
        "report_md": report_md_path.as_posix() if report_md_path is not None else None,
        "manifest": manifest_path.as_posix() if manifest_path is not None else None,
        "day7_dev_gate": gate_path.as_posix() if gate_path is not None else None,
        "report_status": report.get("status") or evidence.get("status"),
        "gate_status": gate.get("status"),
        "gate_manifest_sha256": gate_manifest_sha256,
        "current_manifest_sha256": current_manifest_sha256,
        "hash_consistent": checks["gate_manifest_sha256_matches_current_manifest"],
        "checks": checks,
        "failed_checks": failed_checks,
        "interpretation": (
            "M3 消融报告、manifest 和 gate 哈希一致，可作为同一版代码证据引用。"
            if not failed_checks
            else "M3 消融证据链仍有缺口，Git 冻结前需要刷新报告或哈希。"
        ),
    }


def _acceptance_decision_legacy(
    *,
    quality_report: Mapping[str, Any],
    leakage_report: Mapping[str, Any],
    feasibility_report: Mapping[str, Any],
    benchmark_preflight: Mapping[str, Any],
    evidence: Mapping[str, Any],
    annotation_rows: Sequence[Mapping[str, Any]],
    case_rows: Sequence[Mapping[str, Any]],
    expected_case_count: int,
    expected_turn_count: int,
    expected_scenario_case_count: int,
    required_method_count: int,
) -> Dict[str, Any]:
    checks = {
        "phase0_protocol_present": Path("Phase0_实验协议.md").exists(),
        "test_draft_quality_gate_passed": quality_report.get("status") == "passed",
        "annotation_review_table_complete": len(annotation_rows) == expected_turn_count,
        "case_review_table_complete": len(case_rows) == expected_case_count,
        "cross_dataset_leakage_passed": leakage_report.get("status") == "passed",
        "offline_feasibility_passed": feasibility_report.get("status") == "passed",
        "quota_gate_passed": _nested(evidence, "quota_gate", "status") == "passed",
        "benchmark_manifest_points_test_draft": _benchmark_manifest_points_known_test_set(
            evidence
        ),
        "benchmark_preflight_passed": benchmark_preflight.get("status") == "passed",
        "benchmark_preflight_raw_count_matches_methods": _nested(
            benchmark_preflight,
            "run",
            "expected_raw_run_count",
        )
        == expected_turn_count * required_method_count,
        "pilot_gate_passed": _nested(evidence, "pilot_run", "status") == "passed",
        "dev_gate_passed": _nested(evidence, "development_run", "status") == "passed",
        "dev_runtime_matches_day7_max_tokens_protocol": _nested(
            evidence,
            "development_run",
            "runtime_matches_day7_max_tokens_protocol",
        )
        is True,
        "dev_completion_token_cap_hit_rate_below_limit": _nested(
            evidence,
            "development_run",
            "completion_token_cap_hit_rate_below_limit",
        )
        is True,
        "dev_no_empty_outputs_at_token_cap": _nested(
            evidence,
            "development_run",
            "empty_and_token_capped_call_count",
        )
        == 0,
        "cost_forecast_passed": _nested(evidence, "cost_forecast", "status") == "passed",
        "fix_report_completed": _nested(evidence, "fix_report", "status") == "completed",
        "scenario_case_count_matches": _nested(quality_report, "dataset", "scenario_case_count")
        == expected_scenario_case_count,
    }
    failed_checks = [key for key, passed in checks.items() if not passed]
    status = "accepted_for_day8" if not failed_checks else "blocked"
    return {
        "status": status,
        "ready_for_day8": status == "accepted_for_day8",
        "paper_claims_allowed": False,
        "acceptance_level": "day7_stage_acceptance_not_final_paper_result",
        "failed_checks": failed_checks,
        "checks": checks,
        "human_review_completed": False,
        "manual_review_policy": (
            "复核表已机器预填，但 human_review_completed=false；正式冻结前仍建议人工签字确认。"
        ),
        "interpretation": (
            "Day 7 的数据草稿、真实运行审计、成本冻结和交付物已可进入 Day 8。"
            if status == "accepted_for_day8"
            else "Day 7 阶段验收仍被 failed_checks 阻塞。"
        ),
        "quality_boundary": (
            "开发集真实结果只用于诊断，不允许作为论文最终效果结论；正式论文结论必须等待 "
            "100 条测试集主实验。"
        ),
    }


def _acceptance_decision(
    *,
    quality_report: Mapping[str, Any],
    leakage_report: Mapping[str, Any],
    feasibility_report: Mapping[str, Any],
    benchmark_preflight: Mapping[str, Any],
    evidence: Mapping[str, Any],
    annotation_rows: Sequence[Mapping[str, Any]],
    annotation_summary: Mapping[str, Any],
    case_rows: Sequence[Mapping[str, Any]],
    git_snapshot: Mapping[str, Any],
    expected_case_count: int,
    expected_turn_count: int,
    expected_scenario_case_count: int,
    required_method_count: int,
) -> Dict[str, Any]:
    preparation_checks = {
        "phase0_protocol_present": Path("Phase0_实验协议.md").exists(),
        "test_draft_quality_gate_passed": quality_report.get("status") == "passed",
        "annotation_review_table_complete": len(annotation_rows) == expected_turn_count,
        "case_review_table_complete": len(case_rows) == expected_case_count,
        "cross_dataset_leakage_passed": leakage_report.get("status") == "passed",
        "offline_feasibility_passed": feasibility_report.get("status") == "passed",
        "quota_gate_passed": _nested(evidence, "quota_gate", "status") == "passed",
        "benchmark_manifest_points_test_draft": _benchmark_manifest_points_known_test_set(
            evidence
        ),
        "benchmark_preflight_passed": benchmark_preflight.get("status") == "passed",
        "benchmark_preflight_raw_count_matches_methods": _nested(
            benchmark_preflight,
            "run",
            "expected_raw_run_count",
        )
        == expected_turn_count * required_method_count,
        "pilot_gate_passed": _nested(evidence, "pilot_run", "status") == "passed",
        "dev_gate_passed": _nested(evidence, "development_run", "status") == "passed",
        "dev_runtime_matches_day7_max_tokens_protocol": _nested(
            evidence,
            "development_run",
            "runtime_matches_day7_max_tokens_protocol",
        )
        is True,
        "dev_completion_token_cap_hit_rate_below_limit": _nested(
            evidence,
            "development_run",
            "completion_token_cap_hit_rate_below_limit",
        )
        is True,
        "dev_no_empty_outputs_at_token_cap": _nested(
            evidence,
            "development_run",
            "empty_and_token_capped_call_count",
        )
        == 0,
        "cost_forecast_passed": _nested(evidence, "cost_forecast", "status") == "passed",
        "scenario_case_count_matches": _nested(quality_report, "dataset", "scenario_case_count")
        == expected_scenario_case_count,
    }
    final_acceptance_checks = {
        "annotation_review_human_completed": annotation_summary.get("human_review_completed")
        is True,
        "annotation_review_pending_count_zero": annotation_summary.get(
            "pending_human_confirmation_count"
        )
        == 0,
        "machine_attention_rows_resolved": annotation_summary.get(
            "unresolved_machine_attention_count"
        )
        == 0,
        "annotation_review_no_rejections": annotation_summary.get(
            "rejected_or_needs_revision_count"
        )
        == 0,
        "annotation_review_source_valid": annotation_summary.get("source_error_count") == 0,
        "method_issue_report_completed": _nested(evidence, "fix_report", "status")
        == "completed",
        "method_real_failures_closed": _nested(
            evidence,
            "fix_report",
            "method_open_issue_count",
        )
        == 0,
        "method_required_issue_ids_present": _nested(
            evidence,
            "fix_report",
            "required_method_issues_present",
        )
        is True,
        "method_required_issue_ids_fixed": _nested(
            evidence,
            "fix_report",
            "required_method_issues_fixed",
        )
        is True,
        "m3_systemic_failure_closed": _nested(
            evidence,
            "fix_report",
            "m3_systemic_failure",
        )
        is False,
        "formal_run_unblocked_by_issue_report": _nested(
            evidence,
            "fix_report",
            "formal_run_blocked",
        )
        is False,
        "m3_method_readiness_reported": _nested(
            evidence,
            "fix_report",
            "m3_method_formal_run_blocked",
        )
        is not None,
        "m3_programmatic_decision_audit_reported": _nested(
            evidence,
            "fix_report",
            "m3_programmatic_decision_rate",
        )
        is not None,
        "m3_programmatic_decision_ablation_closed": _nested(
            evidence,
            "fix_report",
            "agent_decision_ablation_required",
        )
        is False,
        "m3_ablation_artifact_hash_consistent": _nested(
            evidence,
            "m3_ablation",
            "hash_consistent",
        )
        is True,
        "git_freeze_tag_created": git_snapshot.get("freeze_object_created") is True,
        "git_freeze_tag_matches_head": git_snapshot.get("freeze_matches_head") is True,
        "git_worktree_clean_at_acceptance": git_snapshot.get("worktree_dirty") is False,
    }
    checks = {**preparation_checks, **final_acceptance_checks}
    preparation_failed_checks = [
        key for key, passed in preparation_checks.items() if not passed
    ]
    final_acceptance_failed_checks = [
        key for key, passed in final_acceptance_checks.items() if not passed
    ]
    failed_checks = [key for key, passed in checks.items() if not passed]
    status = "accepted_for_day8" if not failed_checks else "blocked"
    prepared_for_manual_review = not preparation_failed_checks
    return {
        "status": status,
        "ready_for_day8": status == "accepted_for_day8",
        "prepared_for_manual_review": prepared_for_manual_review,
        "paper_claims_allowed": False,
        "acceptance_level": (
            "day7_stage_accepted_not_final_paper_result"
            if status == "accepted_for_day8"
            else "day7_materials_prepared_but_final_acceptance_blocked"
            if prepared_for_manual_review
            else "day7_stage_acceptance_blocked"
        ),
        "failed_checks": failed_checks,
        "preparation_failed_checks": preparation_failed_checks,
        "final_acceptance_failed_checks": final_acceptance_failed_checks,
        "checks": checks,
        "preparation_checks": preparation_checks,
        "final_acceptance_checks": final_acceptance_checks,
        "human_review_completed": annotation_summary.get("human_review_completed") is True,
        "manual_review_summary": dict(annotation_summary),
        "git_freeze_summary": {
            "freeze_tag_name": git_snapshot.get("freeze_tag_name"),
            "freeze_object_created": git_snapshot.get("freeze_object_created"),
            "freeze_matches_head": git_snapshot.get("freeze_matches_head"),
            "worktree_dirty": git_snapshot.get("worktree_dirty"),
            "changed_file_count": git_snapshot.get("changed_file_count"),
        },
        "manual_review_policy": (
            "Automated export may prefill the review sheet, but Day 7 is not accepted "
            "until every row has a named human reviewer, an approving decision, and all "
            "machine needs_attention rows have explanatory notes. Identical reviewer, "
            "decision, and note values are allowed only as a reviewer declaration; the "
            "exporter cannot prove line-by-line inspection."
        ),
        "interpretation": (
            "Day 7 final acceptance passed; this still does not allow final paper result claims."
            if status == "accepted_for_day8"
            else "Day 7 is blocked until the listed preparation/final acceptance checks are closed."
        ),
        "quality_boundary": (
            "开发集真实结果只能用于诊断，不能作为论文最终效果结论；正式论文结论必须等待 "
            "100 条测试集主实验。"
        ),
    }


def _benchmark_manifest_points_known_test_set(evidence: Mapping[str, Any]) -> bool:
    """Return whether the current manifest points to an accepted test dataset.

    Day 7 originally froze ``ctp120_test_draft.json``.  After Day 8, the formal
    manifest legitimately points at ``ctp100_formal_v2.json``.  The historical
    Day 7 preparation check should accept both states instead of forcing the
    project back to the old draft entry.
    """
    case_files = set(_as_list(_nested(evidence, "benchmark_manifest", "case_files")))
    return bool(case_files & {"ctp120_test_draft.json", "ctp100_formal_v2.json"})


def _stage_delivery_pack(
    *,
    created_at: str,
    run_id: str,
    acceptance: Mapping[str, Any],
    evidence: Mapping[str, Any],
    source_artifacts: Sequence[Mapping[str, Any]],
    git_snapshot: Mapping[str, Any],
) -> Dict[str, Any]:
    return {
        "schema_version": DAY7_STAGE_DELIVERY_PACK_SCHEMA_VERSION,
        "created_at": created_at,
        "run_id": run_id,
        "delivery_status": acceptance.get("status"),
        "ready_for_day8": acceptance.get("ready_for_day8"),
        "prepared_for_manual_review": acceptance.get("prepared_for_manual_review"),
        "paper_claims_allowed": acceptance.get("paper_claims_allowed"),
        "failed_checks": acceptance.get("failed_checks") or [],
        "preparation_failed_checks": acceptance.get("preparation_failed_checks") or [],
        "final_acceptance_failed_checks": acceptance.get("final_acceptance_failed_checks") or [],
        "acceptance_level": acceptance.get("acceptance_level"),
        "manual_review_summary": acceptance.get("manual_review_summary") or {},
        "git_freeze_summary": acceptance.get("git_freeze_summary") or {},
        "source_artifacts": list(source_artifacts),
        "day7_evidence": evidence,
        "git_freeze_snapshot": git_snapshot,
        "day8_next_steps": _stage_day8_next_steps(acceptance),
        "outputs": {},
        "generated_artifacts": [],
    }


def _stage_day8_next_steps(acceptance: Mapping[str, Any]) -> List[str]:
    manual = _dict(acceptance.get("manual_review_summary"))
    if manual.get("human_review_completed") is True:
        first_step = (
            "保留已完成的 confirmed review 文件；若 130 行只是批量写入 approved，"
            "需重新逐行复核后再导出验收包。"
        )
    else:
        first_step = (
            "人工确认 review CSV 中的任务类型、硬约束和多轮 changed/preserved slots。"
        )
    return [
        first_step,
        "保留最终开发集、成本冻结和方法问题报告的同一轮证据链，避免后续文档引用旧目录。",
        "非 Git 验收项通过后，若需要完整 Day 7 冻结证据，请完成 Git freeze/tag 后再执行 100 案例/520 原始结果正式主实验。",
    ]


def _source_artifact_inventory(
    *,
    dataset_path: Path,
    quota_path: Path,
    feasibility_path: Path,
    benchmark_path: Path,
    pilot_run_dir: Path,
    dev_run_dir: Path,
) -> List[Dict[str, Any]]:
    pilot_issue_report = pilot_run_dir / "day7_issue_report.json"
    m3_ablation = _m3_ablation_evidence_from_fix(_read_json_object(pilot_issue_report))
    items = [
        ("test_draft_dataset", dataset_path),
        ("test_draft_quota_report", quota_path),
        ("test_draft_feasibility_report", feasibility_path),
        ("benchmark_manifest", benchmark_path),
        ("pilot_gate", pilot_run_dir / "day7_pilot_gate.json"),
        ("pilot_issue_report", pilot_issue_report),
        ("dev_gate", dev_run_dir / DAY7_DEV_EXPERIMENT_GATE_NAME),
        ("cost_forecast", dev_run_dir / DAY7_COST_FORECAST_JSON_NAME),
    ]
    for key, raw_path in (
        ("m3_ablation_report_json", m3_ablation.get("report_json")),
        ("m3_ablation_report_md", m3_ablation.get("report_md")),
        ("m3_ablation_manifest", m3_ablation.get("manifest")),
        ("m3_ablation_dev_gate", m3_ablation.get("day7_dev_gate")),
    ):
        if raw_path:
            items.append((key, Path(str(raw_path))))
    return [_artifact_item(key, path) for key, path in items]


def _generated_artifact_inventory(paths: Mapping[str, Path]) -> List[Dict[str, Any]]:
    self_referential = {
        "acceptance_report_md",
        "day7_delivery_pack_json",
        "day7_delivery_report_md",
    }
    items: List[Dict[str, Any]] = []
    for key, path in paths.items():
        item = _artifact_item(key, path)
        if key in self_referential and item["exists"]:
            item["sha256"] = None
            item["hash_note"] = "self-referential report; hash is intentionally not embedded"
        items.append(item)
    return items


def _artifact_item(key: str, path: Path) -> Dict[str, Any]:
    exists = path.exists()
    return {
        "key": key,
        "path": path.as_posix(),
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else None,
        "sha256": _file_sha256(path) if exists else None,
    }


def _artifact_index_sha256(gate: Mapping[str, Any], *, key: str) -> Optional[str]:
    for item in _as_dict_list(_nested(gate, "artifact_index", "files")):
        if item.get("key") == key:
            value = item.get("sha256")
            return str(value) if value else None
    return None


def _resolve_existing_path(value: Any, *, base_dir: Path | None = None) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    candidates = [path] if path.is_absolute() else []
    if not path.is_absolute():
        if base_dir is not None:
            candidates.append(base_dir / path)
        candidates.append(Path.cwd() / path)
        candidates.append(path)
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate.resolve()
        except OSError:
            continue
    try:
        return (base_dir / path).resolve() if base_dir is not None and not path.is_absolute() else path.resolve()
    except OSError:
        return path


def _same_existing_path(
    left: Any,
    right: Path | None,
    *,
    base_dir: Path | None = None,
) -> bool:
    if right is None or not left:
        return False
    left_path = _resolve_existing_path(left, base_dir=base_dir)
    if left_path is None:
        return False
    try:
        return left_path.resolve() == right.resolve()
    except OSError:
        return left_path.as_posix() == right.as_posix()


def _post_write_artifact_hashes(
    *,
    run_id: str,
    paths: Mapping[str, Path],
) -> Dict[str, Any]:
    """Build a non-self-referential SHA-256 sidecar after artifacts are written."""
    return {
        "schema_version": "ctp-day7-artifact-sha256-v1",
        "run_id": run_id,
        "hash_strategy": "sha256_raw_file_bytes_post_write_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": [_artifact_item(key, path) for key, path in paths.items()],
        "self_hash_note": (
            f"{DAY7_ARTIFACT_SHA256_JSON_NAME} does not include its own SHA-256 "
            "to avoid self-referential hash drift."
        ),
    }


def _flatten_case_units(cases: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    units: List[Dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("case_id") or "")
        turns = case.get("turns")
        if isinstance(turns, list):
            for turn in turns:
                if not isinstance(turn, Mapping):
                    continue
                turn_id = str(turn.get("turn_id") or "")
                units.append(
                    {
                        "label": f"{case_id}/{turn_id}",
                        "case_id": case_id,
                        "turn_id": turn_id,
                        "target_turn": bool(turn.get("target_turn")),
                        "user_input": turn.get("user_input"),
                        "expected": turn.get("expected") or {},
                    }
                )
        else:
            units.append(
                {
                    "label": case_id,
                    "case_id": case_id,
                    "turn_id": "",
                    "target_turn": True,
                    "user_input": case.get("user_input"),
                    "expected": case.get("expected") or {},
                }
            )
    return units


def _load_comparison_splits(
    dataset_path: Path,
    document: Any,
) -> Dict[str, List[Dict[str, Any]]]:
    if not isinstance(document, Mapping):
        return {}
    comparison_splits: Dict[str, List[Dict[str, Any]]] = {}
    for file_name in document.get("comparison_files") or []:
        comparison_path = dataset_path.parent / str(file_name)
        try:
            comparison_doc, comparison_cases = load_benchmark_document(comparison_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        split_name = (
            str(comparison_doc.get("split") or comparison_doc.get("dataset_id") or "")
            if isinstance(comparison_doc, Mapping)
            else ""
        )
        comparison_splits[split_name or comparison_path.stem] = comparison_cases
    return comparison_splits


def _quality_units_by_label(
    quality_report: Mapping[str, Any],
) -> Dict[str, Mapping[str, Any]]:
    return {
        str(unit.get("label")): unit
        for unit in _as_dict_list(quality_report.get("units"))
        if unit.get("label")
    }


def _compact_quality_report(report: Mapping[str, Any]) -> Dict[str, Any]:
    coverage = _dict(report.get("coverage"))
    language = _dict(report.get("language"))
    return {
        "schema_version": report.get("schema_version"),
        "status": report.get("status"),
        "errors": report.get("errors") or [],
        "warnings": report.get("warnings") or [],
        "dataset": report.get("dataset") or {},
        "coverage": {
            "task_distribution": coverage.get("task_distribution") or {},
            "city_distribution": coverage.get("city_distribution") or {},
            "duplicate_count": len(_as_dict_list(coverage.get("duplicate_visible_input_groups"))),
            "cross_split_duplicate_count": len(
                _as_dict_list(coverage.get("cross_split_duplicate_visible_input_groups"))
            ),
            "near_duplicate_count": len(
                _as_dict_list(coverage.get("near_duplicate_visible_input_pairs"))
            ),
        },
        "language": {
            "unit_count": language.get("unit_count"),
            "chinese_unit_count": language.get("chinese_unit_count"),
            "non_chinese_unit_count": language.get("non_chinese_unit_count"),
            "chinese_ratio": language.get("chinese_ratio"),
        },
    }


def _compact_preflight_report(report: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": report.get("schema_version"),
        "status": report.get("status"),
        "errors": report.get("errors") or [],
        "warnings": report.get("warnings") or [],
        "benchmark": report.get("benchmark") or {},
        "run": report.get("run") or {},
        "policy": report.get("policy") or {},
    }


def _method_stsr_summary(summary: Mapping[str, Any]) -> Dict[str, Any]:
    methods = _dict(summary.get("methods"))
    return {
        method: _dict(payload).get("stsr_rate")
        for method, payload in sorted(methods.items())
        if isinstance(payload, Mapping)
    }


def _issue_status_counts(issue_counts: Mapping[str, Any], field: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for category, payload in issue_counts.items():
        if not isinstance(payload, Mapping):
            continue
        value = payload.get(field)
        counts[str(category)] = int(value) if isinstance(value, int) else 0
    return counts


def _required_method_issue_statuses(fix_report: Mapping[str, Any]) -> Dict[str, str | None]:
    issues = _dict(fix_report.get("issues")).get("method_real_failures")
    observed: Dict[str, str] = {}
    if isinstance(issues, list):
        for issue in issues:
            if not isinstance(issue, Mapping):
                continue
            issue_id = issue.get("issue_id")
            status = issue.get("status")
            if isinstance(issue_id, str) and isinstance(status, str):
                observed[issue_id] = status
    return {
        issue_id: observed.get(issue_id)
        for issue_id in REQUIRED_METHOD_REAL_FAILURE_ISSUE_IDS
    }


def _formal_run_blocked(payload: Any) -> bool | None:
    values: List[bool] = []

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if key == "formal_run_blocked" and isinstance(child, bool):
                    values.append(child)
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    if any(values):
        return True
    if values:
        return False
    return None


def _git_snapshot(*, freeze_tag_name: str | None = None) -> Dict[str, Any]:
    head = _git(["rev-parse", "HEAD"])
    short = _git(["rev-parse", "--short", "HEAD"])
    branch = _git(["branch", "--show-current"])
    status_lines = _git(["status", "--short"]).splitlines()
    tag_name = (
        freeze_tag_name
        or os.environ.get("DAY7_ACCEPTANCE_FREEZE_TAG")
        or _head_day7_acceptance_tag()
        or DEFAULT_DAY7_FREEZE_TAG_NAME
    )
    tag_commit = _git(["rev-parse", "--verify", f"refs/tags/{tag_name}^{{}}"])
    freeze_object_created = bool(tag_commit)
    freeze_matches_head = bool(head and tag_commit and head == tag_commit)
    return {
        "head_commit": head or None,
        "head_short": short or None,
        "branch": branch or None,
        "worktree_dirty": bool(status_lines),
        "changed_file_count": len(status_lines),
        "status_sample": status_lines[:40],
        "freeze_object_created": freeze_object_created,
        "freeze_tag_name": tag_name,
        "freeze_tag_commit": tag_commit or None,
        "freeze_matches_head": freeze_matches_head,
        "freeze_mode": "git_tag" if freeze_object_created else "snapshot_only",
        "recommended_tag_name": tag_name,
        "recommended_commands": [
            "git add <人工确认后的 Day7 文件>",
            "git commit -m \"Freeze Day7 acceptance evidence\"",
            f"git tag -a {tag_name} -m \"Day7 acceptance evidence freeze\"",
        ],
    }


def _head_day7_acceptance_tag() -> str:
    tags = _git(["tag", "--points-at", "HEAD", "--list", "day7-acceptance-*"])
    candidates = sorted(line.strip() for line in tags.splitlines() if line.strip())
    return candidates[-1] if candidates else ""


def _git(args: Sequence[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _latest_run_dir(root: Path, *, required_file: str) -> Path:
    if not root.exists():
        return root
    candidates = [
        path
        for path in root.iterdir()
        if path.is_dir() and (path / required_file).exists()
    ]
    if not candidates:
        return root
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _slot_subset_matches(gold_slots: Mapping[str, Any], parsed_slots: Mapping[str, Any]) -> bool:
    if not gold_slots:
        return not (set(parsed_slots) & AUDITED_REVIEW_PARSE_SLOT_KEYS)
    for key, expected in gold_slots.items():
        if key not in parsed_slots:
            return False
        if not _review_slot_values_equal(parsed_slots.get(key), expected):
            return False
    if (set(parsed_slots) & AUDITED_REVIEW_PARSE_SLOT_KEYS) - set(gold_slots):
        return False
    return True


def _review_slot_values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, list) or isinstance(right, list):
        return {str(item) for item in _as_list(left)} == {str(item) for item in _as_list(right)}
    left_number = _safe_float(left)
    right_number = _safe_float(right)
    if left_number is not None and right_number is not None:
        return left_number == right_number
    return str(left).strip().casefold() == str(right).strip().casefold()


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _case_review_note(rows: Sequence[Mapping[str, Any]]) -> str:
    if any(row.get("machine_review_status") == "needs_attention" for row in rows):
        return "机器预审发现需人工重点确认"
    if any(row.get("changed_slots_json") not in ("{}", "") for row in rows):
        return "多轮修改案例，需核对 changed/preserved slots"
    return "机器预审通过，待人工抽查确认"


def _writing_boundaries() -> Dict[str, List[str]]:
    return {
        "allowed_claims": [
            "可以说明 Day 7 已完成正式测试集草稿、中文口径、重复泄漏、离线可行性和真实运行审计。",
            "可以说明 gpt-5-mini 的成本和运行参数已按开发集证据冻结为后续正式实验候选配置。",
            "可以说明 Day 7 dev/pilot 暴露了方法质量问题，并将其作为 Day 8 修复依据。",
        ],
        "forbidden_claims": [
            "不能声称当前系统已经达到论文最终效果。",
            "不能把 20 条开发集结果当作正式测试集结论。",
            "不能声称 adaptive multi-agent 已优于其他方法；当前证据恰好显示它需要修复。",
        ],
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_cell(row.get(key)) for key in fieldnames})


@contextmanager
def _temporary_env_defaults(defaults: Mapping[str, str]) -> Iterator[None]:
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


def _csv_cell(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple, set)):
        return _compact_json(value)
    return value


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _read_json_object(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp_for_id(iso_timestamp: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_timestamp)
    except ValueError:
        return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _evidence_row(name: str, status: Any, detail: str, path: Any) -> str:
    return f"| {name} | `{status}` | {detail} | `{path or ''}` |"


def _formal_cost_display(cost_summary: Mapping[str, Any]) -> Any:
    with_reserve = _nested(cost_summary, "budget_gate", "formal_with_reserve_cny")
    if with_reserve is not None:
        return with_reserve
    return _nested(cost_summary, "formal_projection", "cost_cny")


def _normalize_methods(methods: Iterable[str]) -> List[str]:
    normalized = [str(method).strip() for method in methods if str(method).strip()]
    if not normalized:
        raise ValueError("required_methods must not be empty")
    return normalized


def _document_value(document: Any, key: str) -> Any:
    return document.get(key) if isinstance(document, Mapping) else None


def _is_scenario_case(case: Mapping[str, Any]) -> bool:
    return isinstance(case.get("turns"), list)


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_dict_list(value: Any) -> List[Dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, tuple | set):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]
    return [str(value)]


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current
