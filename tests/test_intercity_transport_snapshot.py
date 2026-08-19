from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.fixed_data import CANONICAL_JSON_SHA256_STRATEGY, canonical_json_bytes
from app.core.intercity_transport_snapshot import (
    INTERCITY_RAIL_EVIDENCE_LEDGER_FILE,
    INTERCITY_RAIL_FARE_FILE,
    INTERCITY_SUPPORTED_DESTINATION_CITY_IDS,
    INTERCITY_SUPPORTED_ORIGIN_CITY_IDS,
    INTERCITY_TRANSPORT_DIR,
    load_intercity_rail_evidence_ledger,
    load_intercity_transport_snapshot_manifest,
    query_intercity_rail_snapshot,
    validate_intercity_transport_snapshot,
)


def test_intercity_transport_snapshot_manifest_matches_frozen_fare_file() -> None:
    manifest = validate_intercity_transport_snapshot()

    assert manifest["schema_version"] == "ctp-intercity-transport-manifest-v1"
    assert manifest["hash_strategy"] == CANONICAL_JSON_SHA256_STRATEGY
    assert manifest["source_name"] == "China Railway 12306"
    assert manifest["fare_snapshot_date"] == "2026-08-13"
    assert manifest["transport_mode"] == "high_speed_or_d_train"
    assert manifest["seat_class"] == "second_class"
    assert manifest["symmetric_route_lookup_allowed"] is True
    assert manifest["real_time_api_allowed"] is False
    assert manifest["runtime_online_refresh_allowed"] is False
    assert manifest["real_time_price_claim_allowed"] is False
    assert manifest["api_key_recorded"] is False
    assert manifest["route_count"] == (
        len(INTERCITY_SUPPORTED_ORIGIN_CITY_IDS)
        * len(INTERCITY_SUPPORTED_DESTINATION_CITY_IDS)
    )
    assert manifest["evidence"]["ledger_schema_version"] == (
        "ctp-intercity-rail-evidence-ledger-v1"
    )
    assert manifest["evidence"]["manual_review_required"] is True
    assert manifest["evidence"]["manual_review_complete"] is True
    assert manifest["evidence"]["pending_count"] == 0
    assert manifest["evidence"]["reviewed_count"] == manifest["route_count"]
    assert (INTERCITY_TRANSPORT_DIR / "snapshot_manifest.json").exists()
    assert INTERCITY_RAIL_FARE_FILE.exists()
    assert INTERCITY_RAIL_EVIDENCE_LEDGER_FILE.exists()


def test_intercity_transport_snapshot_hashes_match_files() -> None:
    manifest = load_intercity_transport_snapshot_manifest()
    file_records = []
    for item in manifest["files"]:
        path = Path(item["path"])
        if not path.is_absolute():
            path = ROOT / path
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        assert item["sha256"] == hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        file_records.append(
            {
                "kind": item["kind"],
                "path": item["path"],
                "sha256": item["sha256"],
                "hash_strategy": item["hash_strategy"],
            }
        )

    file_records.sort(key=lambda row: (row["kind"], row["path"]))
    assert manifest["combined_sha256"] == hashlib.sha256(
        canonical_json_bytes(file_records)
    ).hexdigest()


def test_intercity_supported_route_adds_round_trip_second_class_cost() -> None:
    result = query_intercity_rail_snapshot(
        origin="guangzhou",
        destination="guilin",
        people_count=2,
    )

    assert result["status"] == "success"
    assert result["route_supported"] is True
    assert result["intercity_transport_included"] is True
    assert result["budget_scope"] == "local_plus_round_trip_intercity"
    assert result["one_way_fare_per_person_cny"] == 200.0
    assert result["round_trip_fare_per_person_cny"] == 400.0
    assert result["total_intercity_transport_cost_cny"] == 800.0
    assert result["real_time_api_allowed"] is False
    assert result["runtime_online_refresh_allowed"] is False
    assert result["real_time_price_claim_allowed"] is False
    assert result["fare_evidence"]["evidence_id"] == "rail_ev_010"
    assert result["fare_evidence"]["route_id"] == "guangzhou_guilin_rail_second_class"
    assert result["fare_evidence"]["manual_review_status"] == "reviewed"
    assert result["fare_evidence"]["travel_date"] == "2026-08-13"
    assert result["fare_evidence"]["selected_train_no"] == "G3722"
    screenshot_path = ROOT / result["fare_evidence"]["screenshot_file"]
    assert screenshot_path.exists()
    assert result["fare_evidence"]["screenshot_sha256"] == hashlib.sha256(
        screenshot_path.read_bytes()
    ).hexdigest()


def test_intercity_city_normalization_does_not_match_pinyin_substrings() -> None:
    result = query_intercity_rail_snapshot(
        origin="zhengzhou",
        destination="xian",
        people_count=2,
    )

    assert result["status"] == "success"
    assert result["origin"] == "zhengzhou"
    assert result["route_id"] == "zhengzhou_xian_rail_second_class"
    assert result["one_way_fare_per_person_cny"] == 221.0
    assert result["total_intercity_transport_cost_cny"] == 884.0
    assert result["fare_evidence"]["selected_train_no"] == "G2111"


def test_intercity_evidence_ledger_has_one_reviewed_record_per_route() -> None:
    manifest = validate_intercity_transport_snapshot()
    ledger = load_intercity_rail_evidence_ledger()
    records = ledger["records"]

    assert ledger["manual_review_required"] is True
    assert ledger["manual_review_complete"] is True
    assert ledger["route_count"] == 50
    assert ledger["pending_count"] == 0
    assert ledger["reviewed_count"] == 50
    assert len(records) == manifest["route_count"]
    assert len({record["route_id"] for record in records}) == manifest["route_count"]
    assert len({record["evidence_id"] for record in records}) == manifest["route_count"]
    assert all(record["manual_review_status"] == "reviewed" for record in records)
    assert all(record["selected_train_no"] for record in records)
    assert all(record["screenshot_file"] for record in records)
    assert all(record["screenshot_sha256"] for record in records)


def test_intercity_route_lookup_is_symmetric_when_reverse_pair_is_requested() -> None:
    result = query_intercity_rail_snapshot(
        origin="beijing",
        destination="shanghai",
        people_count=1,
    )

    assert result["status"] == "success"
    assert result["lookup_direction"] == "reverse_symmetric"
    assert result["lookup_origin"] == "shanghai"
    assert result["lookup_destination"] == "beijing"
    assert result["one_way_fare_per_person_cny"] == 661.0
    assert result["total_intercity_transport_cost_cny"] == 1322.0


def test_intercity_missing_origin_keeps_local_only_budget_scope() -> None:
    result = query_intercity_rail_snapshot(
        origin=None,
        destination="guilin",
        people_count=2,
    )

    assert result["status"] == "origin_missing"
    assert result["intercity_transport_included"] is False
    assert result["total_intercity_transport_cost_cny"] == 0.0
    assert result["budget_scope"] == "destination_local_only"
    assert result["runtime_online_refresh_allowed"] is False
    assert result["real_time_price_claim_allowed"] is False
    assert result["mandatory_budget_disclaimer"] is True
    assert result["disclaimer"]


def test_intercity_unsupported_route_does_not_guess_or_refresh_price() -> None:
    result = query_intercity_rail_snapshot(
        origin="lhasa",
        destination="guilin",
        people_count=2,
    )

    assert result["status"] == "route_not_supported"
    assert result["route_supported"] is False
    assert result["intercity_transport_included"] is False
    assert result["total_intercity_transport_cost_cny"] == 0.0
    assert result["budget_scope"] == "local_only_route_uncovered"
    assert result["runtime_online_refresh_allowed"] is False
    assert result["real_time_price_claim_allowed"] is False
    assert result["mandatory_budget_disclaimer"] is True
    assert result["disclaimer"]
    assert "12306" in result["recommended_user_action"]
