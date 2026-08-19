import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.academic_experiment_design import (  # noqa: E402
    EXPECTED_SEALED_CASE_COUNT,
    EXPECTED_SEALED_TURN_COUNT,
    MAIN_BENCHMARK_ROLE,
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
    assert report["main_benchmark"]["dataset_role"] == MAIN_BENCHMARK_ROLE
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
