"""Frozen intercity rail fare snapshot access for formal tourism experiments.

This module is offline-only.  It reads the manually confirmed 12306 second-class
rail fare table and never performs live price lookup during experiments.
"""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.fixed_data import (
    CANONICAL_JSON_SHA256_STRATEGY,
    DATA_ROOT,
    REPO_ROOT,
    canonical_json_bytes,
    canonical_json_file_sha256,
)


INTERCITY_TRANSPORT_MANIFEST_SCHEMA_VERSION = "ctp-intercity-transport-manifest-v1"
INTERCITY_RAIL_FARE_SCHEMA_VERSION = "ctp-intercity-rail-second-class-v1"
INTERCITY_RAIL_EVIDENCE_LEDGER_SCHEMA_VERSION = "ctp-intercity-rail-evidence-ledger-v1"
INTERCITY_TRANSPORT_DIR = DATA_ROOT / "intercity_transport"
INTERCITY_RAIL_FARE_FILE = INTERCITY_TRANSPORT_DIR / "rail_second_class_v1.json"
INTERCITY_RAIL_EVIDENCE_LEDGER_FILE = (
    INTERCITY_TRANSPORT_DIR / "evidence" / "rail_second_class_evidence_v1.json"
)
INTERCITY_TRANSPORT_MANIFEST_FILE = INTERCITY_TRANSPORT_DIR / "snapshot_manifest.json"

INTERCITY_SUPPORTED_DESTINATION_CITY_IDS = (
    "beijing",
    "hangzhou",
    "xian",
    "shenzhen",
    "guilin",
)
INTERCITY_SUPPORTED_ORIGIN_CITY_IDS = (
    "shanghai",
    "guangzhou",
    "chengdu",
    "chongqing",
    "wuhan",
    "changsha",
    "nanjing",
    "zhengzhou",
    "nanchang",
    "guiyang",
)

INTERCITY_CITY_NAMES: Dict[str, str] = {
    "beijing": "\u5317\u4eac",
    "hangzhou": "\u676d\u5dde",
    "xian": "\u897f\u5b89",
    "shenzhen": "\u6df1\u5733",
    "guilin": "\u6842\u6797",
    "shanghai": "\u4e0a\u6d77",
    "guangzhou": "\u5e7f\u5dde",
    "chengdu": "\u6210\u90fd",
    "chongqing": "\u91cd\u5e86",
    "wuhan": "\u6b66\u6c49",
    "changsha": "\u957f\u6c99",
    "nanjing": "\u5357\u4eac",
    "zhengzhou": "\u90d1\u5dde",
    "nanchang": "\u5357\u660c",
    "guiyang": "\u8d35\u9633",
    "lhasa": "\u62c9\u8428",
}

INTERCITY_CITY_ALIASES: Dict[str, tuple[str, ...]] = {
    "beijing": ("beijing", "bj", "\u5317\u4eac", "\u5317\u4eac\u5e02"),
    "hangzhou": ("hangzhou", "hz", "\u676d\u5dde", "\u676d\u5dde\u5e02"),
    "xian": ("xian", "xi'an", "xi an", "xa", "\u897f\u5b89", "\u897f\u5b89\u5e02"),
    "shenzhen": ("shenzhen", "sz", "\u6df1\u5733", "\u6df1\u5733\u5e02"),
    "guilin": ("guilin", "gl", "\u6842\u6797", "\u6842\u6797\u5e02"),
    "shanghai": ("shanghai", "sh", "\u4e0a\u6d77", "\u4e0a\u6d77\u5e02"),
    "guangzhou": ("guangzhou", "gz", "\u5e7f\u5dde", "\u5e7f\u5dde\u5e02"),
    "chengdu": ("chengdu", "cd", "\u6210\u90fd", "\u6210\u90fd\u5e02"),
    "chongqing": ("chongqing", "cq", "\u91cd\u5e86", "\u91cd\u5e86\u5e02"),
    "wuhan": ("wuhan", "wh", "\u6b66\u6c49", "\u6b66\u6c49\u5e02"),
    "changsha": ("changsha", "cs", "\u957f\u6c99", "\u957f\u6c99\u5e02"),
    "nanjing": ("nanjing", "nj", "\u5357\u4eac", "\u5357\u4eac\u5e02"),
    "zhengzhou": ("zhengzhou", "zz", "\u90d1\u5dde", "\u90d1\u5dde\u5e02"),
    "nanchang": ("nanchang", "nc", "\u5357\u660c", "\u5357\u660c\u5e02"),
    "guiyang": ("guiyang", "gy", "\u8d35\u9633", "\u8d35\u9633\u5e02"),
    "lhasa": ("lhasa", "\u62c9\u8428", "\u62c9\u8428\u5e02"),
}

UNSUPPORTED_ROUTE_DISCLAIMER = (
    "\u672a\u67e5\u8be2\u5230\u76f8\u5173\u52a8\u8f66\u4fe1\u606f\uff0c"
    "\u6b64\u6b21\u9884\u7b97\u4e0d\u5305\u542b\u57ce\u9645\u4ea4\u901a\uff0c"
    "\u5efa\u8bae\u524d\u5f80\u4e2d\u56fd\u94c1\u8def12306\u5b98\u7f51\u67e5\u8be2\u3002"
)
MISSING_ORIGIN_DISCLAIMER = (
    "\u672a\u63d0\u4f9b\u51fa\u53d1\u5730\uff0c"
    "\u5f53\u524d\u9884\u7b97\u53ea\u8ba1\u7b97\u76ee\u7684\u5730\u5f53\u5730\u8d39\u7528\uff0c"
    "\u4e0d\u5305\u542b\u51fa\u53d1\u5730\u4e0e\u76ee\u7684\u5730\u4e4b\u95f4\u7684\u5f80\u8fd4\u57ce\u9645\u4ea4\u901a\u3002"
)


class IntercityTransportSnapshotError(ValueError):
    """Raised when the frozen intercity fare snapshot is missing or invalid."""


def normalize_intercity_city_id(city: Any) -> Optional[str]:
    text = str(city or "").strip()
    if not text:
        return None
    lowered = text.casefold()
    for city_id, aliases in INTERCITY_CITY_ALIASES.items():
        if any(lowered == alias.casefold() for alias in aliases):
            return city_id

    tokens = {
        item
        for item in re.split(r"[^0-9a-zA-Z']+", lowered)
        if item
    }
    for city_id, aliases in INTERCITY_CITY_ALIASES.items():
        for alias in aliases:
            alias_lower = alias.casefold()
            if _contains_cjk(alias):
                if alias in text:
                    return city_id
                continue
            if len(alias_lower) <= 2:
                if alias_lower in tokens:
                    return city_id
                continue
            if alias_lower in tokens or re.search(
                rf"(?<![0-9a-zA-Z]){re.escape(alias_lower)}(?![0-9a-zA-Z])",
                lowered,
            ):
                return city_id
    return None


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def intercity_city_label(city_id: Any) -> str:
    city_text = str(city_id or "").strip()
    normalized = normalize_intercity_city_id(city_text) or city_text
    return INTERCITY_CITY_NAMES.get(normalized, city_text)


def load_intercity_transport_snapshot_manifest(
    snapshot_dir: Path = INTERCITY_TRANSPORT_DIR,
) -> Dict[str, Any]:
    return _read_json(snapshot_dir / "snapshot_manifest.json")


def load_intercity_rail_fare_table(
    snapshot_dir: Path = INTERCITY_TRANSPORT_DIR,
) -> Dict[str, Any]:
    return _read_json(snapshot_dir / "rail_second_class_v1.json")


def load_intercity_rail_evidence_ledger(
    snapshot_dir: Path = INTERCITY_TRANSPORT_DIR,
) -> Dict[str, Any]:
    return _read_json(snapshot_dir / "evidence" / "rail_second_class_evidence_v1.json")


def validate_intercity_transport_snapshot(
    snapshot_dir: Path = INTERCITY_TRANSPORT_DIR,
) -> Dict[str, Any]:
    manifest_path = snapshot_dir / "snapshot_manifest.json"
    fare_path = snapshot_dir / "rail_second_class_v1.json"
    evidence_path = snapshot_dir / "evidence" / "rail_second_class_evidence_v1.json"
    if not manifest_path.exists():
        raise IntercityTransportSnapshotError(f"intercity snapshot manifest not found: {manifest_path}")
    if not fare_path.exists():
        raise IntercityTransportSnapshotError(f"intercity rail fare table not found: {fare_path}")
    if not evidence_path.exists():
        raise IntercityTransportSnapshotError(
            f"intercity rail evidence ledger not found: {evidence_path}"
        )

    manifest = load_intercity_transport_snapshot_manifest(snapshot_dir)
    fare_table = load_intercity_rail_fare_table(snapshot_dir)
    evidence_ledger = load_intercity_rail_evidence_ledger(snapshot_dir)
    errors: List[str] = []

    if manifest.get("schema_version") != INTERCITY_TRANSPORT_MANIFEST_SCHEMA_VERSION:
        errors.append("unexpected intercity snapshot manifest schema_version")
    if fare_table.get("schema_version") != INTERCITY_RAIL_FARE_SCHEMA_VERSION:
        errors.append("unexpected intercity rail fare schema_version")
    if evidence_ledger.get("schema_version") != INTERCITY_RAIL_EVIDENCE_LEDGER_SCHEMA_VERSION:
        errors.append("unexpected intercity rail evidence ledger schema_version")
    if manifest.get("hash_strategy") != CANONICAL_JSON_SHA256_STRATEGY:
        errors.append("unexpected intercity snapshot hash_strategy")
    if manifest.get("real_time_api_allowed") is not False:
        errors.append("real_time_api_allowed must be false")
    if manifest.get("runtime_online_refresh_allowed") is not False:
        errors.append("runtime_online_refresh_allowed must be false")
    if manifest.get("real_time_price_claim_allowed") is not False:
        errors.append("real_time_price_claim_allowed must be false")
    if manifest.get("api_key_recorded") is not False:
        errors.append("api_key_recorded must be false")
    if fare_table.get("runtime_online_refresh_allowed") is not False:
        errors.append("fare table runtime_online_refresh_allowed must be false")
    if fare_table.get("real_time_price_claim_allowed") is not False:
        errors.append("fare table must disallow real-time price claims")
    if fare_table.get("api_key_recorded") is not False:
        errors.append("fare table api_key_recorded must be false")
    if evidence_ledger.get("runtime_online_refresh_allowed") is not False:
        errors.append("evidence ledger runtime_online_refresh_allowed must be false")
    if manifest.get("symmetric_route_lookup_allowed") is not True:
        errors.append("symmetric_route_lookup_allowed must be true")

    expected_file_paths = {
        "data/intercity_transport/rail_second_class_v1.json",
        "data/intercity_transport/evidence/rail_second_class_evidence_v1.json",
    }
    file_records = manifest.get("files")
    if not isinstance(file_records, list):
        errors.append("intercity manifest files must be a list")
        file_records = []
    actual_paths = {str(item.get("path") or "") for item in file_records if isinstance(item, dict)}
    if actual_paths != expected_file_paths:
        errors.append("intercity manifest must contain fare table and evidence ledger files")

    hash_input_records: List[Dict[str, Any]] = []
    for item in file_records:
        if not isinstance(item, dict):
            errors.append("intercity manifest file records must be objects")
            continue
        relative_path = str(item.get("path") or "")
        path = REPO_ROOT / relative_path
        if not path.exists():
            errors.append(f"intercity snapshot file not found: {relative_path}")
            continue
        if item.get("hash_strategy") != CANONICAL_JSON_SHA256_STRATEGY:
            errors.append(f"unexpected intercity file hash strategy: {relative_path}")
        actual_sha = canonical_json_file_sha256(path)
        if item.get("sha256") != actual_sha:
            errors.append(f"intercity snapshot file hash mismatch: {relative_path}")
        hash_input_records.append(
            {
                "kind": item.get("kind"),
                "path": relative_path,
                "sha256": item.get("sha256"),
                "hash_strategy": item.get("hash_strategy"),
            }
        )
        _assert_no_secret_markers(path)

    hash_input_records.sort(key=lambda row: (str(row["kind"]), str(row["path"])))
    combined_sha = hashlib.sha256(canonical_json_bytes(hash_input_records)).hexdigest()
    if manifest.get("combined_sha256") != combined_sha:
        errors.append("intercity snapshot combined hash mismatch")

    routes = fare_table.get("routes")
    if not isinstance(routes, list):
        errors.append("fare table routes must be a list")
        routes = []
    evidence_records = evidence_ledger.get("records")
    if not isinstance(evidence_records, list):
        errors.append("intercity evidence ledger records must be a list")
        evidence_records = []
    if manifest.get("route_count") != len(routes):
        errors.append("manifest route_count does not match fare table")
    if evidence_ledger.get("route_count") != len(evidence_records):
        errors.append("evidence ledger route_count does not match records")
    if evidence_ledger.get("route_count") != len(routes):
        errors.append("evidence ledger route_count does not match fare table")
    if fare_table.get("supported_origin_cities") != list(INTERCITY_SUPPORTED_ORIGIN_CITY_IDS):
        errors.append("fare table origin city set does not match Day8 rule")
    if fare_table.get("supported_destination_cities") != list(INTERCITY_SUPPORTED_DESTINATION_CITY_IDS):
        errors.append("fare table destination city set does not match Day8 rule")

    evidence_by_route_id = _evidence_records_by_route_id(evidence_records, errors)

    seen_route_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    for route in routes:
        if not isinstance(route, dict):
            errors.append("route records must be objects")
            continue
        route_id = str(route.get("route_id") or "")
        origin = str(route.get("origin") or "")
        destination = str(route.get("destination") or "")
        fare = _safe_float(route.get("one_way_fare_per_person_cny"), default=-1.0)
        if not route_id:
            errors.append("route_id is required")
        if route_id in seen_route_ids:
            errors.append(f"duplicate route_id: {route_id}")
        seen_route_ids.add(route_id)
        if origin not in INTERCITY_SUPPORTED_ORIGIN_CITY_IDS:
            errors.append(f"unsupported fare origin city: {origin}")
        if destination not in INTERCITY_SUPPORTED_DESTINATION_CITY_IDS:
            errors.append(f"unsupported fare destination city: {destination}")
        if (origin, destination) in seen_pairs:
            errors.append(f"duplicate fare route pair: {origin}->{destination}")
        seen_pairs.add((origin, destination))
        if fare <= 0:
            errors.append(f"fare must be positive: {route_id}")
        evidence = evidence_by_route_id.get(route_id)
        if not evidence:
            errors.append(f"missing intercity evidence record: {route_id}")
        else:
            _validate_route_evidence_record(
                route=route,
                evidence=evidence,
                errors=errors,
            )

    expected_pairs = {
        (origin, destination)
        for origin in INTERCITY_SUPPORTED_ORIGIN_CITY_IDS
        for destination in INTERCITY_SUPPORTED_DESTINATION_CITY_IDS
    }
    missing_pairs = sorted(expected_pairs - seen_pairs)
    if missing_pairs:
        formatted = ", ".join(f"{origin}->{destination}" for origin, destination in missing_pairs)
        errors.append(f"missing intercity fare pairs: {formatted}")

    missing_evidence_for_routes = sorted(set(seen_route_ids) - set(evidence_by_route_id))
    if missing_evidence_for_routes:
        errors.append(
            "missing evidence records for routes: "
            + ", ".join(missing_evidence_for_routes)
        )

    evidence_extra_routes = sorted(set(evidence_by_route_id) - set(seen_route_ids))
    if evidence_extra_routes:
        errors.append(
            "evidence records without fare routes: "
            + ", ".join(evidence_extra_routes)
        )

    evidence_summary = _evidence_review_summary(evidence_records)
    if manifest.get("evidence"):
        manifest_evidence = manifest.get("evidence")
        if not isinstance(manifest_evidence, dict):
            errors.append("manifest evidence must be an object")
        else:
            if manifest_evidence.get("pending_count") != evidence_summary["pending_count"]:
                errors.append("manifest evidence pending_count mismatch")
            if manifest_evidence.get("reviewed_count") != evidence_summary["reviewed_count"]:
                errors.append("manifest evidence reviewed_count mismatch")
            if bool(manifest_evidence.get("manual_review_complete")) != bool(
                evidence_summary["manual_review_complete"]
            ):
                errors.append("manifest evidence manual_review_complete mismatch")
    else:
        errors.append("manifest evidence summary is required")

    if errors:
        raise IntercityTransportSnapshotError("; ".join(errors))
    return {
        **manifest,
        "evidence": {
            **(manifest.get("evidence") if isinstance(manifest.get("evidence"), dict) else {}),
            **evidence_summary,
            "ledger_schema_version": evidence_ledger.get("schema_version"),
            "ledger_dataset_version": evidence_ledger.get("dataset_version"),
            "ledger_path": "data/intercity_transport/evidence/rail_second_class_evidence_v1.json",
        },
    }


def intercity_transport_snapshot_summary(*, compact: bool = False) -> Dict[str, Any]:
    manifest = validate_intercity_transport_snapshot()
    if not compact:
        return manifest
    return {
        "schema_version": manifest["schema_version"],
        "snapshot_id": manifest["snapshot_id"],
        "provider": manifest["provider"],
        "source_name": manifest["source_name"],
        "hash_strategy": manifest["hash_strategy"],
        "combined_sha256": manifest["combined_sha256"],
        "fare_snapshot_date": manifest["fare_snapshot_date"],
        "transport_mode": manifest["transport_mode"],
        "seat_class": manifest["seat_class"],
        "route_count": manifest["route_count"],
        "symmetric_route_lookup_allowed": manifest["symmetric_route_lookup_allowed"],
        "evidence_manual_review_required": (manifest.get("evidence") or {}).get(
            "manual_review_required"
        ),
        "evidence_manual_review_complete": (manifest.get("evidence") or {}).get(
            "manual_review_complete"
        ),
        "evidence_reviewed_count": (manifest.get("evidence") or {}).get("reviewed_count"),
        "evidence_pending_count": (manifest.get("evidence") or {}).get("pending_count"),
        "real_time_api_allowed": False,
        "runtime_online_refresh_allowed": False,
        "real_time_price_claim_allowed": False,
    }


def query_intercity_rail_snapshot(
    *,
    origin: Any = None,
    destination: Any,
    people_count: int = 1,
    snapshot_dir: Path = INTERCITY_TRANSPORT_DIR,
) -> Dict[str, Any]:
    """Return frozen round-trip second-class rail fare evidence.

    Unsupported or missing-origin routes do not fail the budget calculation.
    Instead they return an explicit zero-cost disclaimer so the local destination
    budget can still be computed without fabricating rail prices.
    """
    manifest = load_intercity_transport_snapshot_manifest(snapshot_dir)
    fare_table = load_intercity_rail_fare_table(snapshot_dir)
    evidence_ledger = load_intercity_rail_evidence_ledger(snapshot_dir)
    travelers = _bounded_people_count(people_count)
    origin_text = str(origin or "").strip()
    destination_text = str(destination or "").strip()
    origin_city_id = normalize_intercity_city_id(origin_text)
    destination_city_id = normalize_intercity_city_id(destination_text)
    base = _base_payload(
        manifest=manifest,
        origin=origin_text,
        destination=destination_text,
        origin_city_id=origin_city_id,
        destination_city_id=destination_city_id,
        people_count=travelers,
    )

    if not origin_text:
        return {
            **base,
            "status": "origin_missing",
            "route_supported": False,
            "intercity_transport_included": False,
            "mandatory_budget_disclaimer": True,
            "budget_scope": "destination_local_only",
            "one_way_fare_per_person_cny": None,
            "round_trip_fare_per_person_cny": 0.0,
            "total_intercity_transport_cost_cny": 0.0,
            "disclaimer": MISSING_ORIGIN_DISCLAIMER,
            "recommended_user_action": None,
        }

    if origin_city_id and destination_city_id and origin_city_id == destination_city_id:
        return {
            **base,
            "status": "same_city_no_intercity_required",
            "route_supported": True,
            "intercity_transport_included": False,
            "mandatory_budget_disclaimer": False,
            "budget_scope": "destination_local_only",
            "one_way_fare_per_person_cny": 0.0,
            "round_trip_fare_per_person_cny": 0.0,
            "total_intercity_transport_cost_cny": 0.0,
            "disclaimer": None,
            "recommended_user_action": None,
        }

    route, lookup_direction = _find_route_record(
        fare_table.get("routes") or [],
        origin_city_id=origin_city_id,
        destination_city_id=destination_city_id,
        symmetric_allowed=bool(manifest.get("symmetric_route_lookup_allowed")),
    )
    if not route:
        return {
            **base,
            "status": "route_not_supported",
            "route_supported": False,
            "intercity_transport_included": False,
            "mandatory_budget_disclaimer": True,
            "budget_scope": "local_only_route_uncovered",
            "one_way_fare_per_person_cny": None,
            "round_trip_fare_per_person_cny": 0.0,
            "total_intercity_transport_cost_cny": 0.0,
            "disclaimer": UNSUPPORTED_ROUTE_DISCLAIMER,
            "recommended_user_action": "\u8bf7\u524d\u5f80\u4e2d\u56fd\u94c1\u8def12306\u5b98\u7f51\u67e5\u8be2\u5b9e\u65f6\u7968\u4ef7\u3002",
        }

    one_way_fare = _safe_float(route.get("one_way_fare_per_person_cny"))
    evidence = _evidence_records_by_route_id(evidence_ledger.get("records") or {}).get(
        str(route.get("route_id") or "")
    )
    round_trip_per_person = round(one_way_fare * float(manifest.get("round_trip_multiplier") or 2), 2)
    total = round(round_trip_per_person * travelers, 2)
    return {
        **base,
        "status": "success",
        "route_supported": True,
        "intercity_transport_included": True,
        "mandatory_budget_disclaimer": False,
        "budget_scope": "local_plus_round_trip_intercity",
        "route_id": route.get("route_id"),
        "lookup_direction": lookup_direction,
        "lookup_origin": route.get("origin"),
        "lookup_destination": route.get("destination"),
        "one_way_fare_per_person_cny": one_way_fare,
        "round_trip_fare_per_person_cny": round_trip_per_person,
        "total_intercity_transport_cost_cny": total,
        "calculation_rule": "one_way_fare_per_person_cny * round_trip_multiplier * people_count",
        "fare_evidence": _public_evidence_payload(evidence),
        "disclaimer": None,
        "recommended_user_action": None,
    }


def _base_payload(
    *,
    manifest: Dict[str, Any],
    origin: str,
    destination: str,
    origin_city_id: Optional[str],
    destination_city_id: Optional[str],
    people_count: int,
) -> Dict[str, Any]:
    return {
        "provider": "manual_12306_snapshot",
        "offline": True,
        "source_name": manifest.get("source_name"),
        "snapshot_id": manifest.get("snapshot_id"),
        "snapshot_combined_sha256": manifest.get("combined_sha256"),
        "fare_snapshot_date": manifest.get("fare_snapshot_date"),
        "transport_mode": manifest.get("transport_mode"),
        "seat_class": manifest.get("seat_class"),
        "passenger_type": manifest.get("passenger_type"),
        "currency": manifest.get("currency") or "CNY",
        "fare_scope": manifest.get("fare_scope"),
        "round_trip_multiplier": manifest.get("round_trip_multiplier") or 2,
        "real_time_api_allowed": False,
        "runtime_online_refresh_allowed": False,
        "real_time_price_claim_allowed": False,
        "requested_origin": origin,
        "requested_destination": destination,
        "origin": origin_city_id,
        "destination": destination_city_id,
        "origin_label": intercity_city_label(origin_city_id or origin),
        "destination_label": intercity_city_label(destination_city_id or destination),
        "people_count": people_count,
        "evidence_manual_review_required": (manifest.get("evidence") or {}).get(
            "manual_review_required"
        ),
        "evidence_manual_review_complete": (manifest.get("evidence") or {}).get(
            "manual_review_complete"
        ),
    }


def _evidence_records_by_route_id(
    records: Any,
    errors: Optional[List[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    if not isinstance(records, list):
        if errors is not None:
            errors.append("evidence records must be a list")
        return {}
    by_route_id: Dict[str, Dict[str, Any]] = {}
    seen_evidence_ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            if errors is not None:
                errors.append("evidence records must be objects")
            continue
        route_id = str(record.get("route_id") or "")
        evidence_id = str(record.get("evidence_id") or "")
        if not route_id:
            if errors is not None:
                errors.append("evidence route_id is required")
            continue
        if not evidence_id and errors is not None:
            errors.append(f"evidence_id is required: {route_id}")
        if evidence_id in seen_evidence_ids and errors is not None:
            errors.append(f"duplicate evidence_id: {evidence_id}")
        if evidence_id:
            seen_evidence_ids.add(evidence_id)
        if route_id in by_route_id and errors is not None:
            errors.append(f"duplicate evidence route_id: {route_id}")
        by_route_id[route_id] = record
    return by_route_id


def _validate_route_evidence_record(
    *,
    route: Dict[str, Any],
    evidence: Dict[str, Any],
    errors: List[str],
) -> None:
    route_id = str(route.get("route_id") or "")
    comparable_fields = (
        "origin",
        "destination",
        "passenger_type",
        "transport_mode",
        "seat_class",
        "fare_scope",
    )
    for field in comparable_fields:
        route_value = route.get(field)
        if route_value is None:
            continue
        if evidence.get(field) != route_value:
            errors.append(f"evidence {field} mismatch: {route_id}")
    route_fare = _safe_float(route.get("one_way_fare_per_person_cny"), default=-1.0)
    evidence_fare = _safe_float(
        evidence.get("one_way_fare_per_person_cny"),
        default=-2.0,
    )
    if abs(route_fare - evidence_fare) > 1e-9:
        errors.append(f"evidence fare mismatch: {route_id}")
    required_nonempty = (
        "evidence_id",
        "departure_station",
        "arrival_station",
        "query_platform",
        "travel_date",
        "fare_selection_rule_id",
        "fare_selection_rule",
        "manual_review_status",
    )
    for field in required_nonempty:
        if evidence.get(field) in (None, "", [], {}):
            errors.append(f"evidence {field} is required: {route_id}")
    status = str(evidence.get("manual_review_status") or "")
    if status not in {"pending", "reviewed", "rejected"}:
        errors.append(f"unexpected evidence manual_review_status: {route_id}")
    if status == "reviewed":
        for field in (
            "query_date",
            "reviewed_by",
            "reviewed_at",
            "selected_train_no",
            "screenshot_file",
            "screenshot_sha256",
        ):
            if evidence.get(field) in (None, "", [], {}):
                errors.append(f"reviewed evidence {field} is required: {route_id}")
        _validate_reviewed_evidence_screenshot(
            route_id=route_id,
            screenshot_file=evidence.get("screenshot_file"),
            screenshot_sha256=evidence.get("screenshot_sha256"),
            errors=errors,
        )


def _validate_reviewed_evidence_screenshot(
    *,
    route_id: str,
    screenshot_file: Any,
    screenshot_sha256: Any,
    errors: List[str],
) -> None:
    if screenshot_file in (None, "", [], {}) or screenshot_sha256 in (None, "", [], {}):
        return
    relative_path = Path(str(screenshot_file))
    if relative_path.is_absolute():
        errors.append(f"reviewed evidence screenshot_file must be repo-relative: {route_id}")
        return
    screenshot_path = (REPO_ROOT / relative_path).resolve()
    try:
        screenshot_path.relative_to(REPO_ROOT.resolve())
    except ValueError:
        errors.append(f"reviewed evidence screenshot_file escapes repo: {route_id}")
        return
    if not screenshot_path.exists():
        errors.append(f"reviewed evidence screenshot_file missing: {route_id}")
        return
    actual_sha256 = _binary_file_sha256(screenshot_path)
    if actual_sha256 != str(screenshot_sha256):
        errors.append(f"reviewed evidence screenshot_sha256 mismatch: {route_id}")


def _binary_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _evidence_review_summary(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    status_counts: Dict[str, int] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        status = str(record.get("manual_review_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    pending_count = status_counts.get("pending", 0)
    reviewed_count = status_counts.get("reviewed", 0)
    rejected_count = status_counts.get("rejected", 0)
    return {
        "manual_review_required": True,
        "manual_review_complete": bool(records) and reviewed_count == len(records),
        "reviewed_count": reviewed_count,
        "pending_count": pending_count,
        "rejected_count": rejected_count,
        "status_counts": status_counts,
        "route_count": len(records),
    }


def _public_evidence_payload(evidence: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(evidence, dict):
        return None
    public_fields = (
        "evidence_id",
        "route_id",
        "departure_station",
        "arrival_station",
        "query_platform",
        "query_date",
        "planned_query_date",
        "travel_date",
        "fare_selection_rule_id",
        "selected_train_no",
        "screenshot_file",
        "screenshot_sha256",
        "manual_review_status",
        "reviewed_at",
    )
    return {
        field: evidence.get(field)
        for field in public_fields
        if field in evidence
    }


def _find_route_record(
    routes: List[Dict[str, Any]],
    *,
    origin_city_id: Optional[str],
    destination_city_id: Optional[str],
    symmetric_allowed: bool,
) -> tuple[Optional[Dict[str, Any]], str]:
    if not origin_city_id or not destination_city_id:
        return None, "unsupported_city"
    for route in routes:
        if route.get("origin") == origin_city_id and route.get("destination") == destination_city_id:
            return route, "direct"
    if symmetric_allowed:
        for route in routes:
            if route.get("origin") == destination_city_id and route.get("destination") == origin_city_id:
                return route, "reverse_symmetric"
    return None, "not_found"


def _bounded_people_count(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 1
    return max(1, min(parsed, 50))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise IntercityTransportSnapshotError(f"intercity snapshot file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise IntercityTransportSnapshotError(f"intercity snapshot file must be a JSON object: {path}")
    return payload


def _assert_no_secret_markers(path: Path) -> None:
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    lowered = text.casefold()
    forbidden_markers = (
        "api_key",
        "apikey",
        "authorization",
        "bearer ",
        "token",
        "password",
        "secret",
    )
    # The schema intentionally contains api_key_recorded=false, so allow that exact marker.
    lowered = lowered.replace('"api_key_recorded"', "")
    for marker in forbidden_markers:
        if marker in lowered:
            raise IntercityTransportSnapshotError(
                f"possible secret marker found in intercity snapshot file: {path.name}"
            )


@lru_cache(maxsize=1)
def get_intercity_rail_route_index() -> Dict[tuple[str, str], Dict[str, Any]]:
    table = load_intercity_rail_fare_table()
    return {
        (str(route.get("origin")), str(route.get("destination"))): dict(route)
        for route in table.get("routes") or []
        if isinstance(route, dict)
    }
