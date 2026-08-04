import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.day7_acceptance_review import (  # noqa: E402
    DAY7_ACCEPTANCE_REVIEW_SCHEMA_VERSION,
    DAY7_STAGE_DELIVERY_PACK_SCHEMA_VERSION,
    _acceptance_decision,
    _git_snapshot,
    _m3_ablation_evidence_from_fix,
    _slot_subset_matches,
    build_day7_acceptance_pack,
    write_day7_acceptance_pack,
)
import app.core.day7_acceptance_review as acceptance_review  # noqa: E402


EXPECTED_CURRENT_BLOCKERS = {
    "annotation_review_human_completed",
    "annotation_review_pending_count_zero",
    "git_freeze_tag_created",
    "git_freeze_tag_matches_head",
    "git_worktree_clean_at_acceptance",
}
FINAL_PILOT_RUN_DIR = (
    "experiments/results/day7_pilot/"
    "day7_pilot_gpt5mini_repair6_20260801T163500Z"
)
FINAL_DEV_RUN_DIR = (
    "experiments/results/day7_dev/"
    "day7_dev_gpt5mini_4096_final14_detanswer_20260803T1410CST"
)


def test_day7_annotation_parse_match_rejects_extra_core_slots() -> None:
    assert _slot_subset_matches(
        {"destination": "shenzhen", "preferences": ["family"]},
        {"destination": "shenzhen", "preferences": ["family"], "people_count": 3},
    ) is False
    assert _slot_subset_matches(
        {"destination": "shenzhen", "preferences": ["family"]},
        {"destination": "shenzhen", "preferences": ["family"], "traveler_group": "family"},
    ) is True


def test_day7_acceptance_pack_builds_first_round_review_from_current_evidence(
    monkeypatch,
) -> None:
    _patch_git_snapshot(monkeypatch, freeze_created=False, dirty=True)
    pack = build_day7_acceptance_pack(
        pilot_run_dir=FINAL_PILOT_RUN_DIR,
        dev_run_dir=FINAL_DEV_RUN_DIR,
        run_id="day7-acceptance-unit",
    )

    assert pack["schema_version"] == DAY7_ACCEPTANCE_REVIEW_SCHEMA_VERSION
    assert pack["acceptance"]["status"] == "blocked"
    assert pack["acceptance"]["ready_for_day8"] is False
    assert pack["acceptance"]["paper_claims_allowed"] is False
    assert set(pack["acceptance"]["failed_checks"]) >= EXPECTED_CURRENT_BLOCKERS
    assert pack["acceptance"]["human_review_completed"] is False
    assert pack["acceptance"]["manual_review_summary"]["pending_human_confirmation_count"] == 130
    assert pack["acceptance"]["manual_review_summary"]["machine_needs_attention_count"] == 0
    assert pack["acceptance"]["manual_review_summary"]["unresolved_machine_attention_count"] == 0
    assert pack["acceptance"]["manual_review_summary"]["rejected_or_needs_revision_count"] == 0
    assert pack["acceptance"]["final_acceptance_checks"]["annotation_review_human_completed"] is False
    assert pack["acceptance"]["final_acceptance_checks"]["machine_attention_rows_resolved"] is True
    assert pack["acceptance"]["final_acceptance_checks"]["git_freeze_tag_created"] is False
    assert pack["actual"]["case_count"] == 100
    assert pack["actual"]["turn_count"] == 130
    assert pack["actual"]["scenario_case_count"] == 30
    assert pack["annotation_review"]["row_count"] == 130
    assert pack["annotation_review"]["human_review_completed"] is False
    assert pack["case_review"]["row_count"] == 100
    assert pack["cross_dataset_leakage"]["status"] == "passed"
    assert pack["cross_dataset_leakage"]["counts"] == {
        "internal_duplicate_count": 0,
        "cross_split_duplicate_count": 0,
        "near_duplicate_count": 0,
    }
    assert pack["offline_feasibility"]["status"] == "passed"
    assert pack["offline_feasibility"]["checked_tourism_unit_count"] == 110
    assert pack["offline_feasibility"]["failed_tourism_unit_count"] == 0
    assert pack["benchmark_preflight"]["status"] == "passed"
    assert pack["benchmark_preflight"]["run"]["expected_raw_run_count"] == 520
    assert pack["day7_evidence"]["pilot_run"]["status"] == "passed"
    assert pack["day7_evidence"]["development_run"]["status"] == "passed"
    assert pack["day7_evidence"]["development_run"]["runtime_matches_day7_max_tokens_protocol"] is True
    assert pack["day7_evidence"]["development_run"]["completion_token_cap_hit_rate"] < 0.05
    assert pack["day7_evidence"]["development_run"]["empty_and_token_capped_call_count"] == 0
    assert pack["day7_evidence"]["cost_forecast"]["status"] == "passed"
    assert (
        pack["day7_evidence"]["cost_forecast"]["freeze_status"]
        == "frozen_for_cost_and_runtime"
    )
    assert pack["day7_evidence"]["cost_forecast"]["rerun_required"] is False
    assert pack["day7_evidence"]["fix_report"]["method_open_issue_count"] == 0
    assert pack["day7_evidence"]["fix_report"]["required_method_issue_statuses"] == {
        "METHOD-001": "fixed",
        "METHOD-002": "fixed",
        "METHOD-003": "fixed",
    }
    assert pack["day7_evidence"]["fix_report"]["required_method_issues_present"] is True
    assert pack["day7_evidence"]["fix_report"]["required_method_issues_fixed"] is True
    assert pack["day7_evidence"]["fix_report"]["m3_systemic_failure"] is False
    assert pack["day7_evidence"]["fix_report"]["m3_method_formal_run_blocked"] is False
    assert pack["day7_evidence"]["fix_report"]["agent_decision_ablation_required"] is False
    assert pack["day7_evidence"]["fix_report"]["m3_programmatic_decision_count"] == 37
    assert pack["day7_evidence"]["fix_report"]["m3_agent_decision_output_count"] == 64
    assert pack["day7_evidence"]["fix_report"]["formal_run_blocked"] is False
    assert pack["day7_evidence"]["m3_ablation"]["status"] == "passed"
    assert pack["day7_evidence"]["m3_ablation"]["hash_consistent"] is True
    assert (
        pack["acceptance"]["final_acceptance_checks"][
            "m3_ablation_artifact_hash_consistent"
        ]
        is True
    )
    source_keys = {item["key"] for item in pack["source_artifacts"]}
    assert {
        "m3_ablation_report_json",
        "m3_ablation_report_md",
        "m3_ablation_manifest",
        "m3_ablation_dev_gate",
    } <= source_keys
    assert pack["delivery_pack"]["schema_version"] == DAY7_STAGE_DELIVERY_PACK_SCHEMA_VERSION
    assert pack["delivery_pack"]["delivery_status"] == "blocked"
    assert pack["delivery_pack"]["prepared_for_manual_review"] is True
    assert pack["git_freeze_snapshot"]["freeze_object_created"] is False


def test_day7_acceptance_overlayed_human_review_clears_manual_blockers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _patch_git_snapshot(monkeypatch, freeze_created=False, dirty=True)
    prefill_pack = build_day7_acceptance_pack(
        pilot_run_dir=FINAL_PILOT_RUN_DIR,
        dev_run_dir=FINAL_DEV_RUN_DIR,
        run_id="day7-acceptance-prefill-unit",
    )
    rows = []
    for row in prefill_pack["annotation_review"]["rows"]:
        notes = ""
        if row["machine_review_status"] == "needs_attention":
            notes = "人工已核对金标、解析槽位和可行性，确认可进入后续实验。"
        rows.append(
            {
                "review_unit_id": row["review_unit_id"],
                "human_review_status": "approved",
                "human_reviewer": "reviewer-a",
                "human_decision": "accepted",
                "human_notes": notes or "人工抽查确认通过。",
            }
        )
    review_path = tmp_path / "completed_review.json"
    review_path.write_text(
        json.dumps({"rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    pack = build_day7_acceptance_pack(
        annotation_review_path=review_path,
        pilot_run_dir=FINAL_PILOT_RUN_DIR,
        dev_run_dir=FINAL_DEV_RUN_DIR,
        run_id="day7-acceptance-human-overlay-unit",
    )

    assert pack["annotation_review"]["source"]["mode"] == "manual_review_overlay"
    assert pack["acceptance"]["human_review_completed"] is True
    assert pack["acceptance"]["manual_review_summary"]["pending_human_confirmation_count"] == 0
    assert pack["acceptance"]["manual_review_summary"]["unresolved_machine_attention_count"] == 0
    assert (
        pack["acceptance"]["manual_review_summary"][
            "authenticity_verification_status"
        ]
        == "reviewer_attestation_required_for_line_by_line_claim"
    )
    assert (
        pack["acceptance"]["manual_review_summary"][
            "line_by_line_authenticity_machine_verifiable"
        ]
        is False
    )
    assert (
        pack["acceptance"]["manual_review_summary"][
            "same_manual_values_across_all_rows"
        ]
        is True
    )
    assert "annotation_review_human_completed" not in pack["acceptance"]["failed_checks"]
    assert "machine_attention_rows_resolved" not in pack["acceptance"]["failed_checks"]
    assert "git_freeze_tag_created" in pack["acceptance"]["failed_checks"]


def test_day7_acceptance_requires_notes_for_machine_attention_rows(tmp_path: Path) -> None:
    broken_dataset_path = _broken_test_draft_with_machine_attention(tmp_path)
    prefill_pack = build_day7_acceptance_pack(
        test_draft_path=broken_dataset_path,
        run_id="day7-acceptance-prefill-attention-unit",
    )
    assert prefill_pack["annotation_review"]["summary"]["machine_needs_attention_count"] >= 1
    rows = [
        {
            "review_unit_id": row["review_unit_id"],
            "human_review_status": "approved",
            "human_reviewer": "reviewer-a",
            "human_decision": "accepted",
            "human_notes": "",
        }
        for row in prefill_pack["annotation_review"]["rows"]
    ]
    review_path = tmp_path / "completed_review_without_attention_notes.json"
    review_path.write_text(
        json.dumps({"rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    pack = build_day7_acceptance_pack(
        test_draft_path=broken_dataset_path,
        annotation_review_path=review_path,
        run_id="day7-acceptance-attention-unit",
    )

    assert pack["acceptance"]["human_review_completed"] is False
    assert pack["acceptance"]["manual_review_summary"]["pending_human_confirmation_count"] == 0
    assert pack["acceptance"]["manual_review_summary"]["unresolved_machine_attention_count"] >= 1
    assert "machine_attention_rows_resolved" in pack["acceptance"]["failed_checks"]


def test_day7_acceptance_blocks_open_method_issue_report() -> None:
    pack = build_day7_acceptance_pack(
        pilot_run_dir=(
            "experiments/results/day7_pilot/"
            "day7_pilot_gpt5mini_smoke_20260731T142500Z"
        ),
        run_id="day7-acceptance-open-method-unit",
    )

    assert pack["day7_evidence"]["fix_report"]["method_open_issue_count"] == 2
    assert pack["day7_evidence"]["fix_report"]["m3_systemic_failure"] is True
    assert pack["day7_evidence"]["fix_report"]["formal_run_blocked"] is True
    assert "method_real_failures_closed" in pack["acceptance"]["failed_checks"]
    assert "m3_systemic_failure_closed" in pack["acceptance"]["failed_checks"]
    assert "formal_run_unblocked_by_issue_report" in pack["acceptance"]["failed_checks"]


def test_day7_acceptance_requires_all_required_method_issue_ids() -> None:
    decision = _acceptance_decision(
        quality_report={"status": "passed", "dataset": {"scenario_case_count": 30}},
        leakage_report={"status": "passed"},
        feasibility_report={"status": "passed"},
        benchmark_preflight={
            "status": "passed",
            "run": {"expected_raw_run_count": 520},
        },
        evidence={
            "quota_gate": {"status": "passed"},
            "benchmark_manifest": {"case_files": ["ctp120_test_draft.json"]},
            "pilot_run": {"status": "passed"},
            "development_run": {
                "status": "passed",
                "runtime_matches_day7_max_tokens_protocol": True,
                "completion_token_cap_hit_rate_below_limit": True,
                "empty_and_token_capped_call_count": 0,
            },
            "cost_forecast": {"status": "passed"},
            "fix_report": {
                "status": "completed",
                "method_open_issue_count": 0,
                "required_method_issue_statuses": {
                    "METHOD-001": "fixed",
                    "METHOD-002": None,
                    "METHOD-003": "fixed",
                },
                "required_method_issues_present": False,
                "required_method_issues_fixed": False,
                "m3_systemic_failure": False,
                "m3_method_formal_run_blocked": False,
                "m3_programmatic_decision_rate": 0.0,
                "agent_decision_ablation_required": False,
                "formal_run_blocked": False,
            },
            "m3_ablation": {"hash_consistent": True},
        },
        annotation_rows=[{}] * 130,
        annotation_summary={
            "human_review_completed": True,
            "pending_human_confirmation_count": 0,
            "unresolved_machine_attention_count": 0,
            "rejected_or_needs_revision_count": 0,
            "source_error_count": 0,
        },
        case_rows=[{}] * 100,
        git_snapshot={
            "freeze_object_created": True,
            "freeze_matches_head": True,
            "worktree_dirty": False,
        },
        expected_case_count=100,
        expected_turn_count=130,
        expected_scenario_case_count=30,
        required_method_count=4,
    )

    assert decision["status"] == "blocked"
    assert "method_real_failures_closed" not in decision["failed_checks"]
    assert "method_required_issue_ids_present" in decision["failed_checks"]
    assert "method_required_issue_ids_fixed" in decision["failed_checks"]


def test_m3_ablation_evidence_detects_stale_manifest_hash(tmp_path: Path) -> None:
    run_dir = tmp_path / "m3-ablation-stale"
    run_dir.mkdir()
    report_path = run_dir / "day7_m3_no_decision_normalizer_ablation.json"
    report_md_path = run_dir / "day7_m3_no_decision_normalizer_ablation.md"
    manifest_path = run_dir / "experiment_manifest.json"
    gate_path = run_dir / "day7_dev_gate.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": "stale-hash-unit",
                "m3_no_decision_normalizer_ablation": {
                    "json": report_path.as_posix(),
                    "markdown": report_md_path.as_posix(),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    stale_manifest_hash = hashlib.sha256(b"previous manifest bytes").hexdigest()
    gate_path.write_text(
        json.dumps(
            {
                "status": "passed",
                "artifact_index": {
                    "files": [
                        {
                            "key": "manifest",
                            "path": manifest_path.as_posix(),
                            "sha256": stale_manifest_hash,
                        }
                    ]
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps({"status": "passed"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report_md_path.write_text("# ablation\n", encoding="utf-8")

    evidence = _m3_ablation_evidence_from_fix(
        {
            "m3_no_decision_normalizer_ablation": {
                "available": True,
                "status": "passed",
                "run_dir": run_dir.as_posix(),
                "path": report_path.as_posix(),
            }
        }
    )

    assert evidence["status"] == "failed"
    assert evidence["hash_consistent"] is False
    assert "gate_manifest_sha256_matches_current_manifest" in evidence["failed_checks"]


def test_write_day7_acceptance_pack_exports_required_artifacts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _patch_git_snapshot(monkeypatch, freeze_created=False, dirty=True)
    output_dir = tmp_path / "day7_acceptance"
    docs_report = tmp_path / "Day7_acceptance_report.md"

    payload = write_day7_acceptance_pack(
        output_dir=output_dir,
        docs_report_path=docs_report,
        pilot_run_dir=FINAL_PILOT_RUN_DIR,
        dev_run_dir=FINAL_DEV_RUN_DIR,
        run_id="day7-acceptance-write-unit",
    )

    assert payload["acceptance_status"] == "blocked"
    assert payload["ready_for_day8"] is False
    assert payload["prepared_for_manual_review"] is True
    assert payload["paper_claims_allowed"] is False
    assert set(payload["failed_checks"]) >= EXPECTED_CURRENT_BLOCKERS
    assert docs_report.exists()
    for path in payload["artifacts"].values():
        assert Path(path).exists()

    annotation_json = json.loads(
        Path(payload["artifacts"]["annotation_review_json"]).read_text(encoding="utf-8")
    )
    assert annotation_json["row_count"] == 130
    assert annotation_json["human_review_completed"] is False
    assert annotation_json["summary"]["machine_needs_attention_count"] == 0
    with Path(payload["artifacts"]["annotation_review_csv"]).open(
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 130
    assert rows[0]["review_unit_id"] == "ctp_test_001_beijing_full_plan"
    assert rows[-1]["review_unit_id"] == "ctp_test_100_general_chat"

    delivery_pack = json.loads(
        Path(payload["artifacts"]["day7_delivery_pack_json"]).read_text(encoding="utf-8")
    )
    assert delivery_pack["delivery_status"] == "blocked"
    assert delivery_pack["prepared_for_manual_review"] is True
    assert delivery_pack["paper_claims_allowed"] is False
    assert delivery_pack["generated_artifacts"]

    report = Path(payload["artifacts"]["acceptance_report_md"]).read_text(encoding="utf-8")
    assert "paper_claims_allowed" in report
    assert "human_review_completed" in report
    assert "machine_needs_attention_count" in report
    assert "day7_annotation_review_round1.csv" in report


def test_git_snapshot_uses_day7_tag_on_current_head_when_freeze_tag_is_omitted(
    monkeypatch,
) -> None:
    def fake_git(args):
        if args == ["rev-parse", "HEAD"]:
            return "abc123"
        if args == ["rev-parse", "--short", "HEAD"]:
            return "abc123"
        if args == ["branch", "--show-current"]:
            return "master"
        if args == ["status", "--short"]:
            return ""
        if args == ["tag", "--points-at", "HEAD", "--list", "day7-acceptance-*"]:
            return "day7-acceptance-20260804"
        if args == ["rev-parse", "--verify", "refs/tags/day7-acceptance-20260804^{}"]:
            return "abc123"
        return ""

    monkeypatch.setattr(acceptance_review, "_git", fake_git)

    snapshot = _git_snapshot()

    assert snapshot["freeze_tag_name"] == "day7-acceptance-20260804"
    assert snapshot["freeze_object_created"] is True
    assert snapshot["freeze_matches_head"] is True
    assert snapshot["worktree_dirty"] is False


def _patch_git_snapshot(monkeypatch, *, freeze_created: bool, dirty: bool) -> None:
    head = "day7-test-head"
    tag_commit = head if freeze_created else None
    monkeypatch.setattr(
        acceptance_review,
        "_git_snapshot",
        lambda *, freeze_tag_name=None: {
            "head_commit": head,
            "head_short": head[:7],
            "branch": "test-branch",
            "worktree_dirty": dirty,
            "changed_file_count": 1 if dirty else 0,
            "status_sample": [" M test-file"] if dirty else [],
            "freeze_object_created": freeze_created,
            "freeze_tag_name": freeze_tag_name or "day7-acceptance-test",
            "freeze_tag_commit": tag_commit,
            "freeze_matches_head": freeze_created,
            "freeze_mode": "git_tag" if freeze_created else "snapshot_only",
            "recommended_tag_name": freeze_tag_name or "day7-acceptance-test",
            "recommended_commands": [],
        },
    )


def _broken_test_draft_with_machine_attention(tmp_path: Path) -> Path:
    document = json.loads(
        (ROOT / "experiments" / "ctp120_test_draft.json").read_text(encoding="utf-8")
    )
    document["cases"][0]["expected"]["hard_constraints"]["duration_days"] = 5
    path = tmp_path / "broken_ctp120_test_draft.json"
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
