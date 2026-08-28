import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.benchmark_dataset_validator import build_benchmark_dataset_quality_report  # noqa: E402
from app.core.fixed_data import canonical_json_file_sha256, canonical_json_sha256  # noqa: E402
from app.core.formal_experiment_preflight import load_benchmark_document  # noqa: E402


FROZEN_DATASET_PATH = ROOT / "experiments" / "ctp30_multiturn_validation_v2.json"
FREEZE_MANIFEST_PATH = (
    ROOT / "experiments" / "generated" / "ctp30_multiturn_v2_freeze_manifest.json"
)
DRAFT_DATASET_PATH = ROOT / "experiments" / "generated" / "ctp30_multiturn_v2_draft.json"
EXPECTED_TARGET_TASK_DISTRIBUTION = {
    "attraction_recommendation": 1,
    "budget_query": 4,
    "clarification": 1,
    "partial_replan": 15,
    "weather_adjustment": 6,
    "weather_query": 3,
}


def test_ctp30_multiturn_v2_is_frozen_reviewed_two_turn_dataset() -> None:
    document = _read_json(FROZEN_DATASET_PATH)
    cases = document["cases"]

    assert document["dataset_id"] == "ctp30_multiturn_validation_v2"
    assert document["dataset_role"] == "sealed_multiturn_validation_after_ctp100_v6_and_ctp30_v1"
    assert document["split"] == "sealed_multiturn_validation"
    assert document["case_count"] == 30
    assert document["turn_count"] == 60
    assert document["claim_policy"]["draft_only"] is False
    assert document["claim_policy"]["used_for_development_tuning"] is False
    assert document["annotation_policy"]["manual_review_status"] == "confirmed"
    assert document["annotation_policy"]["human_review_completed"] is True
    assert document["freeze_policy"]["allowed_methods"] == [
        "fixed_multi_agent",
        "adaptive_multi_agent",
    ]
    assert document["freeze_policy"]["gold_visible_to_generation"] is False
    assert document["freeze_policy"]["previous_state_injection_allowed"] is False

    assert len(cases) == 30
    assert len({case["case_id"] for case in cases}) == 30
    assert all("user_input" not in case for case in cases)
    assert all(case["primary_turn_id"] == "t2" for case in cases)
    assert all(case["evaluation_scope"] == "target_turn_only_after_freeze" for case in cases)
    assert all([turn["turn_id"] for turn in case["turns"]] == ["t1", "t2"] for case in cases)
    assert all(len(case["turns"]) == 2 for case in cases)

    target_distribution = Counter(case["turns"][1]["task_type"] for case in cases)
    assert dict(sorted(target_distribution.items())) == EXPECTED_TARGET_TASK_DISTRIBUTION


def test_ctp30_multiturn_v2_quality_gate_passes_with_ctp100_comparison() -> None:
    document, cases = load_benchmark_document(FROZEN_DATASET_PATH)
    _, ctp100_cases = load_benchmark_document(ROOT / "experiments" / "ctp100_formal_v2.json")

    report = build_benchmark_dataset_quality_report(
        document=document,
        cases=cases,
        expected_case_count=30,
        strict_formal=True,
        comparison_splits={"ctp100_formal_v2": ctp100_cases},
    )

    assert report["status"] == "passed", report["errors"]
    assert report["warnings"] == []
    assert report["dataset"]["case_count"] == 30
    assert report["dataset"]["scenario_case_count"] == 30
    assert report["dataset"]["total_unit_count"] == 60
    assert report["coverage"]["cross_split_duplicate_visible_input_groups"] == []
    assert report["coverage"]["near_duplicate_visible_input_pairs"] == []
    assert set(report["coverage"]["task_distribution"]) == set(
        report["coverage"]["recommended_task_types"]
    )
    assert set(report["coverage"]["city_distribution"]) == {
        "beijing",
        "guilin",
        "hangzhou",
        "shenzhen",
        "xian",
    }


def test_ctp30_multiturn_v2_freeze_manifest_matches_artifacts() -> None:
    manifest = _read_json(FREEZE_MANIFEST_PATH)
    frozen = _read_json(FROZEN_DATASET_PATH)

    assert manifest["status"] == "passed"
    assert manifest["frozen_dataset"]["path"] == "experiments/ctp30_multiturn_validation_v2.json"
    assert manifest["frozen_dataset"]["sha256"] == canonical_json_sha256(frozen)
    assert manifest["source_draft"]["path"] == "experiments/generated/ctp30_multiturn_v2_draft.json"
    assert manifest["source_draft"]["sha256"] == canonical_json_file_sha256(DRAFT_DATASET_PATH)
    assert manifest["quality_gate"]["status"] == "passed"
    assert manifest["quality_gate"]["errors"] == []
    assert manifest["quality_gate"]["warnings"] == []
    assert manifest["paper_use_policy"]["must_disclose_single_annotator"] is True
    assert manifest["paper_use_policy"]["must_not_claim_multi_annotator_agreement"] is True
    assert manifest["api_usage"] == {
        "llm_calls": 0,
        "weather_api_calls": 0,
        "intercity_api_calls": 0,
    }


def test_ctp30_multiturn_v2_is_excluded_from_ctp100_main_manifest() -> None:
    main_manifest = _read_json(ROOT / "experiments" / "benchmark.json")

    assert main_manifest["case_files"] == ["ctp100_formal_v2.json"]
    assert "ctp30_multiturn_validation_v2.json" not in main_manifest.get("case_files", [])
    assert "ctp30_multiturn_validation_v2.json" not in main_manifest.get(
        "comparison_files",
        [],
    )
    excluded = {
        str(item.get("file")): str(item.get("reason"))
        for item in main_manifest.get("excluded_case_files") or []
        if isinstance(item, dict)
    }
    assert excluded["ctp30_multiturn_validation_v2.json"].startswith(
        "sealed_multiturn_validation_after_ctp100_v6_and_ctp30_v1"
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
