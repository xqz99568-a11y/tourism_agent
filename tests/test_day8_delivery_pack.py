import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.day8_delivery_pack import (  # noqa: E402
    DAY8_DELIVERY_PACK_SCHEMA_VERSION,
    build_day8_delivery_pack,
    write_day8_delivery_pack,
)
from app.core.budget_gold import (
    BUDGET_GOLD_REVIEW_STATUS,
    BUDGET_GOLD_SCHEMA_VERSION,
    BUDGET_GOLD_STATUS,
    DEFAULT_CTP100_BUDGET_GOLD_PATH,
)  # noqa: E402
from app.core.budget_manual_review import (
    ECONOMY_BUDGET_CONFIRMED_SCOPE,
    ECONOMY_BUDGET_EXCLUDED_SCOPE,
    ECONOMY_BUDGET_FORMAL_MAIN_TIERS,
)  # noqa: E402
from app.core.academic_experiment_design import (  # noqa: E402
    EXPECTED_SEALED_CASE_COUNT,
    EXPECTED_SEALED_TURN_COUNT,
    MAIN_BENCHMARK_ROLE,
    SEALED_VALIDATION_METHODS,
    SEALED_VALIDATION_ROLE,
)
from app.core.fixed_data import canonical_json_sha256  # noqa: E402
from app.core.formal_artifact_integrity import build_formal_artifact_integrity_report  # noqa: E402


def test_day8_delivery_pack_is_ready_for_current_formal_inputs(tmp_path: Path) -> None:
    pack = build_day8_delivery_pack(
        run_id="day8_delivery_unit",
        preflight_output_dir=tmp_path / "preflight",
        require_clean_git=False,
    )

    assert pack["schema_version"] == DAY8_DELIVERY_PACK_SCHEMA_VERSION
    assert pack["readiness"]["status"] == "day8_delivery_ready"
    assert pack["readiness"]["ready_for_formal_experiment"] is True
    assert pack["readiness"]["failed_checks"] == []
    assert all(pack["readiness"]["checks"].values())
    assert pack["formal_input"]["case_count"] == 100
    assert pack["formal_input"]["turn_count"] == 130
    assert pack["formal_input"]["expected_raw_run_count"] == 520

    qweather = pack["frozen_snapshots"]["qweather"]
    assert qweather["snapshot_id"] == "ctp_qweather_20260807_v1"
    assert qweather["forecast_horizon_days"] == 30
    assert qweather["runtime_online_refresh_allowed"] is False

    intercity = pack["frozen_snapshots"]["intercity_transport"]
    assert intercity["route_count"] == 50
    assert intercity["runtime_online_refresh_allowed"] is False
    assert intercity["real_time_price_claim_allowed"] is False

    budget_gold = pack["budget_gold"]
    assert budget_gold["schema_version"] == BUDGET_GOLD_SCHEMA_VERSION
    assert budget_gold["gold_status"] == BUDGET_GOLD_STATUS
    assert budget_gold["review_status"] == BUDGET_GOLD_REVIEW_STATUS
    assert budget_gold["manual_review"]["confirmed_scope"] == list(ECONOMY_BUDGET_CONFIRMED_SCOPE)
    assert budget_gold["manual_review"]["excluded_scope"] == list(ECONOMY_BUDGET_EXCLUDED_SCOPE)
    assert budget_gold["manual_review"]["formal_main_experiment_tiers"] == list(ECONOMY_BUDGET_FORMAL_MAIN_TIERS)
    assert budget_gold["economy_manual_review"]["valid"] is True
    assert budget_gold["economy_manual_review"]["summary"]["city_count"] == 5
    assert "comfort" not in budget_gold["manual_review"]["confirmed_scope"]
    assert "premium" not in budget_gold["manual_review"]["confirmed_scope"]
    assert budget_gold["budget_policy_version"] == "budget_policy_v2_0"
    assert budget_gold["summary"]["budget_gold_count"] == 90
    assert budget_gold["review"]["issue_row_count"] == 0
    assert pack["dataset_audit"]["status"] == "passed"
    academic = pack["academic_experiment_design"]
    assert academic["status"] == "passed"
    assert academic["main_benchmark"]["dataset_role"] == MAIN_BENCHMARK_ROLE
    assert academic["sealed_validation"]["dataset_role"] == SEALED_VALIDATION_ROLE
    assert academic["sealed_validation"]["case_count"] == EXPECTED_SEALED_CASE_COUNT
    assert academic["sealed_validation"]["turn_count"] == EXPECTED_SEALED_TURN_COUNT
    assert tuple(academic["sealed_validation"]["methods"]) == SEALED_VALIDATION_METHODS
    assert academic["checks"]["sealed_dataset_not_in_main_benchmark"] is True
    assert pack["formal_preflight"]["status"] == "passed"
    integrity = pack["formal_artifact_integrity"]
    assert integrity["schema_version"] == "ctp-formal-artifact-integrity-v1"
    assert integrity["artifacts"]["evaluation_rule_catalog"]["sha256"]
    assert integrity["artifacts"]["independent_evaluator_code"]["sha256"]
    assert pack["readiness"]["checks"]["evaluation_rule_catalog_declares_day8_formal"] is True


def test_write_day8_delivery_pack_writes_json_and_markdown(tmp_path: Path) -> None:
    payload = write_day8_delivery_pack(
        output_dir=tmp_path,
        run_id="day8_delivery_write_unit",
        preflight_output_dir=tmp_path / "preflight",
        require_clean_git=False,
    )

    assert payload["status"] == "completed"
    assert payload["delivery_status"] == "day8_delivery_ready"
    json_path = Path(payload["json"])
    markdown_path = Path(payload["markdown"])
    assert json_path.exists()
    assert markdown_path.exists()

    written = json.loads(json_path.read_text(encoding="utf-8-sig"))
    assert written["readiness"]["ready_for_formal_experiment"] is True
    assert "正式实验输入冻结交付报告" in markdown_path.read_text(encoding="utf-8")


def test_day8_delivery_pack_blocks_dirty_git_when_required(monkeypatch, tmp_path: Path) -> None:
    dirty_report = build_formal_artifact_integrity_report()
    dirty_report["git"]["worktree_clean"] = False
    dirty_report["git"]["status_short"] = [" M app/core/example.py"]

    monkeypatch.setattr(
        "app.core.day8_delivery_pack.build_formal_artifact_integrity_report",
        lambda: dirty_report,
    )

    pack = build_day8_delivery_pack(
        run_id="day8_delivery_dirty_git_unit",
        preflight_output_dir=tmp_path / "preflight",
        require_clean_git=True,
    )

    assert pack["readiness"]["status"] == "day8_delivery_blocked"
    assert "git_worktree_clean" in pack["readiness"]["failed_checks"]
    assert pack["formal_artifact_integrity"]["git"]["worktree_clean"] is False


def test_day8_delivery_pack_blocks_stale_budget_gold(tmp_path: Path) -> None:
    stale_gold = tmp_path / "stale_budget_gold.json"
    source_gold = DEFAULT_CTP100_BUDGET_GOLD_PATH
    gold = json.loads(source_gold.read_text(encoding="utf-8-sig"))
    gold["source_dataset_sha256"] = "0" * 64
    stale_gold.write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8")

    pack = build_day8_delivery_pack(
        run_id="day8_delivery_stale_gold_unit",
        budget_gold_path=stale_gold,
        preflight_output_dir=tmp_path / "preflight",
        require_clean_git=False,
    )

    dataset = json.loads(
        (ROOT / "experiments" / "ctp100_formal_v2.json").read_text(encoding="utf-8-sig")
    )
    assert canonical_json_sha256(dataset) != gold["source_dataset_sha256"]
    assert pack["readiness"]["status"] == "day8_delivery_blocked"
    assert "budget_gold_matches_current_dataset" in pack["readiness"]["failed_checks"]
    assert pack["readiness"]["ready_for_formal_experiment"] is False


def test_day8_delivery_pack_blocks_comfort_premium_confirmed_scope(tmp_path: Path) -> None:
    bad_gold = tmp_path / "bad_scope_budget_gold.json"
    source_gold = DEFAULT_CTP100_BUDGET_GOLD_PATH
    gold = json.loads(source_gold.read_text(encoding="utf-8-sig"))
    gold["manual_review"]["confirmed_scope"] = [
        "economy",
        "comfort",
        "premium",
        "intercity_transport",
        "budget_policy_v2",
    ]
    bad_gold.write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8")

    pack = build_day8_delivery_pack(
        run_id="day8_delivery_bad_budget_scope_unit",
        budget_gold_path=bad_gold,
        preflight_output_dir=tmp_path / "preflight",
        require_clean_git=False,
    )

    assert pack["readiness"]["status"] == "day8_delivery_blocked"
    assert "budget_gold_confirmed_scope_economy_only" in pack["readiness"]["failed_checks"]
    assert "budget_gold_excludes_comfort_premium_confirmation" in pack["readiness"]["failed_checks"]
