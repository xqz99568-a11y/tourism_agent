"""Formal Budget Policy v2 gold access and validation.

The budget gold is evaluator-only evidence: generation code must not read it.
It is used after a method has produced an output, so the independent evaluator
can recompute the expected budget from frozen data instead of trusting numbers
reported by the method itself.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from app.core.fixed_data import (
    BUDGET_CONTINGENCY_RATIO,
    BUDGET_POLICY_VERSION,
    CANONICAL_JSON_SHA256_STRATEGY,
    REPO_ROOT,
    canonical_json_sha256,
    validate_fixed_data_snapshot,
)
from app.core.intercity_transport_snapshot import validate_intercity_transport_snapshot
from app.core.budget_manual_review import (
    DEFAULT_ECONOMY_BUDGET_MANUAL_REVIEW_PATH,
    ECONOMY_BUDGET_CONFIRMED_SCOPE,
    ECONOMY_BUDGET_EXCLUDED_SCOPE,
    ECONOMY_BUDGET_FORMAL_MAIN_TIERS,
    validate_economy_budget_manual_review,
)


BUDGET_GOLD_SCHEMA_VERSION = "ctp100-budget-gold-v2-formal-v1"
BUDGET_GOLD_STATUS = "formal_frozen"
BUDGET_GOLD_REVIEW_STATUS = "confirmed"
BUDGET_GOLD_HASH_STRATEGY_RAW_FILE = "raw_file_sha256_v1"

DEFAULT_CTP100_DATASET_PATH = REPO_ROOT / "experiments" / "ctp100_formal_v2.json"
DEFAULT_CTP100_BUDGET_GOLD_PATH = (
    REPO_ROOT / "experiments" / "generated" / "ctp100_budget_gold_v2.json"
)
LEGACY_CTP100_BUDGET_GOLD_DRAFT_PATH = (
    REPO_ROOT / "experiments" / "generated" / "ctp100_budget_gold_v2_draft.json"
)
DEFAULT_BUDGET_POLICY_DOC_PATH = REPO_ROOT / "docs" / "Budget_Policy_v2.md"

EXPECTED_CTP100_EVALUATION_UNIT_COUNT = 130
EXPECTED_CTP100_BUDGET_GOLD_COUNT = 90
EXPECTED_CTP100_BUDGET_SKIPPED_COUNT = 40


class BudgetGoldError(ValueError):
    """Raised when the formal budget gold is missing or stale."""


def load_budget_gold(path: str | Path = DEFAULT_CTP100_BUDGET_GOLD_PATH) -> Dict[str, Any]:
    budget_gold_path = Path(path)
    if not budget_gold_path.exists():
        raise BudgetGoldError(f"budget gold file not found: {budget_gold_path}")
    payload = json.loads(budget_gold_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise BudgetGoldError(f"budget gold file must be a JSON object: {budget_gold_path}")
    return payload


def build_budget_gold_artifact_hashes(
    *,
    source_dataset: Mapping[str, Any],
    source_dataset_path: str | Path,
    budget_policy_doc_path: str | Path = DEFAULT_BUDGET_POLICY_DOC_PATH,
) -> Dict[str, Any]:
    """Return reproducibility hashes for all frozen budget-gold inputs."""
    dataset_path = Path(source_dataset_path)
    policy_path = Path(budget_policy_doc_path)
    fixed_data = validate_fixed_data_snapshot()
    intercity = validate_intercity_transport_snapshot()
    fixed_files = fixed_data.get("files") if isinstance(fixed_data.get("files"), list) else []
    files_by_kind = {
        kind: [
            {
                "city_id": item.get("city_id"),
                "path": item.get("path"),
                "sha256": item.get("sha256"),
                "hash_strategy": item.get("hash_strategy"),
            }
            for item in fixed_files
            if item.get("kind") == kind
        ]
        for kind in ("accommodation", "restaurants", "pois", "transport")
    }
    return {
        "source_dataset": {
            "path": _display_path(dataset_path),
            "sha256": canonical_json_sha256(source_dataset),
            "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
        },
        "budget_policy_doc": {
            "path": _display_path(policy_path),
            "sha256": _file_sha256(policy_path),
            "hash_strategy": BUDGET_GOLD_HASH_STRATEGY_RAW_FILE,
        },
        "budget_policy": {
            "version": BUDGET_POLICY_VERSION,
            "contingency_ratio": BUDGET_CONTINGENCY_RATIO,
        },
        "fixed_tourism_data": {
            "schema_version": fixed_data.get("schema_version"),
            "combined_sha256": fixed_data.get("combined_sha256"),
            "hash_strategy": fixed_data.get("hash_strategy"),
            "file_count": fixed_data.get("file_count"),
            "city_ids": fixed_data.get("city_ids"),
            "files_by_kind": files_by_kind,
        },
        "intercity_transport_snapshot": {
            "schema_version": intercity.get("schema_version"),
            "snapshot_id": intercity.get("snapshot_id"),
            "combined_sha256": intercity.get("combined_sha256"),
            "hash_strategy": intercity.get("hash_strategy"),
            "route_count": intercity.get("route_count"),
            "fare_snapshot_date": intercity.get("fare_snapshot_date"),
            "source_name": intercity.get("source_name"),
            "evidence": intercity.get("evidence") or {},
        },
    }


def validate_budget_gold(
    path: str | Path = DEFAULT_CTP100_BUDGET_GOLD_PATH,
    *,
    source_dataset_path: str | Path = DEFAULT_CTP100_DATASET_PATH,
    budget_policy_doc_path: str | Path = DEFAULT_BUDGET_POLICY_DOC_PATH,
    expected_evaluation_unit_count: int = EXPECTED_CTP100_EVALUATION_UNIT_COUNT,
    expected_budget_gold_count: int = EXPECTED_CTP100_BUDGET_GOLD_COUNT,
    expected_skipped_count: int = EXPECTED_CTP100_BUDGET_SKIPPED_COUNT,
    manual_review_path: str | Path = DEFAULT_ECONOMY_BUDGET_MANUAL_REVIEW_PATH,
) -> Dict[str, Any]:
    """Validate that the formal budget gold still matches frozen inputs."""
    budget_gold_path = Path(path)
    document = load_budget_gold(budget_gold_path)
    dataset_path = Path(source_dataset_path)
    if not dataset_path.exists():
        raise BudgetGoldError(f"source dataset not found: {dataset_path}")
    source_dataset = json.loads(dataset_path.read_text(encoding="utf-8-sig"))
    expected_hashes = build_budget_gold_artifact_hashes(
        source_dataset=source_dataset,
        source_dataset_path=dataset_path,
        budget_policy_doc_path=budget_policy_doc_path,
    )
    errors: list[str] = []

    if document.get("schema_version") != BUDGET_GOLD_SCHEMA_VERSION:
        errors.append("unexpected budget gold schema_version")
    if document.get("gold_status") != BUDGET_GOLD_STATUS:
        errors.append("budget gold must be formal_frozen")
    if document.get("review_status") != BUDGET_GOLD_REVIEW_STATUS:
        errors.append("budget gold review_status must be confirmed")
    if document.get("budget_policy_version") != BUDGET_POLICY_VERSION:
        errors.append("budget policy version mismatch")
    if document.get("source_dataset_sha256") != expected_hashes["source_dataset"]["sha256"]:
        errors.append("source dataset hash mismatch")

    artifact_hashes = document.get("artifact_hashes")
    if not isinstance(artifact_hashes, dict):
        errors.append("artifact_hashes is required")
    else:
        _expect_equal(
            errors,
            "artifact source dataset hash",
            _nested(artifact_hashes, "source_dataset", "sha256"),
            expected_hashes["source_dataset"]["sha256"],
        )
        _expect_equal(
            errors,
            "budget policy doc hash",
            _nested(artifact_hashes, "budget_policy_doc", "sha256"),
            expected_hashes["budget_policy_doc"]["sha256"],
        )
        _expect_equal(
            errors,
            "fixed tourism data combined hash",
            _nested(artifact_hashes, "fixed_tourism_data", "combined_sha256"),
            expected_hashes["fixed_tourism_data"]["combined_sha256"],
        )
        _expect_equal(
            errors,
            "intercity snapshot combined hash",
            _nested(artifact_hashes, "intercity_transport_snapshot", "combined_sha256"),
            expected_hashes["intercity_transport_snapshot"]["combined_sha256"],
        )
        _expect_equal(
            errors,
            "intercity route count",
            _nested(artifact_hashes, "intercity_transport_snapshot", "route_count"),
            expected_hashes["intercity_transport_snapshot"]["route_count"],
        )

    manual_review = document.get("manual_review")
    if not isinstance(manual_review, Mapping):
        errors.append("manual_review is required")
    else:
        _expect_equal(errors, "manual review status", manual_review.get("status"), BUDGET_GOLD_REVIEW_STATUS)
        _expect_equal(
            errors,
            "manual review status source",
            manual_review.get("status_source"),
            "validated_economy_manual_review_ledger",
        )
        _expect_equal(
            errors,
            "manual review confirmed scope",
            manual_review.get("confirmed_scope"),
            list(ECONOMY_BUDGET_CONFIRMED_SCOPE),
        )
        _expect_equal(
            errors,
            "manual review formal tiers",
            manual_review.get("formal_main_experiment_tiers"),
            list(ECONOMY_BUDGET_FORMAL_MAIN_TIERS),
        )
        confirmed_scope = set(manual_review.get("confirmed_scope") or [])
        if confirmed_scope & set(ECONOMY_BUDGET_EXCLUDED_SCOPE):
            errors.append("manual_review confirmed_scope must not include comfort/premium")
        excluded_scope = set(manual_review.get("excluded_scope") or [])
        if not set(ECONOMY_BUDGET_EXCLUDED_SCOPE) <= excluded_scope:
            errors.append("manual_review excluded_scope must include comfort and premium")
        try:
            validated_review = validate_economy_budget_manual_review(manual_review_path)
        except Exception as exc:
            errors.append(f"economy manual review validation failed: {exc}")
            validated_review = {}
        review_artifacts = manual_review.get("review_artifacts")
        if not isinstance(review_artifacts, Mapping):
            errors.append("manual_review.review_artifacts is required")
        else:
            _expect_equal(
                errors,
                "manual review artifact path",
                review_artifacts.get("economy_manual_review_json"),
                _display_path(Path(manual_review_path)),
            )
        if validated_review:
            _expect_equal(errors, "manual review sha256", manual_review.get("review_sha256"), validated_review.get("sha256"))
            _expect_equal(
                errors,
                "manual review confirmed city ids",
                manual_review.get("confirmed_city_ids"),
                _nested(validated_review, "summary", "city_ids"),
            )

    summary = document.get("summary") if isinstance(document.get("summary"), dict) else {}
    _expect_equal(errors, "evaluation unit count", summary.get("evaluation_unit_count"), expected_evaluation_unit_count)
    _expect_equal(errors, "budget gold count", summary.get("budget_gold_count"), expected_budget_gold_count)
    _expect_equal(errors, "budget skipped count", summary.get("skipped_count"), expected_skipped_count)

    records = document.get("records")
    if not isinstance(records, list):
        errors.append("records must be a list")
        records = []
    if len(records) != expected_evaluation_unit_count:
        errors.append(f"record count mismatch: {len(records)} != {expected_evaluation_unit_count}")

    generated = [record for record in records if isinstance(record, dict) and record.get("status") == "generated"]
    skipped = [record for record in records if isinstance(record, dict) and record.get("status") == "skipped"]
    if len(generated) != expected_budget_gold_count:
        errors.append(f"generated budget record count mismatch: {len(generated)}")
    if len(skipped) != expected_skipped_count:
        errors.append(f"skipped budget record count mismatch: {len(skipped)}")
    repaired = [record.get("unit_id") for record in generated if record.get("source_slot_repairs")]
    if repaired:
        errors.append(f"budget gold contains source_slot_repairs: {repaired}")
    missing_budget_payloads = [
        record.get("unit_id")
        for record in generated
        if not isinstance(record.get("budget_policy_v2"), dict)
    ]
    if missing_budget_payloads:
        errors.append(f"generated records missing budget_policy_v2: {missing_budget_payloads}")
    non_economy_tier_records = [
        record.get("unit_id")
        for record in generated
        if _nested(record, "budget_policy_v2", "hotel_tier") != "economy"
        or _nested(record, "budget_policy_v2", "food_tier") != "economy"
    ]
    if non_economy_tier_records:
        errors.append(f"formal budget gold contains non-economy tier records: {non_economy_tier_records}")

    record_index = {
        str(record.get("unit_id")): record
        for record in generated
        if isinstance(record, dict) and record.get("unit_id")
    }
    case_016 = record_index.get("ctp100_v2_016", {})
    _expect_equal(
        errors,
        "ctp100_v2_016 one-way fare",
        _nested(case_016, "budget_policy_v2", "intercity_one_way_fare_per_person_cny"),
        623.0,
    )
    _expect_equal(
        errors,
        "ctp100_v2_016 round-trip intercity cost",
        _nested(case_016, "budget_policy_v2", "intercity_round_trip_cost_cny"),
        3738.0,
    )

    if errors:
        raise BudgetGoldError("; ".join(errors))
    return {
        **document,
        "valid": True,
        "path": _display_path(budget_gold_path),
        "artifact_hashes_expected": expected_hashes,
    }


@lru_cache(maxsize=1)
def _default_budget_gold_record_index() -> Dict[str, Dict[str, Any]]:
    try:
        document = validate_budget_gold()
    except Exception:
        return {}
    return budget_gold_record_index(document)


def budget_gold_record_index(document: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(record.get("unit_id")): dict(record)
        for record in document.get("records", [])
        if isinstance(record, dict) and record.get("unit_id")
    }


def budget_gold_record_for_case(case: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    index = _default_budget_gold_record_index()
    if not index:
        return None
    case_id = str(case.get("case_id") or case.get("scenario_id") or "").strip()
    turn_id = str(case.get("turn_id") or "").strip()
    candidates = [
        str(case.get("evaluation_unit_id") or "").strip(),
        f"{case_id}::{turn_id}" if case_id and turn_id else "",
        case_id,
    ]
    for unit_id in candidates:
        if unit_id and unit_id in index:
            return dict(index[unit_id])
    return None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expect_equal(errors: list[str], label: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        errors.append(f"{label} mismatch: {actual!r} != {expected!r}")


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()
