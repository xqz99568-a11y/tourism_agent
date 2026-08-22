import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.experiment_runner import ExperimentRunner  # noqa: E402
from app.core.pre_formal_validation_registry import (  # noqa: E402
    CRITICAL_CODE_PATHS,
    DEFAULT_PRE_FORMAL_TASK_REPORT_PATHS,
    PRE_FORMAL_VALIDATION_REGISTRY_SCHEMA_VERSION,
    validate_pre_formal_validation_registry,
    write_pre_formal_validation_registry,
)
from app.core.formal_experiment_preflight import build_formal_preflight_report  # noqa: E402


def test_pre_formal_validation_registry_accepts_current_reports(tmp_path: Path) -> None:
    registry_path = write_pre_formal_validation_registry(output_path=tmp_path / "registry.json")

    report = validate_pre_formal_validation_registry(registry_path)

    assert report["schema_version"] == PRE_FORMAL_VALIDATION_REGISTRY_SCHEMA_VERSION
    assert report["status"] == "passed", report["errors"]
    assert report["summary"]["required_task_count"] == 3
    assert report["summary"]["passed_task_count"] == 3
    assert report["summary"]["transparent_warning_policy"] == "accepted_but_reported"
    assert report["summary"]["transparent_warning_count"] >= 1
    assert {item["task_id"] for item in report["tasks"]} == {
        "task_d_m0_real_api",
        "task_e_four_method_real_api",
        "task_f_multiturn_real_api",
    }


def test_pre_formal_validation_registry_blocks_missing_task_report(tmp_path: Path) -> None:
    report_paths = {
        **DEFAULT_PRE_FORMAL_TASK_REPORT_PATHS,
        "task_f_multiturn_real_api": tmp_path / "missing_task_f_report.json",
    }
    registry_path = write_pre_formal_validation_registry(
        output_path=tmp_path / "registry_missing.json",
        report_paths=report_paths,
    )

    report = validate_pre_formal_validation_registry(registry_path)

    assert report["status"] == "failed"
    assert "task_f_multiturn_real_api: report is missing" in "\n".join(report["errors"])


def test_pre_formal_validation_registry_blocks_failed_report_status(tmp_path: Path) -> None:
    failed_report = tmp_path / "task_f_failed_report.json"
    source = DEFAULT_PRE_FORMAL_TASK_REPORT_PATHS["task_f_multiturn_real_api"]
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    payload["status"] = "failed"
    payload["gate"]["status"] = "failed"
    payload["gate"]["failed_checks"] = ["forced_failure_for_unit_test"]
    failed_report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    report_paths = {
        **DEFAULT_PRE_FORMAL_TASK_REPORT_PATHS,
        "task_f_multiturn_real_api": failed_report,
    }
    registry_path = write_pre_formal_validation_registry(
        output_path=tmp_path / "registry_failed.json",
        report_paths=report_paths,
    )

    report = validate_pre_formal_validation_registry(registry_path)

    errors = "\n".join(report["errors"])
    assert report["status"] == "failed"
    assert "task_f_multiturn_real_api: status mismatch" in errors
    assert "task_f_multiturn_real_api: gate.status mismatch" in errors
    assert "task_f_multiturn_real_api: gate.failed_checks must be empty" in errors


def test_pre_formal_validation_registry_blocks_report_hash_mismatch(tmp_path: Path) -> None:
    mutable_report = tmp_path / "task_e_report.json"
    source = DEFAULT_PRE_FORMAL_TASK_REPORT_PATHS["task_e_four_method_real_api"]
    mutable_report.write_text(source.read_text(encoding="utf-8-sig"), encoding="utf-8")
    report_paths = {
        **DEFAULT_PRE_FORMAL_TASK_REPORT_PATHS,
        "task_e_four_method_real_api": mutable_report,
    }
    registry_path = write_pre_formal_validation_registry(
        output_path=tmp_path / "registry_hash.json",
        report_paths=report_paths,
    )

    payload = json.loads(mutable_report.read_text(encoding="utf-8-sig"))
    payload["results"]["actual_result_count"] = 79
    mutable_report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    report = validate_pre_formal_validation_registry(registry_path)

    assert report["status"] == "failed"
    assert "task_e_four_method_real_api: report hash mismatch" in "\n".join(report["errors"])


def test_pre_formal_validation_registry_blocks_critical_code_hash_mismatch(
    tmp_path: Path,
) -> None:
    registry_path = write_pre_formal_validation_registry(output_path=tmp_path / "registry.json")
    changed_runner = tmp_path / "experiment_runner.py"
    changed_runner.write_text("# changed after registry was written\n", encoding="utf-8")

    report = validate_pre_formal_validation_registry(
        registry_path,
        code_paths={**CRITICAL_CODE_PATHS, "experiment_runner_code": changed_runner},
    )

    assert report["status"] == "failed"
    assert "pre-formal validation critical code hash mismatch" in "\n".join(report["errors"])
    assert "experiment_runner_code" in report["critical_code"]["hash_mismatches"]


def test_formal_preflight_requires_pre_formal_validation_registry_for_ctp100(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _formal_env(monkeypatch)
    monkeypatch.setattr(
        "app.core.formal_experiment_preflight.DEFAULT_PRE_FORMAL_VALIDATION_REGISTRY_PATH",
        tmp_path / "missing_registry.json",
    )

    report = build_formal_preflight_report(
        benchmark_path=ROOT / "experiments" / "benchmark.json",
        output_dir=tmp_path / "runs",
        run_id="missing-pre-formal-validation",
        methods=ExperimentRunner.METHODS,
        repeats=1,
        expected_case_count=100,
        require_llm_config=False,
        require_day8_delivery_pack=False,
        require_clean_git=False,
    )

    errors = "\n".join(report["errors"])
    assert report["status"] == "failed"
    assert report["pre_formal_validation"]["status"] == "failed"
    assert "Task D/E/F pre-formal validation gates must pass" in errors


def _formal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPERIMENT_STRICT_MODE", "true")
    monkeypatch.setenv("EXPERIMENT_DISABLE_CACHE", "true")
    monkeypatch.setenv("TRACE_SAVE_USER_MESSAGE", "false")
    monkeypatch.setenv("LLM_TEMPERATURE", "0")
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
    monkeypatch.setenv("LLM_TIMEOUT", "120")
    monkeypatch.setenv("LLM_RETRY_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("EXPERIMENT_RESULT_HARD_TIMEOUT_SECONDS", "900")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "minimal")
    monkeypatch.setenv("EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER", "true")
