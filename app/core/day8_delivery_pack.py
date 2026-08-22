"""Day8 delivery package for frozen formal experiment inputs.

This module does not run the formal experiment, call an LLM, or refresh any
online data.  It packages the Day8 inputs that must stay aligned before the
paper-level run:

- benchmark manifest and CTP-100 formal dataset;
- frozen QWeather snapshot;
- frozen intercity rail snapshot;
- Budget Policy v2 gold and human-review artifacts;
- dataset audit and formal preflight evidence.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from app.core.academic_experiment_design import (
    DEFAULT_ACADEMIC_DESIGN_JSON_PATH,
    DEFAULT_ACADEMIC_DESIGN_MD_PATH,
    DEFAULT_SEALED_VALIDATION_PATH,
    EXPECTED_SEALED_CASE_COUNT,
    EXPECTED_SEALED_TURN_COUNT,
    MAIN_BENCHMARK_ROLE,
    SEALED_VALIDATION_METHODS,
    SEALED_VALIDATION_ROLE,
    build_academic_experiment_design_report,
)
from app.core.experiment_method_contract import (
    EXPERIMENT_METHODS,
    validate_m2_template_stsr_compatibility,
)
from app.core.budget_gold import (
    BUDGET_GOLD_REVIEW_STATUS,
    BUDGET_GOLD_SCHEMA_VERSION,
    BUDGET_GOLD_STATUS,
    DEFAULT_CTP100_BUDGET_GOLD_PATH,
)
from app.core.budget_manual_review import (
    DEFAULT_ECONOMY_BUDGET_MANUAL_REVIEW_MD_PATH,
    DEFAULT_ECONOMY_BUDGET_MANUAL_REVIEW_PATH,
    ECONOMY_BUDGET_CONFIRMED_SCOPE,
    ECONOMY_BUDGET_EXCLUDED_SCOPE,
    ECONOMY_BUDGET_FORMAL_MAIN_TIERS,
    validate_economy_budget_manual_review,
)
from app.core.fixed_data import BUDGET_POLICY_VERSION, canonical_json_sha256
from app.core.formal_artifact_integrity import (
    DEFAULT_FORMAL_INTEGRITY_PATHS,
    FORMAL_ARTIFACT_INTEGRITY_SCHEMA_VERSION,
    FORMAL_EVALUATION_RULE_CATALOG_ID,
    build_formal_artifact_integrity_report,
)
from app.core.formal_experiment_preflight import (
    DEFAULT_FORMAL_METHOD_ORDER_SEED,
    build_formal_preflight_report,
    load_benchmark_document,
)
from app.core.intercity_transport_snapshot import validate_intercity_transport_snapshot
from app.core.pre_formal_validation_registry import (
    DEFAULT_PRE_FORMAL_VALIDATION_REGISTRY_PATH,
    validate_pre_formal_validation_registry,
)
from app.core.qweather_snapshot import validate_qweather_snapshot


DAY8_DELIVERY_PACK_SCHEMA_VERSION = "ctp-day8-delivery-pack-v1"
DAY8_DELIVERY_PACK_JSON_NAME = "day8_delivery_pack.json"
DAY8_DELIVERY_REPORT_MD_NAME = "day8_delivery_report.md"

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BENCHMARK_MANIFEST_PATH = ROOT / "experiments" / "benchmark.json"
DEFAULT_FORMAL_DATASET_PATH = ROOT / "experiments" / "ctp100_formal_v2.json"
DEFAULT_BUDGET_GOLD_PATH = (
    DEFAULT_CTP100_BUDGET_GOLD_PATH
)
DEFAULT_BUDGET_REVIEW_MD_PATH = (
    ROOT / "experiments" / "generated" / "ctp100_budget_gold_v2_review.md"
)
DEFAULT_BUDGET_REVIEW_CSV_PATH = (
    ROOT / "experiments" / "generated" / "ctp100_budget_gold_v2_review.csv"
)
DEFAULT_ECONOMY_BUDGET_REVIEW_JSON_PATH = DEFAULT_ECONOMY_BUDGET_MANUAL_REVIEW_PATH
DEFAULT_ECONOMY_BUDGET_REVIEW_MD_PATH = DEFAULT_ECONOMY_BUDGET_MANUAL_REVIEW_MD_PATH
DEFAULT_DATASET_AUDIT_JSON_PATH = (
    ROOT / "experiments" / "generated" / "ctp100_formal_v2_dataset_audit.json"
)
DEFAULT_DATASET_AUDIT_MD_PATH = (
    ROOT / "experiments" / "generated" / "ctp100_formal_v2_dataset_audit.md"
)
DEFAULT_QWEATHER_MANIFEST_PATH = (
    ROOT / "data" / "weather_snapshot" / "qweather_v1" / "snapshot_manifest.json"
)
DEFAULT_QWEATHER_VALIDATION_PATH = (
    ROOT / "data" / "weather_snapshot" / "qweather_v1" / "validation_report.json"
)
DEFAULT_INTERCITY_MANIFEST_PATH = ROOT / "data" / "intercity_transport" / "snapshot_manifest.json"
DEFAULT_INTERCITY_FARE_TABLE_PATH = (
    ROOT / "data" / "intercity_transport" / "rail_second_class_v1.json"
)
DEFAULT_INTERCITY_EVIDENCE_PATH = (
    ROOT
    / "data"
    / "intercity_transport"
    / "evidence"
    / "rail_second_class_evidence_v1.json"
)
DEFAULT_BUDGET_POLICY_DOC_PATH = ROOT / "docs" / "Budget_Policy_v2.md"
DEFAULT_EVALUATION_RULE_CATALOG_PATH = ROOT / "experiments" / "evaluation_rule_catalog.json"
DEFAULT_INDEPENDENT_EVALUATOR_CODE_PATH = ROOT / "app" / "core" / "independent_evaluator.py"
DEFAULT_EXPERIMENT_RUNNER_CODE_PATH = ROOT / "app" / "core" / "experiment_runner.py"
DEFAULT_METHOD_CONTRACT_CODE_PATH = ROOT / "app" / "core" / "experiment_method_contract.py"
DEFAULT_FORMAL_PREFLIGHT_CODE_PATH = ROOT / "app" / "core" / "formal_experiment_preflight.py"
DEFAULT_FORMAL_GATE_CODE_PATH = ROOT / "app" / "core" / "formal_experiment_gate.py"
DEFAULT_RUNNER_ACCEPTANCE_TEST_PATH = ROOT / "tests" / "test_day8_task1_runner_acceptance.py"
DEFAULT_ACADEMIC_DESIGN_PATH = DEFAULT_ACADEMIC_DESIGN_JSON_PATH
DEFAULT_ACADEMIC_DESIGN_DOC_PATH = DEFAULT_ACADEMIC_DESIGN_MD_PATH
DEFAULT_SEALED_VALIDATION_DATASET_PATH = DEFAULT_SEALED_VALIDATION_PATH
DEFAULT_ACADEMIC_DESIGN_VALIDATION_JSON_PATH = (
    ROOT / "experiments" / "generated" / "academic_experiment_design_validation_v1.json"
)
DEFAULT_ACADEMIC_DESIGN_VALIDATION_MD_PATH = (
    ROOT / "experiments" / "generated" / "academic_experiment_design_validation_v1.md"
)
DEFAULT_PRE_FORMAL_VALIDATION_REGISTRY_JSON_PATH = (
    DEFAULT_PRE_FORMAL_VALIDATION_REGISTRY_PATH
)
DEFAULT_OUTPUT_DIR = ROOT / "experiments" / "generated"
DEFAULT_PREFLIGHT_OUTPUT_DIR = ROOT / "experiments" / "results" / "formal_runs"
DEFAULT_EXPECTED_CASE_COUNT = 100
DEFAULT_EXPECTED_TURN_COUNT = 130
DEFAULT_EXPECTED_BUDGET_GOLD_COUNT = 90
DEFAULT_EXPECTED_SKIPPED_COUNT = 40
DEFAULT_EXPECTED_INTERCITY_ROUTE_COUNT = 50

PREFLIGHT_RUNTIME_DEFAULTS = {
    "EXPERIMENT_STRICT_MODE": "true",
    "EXPERIMENT_DISABLE_CACHE": "true",
    "TRACE_SAVE_USER_MESSAGE": "false",
    "LLM_TEMPERATURE": "0",
    "LLM_MAX_TOKENS": "4096",
    "LLM_TIMEOUT": "120",
    "LLM_RETRY_MAX_ATTEMPTS": "3",
    "EXPERIMENT_RESULT_HARD_TIMEOUT_SECONDS": "900",
    "LLM_REASONING_EFFORT": "minimal",
    "EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER": "true",
}
EXPECTED_NO_DATE_WEATHER_REMINDER_COUNT = 18


def build_day8_delivery_pack(
    *,
    benchmark_manifest_path: str | Path = DEFAULT_BENCHMARK_MANIFEST_PATH,
    formal_dataset_path: str | Path = DEFAULT_FORMAL_DATASET_PATH,
    budget_gold_path: str | Path = DEFAULT_BUDGET_GOLD_PATH,
    budget_review_md_path: str | Path = DEFAULT_BUDGET_REVIEW_MD_PATH,
    budget_review_csv_path: str | Path = DEFAULT_BUDGET_REVIEW_CSV_PATH,
    economy_budget_review_json_path: str | Path = DEFAULT_ECONOMY_BUDGET_REVIEW_JSON_PATH,
    economy_budget_review_md_path: str | Path = DEFAULT_ECONOMY_BUDGET_REVIEW_MD_PATH,
    dataset_audit_json_path: str | Path = DEFAULT_DATASET_AUDIT_JSON_PATH,
    dataset_audit_md_path: str | Path = DEFAULT_DATASET_AUDIT_MD_PATH,
    qweather_manifest_path: str | Path = DEFAULT_QWEATHER_MANIFEST_PATH,
    qweather_validation_path: str | Path = DEFAULT_QWEATHER_VALIDATION_PATH,
    intercity_manifest_path: str | Path = DEFAULT_INTERCITY_MANIFEST_PATH,
    intercity_fare_table_path: str | Path = DEFAULT_INTERCITY_FARE_TABLE_PATH,
    intercity_evidence_path: str | Path = DEFAULT_INTERCITY_EVIDENCE_PATH,
    budget_policy_doc_path: str | Path = DEFAULT_BUDGET_POLICY_DOC_PATH,
    academic_design_path: str | Path = DEFAULT_ACADEMIC_DESIGN_PATH,
    academic_design_doc_path: str | Path = DEFAULT_ACADEMIC_DESIGN_DOC_PATH,
    sealed_validation_dataset_path: str | Path = DEFAULT_SEALED_VALIDATION_DATASET_PATH,
    academic_design_validation_json_path: str | Path = DEFAULT_ACADEMIC_DESIGN_VALIDATION_JSON_PATH,
    academic_design_validation_md_path: str | Path = DEFAULT_ACADEMIC_DESIGN_VALIDATION_MD_PATH,
    pre_formal_validation_registry_path: str | Path = DEFAULT_PRE_FORMAL_VALIDATION_REGISTRY_JSON_PATH,
    preflight_output_dir: str | Path = DEFAULT_PREFLIGHT_OUTPUT_DIR,
    run_id: str | None = None,
    methods: Iterable[str] | None = None,
    expected_case_count: int = DEFAULT_EXPECTED_CASE_COUNT,
    expected_turn_count: int = DEFAULT_EXPECTED_TURN_COUNT,
    expected_budget_gold_count: int = DEFAULT_EXPECTED_BUDGET_GOLD_COUNT,
    expected_skipped_count: int = DEFAULT_EXPECTED_SKIPPED_COUNT,
    require_clean_git: bool = True,
) -> dict[str, Any]:
    """Build a machine-readable Day8 handoff package from frozen artifacts."""
    created_at = datetime.now(timezone.utc).isoformat()
    run_id = run_id or f"day8_delivery_{_timestamp_for_id(created_at)}"

    benchmark_path = Path(benchmark_manifest_path)
    dataset_path = Path(formal_dataset_path)
    gold_path = Path(budget_gold_path)
    review_md_path = Path(budget_review_md_path)
    review_csv_path = Path(budget_review_csv_path)
    economy_review_json_path = Path(economy_budget_review_json_path)
    economy_review_md_path = Path(economy_budget_review_md_path)
    audit_json_path = Path(dataset_audit_json_path)
    audit_md_path = Path(dataset_audit_md_path)
    qweather_manifest = Path(qweather_manifest_path)
    qweather_validation = Path(qweather_validation_path)
    intercity_manifest = Path(intercity_manifest_path)
    intercity_fare_table = Path(intercity_fare_table_path)
    intercity_evidence = Path(intercity_evidence_path)
    budget_policy_doc = Path(budget_policy_doc_path)
    evaluation_rule_catalog = DEFAULT_EVALUATION_RULE_CATALOG_PATH
    independent_evaluator_code = DEFAULT_INDEPENDENT_EVALUATOR_CODE_PATH
    experiment_runner_code = DEFAULT_EXPERIMENT_RUNNER_CODE_PATH
    method_contract_code = DEFAULT_METHOD_CONTRACT_CODE_PATH
    formal_preflight_code = DEFAULT_FORMAL_PREFLIGHT_CODE_PATH
    formal_gate_code = DEFAULT_FORMAL_GATE_CODE_PATH
    runner_acceptance_test = DEFAULT_RUNNER_ACCEPTANCE_TEST_PATH
    academic_design = Path(academic_design_path)
    academic_design_doc = Path(academic_design_doc_path)
    sealed_validation_dataset = Path(sealed_validation_dataset_path)
    academic_design_validation_json = Path(academic_design_validation_json_path)
    academic_design_validation_md = Path(academic_design_validation_md_path)
    pre_formal_validation_registry = Path(pre_formal_validation_registry_path)

    benchmark_doc, benchmark_cases, benchmark_error = _load_document(benchmark_path)
    dataset_doc, dataset_cases, dataset_error = _load_document(dataset_path)
    dataset_sha256 = canonical_json_sha256(dataset_doc) if dataset_doc is not None else None
    gold_doc = _read_json_object(gold_path)
    economy_review_report = _validated_economy_budget_review(economy_review_json_path)
    audit_doc = _read_json_object(audit_json_path)
    review_summary = _budget_review_summary(review_csv_path)
    qweather_report = _validated_qweather_snapshot()
    intercity_report = _validated_intercity_snapshot()
    formal_artifact_integrity_report = build_formal_artifact_integrity_report()
    pre_formal_validation_report = validate_pre_formal_validation_registry(
        pre_formal_validation_registry,
        required=True,
    )
    academic_design_report = build_academic_experiment_design_report(
        design_path=academic_design,
        design_doc_path=academic_design_doc,
        benchmark_manifest_path=benchmark_path,
        main_dataset_path=dataset_path,
        sealed_validation_path=sealed_validation_dataset,
    )

    selected_methods = tuple(methods or EXPERIMENT_METHODS)
    with _temporary_env_defaults(PREFLIGHT_RUNTIME_DEFAULTS):
        preflight_report = build_formal_preflight_report(
            benchmark_path=benchmark_path,
            output_dir=preflight_output_dir,
            run_id=f"{run_id}_preflight_probe",
            methods=selected_methods,
            repeats=1,
            method_order_seed=DEFAULT_FORMAL_METHOD_ORDER_SEED,
            expected_case_count=expected_case_count,
            require_llm_config=False,
            strict_formal=True,
            require_day8_delivery_pack=False,
            require_clean_git=False,
        )

    artifact_paths = {
        "benchmark_manifest": benchmark_path,
        "formal_dataset": dataset_path,
        "qweather_manifest": qweather_manifest,
        "qweather_validation_report": qweather_validation,
        "intercity_manifest": intercity_manifest,
        "intercity_fare_table": intercity_fare_table,
        "intercity_evidence_ledger": intercity_evidence,
        "budget_policy_doc": budget_policy_doc,
        "evaluation_rule_catalog": evaluation_rule_catalog,
        "independent_evaluator_code": independent_evaluator_code,
        "experiment_runner_code": experiment_runner_code,
        "method_contract_code": method_contract_code,
        "formal_preflight_code": formal_preflight_code,
        "formal_gate_code": formal_gate_code,
        "day8_runner_acceptance_test": runner_acceptance_test,
        "academic_experiment_design_json": academic_design,
        "academic_experiment_design_md": academic_design_doc,
        "sealed_validation_dataset": sealed_validation_dataset,
        "academic_design_validation_json": academic_design_validation_json,
        "academic_design_validation_md": academic_design_validation_md,
        "pre_formal_validation_registry": pre_formal_validation_registry,
        "budget_gold_json": gold_path,
        "economy_budget_manual_review_json": economy_review_json_path,
        "economy_budget_manual_review_md": economy_review_md_path,
        "budget_review_md": review_md_path,
        "budget_review_csv": review_csv_path,
        "dataset_audit_json": audit_json_path,
        "dataset_audit_md": audit_md_path,
    }
    artifact_paths.update(DEFAULT_FORMAL_INTEGRITY_PATHS)
    artifacts = _artifact_inventory(artifact_paths)

    checks = _readiness_checks(
        benchmark_doc=benchmark_doc,
        benchmark_cases=benchmark_cases,
        benchmark_error=benchmark_error,
        dataset_doc=dataset_doc,
        dataset_cases=dataset_cases,
        dataset_error=dataset_error,
        dataset_sha256=dataset_sha256,
        gold_doc=gold_doc,
        audit_doc=audit_doc,
        review_summary=review_summary,
        qweather_report=qweather_report,
        intercity_report=intercity_report,
        economy_review_report=economy_review_report,
        academic_design_report=academic_design_report,
        formal_artifact_integrity_report=formal_artifact_integrity_report,
        pre_formal_validation_report=pre_formal_validation_report,
        preflight_report=preflight_report,
        artifacts=artifacts,
        expected_case_count=expected_case_count,
        expected_turn_count=expected_turn_count,
        expected_budget_gold_count=expected_budget_gold_count,
        expected_skipped_count=expected_skipped_count,
        require_clean_git=require_clean_git,
    )
    failed_checks = [key for key, value in checks.items() if value is not True]
    status = "day8_delivery_ready" if not failed_checks else "day8_delivery_blocked"

    return {
        "schema_version": DAY8_DELIVERY_PACK_SCHEMA_VERSION,
        "created_at": created_at,
        "run_id": run_id,
        "readiness": {
            "status": status,
            "ready_for_formal_experiment": status == "day8_delivery_ready",
            "paper_claims_allowed": False,
            "failed_checks": failed_checks,
            "checks": checks,
            "interpretation": _interpretation(status, failed_checks),
        },
        "formal_input": {
            "benchmark_manifest": _display_path(benchmark_path),
            "formal_dataset": _display_path(dataset_path),
            "dataset_id": _dict(dataset_doc).get("dataset_id"),
            "dataset_version": _dict(dataset_doc).get("dataset_version"),
            "dataset_sha256": dataset_sha256,
            "case_count": len(dataset_cases),
            "turn_count": _turn_count(dataset_cases),
            "benchmark_case_count": len(benchmark_cases),
            "benchmark_turn_count": _turn_count(benchmark_cases),
            "methods": list(selected_methods),
            "expected_raw_run_count": _turn_count(benchmark_cases) * len(selected_methods),
        },
        "frozen_snapshots": {
            "qweather": qweather_report,
            "intercity_transport": intercity_report,
        },
        "budget_gold": {
            "path": _display_path(gold_path),
            "schema_version": gold_doc.get("schema_version"),
            "gold_status": gold_doc.get("gold_status"),
            "review_status": gold_doc.get("review_status"),
            "budget_policy_version": gold_doc.get("budget_policy_version"),
            "source_dataset_sha256": gold_doc.get("source_dataset_sha256"),
            "summary": gold_doc.get("summary") or {},
            "review": review_summary,
            "manual_review": gold_doc.get("manual_review") or {},
            "economy_manual_review": economy_review_report,
            "policy_doc": _display_path(budget_policy_doc),
        },
        "dataset_audit": {
            "path": _display_path(audit_json_path),
            "markdown": _display_path(audit_md_path),
            "schema_version": audit_doc.get("schema_version"),
            "status": audit_doc.get("status"),
            "dataset_sha256": audit_doc.get("dataset_sha256"),
            "issue_counts": audit_doc.get("issue_counts") or {},
        },
        "day8_acceptance_gates": _day8_acceptance_gate_report(
            audit_doc=audit_doc,
            expected_turn_count=expected_turn_count,
        ),
        "academic_experiment_design": {
            "status": academic_design_report.get("status"),
            "errors": academic_design_report.get("errors") or [],
            "warnings": academic_design_report.get("warnings") or [],
            "checks": academic_design_report.get("checks") or {},
            "design": academic_design_report.get("design") or {},
            "main_benchmark": academic_design_report.get("main_benchmark") or {},
            "sealed_validation": academic_design_report.get("sealed_validation") or {},
            "main_quality": academic_design_report.get("main_quality") or {},
            "sealed_quality": academic_design_report.get("sealed_quality") or {},
        },
        "formal_artifact_integrity": formal_artifact_integrity_report,
        "pre_formal_validation": pre_formal_validation_report,
        "formal_preflight": _compact_preflight(preflight_report),
        "artifact_inventory": artifacts,
        "handoff_commands": _handoff_commands(),
        "manual_next_steps": _manual_next_steps(status, failed_checks),
        "writing_boundaries": {
            "allowed_claims": [
                "Day8 已形成可复现的正式实验输入：100 个案例、130 个评测轮次。",
                "CTP100 是开发后冻结的受控主基准，不是完全未见测试集。",
                "CTP30 封闭验证集已单独冻结，不进入正式主实验入口。",
                "正式实验天气使用冻结 QWeather 快照，实验阶段不联网刷新天气。",
                "正式实验城际交通使用冻结成人二等座高铁/动车参考票价，不声称实时票价。",
                "预算金额只用于判断预算充足性，不自动触发住宿或餐饮升级。",
            ],
            "forbidden_claims": [
                "不能把 Day8 交付包说成正式实验结果。",
                "不能把 CTP100 说成完全未见测试集。",
                "不能用 CTP30 封闭验证结果继续调参后再声称其封闭性。",
                "不能在未运行正式四方法实验前宣称某个方法效果最好。",
                "不能声称天气或城际票价是实验运行时实时获取。",
            ],
        },
        "delivery_outputs": {},
    }


def write_day8_delivery_pack(
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    docs_report_path: str | Path | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Write ``day8_delivery_pack.json`` and ``day8_delivery_report.md``."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / DAY8_DELIVERY_PACK_JSON_NAME
    markdown_path = output / DAY8_DELIVERY_REPORT_MD_NAME
    pack = build_day8_delivery_pack(**kwargs)
    pack["delivery_outputs"] = {
        "day8_delivery_pack_json": json_path.as_posix(),
        "day8_delivery_report_md": markdown_path.as_posix(),
    }
    json_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_day8_delivery_report(pack), encoding="utf-8")
    docs_path: Path | None = None
    if docs_report_path is not None:
        docs_path = Path(docs_report_path)
        docs_path.parent.mkdir(parents=True, exist_ok=True)
        docs_path.write_text(render_day8_delivery_report(pack), encoding="utf-8")
    readiness = _dict(pack.get("readiness"))
    return {
        "status": "completed",
        "delivery_status": readiness.get("status"),
        "ready_for_formal_experiment": readiness.get("ready_for_formal_experiment"),
        "failed_checks": readiness.get("failed_checks") or [],
        "json": json_path.as_posix(),
        "markdown": markdown_path.as_posix(),
        "docs_report": docs_path.as_posix() if docs_path else None,
        "pack": pack,
    }


def render_day8_delivery_report(pack: Mapping[str, Any]) -> str:
    """Render the human-facing Day8 delivery report."""
    readiness = _dict(pack.get("readiness"))
    formal_input = _dict(pack.get("formal_input"))
    snapshots = _dict(pack.get("frozen_snapshots"))
    budget_gold = _dict(pack.get("budget_gold"))
    audit = _dict(pack.get("dataset_audit"))
    acceptance = _dict(pack.get("day8_acceptance_gates"))
    academic_design = _dict(pack.get("academic_experiment_design"))
    artifact_integrity = _dict(pack.get("formal_artifact_integrity"))
    pre_formal_validation = _dict(pack.get("pre_formal_validation"))
    preflight = _dict(pack.get("formal_preflight"))
    lines = [
        "# Day8 小任务五：正式实验输入冻结交付报告",
        "",
        "## 总状态",
        "",
        f"- delivery_status: `{readiness.get('status')}`",
        f"- ready_for_formal_experiment: `{readiness.get('ready_for_formal_experiment')}`",
        f"- failed_checks: `{readiness.get('failed_checks') or []}`",
        f"- interpretation: {readiness.get('interpretation')}",
        "",
        "## 正式实验入口",
        "",
        f"- benchmark_manifest: `{formal_input.get('benchmark_manifest')}`",
        f"- formal_dataset: `{formal_input.get('formal_dataset')}`",
        f"- dataset_version: `{formal_input.get('dataset_version')}`",
        f"- dataset_sha256: `{formal_input.get('dataset_sha256')}`",
        f"- case_count / turn_count: `{formal_input.get('case_count')}` / `{formal_input.get('turn_count')}`",
        f"- methods: `{formal_input.get('methods')}`",
        f"- expected_raw_run_count: `{formal_input.get('expected_raw_run_count')}`",
        "",
        "## 冻结数据快照",
        "",
        "| 数据 | 状态 | 版本/ID | 覆盖范围 | 哈希/规模 | 实验期是否允许联网刷新 |",
        "| --- | --- | --- | --- | --- | --- |",
        _snapshot_row("QWeather", _dict(snapshots.get("qweather"))),
        _snapshot_row("Intercity Rail", _dict(snapshots.get("intercity_transport"))),
        "",
        "## 预算金标与审计",
        "",
        f"- budget_policy_version: `{budget_gold.get('budget_policy_version')}`",
        f"- budget_gold_path: `{budget_gold.get('path')}`",
        f"- budget_gold_summary: `{budget_gold.get('summary')}`",
        f"- budget_gold_manual_review_scope: `{_nested(budget_gold, 'manual_review', 'confirmed_scope')}`",
        f"- economy_manual_review_status: `{_nested(budget_gold, 'economy_manual_review', 'review_status')}`",
        f"- economy_manual_review_city_count: `{_nested(budget_gold, 'economy_manual_review', 'summary', 'city_count')}`",
        f"- budget_review_rows: `{_nested(budget_gold, 'review', 'row_count')}`",
        f"- budget_review_issue_rows: `{_nested(budget_gold, 'review', 'issue_row_count')}`",
        f"- dataset_audit_status: `{audit.get('status')}`",
        f"- dataset_audit_issue_counts: `{audit.get('issue_counts')}`",
        "",
        "## Day8 验收门禁",
        "",
        f"- runner_acceptance_test: `{acceptance.get('runner_acceptance_test')}`",
        f"- runner_acceptance_130_turn_gate_locked: `{acceptance.get('runner_acceptance_130_turn_gate_locked')}`",
        f"- expected_method_result_count: `{acceptance.get('expected_method_result_count')}`",
        f"- no_date_weather_reminder_expected_count: `{acceptance.get('no_date_weather_reminder_expected_count')}`",
        f"- no_date_weather_reminder_audit: `{acceptance.get('no_date_weather_reminder_audit')}`",
        f"- planned_actual_consistency_metrics_declared: `{acceptance.get('planned_actual_consistency_metrics_declared')}`",
        f"- m2_template_stsr_compatibility_valid: `{acceptance.get('m2_template_stsr_compatibility_valid')}`",
        f"- bpcr_formal_metric_declared: `{acceptance.get('bpcr_formal_metric_declared')}`",
        "",
        "## 学术实验设计冻结",
        "",
        f"- design_status: `{academic_design.get('status')}`",
        f"- main_dataset_role: `{_nested(academic_design, 'main_benchmark', 'dataset_role')}`",
        f"- sealed_dataset_role: `{_nested(academic_design, 'sealed_validation', 'dataset_role')}`",
        f"- sealed_case_count / turn_count: "
        f"`{_nested(academic_design, 'sealed_validation', 'case_count')}` / "
        f"`{_nested(academic_design, 'sealed_validation', 'turn_count')}`",
        f"- sealed_methods: `{_nested(academic_design, 'sealed_validation', 'methods')}`",
        f"- design_errors: `{academic_design.get('errors') or []}`",
        "",
        "## 正式实验指纹",
        "",
        f"- integrity_schema: `{artifact_integrity.get('schema_version')}`",
        f"- combined_sha256: `{artifact_integrity.get('combined_sha256')}`",
        f"- git_commit: `{_nested(artifact_integrity, 'git', 'commit')}`",
        f"- git_worktree_clean: `{_nested(artifact_integrity, 'git', 'worktree_clean')}`",
        f"- git_status_count: `{len(_as_list(_nested(artifact_integrity, 'git', 'status_short')))}`",
        "",
        "## Formal preflight",
        "",
        f"- status: `{preflight.get('status')}`",
        f"- errors: `{preflight.get('errors') or []}`",
        f"- warnings: `{preflight.get('warnings') or []}`",
        "",
        "## 机器检查",
        "",
        "| check | passed |",
        "| --- | --- |",
    ]
    for key, value in _dict(readiness.get("checks")).items():
        lines.append(f"| {key} | `{value}` |")

    lines.extend(
        [
            "",
            "## Task D/E/F pre-formal real-API validation",
            "",
            f"- registry_status: `{pre_formal_validation.get('status')}`",
            f"- registry_path: `{pre_formal_validation.get('path')}`",
            f"- registry_sha256: `{pre_formal_validation.get('registry_sha256')}`",
            f"- transparent_warning_policy: "
            f"`{_nested(pre_formal_validation, 'summary', 'transparent_warning_policy')}`",
            f"- transparent_warning_count: "
            f"`{_nested(pre_formal_validation, 'summary', 'transparent_warning_count')}`",
            "",
            "| task | status | report hash match | warnings |",
            "| --- | --- | --- | ---: |",
        ]
    )
    for item in _as_dict_list(pre_formal_validation.get("tasks")):
        lines.append(
            f"| {item.get('task_id')} | `{item.get('status')}` | "
            f"`{item.get('registered_report_sha256') == item.get('actual_report_sha256')}` | "
            f"`{len(_as_dict_list(item.get('transparent_warnings')))}` |"
        )

    lines.extend(["", "## 交付文件清单", "", "| key | exists | sha256 | path |", "| --- | ---: | --- | --- |"])
    for item in _as_dict_list(pack.get("artifact_inventory")):
        lines.append(
            f"| {item.get('key')} | `{item.get('exists')}` | "
            f"`{item.get('sha256') or ''}` | `{item.get('path')}` |"
        )

    lines.extend(["", "## 下一步", ""])
    for item in _as_dict_list(pack.get("manual_next_steps")):
        lines.append(f"- [{item.get('priority')}] {item.get('item')}")

    lines.extend(["", "## 可复制命令", ""])
    for command in _as_dict_list(pack.get("handoff_commands")):
        lines.append(f"### {command.get('name')}")
        lines.append("")
        lines.append(f"```powershell\n{command.get('command')}\n```")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _readiness_checks(
    *,
    benchmark_doc: Any,
    benchmark_cases: list[dict[str, Any]],
    benchmark_error: str | None,
    dataset_doc: Any,
    dataset_cases: list[dict[str, Any]],
    dataset_error: str | None,
    dataset_sha256: str | None,
    gold_doc: Mapping[str, Any],
    audit_doc: Mapping[str, Any],
    review_summary: Mapping[str, Any],
    qweather_report: Mapping[str, Any],
    intercity_report: Mapping[str, Any],
    economy_review_report: Mapping[str, Any],
    academic_design_report: Mapping[str, Any],
    formal_artifact_integrity_report: Mapping[str, Any],
    pre_formal_validation_report: Mapping[str, Any],
    preflight_report: Mapping[str, Any],
    artifacts: list[dict[str, Any]],
    expected_case_count: int,
    expected_turn_count: int,
    expected_budget_gold_count: int,
    expected_skipped_count: int,
    require_clean_git: bool,
) -> dict[str, bool]:
    gold_summary = _dict(gold_doc.get("summary"))
    manual_review = _dict(gold_doc.get("manual_review"))
    benchmark_claim_policy = _dict(_dict(dataset_doc).get("claim_policy"))
    academic_checks = _dict(academic_design_report.get("checks"))
    academic_main = _dict(academic_design_report.get("main_benchmark"))
    academic_sealed = _dict(academic_design_report.get("sealed_validation"))
    integrity_artifacts = _dict(formal_artifact_integrity_report.get("artifacts"))
    integrity_git = _dict(formal_artifact_integrity_report.get("git"))
    confirmed_scope = _as_list(manual_review.get("confirmed_scope"))
    excluded_scope = _as_list(manual_review.get("excluded_scope"))
    formal_main_tiers = _as_list(manual_review.get("formal_main_experiment_tiers"))
    non_economy_budget_records = [
        record.get("unit_id")
        for record in _as_dict_list(gold_doc.get("records"))
        if record.get("status") == "generated"
        and (
            _nested(record, "budget_policy_v2", "hotel_tier") != "economy"
            or _nested(record, "budget_policy_v2", "food_tier") != "economy"
        )
    ]
    benchmark_case_files = _as_list(_dict(benchmark_doc).get("case_files"))
    return {
        "benchmark_manifest_loads": benchmark_error is None,
        "formal_dataset_loads": dataset_error is None,
        "benchmark_points_to_ctp100_formal_v2": benchmark_case_files == ["ctp100_formal_v2.json"],
        "benchmark_and_dataset_versions_match": _dict(benchmark_doc).get("dataset_version")
        == _dict(dataset_doc).get("dataset_version"),
        "formal_dataset_case_count_matches": len(dataset_cases) == expected_case_count,
        "formal_dataset_turn_count_matches": _turn_count(dataset_cases) == expected_turn_count,
        "benchmark_expanded_case_count_matches": len(benchmark_cases) == expected_case_count,
        "benchmark_expanded_turn_count_matches": _turn_count(benchmark_cases) == expected_turn_count,
        "pre_formal_validation_passed": pre_formal_validation_report.get("status") == "passed",
        "formal_preflight_passed": preflight_report.get("status") == "passed",
        "qweather_snapshot_valid": qweather_report.get("valid") is True,
        "qweather_runtime_refresh_forbidden": qweather_report.get("runtime_online_refresh_allowed") is False
        and qweather_report.get("real_time_api_allowed") is False,
        "intercity_snapshot_valid": intercity_report.get("valid") is True,
        "intercity_route_count_matches": intercity_report.get("route_count")
        == DEFAULT_EXPECTED_INTERCITY_ROUTE_COUNT,
        "intercity_runtime_refresh_forbidden": intercity_report.get("runtime_online_refresh_allowed") is False
        and intercity_report.get("real_time_api_allowed") is False
        and intercity_report.get("real_time_price_claim_allowed") is False,
        "budget_gold_policy_version_matches": gold_doc.get("budget_policy_version")
        == BUDGET_POLICY_VERSION,
        "budget_gold_schema_formal": gold_doc.get("schema_version")
        == BUDGET_GOLD_SCHEMA_VERSION,
        "budget_gold_status_formal_frozen": gold_doc.get("gold_status")
        == BUDGET_GOLD_STATUS,
        "budget_gold_review_confirmed": gold_doc.get("review_status")
        == BUDGET_GOLD_REVIEW_STATUS,
        "economy_budget_manual_review_valid": economy_review_report.get("valid") is True,
        "budget_gold_manual_review_ledger_linked": _nested(
            manual_review,
            "review_artifacts",
            "economy_manual_review_json",
        )
        == economy_review_report.get("path")
        and manual_review.get("review_sha256") == economy_review_report.get("sha256"),
        "budget_gold_confirmed_scope_economy_only": confirmed_scope
        == list(ECONOMY_BUDGET_CONFIRMED_SCOPE),
        "budget_gold_formal_tiers_economy_only": formal_main_tiers
        == list(ECONOMY_BUDGET_FORMAL_MAIN_TIERS),
        "budget_gold_excludes_comfort_premium_confirmation": set(ECONOMY_BUDGET_EXCLUDED_SCOPE)
        <= set(excluded_scope)
        and not (set(confirmed_scope) & set(ECONOMY_BUDGET_EXCLUDED_SCOPE)),
        "budget_gold_generated_records_use_economy_tiers": non_economy_budget_records == [],
        "budget_gold_matches_current_dataset": bool(dataset_sha256)
        and gold_doc.get("source_dataset_sha256") == dataset_sha256,
        "budget_gold_counts_match": gold_summary.get("evaluation_unit_count") == expected_turn_count
        and gold_summary.get("budget_gold_count") == expected_budget_gold_count
        and gold_summary.get("skipped_count") == expected_skipped_count,
        "budget_review_clean": review_summary.get("row_count") == expected_budget_gold_count
        and review_summary.get("issue_row_count") == 0,
        "dataset_audit_passed": audit_doc.get("status") == "passed"
        and audit_doc.get("issue_counts") == {},
        "dataset_audit_matches_current_dataset": bool(dataset_sha256)
        and audit_doc.get("dataset_sha256") == dataset_sha256,
        "runner_acceptance_130_turn_gate_locked": _runner_acceptance_gate_locked(
            expected_turn_count=expected_turn_count,
            expected_no_date_reminder_count=EXPECTED_NO_DATE_WEATHER_REMINDER_COUNT,
        ),
        "no_date_weather_reminder_18_of_18": _targeted_check_count(
            audit_doc,
            "day8_no_date_trip_planning_requires_weather_reminder",
        )
        == EXPECTED_NO_DATE_WEATHER_REMINDER_COUNT,
        "planned_actual_consistency_metrics_declared": _planned_actual_consistency_metrics_declared(),
        "m2_template_stsr_compatibility_valid": _m2_template_stsr_compatibility_valid(),
        "bpcr_formal_metric_declared": _bpcr_formal_metric_declared(),
        "academic_experiment_design_valid": academic_design_report.get("status") == "passed",
        "ctp100_declared_post_development_controlled": _dict(dataset_doc).get("dataset_role")
        == MAIN_BENCHMARK_ROLE
        and academic_main.get("dataset_role") == MAIN_BENCHMARK_ROLE,
        "ctp100_not_claimed_unseen": benchmark_claim_policy.get("claim_allowed_as_unseen")
        is False,
        "sealed_validation_dataset_valid": academic_sealed.get("dataset_role")
        == SEALED_VALIDATION_ROLE
        and academic_sealed.get("case_count") == EXPECTED_SEALED_CASE_COUNT
        and academic_sealed.get("turn_count") == EXPECTED_SEALED_TURN_COUNT
        and _nested(academic_design_report, "sealed_quality", "status") == "passed",
        "sealed_validation_not_in_main_benchmark": academic_checks.get(
            "sealed_dataset_not_in_main_benchmark"
        )
        is True
        and academic_checks.get("sealed_dataset_not_in_main_comparisons") is True,
        "sealed_validation_methods_m2_m3_only": tuple(
            _as_list(_nested(academic_design_report, "sealed_validation", "methods"))
        )
        == SEALED_VALIDATION_METHODS,
        "formal_artifact_integrity_schema_valid": formal_artifact_integrity_report.get(
            "schema_version"
        )
        == FORMAL_ARTIFACT_INTEGRITY_SCHEMA_VERSION,
        "formal_artifact_integrity_all_required_exist": formal_artifact_integrity_report.get(
            "all_required_artifacts_exist"
        )
        is True,
        "current_commit_recorded": bool(integrity_git.get("commit"))
        and integrity_git.get("commit") != "unknown",
        "git_worktree_clean": (integrity_git.get("worktree_clean") is True)
        if require_clean_git
        else True,
        "evaluation_rule_catalog_hash_recorded": _is_sha256(
            _nested(integrity_artifacts, "evaluation_rule_catalog", "sha256")
        ),
        "independent_evaluator_code_hash_recorded": _is_sha256(
            _nested(integrity_artifacts, "independent_evaluator_code", "sha256")
        ),
        "experiment_runner_code_hash_recorded": _is_sha256(
            _nested(integrity_artifacts, "experiment_runner_code", "sha256")
        ),
        "formal_preflight_records_artifact_integrity": _nested(
            preflight_report,
            "artifact_integrity",
            "schema_version",
        )
        == FORMAL_ARTIFACT_INTEGRITY_SCHEMA_VERSION,
        "evaluation_rule_catalog_declares_day8_formal": _read_json_object(
            DEFAULT_EVALUATION_RULE_CATALOG_PATH
        ).get("catalog_id")
        == FORMAL_EVALUATION_RULE_CATALOG_ID,
        "all_required_artifacts_exist": all(item.get("exists") is True for item in artifacts),
        "all_existing_artifact_hashes_recorded": all(
            _is_sha256(item.get("sha256")) for item in artifacts if item.get("exists") is True
        ),
    }


def _validated_qweather_snapshot() -> dict[str, Any]:
    try:
        snapshot = validate_qweather_snapshot()
    except Exception as exc:  # pragma: no cover - surfaced in delivery pack
        return {"valid": False, "error": str(exc)}
    return {
        "valid": True,
        "provider": snapshot.get("provider"),
        "snapshot_id": snapshot.get("snapshot_id"),
        "combined_sha256": snapshot.get("combined_sha256"),
        "forecast_horizon_days": snapshot.get("forecast_horizon_days"),
        "forecast_start_date": snapshot.get("forecast_start_date"),
        "forecast_end_date": snapshot.get("forecast_end_date"),
        "cities": snapshot.get("cities"),
        "file_count": len(snapshot.get("files") or []),
        "real_time_api_allowed": snapshot.get("real_time_api_allowed"),
        "runtime_online_refresh_allowed": snapshot.get("runtime_online_refresh_allowed"),
    }


def _validated_intercity_snapshot() -> dict[str, Any]:
    try:
        snapshot = validate_intercity_transport_snapshot()
    except Exception as exc:  # pragma: no cover - surfaced in delivery pack
        return {"valid": False, "error": str(exc)}
    return {
        "valid": True,
        "provider": snapshot.get("provider"),
        "snapshot_id": snapshot.get("snapshot_id"),
        "source_name": snapshot.get("source_name"),
        "combined_sha256": snapshot.get("combined_sha256"),
        "route_count": snapshot.get("route_count"),
        "fare_snapshot_date": snapshot.get("fare_snapshot_date"),
        "transport_mode": snapshot.get("transport_mode"),
        "seat_class": snapshot.get("seat_class"),
        "real_time_api_allowed": snapshot.get("real_time_api_allowed"),
        "runtime_online_refresh_allowed": snapshot.get("runtime_online_refresh_allowed"),
        "real_time_price_claim_allowed": snapshot.get("real_time_price_claim_allowed"),
    }


def _validated_economy_budget_review(path: Path) -> dict[str, Any]:
    try:
        review = validate_economy_budget_manual_review(path)
    except Exception as exc:  # pragma: no cover - surfaced in delivery pack
        return {"valid": False, "path": _display_path(path), "error": str(exc)}
    return {
        "valid": True,
        "path": review.get("path"),
        "sha256": review.get("sha256"),
        "review_status": review.get("review_status"),
        "reviewer": review.get("reviewer"),
        "review_date": review.get("review_date"),
        "confirmed_scope": review.get("confirmed_scope"),
        "excluded_scope": review.get("excluded_scope"),
        "formal_main_experiment_tiers": review.get("formal_main_experiment_tiers"),
        "summary": review.get("summary") or {},
    }


def _budget_review_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "row_count": 0, "issue_row_count": None}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    issue_rows = [
        row
        for row in rows
        if str(row.get("issue_flags") or "").strip() not in {"", "[]"}
    ]
    return {
        "exists": True,
        "path": _display_path(path),
        "row_count": len(rows),
        "issue_row_count": len(issue_rows),
        "issue_units": [row.get("unit_id") for row in issue_rows],
    }


def _day8_acceptance_gate_report(
    *,
    audit_doc: Mapping[str, Any],
    expected_turn_count: int,
) -> dict[str, Any]:
    no_date_check = _targeted_check(
        audit_doc,
        "day8_no_date_trip_planning_requires_weather_reminder",
    )
    return {
        "runner_acceptance_test": _display_path(DEFAULT_RUNNER_ACCEPTANCE_TEST_PATH),
        "runner_acceptance_130_turn_gate_locked": _runner_acceptance_gate_locked(
            expected_turn_count=expected_turn_count,
            expected_no_date_reminder_count=EXPECTED_NO_DATE_WEATHER_REMINDER_COUNT,
        ),
        "expected_turn_count": expected_turn_count,
        "expected_method_result_count": expected_turn_count * len(EXPERIMENT_METHODS),
        "no_date_weather_reminder_expected_count": EXPECTED_NO_DATE_WEATHER_REMINDER_COUNT,
        "no_date_weather_reminder_audit": no_date_check,
        "planned_actual_consistency_metrics_declared": _planned_actual_consistency_metrics_declared(),
        "m2_template_stsr_compatibility_valid": _m2_template_stsr_compatibility_valid(),
        "bpcr_formal_metric_declared": _bpcr_formal_metric_declared(),
    }


def _targeted_check(audit_doc: Mapping[str, Any], check_id: str) -> dict[str, Any]:
    for item in _as_dict_list(audit_doc.get("targeted_checks")):
        if item.get("check_id") == check_id:
            return dict(item)
    return {"check_id": check_id, "status": "missing"}


def _targeted_check_count(audit_doc: Mapping[str, Any], check_id: str) -> int | None:
    check = _targeted_check(audit_doc, check_id)
    actual = check.get("actual") if isinstance(check.get("actual"), Mapping) else {}
    if check.get("status") != "passed":
        return None
    violations = actual.get("violations")
    if isinstance(violations, list) and violations:
        return None
    value = actual.get("count")
    return int(value) if isinstance(value, int) else None


def _runner_acceptance_gate_locked(
    *,
    expected_turn_count: int,
    expected_no_date_reminder_count: int,
) -> bool:
    if not DEFAULT_RUNNER_ACCEPTANCE_TEST_PATH.exists():
        return False
    try:
        source = DEFAULT_RUNNER_ACCEPTANCE_TEST_PATH.read_text(encoding="utf-8")
    except OSError:
        return False
    return (
        "test_day8_task1_full_130_turn_runner_acceptance" in source
        and f"expected_turn_count={expected_turn_count}" in source.replace(" ", "")
        and f"expected_no_date_reminder_count={expected_no_date_reminder_count}"
        in source.replace(" ", "")
    )


def _planned_actual_consistency_metrics_declared() -> bool:
    evaluator_source = _read_text(DEFAULT_INDEPENDENT_EVALUATOR_CODE_PATH)
    runner_source = _read_text(ROOT / "app" / "core" / "experiment_runner.py")
    required = (
        "planned_actual_agent_consistency",
        "planned_actual_tool_consistency",
        "planned_executed_agent_coverage",
        "planned_executed_tool_coverage",
    )
    return all(token in evaluator_source and token in runner_source for token in required)


def _m2_template_stsr_compatibility_valid() -> bool:
    try:
        validate_m2_template_stsr_compatibility(DEFAULT_EVALUATION_RULE_CATALOG_PATH)
    except Exception:
        return False
    return True


def _bpcr_formal_metric_declared() -> bool:
    evaluator_source = _read_text(DEFAULT_INDEPENDENT_EVALUATOR_CODE_PATH)
    gate_source = _read_text(DEFAULT_FORMAL_GATE_CODE_PATH)
    catalog = _read_json_object(DEFAULT_EVALUATION_RULE_CATALOG_PATH)
    rules = catalog.get("rules") if isinstance(catalog.get("rules"), list) else []
    return (
        "bpcr" in evaluator_source
        and "bpcr" in gate_source
        and any(
            str(rule.get("id") or "").startswith("H_BUDGET")
            for rule in rules
            if isinstance(rule, Mapping)
        )
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _compact_preflight(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": report.get("schema_version"),
        "status": report.get("status"),
        "errors": report.get("errors") or [],
        "warnings": report.get("warnings") or [],
        "benchmark": report.get("benchmark") or {},
        "run": report.get("run") or {},
        "environment": report.get("environment") or {},
        "qweather_snapshot": report.get("qweather_snapshot") or {},
        "intercity_transport_snapshot": report.get("intercity_transport_snapshot") or {},
        "academic_experiment_design": report.get("academic_experiment_design") or {},
        "artifact_integrity": report.get("artifact_integrity") or {},
        "pre_formal_validation": report.get("pre_formal_validation") or {},
        "day8_delivery_pack": report.get("day8_delivery_pack") or {},
        "policy": report.get("policy") or {},
    }


def _artifact_inventory(paths: Mapping[str, Path]) -> list[dict[str, Any]]:
    return [_artifact_item(key, path) for key, path in paths.items()]


def _artifact_item(key: str, path: Path) -> dict[str, Any]:
    exists = path.exists()
    return {
        "key": key,
        "path": _display_path(path),
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else None,
        "sha256": _file_sha256(path) if exists else None,
    }


def _handoff_commands() -> list[dict[str, str]]:
    return [
        {
            "name": "验证学术实验设计冻结",
            "command": "python experiments/validate_academic_experiment_design.py",
        },
        {
            "name": "重新生成预算金标",
            "command": "python experiments/generate_ctp100_budget_gold_v2.py",
        },
        {
            "name": "重新生成预算审阅表",
            "command": "python experiments/generate_ctp100_budget_gold_review_v2.py",
        },
        {
            "name": "重新生成题库审计报告",
            "command": "python experiments/audit_ctp100_formal_v2.py",
        },
        {
            "name": "重新生成 Task D/E/F 预正式验证注册表",
            "command": "python experiments/build_pre_formal_validation_registry.py",
        },
        {
            "name": "重新生成 Day8 交付包",
            "command": "python experiments/build_day8_delivery_pack.py",
        },
        {
            "name": "正式实验预检查",
            "command": (
                "python experiments/run_formal_experiment.py "
                "--expected-cases 100 --preflight-only --skip-llm-config-check"
            ),
        },
        {
            "name": "正式四方法实验",
            "command": (
                "python experiments/run_formal_experiment.py "
                "--expected-cases 100 --strict-paper-readiness"
            ),
        },
    ]


def _manual_next_steps(status: str, failed_checks: list[str]) -> list[dict[str, str]]:
    if status != "day8_delivery_ready":
        return [
            {
                "priority": "P0",
                "item": f"先修复 Day8 交付包阻塞项：{', '.join(failed_checks)}",
            }
        ]
    return [
        {
            "priority": "P0",
            "item": "可以进入正式四方法实验；运行前不要再修改题库、预算金标或冻结快照。",
        },
        {
            "priority": "P1",
            "item": "正式实验完成后，再生成论文结果包和论文初稿材料。",
        },
    ]


def _snapshot_row(name: str, snapshot: Mapping[str, Any]) -> str:
    if name == "QWeather":
        coverage = (
            f"{snapshot.get('forecast_start_date')} 至 {snapshot.get('forecast_end_date')}"
        )
        scale = (
            f"{snapshot.get('combined_sha256')} / "
            f"{len(snapshot.get('cities') or [])} cities, "
            f"{snapshot.get('forecast_horizon_days')} days"
        )
    else:
        coverage = f"{snapshot.get('transport_mode')} / {snapshot.get('seat_class')}"
        scale = f"{snapshot.get('combined_sha256')} / {snapshot.get('route_count')} routes"
    return (
        f"| {name} | `{snapshot.get('valid')}` | `{snapshot.get('snapshot_id')}` | "
        f"{coverage} | `{scale}` | `{snapshot.get('runtime_online_refresh_allowed')}` |"
    )


def _load_document(path: Path) -> tuple[Any, list[dict[str, Any]], str | None]:
    try:
        document, cases = load_benchmark_document(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return None, [], str(exc)
    return document, cases, None


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


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


def _turn_count(cases: list[dict[str, Any]]) -> int:
    total = 0
    for case in cases:
        turns = case.get("turns")
        total += len(turns) if isinstance(turns, list) and turns else 1
    return total


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text.lower())


def _interpretation(status: str, failed_checks: list[str]) -> str:
    if status == "day8_delivery_ready":
        return "Day8 formal inputs are frozen and ready for the formal four-method experiment."
    return "Day8 delivery is blocked; fix failed_checks before running the formal experiment."


def _timestamp_for_id(iso_timestamp: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_timestamp)
    except ValueError:
        return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, tuple | set):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def _nested(value: Mapping[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current
