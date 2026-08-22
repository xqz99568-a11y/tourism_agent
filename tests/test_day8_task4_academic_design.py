import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.academic_experiment_design import (  # noqa: E402
    ACADEMIC_EXPERIMENT_DESIGN_VERSION,
    EXPECTED_FORMAL_PROVIDER_ACCOUNTING,
    EXPECTED_FORMAL_RESULT_HARD_TIMEOUT_MODE,
    EXPECTED_DECISION_NORMALIZATION_DIAGNOSTIC_METRICS,
    EXPECTED_PRE_FORMAL_VALIDATION_TASKS,
    EXPECTED_SEALED_CASE_COUNT,
    EXPECTED_SEALED_TURN_COUNT,
    MAIN_BENCHMARK_ROLE,
    MAIN_DATASET_VERSION,
    SEALED_VALIDATION_METHODS,
    SEALED_VALIDATION_ROLE,
    build_academic_experiment_design_report,
)
from app.core.formal_experiment_preflight import load_benchmark_document  # noqa: E402


def test_day8_task4_academic_design_freeze_is_valid() -> None:
    report = build_academic_experiment_design_report()

    assert report["status"] == "passed", report["errors"]
    assert report["warnings"] == []
    assert all(report["checks"].values())
    assert report["design"]["design_version"] == ACADEMIC_EXPERIMENT_DESIGN_VERSION
    assert report["main_benchmark"]["dataset_role"] == MAIN_BENCHMARK_ROLE
    assert report["main_benchmark"]["dataset_version"] == MAIN_DATASET_VERSION
    assert report["main_benchmark"]["case_count"] == 100
    assert report["main_benchmark"]["turn_count"] == 130
    assert report["sealed_validation"]["dataset_role"] == SEALED_VALIDATION_ROLE
    assert report["sealed_validation"]["case_count"] == EXPECTED_SEALED_CASE_COUNT
    assert report["sealed_validation"]["turn_count"] == EXPECTED_SEALED_TURN_COUNT
    assert tuple(report["sealed_validation"]["methods"]) == SEALED_VALIDATION_METHODS
    assert report["sealed_quality"]["status"] == "passed"
    assert report["sealed_quality"]["duplicate_visible_input_groups"] == []
    assert report["sealed_quality"]["cross_split_duplicate_visible_input_groups"] == []
    assert report["sealed_quality"]["near_duplicate_visible_input_pairs"] == []
    assert (
        report["runtime_controls"]["result_hard_timeout_mode"]
        == EXPECTED_FORMAL_RESULT_HARD_TIMEOUT_MODE
    )
    assert report["runtime_controls"]["result_hard_timeout_seconds"] >= 900
    assert (
        report["runtime_controls"]["provider_accounting"]
        == EXPECTED_FORMAL_PROVIDER_ACCOUNTING
    )
    assert report["runtime_controls"]["real_api_smoke_required"] is True
    assert report["pre_formal_validation"]["ctp20_four_method_joint_run_required"] is True
    assert report["pre_formal_validation"]["task_d_m0_real_api_required"] is True
    assert report["pre_formal_validation"]["task_e_four_method_real_api_required"] is True
    assert report["pre_formal_validation"]["task_f_multiturn_real_api_required"] is True
    assert tuple(report["pre_formal_validation"]["required_tasks"]) == (
        EXPECTED_PRE_FORMAL_VALIDATION_TASKS
    )
    assert (
        report["pre_formal_validation"]["registry_file"]
        == "experiments/generated/pre_formal_validation_registry_v1.json"
    )
    assert tuple(report["pre_formal_validation"]["methods"]) == (
        "llm_direct",
        "single_agent",
        "fixed_multi_agent",
        "adaptive_multi_agent",
    )
    diagnostics = report["diagnostic_metrics"]["decision_normalization"]
    assert tuple(diagnostics["metrics"]) == EXPECTED_DECISION_NORMALIZATION_DIAGNOSTIC_METRICS
    assert diagnostics["paper_usage"] == "diagnostic_not_primary_effect_metric"
    assert set(diagnostics["formulas"]) == set(EXPECTED_DECISION_NORMALIZATION_DIAGNOSTIC_METRICS)


def test_ctp100_is_controlled_main_benchmark_not_unseen_test_set() -> None:
    dataset = json.loads(
        (ROOT / "experiments" / "ctp100_formal_v2.json").read_text(encoding="utf-8-sig")
    )

    assert dataset["dataset_role"] == MAIN_BENCHMARK_ROLE
    assert dataset["claim_policy"]["claim_allowed_as_unseen"] is False
    assert "开发后冻结的受控主基准" in dataset["claim_policy"]["paper_label_zh"]
    assert "完全未见测试集" in dataset["claim_policy"]["paper_wording_required"]


def test_sealed_validation_is_not_in_main_benchmark_manifest() -> None:
    benchmark = json.loads(
        (ROOT / "experiments" / "benchmark.json").read_text(encoding="utf-8-sig")
    )
    document, cases = load_benchmark_document(ROOT / "experiments" / "benchmark.json")

    assert document["case_files"] == ["ctp100_formal_v2.json"]
    assert "ctp30_sealed_validation_v1.json" not in document["case_files"]
    assert "ctp30_sealed_validation_v1.json" not in document["comparison_files"]
    assert benchmark["excluded_case_files"][0]["file"] == "ctp30_sealed_validation_v1.json"
    assert len(cases) == 100


def test_academic_design_blocks_accidental_sealed_dataset_leak(tmp_path: Path) -> None:
    source = ROOT / "experiments" / "benchmark.json"
    leaked = tmp_path / "benchmark_leaked.json"
    benchmark = json.loads(source.read_text(encoding="utf-8-sig"))
    benchmark["case_files"] = [
        "ctp100_formal_v2.json",
        "ctp30_sealed_validation_v1.json",
    ]
    leaked.write_text(json.dumps(benchmark, ensure_ascii=False, indent=2), encoding="utf-8")

    report = build_academic_experiment_design_report(
        benchmark_manifest_path=leaked,
    )

    assert report["status"] == "failed"
    assert report["checks"]["benchmark_points_only_to_main_ctp100"] is False
    assert report["checks"]["sealed_dataset_not_in_main_benchmark"] is False
