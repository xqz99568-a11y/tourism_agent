"""Frozen QWeather snapshot access for formal tourism experiments.

The module is intentionally offline-only.  It never calls QWeather at runtime;
the online collection step is implemented in ``experiments/freeze_qweather_snapshot.py``.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.core.fixed_data import (
    CANONICAL_JSON_SHA256_STRATEGY,
    DATA_ROOT,
    REPO_ROOT,
    canonical_json_bytes,
    canonical_json_file_sha256,
)


QWEATHER_SNAPSHOT_SCHEMA_VERSION = "ctp-qweather-snapshot-manifest-v1"
QWEATHER_NORMALIZED_CITY_SCHEMA_VERSION = "ctp-qweather-normalized-city-v1"
QWEATHER_RAW_CITY_SCHEMA_VERSION = "ctp-qweather-raw-city-v1"
QWEATHER_SNAPSHOT_DIR = DATA_ROOT / "weather_snapshot" / "qweather_v1"
QWEATHER_MAX_QUERY_DAYS = 30
QWEATHER_VALIDATION_REPORT_SCHEMA_VERSION = "ctp-qweather-validation-report-v1"
QWEATHER_DEFAULT_WEATHER_QUERY_DAYS = 7

QWEATHER_CITY_LOCATION_IDS: Dict[str, str] = {
    "beijing": "101010100",
    "hangzhou": "101210101",
    "xian": "101110101",
    "shenzhen": "101280601",
    "guilin": "101300501",
}

QWEATHER_CITY_NAMES: Dict[str, str] = {
    "beijing": "北京",
    "hangzhou": "杭州",
    "xian": "西安",
    "shenzhen": "深圳",
    "guilin": "桂林",
}

QWEATHER_CITY_ALIASES: Dict[str, tuple[str, ...]] = {
    "beijing": ("beijing", "bj", "北京", "北京市"),
    "hangzhou": ("hangzhou", "hz", "杭州", "杭州市"),
    "xian": ("xian", "xi'an", "xa", "西安", "西安市"),
    "shenzhen": ("shenzhen", "sz", "深圳", "深圳市"),
    "guilin": ("guilin", "gl", "桂林", "桂林市"),
}


class QWeatherSnapshotError(ValueError):
    """Raised when a frozen QWeather snapshot is missing or invalid."""


def normalize_qweather_city_id(city: Any) -> Optional[str]:
    text = str(city or "").strip()
    if not text:
        return None
    lowered = text.casefold()
    for city_id, aliases in QWEATHER_CITY_ALIASES.items():
        for alias in aliases:
            alias_lower = alias.casefold()
            if lowered == alias_lower or alias_lower in lowered or alias in text:
                return city_id
    return None


def load_qweather_snapshot_manifest(
    snapshot_dir: Path = QWEATHER_SNAPSHOT_DIR,
) -> Dict[str, Any]:
    return _read_json(snapshot_dir / "snapshot_manifest.json")


def load_qweather_validation_report(
    snapshot_dir: Path = QWEATHER_SNAPSHOT_DIR,
) -> Dict[str, Any]:
    return _read_json(snapshot_dir / "validation_report.json")


@lru_cache(maxsize=16)
def _cached_city_snapshot(snapshot_dir_text: str, city_id: str) -> Dict[str, Any]:
    return _read_json(Path(snapshot_dir_text) / "normalized" / f"{city_id}.json")


def load_qweather_city_snapshot(
    city: Any,
    snapshot_dir: Path = QWEATHER_SNAPSHOT_DIR,
) -> Dict[str, Any]:
    city_id = normalize_qweather_city_id(city)
    if not city_id:
        raise QWeatherSnapshotError(f"unsupported qweather snapshot city: {city}")
    return _cached_city_snapshot(str(snapshot_dir.resolve()), city_id)


def validate_qweather_snapshot(
    snapshot_dir: Path = QWEATHER_SNAPSHOT_DIR,
) -> Dict[str, Any]:
    manifest_path = snapshot_dir / "snapshot_manifest.json"
    if not manifest_path.exists():
        raise QWeatherSnapshotError(f"qweather snapshot manifest not found: {manifest_path}")
    _assert_no_secret_markers(manifest_path)
    manifest = load_qweather_snapshot_manifest(snapshot_dir)

    errors: List[str] = []
    if manifest.get("schema_version") != QWEATHER_SNAPSHOT_SCHEMA_VERSION:
        errors.append("unexpected qweather snapshot schema_version")
    if manifest.get("provider") != "qweather":
        errors.append("provider must be qweather")
    if manifest.get("hash_strategy") != CANONICAL_JSON_SHA256_STRATEGY:
        errors.append("unexpected hash_strategy")
    if manifest.get("real_time_api_allowed") is not False:
        errors.append("real_time_api_allowed must be false")
    if manifest.get("runtime_online_refresh_allowed") is not False:
        errors.append("runtime_online_refresh_allowed must be false")
    if manifest.get("api_key_recorded") is not False:
        errors.append("api_key_recorded must be false")
    if manifest.get("location_resolution") != "fixed_location_id":
        errors.append("location_resolution must be fixed_location_id")

    expected_cities = list(QWEATHER_CITY_LOCATION_IDS)
    if manifest.get("cities") != expected_cities:
        errors.append("cities do not match the five-city experiment set")

    file_records = manifest.get("files")
    if not isinstance(file_records, list):
        errors.append("manifest files must be a list")
        file_records = []

    expected_paths = {
        f"data/weather_snapshot/qweather_v1/raw/{city_id}.json"
        for city_id in expected_cities
    } | {
        f"data/weather_snapshot/qweather_v1/normalized/{city_id}.json"
        for city_id in expected_cities
    }
    actual_paths = {str(item.get("path") or "") for item in file_records if isinstance(item, dict)}
    missing_paths = sorted(expected_paths - actual_paths)
    unexpected_paths = sorted(actual_paths - expected_paths)
    if missing_paths:
        errors.append(f"missing qweather snapshot files: {', '.join(missing_paths)}")
    if unexpected_paths:
        errors.append(f"unexpected qweather snapshot files: {', '.join(unexpected_paths)}")

    raw_records_by_city: Dict[str, Dict[str, Any]] = {}
    normalized_records_by_city: Dict[str, Dict[str, Any]] = {}
    hash_input_records: List[Dict[str, Any]] = []
    for item in file_records:
        if not isinstance(item, dict):
            errors.append("manifest file records must be objects")
            continue
        relative_path = str(item.get("path") or "")
        path = REPO_ROOT / relative_path
        if not path.exists():
            errors.append(f"snapshot file not found: {relative_path}")
            continue
        if item.get("hash_strategy") != CANONICAL_JSON_SHA256_STRATEGY:
            errors.append(f"unexpected file hash strategy: {relative_path}")
        actual_sha = canonical_json_file_sha256(path)
        if item.get("sha256") != actual_sha:
            errors.append(f"snapshot file hash mismatch: {relative_path}")
        hash_input_records.append(
            {
                "kind": item.get("kind"),
                "city_id": item.get("city_id"),
                "path": relative_path,
                "sha256": item.get("sha256"),
                "hash_strategy": item.get("hash_strategy"),
            }
        )
        document = _read_json(path)
        if item.get("kind") == "raw":
            raw_records_by_city[str(item.get("city_id") or "")] = document
        if item.get("kind") == "normalized":
            normalized_records_by_city[str(item.get("city_id") or "")] = document
        _assert_no_secret_markers(path)

    hash_input_records.sort(key=lambda row: (str(row["kind"]), str(row["city_id"]), str(row["path"])))
    combined_sha = hashlib.sha256(canonical_json_bytes(hash_input_records)).hexdigest()
    if manifest.get("combined_sha256") != combined_sha:
        errors.append("qweather snapshot combined hash mismatch")

    horizon_days = _positive_int(manifest.get("forecast_horizon_days"))
    if horizon_days is None:
        errors.append("forecast_horizon_days must be a positive integer")
        horizon_days = 0
    elif horizon_days > QWEATHER_MAX_QUERY_DAYS:
        errors.append(f"forecast_horizon_days exceeds supported maximum: {horizon_days}")

    expected_start = _parse_date(manifest.get("forecast_start_date"))
    expected_end = _parse_date(manifest.get("forecast_end_date"))
    if horizon_days and expected_start and expected_end:
        if (expected_end - expected_start).days + 1 != horizon_days:
            errors.append("manifest forecast date range length does not match forecast_horizon_days")
    else:
        errors.append("manifest forecast_start_date/forecast_end_date must be valid dates")

    for city_id in expected_cities:
        raw_document = raw_records_by_city.get(city_id)
        normalized_document = normalized_records_by_city.get(city_id)
        if not raw_document:
            errors.append(f"missing raw document for city: {city_id}")
            continue
        if not normalized_document:
            errors.append(f"missing normalized document for city: {city_id}")
            continue

        city_errors = _validate_city_snapshot_pair(
            manifest=manifest,
            city_id=city_id,
            raw_document=raw_document,
            normalized_document=normalized_document,
            expected_horizon_days=horizon_days,
        )
        errors.extend(city_errors)

    validation_report_path = snapshot_dir / "validation_report.json"
    if not validation_report_path.exists():
        errors.append("qweather validation_report.json is required")
    else:
        _assert_no_secret_markers(validation_report_path)
        try:
            validation_report = load_qweather_validation_report(snapshot_dir)
        except Exception as exc:
            errors.append(f"qweather validation_report.json is invalid: {exc}")
        else:
            if validation_report.get("schema_version") != QWEATHER_VALIDATION_REPORT_SCHEMA_VERSION:
                errors.append("unexpected qweather validation report schema_version")
            if validation_report.get("status") != "passed":
                errors.append("qweather validation report status must be passed")
            if validation_report.get("snapshot_id") != manifest.get("snapshot_id"):
                errors.append("qweather validation report snapshot_id mismatch")
            if validation_report.get("forecast_horizon_days") != manifest.get("forecast_horizon_days"):
                errors.append("qweather validation report forecast_horizon_days mismatch")
            if validation_report.get("forecast_start_date") != manifest.get("forecast_start_date"):
                errors.append("qweather validation report forecast_start_date mismatch")
            if validation_report.get("forecast_end_date") != manifest.get("forecast_end_date"):
                errors.append("qweather validation report forecast_end_date mismatch")
            if validation_report.get("runtime_online_refresh_allowed") is not False:
                errors.append("qweather validation report runtime_online_refresh_allowed must be false")
            report_cities = validation_report.get("cities")
            if not isinstance(report_cities, dict):
                errors.append("qweather validation report cities must be an object")
            else:
                for city_id in expected_cities:
                    row = report_cities.get(city_id)
                    if not isinstance(row, dict):
                        errors.append(f"qweather validation report missing city: {city_id}")
                        continue
                    if row.get("status") != "passed":
                        errors.append(f"qweather validation report city did not pass: {city_id}")
                    if row.get("raw_record_count") != horizon_days:
                        errors.append(f"qweather validation report raw count mismatch: {city_id}")
                    if row.get("normalized_record_count") != horizon_days:
                        errors.append(f"qweather validation report normalized count mismatch: {city_id}")
                    if row.get("location_id") != QWEATHER_CITY_LOCATION_IDS[city_id]:
                        errors.append(f"qweather validation report location_id mismatch: {city_id}")

    if errors:
        raise QWeatherSnapshotError("; ".join(errors))
    return manifest


def build_qweather_validation_report(
    snapshot_dir: Path = QWEATHER_SNAPSHOT_DIR,
    *,
    manifest: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    manifest = manifest or load_qweather_snapshot_manifest(snapshot_dir)
    expected_cities = list(QWEATHER_CITY_LOCATION_IDS)
    horizon_days = _positive_int(manifest.get("forecast_horizon_days")) or 0
    city_reports: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []

    for city_id in expected_cities:
        raw_path = snapshot_dir / "raw" / f"{city_id}.json"
        normalized_path = snapshot_dir / "normalized" / f"{city_id}.json"
        city_errors: List[str] = []
        raw_document: Dict[str, Any] = {}
        normalized_document: Dict[str, Any] = {}
        try:
            raw_document = _read_json(raw_path)
        except Exception as exc:
            city_errors.append(f"raw read failed: {exc}")
        try:
            normalized_document = _read_json(normalized_path)
        except Exception as exc:
            city_errors.append(f"normalized read failed: {exc}")

        raw_dates = _raw_dates(raw_document)
        normalized_dates = _normalized_dates(normalized_document)
        raw_location_id = str(raw_document.get("location_id") or "")
        metadata = normalized_document.get("metadata") if isinstance(normalized_document.get("metadata"), dict) else {}
        normalized_location_id = str(metadata.get("location_id") or "")
        if raw_document and normalized_document:
            city_errors.extend(
                _validate_city_snapshot_pair(
                    manifest=manifest,
                    city_id=city_id,
                    raw_document=raw_document,
                    normalized_document=normalized_document,
                    expected_horizon_days=horizon_days,
                )
            )
        city_reports[city_id] = {
            "status": "passed" if not city_errors else "failed",
            "city_id": city_id,
            "location_id": QWEATHER_CITY_LOCATION_IDS[city_id],
            "raw_location_id": raw_location_id,
            "normalized_location_id": normalized_location_id,
            "raw_record_count": len(raw_dates),
            "normalized_record_count": len(normalized_dates),
            "raw_dates_continuous": _dates_are_continuous(raw_dates),
            "normalized_dates_continuous": _dates_are_continuous(normalized_dates),
            "raw_normalized_dates_match": raw_dates == normalized_dates,
            "raw_city_matches_manifest": raw_document.get("city_id") == city_id,
            "normalized_city_matches_manifest": metadata.get("city_id") == city_id,
            "raw_location_matches_manifest": raw_location_id == QWEATHER_CITY_LOCATION_IDS[city_id],
            "normalized_location_matches_manifest": normalized_location_id == QWEATHER_CITY_LOCATION_IDS[city_id],
            "forecast_start_date": normalized_dates[0] if normalized_dates else "",
            "forecast_end_date": normalized_dates[-1] if normalized_dates else "",
            "errors": city_errors,
        }
        errors.extend(f"{city_id}: {error}" for error in city_errors)

    return {
        "schema_version": QWEATHER_VALIDATION_REPORT_SCHEMA_VERSION,
        "status": "passed" if not errors else "failed",
        "provider": "qweather",
        "snapshot_id": manifest.get("snapshot_id"),
        "forecast_endpoint": manifest.get("forecast_endpoint"),
        "forecast_horizon_days": manifest.get("forecast_horizon_days"),
        "forecast_start_date": manifest.get("forecast_start_date"),
        "forecast_end_date": manifest.get("forecast_end_date"),
        "runtime_online_refresh_allowed": False,
        "cities": city_reports,
        "errors": errors,
        "validation_rules": [
            "five_city_raw_and_normalized_files_required",
            "raw_and_normalized_location_id_must_match_fixed_location_id",
            "record_count_must_equal_selected_forecast_horizon",
            "dates_must_be_continuous",
            "raw_and_normalized_dates_must_match",
            "runtime_must_not_call_realtime_weather_api",
        ],
    }


def qweather_snapshot_summary(*, compact: bool = False) -> Dict[str, Any]:
    manifest = validate_qweather_snapshot()
    if not compact:
        return manifest
    return {
        "schema_version": manifest["schema_version"],
        "provider": manifest["provider"],
        "snapshot_id": manifest["snapshot_id"],
        "hash_strategy": manifest["hash_strategy"],
        "combined_sha256": manifest["combined_sha256"],
        "forecast_endpoint": manifest["forecast_endpoint"],
        "forecast_horizon_days": manifest["forecast_horizon_days"],
        "forecast_start_date": manifest["forecast_start_date"],
        "forecast_end_date": manifest["forecast_end_date"],
        "cities": manifest["cities"],
        "real_time_api_allowed": False,
        "runtime_online_refresh_allowed": False,
    }


def query_qweather_snapshot(
    *,
    city: Any,
    start_date: Optional[str] = None,
    days: int = 3,
    snapshot_dir: Path = QWEATHER_SNAPSHOT_DIR,
    default_to_snapshot_start: bool = False,
) -> Dict[str, Any]:
    city_id = normalize_qweather_city_id(city)
    if not city_id:
        raise QWeatherSnapshotError(f"unsupported qweather snapshot city: {city}")

    requested_days = _bounded_days(days)
    manifest = load_qweather_snapshot_manifest(snapshot_dir)
    document = load_qweather_city_snapshot(city_id, snapshot_dir)
    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    forecast_rows = [
        item for item in document.get("daily_forecasts") or [] if isinstance(item, dict)
    ]
    forecast_by_date = {str(item.get("date")): item for item in forecast_rows if item.get("date")}

    date_defaulted = False
    parsed_start = _parse_date(start_date)
    if parsed_start is None:
        if not default_to_snapshot_start:
            raise QWeatherSnapshotError(
                "start_date is required unless default_to_snapshot_start is explicitly enabled"
            )
        parsed_start = _parse_date(metadata.get("forecast_start_date") or manifest.get("forecast_start_date"))
        date_defaulted = True
    if parsed_start is None:
        raise QWeatherSnapshotError("qweather snapshot has no valid forecast_start_date")

    requested_dates = [
        (parsed_start + timedelta(days=offset)).isoformat()
        for offset in range(requested_days)
    ]
    daily_weather: List[Dict[str, Any]] = []
    missing_dates: List[str] = []
    for request_index, requested_date in enumerate(requested_dates, start=1):
        source = forecast_by_date.get(requested_date)
        if not source:
            missing_dates.append(requested_date)
            continue
        daily_weather.append(_format_snapshot_day(source, request_index=request_index))

    if len(daily_weather) == requested_days:
        coverage_status = "full"
    elif daily_weather:
        coverage_status = "partial"
    else:
        coverage_status = "out_of_range"

    risk_level = _overall_risk_level(daily_weather, coverage_status=coverage_status)
    scenario_type = _overall_weather_type(daily_weather, coverage_status=coverage_status)
    planning_constraints = _planning_constraints(
        daily_weather,
        coverage_status=coverage_status,
        missing_dates=missing_dates,
    )
    snapshot_id = str(manifest.get("snapshot_id") or metadata.get("snapshot_id") or "")
    return {
        "provider": "qweather_snapshot",
        "offline": True,
        "available": bool(daily_weather),
        "degraded": coverage_status != "full",
        "current_available": False,
        "real_time_api_allowed": False,
        "runtime_online_refresh_allowed": False,
        "forecast_available": bool(daily_weather),
        "forecast_type": f"qweather_{manifest.get('forecast_horizon_days')}d_frozen",
        "destination": metadata.get("city_name") or QWEATHER_CITY_NAMES[city_id],
        "city": metadata.get("city_name") or QWEATHER_CITY_NAMES[city_id],
        "city_id": city_id,
        "location_id": metadata.get("location_id") or QWEATHER_CITY_LOCATION_IDS[city_id],
        "date": parsed_start.isoformat(),
        "start_date": parsed_start.isoformat(),
        "end_date": (parsed_start + timedelta(days=requested_days - 1)).isoformat(),
        "date_defaulted_to_snapshot_start": date_defaulted,
        "requested_days": requested_days,
        "coverage_days": len(daily_weather),
        "coverage_status": coverage_status,
        "covered_dates": [item["date"] for item in daily_weather],
        "missing_dates": missing_dates,
        "snapshot_forecast_start_date": metadata.get("forecast_start_date") or manifest.get("forecast_start_date"),
        "snapshot_forecast_end_date": metadata.get("forecast_end_date") or manifest.get("forecast_end_date"),
        "forecast_start_date": metadata.get("forecast_start_date") or manifest.get("forecast_start_date"),
        "forecast_end_date": metadata.get("forecast_end_date") or manifest.get("forecast_end_date"),
        "daily_weather": daily_weather,
        "daily_forecasts": daily_weather,
        "forecast": daily_weather,
        "weather_type": scenario_type,
        "scenario_type": scenario_type,
        "risk_level": risk_level,
        "risk_tags": _ordered_unique(
            tag
            for item in daily_weather
            for tag in item.get("risk_tags", [])
        ),
        "planning_constraints": planning_constraints,
        "weather_adjustment_required": bool(planning_constraints.get("dynamic_adjustment_required")),
        "warnings": _coverage_warnings(coverage_status, missing_dates),
        "applied_rules": [
            "qweather_frozen_snapshot",
            "fixed_location_id",
            "date_range_coverage",
        ],
        "scenario_selection": "qweather_frozen_snapshot_date_range",
        "dataset_version": metadata.get("dataset_version"),
        "source_file_id": metadata.get("file_id"),
        "snapshot_id": snapshot_id,
        "snapshot_combined_sha256": manifest.get("combined_sha256"),
        "metadata": {
            "offline": True,
            "source_mode": "qweather_frozen_snapshot",
            "dataset_version": metadata.get("dataset_version"),
            "source_file_id": metadata.get("file_id"),
            "snapshot_id": snapshot_id,
            "snapshot_manifest_path": "data/weather_snapshot/qweather_v1/snapshot_manifest.json",
            "snapshot_combined_sha256": manifest.get("combined_sha256"),
            "forecast_endpoint": manifest.get("forecast_endpoint"),
            "forecast_horizon_days": manifest.get("forecast_horizon_days"),
            "coverage_status": coverage_status,
            "real_time_api_allowed": False,
            "runtime_online_refresh_allowed": False,
        },
    }


def normalize_qweather_daily_item(
    item: Dict[str, Any],
    *,
    day_index: int,
    city_id: str,
    snapshot_id: str,
    source_endpoint: str,
) -> Dict[str, Any]:
    max_temp = _coerce_int(item.get("tempMax"))
    min_temp = _coerce_int(item.get("tempMin"))
    precipitation_mm = _coerce_float(item.get("precip"))
    precipitation_probability = _coerce_int(item.get("pop"))
    wind_scale_day = _coerce_int(item.get("windScaleDay"))
    wind_speed_day = _coerce_float(item.get("windSpeedDay"))
    humidity = _coerce_int(item.get("humidity"))
    uv_index = _coerce_int(item.get("uvIndex"))
    day_weather = str(item.get("textDay") or "").strip()
    night_weather = str(item.get("textNight") or "").strip()
    risk_tags = _daily_risk_tags(
        day_weather=day_weather,
        night_weather=night_weather,
        max_temp=max_temp,
        min_temp=min_temp,
        precipitation_mm=precipitation_mm,
        precipitation_probability=precipitation_probability,
        wind_scale_day=wind_scale_day,
        wind_speed_day=wind_speed_day,
    )
    risk_level = _daily_risk_level(risk_tags)
    return {
        "date": str(item.get("fxDate") or "").strip(),
        "day_index": day_index,
        "snapshot_day_index": day_index,
        "state": _weather_state(day_weather, night_weather, risk_tags),
        "weather": day_weather,
        "day_weather": day_weather,
        "night_weather": night_weather,
        "temperature_min_c": min_temp,
        "temperature_max_c": max_temp,
        "precipitation_mm": precipitation_mm,
        "precipitation_probability": precipitation_probability,
        "wind_direction_day": item.get("windDirDay"),
        "wind_scale_day": wind_scale_day,
        "wind_speed_day_kmh": wind_speed_day,
        "humidity_percent": humidity,
        "uv_index": uv_index,
        "risk_level": risk_level,
        "risk_tags": risk_tags,
        "suitable_periods": _suitable_periods(risk_tags),
        "avoid_periods": _avoid_periods(risk_tags),
        "evidence": {
            "provider": "qweather",
            "source_mode": "qweather_frozen_snapshot",
            "city_id": city_id,
            "snapshot_id": snapshot_id,
            "source_endpoint": source_endpoint,
            "offline": True,
            "real_time_api_allowed": False,
        },
        "provider_raw_fields": {
            "fxDate": item.get("fxDate"),
            "tempMin": item.get("tempMin"),
            "tempMax": item.get("tempMax"),
            "textDay": item.get("textDay"),
            "textNight": item.get("textNight"),
            "windDirDay": item.get("windDirDay"),
            "windScaleDay": item.get("windScaleDay"),
            "windSpeedDay": item.get("windSpeedDay"),
            "humidity": item.get("humidity"),
            "precip": item.get("precip"),
            "pop": item.get("pop"),
            "uvIndex": item.get("uvIndex"),
        },
    }


def _format_snapshot_day(source: Dict[str, Any], *, request_index: int) -> Dict[str, Any]:
    item = dict(source)
    item["snapshot_day_index"] = source.get("snapshot_day_index") or source.get("day_index")
    item["day_index"] = request_index
    item["request_day_index"] = request_index
    return item


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise QWeatherSnapshotError(f"qweather snapshot file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise QWeatherSnapshotError(f"qweather snapshot file must contain object: {path}")
    return payload


def _assert_no_secret_markers(path: Path) -> None:
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    forbidden = ("QWEATHER_API_KEY", "X-QW-Api-Key", "Authorization", "Bearer ")
    found = [marker for marker in forbidden if marker in text]
    if found:
        raise QWeatherSnapshotError(f"secret marker found in snapshot file {path}: {', '.join(found)}")


def _validate_city_snapshot_pair(
    *,
    manifest: Dict[str, Any],
    city_id: str,
    raw_document: Dict[str, Any],
    normalized_document: Dict[str, Any],
    expected_horizon_days: int,
) -> List[str]:
    errors: List[str] = []
    expected_location_id = QWEATHER_CITY_LOCATION_IDS[city_id]
    expected_endpoint = str(manifest.get("forecast_endpoint") or "")
    expected_start = str(manifest.get("forecast_start_date") or "")
    expected_end = str(manifest.get("forecast_end_date") or "")

    if raw_document.get("schema_version") != QWEATHER_RAW_CITY_SCHEMA_VERSION:
        errors.append(f"unexpected raw schema for {city_id}")
    if raw_document.get("provider") != "qweather":
        errors.append(f"raw provider must be qweather for {city_id}")
    if raw_document.get("city_id") != city_id:
        errors.append(f"raw city_id mismatch for {city_id}")
    if str(raw_document.get("location_id") or "") != expected_location_id:
        errors.append(f"raw location_id mismatch for {city_id}")
    request = raw_document.get("request") if isinstance(raw_document.get("request"), dict) else {}
    request_params = request.get("params") if isinstance(request.get("params"), dict) else {}
    if str(request.get("endpoint") or "") != expected_endpoint:
        errors.append(f"raw endpoint mismatch for {city_id}")
    if str(request_params.get("location") or "") != expected_location_id:
        errors.append(f"raw request location mismatch for {city_id}")

    metadata = normalized_document.get("metadata") if isinstance(normalized_document.get("metadata"), dict) else {}
    if metadata.get("schema_version") != QWEATHER_NORMALIZED_CITY_SCHEMA_VERSION:
        errors.append(f"unexpected normalized schema for {city_id}")
    if metadata.get("provider") != "qweather":
        errors.append(f"normalized provider must be qweather for {city_id}")
    if metadata.get("city_id") != city_id:
        errors.append(f"normalized city_id mismatch for {city_id}")
    if str(metadata.get("location_id") or "") != expected_location_id:
        errors.append(f"normalized location_id mismatch for {city_id}")
    if metadata.get("real_time_api_allowed") is not False:
        errors.append(f"normalized city allows real-time api: {city_id}")
    if metadata.get("api_key_recorded") is not False:
        errors.append(f"normalized city records api key: {city_id}")
    if str(metadata.get("forecast_endpoint") or "") != expected_endpoint:
        errors.append(f"normalized endpoint mismatch for {city_id}")

    raw_dates = _raw_dates(raw_document)
    normalized_dates = _normalized_dates(normalized_document)
    if len(raw_dates) != expected_horizon_days:
        errors.append(f"raw record count mismatch for {city_id}: expected {expected_horizon_days}, got {len(raw_dates)}")
    if len(normalized_dates) != expected_horizon_days:
        errors.append(
            f"normalized record count mismatch for {city_id}: expected {expected_horizon_days}, got {len(normalized_dates)}"
        )
    if raw_dates != normalized_dates:
        errors.append(f"raw and normalized dates do not match for {city_id}")
    if raw_dates and not _dates_are_continuous(raw_dates):
        errors.append(f"raw dates are not continuous for {city_id}")
    if normalized_dates and not _dates_are_continuous(normalized_dates):
        errors.append(f"normalized dates are not continuous for {city_id}")
    if expected_horizon_days and normalized_dates:
        if normalized_dates[0] != expected_start:
            errors.append(f"forecast_start_date mismatch for {city_id}")
        if normalized_dates[-1] != expected_end:
            errors.append(f"forecast_end_date mismatch for {city_id}")
    if _positive_int(metadata.get("forecast_horizon_days")) != expected_horizon_days:
        errors.append(f"normalized forecast_horizon_days mismatch for {city_id}")
    if _positive_int(metadata.get("record_count")) != expected_horizon_days:
        errors.append(f"normalized record_count mismatch for {city_id}")

    return errors


def _raw_dates(document: Dict[str, Any]) -> List[str]:
    response = document.get("response") if isinstance(document.get("response"), dict) else {}
    daily = response.get("daily") if isinstance(response.get("daily"), list) else []
    return [str(item.get("fxDate") or "").strip() for item in daily if isinstance(item, dict) and item.get("fxDate")]


def _normalized_dates(document: Dict[str, Any]) -> List[str]:
    daily = document.get("daily_forecasts") if isinstance(document.get("daily_forecasts"), list) else []
    return [str(item.get("date") or "").strip() for item in daily if isinstance(item, dict) and item.get("date")]


def _dates_are_continuous(values: List[str]) -> bool:
    parsed = [_parse_date(value) for value in values]
    if any(value is None for value in parsed):
        return False
    dates = [value for value in parsed if value is not None]
    if len(dates) != len(set(dates)):
        return False
    return all(dates[index] + timedelta(days=1) == dates[index + 1] for index in range(len(dates) - 1))


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _parse_date(value: Any) -> Optional[date]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _bounded_days(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 3
    return max(1, min(parsed, QWEATHER_MAX_QUERY_DAYS))


def _coerce_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        numbers = re.findall(r"-?\d+", str(value))
        if not numbers:
            return None
        return max(int(number) for number in numbers)


def _coerce_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        numbers = re.findall(r"-?\d+(?:\.\d+)?", str(value))
        if not numbers:
            return None
        return max(float(number) for number in numbers)


def _daily_risk_tags(
    *,
    day_weather: str,
    night_weather: str,
    max_temp: Optional[int],
    min_temp: Optional[int],
    precipitation_mm: Optional[float],
    precipitation_probability: Optional[int],
    wind_scale_day: Optional[int],
    wind_speed_day: Optional[float],
) -> List[str]:
    text = f"{day_weather} {night_weather}".casefold()
    tags: List[str] = []
    if any(marker in text for marker in ("雨", "雪", "雷", "rain", "shower", "snow", "storm")):
        tags.append("rain")
    if precipitation_mm is not None and precipitation_mm >= 10:
        tags.extend(["rain", "heavy_rain"])
    elif precipitation_mm is not None and precipitation_mm > 0:
        tags.append("rain")
    if precipitation_probability is not None and precipitation_probability >= 60:
        tags.append("rain")
    if max_temp is not None and max_temp >= 36:
        tags.extend(["heat", "extreme_heat"])
    elif max_temp is not None and max_temp >= 33:
        tags.append("heat")
    if min_temp is not None and min_temp <= 5:
        tags.append("cold")
    if max_temp is not None and min_temp is not None and max_temp - min_temp >= 8:
        tags.append("large_temp_gap")
    if (wind_scale_day is not None and wind_scale_day >= 6) or (
        wind_speed_day is not None and wind_speed_day >= 39
    ):
        tags.append("wind")
    return _ordered_unique(tags)


def _daily_risk_level(risk_tags: Iterable[str]) -> str:
    tags = set(risk_tags)
    if tags & {"heavy_rain", "extreme_heat", "wind"}:
        return "high"
    if tags & {"rain", "heat", "cold", "large_temp_gap"}:
        return "medium"
    return "low"


def _weather_state(day_weather: str, night_weather: str, risk_tags: Iterable[str]) -> str:
    tags = set(risk_tags)
    text = f"{day_weather} {night_weather}"
    if "extreme_heat" in tags or "heat" in tags:
        return "high_temperature"
    if "cold" in tags:
        return "low_temperature"
    if "rain" in tags:
        return "rain"
    if "晴" in text:
        return "sunny"
    if "云" in text:
        return "cloudy"
    if "阴" in text:
        return "overcast"
    return "other"


def _overall_risk_level(
    daily_weather: List[Dict[str, Any]],
    *,
    coverage_status: str,
) -> str:
    if coverage_status == "out_of_range":
        return "unavailable"
    levels = {str(item.get("risk_level") or "low") for item in daily_weather}
    if "high" in levels:
        return "high"
    if "medium" in levels:
        return "medium"
    return "low"


def _overall_weather_type(
    daily_weather: List[Dict[str, Any]],
    *,
    coverage_status: str,
) -> str:
    if coverage_status == "out_of_range":
        return "out_of_range"
    tags = {
        tag
        for item in daily_weather
        for tag in item.get("risk_tags", [])
    }
    if "extreme_heat" in tags or "heat" in tags:
        return "high_temperature"
    if "cold" in tags:
        return "low_temperature"
    if "rain" in tags:
        return "rain"
    states = {
        str(item.get("state") or "")
        for item in daily_weather
        if item.get("state")
    }
    if len(states) > 1:
        return "continuous_change"
    return next(iter(states), "sunny")


def _planning_constraints(
    daily_weather: List[Dict[str, Any]],
    *,
    coverage_status: str,
    missing_dates: List[str],
) -> Dict[str, Any]:
    risk_tags = {
        tag
        for item in daily_weather
        for tag in item.get("risk_tags", [])
    }
    return {
        "coverage_status": coverage_status,
        "missing_dates": missing_dates,
        "dynamic_adjustment_required": bool(
            coverage_status == "partial"
            or risk_tags & {"rain", "heavy_rain", "heat", "extreme_heat", "cold", "wind"}
        ),
        "indoor_backup_recommended": bool(
            coverage_status != "full"
            or risk_tags & {"rain", "heavy_rain", "heat", "extreme_heat", "cold", "wind"}
        ),
        "missing_weather_must_not_be_fabricated": coverage_status in {"partial", "out_of_range"},
    }


def _coverage_warnings(coverage_status: str, missing_dates: List[str]) -> List[str]:
    if coverage_status == "full":
        return []
    if coverage_status == "partial":
        return [
            "Frozen QWeather snapshot only covers part of the requested trip; missing dates must not be fabricated.",
            f"Missing weather dates: {', '.join(missing_dates)}",
        ]
    return [
        "Requested trip dates are outside the frozen QWeather snapshot range; this is out_of_range, not a tool failure.",
        f"Missing weather dates: {', '.join(missing_dates)}",
    ]


def _suitable_periods(risk_tags: Iterable[str]) -> List[str]:
    tags = set(risk_tags)
    if tags & {"heat", "extreme_heat"}:
        return ["morning", "evening", "indoor"]
    if tags & {"rain", "heavy_rain", "wind", "cold"}:
        return ["indoor", "short_outdoor_window"]
    return ["morning", "afternoon", "evening"]


def _avoid_periods(risk_tags: Iterable[str]) -> List[str]:
    tags = set(risk_tags)
    periods: List[str] = []
    if tags & {"heat", "extreme_heat"}:
        periods.append("midday_outdoor")
    if tags & {"rain", "heavy_rain", "wind", "cold"}:
        periods.append("long_outdoor_exposure")
    return periods


def _ordered_unique(values: Iterable[Any]) -> List[Any]:
    result: List[Any] = []
    seen: set[str] = set()
    for value in values:
        if value in (None, ""):
            continue
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
