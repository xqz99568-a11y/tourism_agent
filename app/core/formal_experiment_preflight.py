"""Preflight checks for paper-level formal experiment runs."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.core.academic_experiment_design import (
    build_academic_experiment_design_report,
)
from app.core.config import settings
from app.core.benchmark_dataset_validator import (
    build_benchmark_dataset_quality_report,
)
from app.core.budget_gold import (
    BudgetGoldError,
    DEFAULT_CTP100_BUDGET_GOLD_PATH,
    DEFAULT_CTP100_DATASET_PATH,
    validate_budget_gold,
)
from app.core.experiment_method_contract import (
    EXPERIMENT_METHODS,
    build_method_fairness_contract,
    method_fairness_contract_hash,
    validate_method_fairness_contract,
)
from app.core.experiment_method_input import (
    build_generation_case,
    contains_evaluator_only_generation_fields,
)
from app.core.fixed_data import (
    CANONICAL_JSON_SHA256_STRATEGY,
    canonical_json_sha256,
    validate_fixed_data_snapshot,
)
from app.core.formal_artifact_integrity import (
    ROOT,
    build_formal_artifact_integrity_report,
)
from app.core.llm.client import LLM_REASONING_EFFORT_ENV, SUPPORTED_REASONING_EFFORTS
from app.core.qweather_snapshot import validate_qweather_snapshot
from app.core.intercity_transport_snapshot import validate_intercity_transport_snapshot
from app.core.experiment_runner import (
    BENCHMARK_CHECKPOINT_JSON_NAME,
    BENCHMARK_RESULTS_JSON_NAME,
    BENCHMARK_RESUME_STATE_NAME,
    EXPERIMENT_RESUME_SCHEMA_VERSION,
)


FORMAL_PREFLIGHT_SCHEMA_VERSION = "ctp-formal-preflight-v1"
DEFAULT_FORMAL_METHOD_ORDER_SEED = 20260718
FORMAL_RETRY_MAX_ATTEMPTS = 3
FORMAL_GPT5_REASONING_EFFORT = "minimal"
FORMAL_MIN_MAX_TOKENS = 4096
FORMAL_DETERMINISTIC_RESEARCH_FINAL_ANSWER_ENV = (
    "EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER"
)
FORMAL_RESULT_FILES = (
    "benchmark_results.csv",
    "benchmark_results.json",
    "evaluation_summary.json",
    "paper_tables.md",
    "experiment_manifest.json",
)
DEFAULT_DAY8_DELIVERY_PACK_PATH = ROOT / "experiments" / "generated" / "day8_delivery_pack.json"
_DAY8_ARTIFACT_HASH_KEYS = {
    "benchmark_manifest": "benchmark_manifest",
    "formal_dataset": "formal_dataset",
    "budget_gold": "budget_gold_json",
    "qweather_manifest": "qweather_manifest",
    "qweather_validation": "qweather_validation_report",
    "intercity_manifest": "intercity_manifest",
    "intercity_fare_table": "intercity_fare_table",
    "budget_policy_doc": "budget_policy_doc",
    "academic_experiment_design": "academic_experiment_design_json",
    "sealed_validation_dataset": "sealed_validation_dataset",
    "evaluation_rule_catalog": "evaluation_rule_catalog",
    "independent_evaluator_code": "independent_evaluator_code",
}


def build_formal_preflight_report(
    *,
    benchmark_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    methods: Iterable[str] | None = None,
    repeats: int = 1,
    method_order_seed: int = DEFAULT_FORMAL_METHOD_ORDER_SEED,
    model_config_name: str | None = None,
    expected_case_count: int | None = None,
    require_llm_config: bool = True,
    strict_formal: bool = True,
    require_day8_delivery_pack: bool | None = None,
    require_clean_git: bool | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """Return a machine-readable report for a formal benchmark run.

    The report is read-only: it validates the benchmark and runtime metadata
    without creating traces, calling an LLM, or consuming API quota.
    """
    benchmark_file = Path(benchmark_path)
    run_output_dir = resolve_run_output_dir(output_dir, run_id)
    selected_methods = tuple(str(method).strip().lower() for method in (methods or EXPERIMENT_METHODS))
    errors: list[str] = []
    warnings: list[str] = []

    if not selected_methods:
        errors.append("method list must not be empty")
    try:
        validate_method_fairness_contract(selected_methods)
    except ValueError as exc:
        errors.append(str(exc))

    repeats = _validated_repeats(repeats, errors)
    if not isinstance(method_order_seed, int):
        errors.append("method_order_seed must be an integer")

    document: Any = None
    cases: list[dict[str, Any]] = []
    resolved_model_config_name = str(model_config_name or "default")
    if not benchmark_file.exists():
        errors.append(f"benchmark file does not exist: {benchmark_file}")
    else:
        try:
            document, cases = load_benchmark_document(benchmark_file)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"benchmark file is invalid: {exc}")

    output_dir_has_contents = run_output_dir.exists() and any(run_output_dir.iterdir())
    if output_dir_has_contents and not resume:
        errors.append(f"output directory is not empty: {run_output_dir}")

    if expected_case_count is not None and len(cases) != expected_case_count:
        errors.append(
            f"case_count mismatch: expected {expected_case_count}, got {len(cases)}"
        )

    _validate_cases(cases, errors=errors, warnings=warnings, strict_formal=strict_formal)
    comparison_splits = _load_benchmark_comparison_splits(benchmark_file, document, errors)
    dataset_quality_report = build_benchmark_dataset_quality_report(
        document=document,
        cases=cases,
        expected_case_count=expected_case_count,
        strict_formal=strict_formal,
        comparison_splits=comparison_splits,
    )
    errors.extend(
        f"benchmark_quality: {error}"
        for error in dataset_quality_report.get("errors", [])
    )
    warnings.extend(
        f"benchmark_quality: {warning}"
        for warning in dataset_quality_report.get("warnings", [])
    )
    _validate_generation_visibility(cases, selected_methods, errors=errors)
    formal_release_required = strict_formal and _requires_ctp100_budget_gold(benchmark_file, document)
    require_day8_delivery = (
        formal_release_required
        if require_day8_delivery_pack is None
        else bool(require_day8_delivery_pack)
    )
    require_clean_git = (
        formal_release_required
        if require_clean_git is None
        else bool(require_clean_git)
    )

    fixed_data_report = _fixed_data_report(errors)
    intercity_transport_report = _intercity_transport_snapshot_report(errors)
    budget_gold_report = _budget_gold_report(
        benchmark_file=benchmark_file,
        document=document,
        errors=errors,
        strict_formal=strict_formal,
    )
    academic_design_report = _academic_design_report(
        benchmark_file=benchmark_file,
        required=formal_release_required,
        errors=errors,
    )
    artifact_integrity_report = build_formal_artifact_integrity_report()
    _validate_artifact_integrity(
        artifact_integrity_report,
        errors=errors,
        required=formal_release_required,
        require_clean_git=require_clean_git,
    )
    day8_delivery_pack_report = _day8_delivery_pack_report(
        DEFAULT_DAY8_DELIVERY_PACK_PATH,
        artifact_integrity_report=artifact_integrity_report,
        errors=errors,
        required=require_day8_delivery,
    )
    environment_report = _environment_report(
        errors=errors,
        warnings=warnings,
        require_llm_config=require_llm_config,
        strict_formal=strict_formal,
    )

    benchmark_sha256 = canonical_json_sha256(document) if document is not None else None
    structure = _benchmark_structure(cases)
    raw_run_count = structure["total_turn_count"] * len(selected_methods) * repeats
    method_contract = _method_contract_report(selected_methods, errors)
    qweather_snapshot_report = _qweather_snapshot_report(errors)
    resume_report = _resume_preflight_report(
        run_output_dir=run_output_dir,
        requested=bool(resume),
        output_dir_has_contents=output_dir_has_contents,
        run_id=str(run_id),
        benchmark_sha256=benchmark_sha256,
        selected_methods=list(selected_methods),
        repeats=repeats,
        method_order_seed=method_order_seed,
        model_config_name=resolved_model_config_name,
        expected_raw_run_count=raw_run_count,
        method_contract_sha256=method_contract.get("contract_sha256"),
        artifact_integrity_report=artifact_integrity_report,
        environment_report=environment_report,
        errors=errors,
    )
    report = {
        "schema_version": FORMAL_PREFLIGHT_SCHEMA_VERSION,
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "benchmark": {
            "path": benchmark_file.as_posix(),
            "sha256": benchmark_sha256,
            "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY if benchmark_sha256 else None,
            **structure,
        },
        "run": {
            "run_id": str(run_id),
            "output_dir": run_output_dir.as_posix(),
            "methods": list(selected_methods),
            "method_count": len(selected_methods),
            "repeats": repeats,
            "method_order_seed": method_order_seed,
            "model_config_name": resolved_model_config_name,
            "expected_raw_run_count": raw_run_count,
            "expected_result_files": list(FORMAL_RESULT_FILES),
        },
        "method_fairness_contract": method_contract,
        "benchmark_quality": dataset_quality_report,
        "fixed_data": fixed_data_report,
        "qweather_snapshot": qweather_snapshot_report,
        "intercity_transport_snapshot": intercity_transport_report,
        "budget_gold": budget_gold_report,
        "academic_experiment_design": academic_design_report,
        "artifact_integrity": artifact_integrity_report,
        "day8_delivery_pack": day8_delivery_pack_report,
        "environment": environment_report,
        "resume": resume_report,
        "policy": {
            "strict_formal": strict_formal,
            "formal_release_required": formal_release_required,
            "require_day8_delivery_pack": require_day8_delivery,
            "require_clean_git": require_clean_git,
            "gold_visible_to_generation": False,
            "previous_state_policy": (
                "formal multi-turn state must be produced by the same method's prior turn"
            ),
            "no_overwrite": not bool(resume),
            "resume_requested": bool(resume),
            "resume_requires_contract_match": True,
            "preflight_consumes_api": False,
        },
    }
    return report


def assert_formal_preflight_passed(report: Mapping[str, Any]) -> None:
    if report.get("status") == "passed":
        return
    errors = report.get("errors") if isinstance(report.get("errors"), list) else []
    details = "\n".join(f"- {error}" for error in errors) or "- unknown preflight error"
    raise RuntimeError(f"formal experiment preflight failed:\n{details}")


def write_preflight_report(report: Mapping[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def resolve_run_output_dir(output_dir: str | Path, run_id: str) -> Path:
    root = Path(output_dir)
    return root if root.name == run_id else root / run_id


def load_benchmark_document(path: str | Path) -> tuple[Any, list[dict[str, Any]]]:
    benchmark_file = Path(path)
    document = json.loads(benchmark_file.read_text(encoding="utf-8"))
    if isinstance(document, list):
        return document, [case for case in document if isinstance(case, dict)]
    if isinstance(document, dict) and isinstance(document.get("cases"), list):
        return document, [case for case in document["cases"] if isinstance(case, dict)]
    if isinstance(document, dict) and isinstance(document.get("case_files"), list):
        cases: list[dict[str, Any]] = []
        for file_name in document["case_files"]:
            case_path = benchmark_file.parent / str(file_name)
            loaded = json.loads(case_path.read_text(encoding="utf-8"))
            cases.extend(_cases_from_loaded_case_file(loaded))
        return document, cases
    raise ValueError("unsupported benchmark format; expected list, cases, or case_files")


def _load_benchmark_comparison_splits(
    benchmark_file: Path,
    document: Any,
    errors: list[str],
) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(document, Mapping) or not isinstance(document.get("comparison_files"), list):
        return {}
    comparison_splits: dict[str, list[dict[str, Any]]] = {}
    for file_name in document["comparison_files"]:
        comparison_path = benchmark_file.parent / str(file_name)
        try:
            comparison_document, comparison_cases = load_benchmark_document(comparison_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"benchmark comparison file is invalid: {comparison_path}: {exc}")
            continue
        comparison_splits[_comparison_split_name(comparison_path, comparison_document)] = comparison_cases
    return comparison_splits


def _comparison_split_name(path: Path, document: Any) -> str:
    if isinstance(document, Mapping):
        for key in ("split", "dataset_id"):
            value = str(document.get(key) or "").strip()
            if value:
                return value
    return path.stem


def _cases_from_loaded_case_file(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [case for case in value if isinstance(case, dict)]
    if isinstance(value, dict) and isinstance(value.get("cases"), list):
        return [case for case in value["cases"] if isinstance(case, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _resume_preflight_report(
    *,
    run_output_dir: Path,
    requested: bool,
    output_dir_has_contents: bool,
    run_id: str,
    benchmark_sha256: str | None,
    selected_methods: list[str],
    repeats: int,
    method_order_seed: int,
    model_config_name: str,
    expected_raw_run_count: int,
    method_contract_sha256: Any,
    artifact_integrity_report: Mapping[str, Any],
    environment_report: Mapping[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "requested": requested,
        "schema_version": EXPERIMENT_RESUME_SCHEMA_VERSION,
        "run_output_dir": run_output_dir.as_posix(),
        "output_dir_has_contents": output_dir_has_contents,
        "state_path": (run_output_dir / BENCHMARK_RESUME_STATE_NAME).as_posix(),
        "checkpoint_json": (run_output_dir / BENCHMARK_CHECKPOINT_JSON_NAME).as_posix(),
        "final_json": (run_output_dir / BENCHMARK_RESULTS_JSON_NAME).as_posix(),
        "status": "not_requested",
        "completed_result_count": 0,
        "completed_unique_key_count": 0,
        "expected_result_count": expected_raw_run_count,
        "duplicate_key_count": 0,
        "errors": [],
    }
    if not requested:
        return report
    local_errors: list[str] = []
    if not run_output_dir.exists():
        local_errors.append(f"resume requested but output directory does not exist: {run_output_dir}")
    state_path = run_output_dir / BENCHMARK_RESUME_STATE_NAME
    state = _read_json_object(state_path, local_errors, label="resume state")
    if state:
        if state.get("schema_version") != EXPERIMENT_RESUME_SCHEMA_VERSION:
            local_errors.append(
                "resume state schema mismatch: "
                f"{state.get('schema_version')}"
            )
        contract = state.get("contract") if isinstance(state.get("contract"), Mapping) else {}
        _compare_resume_contract_value(
            contract,
            ("run_id",),
            run_id,
            local_errors,
        )
        _compare_resume_contract_value(
            contract,
            ("git_commit",),
            _nested_value(artifact_integrity_report, "git", "commit"),
            local_errors,
        )
        _compare_resume_contract_value(
            contract,
            ("dataset", "sha256"),
            benchmark_sha256,
            local_errors,
        )
        _compare_resume_contract_value(
            contract,
            ("method_contract_sha256",),
            method_contract_sha256,
            local_errors,
        )
        _compare_resume_contract_value(
            contract,
            ("methods",),
            selected_methods,
            local_errors,
        )
        _compare_resume_contract_value(contract, ("repeats",), repeats, local_errors)
        _compare_resume_contract_value(
            contract,
            ("method_order_seed",),
            method_order_seed,
            local_errors,
        )
        _compare_resume_contract_value(
            contract,
            ("model_config_name",),
            model_config_name,
            local_errors,
        )
        _compare_resume_contract_value(
            contract,
            ("model_config", "base_url"),
            environment_report.get("LLM_BASE_URL"),
            local_errors,
        )
        _compare_resume_contract_value(
            contract,
            ("model_config", "model"),
            environment_report.get("LLM_MODEL"),
            local_errors,
        )
        _compare_resume_contract_value(
            contract,
            ("model_config", "temperature"),
            environment_report.get("LLM_TEMPERATURE"),
            local_errors,
        )
        _compare_resume_contract_value(
            contract,
            ("model_config", "timeout_seconds"),
            environment_report.get("LLM_TIMEOUT"),
            local_errors,
        )
        _compare_resume_contract_value(
            contract,
            ("model_config", "max_tokens"),
            environment_report.get("LLM_MAX_TOKENS"),
            local_errors,
        )
        _compare_resume_contract_value(
            contract,
            ("model_config", "retry_max_attempts"),
            environment_report.get("LLM_RETRY_MAX_ATTEMPTS"),
            local_errors,
        )
        _compare_resume_contract_value(
            contract,
            ("model_config", "reasoning_effort"),
            environment_report.get("LLM_REASONING_EFFORT"),
            local_errors,
        )
        _compare_resume_contract_value(
            contract,
            ("model_config", "deterministic_research_final_answer"),
            environment_report.get("EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER"),
            local_errors,
        )
        progress = state.get("progress") if isinstance(state.get("progress"), Mapping) else {}
        report["state_status"] = state.get("status")
        report["state_progress"] = progress
        report["resume_event_count"] = len(state.get("resume_events") or [])

    previous_preflight = _read_json_object(
        run_output_dir / "formal_preflight_report.json",
        local_errors,
        label="previous formal preflight report",
    )
    if previous_preflight:
        if previous_preflight.get("schema_version") != FORMAL_PREFLIGHT_SCHEMA_VERSION:
            local_errors.append(
                "previous formal preflight schema mismatch: "
                f"{previous_preflight.get('schema_version')}"
            )
        if previous_preflight.get("status") != "passed":
            local_errors.append("previous formal preflight did not pass")
        _compare_plain_value(
            "previous run.run_id",
            _nested_value(previous_preflight, "run", "run_id"),
            run_id,
            local_errors,
        )
        _compare_plain_value(
            "previous benchmark.sha256",
            _nested_value(previous_preflight, "benchmark", "sha256"),
            benchmark_sha256,
            local_errors,
        )
        _compare_plain_value(
            "previous method_fairness_contract.contract_sha256",
            _nested_value(
                previous_preflight,
                "method_fairness_contract",
                "contract_sha256",
            ),
            method_contract_sha256,
            local_errors,
        )
        _compare_plain_value(
            "previous run.method_order_seed",
            _nested_value(previous_preflight, "run", "method_order_seed"),
            method_order_seed,
            local_errors,
        )
        _compare_plain_value(
            "previous run.model_config_name",
            _nested_value(previous_preflight, "run", "model_config_name"),
            model_config_name,
            local_errors,
        )
        _compare_plain_value(
            "previous run.expected_raw_run_count",
            _nested_value(previous_preflight, "run", "expected_raw_run_count"),
            expected_raw_run_count,
            local_errors,
        )
    else:
        report["previous_preflight_missing"] = True

    checkpoint_results = _read_json_list(
        run_output_dir / BENCHMARK_CHECKPOINT_JSON_NAME,
        local_errors,
        label="checkpoint results",
        required=False,
    )
    final_results = _read_json_list(
        run_output_dir / BENCHMARK_RESULTS_JSON_NAME,
        local_errors,
        label="final results",
        required=False,
    )
    results = final_results if len(final_results) > len(checkpoint_results) else checkpoint_results
    key_report = _resume_result_key_report(results, run_id=run_id)
    report.update(key_report)
    if key_report["duplicate_key_count"]:
        local_errors.append("resume checkpoint contains duplicate result keys")
    if key_report["foreign_run_id_count"]:
        local_errors.append("resume checkpoint contains results from a different run_id")
    if len(results) > expected_raw_run_count:
        local_errors.append(
            f"resume checkpoint has too many results: {len(results)} > {expected_raw_run_count}"
        )
    if not state and not results:
        local_errors.append("resume requested but no resume state or result checkpoint exists")

    report["status"] = "resume_allowed" if not local_errors else "resume_blocked"
    report["errors"] = local_errors
    errors.extend(local_errors)
    return report


def _compare_resume_contract_value(
    contract: Mapping[str, Any],
    path: tuple[str, ...],
    expected: Any,
    errors: list[str],
) -> None:
    _compare_plain_value(
        f"resume contract {'.'.join(path)}",
        _nested_value(contract, *path),
        expected,
        errors,
    )


def _compare_plain_value(
    label: str,
    actual: Any,
    expected: Any,
    errors: list[str],
) -> None:
    if actual != expected:
        errors.append(f"{label} mismatch: previous={actual!r}, current={expected!r}")


def _read_json_object(
    path: Path,
    errors: list[str],
    *,
    label: str,
    required: bool = True,
) -> dict[str, Any]:
    if not path.exists():
        if required:
            errors.append(f"{label} is missing: {path}")
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label} is invalid: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label} must be a JSON object: {path}")
        return {}
    return value


def _read_json_list(
    path: Path,
    errors: list[str],
    *,
    label: str,
    required: bool = False,
) -> list[dict[str, Any]]:
    if not path.exists():
        if required:
            errors.append(f"{label} is missing: {path}")
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label} is invalid: {exc}")
        return []
    if not isinstance(value, list):
        errors.append(f"{label} must be a JSON list: {path}")
        return []
    return [item for item in value if isinstance(item, dict)]


def _nested_value(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _resume_result_key_report(
    results: list[dict[str, Any]],
    *,
    run_id: str,
) -> dict[str, Any]:
    seen: set[tuple[str, str, str, str]] = set()
    duplicates = 0
    foreign_run_id_count = 0
    for result in results:
        if str(result.get("run_id") or "") != run_id:
            foreign_run_id_count += 1
        key = (
            str(result.get("case_id") or result.get("scenario_id") or ""),
            str(result.get("turn_id") or ""),
            str(result.get("method") or ""),
            str(result.get("repeat_index") or ""),
        )
        if key in seen:
            duplicates += 1
        seen.add(key)
    return {
        "completed_result_count": len(results),
        "completed_unique_key_count": len(seen),
        "duplicate_key_count": duplicates,
        "foreign_run_id_count": foreign_run_id_count,
    }


def _validated_repeats(repeats: Any, errors: list[str]) -> int:
    if isinstance(repeats, bool):
        errors.append("repeats must be a positive integer")
        return 1
    try:
        value = int(repeats)
    except (TypeError, ValueError):
        errors.append("repeats must be a positive integer")
        return 1
    if value < 1:
        errors.append("repeats must be a positive integer")
        return 1
    return value


def _method_contract_report(
    selected_methods: tuple[str, ...],
    errors: list[str],
) -> dict[str, Any]:
    if not selected_methods:
        return {"active_methods": [], "contract_sha256": None}
    try:
        return {
            **build_method_fairness_contract(selected_methods),
            "contract_sha256": method_fairness_contract_hash(selected_methods),
        }
    except ValueError as exc:
        if str(exc) not in errors:
            errors.append(str(exc))
        return {"active_methods": list(selected_methods), "contract_sha256": None}


def _validate_cases(
    cases: list[dict[str, Any]],
    *,
    errors: list[str],
    warnings: list[str],
    strict_formal: bool,
) -> None:
    if not cases:
        errors.append("benchmark must contain at least one case")
        return

    seen_case_ids: set[str] = set()
    for index, case in enumerate(cases, start=1):
        case_id = _case_id(case)
        label = case_id or f"case#{index}"
        if not case_id:
            errors.append(f"{label}: case_id is required for formal experiments")
        elif case_id in seen_case_ids:
            errors.append(f"{label}: duplicate case_id")
        seen_case_ids.add(case_id)

        if strict_formal and _has_previous_state(case):
            errors.append(
                f"{label}: formal cases must not contain handcrafted previous_state"
            )
        if _is_oracle_mode(case):
            errors.append(f"{label}: oracle_slots mode is not allowed in formal runs")

        if _is_scenario_case(case):
            _validate_scenario_turns(
                case,
                label=label,
                errors=errors,
                warnings=warnings,
                strict_formal=strict_formal,
            )
            continue

        if not _has_visible_user_input(case):
            errors.append(f"{label}: user_input/query/prompt/message/input is required")
        if not _has_evaluation_labels(case):
            warnings.append(f"{label}: no expected/gold labels found for independent evaluation")


def _validate_scenario_turns(
    case: Mapping[str, Any],
    *,
    label: str,
    errors: list[str],
    warnings: list[str],
    strict_formal: bool,
) -> None:
    turns = case.get("turns")
    if not isinstance(turns, list) or not turns:
        errors.append(f"{label}: scenario turns must be a non-empty list")
        return
    seen_turn_ids: set[str] = set()
    for index, turn in enumerate(turns, start=1):
        if not isinstance(turn, Mapping):
            errors.append(f"{label}/turn#{index}: turn must be an object")
            continue
        turn_id = str(turn.get("turn_id") or turn.get("id") or f"turn_{index:02d}")
        if turn_id in seen_turn_ids:
            errors.append(f"{label}/{turn_id}: duplicate turn_id")
        seen_turn_ids.add(turn_id)
        if strict_formal and _has_previous_state(turn):
            errors.append(
                f"{label}/{turn_id}: formal turns must not contain handcrafted previous_state"
            )
        if _is_oracle_mode(turn):
            errors.append(f"{label}/{turn_id}: oracle_slots mode is not allowed in formal runs")
        if not _has_visible_user_input(turn):
            errors.append(f"{label}/{turn_id}: user_input/query/prompt/message/input is required")
        if not _has_evaluation_labels(turn) and not _has_evaluation_labels(case):
            warnings.append(
                f"{label}/{turn_id}: no expected/gold labels found for independent evaluation"
            )


def _validate_generation_visibility(
    cases: list[dict[str, Any]],
    methods: tuple[str, ...],
    *,
    errors: list[str],
) -> None:
    for case in cases:
        validation_units = _generation_visibility_units(case)
        for unit in validation_units:
            label = str(unit.get("case_id") or unit.get("scenario_id") or "case")
            for method in methods:
                try:
                    visible = build_generation_case(unit, method)
                except Exception as exc:
                    errors.append(f"{label}/{method}: generation input failed: {exc}")
                    continue
                if contains_evaluator_only_generation_fields(visible):
                    errors.append(
                        f"{label}/{method}: generation-visible input contains evaluator-only fields"
                    )


def _generation_visibility_units(case: dict[str, Any]) -> list[dict[str, Any]]:
    if not _is_scenario_case(case):
        return [case]
    scenario_id = _case_id(case) or str(case.get("scenario_id") or "")
    units: list[dict[str, Any]] = []
    for index, turn in enumerate(case.get("turns") or [], start=1):
        if not isinstance(turn, dict):
            continue
        units.append(
            {
                **{key: value for key, value in case.items() if key != "turns"},
                **turn,
                "case_id": scenario_id,
                "scenario_id": scenario_id,
                "turn_id": str(turn.get("turn_id") or turn.get("id") or f"turn_{index:02d}"),
            }
        )
    return units


def _fixed_data_report(errors: list[str]) -> dict[str, Any]:
    try:
        snapshot = validate_fixed_data_snapshot()
    except Exception as exc:
        errors.append(f"fixed offline data snapshot is invalid: {exc}")
        return {"valid": False, "error": str(exc)}
    return {
        "valid": True,
        "schema_version": snapshot.get("schema_version"),
        "hash_strategy": snapshot.get("hash_strategy"),
        "file_count": snapshot.get("file_count"),
        "combined_sha256": snapshot.get("combined_sha256"),
        "city_ids": snapshot.get("city_ids"),
    }


def _qweather_snapshot_report(errors: list[str]) -> dict[str, Any]:
    try:
        snapshot = validate_qweather_snapshot()
    except Exception as exc:
        errors.append(f"qweather frozen weather snapshot is invalid: {exc}")
        return {"valid": False, "error": str(exc)}
    return {
        "valid": True,
        "schema_version": snapshot.get("schema_version"),
        "provider": snapshot.get("provider"),
        "snapshot_id": snapshot.get("snapshot_id"),
        "hash_strategy": snapshot.get("hash_strategy"),
        "combined_sha256": snapshot.get("combined_sha256"),
        "forecast_endpoint": snapshot.get("forecast_endpoint"),
        "forecast_horizon_days": snapshot.get("forecast_horizon_days"),
        "forecast_start_date": snapshot.get("forecast_start_date"),
        "forecast_end_date": snapshot.get("forecast_end_date"),
        "cities": snapshot.get("cities"),
        "file_count": len(snapshot.get("files") or []),
        "validation_report": {
            "required": True,
            "path": "data/weather_snapshot/qweather_v1/validation_report.json",
        },
        "real_time_api_allowed": snapshot.get("real_time_api_allowed"),
    }


def _intercity_transport_snapshot_report(errors: list[str]) -> dict[str, Any]:
    try:
        snapshot = validate_intercity_transport_snapshot()
    except Exception as exc:
        errors.append(f"intercity frozen transport snapshot is invalid: {exc}")
        return {"valid": False, "error": str(exc)}
    return {
        "valid": True,
        "schema_version": snapshot.get("schema_version"),
        "provider": snapshot.get("provider"),
        "snapshot_id": snapshot.get("snapshot_id"),
        "source_name": snapshot.get("source_name"),
        "hash_strategy": snapshot.get("hash_strategy"),
        "combined_sha256": snapshot.get("combined_sha256"),
        "fare_snapshot_date": snapshot.get("fare_snapshot_date"),
        "transport_mode": snapshot.get("transport_mode"),
        "seat_class": snapshot.get("seat_class"),
        "route_count": snapshot.get("route_count"),
        "symmetric_route_lookup_allowed": snapshot.get("symmetric_route_lookup_allowed"),
        "file_count": len(snapshot.get("files") or []),
        "evidence": snapshot.get("evidence") or {},
        "real_time_api_allowed": snapshot.get("real_time_api_allowed"),
        "runtime_online_refresh_allowed": snapshot.get("runtime_online_refresh_allowed"),
        "real_time_price_claim_allowed": snapshot.get("real_time_price_claim_allowed"),
    }


def _budget_gold_report(
    *,
    benchmark_file: Path,
    document: Any,
    errors: list[str],
    strict_formal: bool,
) -> dict[str, Any]:
    required = strict_formal and _requires_ctp100_budget_gold(benchmark_file, document)
    if not required:
        return {
            "required": False,
            "valid": None,
            "path": DEFAULT_CTP100_BUDGET_GOLD_PATH.as_posix(),
            "reason": "benchmark_is_not_ctp100_formal_v2",
        }
    source_dataset_path = (
        benchmark_file
        if benchmark_file.name == "ctp100_formal_v2.json"
        else DEFAULT_CTP100_DATASET_PATH
    )
    try:
        document = validate_budget_gold(
            DEFAULT_CTP100_BUDGET_GOLD_PATH,
            source_dataset_path=source_dataset_path,
        )
    except BudgetGoldError as exc:
        errors.append(f"formal budget gold is invalid: {exc}")
        return {
            "required": True,
            "valid": False,
            "path": DEFAULT_CTP100_BUDGET_GOLD_PATH.as_posix(),
            "source_dataset_path": source_dataset_path.as_posix(),
            "error": str(exc),
        }
    return {
        "required": True,
        "valid": True,
        "path": document.get("path"),
        "schema_version": document.get("schema_version"),
        "gold_status": document.get("gold_status"),
        "review_status": document.get("review_status"),
        "source_dataset_sha256": document.get("source_dataset_sha256"),
        "summary": document.get("summary") or {},
        "artifact_hashes": document.get("artifact_hashes") or {},
    }


def _requires_ctp100_budget_gold(benchmark_file: Path, document: Any) -> bool:
    if benchmark_file.name == "ctp100_formal_v2.json":
        return True
    if not isinstance(document, Mapping):
        return False
    if document.get("dataset_id") == "ctp100_formal_v2":
        return True
    return list(document.get("case_files") or []) == ["ctp100_formal_v2.json"]


def _academic_design_report(
    *,
    benchmark_file: Path,
    required: bool,
    errors: list[str],
) -> dict[str, Any]:
    if not required:
        return {
            "required": False,
            "status": "not_required",
            "reason": "benchmark_is_not_ctp100_formal_v2",
        }
    try:
        report = build_academic_experiment_design_report(
            benchmark_manifest_path=benchmark_file,
        )
    except Exception as exc:
        errors.append(f"academic experiment design validation failed: {exc}")
        return {"required": True, "status": "failed", "error": str(exc)}
    if report.get("status") != "passed":
        design_errors = report.get("errors") if isinstance(report.get("errors"), list) else []
        errors.append(
            "academic experiment design must pass before formal runs"
            + (f": {'; '.join(str(item) for item in design_errors)}" if design_errors else "")
        )
    return {"required": True, **report}


def _validate_artifact_integrity(
    report: Mapping[str, Any],
    *,
    errors: list[str],
    required: bool,
    require_clean_git: bool,
) -> None:
    if required and report.get("all_required_artifacts_exist") is not True:
        missing = report.get("missing_artifacts") if isinstance(report.get("missing_artifacts"), list) else []
        errors.append(f"formal artifact integrity missing required artifacts: {missing}")
    git = report.get("git") if isinstance(report.get("git"), Mapping) else {}
    if require_clean_git and git.get("worktree_clean") is not True:
        errors.append("git working tree must be clean before formal runs")


def _day8_delivery_pack_report(
    path: Path,
    *,
    artifact_integrity_report: Mapping[str, Any],
    errors: list[str],
    required: bool,
) -> dict[str, Any]:
    if not required:
        return {
            "required": False,
            "path": path.as_posix(),
            "status": "not_required",
            "reason": "benchmark_is_not_ctp100_formal_v2",
        }
    if not path.exists():
        errors.append(f"Day8 delivery pack is required before formal runs: {path}")
        return {"required": True, "path": path.as_posix(), "status": "missing"}
    try:
        pack = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"Day8 delivery pack is invalid: {exc}")
        return {"required": True, "path": path.as_posix(), "status": "invalid", "error": str(exc)}

    readiness = pack.get("readiness") if isinstance(pack.get("readiness"), Mapping) else {}
    inventory = _day8_inventory(pack)
    hash_mismatches: list[str] = []
    missing_day8_hashes: list[str] = []
    for integrity_key, day8_key in _DAY8_ARTIFACT_HASH_KEYS.items():
        current_hash = _artifact_hash(artifact_integrity_report, integrity_key)
        day8_hash = inventory.get(day8_key)
        if current_hash and not day8_hash:
            missing_day8_hashes.append(integrity_key)
        elif current_hash and day8_hash and current_hash != day8_hash:
            hash_mismatches.append(integrity_key)
    if readiness.get("status") != "day8_delivery_ready":
        errors.append(
            "Day8 delivery pack must be ready before formal runs"
        )
    if hash_mismatches:
        errors.append(
            "Day8 delivery pack is stale for formal artifacts: "
            + ", ".join(hash_mismatches)
        )
    if missing_day8_hashes:
        errors.append(
            "Day8 delivery pack does not record required formal artifact hashes: "
            + ", ".join(missing_day8_hashes)
        )
    return {
        "required": True,
        "path": path.as_posix(),
        "status": readiness.get("status") or "unknown",
        "ready_for_formal_experiment": readiness.get("ready_for_formal_experiment"),
        "failed_checks": readiness.get("failed_checks") or [],
        "current_artifact_hashes_match": not hash_mismatches,
        "hash_mismatches": hash_mismatches,
        "missing_artifact_hashes": missing_day8_hashes,
    }


def _day8_inventory(pack: Mapping[str, Any]) -> dict[str, str]:
    items = pack.get("artifact_inventory") if isinstance(pack.get("artifact_inventory"), list) else []
    result: dict[str, str] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        key = str(item.get("key") or "")
        value = item.get("sha256")
        if key and isinstance(value, str) and len(value) == 64:
            result[key] = value
    return result


def _artifact_hash(report: Mapping[str, Any], key: str) -> str | None:
    artifacts = report.get("artifacts") if isinstance(report.get("artifacts"), Mapping) else {}
    item = artifacts.get(key) if isinstance(artifacts, Mapping) else None
    if not isinstance(item, Mapping):
        return None
    value = item.get("sha256")
    return str(value) if isinstance(value, str) and value else None


def _environment_report(
    *,
    errors: list[str],
    warnings: list[str],
    require_llm_config: bool,
    strict_formal: bool,
) -> dict[str, Any]:
    env = {
        "EXPERIMENT_STRICT_MODE": _env_bool("EXPERIMENT_STRICT_MODE"),
        "EXPERIMENT_DISABLE_CACHE": _env_bool("EXPERIMENT_DISABLE_CACHE"),
        "TRACE_SAVE_USER_MESSAGE": _env_bool("TRACE_SAVE_USER_MESSAGE"),
        "LLM_MODEL": os.getenv("LLM_MODEL") or settings.llm.model,
        "LLM_BASE_URL": os.getenv("LLM_BASE_URL") or settings.llm.base_url,
        "LLM_TEMPERATURE": _env_float("LLM_TEMPERATURE", settings.llm.temperature),
        "LLM_MAX_TOKENS": _env_int("LLM_MAX_TOKENS", settings.llm.max_tokens),
        "LLM_TIMEOUT": _env_int("LLM_TIMEOUT", settings.llm.timeout),
        "LLM_RETRY_MAX_ATTEMPTS": _env_int(
            "LLM_RETRY_MAX_ATTEMPTS",
            settings.llm.retry_max_attempts,
        ),
        LLM_REASONING_EFFORT_ENV: _env_text(LLM_REASONING_EFFORT_ENV),
        FORMAL_DETERMINISTIC_RESEARCH_FINAL_ANSWER_ENV: _env_bool(
            FORMAL_DETERMINISTIC_RESEARCH_FINAL_ANSWER_ENV
        ),
        "LLM_CONFIGURED": _llm_configured(),
        "OLLAMA_CONFIGURED": bool(os.getenv("OLLAMA_MODEL") or os.getenv("OLLAMA_BASE_URL")),
    }
    if strict_formal:
        if env["EXPERIMENT_STRICT_MODE"] is not True:
            errors.append("EXPERIMENT_STRICT_MODE must be true for formal runs")
        if env["EXPERIMENT_DISABLE_CACHE"] is not True:
            errors.append("EXPERIMENT_DISABLE_CACHE must be true for formal runs")
        if env["TRACE_SAVE_USER_MESSAGE"] is True:
            errors.append("TRACE_SAVE_USER_MESSAGE must not be true for formal runs")
        if env[FORMAL_DETERMINISTIC_RESEARCH_FINAL_ANSWER_ENV] is not True:
            errors.append(
                f"{FORMAL_DETERMINISTIC_RESEARCH_FINAL_ANSWER_ENV} must be true "
                "for formal runs to match the frozen Day 7 development protocol"
            )
        if env["LLM_TEMPERATURE"] is None:
            errors.append("LLM_TEMPERATURE must be numeric for formal runs")
        elif float(env["LLM_TEMPERATURE"]) != 0.0:
            errors.append("LLM_TEMPERATURE must be 0 for formal runs")
        if env["LLM_MAX_TOKENS"] is None or int(env["LLM_MAX_TOKENS"]) < FORMAL_MIN_MAX_TOKENS:
            errors.append(
                f"LLM_MAX_TOKENS must be an integer >= {FORMAL_MIN_MAX_TOKENS} "
                "for formal runs"
            )
        if env["LLM_TIMEOUT"] is None or int(env["LLM_TIMEOUT"]) < 1:
            errors.append("LLM_TIMEOUT must be a positive integer for formal runs")
        if env["LLM_RETRY_MAX_ATTEMPTS"] is None:
            errors.append("LLM_RETRY_MAX_ATTEMPTS must be numeric for formal runs")
        elif int(env["LLM_RETRY_MAX_ATTEMPTS"]) != FORMAL_RETRY_MAX_ATTEMPTS:
            errors.append(
                "LLM_RETRY_MAX_ATTEMPTS must be 3 for formal runs "
                "(initial request plus at most two retries)"
            )
        reasoning_effort = env[LLM_REASONING_EFFORT_ENV]
        if reasoning_effort is not None and reasoning_effort not in SUPPORTED_REASONING_EFFORTS:
            errors.append(
                f"{LLM_REASONING_EFFORT_ENV} must be one of "
                f"{', '.join(sorted(SUPPORTED_REASONING_EFFORTS))}"
            )
        if _model_requires_minimal_reasoning_effort(env["LLM_MODEL"]):
            if reasoning_effort != FORMAL_GPT5_REASONING_EFFORT:
                errors.append(
                    f"{LLM_REASONING_EFFORT_ENV} must be "
                    f"{FORMAL_GPT5_REASONING_EFFORT} for gpt-5 formal runs"
                )
    if require_llm_config and not env["LLM_CONFIGURED"] and not env["OLLAMA_CONFIGURED"]:
        errors.append(
            "no LLM runtime configured; set LLM_API_KEY/LLM_BASE_URL/LLM_MODEL "
            "or configure OLLAMA_MODEL for a local run"
        )
    if not require_llm_config:
        warnings.append("LLM runtime configuration check skipped")
    return env


def _benchmark_structure(cases: list[dict[str, Any]]) -> dict[str, Any]:
    scenario_count = sum(1 for case in cases if _is_scenario_case(case))
    total_turn_count = sum(_case_turn_count(case) for case in cases)
    return {
        "case_count": len(cases),
        "single_turn_case_count": len(cases) - scenario_count,
        "scenario_case_count": scenario_count,
        "total_turn_count": total_turn_count,
        "statistical_unit": "case_id",
    }


def _case_id(case: Mapping[str, Any]) -> str:
    return str(case.get("case_id") or case.get("scenario_id") or case.get("id") or "").strip()


def _case_turn_count(case: Mapping[str, Any]) -> int:
    turns = case.get("turns")
    if isinstance(turns, list) and turns:
        return len(turns)
    return 1


def _is_scenario_case(case: Mapping[str, Any]) -> bool:
    return isinstance(case.get("turns"), list) and bool(case.get("turns"))


def _has_visible_user_input(case: Mapping[str, Any]) -> bool:
    for key in ("user_input", "query", "prompt", "message", "input"):
        value = case.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, Mapping) and value:
            return True
    return False


def _has_previous_state(case: Mapping[str, Any]) -> bool:
    return "previous_state" in case or "method_previous_state" in case


def _is_oracle_mode(case: Mapping[str, Any]) -> bool:
    return str(case.get("evaluation_mode") or "").strip().lower().replace("-", "_") in {
        "oracle",
        "oracle_slot",
        "oracle_slots",
    }


def _has_evaluation_labels(case: Mapping[str, Any]) -> bool:
    return any(key in case for key in ("expected", "expected_goal", "gold", "hard_constraints"))


def _env_bool(name: str) -> bool | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float | None:
    raw = os.getenv(name)
    if raw is None:
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return None


def _env_int(name: str, default: int) -> int | None:
    raw = os.getenv(name)
    if raw is None:
        return int(default)
    try:
        return int(raw)
    except ValueError:
        return None


def _env_text(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip().lower()
    return value or None


def _model_requires_minimal_reasoning_effort(model: Any) -> bool:
    return str(model or "").strip().lower().startswith("gpt-5")


def _llm_configured() -> bool:
    return bool(os.getenv("LLM_API_KEY") or settings.llm.is_configured)
