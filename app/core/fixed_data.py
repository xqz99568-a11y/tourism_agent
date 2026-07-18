"""Fixed offline data access for formal tourism experiments."""
from __future__ import annotations

import json
import math
import os
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data"

OFFLINE_ENV_NAMES = (
    "TOURISM_FORMAL_EXPERIMENT_OFFLINE",
    "EXPERIMENT_OFFLINE_DATA",
    "FORMAL_EXPERIMENT_OFFLINE",
)

FIXED_CITY_IDS = ("beijing", "hangzhou", "xian", "shenzhen", "guilin")
FIXED_DATA_SNAPSHOT_DIRS = ("pois", "weather", "restaurants", "accommodation", "transport")
FIXED_DATA_EXPECTED_FILE_COUNT = 25
FIXED_DATA_EXPECTED_COMBINED_SHA256 = "90d9db7e967b44c4bf481a567ebeb76357c0231ee4c5e3c992740a18c1b54af3"
FIXED_DATA_EXPECTED_FILE_HASHES = {
    "data/accommodation/beijing.json": "91ebdadc86245922c61901a2ecfa437f1c754ed2c3975d68c642f7f8c5c93f05",
    "data/accommodation/guilin.json": "e8bbd330fa10ea575da49201bb69b30edc89874b64175a0c8f2593b09113f75d",
    "data/accommodation/hangzhou.json": "b146fa73d48688d36e035179e59f08d12a5a283d1bbe5e45ab1fbce27385bfee",
    "data/accommodation/shenzhen.json": "6ed2f5ef6078e7651c1f0106568136656dfab92cfe4cfe6866e4edbc185784e4",
    "data/accommodation/xian.json": "6a82d4ba2e8659bd414a048371690525f15b26491e2a2934d4c0d380c95e3aca",
    "data/pois/beijing.json": "4bd2fb952e1a9b2fb6670793d007d5ebd2cfc897f67829c4d36538410ac4977e",
    "data/pois/guilin.json": "1a6d802bb7295998f5d3d965aff1cb5b59998411645922211b319a5c0bfb09cb",
    "data/pois/hangzhou.json": "7abd466ba674fa160978d6037c95c0bd64a78deed6b5c454bacad8ba055f8aea",
    "data/pois/shenzhen.json": "199977c5ef39cef67d52af432922de53f57c4862e27e2fb1b34cff7bbbe17582",
    "data/pois/xian.json": "7f203268990980552debdc8425b77122c7ba7eb218d349f5723e77eada0e6e99",
    "data/restaurants/beijing.json": "378efb83ef2ba54ff563fd1d09e91403df354c942d31693d3a8725fcf9a11b33",
    "data/restaurants/guilin.json": "0b6c68e469096b53779ede207450df55db9040234e89d7cdb3e0bd907bf1a5fc",
    "data/restaurants/hangzhou.json": "214312ef2d5878038b74b9467210851184fbcad32edebe556bfee77a9cb881a0",
    "data/restaurants/shenzhen.json": "2d8572cfc4f87380b44e1026b39c228617b2e3989cac82baebc61d58109972ec",
    "data/restaurants/xian.json": "b4eb9c0f3503e63a988441cf4a8fc942c9c69edb1c797ef745b7ec446986a2f5",
    "data/transport/beijing.json": "758967b5cc01305b5c228d728a43bd91dc6a5f25e8366185bb459b7aa789929b",
    "data/transport/guilin.json": "475c97fb492d2386c82bb29863cde96d7ab8e78e9f14d2dd399f9b05102765c7",
    "data/transport/hangzhou.json": "3aa7ab8650eeeb605f95ca8779fa20aca4274b4b4134ac81e3d7911119f2134f",
    "data/transport/shenzhen.json": "ed0adb7927e11b66e8f2b8ed6dbfa397f84ec363edeee20aac0a21a92c246923",
    "data/transport/xian.json": "78977ab060a1c71fe87382ffc88a57644c721ea1270afc9520a3ae3b829472c0",
    "data/weather/beijing.json": "909fd6078a489aa09765a187411e4afa26c30ee8d3fd540734ed67eb3b62a348",
    "data/weather/guilin.json": "40cbe4ee2ce08189922d4639de5d59155050f6e4412fb4cb1a3f7c62d8574740",
    "data/weather/hangzhou.json": "d29568c5ab66f71261304511e7687b721e426176aff0da2152ed1bbee5c3e10a",
    "data/weather/shenzhen.json": "630a643c25608a9eef54e934ae7fe8a2eed59f7cb61f39f10484c08d90aba82e",
    "data/weather/xian.json": "26734c7f640ddabcddbca955672a4aa75927946a174df2a9dca2a43a5100b607",
}

CITY_ALIASES = {
    "beijing": ("beijing", "bj", "北京", "北京市"),
    "hangzhou": ("hangzhou", "hz", "杭州", "杭州市"),
    "xian": ("xian", "xi'an", "xa", "西安", "西安市"),
    "shenzhen": ("shenzhen", "sz", "深圳", "深圳市"),
    "guilin": ("guilin", "gl", "桂林", "桂林市"),
}

NODE_PREFIX_TO_CITY = {
    "bj": "beijing",
    "hz": "hangzhou",
    "xa": "xian",
    "sz": "shenzhen",
    "gl": "guilin",
}

BUDGET_TIER_MAP = {
    "economy": "economy",
    "low": "economy",
    "medium": "comfort",
    "comfort": "comfort",
    "standard": "comfort",
    "luxury": "premium",
    "premium": "premium",
    "high": "premium",
}

ROUTE_MODE_ALIASES = {
    "walk": "walking",
    "walking": "walking",
    "步行": "walking",
    "metro": "public_transit",
    "subway": "public_transit",
    "rail": "public_transit",
    "transit": "public_transit",
    "public_transit": "public_transit",
    "public_transport": "public_transit",
    "bus": "public_transit",
    "公共交通": "public_transit",
    "公交": "public_transit",
    "地铁": "public_transit",
    "taxi": "taxi",
    "car": "taxi",
    "driving": "taxi",
    "drive": "taxi",
    "打车": "taxi",
}

GENERIC_SEARCH_TERMS = {
    "",
    "poi",
    "search",
    "attraction",
    "attractions",
    "景点",
    "热门景点",
    "经典景点",
    "旅游景点",
    "餐饮",
    "美食",
    "住宿",
    "酒店",
}

WEATHER_STATE_LABELS = {
    "sunny": "晴天",
    "rain": "雨天",
    "high_temperature": "高温",
    "low_temperature": "低温",
    "continuous_change": "连续变化",
}


class FixedDataError(ValueError):
    """Raised when fixed experiment data cannot satisfy a request."""


def _env_true(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def is_formal_offline_mode() -> bool:
    """Return whether tools must use fixed offline data."""
    return any(_env_true(os.getenv(name)) for name in OFFLINE_ENV_NAMES)


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class FixedTourismData:
    """Loader and query layer for the frozen five-city experiment dataset."""

    def __init__(self, data_root: Path = DATA_ROOT) -> None:
        self.data_root = data_root
        self._documents: Dict[tuple[str, str], Dict[str, Any]] = {}
        self._entity_index_cache: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def resolve_city_id(self, value: Any) -> Optional[str]:
        text = str(value or "").strip()
        if not text:
            return None
        lowered = text.lower()
        if lowered in FIXED_CITY_IDS:
            return lowered
        node_city = self._city_from_node_id(text)
        if node_city:
            return node_city
        for city_id, aliases in CITY_ALIASES.items():
            for alias in aliases:
                alias_lower = alias.lower()
                if lowered == alias_lower or alias_lower in lowered or alias in text:
                    return city_id
        return None

    def city_bundle(self, city: Any) -> Dict[str, Dict[str, Any]]:
        city_id = self._require_city_id(city)
        return {
            "pois": self._load_city_file("pois", city_id),
            "restaurants": self._load_city_file("restaurants", city_id),
            "accommodation": self._load_city_file("accommodation", city_id),
            "weather": self._load_city_file("weather", city_id),
            "transport": self._load_city_file("transport", city_id),
        }

    def search_pois(
        self,
        *,
        city: Any,
        keywords: str = "",
        category: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        city_id = self._require_city_id(city)
        bundle = self.city_bundle(city_id)
        kind = self._resolve_search_kind(category, keywords)
        candidates: List[Dict[str, Any]] = []

        if kind in {"poi", "all"}:
            candidates.extend(
                self._format_attraction(item, bundle["pois"]["metadata"])
                for item in bundle["pois"].get("pois", [])
            )
        if kind in {"dining", "all"}:
            candidates.extend(
                self._format_dining_area(item, bundle["restaurants"]["metadata"])
                for item in bundle["restaurants"].get("dining_areas", [])
            )
        if kind in {"accommodation", "all"}:
            candidates.extend(
                self._format_accommodation_area(item, bundle["accommodation"]["metadata"])
                for item in bundle["accommodation"].get("accommodation_areas", [])
            )

        scored = [
            (self._match_score(item, keywords), index, item)
            for index, item in enumerate(candidates)
        ]
        if not self._is_generic_search(keywords):
            scored = [row for row in scored if row[0] > 0]
        scored.sort(key=lambda row: (-row[0], row[1]))
        bounded_limit = max(1, int(limit or 10))
        return [item for _, _, item in scored[:bounded_limit]]

    def get_poi_detail(self, poi_id: str) -> Dict[str, Any]:
        entity = self.find_entity(poi_id)
        if not entity:
            raise FixedDataError(f"fixed POI not found: {poi_id}")
        return dict(entity["formatted"])

    def find_entity(self, identifier: Any, city: Any = None) -> Optional[Dict[str, Any]]:
        text = str(identifier or "").strip()
        if not text:
            return None
        city_id = self.resolve_city_id(city) or self._city_from_node_id(text)
        cities = [city_id] if city_id else list(FIXED_CITY_IDS)
        lowered = text.lower()
        for candidate_city in cities:
            if not candidate_city:
                continue
            index = self._entity_index(candidate_city)
            if text in index:
                return index[text]
            if lowered in index:
                return index[lowered]
        return None

    def weather_query(
        self,
        *,
        city: Any,
        scenario_type: Optional[str] = None,
        days: int = 5,
    ) -> Dict[str, Any]:
        city_id = self._require_city_id(city)
        document = self._load_city_file("weather", city_id)
        metadata = document["metadata"]
        scenarios = document.get("weather_scenarios", [])
        scenario = self._select_weather_scenario(scenarios, scenario_type)
        requested_days = max(1, min(int(days or 5), int(metadata.get("maximum_trip_days") or 5)))
        day_rows = list(scenario.get("days", []))[:requested_days]
        daily_forecasts = [self._format_weather_day(item) for item in day_rows]
        current = self._build_current_weather(daily_forecasts)
        return {
            "provider": "fixed_weather_dataset",
            "offline": True,
            "available": bool(daily_forecasts),
            "degraded": False,
            "current_available": bool(current),
            "forecast_available": bool(daily_forecasts),
            "forecast_type": "fixed_weather_scenario",
            "destination": metadata.get("city_name") or city_id,
            "city": metadata.get("city_name") or city_id,
            "city_id": city_id,
            "scenario_id": scenario.get("id"),
            "scenario_type": scenario.get("scenario_type"),
            "scenario_name": scenario.get("name"),
            "requested_days": requested_days,
            "coverage_days": len(daily_forecasts),
            "current": current,
            "forecast": daily_forecasts,
            "daily_forecasts": daily_forecasts,
            "daily_weather": daily_forecasts,
            "temperature_range": self._temperature_range(daily_forecasts),
            "weather_type": scenario.get("scenario_type"),
            "risk_level": scenario.get("risk_level"),
            "risk_tags": self._collect_weather_tags(daily_forecasts),
            "planning_constraints": scenario.get("planning_constraints") or {},
            "packing_list": self._packing_list_for_weather(scenario.get("scenario_type")),
            "alternatives": self._alternatives_for_weather(scenario),
            "warnings": [],
            "applied_rules": ["fixed_weather_scenario", "day_index_not_real_date"],
            "dataset_version": metadata.get("dataset_version"),
            "source_file_id": metadata.get("file_id"),
            "snapshot_date": metadata.get("snapshot_date"),
            "metadata": self._metadata_payload(metadata),
        }

    def route(
        self,
        *,
        origin: Any,
        destination: Any,
        city: Any = None,
        mode: str = "public_transit",
    ) -> Dict[str, Any]:
        origin_text = str(origin or "").strip()
        destination_text = str(destination or "").strip()
        if not origin_text or not destination_text:
            raise FixedDataError("origin and destination are required for fixed routing")

        city_id = (
            self.resolve_city_id(city)
            or self._city_from_node_id(origin_text)
            or self._city_from_node_id(destination_text)
        )
        if not city_id:
            origin_entity = self.find_entity(origin_text)
            destination_entity = self.find_entity(destination_text)
            city_id = (
                (origin_entity or {}).get("city_id")
                or (destination_entity or {}).get("city_id")
            )
        if not city_id:
            raise FixedDataError("fixed routing requires one of the five experiment cities")

        normalized_mode = self.normalize_route_mode(mode)
        origin_area = self.resolve_area_id(city_id, origin_text)
        destination_area = self.resolve_area_id(city_id, destination_text)
        if not origin_area or not destination_area:
            raise FixedDataError(
                f"cannot map route nodes to fixed matrix areas: {origin_text} -> {destination_text}"
            )

        document = self._load_city_file("transport", city_id)
        link = self._find_transport_link(document, origin_area, destination_area)
        if not link:
            raise FixedDataError(f"missing fixed transport matrix link: {origin_area} -> {destination_area}")

        metadata = document["metadata"]
        duration_map = link.get("duration_minutes") or {}
        cost_map = link.get("cost_cny") or {}
        if normalized_mode not in duration_map or normalized_mode not in cost_map:
            raise FixedDataError(
                f"missing fixed transport mode '{normalized_mode}' for matrix link: "
                f"{origin_area} -> {destination_area}"
            )
        duration = int(duration_map[normalized_mode])
        cost = _safe_float(cost_map[normalized_mode])
        distance = _safe_float(link.get("distance_km"))
        return {
            "origin": origin_text,
            "destination": destination_text,
            "origin_area_id": origin_area,
            "destination_area_id": destination_area,
            "mode": normalized_mode,
            "distance_km": distance,
            "duration_minutes": duration,
            "estimated_cost_cny": cost,
            "strategy": "fixed_area_matrix",
            "offline": True,
            "dataset_version": metadata.get("dataset_version"),
            "source_file_id": metadata.get("file_id"),
            "snapshot_date": metadata.get("snapshot_date"),
            "calculation_rule": "lookup fixed area-pair matrix by mode",
            "steps": [
                {
                    "instruction": f"fixed {normalized_mode} matrix: {origin_area} -> {destination_area}",
                    "distance_km": distance,
                    "duration_minutes": duration,
                }
            ],
            "metadata": self._metadata_payload(metadata),
        }

    def calculate_budget(
        self,
        *,
        destination: Any,
        duration: int,
        num_travelers: int = 1,
        budget_level: str = "medium",
        poi_ids: Optional[Iterable[Any]] = None,
        dining_area_id: Optional[str] = None,
        accommodation_area_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        city_id = self._require_city_id(destination)
        bundle = self.city_bundle(city_id)
        tier = self.normalize_budget_tier(budget_level)
        duration = max(1, int(duration or 1))
        num_travelers = max(1, int(num_travelers or 1))
        nights = max(duration - 1, 1)
        room_count = max(math.ceil(num_travelers / 2), 1)

        dining_reference = self._reference_price(
            bundle["restaurants"].get("dining_areas", []),
            tier,
            preferred_id=dining_area_id,
        )
        accommodation_reference = self._reference_price(
            bundle["accommodation"].get("accommodation_areas", []),
            tier,
            preferred_id=accommodation_area_id,
        )
        meals_per_day = 3
        food_cost = dining_reference * num_travelers * duration * meals_per_day
        accommodation_cost = accommodation_reference * room_count * nights

        transport_mode = "taxi" if tier == "premium" else "public_transit"
        trip_count_per_day = 2 if tier == "premium" else 3
        transport_trip_cost = self._average_transport_cost(city_id, transport_mode)
        if transport_mode == "taxi":
            vehicle_count = max(math.ceil(num_travelers / 4), 1)
            transport_cost = transport_trip_cost * trip_count_per_day * duration * vehicle_count
        else:
            transport_cost = transport_trip_cost * trip_count_per_day * duration * num_travelers

        ticket_breakdown = self._ticket_budget(
            bundle["pois"].get("pois", []),
            num_travelers=num_travelers,
            duration=duration,
            poi_ids=poi_ids,
        )
        ticket_cost = ticket_breakdown["ticket_cost"]
        other_cost = {"economy": 30, "comfort": 60, "premium": 120}[tier] * duration * num_travelers
        subtotal = food_cost + accommodation_cost + transport_cost + ticket_cost + other_cost
        buffer_cost = round(subtotal * 0.10, 2)
        total = round(subtotal + buffer_cost, 2)

        metadata = {
            "poi": bundle["pois"]["metadata"],
            "dining": bundle["restaurants"]["metadata"],
            "accommodation": bundle["accommodation"]["metadata"],
            "transport": bundle["transport"]["metadata"],
        }
        return {
            "destination": destination,
            "city_id": city_id,
            "duration": duration,
            "num_travelers": num_travelers,
            "budget_level": budget_level,
            "normalized_budget_tier": tier,
            "offline": True,
            "calculation_source": "fixed_offline_dataset",
            "total_min": total,
            "total_max": total,
            "total_recommended": total,
            "per_person": round(total / num_travelers, 2),
            "daily": round(total / duration, 2),
            "breakdown": {
                "transport": {
                    "recommended": round(transport_cost, 2),
                    "mode": transport_mode,
                    "calculation_rule": "fixed matrix average cost * fixed trip count",
                },
                "accommodation": {
                    "recommended": round(accommodation_cost, 2),
                    "reference_price_cny": accommodation_reference,
                    "room_count": room_count,
                    "night_count": nights,
                    "calculation_rule": "room_count = ceil(traveler_count / 2); total_cost = room_count * reference_price_cny * night_count",
                },
                "food": {
                    "recommended": round(food_cost, 2),
                    "reference_price_cny": dining_reference,
                    "meal_count": meals_per_day * duration,
                    "calculation_rule": "total_cost = reference_price_cny * diner_count * meal_count",
                },
                "tickets": {
                    "recommended": round(ticket_cost, 2),
                    "calculation_rule": "sum known fixed adult ticket prices for selected experiment POIs; pending prices are not guessed",
                },
                "other": {"recommended": round(other_cost, 2), "calculation_rule": "fixed per-person daily allowance"},
                "buffer": {"recommended": buffer_cost, "calculation_rule": "10 percent fixed buffer"},
            },
            "ticket_breakdown": ticket_breakdown,
            "items": [
                {"category": "transport", "item": "fixed city transport", "estimated_cost": round(transport_cost, 2), "is_essential": True},
                {"category": "accommodation", "item": "fixed accommodation area", "estimated_cost": round(accommodation_cost, 2), "is_essential": True},
                {"category": "food", "item": "fixed dining area meals", "estimated_cost": round(food_cost, 2), "is_essential": True},
                {"category": "tickets", "item": "fixed POI tickets", "estimated_cost": round(ticket_cost, 2), "is_essential": True},
                {"category": "other", "item": "fixed miscellaneous allowance", "estimated_cost": round(other_cost, 2), "is_essential": False},
            ],
            "dataset_versions": {
                key: value.get("dataset_version") for key, value in metadata.items()
            },
            "source_file_ids": {
                key: value.get("file_id") for key, value in metadata.items()
            },
            "snapshot_dates": {
                key: value.get("snapshot_date") for key, value in metadata.items()
            },
            "metadata": {
                "offline": True,
                "live_price_allowed": False,
                "real_time_api_allowed": False,
            },
        }

    def resolve_area_id(self, city: Any, node_or_area: Any) -> Optional[str]:
        city_id = self._require_city_id(city)
        text = str(node_or_area or "").strip()
        if not text:
            return None
        transport = self._load_city_file("transport", city_id)
        valid_areas = {item.get("area_id") for item in transport.get("area_nodes", [])}
        if text in valid_areas:
            return text
        entity = self.find_entity(text, city_id)
        if entity:
            return entity.get("area_id")
        return None

    def normalize_route_mode(self, mode: Any) -> str:
        text = str(mode or "").strip().lower()
        if not text:
            return "public_transit"
        normalized = ROUTE_MODE_ALIASES.get(text)
        if not normalized:
            raise FixedDataError(f"unsupported fixed transport mode: {mode}")
        return normalized

    def normalize_budget_tier(self, budget_level: Any) -> str:
        text = str(budget_level or "medium").strip().lower()
        return BUDGET_TIER_MAP.get(text, "comfort")

    def _require_city_id(self, value: Any) -> str:
        city_id = self.resolve_city_id(value)
        if city_id not in FIXED_CITY_IDS:
            raise FixedDataError(f"unsupported fixed experiment city: {value}")
        return city_id

    def _load_city_file(self, folder: str, city_id: str) -> Dict[str, Any]:
        key = (folder, city_id)
        if key not in self._documents:
            path = self.data_root / folder / f"{city_id}.json"
            self._documents[key] = _read_json(path)
        return self._documents[key]

    def _city_from_node_id(self, value: Any) -> Optional[str]:
        text = str(value or "").strip().lower()
        if len(text) < 2:
            return None
        prefix = text[:2]
        return NODE_PREFIX_TO_CITY.get(prefix)

    def _resolve_search_kind(self, category: Optional[str], keywords: str) -> str:
        text = f"{category or ''} {keywords or ''}".lower()
        if any(token in text for token in ("all", "mixed", "全部", "综合")):
            return "all"
        if any(token in text for token in ("hotel", "accommodation", "住宿", "酒店")):
            return "accommodation"
        if any(token in text for token in ("restaurant", "dining", "food", "餐", "美食")):
            return "dining"
        return "poi"

    def _format_attraction(self, item: Dict[str, Any], metadata: Dict[str, Any]) -> Dict[str, Any]:
        location = item.get("location") or {}
        coordinate = location.get("coordinate") or {}
        classification = item.get("classification") or {}
        transport = item.get("transport") or {}
        duration = ((item.get("visit_profile") or {}).get("duration_hours") or {}).get("recommended")
        ticket = self._ticket_amount(item)
        formatted = {
            "id": item.get("id"),
            "name": item.get("name"),
            "city": metadata.get("city_name"),
            "city_id": metadata.get("city_id"),
            "district": location.get("district"),
            "area": location.get("district") or location.get("area_id"),
            "area_id": transport.get("area_id") or location.get("area_id"),
            "address": location.get("address"),
            "location": self._coordinate_text(coordinate),
            "type": classification.get("primary_category"),
            "category": classification.get("primary_category"),
            "tag": ",".join(str(tag) for tag in classification.get("tags", [])),
            "tags": list(classification.get("tags", [])),
            "ticket_price": self._format_price(ticket),
            "ticket_price_value": ticket,
            "opening_hours": (item.get("opening_hours") or {}).get("display_text"),
            "open_time": (item.get("opening_hours") or {}).get("display_text"),
            "recommended_duration": duration,
            "visit_duration_hours": duration,
            "indoor_outdoor": (item.get("environment") or {}).get("type"),
            "description": item.get("description"),
            "matrix_node_id": transport.get("matrix_node_id") or location.get("transport_node_id"),
            "transport_node_id": location.get("transport_node_id"),
            "rating": None,
            "biz_type": "fixed_attraction",
            "offline": True,
            "dataset_version": metadata.get("dataset_version"),
            "source_file_id": metadata.get("file_id"),
            "snapshot_date": metadata.get("snapshot_date"),
        }
        return formatted

    def _format_dining_area(self, item: Dict[str, Any], metadata: Dict[str, Any]) -> Dict[str, Any]:
        return self._format_area_entity(item, metadata, "fixed_dining_area", "dining_area")

    def _format_accommodation_area(self, item: Dict[str, Any], metadata: Dict[str, Any]) -> Dict[str, Any]:
        return self._format_area_entity(item, metadata, "fixed_accommodation_area", "accommodation_area")

    def _format_area_entity(
        self,
        item: Dict[str, Any],
        metadata: Dict[str, Any],
        biz_type: str,
        default_category: str,
    ) -> Dict[str, Any]:
        location = item.get("location") or {}
        coordinate = location.get("center_coordinate") or {}
        classification = item.get("classification") or {}
        transport = item.get("transport") or {}
        area_ids = list(location.get("area_ids") or [])
        tags = list(classification.get("tags") or [])
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "city": metadata.get("city_name"),
            "city_id": metadata.get("city_id"),
            "district": ",".join(str(value) for value in location.get("districts", [])),
            "area": area_ids[0] if area_ids else None,
            "area_id": area_ids[0] if area_ids else None,
            "address": ",".join(str(value) for value in location.get("districts", [])),
            "location": self._coordinate_text(coordinate),
            "type": classification.get("area_type") or default_category,
            "category": classification.get("area_type") or default_category,
            "tag": ",".join(str(tag) for tag in tags),
            "tags": tags,
            "matrix_node_id": transport.get("matrix_node_id"),
            "budget": item.get("budget") or {},
            "reference_prices": ((item.get("budget") or {}).get("tiers") or {}),
            "rating": None,
            "biz_type": biz_type,
            "offline": True,
            "dataset_version": metadata.get("dataset_version"),
            "source_file_id": metadata.get("file_id"),
            "snapshot_date": metadata.get("snapshot_date"),
        }

    def _entity_index(self, city_id: str) -> Dict[str, Dict[str, Any]]:
        if city_id in self._entity_index_cache:
            return self._entity_index_cache[city_id]
        bundle = self.city_bundle(city_id)
        records: List[tuple[Dict[str, Any], Dict[str, Any], str]] = []
        records.extend(
            (item, self._format_attraction(item, bundle["pois"]["metadata"]), "poi")
            for item in bundle["pois"].get("pois", [])
        )
        records.extend(
            (item, self._format_dining_area(item, bundle["restaurants"]["metadata"]), "dining")
            for item in bundle["restaurants"].get("dining_areas", [])
        )
        records.extend(
            (item, self._format_accommodation_area(item, bundle["accommodation"]["metadata"]), "accommodation")
            for item in bundle["accommodation"].get("accommodation_areas", [])
        )
        index: Dict[str, Dict[str, Any]] = {}
        for raw, formatted, kind in records:
            area_id = formatted.get("area_id")
            entity = {
                "raw": raw,
                "formatted": formatted,
                "kind": kind,
                "city_id": city_id,
                "area_id": area_id,
            }
            for key in (
                formatted.get("id"),
                formatted.get("matrix_node_id"),
                formatted.get("transport_node_id"),
                formatted.get("name"),
            ):
                text = str(key or "").strip()
                if text:
                    index[text] = entity
                    index[text.lower()] = entity
        self._entity_index_cache[city_id] = index
        return index

    def _ticket_amount(self, item: Dict[str, Any]) -> Optional[float]:
        rules = ((item.get("ticketing") or {}).get("price_rules") or [])
        adult_amounts = [
            _safe_float(rule.get("amount"))
            for rule in rules
            if rule.get("visitor_type") == "adult" and rule.get("amount") is not None
        ]
        if adult_amounts:
            return float(adult_amounts[0])
        return None

    def _format_price(self, amount: Optional[float]) -> Optional[str]:
        if amount is None:
            return None
        if amount == 0:
            return "免费"
        return f"{amount:g}元"

    def _coordinate_text(self, coordinate: Dict[str, Any]) -> Optional[str]:
        longitude = coordinate.get("longitude")
        latitude = coordinate.get("latitude")
        if longitude is None or latitude is None:
            return None
        return f"{longitude},{latitude}"

    def _match_score(self, item: Dict[str, Any], keywords: str) -> int:
        keyword = str(keywords or "").strip().lower()
        if self._is_generic_search(keyword):
            return 1
        haystack = " ".join(
            str(value or "")
            for value in (
                item.get("name"),
                item.get("type"),
                item.get("category"),
                item.get("tag"),
                item.get("address"),
            )
        ).lower()
        if keyword in haystack:
            return 10
        return 0

    def _is_generic_search(self, keywords: Any) -> bool:
        keyword = str(keywords or "").strip().lower()
        return keyword in GENERIC_SEARCH_TERMS

    def _select_weather_scenario(
        self,
        scenarios: List[Dict[str, Any]],
        scenario_type: Optional[str],
    ) -> Dict[str, Any]:
        target = str(scenario_type or "").strip() or "sunny"
        for scenario in scenarios:
            if scenario.get("scenario_type") == target or scenario.get("id") == target:
                return scenario
        if not scenarios:
            raise FixedDataError("weather scenario file has no scenarios")
        available = sorted(
            {
                str(value)
                for scenario in scenarios
                for value in (scenario.get("scenario_type"), scenario.get("id"))
                if value
            }
        )
        raise FixedDataError(
            f"unsupported fixed weather scenario: {target}; available scenarios: {', '.join(available)}"
        )

    def _format_weather_day(self, item: Dict[str, Any]) -> Dict[str, Any]:
        state = str(item.get("state") or "").strip()
        min_temp = item.get("temperature_min_c")
        max_temp = item.get("temperature_max_c")
        precipitation_mm = _safe_float(item.get("precipitation_mm"))
        rain_prob = min(100, int(round(precipitation_mm * 8)))
        tags = []
        if state == "rain" or precipitation_mm >= 5:
            tags.append("rain")
        if state == "high_temperature":
            tags.append("heat")
        if state == "low_temperature":
            tags.append("cold")
        return {
            "date": f"day_{item.get('day_index')}",
            "day_index": item.get("day_index"),
            "weather": WEATHER_STATE_LABELS.get(state, state),
            "day_weather": WEATHER_STATE_LABELS.get(state, state),
            "night_weather": WEATHER_STATE_LABELS.get(state, state),
            "state": state,
            "min_temp": min_temp,
            "max_temp": max_temp,
            "temperature_min_c": min_temp,
            "temperature_max_c": max_temp,
            "precipitation": rain_prob,
            "rain_prob": rain_prob,
            "precipitation_mm": precipitation_mm,
            "risk_tags": tags,
            "risk_level": "high" if "heat" in tags else ("medium" if tags else "low"),
            "suitable_periods": ["morning", "afternoon"] if state != "high_temperature" else ["morning", "evening"],
            "provider_raw": item,
        }

    def _build_current_weather(self, daily_forecasts: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not daily_forecasts:
            return {}
        first = daily_forecasts[0]
        return {
            "temperature": first.get("max_temp"),
            "weather": first.get("weather"),
            "wind_direction": "",
            "wind_level": None,
            "humidity": None,
            "report_time": f"day_{first.get('day_index')}",
            "provider_raw": first.get("provider_raw") or {},
        }

    def _temperature_range(self, daily_forecasts: List[Dict[str, Any]]) -> Dict[str, Any]:
        values = [
            value
            for item in daily_forecasts
            for value in (item.get("min_temp"), item.get("max_temp"))
            if isinstance(value, (int, float))
        ]
        if not values:
            return {"min": None, "max": None, "avg": None, "by_day": []}
        return {
            "min": min(values),
            "max": max(values),
            "avg": round(sum(values) / len(values), 1),
            "by_day": [
                {
                    "day_index": item.get("day_index"),
                    "min": item.get("min_temp"),
                    "max": item.get("max_temp"),
                }
                for item in daily_forecasts
            ],
        }

    def _collect_weather_tags(self, daily_forecasts: List[Dict[str, Any]]) -> List[str]:
        seen: List[str] = []
        for item in daily_forecasts:
            for tag in item.get("risk_tags") or []:
                if tag not in seen:
                    seen.append(tag)
        return seen

    def _packing_list_for_weather(self, scenario_type: Any) -> List[str]:
        scenario = str(scenario_type or "")
        if scenario == "rain":
            return ["雨具", "防滑鞋", "室内备选方案"]
        if scenario == "high_temperature":
            return ["防晒用品", "饮用水", "遮阳帽"]
        if scenario == "low_temperature":
            return ["保暖衣物", "手套", "防风外套"]
        return ["常规出行用品"]

    def _alternatives_for_weather(self, scenario: Dict[str, Any]) -> List[Dict[str, Any]]:
        constraints = scenario.get("planning_constraints") or {}
        if not constraints.get("dynamic_adjustment_required"):
            return []
        return [
            {
                "condition": scenario.get("scenario_type"),
                "action": "prefer indoor or lower-intensity activities according to fixed weather constraints",
                "preferred_categories": ["museum", "indoor_venue", "dining_area"],
            }
        ]

    def _find_transport_link(
        self,
        document: Dict[str, Any],
        origin_area: str,
        destination_area: str,
    ) -> Optional[Dict[str, Any]]:
        for link in document.get("links", []):
            origin = link.get("origin_area_id")
            destination = link.get("destination_area_id")
            if {origin, destination} == {origin_area, destination_area}:
                return link
        return None

    def _reference_price(
        self,
        items: List[Dict[str, Any]],
        tier: str,
        preferred_id: Optional[str] = None,
    ) -> float:
        if preferred_id:
            for item in items:
                if preferred_id in {item.get("id"), (item.get("transport") or {}).get("matrix_node_id")}:
                    return self._item_reference_price(item, tier)
        prices = [self._item_reference_price(item, tier) for item in items]
        prices = [price for price in prices if price > 0]
        if not prices:
            raise FixedDataError(f"missing reference_price_cny for tier {tier}")
        return round(sum(prices) / len(prices), 2)

    def _item_reference_price(self, item: Dict[str, Any], tier: str) -> float:
        tiers = ((item.get("budget") or {}).get("tiers") or {})
        return _safe_float((tiers.get(tier) or {}).get("reference_price_cny"))

    def _average_transport_cost(self, city_id: str, mode: str) -> float:
        document = self._load_city_file("transport", city_id)
        costs = [
            _safe_float((link.get("cost_cny") or {}).get(mode))
            for link in document.get("links", [])
            if link.get("origin_area_id") != link.get("destination_area_id")
        ]
        costs = [cost for cost in costs if cost > 0]
        if not costs:
            raise FixedDataError(f"missing transport cost matrix for mode {mode}")
        return round(sum(costs) / len(costs), 2)

    def _ticket_budget(
        self,
        pois: List[Dict[str, Any]],
        *,
        num_travelers: int,
        duration: int,
        poi_ids: Optional[Iterable[Any]],
    ) -> Dict[str, Any]:
        requested_ids = {str(value) for value in _as_list(poi_ids) if str(value or "").strip()}
        selected = [
            poi for poi in pois
            if not requested_ids or str(poi.get("id")) in requested_ids
        ]
        if not requested_ids:
            selected = selected[: max(1, duration * 2)]
        details = []
        ticket_sum = 0.0
        pending = []
        known_count = 0
        free_count = 0
        estimated_count = 0
        estimated_total = 0.0
        for poi in selected:
            amount = self._ticket_amount(poi)
            name = str(poi.get("name") or poi.get("id"))
            if amount is None:
                estimate = self._estimated_ticket_amount(poi)
                pending.append(name)
                estimated_count += 1
                estimated_total += estimate["amount"]
                ticket_sum += estimate["amount"]
                details.append(
                    {
                        "name": name,
                        "status": "estimated",
                        "parsed_ticket_yuan": None,
                        "counted_amount_yuan": estimate["amount"],
                        "estimation_rule": estimate["rule"],
                        "estimation_basis": estimate["basis"],
                    }
                )
                continue
            if amount == 0:
                free_count += 1
                details.append({"name": name, "status": "free", "counted_amount_yuan": 0.0})
                continue
            known_count += 1
            ticket_sum += amount
            details.append({"name": name, "status": "known", "parsed_ticket_yuan": amount, "counted_amount_yuan": amount})
        total = round(ticket_sum * num_travelers, 2)
        return {
            "ticket_cost": total,
            "ticket_cost_per_person": round(ticket_sum, 2),
            "details": details,
            "summary": {
                "poi_source_field": "fixed_poi_dataset",
                "source": "fixed_poi_ticketing",
                "known_ticket_count": known_count,
                "free_ticket_count": free_count,
                "estimated_ticket_count": estimated_count,
                "estimated_ticket_total_per_person": round(estimated_total, 2),
                "pending_confirmation_count": len(pending),
                "pending_confirmation_pois": pending,
                "ignored_non_ticket_count": 0,
                "fallback_applied": estimated_count > 0,
                "experiment_estimate_rule": (
                    "unknown adult ticket prices are counted with explicit fixed category estimates, "
                    "not treated as zero"
                ),
            },
        }

    def _estimated_ticket_amount(self, poi: Dict[str, Any]) -> Dict[str, Any]:
        classification = poi.get("classification") or {}
        category = str(
            classification.get("primary_category")
            or poi.get("category")
            or ""
        ).strip().lower()
        tags = [
            str(tag).strip().lower()
            for tag in _as_list(classification.get("tags") or poi.get("tags"))
        ]
        if any(tag in {"免费", "free"} for tag in tags):
            return {
                "amount": 0.0,
                "rule": "experiment_ticket_estimate_v1.free_tag",
                "basis": "POI tag indicates free entry",
            }
        category_estimates = {
            "museum": 80.0,
            "history_culture": 60.0,
            "nature": 35.0,
            "nature_park": 35.0,
            "urban_landmark": 40.0,
            "theme_park": 180.0,
            "family_science": 80.0,
            "indoor_venue": 60.0,
        }
        amount = category_estimates.get(category, 50.0)
        return {
            "amount": amount,
            "rule": "experiment_ticket_estimate_v1.category_default",
            "basis": f"primary_category={category or 'unknown'}",
        }

    def _metadata_payload(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "offline": True,
            "dataset_version": metadata.get("dataset_version"),
            "source_file_id": metadata.get("file_id"),
            "snapshot_date": metadata.get("snapshot_date"),
            "data_mode": metadata.get("data_mode"),
        }


@lru_cache(maxsize=1)
def get_fixed_tourism_data() -> FixedTourismData:
    return FixedTourismData()


def fixed_data_file_manifest(data_root: Path = DATA_ROOT) -> Dict[str, Any]:
    """Return SHA-256 hashes for the fixed data files used by experiments."""
    files: List[Dict[str, Any]] = []
    missing_files: List[str] = []
    for directory in FIXED_DATA_SNAPSHOT_DIRS:
        folder = data_root / directory
        for city_id in FIXED_CITY_IDS:
            path = folder / f"{city_id}.json"
            manifest_path = _manifest_relative_path(path, data_root)
            if not path.exists():
                missing_files.append(manifest_path)
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            files.append(
                {
                    "kind": directory,
                    "city_id": city_id,
                    "path": manifest_path,
                    "sha256": digest,
                }
            )
    files.sort(key=lambda item: (item["kind"], item["city_id"], item["path"]))
    missing_files.sort()
    combined_source = json.dumps(files, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "schema_version": "fixed_data_manifest_v1",
        "city_ids": list(FIXED_CITY_IDS),
        "snapshot_dirs": list(FIXED_DATA_SNAPSHOT_DIRS),
        "file_count": len(files),
        "expected_file_count": FIXED_DATA_EXPECTED_FILE_COUNT,
        "combined_sha256": hashlib.sha256(combined_source).hexdigest(),
        "expected_combined_sha256": FIXED_DATA_EXPECTED_COMBINED_SHA256,
        "missing_files": missing_files,
        "files": files,
    }


def validate_fixed_data_snapshot(data_root: Path = DATA_ROOT) -> Dict[str, Any]:
    """Fail fast when the formal offline data snapshot differs from the locked set."""
    manifest = fixed_data_file_manifest(data_root)
    actual_hashes = {item["path"]: item["sha256"] for item in manifest["files"]}
    expected_paths = set(FIXED_DATA_EXPECTED_FILE_HASHES)
    actual_paths = set(actual_hashes)
    missing_paths = sorted(expected_paths - actual_paths)
    unexpected_paths = sorted(actual_paths - expected_paths)
    changed_paths = sorted(
        path
        for path, expected_hash in FIXED_DATA_EXPECTED_FILE_HASHES.items()
        if path in actual_hashes and actual_hashes[path] != expected_hash
    )

    errors: List[str] = []
    if manifest["file_count"] != FIXED_DATA_EXPECTED_FILE_COUNT:
        errors.append(
            f"expected {FIXED_DATA_EXPECTED_FILE_COUNT} fixed data files, got {manifest['file_count']}"
        )
    if missing_paths:
        errors.append(f"missing fixed data files: {', '.join(missing_paths)}")
    if unexpected_paths:
        errors.append(f"unexpected fixed data files: {', '.join(unexpected_paths)}")
    if changed_paths:
        errors.append(f"modified fixed data files: {', '.join(changed_paths)}")
    if manifest["combined_sha256"] != FIXED_DATA_EXPECTED_COMBINED_SHA256:
        errors.append(
            "fixed data combined hash mismatch: "
            f"expected {FIXED_DATA_EXPECTED_COMBINED_SHA256}, got {manifest['combined_sha256']}"
        )
    if errors:
        raise FixedDataError("formal fixed data snapshot validation failed; " + "; ".join(errors))
    return manifest


def _manifest_relative_path(path: Path, data_root: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        try:
            return (Path("data") / path.relative_to(data_root)).as_posix()
        except ValueError:
            return path.as_posix()
