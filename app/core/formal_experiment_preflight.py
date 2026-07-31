"""Preflight checks for paper-level formal experiment runs."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.core.config import settings
from app.core.benchmark_dataset_validator import (
    build_benchmark_dataset_quality_report,
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


FORMAL_PREFLIGHT_SCHEMA_VERSION = "ctp-formal-preflight-v1"
DEFAULT_FORMAL_METHOD_ORDER_SEED = 20260718
FORMAL_RESULT_FILES = (
    "benchmark_results.csv",
    "benchmark_results.json",
    "evaluation_summary.json",
    "paper_tables.md",
    "experiment_manifest.json",
)


def build_formal_preflight_report(
    *,
    benchmark_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    methods: Iterable[str] | None = None,
    repeats: int = 1,
    method_order_seed: int = DEFAULT_FORMAL_METHOD_ORDER_SEED,
    expected_case_count: int | None = None,
    require_llm_config: bool = True,
    strict_formal: bool = True,
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
    if not benchmark_file.exists():
        errors.append(f"benchmark file does not exist: {benchmark_file}")
    else:
        try:
            document, cases = load_benchmark_document(benchmark_file)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"benchmark file is invalid: {exc}")

    if run_output_dir.exists() and any(run_output_dir.iterdir()):
        errors.append(f"output directory is not empty: {run_output_dir}")

    if expected_case_count is not None and len(cases) != expected_case_count:
        errors.append(
            f"case_count mismatch: expected {expected_case_count}, got {len(cases)}"
        )

    _validate_cases(cases, errors=errors, warnings=warnings, strict_formal=strict_formal)
    dataset_quality_report = build_benchmark_dataset_quality_report(
        document=document,
        cases=cases,
        expected_case_count=expected_case_count,
        strict_formal=strict_formal,
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
    fixed_data_report = _fixed_data_report(errors)
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
            "expected_raw_run_count": raw_run_count,
            "expected_result_files": list(FORMAL_RESULT_FILES),
        },
        "method_fairness_contract": method_contract,
        "benchmark_quality": dataset_quality_report,
        "fixed_data": fixed_data_report,
        "environment": environment_report,
        "policy": {
            "strict_formal": strict_formal,
            "gold_visible_to_generation": False,
            "previous_state_policy": (
                "formal multi-turn state must be produced by the same method's prior turn"
            ),
            "no_overwrite": True,
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


def _cases_from_loaded_case_file(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [case for case in value if isinstance(case, dict)]
    if isinstance(value, dict) and isinstance(value.get("cases"), list):
        return [case for case in value["cases"] if isinstance(case, dict)]
    if isinstance(value, dict):
        return [value]
    return []


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
        "LLM_TEMPERATURE": _env_float("LLM_TEMPERATURE", settings.llm.temperature),
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
        if env["LLM_TEMPERATURE"] is None:
            errors.append("LLM_TEMPERATURE must be numeric for formal runs")
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


def _llm_configured() -> bool:
    return bool(os.getenv("LLM_API_KEY") or settings.llm.is_configured)
