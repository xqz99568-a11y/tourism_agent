"""
POI search tools backed by the AMap Place APIs.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.fixed_data import FixedDataError, get_fixed_tourism_data, is_formal_offline_mode
from app.core.logger import get_logger
from app.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)

POI_HTTP_TIMEOUT = httpx.Timeout(10.0)
POI_HTTP_LIMITS = httpx.Limits(max_connections=12, max_keepalive_connections=12)
_POI_HTTP_CLIENTS: Dict[int, httpx.AsyncClient] = {}
_POI_HTTP_CLIENT_LOCKS: Dict[int, asyncio.Lock] = {}


def _build_poi_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=POI_HTTP_TIMEOUT, limits=POI_HTTP_LIMITS)


async def _get_poi_http_client() -> httpx.AsyncClient:
    loop_id = id(asyncio.get_running_loop())
    lock = _POI_HTTP_CLIENT_LOCKS.get(loop_id)
    if lock is None:
        lock = asyncio.Lock()
        _POI_HTTP_CLIENT_LOCKS[loop_id] = lock

    async with lock:
        client = _POI_HTTP_CLIENTS.get(loop_id)
        if client is None or client.is_closed:
            client = _build_poi_http_client()
            _POI_HTTP_CLIENTS[loop_id] = client
        return client


def _format_exception_message(exc: Exception) -> str:
    detail = str(exc)
    if detail:
        return f"{exc.__class__.__name__}: {detail}"
    return exc.__class__.__name__


def _is_expected_http_error(exc: Exception) -> bool:
    return isinstance(exc, httpx.TransportError)


class POISearchTool(BaseTool):
    """Search POIs from AMap."""

    name = "poi_search"
    description = "Search POI information such as attractions and restaurants"
    external_service = "高德地图API"
    parameters = {
        "type": "object",
        "properties": {
            "keywords": {
                "type": "string",
                "description": "Search keywords",
            },
            "city": {
                "type": "string",
                "description": "City name",
            },
            "category": {
                "type": "string",
                "description": "POI category, such as attraction, restaurant, or hotel",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return",
                "default": 10,
            },
        },
        "required": ["keywords", "city"],
    }

    def __init__(self):
        super().__init__()
        self.api_key = settings.amap.api_key
        self.base_url = "https://restapi.amap.com/v3/place/text"

    async def execute(
        self,
        keywords: str,
        city: str,
        category: Optional[str] = None,
        limit: int = 10,
        **kwargs,
    ) -> ToolResult:
        """Execute a POI text search."""
        if not self.validate_params({"keywords": keywords, "city": city}):
            return ToolResult(success=False, error="Invalid parameters")

        if is_formal_offline_mode():
            try:
                self.external_service = "fixed_offline_dataset"
                results = get_fixed_tourism_data().search_pois(
                    keywords=keywords,
                    city=city,
                    category=category,
                    limit=limit,
                )
                metadata = {
                    "offline": True,
                    "count": len(results),
                    "data_source": "fixed_poi_dining_accommodation_dataset",
                    "real_time_api_allowed": False,
                }
                return ToolResult(success=True, data=results, metadata=metadata, api_calls=[])
            except FixedDataError as exc:
                return ToolResult(success=False, error=str(exc), metadata={"offline": True})

        params = {
            "key": self.api_key,
            "keywords": keywords,
            "city": city,
            "output": "json",
            "offset": limit,
            "page": 1,
            "extensions": "all",
        }
        if category:
            params["types"] = self._map_category(category)

        try:
            start_time = time.time()
            client = await _get_poi_http_client()
            response = await client.get(self.base_url, params=params)
            cost_ms = (time.time() - start_time) * 1000

            if response.status_code != 200:
                error = f"API request failed: {response.status_code}"
                self.record_api_call(
                    endpoint="/v3/place/text",
                    params={"city": city, "keywords": keywords},
                    status="failed",
                    http_status=response.status_code,
                    error=error,
                    cost_ms=cost_ms,
                )
                return ToolResult(success=False, error=error)

            data = response.json()
            if data.get("status") != "1":
                error = data.get("info", "Unknown error")
                self.record_api_call(
                    endpoint="/v3/place/text",
                    params={"city": city, "keywords": keywords},
                    status="failed",
                    http_status=200,
                    error=error,
                    cost_ms=cost_ms,
                )
                return ToolResult(success=False, error=error)

            pois = data.get("pois", [])
            self.record_api_call(
                endpoint="/v3/place/text",
                params={"city": city, "keywords": keywords},
                status="completed",
                response={"count": len(pois), "pois": pois[:3]},
                http_status=200,
                cost_ms=cost_ms,
            )

            results = []
            for poi in pois[:limit]:
                results.append(
                    {
                        "id": poi.get("id"),
                        "name": poi.get("name"),
                        "address": poi.get("address"),
                        "location": poi.get("location"),
                        "tel": poi.get("tel"),
                        "type": poi.get("type"),
                        "typecode": poi.get("typecode"),
                        "rating": self._calculate_rating(poi),
                        "biz_type": poi.get("biz_type"),
                    }
                )

            return ToolResult(
                success=True,
                data=results,
                metadata={"count": len(results)},
                api_calls=[
                    {
                        "service": self.external_service,
                        "endpoint": "/v3/place/text",
                        "status": "completed",
                        "cost_ms": cost_ms,
                        "result_count": len(pois),
                    }
                ],
            )
        except Exception as e:
            error_text = _format_exception_message(e)
            if _is_expected_http_error(e):
                logger.warning(
                    f"POI search request failed for city={city} keywords={keywords}: {error_text}"
                )
            else:
                logger.exception(f"POI search failed: {error_text}")
            self.record_api_call(
                endpoint="/v3/place/text",
                params={"city": city, "keywords": keywords},
                status="failed",
                error=error_text,
            )
            return ToolResult(success=False, error=error_text)

    def _map_category(self, category: str) -> str:
        """Map a friendly category to an AMap type code."""
        category_map = {
            "景点": "110000",
            "餐厅": "050000",
            "酒店": "100000",
            "购物": "060000",
            "娱乐": "080000",
            "交通": "150000",
        }
        return category_map.get(category, "")

    def _calculate_rating(self, poi: Dict[str, Any]) -> float:
        """Return a placeholder rating because AMap text search has no rating."""
        return 4.0


class POIDetailTool(BaseTool):
    """Fetch POI detail from AMap."""

    name = "poi_detail"
    description = "Fetch detailed POI information such as opening hours and tickets"
    external_service = "高德地图API"
    parameters = {
        "type": "object",
        "properties": {
            "poi_id": {
                "type": "string",
                "description": "POI ID",
            },
        },
        "required": ["poi_id"],
    }

    def __init__(self):
        super().__init__()
        self.api_key = settings.amap.api_key
        self.base_url = "https://restapi.amap.com/v3/place/detail"

    async def execute(self, poi_id: str, **kwargs) -> ToolResult:
        """Fetch POI detail."""
        if not self.validate_params({"poi_id": poi_id}):
            return ToolResult(success=False, error="Invalid parameters")

        if is_formal_offline_mode():
            try:
                self.external_service = "fixed_offline_dataset"
                detail = get_fixed_tourism_data().get_poi_detail(poi_id)
                metadata = {
                    "offline": True,
                    "data_source": "fixed_poi_dining_accommodation_dataset",
                    "real_time_api_allowed": False,
                    "source_file_id": detail.get("source_file_id"),
                    "dataset_version": detail.get("dataset_version"),
                }
                return ToolResult(success=True, data=detail, metadata=metadata, api_calls=[])
            except FixedDataError as exc:
                return ToolResult(success=False, error=str(exc), metadata={"offline": True})

        params = {
            "key": self.api_key,
            "id": poi_id,
            "extensions": "all",
        }

        try:
            start_time = time.time()
            client = await _get_poi_http_client()
            response = await client.get(self.base_url, params=params)
            cost_ms = (time.time() - start_time) * 1000

            if response.status_code != 200:
                error = f"API request failed: {response.status_code}"
                self.record_api_call(
                    endpoint="/v3/place/detail",
                    params={"id": poi_id},
                    status="failed",
                    http_status=response.status_code,
                    error=error,
                    cost_ms=cost_ms,
                )
                return ToolResult(success=False, error=error)

            data = response.json()
            if data.get("status") != "1":
                error = data.get("info", "Unknown error")
                self.record_api_call(
                    endpoint="/v3/place/detail",
                    params={"id": poi_id},
                    status="failed",
                    http_status=200,
                    error=error,
                    cost_ms=cost_ms,
                )
                return ToolResult(success=False, error=error)

            poi = data.get("pois", [{}])[0]
            self.record_api_call(
                endpoint="/v3/place/detail",
                params={"id": poi_id},
                status="completed",
                response={"name": poi.get("name"), "type": poi.get("type")},
                http_status=200,
                cost_ms=cost_ms,
            )

            result = {
                "id": poi.get("id"),
                "name": poi.get("name"),
                "location": poi.get("location"),
                "address": poi.get("address"),
                "tel": poi.get("tel"),
                "type": poi.get("type"),
                "tag": poi.get("tag"),
                "biz_type": poi.get("biz_type"),
                "indoor_map": poi.get("indoor_map"),
                "photos": self._get_photos(poi),
            }
            return ToolResult(success=True, data=result)
        except Exception as e:
            error_text = _format_exception_message(e)
            if _is_expected_http_error(e):
                logger.warning(
                    f"POI detail request failed for poi_id={poi_id}: {error_text}"
                )
            else:
                logger.exception(f"POI detail fetch failed: {error_text}")
            self.record_api_call(
                endpoint="/v3/place/detail",
                params={"id": poi_id},
                status="failed",
                error=error_text,
            )
            return ToolResult(success=False, error=error_text)

    def _get_photos(self, poi: Dict[str, Any]) -> List[str]:
        """Extract up to five photo URLs."""
        photos = poi.get("photos", [])
        return [photo.get("url") for photo in photos[:5] if photo.get("url")]


def register_poi_tools(registry):
    """Register POI-related tools."""
    registry.register(POISearchTool())
    registry.register(POIDetailTool())
