"""Validated manual review evidence for the formal economy budget baseline.

This module keeps the paper-facing budget review honest: a formal budget gold
file may only claim ``review_status=confirmed`` after this explicit review
ledger has been validated against the frozen local data.
"""
from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

from app.core.fixed_data import (
    BUDGET_POLICY_VERSION,
    CANONICAL_JSON_SHA256_STRATEGY,
    FIXED_CITY_IDS,
    REPO_ROOT,
    validate_fixed_data_snapshot,
)


ECONOMY_BUDGET_MANUAL_REVIEW_SCHEMA_VERSION = "economy-budget-manual-review-v1"
ECONOMY_BUDGET_MANUAL_REVIEW_STATUS = "confirmed"
ECONOMY_BUDGET_CONFIRMED_SCOPE = (
    "economy",
    "intercity_transport",
    "budget_policy_v2",
)
ECONOMY_BUDGET_EXCLUDED_SCOPE = ("comfort", "premium")
ECONOMY_BUDGET_FORMAL_MAIN_TIERS = ("economy",)
ECONOMY_FOOD_FORMULA_ID = "food_median_reference_price_x_people_x_2d_plus_0_5n_v1"
ECONOMY_ACCOMMODATION_FORMULA_ID = "accommodation_median_reference_price_x_rooms_x_nights_v1"

DEFAULT_ECONOMY_BUDGET_MANUAL_REVIEW_PATH = (
    REPO_ROOT / "experiments" / "generated" / "economy_budget_manual_review_v1.json"
)
DEFAULT_ECONOMY_BUDGET_MANUAL_REVIEW_MD_PATH = (
    REPO_ROOT / "experiments" / "generated" / "economy_budget_manual_review_v1.md"
)


class EconomyBudgetManualReviewError(ValueError):
    """Raised when the economy budget manual review ledger is missing or stale."""


def load_economy_budget_manual_review(
    path: str | Path = DEFAULT_ECONOMY_BUDGET_MANUAL_REVIEW_PATH,
) -> Dict[str, Any]:
    review_path = Path(path)
    if not review_path.exists():
        raise EconomyBudgetManualReviewError(f"economy budget manual review not found: {review_path}")
    payload = json.loads(review_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise EconomyBudgetManualReviewError(
            f"economy budget manual review must be a JSON object: {review_path}"
        )
    return payload


def validate_economy_budget_manual_review(
    path: str | Path = DEFAULT_ECONOMY_BUDGET_MANUAL_REVIEW_PATH,
) -> Dict[str, Any]:
    """Validate the explicit economy-only review ledger against frozen data."""
    review_path = Path(path)
    document = load_economy_budget_manual_review(review_path)
    expected_city_reviews = build_expected_economy_city_reviews()
    expected_by_city = {row["city_id"]: row for row in expected_city_reviews}
    errors: list[str] = []

    if document.get("schema_version") != ECONOMY_BUDGET_MANUAL_REVIEW_SCHEMA_VERSION:
        errors.append("unexpected economy budget manual review schema_version")
    if document.get("review_status") != ECONOMY_BUDGET_MANUAL_REVIEW_STATUS:
        errors.append("economy budget manual review status must be confirmed")
    if not str(document.get("reviewer") or "").strip():
        errors.append("economy budget manual review reviewer is required")
    if not str(document.get("review_date") or "").strip():
        errors.append("economy budget manual review review_date is required")
    if document.get("budget_policy_version") != BUDGET_POLICY_VERSION:
        errors.append("economy budget manual review budget_policy_version mismatch")

    confirmed_scope = tuple(document.get("confirmed_scope") or ())
    if confirmed_scope != ECONOMY_BUDGET_CONFIRMED_SCOPE:
        errors.append(
            f"confirmed_scope must be exactly {list(ECONOMY_BUDGET_CONFIRMED_SCOPE)}"
        )
    if set(confirmed_scope) & set(ECONOMY_BUDGET_EXCLUDED_SCOPE):
        errors.append("comfort/premium must not appear in confirmed_scope")
    excluded_scope = set(document.get("excluded_scope") or ())
    if not set(ECONOMY_BUDGET_EXCLUDED_SCOPE) <= excluded_scope:
        errors.append("excluded_scope must explicitly include comfort and premium")
    formal_main_tiers = tuple(document.get("formal_main_experiment_tiers") or ())
    if formal_main_tiers != ECONOMY_BUDGET_FORMAL_MAIN_TIERS:
        errors.append("formal_main_experiment_tiers must be economy-only")

    exclusion = document.get("comfort_premium_exclusion")
    if not isinstance(exclusion, Mapping):
        errors.append("comfort_premium_exclusion is required")
    elif exclusion.get("excluded_from_formal_main_experiment") is not True:
        errors.append("comfort/premium exclusion must be explicit")

    fixed_snapshot = validate_fixed_data_snapshot()
    fixed_review = document.get("fixed_tourism_data")
    if not isinstance(fixed_review, Mapping):
        errors.append("fixed_tourism_data review hash block is required")
    else:
        if fixed_review.get("combined_sha256") != fixed_snapshot.get("combined_sha256"):
            errors.append("fixed tourism data combined hash mismatch")
        if fixed_review.get("hash_strategy") != fixed_snapshot.get("hash_strategy"):
            errors.append("fixed tourism data hash strategy mismatch")

    food_formula = document.get("food_formula")
    if not isinstance(food_formula, Mapping):
        errors.append("food_formula is required")
    elif food_formula.get("formula_id") != ECONOMY_FOOD_FORMULA_ID:
        errors.append("food formula id mismatch")

    accommodation_formula = document.get("accommodation_formula")
    if not isinstance(accommodation_formula, Mapping):
        errors.append("accommodation_formula is required")
    elif accommodation_formula.get("formula_id") != ECONOMY_ACCOMMODATION_FORMULA_ID:
        errors.append("accommodation formula id mismatch")

    city_reviews = document.get("city_reviews")
    if not isinstance(city_reviews, list):
        errors.append("city_reviews must be a list")
        city_reviews = []
    city_ids = [str(row.get("city_id") or "") for row in city_reviews if isinstance(row, Mapping)]
    if tuple(city_ids) != tuple(FIXED_CITY_IDS):
        errors.append(f"city_reviews must cover fixed cities in order: {list(FIXED_CITY_IDS)}")

    for row in city_reviews:
        if not isinstance(row, Mapping):
            errors.append("city_review row must be an object")
            continue
        city_id = str(row.get("city_id") or "")
        expected = expected_by_city.get(city_id)
        if not expected:
            continue
        if row.get("review_status") != ECONOMY_BUDGET_MANUAL_REVIEW_STATUS:
            errors.append(f"{city_id} review_status must be confirmed")
        _check_component(errors, city_id, "accommodation", row.get("accommodation"), expected["accommodation"])
        _check_component(errors, city_id, "food", row.get("food"), expected["food"])
        if row.get("review_conclusion") != "confirmed_for_formal_economy_budget_baseline":
            errors.append(f"{city_id} review_conclusion mismatch")

    if errors:
        raise EconomyBudgetManualReviewError("; ".join(errors))

    return {
        **document,
        "valid": True,
        "path": _display_path(review_path),
        "sha256": _file_sha256(review_path),
        "summary": {
            "review_status": document.get("review_status"),
            "confirmed_scope": list(ECONOMY_BUDGET_CONFIRMED_SCOPE),
            "excluded_scope": list(ECONOMY_BUDGET_EXCLUDED_SCOPE),
            "formal_main_experiment_tiers": list(ECONOMY_BUDGET_FORMAL_MAIN_TIERS),
            "city_count": len(city_reviews),
            "city_ids": city_ids,
        },
    }


def build_expected_economy_city_reviews() -> list[Dict[str, Any]]:
    """Return the economy review rows expected from the frozen data layer."""
    fixed_snapshot = validate_fixed_data_snapshot()
    files = fixed_snapshot.get("files") if isinstance(fixed_snapshot.get("files"), list) else []
    files_by_path = {str(item.get("path")): item for item in files if isinstance(item, Mapping)}
    rows: list[Dict[str, Any]] = []
    for city_id in FIXED_CITY_IDS:
        accommodation_path = REPO_ROOT / "data" / "accommodation" / f"{city_id}.json"
        restaurants_path = REPO_ROOT / "data" / "restaurants" / f"{city_id}.json"
        accommodation_doc = _read_json(accommodation_path)
        restaurants_doc = _read_json(restaurants_path)
        accommodation_values = _tier_values(
            accommodation_doc.get("accommodation_areas") or [],
            "economy",
            "reference_price_cny",
        )
        food_values = _tier_values(
            restaurants_doc.get("dining_areas") or [],
            "economy",
            "reference_price_cny",
        )
        city_name = (
            (accommodation_doc.get("metadata") or {}).get("city_name")
            or (restaurants_doc.get("metadata") or {}).get("city_name")
            or city_id
        )
        accommodation_source = _source_block(accommodation_path, files_by_path)
        restaurants_source = _source_block(restaurants_path, files_by_path)
        rows.append(
            {
                "city_id": city_id,
                "city_name": city_name,
                "review_status": ECONOMY_BUDGET_MANUAL_REVIEW_STATUS,
                "accommodation": {
                    "tier": "economy",
                    "reference_price_cny": round(_median(accommodation_values), 2),
                    "statistic": "citywide_median_reference_price",
                    "source_values": accommodation_values,
                    "source_file": accommodation_source["path"],
                    "source_sha256": accommodation_source["sha256"],
                    "hash_strategy": accommodation_source["hash_strategy"],
                },
                "food": {
                    "tier": "economy",
                    "reference_price_cny": round(_median(food_values), 2),
                    "statistic": "citywide_median_reference_price",
                    "source_values": food_values,
                    "source_file": restaurants_source["path"],
                    "source_sha256": restaurants_source["sha256"],
                    "hash_strategy": restaurants_source["hash_strategy"],
                    "formula_id": ECONOMY_FOOD_FORMULA_ID,
                },
                "review_conclusion": "confirmed_for_formal_economy_budget_baseline",
            }
        )
    return rows


def _check_component(
    errors: list[str],
    city_id: str,
    component: str,
    actual: Any,
    expected: Mapping[str, Any],
) -> None:
    if not isinstance(actual, Mapping):
        errors.append(f"{city_id} {component} must be an object")
        return
    for key in (
        "tier",
        "reference_price_cny",
        "statistic",
        "source_values",
        "source_file",
        "source_sha256",
        "hash_strategy",
    ):
        if actual.get(key) != expected.get(key):
            errors.append(
                f"{city_id} {component}.{key} mismatch: {actual.get(key)!r} != {expected.get(key)!r}"
            )
    if component == "food" and actual.get("formula_id") != expected.get("formula_id"):
        errors.append(f"{city_id} food.formula_id mismatch")


def _source_block(path: Path, files_by_path: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    display = _display_path(path)
    manifest_item = files_by_path.get(display) or {}
    return {
        "path": display,
        "sha256": manifest_item.get("sha256"),
        "hash_strategy": manifest_item.get("hash_strategy") or CANONICAL_JSON_SHA256_STRATEGY,
    }


def _tier_values(items: Iterable[Mapping[str, Any]], tier: str, field: str) -> list[float]:
    values: list[float] = []
    for item in items:
        value = (((item.get("budget") or {}).get("tiers") or {}).get(tier) or {}).get(field)
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            values.append(parsed)
    return values


def _median(values: Iterable[float]) -> float:
    parsed = sorted(float(value) for value in values if float(value) > 0)
    if not parsed:
        return 0.0
    return float(statistics.median(parsed))


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()
