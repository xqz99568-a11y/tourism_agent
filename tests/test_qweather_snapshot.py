from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.fixed_data import CANONICAL_JSON_SHA256_STRATEGY, canonical_json_bytes
from app.core.qweather_snapshot import (
    QWEATHER_CITY_LOCATION_IDS,
    QWEATHER_SNAPSHOT_DIR,
    QWEATHER_VALIDATION_REPORT_SCHEMA_VERSION,
    load_qweather_validation_report,
    load_qweather_snapshot_manifest,
    query_qweather_snapshot,
    validate_qweather_snapshot,
)
from app.tools.research_tools import ResearchWeatherTool


def _snapshot_start() -> date:
    manifest = load_qweather_snapshot_manifest()
    return date.fromisoformat(manifest["forecast_start_date"])


def test_qweather_snapshot_has_five_raw_and_normalized_city_files() -> None:
    manifest = validate_qweather_snapshot()

    assert manifest["schema_version"] == "ctp-qweather-snapshot-manifest-v1"
    assert manifest["provider"] == "qweather"
    assert manifest["hash_strategy"] == CANONICAL_JSON_SHA256_STRATEGY
    assert manifest["location_resolution"] == "fixed_location_id"
    assert manifest["real_time_api_allowed"] is False
    assert manifest["runtime_online_refresh_allowed"] is False
    assert manifest["api_key_recorded"] is False
    assert manifest["cities"] == list(QWEATHER_CITY_LOCATION_IDS)
    assert manifest["forecast_horizon_days"] >= 7
    assert {item["kind"] for item in manifest["files"]} == {"raw", "normalized"}
    assert len(manifest["files"]) == len(QWEATHER_CITY_LOCATION_IDS) * 2

    for city_id in QWEATHER_CITY_LOCATION_IDS:
        assert (QWEATHER_SNAPSHOT_DIR / "raw" / f"{city_id}.json").exists()
        assert (QWEATHER_SNAPSHOT_DIR / "normalized" / f"{city_id}.json").exists()
    assert (QWEATHER_SNAPSHOT_DIR / "validation_report.json").exists()


def test_qweather_snapshot_validation_report_passes_strict_checks() -> None:
    manifest = validate_qweather_snapshot()
    report = load_qweather_validation_report()

    assert report["schema_version"] == QWEATHER_VALIDATION_REPORT_SCHEMA_VERSION
    assert report["status"] == "passed"
    assert report["snapshot_id"] == manifest["snapshot_id"]
    assert report["forecast_horizon_days"] == manifest["forecast_horizon_days"]
    assert report["runtime_online_refresh_allowed"] is False
    assert set(report["cities"]) == set(QWEATHER_CITY_LOCATION_IDS)
    for city_id, row in report["cities"].items():
        assert row["status"] == "passed"
        assert row["raw_record_count"] == manifest["forecast_horizon_days"]
        assert row["normalized_record_count"] == manifest["forecast_horizon_days"]
        assert row["raw_dates_continuous"] is True
        assert row["normalized_dates_continuous"] is True
        assert row["raw_normalized_dates_match"] is True
        assert row["raw_location_matches_manifest"] is True
        assert row["normalized_location_matches_manifest"] is True


def test_qweather_snapshot_manifest_hashes_match_files() -> None:
    manifest = load_qweather_snapshot_manifest()
    file_records = []
    for item in manifest["files"]:
        path = Path(item["path"])
        if not path.is_absolute():
            path = QWEATHER_SNAPSHOT_DIR.parents[2] / path
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        assert item["sha256"] == hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        file_records.append(
            {
                "kind": item["kind"],
                "city_id": item["city_id"],
                "path": item["path"],
                "sha256": item["sha256"],
                "hash_strategy": item["hash_strategy"],
            }
        )

    file_records.sort(key=lambda row: (row["kind"], row["city_id"], row["path"]))
    assert manifest["combined_sha256"] == hashlib.sha256(
        canonical_json_bytes(file_records)
    ).hexdigest()


def test_qweather_snapshot_query_returns_full_partial_and_out_of_range() -> None:
    start = _snapshot_start()

    full = query_qweather_snapshot(
        city="guilin",
        start_date=start.isoformat(),
        days=3,
    )
    assert full["coverage_status"] == "full"
    assert full["real_time_api_allowed"] is False
    assert full["runtime_online_refresh_allowed"] is False
    assert full["metadata"]["runtime_online_refresh_allowed"] is False
    assert [item["date"] for item in full["daily_weather"]] == [
        start.isoformat(),
        (start + timedelta(days=1)).isoformat(),
        (start + timedelta(days=2)).isoformat(),
    ]
    assert full["missing_dates"] == []

    partial_start = date.fromisoformat(load_qweather_snapshot_manifest()["forecast_end_date"])
    partial = query_qweather_snapshot(
        city="guilin",
        start_date=partial_start.isoformat(),
        days=3,
    )
    assert partial["coverage_status"] == "partial"
    assert partial["coverage_days"] == 1
    assert len(partial["missing_dates"]) == 2

    out_of_range = query_qweather_snapshot(
        city="guilin",
        start_date="2026-10-01",
        days=3,
    )
    assert out_of_range["coverage_status"] == "out_of_range"
    assert out_of_range["daily_weather"] == []
    assert out_of_range["missing_dates"] == [
        "2026-10-01",
        "2026-10-02",
        "2026-10-03",
    ]


def test_qweather_snapshot_query_requires_explicit_date_by_default() -> None:
    with pytest.raises(Exception, match="start_date is required"):
        query_qweather_snapshot(city="guilin", days=3)


def test_research_weather_tool_reads_qweather_snapshot_without_api_calls() -> None:
    start = _snapshot_start()
    result = asyncio.run(
        ResearchWeatherTool().execute(
            city="Guilin",
            date=start.isoformat(),
            days=2,
            scenario_type="rain",
        )
    )

    assert result.success is True
    assert result.api_calls == []
    assert result.data["status"] == "success"
    assert result.data["data"]["provider"] == "qweather_snapshot"
    assert result.data["data"]["coverage_status"] == "full"
    assert result.data["data"]["requested_scenario_type"] == "rain"
    assert result.data["data"]["scenario_selection"] == "qweather_frozen_snapshot_date_range"
    assert result.data["metadata"]["source_mode"] == "qweather_frozen_snapshot"
    assert result.data["metadata"]["real_time_api_allowed"] is False


def test_research_weather_tool_out_of_range_is_not_failed() -> None:
    result = asyncio.run(
        ResearchWeatherTool().execute(
            city="桂林",
            date="2026-10-01",
            days=3,
        )
    )

    assert result.success is True
    assert result.data["status"] == "success"
    assert result.data["data"]["coverage_status"] == "out_of_range"
    assert result.data["data"]["daily_weather"] == []
    assert result.data["data"]["coverage_days"] == 0
    assert result.data["data"]["missing_dates"] == [
        "2026-10-01",
        "2026-10-02",
        "2026-10-03",
    ]
