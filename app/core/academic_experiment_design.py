"""Academic experiment design freeze checks for the Tourism_Agent paper run.

This module is intentionally read-only.  It validates the paper-facing
experiment design before any formal result is produced, especially the split
between the post-development controlled CTP-100 main benchmark and the CTP-30
sealed validation set.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from app.core.benchmark_dataset_validator import (
    build_benchmark_dataset_quality_report,
)
from app.core.experiment_method_contract import EXPERIMENT_METHODS
from app.core.fixed_data import canonical_json_sha256


ACADEMIC_EXPERIMENT_DESIGN_SCHEMA_VERSION = "ctp-academic-experiment-design-v1"
ACADEMIC_EXPERIMENT_DESIGN_REPORT_SCHEMA_VERSION = (
    "ctp-academic-experiment-design-report-v1"
)
ACADEMIC_EXPERIMENT_DESIGN_VERSION = "CTP-GMAS-ACADEMIC-DESIGN-v2"

MAIN_BENCHMARK_ROLE = "post_development_frozen_controlled_main_benchmark"
SEALED_VALIDATION_ROLE = "sealed_validation_after_main_design_freeze"
MAIN_DATASET_ID = "ctp100_formal_v2"
MAIN_DATASET_VERSION = "2026-08-21-formal-v3-runtime-control-freeze"
SEALED_DATASET_ID = "ctp30_sealed_validation_v1"
SEALED_VALIDATION_METHODS = ("fixed_multi_agent", "adaptive_multi_agent")
EXPECTED_FORMAL_RESULT_HARD_TIMEOUT_MODE = "subprocess_per_result"
EXPECTED_FORMAL_PROVIDER_ACCOUNTING = "base_url_derived_openai_compatible_provider"
EXPECTED_DECISION_NORMALIZATION_DIAGNOSTIC_METRICS = (
    "raw_decision_success_rate",
    "normalizer_recovery_rate",
    "pipeline_completion_rate",
)
EXPECTED_PRE_FORMAL_VALIDATION_TASKS = (
    "task_d_m0_real_api",
    "task_e_four_method_real_api",
    "task_f_multiturn_real_api",
)
EXPECTED_MAIN_CASE_COUNT = 100
EXPECTED_MAIN_TURN_COUNT = 130
EXPECTED_SEALED_CASE_COUNT = 30
EXPECTED_SEALED_TURN_COUNT = 30

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ACADEMIC_DESIGN_JSON_PATH = (
    ROOT / "experiments" / "academic_experiment_design_v1.json"
)
DEFAULT_ACADEMIC_DESIGN_MD_PATH = ROOT / "docs" / "Academic_Experiment_Design_v1.md"
DEFAULT_MAIN_BENCHMARK_MANIFEST_PATH = ROOT / "experiments" / "benchmark.json"
DEFAULT_MAIN_DATASET_PATH = ROOT / "experiments" / "ctp100_formal_v2.json"
DEFAULT_SEALED_VALIDATION_PATH = ROOT / "experiments" / "ctp30_sealed_validation_v1.json"
DEFAULT_COMPARISON_PATHS = (
    ROOT / "experiments" / "ctp120_dev.json",
    ROOT / "experiments" / "benchmark_test.json",
    ROOT / "experiments" / "day8_dev_experiment_cases_v1_3.json",
)


class AcademicExperimentDesignError(RuntimeError):
    """Raised when the frozen academic design is invalid."""


def build_academic_experiment_design_report(
    *,
    design_path: str | Path = DEFAULT_ACADEMIC_DESIGN_JSON_PATH,
    design_doc_path: str | Path = DEFAULT_ACADEMIC_DESIGN_MD_PATH,
    benchmark_manifest_path: str | Path = DEFAULT_MAIN_BENCHMARK_MANIFEST_PATH,
    main_dataset_path: str | Path = DEFAULT_MAIN_DATASET_PATH,
    sealed_validation_path: str | Path = DEFAULT_SEALED_VALIDATION_PATH,
    comparison_paths: tuple[str | Path, ...] = DEFAULT_COMPARISON_PATHS,
) -> dict[str, Any]:
    """Validate the paper-level experiment design freeze."""
    design_file = Path(design_path)
    design_doc = Path(design_doc_path)
    benchmark_file = Path(benchmark_manifest_path)
    main_file = Path(main_dataset_path)
    sealed_file = Path(sealed_validation_path)

    errors: list[str] = []
    warnings: list[str] = []

    design = _read_json_object(design_file, errors, label="academic design")
    benchmark_doc = _read_json_object(benchmark_file, errors, label="benchmark manifest")
    main_doc, main_cases = _load_benchmark(main_file, errors, label="main dataset")
    sealed_doc, sealed_cases = _load_benchmark(
        sealed_file,
        errors,
        label="sealed validation dataset",
    )
    comparison_splits = _comparison_splits(comparison_paths, errors)

    main_quality = build_benchmark_dataset_quality_report(
        document=main_doc,
        cases=main_cases,
        expected_case_count=EXPECTED_MAIN_CASE_COUNT,
        strict_formal=True,
        comparison_splits=comparison_splits,
    )
    sealed_quality = build_benchmark_dataset_quality_report(
        document=sealed_doc,
        cases=sealed_cases,
        expected_case_count=EXPECTED_SEALED_CASE_COUNT,
        strict_formal=True,
        comparison_splits={
            "controlled_main_benchmark": main_cases,
            **comparison_splits,
        },
    )

    checks = _checks(
        design=design,
        benchmark_doc=benchmark_doc,
        main_doc=main_doc,
        main_cases=main_cases,
        sealed_doc=sealed_doc,
        sealed_cases=sealed_cases,
        design_file=design_file,
        design_doc=design_doc,
        benchmark_file=benchmark_file,
        main_file=main_file,
        sealed_file=sealed_file,
        main_quality=main_quality,
        sealed_quality=sealed_quality,
    )
    for key, value in checks.items():
        if value is not True:
            errors.append(f"academic_design: {key} failed")
    if main_quality.get("status") != "passed":
        errors.extend(f"main_quality: {item}" for item in main_quality.get("errors", []))
    if sealed_quality.get("status") != "passed":
        errors.extend(f"sealed_quality: {item}" for item in sealed_quality.get("errors", []))
    warnings.extend(f"main_quality: {item}" for item in main_quality.get("warnings", []))
    warnings.extend(f"sealed_quality: {item}" for item in sealed_quality.get("warnings", []))

    status = "passed" if not errors else "failed"
    return {
        "schema_version": ACADEMIC_EXPERIMENT_DESIGN_REPORT_SCHEMA_VERSION,
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "design": {
            "path": _display_path(design_file),
            "sha256": _file_sha256(design_file) if design_file.exists() else None,
            "doc_path": _display_path(design_doc),
            "doc_sha256": _file_sha256(design_doc) if design_doc.exists() else None,
            "schema_version": design.get("schema_version"),
            "design_version": design.get("design_version"),
            "freeze_status": design.get("freeze_status"),
            "freeze_date": design.get("freeze_date"),
        },
        "main_benchmark": {
            "manifest_path": _display_path(benchmark_file),
            "manifest_sha256": _file_sha256(benchmark_file) if benchmark_file.exists() else None,
            "dataset_path": _display_path(main_file),
            "dataset_sha256": canonical_json_sha256(main_doc) if main_doc else None,
            "dataset_id": main_doc.get("dataset_id"),
            "dataset_version": main_doc.get("dataset_version"),
            "dataset_role": main_doc.get("dataset_role"),
            "case_count": len(main_cases),
            "turn_count": _turn_count(main_cases),
            "quality_status": main_quality.get("status"),
        },
        "sealed_validation": {
            "dataset_path": _display_path(sealed_file),
            "dataset_sha256": canonical_json_sha256(sealed_doc) if sealed_doc else None,
            "dataset_id": sealed_doc.get("dataset_id"),
            "dataset_role": sealed_doc.get("dataset_role"),
            "case_count": len(sealed_cases),
            "turn_count": _turn_count(sealed_cases),
            "quality_status": sealed_quality.get("status"),
            "methods": list(SEALED_VALIDATION_METHODS),
        },
        "main_quality": _compact_quality(main_quality),
        "sealed_quality": _compact_quality(sealed_quality),
        "runtime_controls": _dict(design.get("runtime_controls")),
        "pre_formal_validation": _dict(design.get("pre_formal_validation")),
        "diagnostic_metrics": _dict(design.get("diagnostic_metrics")),
    }


def assert_academic_experiment_design_valid(report: Mapping[str, Any]) -> None:
    if report.get("status") == "passed":
        return
    errors = report.get("errors") if isinstance(report.get("errors"), list) else []
    details = "\n".join(f"- {error}" for error in errors) or "- unknown design error"
    raise AcademicExperimentDesignError(
        f"academic experiment design validation failed:\n{details}"
    )


def validate_academic_experiment_design(**kwargs: Any) -> dict[str, Any]:
    report = build_academic_experiment_design_report(**kwargs)
    assert_academic_experiment_design_valid(report)
    return report


def render_academic_experiment_design_report(report: Mapping[str, Any]) -> str:
    """Render a compact markdown validation report."""
    design = _dict(report.get("design"))
    main = _dict(report.get("main_benchmark"))
    sealed = _dict(report.get("sealed_validation"))
    pre_formal_validation = _dict(report.get("pre_formal_validation"))
    diagnostics = _dict(report.get("diagnostic_metrics"))
    decision_normalization = _dict(diagnostics.get("decision_normalization"))
    lines = [
        "# Academic Experiment Design Validation v2",
        "",
        f"- status: `{report.get('status')}`",
        f"- errors: `{report.get('errors') or []}`",
        f"- warnings: `{report.get('warnings') or []}`",
        "",
        "## Design freeze",
        "",
        f"- design_version: `{design.get('design_version')}`",
        f"- freeze_status: `{design.get('freeze_status')}`",
        f"- freeze_date: `{design.get('freeze_date')}`",
        f"- design_sha256: `{design.get('sha256')}`",
        "",
        "## Main benchmark",
        "",
        f"- dataset_id: `{main.get('dataset_id')}`",
        f"- dataset_version: `{main.get('dataset_version')}`",
        f"- dataset_role: `{main.get('dataset_role')}`",
        f"- case_count / turn_count: `{main.get('case_count')}` / `{main.get('turn_count')}`",
        f"- quality_status: `{main.get('quality_status')}`",
        "",
        "## Sealed validation",
        "",
        f"- dataset_id: `{sealed.get('dataset_id')}`",
        f"- dataset_role: `{sealed.get('dataset_role')}`",
        f"- case_count / turn_count: `{sealed.get('case_count')}` / `{sealed.get('turn_count')}`",
        f"- methods: `{sealed.get('methods')}`",
        f"- quality_status: `{sealed.get('quality_status')}`",
        "",
        "## Pre-formal validation",
        "",
        f"- registry_file: `{pre_formal_validation.get('registry_file')}`",
        f"- required_tasks: `{pre_formal_validation.get('required_tasks')}`",
        f"- warning_policy: `{pre_formal_validation.get('warning_policy')}`",
        "",
        "## Diagnostic metrics",
        "",
        f"- decision_normalization_metrics: `{decision_normalization.get('metrics')}`",
        f"- decision_normalization_formulas: `{decision_normalization.get('formulas')}`",
        f"- paper_usage: `{decision_normalization.get('paper_usage')}`",
        "",
        "## Checks",
        "",
        "| check | passed |",
        "| --- | --- |",
    ]
    for key, value in _dict(report.get("checks")).items():
        lines.append(f"| {key} | `{value}` |")
    return "\n".join(lines).rstrip() + "\n"


def _checks(
    *,
    design: Mapping[str, Any],
    benchmark_doc: Mapping[str, Any],
    main_doc: Mapping[str, Any],
    main_cases: list[dict[str, Any]],
    sealed_doc: Mapping[str, Any],
    sealed_cases: list[dict[str, Any]],
    design_file: Path,
    design_doc: Path,
    benchmark_file: Path,
    main_file: Path,
    sealed_file: Path,
    main_quality: Mapping[str, Any],
    sealed_quality: Mapping[str, Any],
) -> dict[str, bool]:
    case_files = _as_text_list(benchmark_doc.get("case_files"))
    comparison_files = _as_text_list(benchmark_doc.get("comparison_files"))
    sealed_name = sealed_file.name
    main_design = _dict(design.get("main_benchmark"))
    sealed_design = _dict(design.get("sealed_validation"))
    statistical_plan = _dict(design.get("statistical_plan"))
    claim_boundaries = _dict(design.get("claim_boundaries"))
    runtime_controls = _dict(design.get("runtime_controls"))
    pre_formal_validation = _dict(design.get("pre_formal_validation"))
    diagnostic_metrics = _dict(design.get("diagnostic_metrics"))
    decision_normalization = _dict(diagnostic_metrics.get("decision_normalization"))
    decision_metric_names = tuple(_as_text_list(decision_normalization.get("metrics")))
    decision_formulas = _dict(decision_normalization.get("formulas"))

    return {
        "design_json_exists": design_file.exists(),
        "design_markdown_exists": design_doc.exists(),
        "schema_version_matches": design.get("schema_version")
        == ACADEMIC_EXPERIMENT_DESIGN_SCHEMA_VERSION,
        "design_version_matches": design.get("design_version")
        == ACADEMIC_EXPERIMENT_DESIGN_VERSION,
        "freeze_before_formal_results": design.get("freeze_status")
        == "frozen_before_formal_results",
        "freeze_date_recorded": _valid_iso_date(design.get("freeze_date")),
        "main_dataset_id_matches": main_doc.get("dataset_id") == MAIN_DATASET_ID,
        "main_dataset_version_matches": main_doc.get("dataset_version")
        == MAIN_DATASET_VERSION,
        "benchmark_dataset_version_matches_main": benchmark_doc.get("dataset_version")
        == main_doc.get("dataset_version"),
        "main_dataset_role_controlled": main_doc.get("dataset_role") == MAIN_BENCHMARK_ROLE,
        "main_dataset_not_claimed_unseen": _dict(main_doc.get("claim_policy")).get(
            "claim_allowed_as_unseen"
        )
        is False,
        "main_design_role_matches": main_design.get("role") == MAIN_BENCHMARK_ROLE,
        "main_design_declares_not_unseen": main_design.get("claim_allowed_as_unseen")
        is False,
        "main_case_count_matches": len(main_cases) == EXPECTED_MAIN_CASE_COUNT,
        "main_turn_count_matches": _turn_count(main_cases) == EXPECTED_MAIN_TURN_COUNT,
        "main_quality_passed": main_quality.get("status") == "passed",
        "benchmark_points_only_to_main_ctp100": case_files == [main_file.name],
        "sealed_dataset_not_in_main_benchmark": sealed_name not in set(case_files),
        "sealed_dataset_not_in_main_comparisons": sealed_name not in set(comparison_files),
        "sealed_dataset_id_matches": sealed_doc.get("dataset_id") == SEALED_DATASET_ID,
        "sealed_dataset_role_matches": sealed_doc.get("dataset_role")
        == SEALED_VALIDATION_ROLE,
        "sealed_design_role_matches": sealed_design.get("role") == SEALED_VALIDATION_ROLE,
        "sealed_case_count_matches": len(sealed_cases) == EXPECTED_SEALED_CASE_COUNT,
        "sealed_turn_count_matches": _turn_count(sealed_cases) == EXPECTED_SEALED_TURN_COUNT,
        "sealed_quality_passed": sealed_quality.get("status") == "passed",
        "sealed_validation_methods_are_m2_m3_only": tuple(
            _as_text_list(sealed_design.get("methods"))
        )
        == SEALED_VALIDATION_METHODS,
        "main_methods_are_four_method_comparison": tuple(
            _as_text_list(main_design.get("methods"))
        )
        == EXPERIMENT_METHODS,
        "primary_comparison_is_m3_vs_m2": statistical_plan.get("primary_comparison")
        == "adaptive_multi_agent_vs_fixed_multi_agent",
        "statistical_tests_frozen": statistical_plan.get("binary_test") == "McNemar"
        and statistical_plan.get("continuous_test") == "Wilcoxon signed-rank"
        and statistical_plan.get("confidence_interval") == "paired bootstrap 95%",
        "secondary_multiplicity_control_recorded": bool(
            statistical_plan.get("secondary_multiplicity_control")
        ),
        "no_tuning_after_main_freeze": claim_boundaries.get("no_tuning_after_main_freeze")
        is True,
        "sealed_validation_no_tuning_policy": claim_boundaries.get(
            "sealed_validation_no_tuning_after_run"
        )
        is True,
        "formal_hard_timeout_control_recorded": runtime_controls.get(
            "result_hard_timeout_mode"
        )
        == EXPECTED_FORMAL_RESULT_HARD_TIMEOUT_MODE
        and (_float_or_none(runtime_controls.get("result_hard_timeout_seconds")) or 0.0)
        >= 900.0,
        "formal_provider_accounting_control_recorded": runtime_controls.get(
            "provider_accounting"
        )
        == EXPECTED_FORMAL_PROVIDER_ACCOUNTING,
        "pre_formal_real_api_smoke_required": runtime_controls.get(
            "real_api_smoke_required"
        )
        is True,
        "pre_formal_ctp20_joint_run_required": pre_formal_validation.get(
            "ctp20_four_method_joint_run_required"
        )
        is True,
        "pre_formal_ctp20_joint_run_methods_are_four_method": tuple(
            _as_text_list(pre_formal_validation.get("methods"))
        )
        == EXPERIMENT_METHODS,
        "pre_formal_task_d_required": pre_formal_validation.get(
            "task_d_m0_real_api_required"
        )
        is True,
        "pre_formal_task_e_required": pre_formal_validation.get(
            "task_e_four_method_real_api_required"
        )
        is True,
        "pre_formal_task_f_required": pre_formal_validation.get(
            "task_f_multiturn_real_api_required"
        )
        is True,
        "pre_formal_registry_declares_all_tasks": tuple(
            _as_text_list(pre_formal_validation.get("required_tasks"))
        )
        == EXPECTED_PRE_FORMAL_VALIDATION_TASKS
        and bool(pre_formal_validation.get("registry_file")),
        "decision_normalization_diagnostic_metrics_declared": all(
            metric in decision_metric_names
            for metric in EXPECTED_DECISION_NORMALIZATION_DIAGNOSTIC_METRICS
        ),
        "decision_normalization_formulas_declared": all(
            bool(decision_formulas.get(metric))
            for metric in EXPECTED_DECISION_NORMALIZATION_DIAGNOSTIC_METRICS
        ),
        "decision_normalization_marked_as_diagnostic": decision_normalization.get(
            "paper_usage"
        )
        == "diagnostic_not_primary_effect_metric",
    }


def _load_benchmark(
    path: Path,
    errors: list[str],
    *,
    label: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        doc, cases = _load_benchmark_document(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"{label} is invalid: {path}: {exc}")
        return {}, []
    return _dict(doc), cases


def _comparison_splits(
    paths: tuple[str | Path, ...],
    errors: list[str],
) -> dict[str, list[dict[str, Any]]]:
    splits: dict[str, list[dict[str, Any]]] = {}
    for path_value in paths:
        path = Path(path_value)
        try:
            doc, cases = _load_benchmark_document(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"comparison split is invalid: {path}: {exc}")
            continue
        split_name = str(_dict(doc).get("split") or _dict(doc).get("dataset_id") or path.stem)
        splits[split_name] = cases
    return splits


def _load_benchmark_document(path: Path) -> tuple[Any, list[dict[str, Any]]]:
    from app.core.formal_experiment_preflight import load_benchmark_document

    return load_benchmark_document(path)


def _read_json_object(path: Path, errors: list[str], *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label} is invalid: {path}: {exc}")
        return {}
    return _dict(value)


def _compact_quality(report: Mapping[str, Any]) -> dict[str, Any]:
    dataset = _dict(report.get("dataset"))
    coverage = _dict(report.get("coverage"))
    return {
        "status": report.get("status"),
        "errors": report.get("errors") or [],
        "warnings": report.get("warnings") or [],
        "case_count": dataset.get("case_count"),
        "scenario_case_count": dataset.get("scenario_case_count"),
        "total_unit_count": dataset.get("total_unit_count"),
        "task_distribution": coverage.get("task_distribution") or {},
        "city_distribution": coverage.get("city_distribution") or {},
        "duplicate_visible_input_groups": coverage.get("duplicate_visible_input_groups") or [],
        "cross_split_duplicate_visible_input_groups": coverage.get(
            "cross_split_duplicate_visible_input_groups"
        )
        or [],
        "near_duplicate_visible_input_pairs": coverage.get("near_duplicate_visible_input_pairs")
        or [],
    }


def _turn_count(cases: list[dict[str, Any]]) -> int:
    total = 0
    for case in cases:
        turns = case.get("turns")
        total += len(turns) if isinstance(turns, list) and turns else 1
    return total


def _file_sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_bytes(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def _valid_iso_date(value: Any) -> bool:
    try:
        date.fromisoformat(str(value or ""))
    except ValueError:
        return False
    return True


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_text_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []
