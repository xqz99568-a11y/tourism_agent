"""Freeze the reviewed CTP30-v2 multi-turn validation dataset.

This script performs no LLM/API calls.  It promotes the human-reviewed draft
into an official sealed validation artifact, records canonical hashes, and
keeps the dataset separate from the CTP100 main benchmark.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.benchmark_dataset_validator import build_benchmark_dataset_quality_report
from app.core.fixed_data import (
    CANONICAL_JSON_SHA256_STRATEGY,
    canonical_json_file_sha256,
    canonical_json_sha256,
)
from app.core.formal_experiment_preflight import load_benchmark_document


GENERATED_DIR = ROOT / "experiments" / "generated"
DRAFT_DATASET_PATH = GENERATED_DIR / "ctp30_multiturn_v2_draft.json"
DRAFT_AUDIT_PATH = GENERATED_DIR / "ctp30_multiturn_v2_auto_audit.json"
HUMAN_REVIEW_PATH = GENERATED_DIR / "ctp30_multiturn_v2_human_review.md"

FROZEN_DATASET_PATH = ROOT / "experiments" / "ctp30_multiturn_validation_v2.json"
FREEZE_MANIFEST_JSON_PATH = GENERATED_DIR / "ctp30_multiturn_v2_freeze_manifest.json"
FREEZE_MANIFEST_MD_PATH = GENERATED_DIR / "ctp30_multiturn_v2_freeze_manifest.md"
HUMAN_REVIEW_CONFIRMED_PATH = GENERATED_DIR / "ctp30_multiturn_v2_human_review_confirmed.md"

FROZEN_DATASET_ID = "ctp30_multiturn_validation_v2"
FROZEN_DATASET_VERSION = "2026-08-28-route-b-task2-frozen"
FROZEN_DATASET_ROLE = "sealed_multiturn_validation_after_ctp100_v6_and_ctp30_v1"
FROZEN_SPLIT = "sealed_multiturn_validation"
FREEZE_DATE = "2026-08-28"
EXPECTED_TARGET_TASK_DISTRIBUTION = {
    "attraction_recommendation": 1,
    "budget_query": 4,
    "clarification": 1,
    "partial_replan": 15,
    "weather_adjustment": 6,
    "weather_query": 3,
}


def main() -> int:
    errors: list[str] = []
    draft = _read_json_object(DRAFT_DATASET_PATH, errors, label="draft dataset")
    draft_audit = _read_json_object(DRAFT_AUDIT_PATH, errors, label="draft auto audit")
    if errors:
        _write_failure(errors)
        return 1

    _validate_draft_ready(draft, draft_audit, errors)
    if errors:
        _write_failure(errors)
        return 1

    frozen = _promote_to_frozen_dataset(draft)
    quality_report = _quality_report(frozen)
    errors.extend(str(error) for error in quality_report.get("errors") or [])

    manifest = _build_freeze_manifest(
        frozen=frozen,
        draft=draft,
        draft_audit=draft_audit,
        quality_report=quality_report,
        errors=errors,
    )

    if errors:
        _write_json(FREEZE_MANIFEST_JSON_PATH, manifest)
        FREEZE_MANIFEST_MD_PATH.write_text(_render_manifest_md(manifest), encoding="utf-8")
        print(json.dumps(_console_payload(manifest), ensure_ascii=False, indent=2))
        return 1

    _write_json(FROZEN_DATASET_PATH, frozen)
    _write_json(FREEZE_MANIFEST_JSON_PATH, manifest)
    FREEZE_MANIFEST_MD_PATH.write_text(_render_manifest_md(manifest), encoding="utf-8")
    HUMAN_REVIEW_CONFIRMED_PATH.write_text(
        _render_human_review_confirmation(frozen, manifest),
        encoding="utf-8",
    )
    print(json.dumps(_console_payload(manifest), ensure_ascii=False, indent=2))
    return 0


def _promote_to_frozen_dataset(draft: Mapping[str, Any]) -> dict[str, Any]:
    frozen = deepcopy(dict(draft))
    draft_sha256 = canonical_json_sha256(draft)
    frozen.update(
        {
            "dataset_id": FROZEN_DATASET_ID,
            "dataset_version": FROZEN_DATASET_VERSION,
            "dataset_role": FROZEN_DATASET_ROLE,
            "split": FROZEN_SPLIT,
            "description": (
                "Frozen Route-B CTP30-v2 sealed multi-turn validation set. "
                "Each case has two real turns: turn 1 builds method-local "
                "dialogue state, and turn 2 is the primary evaluation turn. "
                "This set is frozen after CTP100 v6 and CTP30-v1 and must not "
                "be used for development tuning."
            ),
            "comparison_files": ["ctp100_formal_v2.json"],
            "source_draft": {
                "path": _repo_path(DRAFT_DATASET_PATH),
                "dataset_id": draft.get("dataset_id"),
                "dataset_version": draft.get("dataset_version"),
                "sha256": draft_sha256,
                "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
            },
            "manual_review": {
                "status": "confirmed",
                "confirmed_by": "single_annotator_user",
                "confirmed_on": FREEZE_DATE,
                "source": "user conversation confirmation before task 2 freeze",
                "review_artifact": _repo_path(HUMAN_REVIEW_PATH),
                "confirmed_artifact": _repo_path(HUMAN_REVIEW_CONFIRMED_PATH),
                "paper_disclosure_required": (
                    "CTP30-v2 was designed and labeled by a single annotator "
                    "and checked by automatic schema, slot, weather, budget, "
                    "city-coverage, and duplicate audits."
                ),
            },
            "freeze_policy": {
                "frozen_on": FREEZE_DATE,
                "may_be_used_for": "sealed_multiturn_validation_only",
                "must_not_be_used_for": "development_tuning_or_ctp100_main_benchmark",
                "allowed_methods": ["fixed_multi_agent", "adaptive_multi_agent"],
                "primary_evaluation_turn": "t2",
                "statistical_unit": "case_id",
                "gold_visible_to_generation": False,
                "previous_state_injection_allowed": False,
                "previous_state_policy": (
                    "During sealed execution, turn 2 may read only the same "
                    "method's own turn-1 runtime state. Gold slots must not be "
                    "injected as previous state."
                ),
                "runtime_online_weather_refresh_allowed": False,
                "runtime_online_intercity_price_refresh_allowed": False,
                "ctp30_v1_retained_for_limitations_analysis": True,
            },
        }
    )

    annotation_policy = dict(frozen.get("annotation_policy") or {})
    annotation_policy.update(
        {
            "human_review_required_before_freeze": False,
            "human_review_completed": True,
            "manual_review_status": "confirmed",
            "manual_review_completed_on": FREEZE_DATE,
            "frozen_after_main_experiment": True,
            "gold_visible_to_generation": False,
            "previous_state_injection_allowed": False,
        }
    )
    frozen["annotation_policy"] = annotation_policy

    claim_policy = dict(frozen.get("claim_policy") or {})
    claim_policy.update(
        {
            "draft_only": False,
            "must_not_run_before_human_confirmation": False,
            "human_review_status": "confirmed",
            "used_for_development_tuning": False,
            "paper_claims_allowed_after_successful_runner_gate": True,
            "paper_wording_required": (
                "论文中应说明 CTP30-v2 由单人标注并经自动规则审计；"
                "不得声称多人一致性。CTP30-v2 只作为封闭多轮补充验证，"
                "不替代 CTP100 主实验。"
            ),
        }
    )
    frozen["claim_policy"] = claim_policy
    return frozen


def _validate_draft_ready(
    draft: Mapping[str, Any],
    draft_audit: Mapping[str, Any],
    errors: list[str],
) -> None:
    if draft.get("dataset_id") != "ctp30_multiturn_validation_v2_draft":
        errors.append(f"unexpected draft dataset_id: {draft.get('dataset_id')}")
    if (draft.get("claim_policy") or {}).get("draft_only") is not True:
        errors.append("source draft must still be marked draft_only=true")
    if draft.get("case_count") != 30:
        errors.append(f"draft case_count must be 30, got {draft.get('case_count')}")
    if draft.get("turn_count") != 60:
        errors.append(f"draft turn_count must be 60, got {draft.get('turn_count')}")
    cases = draft.get("cases") if isinstance(draft.get("cases"), list) else []
    if len(cases) != 30:
        errors.append(f"draft cases list must contain 30 items, got {len(cases)}")
    if any(len(case.get("turns") or []) != 2 for case in cases if isinstance(case, Mapping)):
        errors.append("every CTP30-v2 draft case must contain exactly two turns")
    target_distribution = Counter(
        str(case["turns"][1].get("task_type"))
        for case in cases
        if isinstance(case, Mapping)
        and isinstance(case.get("turns"), list)
        and len(case["turns"]) == 2
    )
    if dict(sorted(target_distribution.items())) != EXPECTED_TARGET_TASK_DISTRIBUTION:
        errors.append(
            "unexpected target turn distribution: "
            f"{dict(sorted(target_distribution.items()))}"
        )
    if draft_audit.get("status") != "passed":
        errors.append(f"draft auto audit must pass, got {draft_audit.get('status')}")
    if draft_audit.get("quality_status") != "passed":
        errors.append(f"draft quality audit must pass, got {draft_audit.get('quality_status')}")
    actual_sha256 = canonical_json_sha256(draft)
    if draft_audit.get("dataset_sha256") != actual_sha256:
        errors.append(
            "draft auto audit sha256 does not match draft dataset: "
            f"{draft_audit.get('dataset_sha256')} != {actual_sha256}"
        )


def _quality_report(frozen: Mapping[str, Any]) -> dict[str, Any]:
    _, ctp100_cases = load_benchmark_document(ROOT / "experiments" / "ctp100_formal_v2.json")
    return build_benchmark_dataset_quality_report(
        document=frozen,
        cases=frozen.get("cases") or [],
        expected_case_count=30,
        strict_formal=True,
        comparison_splits={"ctp100_formal_v2": ctp100_cases},
    )


def _build_freeze_manifest(
    *,
    frozen: Mapping[str, Any],
    draft: Mapping[str, Any],
    draft_audit: Mapping[str, Any],
    quality_report: Mapping[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    target_distribution = Counter(
        str(case["turns"][1].get("task_type"))
        for case in frozen.get("cases") or []
        if isinstance(case, Mapping)
        and isinstance(case.get("turns"), list)
        and len(case["turns"]) == 2
    )
    turn_distribution = Counter(
        str(turn.get("task_type"))
        for case in frozen.get("cases") or []
        if isinstance(case, Mapping)
        for turn in case.get("turns") or []
        if isinstance(turn, Mapping)
    )
    frozen_sha256 = canonical_json_sha256(frozen)
    manifest = {
        "schema_version": "ctp30-multiturn-v2-freeze-manifest-v1",
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "freeze_date": FREEZE_DATE,
        "frozen_dataset": {
            "path": _repo_path(FROZEN_DATASET_PATH),
            "dataset_id": frozen.get("dataset_id"),
            "dataset_version": frozen.get("dataset_version"),
            "dataset_role": frozen.get("dataset_role"),
            "split": frozen.get("split"),
            "sha256": frozen_sha256,
            "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
            "case_count": frozen.get("case_count"),
            "turn_count": frozen.get("turn_count"),
            "scenario_case_count": len(frozen.get("cases") or []),
            "target_turn_id": "t2",
            "turn_task_distribution": dict(sorted(turn_distribution.items())),
            "target_turn_task_distribution": dict(sorted(target_distribution.items())),
        },
        "source_draft": {
            "path": _repo_path(DRAFT_DATASET_PATH),
            "sha256": canonical_json_sha256(draft),
            "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
            "dataset_id": draft.get("dataset_id"),
            "dataset_version": draft.get("dataset_version"),
        },
        "source_audit": {
            "path": _repo_path(DRAFT_AUDIT_PATH),
            "sha256": canonical_json_file_sha256(DRAFT_AUDIT_PATH),
            "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
            "status": draft_audit.get("status"),
            "quality_status": draft_audit.get("quality_status"),
            "quality_error_count": len(draft_audit.get("quality_errors") or []),
            "cross_split_duplicate_count": len(
                draft_audit.get("cross_split_duplicate_visible_input_groups") or []
            ),
            "cross_split_near_duplicate_count": len(
                draft_audit.get("cross_split_near_duplicate_visible_input_pairs") or []
            ),
        },
        "human_review": {
            "status": "confirmed",
            "confirmed_by": "single_annotator_user",
            "confirmed_on": FREEZE_DATE,
            "review_artifact": _repo_path(HUMAN_REVIEW_PATH),
            "review_artifact_sha256_raw": _raw_file_sha256(HUMAN_REVIEW_PATH),
            "confirmed_artifact": _repo_path(HUMAN_REVIEW_CONFIRMED_PATH),
        },
        "quality_gate": {
            "status": quality_report.get("status"),
            "errors": quality_report.get("errors") or [],
            "warnings": quality_report.get("warnings") or [],
            "cross_split_duplicate_count": len(
                (quality_report.get("coverage") or {}).get(
                    "cross_split_duplicate_visible_input_groups"
                )
                or []
            ),
            "cross_split_near_duplicate_count": len(
                (quality_report.get("coverage") or {}).get(
                    "near_duplicate_visible_input_pairs"
                )
                or []
            ),
        },
        "paper_use_policy": {
            "allowed": True,
            "scope": "supplementary sealed multi-turn validation after CTP100 v6",
            "must_disclose_single_annotator": True,
            "must_not_claim_multi_annotator_agreement": True,
            "must_not_replace_ctp100_main_experiment": True,
            "ctp30_v1_retained_for_limitations_analysis": True,
            "formal_runner_update_required_next": True,
        },
        "api_usage": {
            "llm_calls": 0,
            "weather_api_calls": 0,
            "intercity_api_calls": 0,
        },
    }
    return manifest


def _render_human_review_confirmation(
    frozen: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> str:
    lines = [
        "# CTP30-v2 人工确认记录",
        "",
        "> 本文件记录 CTP30-v2 草稿在冻结前已经由单人审阅确认。它不表示多人一致性。",
        "",
        f"- 确认状态：`{manifest['human_review']['status']}`",
        f"- 确认日期：`{manifest['human_review']['confirmed_on']}`",
        "- 确认人：`single_annotator_user`",
        f"- 正式数据集：`{manifest['frozen_dataset']['path']}`",
        f"- 正式数据集 SHA256：`{manifest['frozen_dataset']['sha256']}`",
        "- 使用范围：只作为 CTP100 主实验之后的封闭多轮补充验证。",
        "",
        "## 论文披露口径",
        "",
        "CTP30-v2 由单人设计和标注，并经过自动规则审计；论文中不得声称多人标注一致性。"
        "该数据集只用于考察多轮上下文传递与调度复用能力，不替代 CTP100 主实验。",
        "",
        "## 冻结案例清单",
        "",
        "| # | case_id | 第一轮任务 | 第二轮任务 | 第二轮是否主评估 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for index, case in enumerate(frozen.get("cases") or [], start=1):
        turns = case.get("turns") or []
        t1 = turns[0] if len(turns) >= 1 else {}
        t2 = turns[1] if len(turns) >= 2 else {}
        lines.append(
            "| {index} | `{case_id}` | `{t1_task}` | `{t2_task}` | `{primary}` |".format(
                index=index,
                case_id=case.get("case_id"),
                t1_task=t1.get("task_type"),
                t2_task=t2.get("task_type"),
                primary="是" if case.get("primary_turn_id") == "t2" else "否",
            )
        )
    lines.append("")
    return "\n".join(lines)


def _render_manifest_md(manifest: Mapping[str, Any]) -> str:
    frozen = manifest.get("frozen_dataset") or {}
    source = manifest.get("source_draft") or {}
    quality = manifest.get("quality_gate") or {}
    policy = manifest.get("paper_use_policy") or {}
    lines = [
        "# CTP30-v2 Freeze Manifest",
        "",
        f"- status: `{manifest.get('status')}`",
        f"- freeze_date: `{manifest.get('freeze_date')}`",
        f"- frozen_dataset: `{frozen.get('path')}`",
        f"- frozen_dataset_sha256: `{frozen.get('sha256')}`",
        f"- source_draft: `{source.get('path')}`",
        f"- source_draft_sha256: `{source.get('sha256')}`",
        f"- case_count / turn_count: `{frozen.get('case_count')}` / `{frozen.get('turn_count')}`",
        f"- target_turn_task_distribution: `{frozen.get('target_turn_task_distribution')}`",
        f"- quality_status: `{quality.get('status')}`",
        f"- quality_error_count: `{len(quality.get('errors') or [])}`",
        f"- quality_warning_count: `{len(quality.get('warnings') or [])}`",
        f"- cross_split_duplicate_count: `{quality.get('cross_split_duplicate_count')}`",
        f"- cross_split_near_duplicate_count: `{quality.get('cross_split_near_duplicate_count')}`",
        f"- paper_allowed: `{policy.get('allowed')}`",
        "",
        "## Errors",
        "",
    ]
    lines.extend([f"- {item}" for item in manifest.get("errors") or []] or ["- None"])
    lines.extend(
        [
            "",
            "## Required paper wording",
            "",
            "- CTP30-v2 is a supplementary sealed multi-turn validation set after CTP100 v6.",
            "- CTP30-v2 uses single-annotator labels plus automatic rule audit.",
            "- Do not claim multi-annotator agreement for CTP30-v2.",
            "- CTP30-v1 is retained and discussed as a limitation/design-boundary result.",
            "",
        ]
    )
    return "\n".join(lines)


def _console_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    frozen = manifest.get("frozen_dataset") or {}
    return {
        "status": manifest.get("status"),
        "frozen_dataset": frozen.get("path"),
        "frozen_dataset_sha256": frozen.get("sha256"),
        "freeze_manifest_json": _repo_path(FREEZE_MANIFEST_JSON_PATH),
        "freeze_manifest_md": _repo_path(FREEZE_MANIFEST_MD_PATH),
        "human_review_confirmed": _repo_path(HUMAN_REVIEW_CONFIRMED_PATH),
        "case_count": frozen.get("case_count"),
        "turn_count": frozen.get("turn_count"),
        "target_turn_task_distribution": frozen.get("target_turn_task_distribution"),
        "errors": manifest.get("errors") or [],
    }


def _write_failure(errors: list[str]) -> None:
    payload = {
        "schema_version": "ctp30-multiturn-v2-freeze-manifest-v1",
        "status": "failed",
        "errors": errors,
        "freeze_date": FREEZE_DATE,
        "api_usage": {"llm_calls": 0, "weather_api_calls": 0, "intercity_api_calls": 0},
    }
    _write_json(FREEZE_MANIFEST_JSON_PATH, payload)
    FREEZE_MANIFEST_MD_PATH.write_text(_render_manifest_md(payload), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _read_json_object(path: Path, errors: list[str], *, label: str) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"{label} does not exist: {_repo_path(path)}")
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label} is invalid: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label} must be a JSON object")
        return {}
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _raw_file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
