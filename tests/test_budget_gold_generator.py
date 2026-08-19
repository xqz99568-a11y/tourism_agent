import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.budget_gold import (
    BUDGET_GOLD_REVIEW_STATUS,
    BUDGET_GOLD_SCHEMA_VERSION,
    BUDGET_GOLD_STATUS,
)
from app.core.budget_manual_review import (
    ECONOMY_BUDGET_CONFIRMED_SCOPE,
    ECONOMY_BUDGET_EXCLUDED_SCOPE,
    ECONOMY_BUDGET_FORMAL_MAIN_TIERS,
    EconomyBudgetManualReviewError,
)
from experiments.generate_ctp100_budget_gold_v2 import generate_budget_gold


def test_generate_ctp100_budget_gold_v2_formal_without_mutating_dataset(tmp_path: Path) -> None:
    dataset_path = ROOT / "experiments" / "ctp100_formal_v2.json"
    before = dataset_path.read_text(encoding="utf-8")
    output_path = tmp_path / "budget_gold.json"

    result = generate_budget_gold(
        dataset_path=dataset_path,
        output_path=output_path,
        write=True,
    )

    assert dataset_path.read_text(encoding="utf-8") == before
    assert output_path.exists()
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["summary"] == result["summary"]
    assert result["schema_version"] == BUDGET_GOLD_SCHEMA_VERSION
    assert result["gold_status"] == BUDGET_GOLD_STATUS
    assert result["review_status"] == BUDGET_GOLD_REVIEW_STATUS
    assert result["manual_review"]["status_source"] == "validated_economy_manual_review_ledger"
    assert result["manual_review"]["confirmed_scope"] == list(ECONOMY_BUDGET_CONFIRMED_SCOPE)
    assert result["manual_review"]["excluded_scope"] == list(ECONOMY_BUDGET_EXCLUDED_SCOPE)
    assert result["manual_review"]["formal_main_experiment_tiers"] == list(ECONOMY_BUDGET_FORMAL_MAIN_TIERS)
    assert "comfort" not in result["manual_review"]["confirmed_scope"]
    assert "premium" not in result["manual_review"]["confirmed_scope"]
    assert result["artifact_hashes"]["source_dataset"]["sha256"] == result["source_dataset_sha256"]
    assert result["artifact_hashes"]["fixed_tourism_data"]["combined_sha256"]
    assert result["artifact_hashes"]["intercity_transport_snapshot"]["route_count"] == 50
    assert result["budget_policy_version"] == "budget_policy_v2_0"
    assert result["summary"]["evaluation_unit_count"] == 130
    assert result["summary"]["budget_gold_count"] == 90
    assert result["summary"]["skipped_by_reason"] == {"budget_not_required": 40}

    first = next(record for record in result["records"] if record["unit_id"] == "ctp100_v2_001")
    assert first["status"] == "generated"
    assert first["budget_policy_v2"]["nights"] == 2
    assert first["budget_policy_v2"]["rooms"] == 1
    assert first["budget_policy_v2"]["budget_scope"] == "destination_local_only"
    assert first["budget_policy_v2"]["requested_budget_scope"] == "local_plus_round_trip_intercity"
    assert first["budget_policy_v2"]["scope_complete"] is False
    assert first["budget_policy_v2"]["sufficiency_status"] == "indeterminate"
    assert first["budget_policy_v2"]["mandatory_budget_disclaimer"] is True

    shanghai_hangzhou = next(
        record for record in result["records"] if record["unit_id"] == "ctp100_v2_002"
    )
    assert shanghai_hangzhou["budget_policy_v2"]["intercity_transport_included"] is True
    assert shanghai_hangzhou["budget_policy_v2"]["intercity_round_trip_cost_cny"] == 332.0
    assert shanghai_hangzhou["budget_policy_v2"]["hotel_tier"] == "economy"
    assert shanghai_hangzhou["budget_policy_v2"]["food_tier"] == "economy"
    assert shanghai_hangzhou["budget_policy_v2"]["upgrade_applied"] == []
    assert shanghai_hangzhou["budget_policy_v2"]["scope_complete"] is True
    assert shanghai_hangzhou["budget_policy_v2"]["sufficiency_status"] == "sufficient"

    wuhan_beijing = next(
        record for record in result["records"] if record["unit_id"] == "ctp100_v2_016"
    )
    assert wuhan_beijing["input_slots"]["origin"] == "wuhan"
    assert wuhan_beijing["budget_policy_v2"]["intercity_transport_included"] is True
    assert wuhan_beijing["budget_policy_v2"]["intercity_round_trip_cost_cny"] == 3738.0

    people_change = next(
        record for record in result["records"] if record["unit_id"] == "ctp100_v2_057::t2"
    )
    assert people_change["input_slots"]["people_count"] == 3
    assert people_change["budget_policy_v2"]["people_count"] == 3
    assert "source_slot_repairs" not in people_change


def test_generate_ctp100_budget_gold_requires_manual_review_for_confirmed_output(tmp_path: Path) -> None:
    dataset_path = ROOT / "experiments" / "ctp100_formal_v2.json"

    try:
        generate_budget_gold(
            dataset_path=dataset_path,
            output_path=tmp_path / "budget_gold.json",
            write=True,
            manual_review_path=tmp_path / "missing_manual_review.json",
        )
    except EconomyBudgetManualReviewError as exc:
        assert "manual review not found" in str(exc)
    else:  # pragma: no cover - defensive failure message
        raise AssertionError("confirmed budget gold generation must require a valid manual review ledger")


def test_generate_ctp100_budget_gold_candidate_keeps_review_pending(tmp_path: Path) -> None:
    dataset_path = ROOT / "experiments" / "ctp100_formal_v2.json"

    result = generate_budget_gold(
        dataset_path=dataset_path,
        output_path=tmp_path / "budget_gold_candidate.json",
        write=True,
        manual_review_path=tmp_path / "missing_manual_review.json",
        confirm_reviewed=False,
    )

    assert result["schema_version"] == "ctp100-budget-gold-v2-candidate-v1"
    assert result["gold_status"] == "candidate_generated"
    assert result["review_status"] == "pending_human_confirmation"
    assert result["manual_review"]["status_source"] == "candidate_generation_without_formal_review_confirmation"
    assert result["manual_review"]["confirmed_scope"] == []
