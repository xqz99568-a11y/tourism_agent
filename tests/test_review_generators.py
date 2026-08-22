import csv
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.generate_ctp100_budget_gold_review_v2 import generate_budget_review
from experiments.generate_ctp100_budget_gold_v2 import generate_budget_gold
from experiments.generate_food_reference_policy_review_v1 import generate_food_reference_policy_review
from experiments.audit_ctp100_formal_v2 import generate_ctp100_formal_v2_audit
from app.core.budget_gold import (
    BUDGET_GOLD_REVIEW_STATUS,
    BUDGET_GOLD_SCHEMA_VERSION,
    BUDGET_GOLD_STATUS,
    DEFAULT_CTP100_BUDGET_GOLD_PATH,
)
from app.core.budget_manual_review import (
    ECONOMY_BUDGET_CONFIRMED_SCOPE,
    ECONOMY_BUDGET_EXCLUDED_SCOPE,
    ECONOMY_BUDGET_FORMAL_MAIN_TIERS,
    validate_economy_budget_manual_review,
)
from app.core.academic_experiment_design import MAIN_DATASET_VERSION
from app.core.fixed_data import canonical_json_sha256


def test_food_reference_policy_review_generates_five_city_three_tier_materials(tmp_path: Path) -> None:
    md_path = tmp_path / "food.md"
    csv_path = tmp_path / "food.csv"

    rows = generate_food_reference_policy_review(output_md=md_path, output_csv=csv_path)

    assert len(rows) == 15
    assert md_path.exists()
    assert csv_path.exists()
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert len(csv_rows) == 15
    assert {"economy", "comfort", "premium"} <= {row["tier"] for row in csv_rows}
    assert "suggested_breakfast_cost" in csv_rows[0]
    assert "current_per_person_day_cost" not in csv_rows[0]
    assert "suggested_per_person_day_cost" not in csv_rows[0]
    assert "example_2d1n_average_per_person_day_cost" in csv_rows[0]
    assert "full_three_meal_day_reference_cost" in csv_rows[0]
    assert "current_2_people_2_days_1_night_cost" in csv_rows[0]
    assert "suggested_2_people_2_days_1_night_cost" in csv_rows[0]
    economy_rows = [row for row in csv_rows if row["tier"] == "economy"]
    non_formal_rows = [row for row in csv_rows if row["tier"] in {"comfort", "premium"}]
    assert len(economy_rows) == 5
    assert len(non_formal_rows) == 10
    assert {row["anomaly_note"] for row in economy_rows} == {"已人工确认：进入正式主实验经济型预算基线"}
    assert {row["anomaly_note"] for row in non_formal_rows} == {
        "不进入正式主实验确认范围：仅作开发检查或后续扩展参考"
    }
    hangzhou_economy = next(
        row for row in csv_rows if row["city_id"] == "hangzhou" and row["tier"] == "economy"
    )
    hangzhou_comfort = next(
        row for row in csv_rows if row["city_id"] == "hangzhou" and row["tier"] == "comfort"
    )
    assert float(hangzhou_economy["current_2_people_2_days_1_night_cost"]) == 450.0
    assert float(hangzhou_economy["suggested_2_people_2_days_1_night_cost"]) == 450.0
    assert float(hangzhou_economy["same_scenario_difference"]) == 0.0
    assert float(hangzhou_comfort["current_2_people_2_days_1_night_cost"]) == 1170.0
    assert float(hangzhou_comfort["suggested_2_people_2_days_1_night_cost"]) == 1200.0
    assert float(hangzhou_comfort["same_scenario_difference"]) == 30.0
    md_text = md_path.read_text(encoding="utf-8")
    assert "同口径比较表" in md_text
    assert "完整三餐日费用，不能与“两天一晚示例的人均日均餐饮费”直接比较" in md_text
    assert "economy 餐饮参考值已在 `economy_budget_manual_review_v1.json` 中确认" in md_text
    assert "comfort/premium 不属于本次正式主实验预算金标确认范围" in md_text


def test_budget_gold_review_passes_after_formal_dataset_slot_fixes(tmp_path: Path) -> None:
    dataset_path = ROOT / "experiments" / "ctp100_formal_v2.json"
    before = dataset_path.read_text(encoding="utf-8")
    gold_path = tmp_path / "budget_gold.json"
    md_path = tmp_path / "review.md"
    csv_path = tmp_path / "review.csv"

    generate_budget_gold(dataset_path=dataset_path, output_path=gold_path, write=True)
    summary = generate_budget_review(
        dataset_path=dataset_path,
        gold_path=gold_path,
        output_md=md_path,
        output_csv=csv_path,
    )

    assert dataset_path.read_text(encoding="utf-8") == before
    assert summary["budget_review_rows"] == 90
    assert summary["issue_counts"] == {}
    written = json.loads(gold_path.read_text(encoding="utf-8"))
    manual_review = written["manual_review"]
    assert manual_review["status"] == BUDGET_GOLD_REVIEW_STATUS
    assert manual_review["status_source"] == "validated_economy_manual_review_ledger"
    assert manual_review["confirmed_scope"] == list(ECONOMY_BUDGET_CONFIRMED_SCOPE)
    assert manual_review["excluded_scope"] == list(ECONOMY_BUDGET_EXCLUDED_SCOPE)
    assert manual_review["formal_main_experiment_tiers"] == list(ECONOMY_BUDGET_FORMAL_MAIN_TIERS)
    assert "comfort" not in manual_review["confirmed_scope"]
    assert "premium" not in manual_review["confirmed_scope"]
    people_change = next(record for record in written["records"] if record["unit_id"] == "ctp100_v2_057::t2")
    assert people_change["input_slots"]["people_count"] == 3
    assert "source_slot_repairs" not in people_change
    local_only = next(record for record in written["records"] if record["unit_id"] == "ctp100_v2_049")
    assert local_only["budget_policy_v2"]["requested_budget_scope"] == "destination_local_only"
    assert local_only["budget_policy_v2"]["sufficiency_status"] == "sufficient"
    assert local_only["budget_policy_v2"]["mandatory_budget_disclaimer"] is True
    assert md_path.exists()
    assert csv_path.exists()
    md_text = md_path.read_text(encoding="utf-8")
    assert "本行程人均日均餐饮费" in md_text
    assert "餐饮人均日" not in md_text
    assert "餐饮总额 ÷ people_count ÷ duration_days" in md_text
    assert "预算金标草稿" not in md_text
    assert "不是正式题库" not in md_text


def test_economy_budget_manual_review_validates_five_city_formal_scope() -> None:
    review = validate_economy_budget_manual_review()

    assert review["valid"] is True
    assert review["review_status"] == "confirmed"
    assert review["confirmed_scope"] == list(ECONOMY_BUDGET_CONFIRMED_SCOPE)
    assert review["excluded_scope"] == list(ECONOMY_BUDGET_EXCLUDED_SCOPE)
    assert review["formal_main_experiment_tiers"] == list(ECONOMY_BUDGET_FORMAL_MAIN_TIERS)
    assert review["summary"]["city_ids"] == ["beijing", "hangzhou", "xian", "shenzhen", "guilin"]
    by_city = {row["city_id"]: row for row in review["city_reviews"]}
    assert by_city["beijing"]["accommodation"]["reference_price_cny"] == 330.0
    assert by_city["beijing"]["food"]["reference_price_cny"] == 55.0
    assert by_city["guilin"]["accommodation"]["reference_price_cny"] == 180.0
    assert by_city["guilin"]["food"]["reference_price_cny"] == 30.0


def test_ctp100_formal_v2_audit_records_dataset_hash_and_no_repairs(tmp_path: Path) -> None:
    dataset_path = ROOT / "experiments" / "ctp100_formal_v2.json"
    gold_path = tmp_path / "budget_gold.json"
    audit_json = tmp_path / "audit.json"
    audit_md = tmp_path / "audit.md"

    generate_budget_gold(dataset_path=dataset_path, output_path=gold_path, write=True)
    audit = generate_ctp100_formal_v2_audit(
        dataset_path=dataset_path,
        budget_gold_path=gold_path,
        output_json=audit_json,
        output_md=audit_md,
    )

    assert audit["status"] == "passed", audit["issue_counts"]
    assert audit["dataset_version"] == MAIN_DATASET_VERSION
    assert (
        audit["budget_gold_audit"]["source_dataset_sha256"]
        == audit["dataset_sha256"]
    )
    assert audit["budget_gold_audit"]["source_dataset_sha256_matches"] is True
    assert audit["budget_gold_audit"]["source_slot_repair_count"] == 0
    assert any(
        check["check_id"] == "day8_explicit_date_trip_planning_requires_weather"
        and check["status"] == "passed"
        for check in audit["targeted_checks"]
    )
    assert audit_json.exists()
    assert audit_md.exists()


def test_day8_budget_policy_dev_cases_cover_required_tier_scenarios() -> None:
    path = ROOT / "experiments" / "day8_budget_policy_dev_cases_v2.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    cases = document["cases"]

    assert len(cases) >= 6
    case_ids = {case["case_id"] for case in cases}
    assert "day8_budget_v2_001_comfort_hotel_economy_food" in case_ids
    assert "day8_budget_v2_002_economy_hotel_comfort_food" in case_ids
    assert "day8_budget_v2_003_explicit_premium" in case_ids
    assert "day8_budget_v2_004_insufficient_keep_explicit_tier" in case_ids
    assert "day8_budget_v2_005_comfortable_pace_not_spending_upgrade" in case_ids
    assert "day8_budget_v2_006_optional_upgrade_not_main_plan" in case_ids
    optional = next(case for case in cases if case["case_id"].endswith("optional_upgrade_not_main_plan"))
    assert optional["expected"]["hotel_tier"] == "economy"
    assert optional["expected"]["food_tier"] == "economy"


def test_day8_generated_budget_artifacts_match_current_formal_dataset() -> None:
    dataset_path = ROOT / "experiments" / "ctp100_formal_v2.json"
    gold_path = DEFAULT_CTP100_BUDGET_GOLD_PATH
    review_csv_path = ROOT / "experiments" / "generated" / "ctp100_budget_gold_v2_review.csv"
    audit_path = ROOT / "experiments" / "generated" / "ctp100_formal_v2_dataset_audit.json"

    dataset = json.loads(dataset_path.read_text(encoding="utf-8-sig"))
    gold = json.loads(gold_path.read_text(encoding="utf-8-sig"))
    audit = json.loads(audit_path.read_text(encoding="utf-8-sig"))
    dataset_sha256 = canonical_json_sha256(dataset)

    assert gold["source_dataset_sha256"] == dataset_sha256
    assert gold["schema_version"] == BUDGET_GOLD_SCHEMA_VERSION
    assert gold["gold_status"] == BUDGET_GOLD_STATUS
    assert gold["review_status"] == BUDGET_GOLD_REVIEW_STATUS
    assert gold["manual_review"]["confirmed_scope"] == list(ECONOMY_BUDGET_CONFIRMED_SCOPE)
    assert gold["manual_review"]["excluded_scope"] == list(ECONOMY_BUDGET_EXCLUDED_SCOPE)
    assert gold["manual_review"]["formal_main_experiment_tiers"] == list(ECONOMY_BUDGET_FORMAL_MAIN_TIERS)
    assert "comfort" not in gold["manual_review"]["confirmed_scope"]
    assert "premium" not in gold["manual_review"]["confirmed_scope"]
    assert gold["dataset_version"] == dataset["dataset_version"]
    assert gold["summary"]["evaluation_unit_count"] == 130
    assert gold["summary"]["budget_gold_count"] == 90
    assert gold["summary"]["skipped_by_reason"] == {"budget_not_required": 40}

    assert audit["dataset_sha256"] == dataset_sha256
    assert audit["status"] == "passed"
    assert audit["issue_counts"] == {}
    assert audit["budget_gold_audit"]["source_dataset_sha256_matches"] is True
    assert audit["budget_gold_audit"]["source_slot_repair_count"] == 0

    with review_csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 90
    assert {row["issue_flags"] for row in rows} == {"[]"}
