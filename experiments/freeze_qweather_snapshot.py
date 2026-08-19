"""Collect and freeze QWeather forecast data for Day8 experiments.

This script is the only online step for weather data.  Formal experiments must
read the generated JSON files and must not call QWeather again.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.fixed_data import (  # noqa: E402
    CANONICAL_JSON_SHA256_STRATEGY,
    REPO_ROOT,
    canonical_json_bytes,
    canonical_json_file_sha256,
)
from app.core.qweather_snapshot import (  # noqa: E402
    QWEATHER_CITY_LOCATION_IDS,
    QWEATHER_CITY_NAMES,
    QWEATHER_NORMALIZED_CITY_SCHEMA_VERSION,
    QWEATHER_RAW_CITY_SCHEMA_VERSION,
    QWEATHER_SNAPSHOT_DIR,
    QWEATHER_SNAPSHOT_SCHEMA_VERSION,
    build_qweather_validation_report,
    normalize_qweather_daily_item,
    validate_qweather_snapshot,
)
from app.services.weather_client import QWeatherRequestError, _request_json  # noqa: E402


FORECAST_DAY_CANDIDATES = (30, 15, 10, 7, 3)
TIMEZONE = "Asia/Shanghai"
CHINA_TIMEZONE = timezone(timedelta(hours=8), name=TIMEZONE)


def main() -> None:
    args = _parse_args()
    snapshot_dir = Path(args.output_dir)
    if snapshot_dir.exists() and any(snapshot_dir.iterdir()) and not args.overwrite:
        raise SystemExit(
            f"snapshot directory already exists and is not empty: {snapshot_dir}. "
            "Use --overwrite only when intentionally re-freezing before formal experiments."
        )

    fetched_at_dt = datetime.now(CHINA_TIMEZONE)
    fetched_at = fetched_at_dt.isoformat(timespec="seconds")
    reference_date = fetched_at_dt.date().isoformat()
    snapshot_id = args.snapshot_id or f"ctp_qweather_{fetched_at_dt:%Y%m%d}_v1"

    selected_days, endpoint, city_payloads = _fetch_largest_common_forecast(
        timeout=args.timeout,
    )
    if snapshot_dir.exists() and args.overwrite:
        shutil.rmtree(snapshot_dir)

    raw_dir = snapshot_dir / "raw"
    normalized_dir = snapshot_dir / "normalized"
    raw_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir.mkdir(parents=True, exist_ok=True)

    city_summaries: Dict[str, Dict[str, Any]] = {}
    for city_id, payload in city_payloads.items():
        raw_document = _build_raw_document(
            city_id=city_id,
            payload=payload,
            endpoint=endpoint,
            snapshot_id=snapshot_id,
            reference_date=reference_date,
            fetched_at=fetched_at,
        )
        raw_path = raw_dir / f"{city_id}.json"
        _write_json(raw_path, raw_document)

        normalized_document = _build_normalized_document(
            city_id=city_id,
            payload=payload,
            endpoint=endpoint,
            snapshot_id=snapshot_id,
            reference_date=reference_date,
            fetched_at=fetched_at,
        )
        normalized_path = normalized_dir / f"{city_id}.json"
        _write_json(normalized_path, normalized_document)
        metadata = normalized_document["metadata"]
        city_summaries[city_id] = {
            "city_name": metadata["city_name"],
            "location_id": metadata["location_id"],
            "forecast_start_date": metadata["forecast_start_date"],
            "forecast_end_date": metadata["forecast_end_date"],
            "forecast_horizon_days": metadata["forecast_horizon_days"],
            "raw_path": _relative_path(raw_path),
            "normalized_path": _relative_path(normalized_path),
        }

    manifest = _build_manifest(
        snapshot_dir=snapshot_dir,
        snapshot_id=snapshot_id,
        reference_date=reference_date,
        fetched_at=fetched_at,
        endpoint=endpoint,
        selected_days=selected_days,
        city_summaries=city_summaries,
    )
    _write_json(snapshot_dir / "snapshot_manifest.json", manifest)
    validation_report = build_qweather_validation_report(snapshot_dir, manifest=manifest)
    _write_json(snapshot_dir / "validation_report.json", validation_report)
    validated = validate_qweather_snapshot(snapshot_dir)

    print(
        json.dumps(
            {
                "status": "success",
                "snapshot_id": validated["snapshot_id"],
                "forecast_endpoint": validated["forecast_endpoint"],
                "forecast_horizon_days": validated["forecast_horizon_days"],
                "forecast_start_date": validated["forecast_start_date"],
                "forecast_end_date": validated["forecast_end_date"],
                "cities": validated["cities"],
                "combined_sha256": validated["combined_sha256"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freeze QWeather forecast snapshot.")
    parser.add_argument(
        "--output-dir",
        default=str(QWEATHER_SNAPSHOT_DIR),
        help="Output snapshot directory.",
    )
    parser.add_argument(
        "--snapshot-id",
        default="",
        help="Stable snapshot id. Defaults to ctp_qweather_YYYYMMDD_v1.",
    )
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def _fetch_largest_common_forecast(
    *,
    timeout: float,
) -> tuple[int, str, Dict[str, Dict[str, Any]]]:
    failures: List[str] = []
    for days in FORECAST_DAY_CANDIDATES:
        endpoint = f"/v7/weather/{days}d"
        city_payloads: Dict[str, Dict[str, Any]] = {}
        ok = True
        for city_id, location_id in QWEATHER_CITY_LOCATION_IDS.items():
            try:
                payload = _request_json(
                    endpoint,
                    {"location": location_id, "lang": "zh", "unit": "m"},
                    timeout,
                )
            except QWeatherRequestError as exc:
                failures.append(f"{endpoint} {city_id}: {exc.response_error or exc.response_code or exc.status_code}")
                ok = False
                break
            daily = payload.get("daily")
            if not isinstance(daily, list) or len(daily) != days:
                actual_count = len(daily) if isinstance(daily, list) else "missing"
                failures.append(
                    f"{endpoint} {city_id}: expected exactly {days} daily forecasts, got {actual_count}"
                )
                ok = False
                break
            city_payloads[city_id] = payload
        if ok and len(city_payloads) == len(QWEATHER_CITY_LOCATION_IDS):
            return days, endpoint, city_payloads
    raise SystemExit("No common QWeather forecast endpoint succeeded for all cities: " + "; ".join(failures))


def _build_raw_document(
    *,
    city_id: str,
    payload: Dict[str, Any],
    endpoint: str,
    snapshot_id: str,
    reference_date: str,
    fetched_at: str,
) -> Dict[str, Any]:
    return {
        "schema_version": QWEATHER_RAW_CITY_SCHEMA_VERSION,
        "provider": "qweather",
        "snapshot_id": snapshot_id,
        "reference_date": reference_date,
        "fetched_at": fetched_at,
        "timezone": TIMEZONE,
        "city_id": city_id,
        "city_name": QWEATHER_CITY_NAMES[city_id],
        "location_id": QWEATHER_CITY_LOCATION_IDS[city_id],
        "request": {
            "endpoint": endpoint,
            "params": {
                "location": QWEATHER_CITY_LOCATION_IDS[city_id],
                "lang": "zh",
                "unit": "m",
            },
            "auth_policy": "api credential used during collection; credential value and header name are not recorded",
        },
        "response": payload,
    }


def _build_normalized_document(
    *,
    city_id: str,
    payload: Dict[str, Any],
    endpoint: str,
    snapshot_id: str,
    reference_date: str,
    fetched_at: str,
) -> Dict[str, Any]:
    daily = [
        normalize_qweather_daily_item(
            item,
            day_index=index,
            city_id=city_id,
            snapshot_id=snapshot_id,
            source_endpoint=endpoint,
        )
        for index, item in enumerate(payload.get("daily") or [], start=1)
    ]
    dates = [item["date"] for item in daily if item.get("date")]
    forecast_start_date = min(dates) if dates else ""
    forecast_end_date = max(dates) if dates else ""
    city_name = QWEATHER_CITY_NAMES[city_id]
    return {
        "metadata": {
            "file_id": f"ctp_qweather_{city_id}_{snapshot_id}_normalized",
            "schema_version": QWEATHER_NORMALIZED_CITY_SCHEMA_VERSION,
            "dataset_version": "CTP-QWEATHER-SNAPSHOT-v1",
            "provider": "qweather",
            "snapshot_id": snapshot_id,
            "reference_date": reference_date,
            "fetched_at": fetched_at,
            "timezone": TIMEZONE,
            "city_id": city_id,
            "city_name": city_name,
            "location_id": QWEATHER_CITY_LOCATION_IDS[city_id],
            "forecast_endpoint": endpoint,
            "forecast_start_date": forecast_start_date,
            "forecast_end_date": forecast_end_date,
            "forecast_horizon_days": len(daily),
            "record_count": len(daily),
            "data_mode": "frozen_offline",
            "source_mode": "qweather_frozen_snapshot",
            "location_resolution": "fixed_location_id",
            "real_time_api_allowed": False,
            "api_key_recorded": False,
            "source": {
                "source_name": "QWeather",
                "source_endpoint": endpoint,
                "collection_policy": "collected once before formal experiments; runtime reads local snapshot only",
            },
        },
        "daily_forecasts": daily,
    }


def _build_manifest(
    *,
    snapshot_dir: Path,
    snapshot_id: str,
    reference_date: str,
    fetched_at: str,
    endpoint: str,
    selected_days: int,
    city_summaries: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    file_records = _file_records(snapshot_dir)
    forecast_start_date = max(
        summary["forecast_start_date"] for summary in city_summaries.values()
    )
    forecast_end_date = min(
        summary["forecast_end_date"] for summary in city_summaries.values()
    )
    combined_sha256 = hashlib.sha256(canonical_json_bytes(file_records)).hexdigest()
    return {
        "schema_version": QWEATHER_SNAPSHOT_SCHEMA_VERSION,
        "provider": "qweather",
        "snapshot_id": snapshot_id,
        "dataset_version": "CTP-QWEATHER-SNAPSHOT-v1",
        "reference_date": reference_date,
        "fetched_at": fetched_at,
        "timezone": TIMEZONE,
        "forecast_endpoint": endpoint,
        "forecast_start_date": forecast_start_date,
        "forecast_end_date": forecast_end_date,
        "forecast_horizon_days": selected_days,
        "cities": list(QWEATHER_CITY_LOCATION_IDS),
        "city_summaries": city_summaries,
        "location_resolution": "fixed_location_id",
        "location_ids": dict(QWEATHER_CITY_LOCATION_IDS),
        "raw_dir": "data/weather_snapshot/qweather_v1/raw",
        "normalized_dir": "data/weather_snapshot/qweather_v1/normalized",
        "real_time_api_allowed": False,
        "runtime_online_refresh_allowed": False,
        "api_key_recorded": False,
        "formal_experiment_policy": (
            "M1/M2/M3 read this frozen local snapshot; formal runs must not refresh weather online."
        ),
        "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
        "combined_sha256": combined_sha256,
        "files": file_records,
    }


def _file_records(snapshot_dir: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for kind in ("raw", "normalized"):
        for city_id in QWEATHER_CITY_LOCATION_IDS:
            path = snapshot_dir / kind / f"{city_id}.json"
            records.append(
                {
                    "kind": kind,
                    "city_id": city_id,
                    "path": _relative_path(path),
                    "sha256": canonical_json_file_sha256(path),
                    "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
                }
            )
    records.sort(key=lambda row: (row["kind"], row["city_id"], row["path"]))
    return records


def _relative_path(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
