"""Registry and gates for pre-formal real-API validation evidence.

Task D/E/F are not the paper's final experiment results.  They are runtime
validation gates proving that the candidate system can run with the real
OpenAI-compatible gateway before the full CTP100 run starts.

This module keeps those gates auditable:

* a registry file records the accepted Task D/E/F report paths and hashes;
* preflight checks that the reports still exist, still match the registered
  hashes, and still satisfy the required gate conditions;
* critical code hashes are recorded so later edits can make the registry
  explicitly stale instead of silently reusing old validation evidence.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.core.formal_artifact_integrity import (
    FORMAL_OUTPUT_PACK_CODE_PATHS,
    FORMAL_RUN_SCRIPT_PATHS,
    FORMAL_RUNTIME_CODE_PATHS,
    PRE_FORMAL_VALIDATION_SCRIPT_PATHS,
)


PRE_FORMAL_VALIDATION_REGISTRY_SCHEMA_VERSION = "ctp-pre-formal-validation-registry-v1"
PRE_FORMAL_VALIDATION_HASH_STRATEGY = "sha256_file_bytes_v1"

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRE_FORMAL_VALIDATION_REGISTRY_PATH = (
    ROOT / "experiments" / "generated" / "pre_formal_validation_registry_v1.json"
)

DEFAULT_PRE_FORMAL_TASK_REPORT_PATHS: dict[str, Path] = {
    "task_d_m0_real_api": (
        ROOT
        / "experiments"
        / "results"
        / "task_d_m0_real_api"
        / "task_d_m0_real_api_final_20260821T110521Z"
        / "task_d_m0_real_api_report.json"
    ),
    "task_e_four_method_real_api": (
        ROOT
        / "experiments"
        / "results"
        / "task_e_four_method_real_api"
        / "task_e_four_method_real_api_final3_20260821T123500Z"
        / "task_e_four_method_real_api_report.json"
    ),
    "task_f_multiturn_real_api": (
        ROOT
        / "experiments"
        / "results"
        / "task_f_multiturn_real_api"
        / "task_f_multiturn_real_api_full_recheck_20260822T170309Z"
        / "task_f_multiturn_real_api_report.json"
    ),
}

CRITICAL_CODE_PATHS: dict[str, Path] = {
    **FORMAL_RUNTIME_CODE_PATHS,
    **FORMAL_OUTPUT_PACK_CODE_PATHS,
    **FORMAL_RUN_SCRIPT_PATHS,
    **PRE_FORMAL_VALIDATION_SCRIPT_PATHS,
    "evaluation_rule_catalog": ROOT / "experiments" / "evaluation_rule_catalog.json",
}

TRANSPARENT_NON_BLOCKING_WARNING_CODES = (
    "failed_llm_calls_recorded",
    "llm_retry_errors_recorded",
)

_TASK_SPECS: dict[str, dict[str, Any]] = {
    "task_d_m0_real_api": {
        "schema_version": "ctp-task-d-m0-real-api-validation-v1",
        "dataset_id": "task_d_m0_real_api_20",
        "case_count": 20,
        "turn_count": 20,
        "expected_result_count": 20,
        "methods": ("llm_direct",),
        "runtime": {
            "provider": "vectorengine_openai_compatible",
            "base_url": "https://api.vectorengine.ai/v1",
            "model": "gpt-5-mini",
            "temperature": 0.0,
            "max_tokens": 4096,
            "timeout_seconds": 120,
            "retry_max_attempts": 3,
            "reasoning_effort": "minimal",
            "strict_mode": True,
            "cache_disabled": True,
            "trace_save_user_message": False,
            "mock_fallback_allowed": False,
        },
    },
    "task_e_four_method_real_api": {
        "schema_version": "ctp-task-e-four-method-real-api-validation-v1",
        "dataset_id": "task_e_four_method_real_api_20",
        "case_count": 20,
        "turn_count": 20,
        "expected_result_count": 80,
        "methods": (
            "llm_direct",
            "single_agent",
            "fixed_multi_agent",
            "adaptive_multi_agent",
        ),
        "runtime": {
            "provider": "vectorengine_openai_compatible",
            "base_url": "https://api.vectorengine.ai/v1",
            "model": "gpt-5-mini",
            "temperature": 0.0,
            "max_tokens": 4096,
            "timeout_seconds": 120,
            "retry_max_attempts": 3,
            "reasoning_effort": "minimal",
            "strict_mode": True,
            "cache_disabled": True,
            "trace_save_user_message": False,
            "mock_fallback_allowed": False,
        },
    },
    "task_f_multiturn_real_api": {
        "schema_version": "ctp-task-f-multiturn-real-api-report-v1",
        "dataset_id": "task_f_multiturn_real_api_m2_m3",
        "case_count": 6,
        "turn_count": 12,
        "expected_result_count": 24,
        "methods": ("fixed_multi_agent", "adaptive_multi_agent"),
        "runtime": {
            "provider": "vectorengine_openai_compatible",
            "base_url": "https://api.vectorengine.ai/v1",
            "model": "gpt-5-mini",
            "temperature": 0.0,
            "max_tokens": 4096,
            "timeout_seconds": 120,
            "retry_max_attempts": 3,
            "reasoning_effort": "minimal",
            "strict_mode": True,
            "cache_disabled": True,
            "trace_save_user_message": False,
            "mock_fallback_allowed": False,
        },
        "decision_normalizer": {
            "agent_decision_total": 76,
            "raw_llm_decision_success_count": 37,
            "decision_normalizer_recovery_count": 39,
            "pipeline_completion_rate": 1.0,
        },
    },
}


def build_pre_formal_validation_registry(
    *,
    report_paths: Mapping[str, str | Path] | None = None,
    code_paths: Mapping[str, str | Path] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build the registry document for the current accepted reports."""
    selected_report_paths = _selected_paths(
        DEFAULT_PRE_FORMAL_TASK_REPORT_PATHS,
        report_paths,
    )
    selected_code_paths = _selected_paths(CRITICAL_CODE_PATHS, code_paths)
    task_entries = [
        _task_registry_entry(task_id, selected_report_paths[task_id])
        for task_id in _TASK_SPECS
    ]
    code_artifacts = [
        _artifact_item(key, selected_code_paths[key])
        for key in sorted(selected_code_paths)
    ]
    return {
        "schema_version": PRE_FORMAL_VALIDATION_REGISTRY_SCHEMA_VERSION,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "hash_strategy": PRE_FORMAL_VALIDATION_HASH_STRATEGY,
        "purpose": (
            "Bind Task D/E/F real-API validation reports to the formal "
            "experiment preflight and delivery package."
        ),
        "warning_policy": {
            "transparent_non_blocking_codes": list(TRANSPARENT_NON_BLOCKING_WARNING_CODES),
            "blocking_conditions": [
                "report_missing",
                "report_hash_mismatch",
                "report_status_not_passed",
                "gate_status_not_passed",
                "failed_final_result",
                "mock_or_fallback_call",
                "hard_timeout_triggered",
                "critical_code_hash_mismatch",
            ],
        },
        "critical_code_artifacts": code_artifacts,
        "tasks": task_entries,
    }


def write_pre_formal_validation_registry(
    *,
    output_path: str | Path = DEFAULT_PRE_FORMAL_VALIDATION_REGISTRY_PATH,
    report_paths: Mapping[str, str | Path] | None = None,
    code_paths: Mapping[str, str | Path] | None = None,
) -> Path:
    """Write a registry JSON file and return its path."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    registry = build_pre_formal_validation_registry(
        report_paths=report_paths,
        code_paths=code_paths,
    )
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def validate_pre_formal_validation_registry(
    path: str | Path = DEFAULT_PRE_FORMAL_VALIDATION_REGISTRY_PATH,
    *,
    required: bool = True,
    code_paths: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    """Validate the registry and the Task D/E/F reports it points to."""
    registry_path = Path(path)
    if not registry_path.exists():
        status = "failed" if required else "not_required"
        errors = [f"pre-formal validation registry is missing: {registry_path}"] if required else []
        return {
            "schema_version": PRE_FORMAL_VALIDATION_REGISTRY_SCHEMA_VERSION,
            "required": required,
            "path": _display_path(registry_path),
            "status": status,
            "errors": errors,
            "warnings": [],
            "tasks": [],
            "summary": _summary([]),
        }

    errors: list[str] = []
    warnings: list[str] = []
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "schema_version": PRE_FORMAL_VALIDATION_REGISTRY_SCHEMA_VERSION,
            "required": required,
            "path": _display_path(registry_path),
            "status": "failed",
            "errors": [f"pre-formal validation registry is invalid: {exc}"],
            "warnings": [],
            "tasks": [],
            "summary": _summary([]),
        }
    if not isinstance(registry, Mapping):
        return {
            "schema_version": PRE_FORMAL_VALIDATION_REGISTRY_SCHEMA_VERSION,
            "required": required,
            "path": _display_path(registry_path),
            "status": "failed",
            "errors": ["pre-formal validation registry must be a JSON object"],
            "warnings": [],
            "tasks": [],
            "summary": _summary([]),
        }

    if registry.get("schema_version") != PRE_FORMAL_VALIDATION_REGISTRY_SCHEMA_VERSION:
        errors.append(
            "pre-formal validation registry schema mismatch: "
            f"{registry.get('schema_version')}"
        )
    if registry.get("hash_strategy") != PRE_FORMAL_VALIDATION_HASH_STRATEGY:
        errors.append(
            "pre-formal validation registry hash strategy mismatch: "
            f"{registry.get('hash_strategy')}"
        )

    selected_code_paths = _selected_paths(CRITICAL_CODE_PATHS, code_paths)
    code_report = _validate_registered_code_artifacts(
        registry.get("critical_code_artifacts"),
        selected_code_paths=selected_code_paths,
        errors=errors,
    )
    task_reports = _validate_registered_tasks(
        registry.get("tasks"),
        errors=errors,
        warnings=warnings,
    )
    status = "passed" if not errors else "failed"
    return {
        "schema_version": PRE_FORMAL_VALIDATION_REGISTRY_SCHEMA_VERSION,
        "required": required,
        "path": _display_path(registry_path),
        "registry_sha256": _file_sha256(registry_path),
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "summary": _summary(task_reports),
        "critical_code": code_report,
        "tasks": task_reports,
    }


def _task_registry_entry(task_id: str, report_path: Path) -> dict[str, Any]:
    report = _read_json_object(report_path)
    spec = _TASK_SPECS[task_id]
    return {
        "task_id": task_id,
        "required": True,
        "report_path": _display_path(report_path),
        "report_sha256": _file_sha256(report_path) if report_path.exists() else None,
        "schema_version": spec["schema_version"],
        "expected": {
            "dataset_id": spec["dataset_id"],
            "case_count": spec["case_count"],
            "turn_count": spec["turn_count"],
            "expected_result_count": spec["expected_result_count"],
            "methods": list(spec["methods"]),
            "runtime": spec["runtime"],
            **(
                {"decision_normalizer": spec["decision_normalizer"]}
                if "decision_normalizer" in spec
                else {}
            ),
        },
        "observed": _report_observed_summary(report),
    }


def _validate_registered_tasks(
    value: Any,
    *,
    errors: list[str],
    warnings: list[str],
) -> list[dict[str, Any]]:
    entries = _as_dict_list(value)
    by_id = {str(entry.get("task_id") or ""): entry for entry in entries}
    reports: list[dict[str, Any]] = []
    for task_id in _TASK_SPECS:
        entry = by_id.get(task_id)
        if not entry:
            errors.append(f"pre-formal validation registry missing task: {task_id}")
            reports.append({"task_id": task_id, "status": "missing"})
            continue
        reports.append(
            _validate_task_entry(
                task_id,
                entry,
                errors=errors,
                warnings=warnings,
            )
        )
    extra_ids = sorted(set(by_id) - set(_TASK_SPECS))
    if extra_ids:
        warnings.append(
            "pre-formal validation registry contains unrecognized tasks: "
            + ", ".join(extra_ids)
        )
    return reports


def _validate_task_entry(
    task_id: str,
    entry: Mapping[str, Any],
    *,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    spec = _TASK_SPECS[task_id]
    task_errors: list[str] = []
    task_warnings: list[dict[str, Any]] = []
    report_path = _resolve_path(entry.get("report_path"))
    registered_sha = entry.get("report_sha256")
    report_exists = report_path.exists()
    actual_sha = _file_sha256(report_path) if report_exists else None

    if not report_exists:
        task_errors.append(f"{task_id}: report is missing: {report_path}")
    elif not _is_sha256(registered_sha):
        task_errors.append(f"{task_id}: registry does not contain a valid report sha256")
    elif actual_sha != registered_sha:
        task_errors.append(
            f"{task_id}: report hash mismatch: expected {registered_sha}, got {actual_sha}"
        )

    report = _read_json_object(report_path) if report_exists else {}
    if report:
        _validate_report_content(task_id, spec, report, task_errors, task_warnings)

    for message in task_errors:
        errors.append(message)
    for warning in task_warnings:
        warnings.append(f"{task_id}: {warning.get('code')}: {warning.get('meaning')}")

    status = "passed" if not task_errors else "failed"
    return {
        "task_id": task_id,
        "status": status,
        "report_path": _display_path(report_path),
        "registered_report_sha256": registered_sha,
        "actual_report_sha256": actual_sha,
        "report_exists": report_exists,
        "errors": task_errors,
        "transparent_warnings": task_warnings,
        "observed": _report_observed_summary(report),
    }


def _validate_report_content(
    task_id: str,
    spec: Mapping[str, Any],
    report: Mapping[str, Any],
    errors: list[str],
    warnings: list[dict[str, Any]],
) -> None:
    gate = _dict(report.get("gate"))
    benchmark = _dict(report.get("benchmark"))
    runtime = _dict(report.get("runtime_config"))
    results = _dict(report.get("results"))
    trace_audit = _dict(report.get("trace_audit"))

    _expect_equal(errors, task_id, "schema_version", report.get("schema_version"), spec.get("schema_version"))
    _expect_equal(errors, task_id, "status", report.get("status"), "passed")
    _expect_equal(errors, task_id, "skipped_reason", report.get("skipped_reason"), None)
    _expect_equal(errors, task_id, "gate.status", gate.get("status"), "passed")
    if gate.get("failed_checks") not in ([], None):
        errors.append(f"{task_id}: gate.failed_checks must be empty")

    _expect_equal(errors, task_id, "benchmark.dataset_id", benchmark.get("dataset_id"), spec.get("dataset_id"))
    _expect_equal(errors, task_id, "benchmark.case_count", benchmark.get("case_count"), spec.get("case_count"))
    _expect_equal(errors, task_id, "benchmark.turn_count", benchmark.get("turn_count"), spec.get("turn_count"))

    expected_methods = tuple(spec.get("methods") or ())
    observed_methods_source = (
        results.get("methods")
        or list(_dict(results.get("method_counts")).keys())
        or runtime.get("methods")
        or ([runtime.get("method")] if runtime.get("method") else [])
    )
    observed_methods = tuple(sorted(str(item) for item in _as_list(observed_methods_source)))
    if observed_methods != tuple(sorted(expected_methods)):
        errors.append(
            f"{task_id}: results.methods mismatch: expected {sorted(expected_methods)}, "
            f"got {list(observed_methods)}"
        )
    if runtime.get("method"):
        runtime_methods = (str(runtime.get("method")),)
    else:
        runtime_methods = tuple(str(item) for item in _as_list(runtime.get("methods")))
    if tuple(sorted(runtime_methods)) != tuple(sorted(expected_methods)):
        errors.append(
            f"{task_id}: runtime methods mismatch: expected {sorted(expected_methods)}, "
            f"got {sorted(runtime_methods)}"
        )

    _expect_equal(
        errors,
        task_id,
        "results.expected_result_count",
        results.get("expected_result_count"),
        spec.get("expected_result_count"),
    )
    _expect_equal(
        errors,
        task_id,
        "results.actual_result_count",
        results.get("actual_result_count"),
        spec.get("expected_result_count"),
    )
    if results.get("failed_results") not in ([], None):
        errors.append(f"{task_id}: results.failed_results must be empty")
    _expect_equal(
        errors,
        task_id,
        "results.hard_timeout_triggered_count",
        results.get("hard_timeout_triggered_count"),
        0,
    )

    for key, expected in _dict(spec.get("runtime")).items():
        _expect_equal(errors, task_id, f"runtime_config.{key}", runtime.get(key), expected)
    if runtime.get("api_key_configured") is not True:
        errors.append(f"{task_id}: runtime_config.api_key_configured must be true")

    _expect_equal(errors, task_id, "trace_audit.mock_call_count", trace_audit.get("mock_call_count"), 0)
    _expect_equal(errors, task_id, "trace_audit.fallback_call_count", trace_audit.get("fallback_call_count"), 0)
    _expect_equal(
        errors,
        task_id,
        "trace_audit.length_finish_reason_attempt_count",
        trace_audit.get("length_finish_reason_attempt_count"),
        0,
    )

    if "decision_normalizer" in spec:
        expected_decision = _dict(spec.get("decision_normalizer"))
        observed_decision = _dict(report.get("decision_normalizer"))
        for key, expected in expected_decision.items():
            _expect_equal(
                errors,
                task_id,
                f"decision_normalizer.{key}",
                observed_decision.get(key),
                expected,
            )

    for warning in _report_warnings(report):
        warnings.append(warning)
        code = str(warning.get("code") or "")
        if code and code not in TRANSPARENT_NON_BLOCKING_WARNING_CODES:
            warnings.append(
                {
                    "code": "unregistered_warning_code",
                    "meaning": f"Warning code is transparent but not in the frozen allowlist: {code}",
                }
            )


def _validate_registered_code_artifacts(
    value: Any,
    *,
    selected_code_paths: Mapping[str, Path],
    errors: list[str],
) -> dict[str, Any]:
    entries = _as_dict_list(value)
    by_key = {str(entry.get("key") or ""): entry for entry in entries}
    artifacts: list[dict[str, Any]] = []
    mismatches: list[str] = []
    missing: list[str] = []
    for key in sorted(selected_code_paths):
        path = selected_code_paths[key]
        registered = by_key.get(key)
        if not registered:
            missing.append(key)
            artifacts.append({**_artifact_item(key, path), "registered_sha256": None, "matches": False})
            continue
        actual = _artifact_item(key, path)
        registered_sha = registered.get("sha256")
        matches = actual.get("sha256") == registered_sha and actual.get("exists") is True
        artifacts.append(
            {
                **actual,
                "registered_sha256": registered_sha,
                "matches": matches,
            }
        )
        if not matches:
            mismatches.append(key)
    if missing:
        errors.append(
            "pre-formal validation registry missing critical code hashes: "
            + ", ".join(missing)
        )
    if mismatches:
        errors.append(
            "pre-formal validation critical code hash mismatch: "
            + ", ".join(mismatches)
        )
    return {
        "hash_strategy": PRE_FORMAL_VALIDATION_HASH_STRATEGY,
        "artifact_count": len(artifacts),
        "missing_registered_hashes": missing,
        "hash_mismatches": mismatches,
        "artifacts": artifacts,
    }


def _report_observed_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    gate = _dict(report.get("gate"))
    benchmark = _dict(report.get("benchmark"))
    runtime = _dict(report.get("runtime_config"))
    results = _dict(report.get("results"))
    trace_audit = _dict(report.get("trace_audit"))
    return {
        "schema_version": report.get("schema_version"),
        "status": report.get("status"),
        "gate_status": gate.get("status"),
        "failed_checks": gate.get("failed_checks") or [],
        "dataset_id": benchmark.get("dataset_id"),
        "case_count": benchmark.get("case_count"),
        "turn_count": benchmark.get("turn_count"),
        "expected_result_count": results.get("expected_result_count"),
        "actual_result_count": results.get("actual_result_count"),
        "methods": results.get("methods")
        or list(_dict(results.get("method_counts")).keys())
        or runtime.get("methods")
        or ([runtime.get("method")] if runtime.get("method") else []),
        "provider": runtime.get("provider"),
        "base_url": runtime.get("base_url"),
        "model": runtime.get("model"),
        "prompt_version_counts": trace_audit.get("prompt_version_counts") or {},
        "mock_call_count": trace_audit.get("mock_call_count"),
        "fallback_call_count": trace_audit.get("fallback_call_count"),
        "failed_llm_call_count": trace_audit.get("failed_llm_call_count"),
        "retry_error_count": trace_audit.get("retry_error_count"),
        "hard_timeout_triggered_count": results.get("hard_timeout_triggered_count"),
        "transparent_warnings": _report_warnings(report),
    }


def _report_warnings(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for item in _as_dict_list(_dict(report.get("gate")).get("warnings")):
        warnings.append(dict(item))
    for item in _as_dict_list(report.get("warnings")):
        if item not in warnings:
            warnings.append(dict(item))
    return warnings


def _summary(task_reports: list[Mapping[str, Any]]) -> dict[str, Any]:
    transparent_warning_count = sum(
        len(_as_dict_list(report.get("transparent_warnings")))
        for report in task_reports
    )
    return {
        "required_task_count": len(_TASK_SPECS),
        "registered_task_count": len(task_reports),
        "passed_task_count": sum(1 for report in task_reports if report.get("status") == "passed"),
        "failed_task_count": sum(1 for report in task_reports if report.get("status") == "failed"),
        "task_ids": list(_TASK_SPECS),
        "transparent_warning_count": transparent_warning_count,
        "transparent_warning_policy": "accepted_but_reported",
    }


def _artifact_item(key: str, path: Path) -> dict[str, Any]:
    exists = path.exists()
    return {
        "key": key,
        "path": _display_path(path),
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else None,
        "sha256": _file_sha256(path) if exists else None,
    }


def _selected_paths(
    defaults: Mapping[str, Path],
    overrides: Mapping[str, str | Path] | None,
) -> dict[str, Path]:
    selected = dict(defaults)
    for key, value in (overrides or {}).items():
        selected[str(key)] = Path(value)
    return selected


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _resolve_path(value: Any) -> Path:
    path = Path(str(value or ""))
    return path if path.is_absolute() else ROOT / path


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


def _expect_equal(
    errors: list[str],
    task_id: str,
    field: str,
    actual: Any,
    expected: Any,
) -> None:
    if actual != expected:
        errors.append(f"{task_id}: {field} mismatch: expected {expected!r}, got {actual!r}")


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text.lower())
