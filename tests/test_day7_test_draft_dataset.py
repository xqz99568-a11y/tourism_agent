import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.benchmark_dataset_validator import build_benchmark_dataset_quality_report
from app.core.day7_test_draft import (
    DAY7_TEST_DRAFT_FEASIBILITY_SCHEMA_VERSION,
    DAY7_TEST_DRAFT_GATE_SCHEMA_VERSION,
    DEFAULT_EXPECTED_CASE_COUNT,
    DEFAULT_EXPECTED_SCENARIO_CASE_COUNT,
    DEFAULT_EXPECTED_TURN_COUNT,
    TEST_DRAFT_CASE_TASK_QUOTAS,
    build_ctp120_test_draft_document,
    build_day7_test_draft_gate,
)
from app.core.experiment_method_input import parse_visible_request_slots
from app.core.formal_experiment_preflight import (
    build_formal_preflight_report,
    load_benchmark_document,
)


def test_generated_day7_test_draft_matches_protocol_and_quality_gate() -> None:
    document = build_ctp120_test_draft_document()
    comparison_splits = _comparison_splits()
    quality = build_benchmark_dataset_quality_report(
        document=document,
        cases=document["cases"],
        expected_case_count=100,
        strict_formal=True,
        comparison_splits=comparison_splits,
    )
    gate = build_day7_test_draft_gate(
        document=document,
        cases=document["cases"],
        comparison_splits=comparison_splits,
        quality_report=quality,
    )

    assert quality["status"] == "passed", quality["errors"]
    assert gate["schema_version"] == DAY7_TEST_DRAFT_GATE_SCHEMA_VERSION
    assert gate["status"] == "passed", gate["failed_checks"]
    assert gate["actual"]["case_count"] == DEFAULT_EXPECTED_CASE_COUNT
    assert gate["actual"]["total_turn_count"] == DEFAULT_EXPECTED_TURN_COUNT
    assert gate["actual"]["scenario_case_count"] == DEFAULT_EXPECTED_SCENARIO_CASE_COUNT
    assert gate["actual"]["case_task_distribution"] == TEST_DRAFT_CASE_TASK_QUOTAS
    assert gate["actual"]["city_case_distribution"] == {
        "beijing": 16,
        "guilin": 16,
        "hangzhou": 16,
        "shenzhen": 16,
        "xian": 16,
    }
    assert gate["actual"]["duplicate_counts"] == {
        "internal_duplicate_count": 0,
        "cross_split_duplicate_count": 0,
        "near_duplicate_count": 0,
        "semantic_template_duplicate_count": 0,
        "tourism_template_family_count": 58,
        "max_tourism_template_family_size": 6,
    }
    assert gate["actual"]["semantic_template_family_report"]["diversity_sufficient"] is True
    assert gate["actual"]["semantic_template_family_report"]["family_size_below_limit"] is True
    assert gate["actual"]["visible_artifacts"]["leaking_unit_count"] == 0
    assert gate["actual"]["tool_label_completeness"]["required_tools_labeled_count"] == 130
    assert gate["actual"]["tool_label_completeness"]["forbidden_tools_labeled_count"] == 130
    assert gate["offline_feasibility"]["schema_version"] == (
        DAY7_TEST_DRAFT_FEASIBILITY_SCHEMA_VERSION
    )
    assert gate["offline_feasibility"]["status"] == "passed"
    assert gate["offline_feasibility"]["checked_tourism_unit_count"] == 110


def test_day7_test_draft_review_fix_gold_policies_are_encoded() -> None:
    document = build_ctp120_test_draft_document()
    cases = {case["case_id"]: case for case in document["cases"]}

    attraction_case = cases["ctp_test_024_shenzhen_attractions"]
    attraction_expected = attraction_case["expected"]
    attraction_slots = parse_visible_request_slots(attraction_case["user_input"])
    assert "people_count" not in attraction_slots
    assert attraction_expected["hard_constraints"] == {
        "destination": "shenzhen",
        "min_attractions": 3,
        "max_attractions": 3,
        "preferences": ["family"],
    }

    for case_id in (
        "ctp_test_051_beijing_partial_replan",
        "ctp_test_055_guilin_partial_replan",
        "ctp_test_059_shenzhen_partial_replan",
        "ctp_test_063_xian_partial_replan",
        "ctp_test_067_hangzhou_partial_replan",
    ):
        expected = cases[case_id]["turns"][1]["expected"]
        assert expected["accepted_agent_sets"] == [
            ["weather", "itinerary", "budget"],
            ["attraction", "weather", "itinerary", "budget"],
        ]
        assert expected["accepted_tool_sets"] == [
            ["weather_query", "budget_calculator"],
            ["poi_search", "weather_query", "budget_calculator"],
        ]
        assert expected["forbidden_tools"] == []

    for index in range(71, 81):
        case_id = next(case_id for case_id in cases if case_id.startswith(f"ctp_test_{index:03d}_"))
        expected = cases[case_id]["turns"][1]["expected"]
        assert set(expected["required_tools"]) == {"weather_query", "poi_search"}
        assert expected["accepted_agent_sets"] == [
            ["weather", "attraction", "itinerary"],
            ["weather", "attraction", "itinerary", "budget"],
        ]
        assert expected["accepted_tool_sets"] == [
            ["weather_query", "poi_search"],
            ["weather_query", "poi_search", "budget_calculator"],
        ]
        assert expected["forbidden_tools"] == []


def test_committed_day7_test_draft_files_are_current_and_pass_gate() -> None:
    benchmark_path = ROOT / "experiments" / "benchmark.json"
    benchmark_document, benchmark_cases = load_benchmark_document(benchmark_path)
    document, cases = load_benchmark_document(ROOT / "experiments" / "ctp120_test_draft.json")
    comparison_splits = _comparison_splits()
    quality = build_benchmark_dataset_quality_report(
        document=document,
        cases=cases,
        expected_case_count=100,
        strict_formal=True,
        comparison_splits=comparison_splits,
    )
    gate = build_day7_test_draft_gate(
        document=document,
        cases=cases,
        comparison_splits=comparison_splits,
        quality_report=quality,
    )
    persisted_quota = json.loads(
        (ROOT / "experiments" / "ctp120_test_draft_quota_report.json").read_text(
            encoding="utf-8"
        )
    )
    persisted_feasibility = json.loads(
        (
            ROOT / "experiments" / "ctp120_test_draft_feasibility_report.json"
        ).read_text(encoding="utf-8")
    )

    assert benchmark_document["case_files"] == ["ctp100_formal_v2.json"]
    assert benchmark_document["comparison_files"] == [
        "ctp120_dev.json",
        "benchmark_test.json",
        "day8_dev_experiment_cases_v1_3.json",
    ]
    assert len(benchmark_cases) == 100
    assert gate["status"] == "passed", gate["failed_checks"]
    assert persisted_quota["status"] == "passed"
    assert persisted_quota["dataset_sha256"] == gate["dataset_sha256"]
    assert persisted_quota["actual"]["duplicate_counts"]["semantic_template_duplicate_count"] == 0
    assert persisted_quota["actual"]["duplicate_counts"]["tourism_template_family_count"] == 58
    assert persisted_quota["actual"]["duplicate_counts"]["max_tourism_template_family_size"] == 6
    assert persisted_quota["actual"]["visible_artifacts"]["leaking_unit_count"] == 0
    assert persisted_quota["actual"]["tool_label_completeness"]["unit_count"] == 130
    assert persisted_quota["actual"]["tool_label_completeness"]["missing_required_tools_count"] == 0
    assert persisted_quota["actual"]["tool_label_completeness"]["missing_forbidden_tools_count"] == 0
    assert persisted_feasibility["status"] == "passed"
    assert persisted_feasibility["failed_tourism_unit_count"] == 0


def test_day7_test_draft_visible_inputs_do_not_leak_experiment_design() -> None:
    document = build_ctp120_test_draft_document()
    forbidden_terms = (
        "样本编号",
        "补充背景",
        "实验标注",
        "固定离线资料",
        "工具调用",
        "多 Agent",
        "多Agent",
        "多角色旅游系统",
        "系统架构",
    )
    units = []
    for case in document["cases"]:
        turns = case.get("turns")
        units.extend(turns if isinstance(turns, list) else [case])

    assert len(units) == 130
    for unit in units:
        text = unit["user_input"]
        assert not any(term in text for term in forbidden_terms), text
        expected = unit["expected"]
        assert "required_tools" in expected
        assert "forbidden_tools" in expected


def test_day7_test_draft_gate_blocks_visible_artifact_terms() -> None:
    document = build_ctp120_test_draft_document()
    broken_cases = json.loads(json.dumps(document["cases"], ensure_ascii=False))
    broken_cases[0]["user_input"] += " 样本编号999，用于实验标注。"
    gate = build_day7_test_draft_gate(
        document={**document, "cases": broken_cases},
        cases=broken_cases,
        comparison_splits=_comparison_splits(),
    )

    assert gate["status"] == "failed"
    assert "no_visible_experiment_artifacts" in gate["failed_checks"]


def test_day7_test_draft_gate_blocks_semantic_template_duplicates() -> None:
    document = build_ctp120_test_draft_document()
    broken_cases = json.loads(json.dumps(document["cases"], ensure_ascii=False))
    broken_cases[1]["user_input"] = broken_cases[0]["user_input"]
    gate = build_day7_test_draft_gate(
        document={**document, "cases": broken_cases},
        cases=broken_cases,
        comparison_splits=_comparison_splits(),
    )

    assert gate["status"] == "failed"
    assert "no_semantic_template_duplicate_inputs" in gate["failed_checks"]


def test_day7_test_draft_gate_blocks_missing_case_quota() -> None:
    document = build_ctp120_test_draft_document()
    broken_cases = list(document["cases"][:-1])
    quality = build_benchmark_dataset_quality_report(
        document={**document, "cases": broken_cases},
        cases=broken_cases,
        expected_case_count=100,
        strict_formal=True,
        comparison_splits=_comparison_splits(),
    )
    gate = build_day7_test_draft_gate(
        document={**document, "cases": broken_cases},
        cases=broken_cases,
        comparison_splits=_comparison_splits(),
        quality_report=quality,
    )

    assert gate["status"] == "failed"
    assert "case_count_matches" in gate["failed_checks"]
    assert "case_task_quotas_match" in gate["failed_checks"]


def test_benchmark_manifest_preflight_accepts_100_case_test_draft(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _formal_env(monkeypatch)
    report = build_formal_preflight_report(
        benchmark_path=ROOT / "experiments" / "benchmark.json",
        output_dir=tmp_path / "runs",
        run_id="day7-test-draft-preflight",
        expected_case_count=100,
        require_llm_config=False,
        strict_formal=True,
        require_day8_delivery_pack=False,
        require_clean_git=False,
    )

    assert report["status"] == "passed", report["errors"]
    assert report["benchmark"]["case_count"] == 100
    assert report["benchmark"]["scenario_case_count"] == 30
    assert report["benchmark"]["total_turn_count"] == 130
    assert report["run"]["expected_raw_run_count"] == 520
    assert report["benchmark_quality"]["status"] == "passed"


def _comparison_splits() -> dict[str, list[dict[str, object]]]:
    splits: dict[str, list[dict[str, object]]] = {}
    for filename in ("ctp120_dev.json", "benchmark_test.json"):
        document, cases = load_benchmark_document(ROOT / "experiments" / filename)
        split_name = str(document.get("split") or document.get("dataset_id") or filename)
        splits[split_name] = cases
    return splits


def _formal_env(monkeypatch) -> None:
    monkeypatch.setenv("EXPERIMENT_STRICT_MODE", "true")
    monkeypatch.setenv("EXPERIMENT_DISABLE_CACHE", "true")
    monkeypatch.setenv("TRACE_SAVE_USER_MESSAGE", "false")
    monkeypatch.setenv("LLM_MODEL", "gpt-5-mini")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.vectorengine.ai/v1")
    monkeypatch.setenv("LLM_TEMPERATURE", "0")
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
    monkeypatch.setenv("LLM_TIMEOUT", "60")
    monkeypatch.setenv("LLM_RETRY_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("EXPERIMENT_RESULT_HARD_TIMEOUT_SECONDS", "900")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "minimal")
    monkeypatch.setenv("EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER", "true")
