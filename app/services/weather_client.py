"""QWeather-backed weather client for the Weather Agent."""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

from app.core.context import ExecutionContext
from app.core.logger import get_logger

load_dotenv(override=False)

logger = get_logger(__name__)

DEFAULT_LOCATION = "101010100"
GEO_LOOKUP_PATH = "/geo/v2/city/lookup"
WEATHER_NOW_PATH = "/v7/weather/now"
WEATHER_FORECAST_PATH = "/v7/weather/7d"
AMAP_GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"

QWEATHER_TEXT_TO_WMO: Tuple[Tuple[str, int], ...] = (
    ("特大暴雨", 82),
    ("大暴雨", 82),
    ("强雷阵雨", 95),
    ("雷阵雨", 95),
    ("雷暴", 95),
    ("暴雨", 82),
    ("大雨", 65),
    ("中雨", 63),
    ("小雨", 61),
    ("阵雨", 80),
    ("冻雨", 66),
    ("雨夹雪", 79),
    ("暴雪", 75),
    ("大雪", 75),
    ("中雪", 73),
    ("小雪", 71),
    ("阵雪", 85),
    ("冰雹", 90),
    ("浓雾", 48),
    ("雾", 45),
    ("沙尘暴", 3),
    ("扬沙", 3),
    ("浮尘", 3),
    ("阴", 3),
    ("多云", 2),
    ("少云", 1),
    ("晴间多云", 1),
    ("晴", 0),
)


class QWeatherRequestError(RuntimeError):
    """Structured upstream request error for QWeather requests."""

    def __init__(
        self,
        *,
        endpoint: str,
        url: str,
        method: str,
        params: Dict[str, Any],
        status_code: Optional[int],
        response_code: Optional[str],
        response_error: Optional[str],
        response_payload: Optional[Dict[str, Any]],
    ) -> None:
        self.endpoint = endpoint
        self.url = url
        self.method = method
        self.params = params
        self.status_code = status_code
        self.response_code = response_code
        self.response_error = response_error
        self.response_payload = response_payload or {}
        status_text = status_code if status_code is not None else "unknown"
        detail = response_error or "Unknown upstream error"
        super().__init__(f"{method} {endpoint} failed with HTTP {status_text}: {detail}")


def _get_api_host() -> str:
    api_host = str(os.getenv("QWEATHER_API_HOST") or "").strip()
    if not api_host:
        raise ValueError("QWEATHER_API_HOST 未配置")
    return api_host


def _get_api_key() -> str:
    api_key = str(os.getenv("QWEATHER_API_KEY") or "").strip()
    if not api_key:
        raise ValueError("QWEATHER_API_KEY 未配置")
    return api_key


def _get_amap_api_key() -> str:
    return str(os.getenv("AMAP_API_KEY") or "").strip()


def _coerce_location(location: Optional[str]) -> str:
    return str(location or DEFAULT_LOCATION).strip() or DEFAULT_LOCATION


def _build_url(endpoint: str) -> str:
    host = _get_api_host().rstrip("/")
    base = host if host.startswith(("http://", "https://")) else f"https://{host}"
    return f"{base}{endpoint}"


def _get_api_headers() -> Dict[str, str]:
    return {
        "X-QW-Api-Key": _get_api_key(),
        "Accept-Encoding": "gzip",
    }


QWEATHER_API_HOST = _get_api_host()
BASE_URL = _build_url(WEATHER_FORECAST_PATH)
CITY_LOOKUP_URL = _build_url(GEO_LOOKUP_PATH)


def _is_coordinate_location(location: str) -> bool:
    parts = location.split(",")
    if len(parts) != 2:
        return False
    try:
        float(parts[0])
        float(parts[1])
        return True
    except (TypeError, ValueError):
        return False


def _is_text_location(location: str) -> bool:
    return not location.isdigit() and not _is_coordinate_location(location)


def _coerce_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_json(response: requests.Response) -> Dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _sanitize_params(params: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in params.items() if key.lower() != "key"}


def _extract_error_details(payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    if not payload:
        return None, None

    error = payload.get("error")
    if isinstance(error, dict):
        code = error.get("status")
        detail = error.get("detail") or error.get("title")
        return (str(code) if code not in (None, "") else None), (str(detail) if detail else None)

    code = payload.get("code")
    detail = payload.get("message") or payload.get("msg")
    return (str(code) if code not in (None, "") else None), (str(detail) if detail else None)


def _log_request_failure(
    *,
    endpoint: str,
    method: str,
    url: str,
    params: Dict[str, Any],
    status_code: Optional[int],
    response_code: Optional[str],
    response_error: Optional[str],
    response_payload: Optional[Dict[str, Any]],
) -> None:
    logger.error(
        "QWeather request failed",
        endpoint=endpoint,
        method=method,
        url=url,
        query=params,
        http_status=status_code,
        response_code=response_code,
        response_error=response_error,
        response=response_payload,
    )


def _request_json(endpoint: str, params: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    sanitized_params = _sanitize_params(params)
    url = _build_url(endpoint)
    try:
        response = requests.get(url, params=params, headers=_get_api_headers(), timeout=timeout)
    except requests.RequestException as exc:
        _log_request_failure(
            endpoint=endpoint,
            method="GET",
            url=url,
            params=sanitized_params,
            status_code=None,
            response_code=None,
            response_error=str(exc),
            response_payload=None,
        )
        raise QWeatherRequestError(
            endpoint=endpoint,
            url=url,
            method="GET",
            params=sanitized_params,
            status_code=None,
            response_code=None,
            response_error=str(exc),
            response_payload=None,
        ) from exc
    payload = _safe_json(response)
    response_code, response_error = _extract_error_details(payload)

    if response.status_code != 200:
        _log_request_failure(
            endpoint=endpoint,
            method="GET",
            url=response.request.url or url,
            params=sanitized_params,
            status_code=response.status_code,
            response_code=response_code,
            response_error=response_error,
            response_payload=payload,
        )
        raise QWeatherRequestError(
            endpoint=endpoint,
            url=response.request.url or url,
            method="GET",
            params=sanitized_params,
            status_code=response.status_code,
            response_code=response_code,
            response_error=response_error,
            response_payload=payload,
        )

    if payload.get("code") != "200":
        if response_error is None:
            response_error = f"QWeather API returned code {payload.get('code')}"
        _log_request_failure(
            endpoint=endpoint,
            method="GET",
            url=response.request.url or url,
            params=sanitized_params,
            status_code=response.status_code,
            response_code=response_code,
            response_error=response_error,
            response_payload=payload,
        )
        raise QWeatherRequestError(
            endpoint=endpoint,
            url=response.request.url or url,
            method="GET",
            params=sanitized_params,
            status_code=response.status_code,
            response_code=response_code,
            response_error=response_error,
            response_payload=payload,
        )

    return payload


def _request_now_payload(location: str, timeout: float = 5.0) -> Dict[str, Any]:
    return _request_json(
        WEATHER_NOW_PATH,
        {
            "location": _coerce_location(location),
            "lang": "zh",
        },
        timeout,
    )


def _request_forecast_payload(location: str, timeout: float = 5.0) -> Dict[str, Any]:
    return _request_json(
        WEATHER_FORECAST_PATH,
        {
            "location": _coerce_location(location),
            "lang": "zh",
        },
        timeout,
    )


_request_weather_payload = _request_forecast_payload


def _map_daily_forecast(daily: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for item in daily:
        results.append(
            {
                "date": item.get("fxDate"),
                "temp_max": item.get("tempMax"),
                "temp_min": item.get("tempMin"),
                "weather": item.get("textDay"),
                "day_weather": item.get("textDay"),
                "night_weather": item.get("textNight"),
                "wind_speed": item.get("windSpeedDay"),
                "precipitation_probability": _coerce_int(item.get("precip")),
                "raw": {
                    "fxDate": item.get("fxDate"),
                    "tempMin": item.get("tempMin"),
                    "tempMax": item.get("tempMax"),
                    "textDay": item.get("textDay"),
                    "textNight": item.get("textNight"),
                    "precip": item.get("precip"),
                    "windSpeedDay": item.get("windSpeedDay"),
                },
            }
        )
    return results


def _lookup_location(location_query: str, timeout: float) -> Optional[Dict[str, Any]]:
    payload = _request_json(
        GEO_LOOKUP_PATH,
        {
            "location": location_query,
            "number": 1,
            "lang": "zh",
            "range": "cn",
        },
        timeout,
    )
    locations = payload.get("location") or []
    if not locations:
        return None

    top = locations[0]
    return {
        "location_id": str(top.get("id") or "").strip() or location_query,
        "name": str(top.get("name") or "").strip() or location_query,
        "admin1": str(top.get("adm1") or "").strip() or str(top.get("country") or "").strip() or None,
        "district": str(top.get("adm2") or "").strip() or None,
        "country": str(top.get("country") or "").strip() or None,
        "lon": top.get("lon"),
        "lat": top.get("lat"),
        "adcode": None,
        "source": "qweather_geo",
    }


def _geocode_with_amap(location_query: str, timeout: float) -> Optional[Dict[str, Any]]:
    amap_api_key = _get_amap_api_key()
    if not amap_api_key:
        return None

    try:
        response = requests.get(
            AMAP_GEOCODE_URL,
            params={"address": location_query, "key": amap_api_key},
            timeout=max(timeout, 10.0),
        )
    except requests.RequestException as exc:
        logger.error(
            "AMap geocode fallback failed",
            endpoint="/v3/geocode/geo",
            method="GET",
            url=AMAP_GEOCODE_URL,
            query={"address": location_query},
            http_status=None,
            response_code=None,
            response_error=str(exc),
            response=None,
        )
        return None
    payload = _safe_json(response)
    if response.status_code != 200 or payload.get("status") != "1":
        logger.error(
            "AMap geocode fallback failed",
            endpoint="/v3/geocode/geo",
            method="GET",
            url=response.request.url,
            query={"address": location_query},
            http_status=response.status_code,
            response_code=payload.get("infocode"),
            response_error=payload.get("info"),
            response=payload,
        )
        return None

    geocodes = payload.get("geocodes") or []
    if not geocodes:
        return None

    top = geocodes[0]
    coordinate_text = str(top.get("location") or "").strip()
    if not coordinate_text or not _is_coordinate_location(coordinate_text):
        return None

    longitude, latitude = coordinate_text.split(",", 1)
    city = top.get("city")
    if isinstance(city, list):
        city = city[0] if city else None

    return {
        "location_id": coordinate_text,
        "name": str(city or top.get("province") or location_query).strip() or location_query,
        "admin1": str(top.get("province") or "").strip() or None,
        "district": str(top.get("district") or "").strip() or None,
        "country": "中国",
        "lon": longitude,
        "lat": latitude,
        "adcode": str(top.get("adcode") or "").strip() or None,
        "source": "amap_geocode_fallback",
    }


def _qweather_text_to_wmo_code(text: Any) -> Optional[int]:
    weather_text = str(text or "").strip()
    if not weather_text:
        return None

    for keyword, code in QWEATHER_TEXT_TO_WMO:
        if keyword in weather_text:
            return code
    return None


def _to_provider_forecast(item: Dict[str, Any]) -> Dict[str, Any]:
    weather_text = str(item.get("day_weather") or item.get("weather") or "").strip()
    night_weather_text = str(item.get("night_weather") or "").strip()
    return {
        "date": item.get("date"),
        "weather": weather_text,
        "day_weather": weather_text,
        "night_weather": night_weather_text,
        "weather_code": _qweather_text_to_wmo_code(weather_text),
        "max_temp": item.get("temp_max"),
        "min_temp": item.get("temp_min"),
        "wind_speed": _coerce_float(item.get("wind_speed")),
        "precipitation_probability": _coerce_int(item.get("precipitation_probability")),
        "raw": item.get("raw") if isinstance(item.get("raw"), dict) else {},
    }


def _build_current_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    now = payload.get("now") or {}
    return {
        "temperature": _coerce_int(now.get("temp")),
        "weather": now.get("text"),
        "wind_direction": now.get("windDir"),
        "wind_level": _coerce_int(now.get("windScale")),
        "humidity": _coerce_int(now.get("humidity")),
        "report_time": now.get("obsTime") or payload.get("updateTime"),
        "provider_raw": {
            "obsTime": now.get("obsTime") or payload.get("updateTime"),
            "temp": now.get("temp"),
            "text": now.get("text"),
            "windDir": now.get("windDir"),
            "windScale": now.get("windScale"),
            "humidity": now.get("humidity"),
        },
    }


def fetch_weather(location: str = DEFAULT_LOCATION) -> List[Dict[str, Any]]:
    """Legacy sync helper used by a few local checks."""
    location_query = _coerce_location(location)
    if _is_text_location(location_query):
        try:
            resolved = _lookup_location(location_query, timeout=5.0)
        except QWeatherRequestError:
            resolved = _geocode_with_amap(location_query, timeout=5.0)
        if not resolved:
            return []
        location_query = str(resolved.get("location_id") or location_query)

    try:
        payload = _request_forecast_payload(location_query, timeout=5.0)
    except Exception:
        return []

    daily = payload.get("daily") or []
    return _map_daily_forecast(daily)


class QWeatherWeatherClient:
    """Async QWeather client with location-resolution fallback."""

    def __init__(self, timeout: float = 12.0):
        self.timeout = timeout

    async def fetch_weather(
        self,
        *,
        label: str,
        coordinates: Optional[Tuple[float, float]] = None,
        context: Optional[ExecutionContext] = None,
    ) -> Optional[Dict[str, Any]]:
        resolved = await asyncio.to_thread(self._resolve_location, label, coordinates, context)
        if not resolved:
            return None

        try:
            current_payload = await asyncio.to_thread(
                self._call_qweather_api,
                context,
                "QWeather Current Weather",
                WEATHER_NOW_PATH,
                {"location": resolved["location_id"], "lang": "zh"},
            )
            forecast_payload = await asyncio.to_thread(
                self._call_qweather_api,
                context,
                "QWeather Daily Forecast",
                WEATHER_FORECAST_PATH,
                {"location": resolved["location_id"], "lang": "zh"},
            )
        except QWeatherRequestError:
            return None

        forecast_items = _map_daily_forecast(forecast_payload.get("daily") or [])
        if not forecast_items:
            return None

        district = resolved.get("district")
        if district == resolved.get("name"):
            district = None

        location_name = resolved.get("name") or label or "北京"
        raw_daily = forecast_payload.get("daily") or []
        return {
            "location": {
                "city": location_name,
                "province": resolved.get("admin1") or resolved.get("country"),
                "district": district,
                "adcode": resolved.get("adcode"),
                "location": location_name,
            },
            "location_id": resolved.get("location_id"),
            "location_source": resolved.get("source"),
            "resolved_query": label,
            "current": _build_current_payload(current_payload),
            "forecast": [_to_provider_forecast(item) for item in forecast_items],
            "raw": {
                "now": (current_payload.get("now") or {}).copy(),
                "daily": [
                    {
                        "fxDate": item.get("fxDate"),
                        "tempMin": item.get("tempMin"),
                        "tempMax": item.get("tempMax"),
                        "textDay": item.get("textDay"),
                        "textNight": item.get("textNight"),
                        "precip": item.get("precip"),
                        "windSpeedDay": item.get("windSpeedDay"),
                    }
                    for item in raw_daily
                ],
            },
        }

    def _resolve_location(
        self,
        label: str,
        coordinates: Optional[Tuple[float, float]],
        context: Optional[ExecutionContext],
    ) -> Optional[Dict[str, Any]]:
        if coordinates is not None:
            longitude, latitude = coordinates
            coordinate_text = f"{longitude},{latitude}"
            return {
                "location_id": coordinate_text,
                "name": str(label or "").strip() or coordinate_text,
                "admin1": None,
                "district": None,
                "country": "中国",
                "lon": longitude,
                "lat": latitude,
                "adcode": None,
                "source": "request_coordinates",
            }

        location_query = str(label or "").strip() or DEFAULT_LOCATION
        if location_query.isdigit() or _is_coordinate_location(location_query):
            return {
                "location_id": location_query,
                "name": str(label or "").strip() or location_query,
                "admin1": None,
                "district": None,
                "country": "中国",
                "lon": None,
                "lat": None,
                "adcode": None,
                "source": "direct_location",
            }

        start = time.perf_counter()
        try:
            resolved = _lookup_location(location_query, self.timeout)
            cost_ms = (time.perf_counter() - start) * 1000
            if not resolved:
                self._record_api_call(
                    context,
                    "QWeather Geo Lookup",
                    GEO_LOOKUP_PATH,
                    {"location": location_query},
                    "completed",
                    {"count": 0},
                    200,
                    None,
                    cost_ms,
                )
                return None

            self._record_api_call(
                context,
                "QWeather Geo Lookup",
                GEO_LOOKUP_PATH,
                {"location": location_query},
                "completed",
                {"count": 1, "location_id": resolved.get("location_id"), "source": resolved.get("source")},
                200,
                None,
                cost_ms,
            )
            return resolved
        except QWeatherRequestError as exc:
            cost_ms = (time.perf_counter() - start) * 1000
            self._record_api_call(
                context,
                "QWeather Geo Lookup",
                GEO_LOOKUP_PATH,
                exc.params,
                "failed",
                {"code": exc.response_code, "error": exc.response_error},
                exc.status_code or 500,
                exc.response_error,
                cost_ms,
            )

            fallback_start = time.perf_counter()
            fallback = _geocode_with_amap(location_query, self.timeout)
            fallback_cost_ms = (time.perf_counter() - fallback_start) * 1000
            if fallback:
                logger.warning(
                    "QWeather GeoAPI is restricted; fallback to AMap coordinates",
                    endpoint=GEO_LOOKUP_PATH,
                    method="GET",
                    url=exc.url,
                    query=exc.params,
                    http_status=exc.status_code,
                    response_code=exc.response_code,
                    response_error=exc.response_error,
                )
                self._record_api_call(
                    context,
                    "AMap Geocode Fallback",
                    "/v3/geocode/geo",
                    {"address": location_query},
                    "completed",
                    {"location_id": fallback.get("location_id"), "adcode": fallback.get("adcode")},
                    200,
                    None,
                    fallback_cost_ms,
                )
                return fallback

            logger.exception(f"Weather location resolution failed for '{location_query}'")
            return None

    def _call_qweather_api(
        self,
        context: Optional[ExecutionContext],
        service_name: str,
        endpoint: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        start = time.perf_counter()
        try:
            payload = _request_json(endpoint, params, self.timeout)
            cost_ms = (time.perf_counter() - start) * 1000
            self._record_api_call(
                context,
                service_name,
                endpoint,
                _sanitize_params(params),
                "completed",
                {"code": payload.get("code"), "updateTime": payload.get("updateTime")},
                200,
                None,
                cost_ms,
            )
            return payload
        except QWeatherRequestError as exc:
            cost_ms = (time.perf_counter() - start) * 1000
            self._record_api_call(
                context,
                service_name,
                endpoint,
                exc.params,
                "failed",
                {"code": exc.response_code, "error": exc.response_error},
                exc.status_code or 500,
                exc.response_error,
                cost_ms,
            )
            raise

    def _record_api_call(
        self,
        context: Optional[ExecutionContext],
        service_name: str,
        endpoint: str,
        params: Dict[str, Any],
        status: str,
        response: Optional[Dict[str, Any]],
        http_status: int,
        error: Optional[str],
        cost_ms: float,
    ) -> None:
        if context is None:
            return
        context.add_api_call_to_latest(
            agent_name="Weather",
            service=service_name,
            endpoint=endpoint,
            params=params,
            status=status,
            response=response,
            http_status=http_status,
            error=error,
            cost_ms=cost_ms,
        )


OpenMeteoWeatherClient = QWeatherWeatherClient
