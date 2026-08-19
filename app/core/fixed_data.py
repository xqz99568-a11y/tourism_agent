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
CANONICAL_JSON_SHA256_STRATEGY = "canonical_json_utf8_sort_keys_v1"
FIXED_DATA_EXPECTED_COMBINED_SHA256 = "8746745969a4045b0295bdb27a7a19fb953e50067a097aa53e38c8f9b5e288d0"
FIXED_DATA_EXPECTED_FILE_HASHES = {
    "data/accommodation/beijing.json": "2b50fd5c0001f6c2c8d23a1197e7aca0b42c361775e329a44cb6fc44fcf525ff",
    "data/accommodation/guilin.json": "1c9423ded3c30d2781c9cfe28e42699bb94110956150105c92e54a553400954d",
    "data/accommodation/hangzhou.json": "4246b431b3c63bab787692549ff13d40e8cdfd05e3f25ec1763425d3e5447c0f",
    "data/accommodation/shenzhen.json": "b8f9fad3895bcea7bea795311e0360b62bbe14e33afa6f448472f1f96fd6c0d9",
    "data/accommodation/xian.json": "127ab00c1e2c5435b5bda9db2b07c94f891e6d1b2d5e85abaa4e4fb79e76f5f7",
    "data/pois/beijing.json": "da06efbb03a94facbc71501dd7c6ec38cf56a25a9255ff091f01cc0d311b63a8",
    "data/pois/guilin.json": "d6eb9436760bbea33d24fd3637ac67d3096e08efa542683d7a089e70ca71194e",
    "data/pois/hangzhou.json": "5062fa9214f1a4cd99db8347526e99005da3cead1d85a55e9b4922d73fa9aa6e",
    "data/pois/shenzhen.json": "7fc9fec9f14f58ef6095e8fe725273d23e955d813b6d2447aa1a151fbe57e26e",
    "data/pois/xian.json": "b5564a26e8ac8e0629fc58b24ae6d10092a4524a46d0c764eefc2273bd0f051e",
    "data/restaurants/beijing.json": "9014ba5a573a54932a3c71c1c3db6f446ab2affc201e5293f1d26aed5a9834c8",
    "data/restaurants/guilin.json": "a34b14352672174ce3dbabbcbb6a8a675728faa0c1fa47243c27b5cb2f818d30",
    "data/restaurants/hangzhou.json": "6d294302e53b6c1f540f15741bdf5d8fd431a1ad518d461f0890b7d3f64b4425",
    "data/restaurants/shenzhen.json": "370a5947d3d3b6fbce3b7eb920262396cf6ae9aa797859a8c73abab049497d62",
    "data/restaurants/xian.json": "fe64fd4fadfb5a6e6d437e3fcab3d7c1d6aec09d631f41ed3c92b3572f7dbf10",
    "data/transport/beijing.json": "0cd9687c5b5457140113355b84da19e1dde7610dcb59d4360b9a70f18e8f74d2",
    "data/transport/guilin.json": "dce6bbaa6311123321c9d56d8267eed4decd9b3e1e35141ff0b24fb757b7cca9",
    "data/transport/hangzhou.json": "7ce095fd0a66ee943443cca69993599231c83abe4b71cfed4109e9fb26546891",
    "data/transport/shenzhen.json": "b18ee3d6c7b31edb79bf01749fac9b5ad1160f5de1d03a3dcd8335b0de80d8a8",
    "data/transport/xian.json": "c72faec4caa70466e36b28a428c3f1e8f21a684f79f55a8c4c09a0c378e685a9",
    "data/weather/beijing.json": "a6b32944050cc2a638d09a67be8d7747ca2b0153527f856d85b4813651c91d0a",
    "data/weather/guilin.json": "450d86b2f7121f970e7c48e5a38ad113c8e4289c0356f448221ce1d63d412f94",
    "data/weather/hangzhou.json": "e4ea7c0b10b350cd4c7ba739746e0634d0aa86d77378d858104c0f789f6f64fd",
    "data/weather/shenzhen.json": "533e74a25a72fdc58a0f31746f10dd405611b3ab007f18d0319566deaec5e281",
    "data/weather/xian.json": "7d9e244e1bd64d129cb75b641a09adc8521d9ce082b4a28de7bbb2aadb92cef4",
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
    "medium": "economy",
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

BUDGET_POLICY_VERSION = "budget_policy_v2_0"
BUDGET_POLICY_NAME = "Budget Policy v2.0"
BUDGET_CONTINGENCY_RATIO = 0.10
BUDGET_AUTO_UPGRADE_THRESHOLD = None
BUDGET_FOOD_MEALS_PER_DAY = 2.0
BUDGET_BREAKFAST_MEAL_EQUIVALENT_PER_NIGHT = 0.5
BUDGET_DEFAULT_POIS_PER_DAY = 2

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


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON-compatible content in a platform-independent form."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def canonical_json_sha256(value: Any) -> str:
    """Return SHA-256 over canonical JSON content, not raw file bytes."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def canonical_json_file_sha256(path: Path) -> str:
    """Hash a JSON file by parsed content so LF/CRLF and key order are ignored."""
    return canonical_json_sha256(_read_json(path))


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
        origin: Any = None,
        destination: Any,
        duration: int,
        num_travelers: int = 1,
        budget_level: str = "medium",
        budget_limit: Any = None,
        poi_ids: Optional[Iterable[Any]] = None,
        daily_itinerary: Optional[Iterable[Any]] = None,
        dining_area_id: Optional[str] = None,
        accommodation_area_id: Optional[str] = None,
        hotel_level: Any = None,
        food_level: Any = None,
        transport_mode: Any = None,
        requested_budget_scope: Any = None,
    ) -> Dict[str, Any]:
        city_id = self._require_city_id(destination)
        bundle = self.city_bundle(city_id)
        duration = max(1, int(duration or 1))
        num_travelers = max(1, int(num_travelers or 1))
        nights = max(duration - 1, 0)
        room_count = max(math.ceil(num_travelers / 2), 1)
        parsed_budget_limit = self._positive_float_or_none(budget_limit)
        requested_scope = self._normalize_requested_budget_scope(requested_budget_scope)
        meal_count_equivalent = round(
            BUDGET_FOOD_MEALS_PER_DAY * duration
            + BUDGET_BREAKFAST_MEAL_EQUIVALENT_PER_NIGHT * nights,
            2,
        )

        requested_poi_ids = self._poi_ids_from_itinerary(daily_itinerary) or [
            str(value).strip()
            for value in _as_list(poi_ids)
            if str(value or "").strip()
        ]
        ticket_breakdown = self._ticket_budget(
            bundle["pois"].get("pois", []),
            num_travelers=num_travelers,
            duration=duration,
            poi_ids=requested_poi_ids,
        )
        selected_poi_ids = [
            str(value)
            for value in (ticket_breakdown.get("summary") or {}).get("selected_poi_ids", [])
            if str(value or "").strip()
        ]
        economy_accommodation = self._reference_price_detail(
            bundle["accommodation"].get("accommodation_areas", []),
            "economy",
            preferred_id=accommodation_area_id,
        )
        transport_breakdown = self._local_transport_budget(
            city_id=city_id,
            duration=duration,
            num_travelers=num_travelers,
            accommodation_area_id=economy_accommodation.get("area_id"),
            poi_ids=selected_poi_ids,
            daily_itinerary=daily_itinerary,
            requested_mode=transport_mode,
        )
        if requested_scope == "destination_local_only":
            intercity_transport = self._local_only_intercity_transport_payload(
                origin=origin,
                destination=city_id,
                num_travelers=num_travelers,
            )
        else:
            intercity_transport = self._intercity_transport_budget(
                origin=origin,
                destination=city_id,
                num_travelers=num_travelers,
            )
        intercity_transport_cost = _safe_float(
            intercity_transport.get("total_intercity_transport_cost_cny")
        )
        computed_scope = str(intercity_transport.get("budget_scope") or "destination_local_only")
        scope_complete = self._budget_scope_complete(
            requested_scope=requested_scope,
            computed_scope=computed_scope,
            intercity_transport=intercity_transport,
        )
        preferences = self._budget_preference_flags(
            budget_level=budget_level,
            hotel_level=hotel_level,
            food_level=food_level,
        )

        def build_scheme(
            *,
            hotel_tier: str,
            food_tier: str,
            scheme_id: str,
            reason: str,
        ) -> Dict[str, Any]:
            accommodation_reference = self._reference_price_detail(
                bundle["accommodation"].get("accommodation_areas", []),
                hotel_tier,
                preferred_id=accommodation_area_id,
            )
            dining_reference = self._reference_price_detail(
                bundle["restaurants"].get("dining_areas", []),
                food_tier,
                preferred_id=dining_area_id,
            )
            accommodation_cost = round(
                accommodation_reference["reference_price_cny"] * room_count * nights,
                2,
            )
            food_cost = round(
                dining_reference["reference_price_cny"] * meal_count_equivalent * num_travelers,
                2,
            )
            ticket_cost = round(_safe_float(ticket_breakdown.get("ticket_cost")), 2)
            transport_cost = round(_safe_float(transport_breakdown.get("recommended")), 2)
            local_basic = round(accommodation_cost + food_cost + ticket_cost + transport_cost, 2)
            contingency = round(local_basic * BUDGET_CONTINGENCY_RATIO, 2)
            local_total = round(local_basic + contingency, 2)
            actual_spending = round(local_basic + intercity_transport_cost, 2)
            total = round(local_total + intercity_transport_cost, 2)
            return {
                "scheme_id": scheme_id,
                "reason": reason,
                "hotel_tier": hotel_tier,
                "food_tier": food_tier,
                "transport_mode": transport_breakdown.get("mode"),
                "accommodation_reference": accommodation_reference,
                "dining_reference": dining_reference,
                "accommodation_cost": accommodation_cost,
                "food_cost": food_cost,
                "ticket_cost": ticket_cost,
                "transport_cost": transport_cost,
                "other_cost": 0.0,
                "local_basic_cost": local_basic,
                "contingency_amount": contingency,
                "local_total_recommended": local_total,
                "estimated_actual_spending": actual_spending,
                "total_recommended": total,
                "per_person": round(total / num_travelers, 2),
                "daily": round(total / duration, 2),
            }

        economy_scheme = build_scheme(
            hotel_tier="economy",
            food_tier="economy",
            scheme_id="E",
            reason="economic_baseline",
        )
        candidate_schemes = [economy_scheme]
        preference_candidate = None
        final_scheme = economy_scheme
        upgrade_applied: List[str] = []
        upgrade_decision = (
            "economic_baseline_over_budget"
            if parsed_budget_limit is not None
            and economy_scheme["total_recommended"] > parsed_budget_limit
            else "economic_baseline"
        )
        if preferences["explicit_hotel_tier"] or preferences["explicit_food_tier"]:
            requested_hotel_tier = preferences["explicit_hotel_tier"] or "economy"
            requested_food_tier = preferences["explicit_food_tier"] or "economy"
            preference_candidate = build_scheme(
                hotel_tier=requested_hotel_tier,
                food_tier=requested_food_tier,
                scheme_id="PREF",
                reason="explicit_user_preference",
            )
            candidate_schemes.append(preference_candidate)
            final_scheme = preference_candidate
            if requested_hotel_tier != "economy":
                upgrade_applied.append("accommodation")
            if requested_food_tier != "economy":
                upgrade_applied.append("food")
            upgrade_decision = (
                "explicit_preference_applied_over_budget"
                if parsed_budget_limit is not None
                and preference_candidate["total_recommended"] > parsed_budget_limit
                else "explicit_preference_applied"
            )

        total = final_scheme["total_recommended"]
        local_total = final_scheme["local_total_recommended"]
        local_subtotal = final_scheme["local_basic_cost"]
        buffer_cost = final_scheme["contingency_amount"]
        ticket_cost = final_scheme["ticket_cost"]
        accommodation_cost = final_scheme["accommodation_cost"]
        food_cost = final_scheme["food_cost"]
        transport_cost = final_scheme["transport_cost"]
        other_cost = 0.0
        tier = (
            "comfort"
            if final_scheme["hotel_tier"] == "comfort" or final_scheme["food_tier"] == "comfort"
            else ("premium" if final_scheme["hotel_tier"] == "premium" or final_scheme["food_tier"] == "premium" else "economy")
        )
        budget_gap = None
        remaining_budget = None
        covered_scope_remaining_budget = None
        if parsed_budget_limit is not None:
            budget_gap = round(max(total - parsed_budget_limit, 0.0), 2)
            covered_scope_remaining_budget = round(max(parsed_budget_limit - total, 0.0), 2)
            remaining_budget = covered_scope_remaining_budget if scope_complete else None
        sufficiency_status = self._budget_sufficiency_status(
            total=total,
            budget_limit=parsed_budget_limit,
            scope_complete=scope_complete,
        )
        preference_budget_gap = None
        if preference_candidate and parsed_budget_limit is not None:
            preference_budget_gap = round(
                max(preference_candidate["total_recommended"] - parsed_budget_limit, 0.0),
                2,
            )

        metadata = {
            "poi": bundle["pois"]["metadata"],
            "dining": bundle["restaurants"]["metadata"],
            "accommodation": bundle["accommodation"]["metadata"],
            "transport": bundle["transport"]["metadata"],
        }
        dataset_versions = {
            key: value.get("dataset_version") for key, value in metadata.items()
        }
        source_file_ids = {
            key: value.get("file_id") for key, value in metadata.items()
        }
        snapshot_dates = {
            key: value.get("snapshot_date") for key, value in metadata.items()
        }
        dataset_versions["intercity_transport"] = intercity_transport.get("snapshot_id")
        source_file_ids["intercity_transport"] = "data/intercity_transport/rail_second_class_v1.json"
        snapshot_dates["intercity_transport"] = intercity_transport.get("fare_snapshot_date")
        budget_items = [
            {"category": "transport", "item": "fixed destination-local transport", "estimated_cost": round(transport_cost, 2), "is_essential": True},
            {"category": "accommodation", "item": "fixed accommodation area", "estimated_cost": round(accommodation_cost, 2), "is_essential": True},
            {"category": "food", "item": "fixed dining area meals", "estimated_cost": round(food_cost, 2), "is_essential": True},
            {"category": "tickets", "item": "fixed POI tickets", "estimated_cost": round(ticket_cost, 2), "is_essential": True},
            {"category": "contingency", "item": "10 percent destination-local contingency reserve", "estimated_cost": round(buffer_cost, 2), "is_essential": False},
            {
                "category": "intercity_transport",
                "item": "frozen round-trip rail second-class fare",
                "estimated_cost": round(intercity_transport_cost, 2),
                "is_essential": bool(intercity_transport.get("intercity_transport_included")),
                "notes": intercity_transport.get("disclaimer"),
            },
        ]
        return {
            "origin": origin,
            "destination": destination,
            "city_id": city_id,
            "duration": duration,
            "num_travelers": num_travelers,
            "budget_level": budget_level,
            "normalized_budget_tier": tier,
            "budget_limit": parsed_budget_limit,
            "offline": True,
            "calculation_source": "fixed_reference_cost_model",
            "budget_policy_version": BUDGET_POLICY_VERSION,
            "budget_policy_name": BUDGET_POLICY_NAME,
            "total_min": total,
            "total_max": total,
            "total_recommended": total,
            "final_recommended_total": total,
            "recommended_preparation_amount": total,
            "estimated_actual_spending": final_scheme["estimated_actual_spending"],
            "economic_baseline_total": economy_scheme["total_recommended"],
            "economic_baseline_local_total": economy_scheme["local_total_recommended"],
            "economic_baseline_actual_spending": economy_scheme["estimated_actual_spending"],
            "per_person": round(total / num_travelers, 2),
            "daily": round(total / duration, 2),
            "local_subtotal": round(local_subtotal, 2),
            "local_total_recommended": local_total,
            "destination_local_basic_cost": round(local_subtotal, 2),
            "contingency_amount": buffer_cost,
            "buffer_cost": buffer_cost,
            "remaining_budget": remaining_budget,
            "covered_scope_remaining_budget": covered_scope_remaining_budget,
            "budget_gap": budget_gap,
            "preference_budget_gap": preference_budget_gap,
            "is_over_budget": bool(parsed_budget_limit is not None and total > parsed_budget_limit),
            "can_judge_budget_sufficiency": sufficiency_status != "indeterminate",
            "sufficiency_status": sufficiency_status,
            "requested_budget_scope": requested_scope,
            "computed_budget_scope": computed_scope,
            "scope_complete": scope_complete,
            "budget_complete": not bool((ticket_breakdown.get("summary") or {}).get("unpriceable_count")),
            "intercity_transport_cost": round(intercity_transport_cost, 2),
            "intercity_transport_included": bool(intercity_transport.get("intercity_transport_included")),
            "budget_scope": computed_scope,
            "mandatory_budget_disclaimer": bool(intercity_transport.get("mandatory_budget_disclaimer")),
            "budget_disclaimer": intercity_transport.get("disclaimer"),
            "breakdown": {
                "transport": {
                    "recommended": round(transport_cost, 2),
                    "mode": transport_breakdown.get("mode"),
                    "scope": "destination_local_transport_only",
                    "source": transport_breakdown.get("source"),
                    "fallback_segment_count": transport_breakdown.get("fallback_segment_count"),
                    "segments": transport_breakdown.get("segments"),
                    "calculation_rule": transport_breakdown.get("calculation_rule"),
                },
                "intercity_transport": {
                    "recommended": round(intercity_transport_cost, 2),
                    "included": bool(intercity_transport.get("intercity_transport_included")),
                    "status": intercity_transport.get("status"),
                    "route_supported": bool(intercity_transport.get("route_supported")),
                    "origin": intercity_transport.get("origin"),
                    "destination": intercity_transport.get("destination"),
                    "one_way_fare_per_person_cny": intercity_transport.get("one_way_fare_per_person_cny"),
                    "round_trip_fare_per_person_cny": intercity_transport.get("round_trip_fare_per_person_cny"),
                    "calculation_rule": intercity_transport.get("calculation_rule")
                    or "no intercity fare added when origin is missing or route is unsupported",
                    "disclaimer": intercity_transport.get("disclaimer"),
                    "fare_evidence": intercity_transport.get("fare_evidence"),
                    "evidence_manual_review_complete": intercity_transport.get(
                        "evidence_manual_review_complete"
                    ),
                },
                "accommodation": {
                    "recommended": round(accommodation_cost, 2),
                    "tier": final_scheme["hotel_tier"],
                    "reference_price_cny": final_scheme["accommodation_reference"]["reference_price_cny"],
                    "reference_area_id": final_scheme["accommodation_reference"].get("id"),
                    "price_statistic": final_scheme["accommodation_reference"].get("statistic"),
                    "room_count": room_count,
                    "night_count": nights,
                    "calculation_rule": "room_count = ceil(traveler_count / 2); total_cost = room_count * reference_price_cny * night_count",
                },
                "food": {
                    "recommended": round(food_cost, 2),
                    "tier": final_scheme["food_tier"],
                    "reference_price_cny": final_scheme["dining_reference"]["reference_price_cny"],
                    "reference_area_id": final_scheme["dining_reference"].get("id"),
                    "price_statistic": final_scheme["dining_reference"].get("statistic"),
                    "meal_count_equivalent": meal_count_equivalent,
                    "calculation_rule": "meal_count_equivalent = 2 * day_count + 0.5 * night_count; total_cost = reference_price_cny * meal_count_equivalent * diner_count",
                },
                "tickets": {
                    "recommended": round(ticket_cost, 2),
                    "source": (ticket_breakdown.get("summary") or {}).get("source"),
                    "selected_poi_ids": selected_poi_ids,
                    "calculation_rule": "sum unique final-itinerary fixed adult ticket prices; category estimates are marked as experiment estimates; unpriceable POIs are not guessed",
                },
                "other": {"recommended": round(other_cost, 2), "calculation_rule": "removed by Budget Policy v2.0; personal shopping is excluded"},
                "buffer": {
                    "recommended": buffer_cost,
                    "calculation_rule": "10 percent contingency reserve applies only to destination-local basic cost; intercity rail is excluded",
                },
            },
            "intercity_transport": intercity_transport,
            "ticket_breakdown": ticket_breakdown,
            "transport_breakdown": transport_breakdown,
            "items": budget_items,
            "budget_policy": {
                "version": BUDGET_POLICY_VERSION,
                "name": BUDGET_POLICY_NAME,
                "economic_baseline_first": True,
                "auto_upgrade_threshold": BUDGET_AUTO_UPGRADE_THRESHOLD,
                "auto_upgrade_enabled": False,
                "contingency_ratio": BUDGET_CONTINGENCY_RATIO,
                "default_budget_scope": intercity_transport.get("budget_scope"),
                "requested_budget_scope": requested_scope,
                "computed_budget_scope": computed_scope,
                "scope_complete": scope_complete,
                "sufficiency_status": sufficiency_status,
                "budget_limit": parsed_budget_limit,
                "upgrade_decision": upgrade_decision,
                "upgrade_applied": upgrade_applied,
                "automatic_upgrade_allowed": False,
                "automatic_upgrade_blocked_reasons": ["auto_upgrade_disabled_by_budget_policy_v2_0"],
                "selected_scheme_id": final_scheme["scheme_id"],
                "hotel_tier": final_scheme["hotel_tier"],
                "food_tier": final_scheme["food_tier"],
                "transport_mode": final_scheme["transport_mode"],
                "tier_selection_rule": (
                    "budget_amount_never_changes_hotel_or_food_tier; "
                    "comfort_or_premium_requires_explicit_hotel_or_food_preference"
                ),
                "candidate_schemes": [
                    {
                        "scheme_id": scheme["scheme_id"],
                        "reason": scheme["reason"],
                        "hotel_tier": scheme["hotel_tier"],
                        "food_tier": scheme["food_tier"],
                        "total_recommended": scheme["total_recommended"],
                        "local_total_recommended": scheme["local_total_recommended"],
                    }
                    for scheme in candidate_schemes
                ],
                "explicit_preferences": preferences,
            },
            "dataset_versions": dataset_versions,
            "source_file_ids": source_file_ids,
            "snapshot_dates": snapshot_dates,
            "metadata": {
                "offline": True,
                "live_price_allowed": False,
                "real_time_api_allowed": False,
                "runtime_online_refresh_allowed": False,
                "real_time_price_claim_allowed": False,
                "local_budget_buffer_policy": "10 percent contingency applies to destination-local basic cost only",
                "budget_policy_version": BUDGET_POLICY_VERSION,
                "budget_amount_does_not_change_economic_baseline": True,
            },
        }

    def _normalize_requested_budget_scope(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in {
            "destination_local_only",
            "local_only",
            "destination_only",
            "local",
            "当地",
            "只算当地",
        }:
            return "destination_local_only"
        if text in {
            "local_plus_round_trip_intercity",
            "full_trip",
            "complete_trip",
            "full",
            "总预算",
            "完整旅行",
        }:
            return "local_plus_round_trip_intercity"
        return "local_plus_round_trip_intercity"

    def _budget_scope_complete(
        self,
        *,
        requested_scope: str,
        computed_scope: str,
        intercity_transport: Dict[str, Any],
    ) -> bool:
        if requested_scope == "destination_local_only":
            return computed_scope == "destination_local_only"
        if computed_scope == "local_plus_round_trip_intercity":
            return True
        if intercity_transport.get("status") == "same_city_no_intercity_required":
            return True
        return False

    def _budget_sufficiency_status(
        self,
        *,
        total: float,
        budget_limit: Optional[float],
        scope_complete: bool,
    ) -> str:
        if budget_limit is None:
            return "indeterminate"
        if total > budget_limit:
            return "insufficient"
        if scope_complete:
            return "sufficient"
        return "indeterminate"

    def _local_only_intercity_transport_payload(
        self,
        *,
        origin: Any,
        destination: str,
        num_travelers: int,
    ) -> Dict[str, Any]:
        origin_text = str(origin or "").strip()
        return {
            "provider": "manual_12306_snapshot",
            "offline": True,
            "status": "not_requested_local_only",
            "route_supported": False,
            "intercity_transport_included": False,
            "mandatory_budget_disclaimer": False,
            "budget_scope": "destination_local_only",
            "requested_origin": origin_text,
            "requested_destination": destination,
            "origin": origin_text or None,
            "destination": destination,
            "people_count": max(1, int(num_travelers or 1)),
            "one_way_fare_per_person_cny": None,
            "round_trip_fare_per_person_cny": 0.0,
            "total_intercity_transport_cost_cny": 0.0,
            "real_time_api_allowed": False,
            "runtime_online_refresh_allowed": False,
            "real_time_price_claim_allowed": False,
            "disclaimer": None,
            "recommended_user_action": None,
            "calculation_rule": (
                "intercity transport intentionally excluded because the requested "
                "budget scope is destination_local_only"
            ),
        }

    def _intercity_transport_budget(
        self,
        *,
        origin: Any,
        destination: Any,
        num_travelers: int,
    ) -> Dict[str, Any]:
        try:
            from app.core.intercity_transport_snapshot import query_intercity_rail_snapshot

            return query_intercity_rail_snapshot(
                origin=origin,
                destination=destination,
                people_count=num_travelers,
            )
        except Exception as exc:
            raise FixedDataError(f"intercity transport snapshot unavailable: {exc}") from exc

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
        environment = item.get("environment") or {}
        weather_suitability = environment.get("weather_suitability") or {}
        visit_profile = item.get("visit_profile") or {}
        duration = (visit_profile.get("duration_hours") or {}).get("recommended")
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
            "indoor_outdoor": environment.get("type"),
            "outdoor_ratio": environment.get("outdoor_ratio"),
            "weather_suitability": dict(weather_suitability),
            "rain_suitability": weather_suitability.get("rain"),
            "high_temperature_suitability": weather_suitability.get("high_temperature"),
            "low_temperature_suitability": weather_suitability.get("low_temperature"),
            "visit_intensity": visit_profile.get("intensity"),
            "walking_level": visit_profile.get("walking_level"),
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
        return self._reference_price_detail(items, tier, preferred_id=preferred_id)["reference_price_cny"]

    def _reference_price_detail(
        self,
        items: List[Dict[str, Any]],
        tier: str,
        preferred_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if preferred_id:
            for item in items:
                if preferred_id in {item.get("id"), (item.get("transport") or {}).get("matrix_node_id")}:
                    return {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "area_id": self._first_area_id(item),
                        "matrix_node_id": (item.get("transport") or {}).get("matrix_node_id"),
                        "tier": tier,
                        "reference_price_cny": self._item_reference_price(item, tier),
                        "statistic": "preferred_area_reference_price",
                    }
        prices = [self._item_reference_price(item, tier) for item in items]
        prices = [price for price in prices if price > 0]
        if not prices:
            raise FixedDataError(f"missing reference_price_cny for tier {tier}")
        median = self._median(prices)
        median_item = self._closest_price_item(items, tier, median)
        return {
            "id": median_item.get("id") if median_item else None,
            "name": median_item.get("name") if median_item else None,
            "area_id": self._first_area_id(median_item or {}),
            "matrix_node_id": ((median_item or {}).get("transport") or {}).get("matrix_node_id"),
            "tier": tier,
            "reference_price_cny": round(median, 2),
            "statistic": "citywide_median_reference_price",
        }

    def _item_reference_price(self, item: Dict[str, Any], tier: str) -> float:
        tiers = ((item.get("budget") or {}).get("tiers") or {})
        return _safe_float((tiers.get(tier) or {}).get("reference_price_cny"))

    @staticmethod
    def _median(values: Iterable[Any]) -> float:
        sorted_values = sorted(_safe_float(value) for value in values if _safe_float(value) > 0)
        if not sorted_values:
            return 0.0
        mid = len(sorted_values) // 2
        if len(sorted_values) % 2:
            return float(sorted_values[mid])
        return (sorted_values[mid - 1] + sorted_values[mid]) / 2

    def _closest_price_item(
        self,
        items: List[Dict[str, Any]],
        tier: str,
        target_price: float,
    ) -> Optional[Dict[str, Any]]:
        candidates = [
            (abs(self._item_reference_price(item, tier) - target_price), index, item)
            for index, item in enumerate(items)
            if self._item_reference_price(item, tier) > 0
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda row: (row[0], row[1]))
        return candidates[0][2]

    @staticmethod
    def _first_area_id(item: Dict[str, Any]) -> Optional[str]:
        location = item.get("location") or {}
        area_ids = location.get("area_ids")
        if isinstance(area_ids, list) and area_ids:
            return str(area_ids[0])
        area_id = location.get("area_id") or item.get("area_id")
        return str(area_id) if area_id else None

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

    def _local_transport_budget(
        self,
        *,
        city_id: str,
        duration: int,
        num_travelers: int,
        accommodation_area_id: Optional[str],
        poi_ids: List[str],
        daily_itinerary: Optional[Iterable[Any]],
        requested_mode: Any = None,
    ) -> Dict[str, Any]:
        normalized_requested = str(requested_mode or "").strip()
        mode = "taxi" if any(token in normalized_requested for token in ("打车", "出租", "taxi")) else "public_transit"
        day_poi_ids = self._daily_poi_ids_from_itinerary(daily_itinerary)
        if not day_poi_ids and poi_ids:
            day_poi_ids = [poi_ids[index : index + BUDGET_DEFAULT_POIS_PER_DAY] for index in range(0, len(poi_ids), BUDGET_DEFAULT_POIS_PER_DAY)]
        if not day_poi_ids:
            day_poi_ids = [
                self._default_reference_poi_ids(city_id, duration)
            ]
        day_poi_ids = day_poi_ids[:duration]
        while len(day_poi_ids) < duration:
            day_poi_ids.append([])

        base_area = accommodation_area_id or self._default_accommodation_area_id(city_id)
        median_segment_cost = self._average_transport_cost(city_id, mode)
        segments: List[Dict[str, Any]] = []
        fallback_segment_count = 0
        total = 0.0
        for day_index, day_ids in enumerate(day_poi_ids, start=1):
            route_areas = [base_area]
            for poi_id in day_ids:
                area_id = self._poi_area_id(city_id, poi_id)
                if area_id:
                    route_areas.append(area_id)
            route_areas.append(base_area)
            for origin_area, destination_area in zip(route_areas, route_areas[1:]):
                segment = self._transport_segment_cost(
                    city_id=city_id,
                    origin_area=origin_area,
                    destination_area=destination_area,
                    mode=mode,
                    fallback_cost=median_segment_cost,
                    day_index=day_index,
                )
                fallback_segment_count += 1 if segment.get("fallback_applied") else 0
                total += _safe_float(segment.get("cost_cny"))
                segments.append(segment)
        return {
            "recommended": round(total * num_travelers, 2),
            "per_person": round(total, 2),
            "mode": mode,
            "source": "daily_itinerary_route_matrix" if daily_itinerary else "standard_reference_route_matrix",
            "base_area_id": base_area,
            "fallback_segment_count": fallback_segment_count,
            "segments": segments,
            "calculation_rule": (
                "per day route = accommodation area -> itinerary POIs -> accommodation area; "
                "sum fixed area-matrix public transit costs * traveler_count; missing links use city median segment cost"
            ),
        }

    def _transport_segment_cost(
        self,
        *,
        city_id: str,
        origin_area: Optional[str],
        destination_area: Optional[str],
        mode: str,
        fallback_cost: float,
        day_index: int,
    ) -> Dict[str, Any]:
        origin_text = str(origin_area or "").strip()
        destination_text = str(destination_area or "").strip()
        if not origin_text or not destination_text or origin_text == destination_text:
            return {
                "day": day_index,
                "origin_area_id": origin_text or None,
                "destination_area_id": destination_text or None,
                "mode": "walking",
                "cost_cny": 0.0,
                "fallback_applied": False,
                "note": "same or missing area treated as walking/no local fare",
            }
        document = self._load_city_file("transport", city_id)
        link = self._find_transport_link(document, origin_text, destination_text)
        if not link:
            return {
                "day": day_index,
                "origin_area_id": origin_text,
                "destination_area_id": destination_text,
                "mode": mode,
                "cost_cny": round(fallback_cost, 2),
                "fallback_applied": True,
                "note": "missing matrix link; city median segment fare applied",
            }
        cost_map = link.get("cost_cny") or {}
        cost = _safe_float(cost_map.get(mode))
        if mode not in cost_map:
            cost = fallback_cost
            fallback = True
        else:
            fallback = False
        return {
            "day": day_index,
            "origin_area_id": origin_text,
            "destination_area_id": destination_text,
            "mode": mode,
            "cost_cny": round(cost, 2),
            "duration_minutes": (link.get("duration_minutes") or {}).get(mode),
            "fallback_applied": fallback,
        }

    def _default_accommodation_area_id(self, city_id: str) -> Optional[str]:
        areas = self._load_city_file("accommodation", city_id).get("accommodation_areas", [])
        detail = self._reference_price_detail(areas, "economy")
        return detail.get("area_id")

    def _default_reference_poi_ids(self, city_id: str, duration: int) -> List[str]:
        pois = self._load_city_file("pois", city_id).get("pois", [])
        return [
            str(poi.get("id"))
            for poi in pois[: max(1, duration * BUDGET_DEFAULT_POIS_PER_DAY)]
            if poi.get("id")
        ]

    def _poi_area_id(self, city_id: str, poi_id: Any) -> Optional[str]:
        entity = self.find_entity(poi_id, city_id)
        if entity:
            return entity.get("area_id")
        text = str(poi_id or "").strip()
        if not text:
            return None
        for poi in self._load_city_file("pois", city_id).get("pois", []):
            if text in {str(poi.get("id")), str(poi.get("name"))}:
                return ((poi.get("location") or {}).get("area_id"))
        return None

    def _daily_poi_ids_from_itinerary(self, daily_itinerary: Optional[Iterable[Any]]) -> List[List[str]]:
        result: List[List[str]] = []
        for day in _as_list(daily_itinerary):
            if not isinstance(day, dict):
                continue
            ids = self._poi_ids_from_day(day)
            if ids:
                result.append(ids)
        return result

    def _poi_ids_from_itinerary(self, daily_itinerary: Optional[Iterable[Any]]) -> List[str]:
        seen: List[str] = []
        for day_ids in self._daily_poi_ids_from_itinerary(daily_itinerary):
            for poi_id in day_ids:
                if poi_id not in seen:
                    seen.append(poi_id)
        return seen

    def _poi_ids_from_day(self, day: Dict[str, Any]) -> List[str]:
        raw_items: List[Any] = []
        raw_items.extend(_as_list(day.get("attraction_poi_ids")))
        raw_items.extend(_as_list(day.get("poi_ids")))
        for key in ("attractions", "pois", "activities", "items"):
            raw_items.extend(_as_list(day.get(key)))
        ids: List[str] = []
        for item in raw_items:
            if isinstance(item, str):
                if item.strip():
                    ids.append(item.strip())
            elif isinstance(item, dict):
                poi = item.get("poi") if isinstance(item.get("poi"), dict) else {}
                value = (
                    item.get("poi_id")
                    or item.get("id")
                    or item.get("name")
                    or poi.get("poi_id")
                    or poi.get("id")
                    or poi.get("name")
                )
                if value:
                    ids.append(str(value).strip())
        return [value for index, value in enumerate(ids) if value and value not in ids[:index]]

    @staticmethod
    def _positive_float_or_none(value: Any) -> Optional[float]:
        parsed = _safe_float(value, default=-1.0)
        return parsed if parsed > 0 else None

    def _budget_preference_flags(
        self,
        *,
        budget_level: Any,
        hotel_level: Any,
        food_level: Any,
    ) -> Dict[str, Any]:
        text = " ".join(str(value or "") for value in (budget_level, hotel_level, food_level)).lower()
        save_money = any(token in text for token in ("economy", "省钱", "经济", "便宜", "穷游", "low"))
        explicit_hotel = str(hotel_level or "").strip().lower()
        explicit_food = str(food_level or "").strip().lower()
        explicit_hotel_tier = None
        explicit_food_tier = None
        if explicit_hotel:
            if any(token in explicit_hotel for token in ("五星", "高端", "豪华", "premium", "luxury")):
                explicit_hotel_tier = "premium"
            elif any(token in explicit_hotel for token in ("住好", "品质", "舒服", "舒适", "中档", "中等", "comfort", "medium")):
                explicit_hotel_tier = "comfort"
            elif any(token in explicit_hotel for token in ("经济", "省钱", "青旅", "economy")):
                explicit_hotel_tier = "economy"
        if explicit_food:
            if any(token in explicit_food for token in ("高档", "高端", "豪华", "premium", "luxury", "米其林")):
                explicit_food_tier = "premium"
            elif any(token in explicit_food for token in ("吃好", "美食", "特色", "品质", "舒服", "舒适", "中档", "中等", "comfort", "medium")):
                explicit_food_tier = "comfort"
            elif any(token in explicit_food for token in ("经济", "省钱", "小吃", "快餐", "economy")):
                explicit_food_tier = "economy"
        return {
            "save_money": save_money,
            "explicit_hotel_tier": explicit_hotel_tier,
            "explicit_food_tier": explicit_food_tier,
            "raw_budget_level": budget_level,
            "raw_hotel_level": hotel_level,
            "raw_food_level": food_level,
        }

    def _budget_auto_upgrade_blockers(
        self,
        *,
        intercity_transport: Dict[str, Any],
        ticket_breakdown: Dict[str, Any],
        preferences: Dict[str, Any],
        budget_limit: Optional[float],
    ) -> List[str]:
        reasons: List[str] = []
        if budget_limit is None:
            reasons.append("budget_limit_missing")
        if preferences.get("save_money"):
            reasons.append("user_requested_saving_money")
        if intercity_transport.get("mandatory_budget_disclaimer"):
            status = str(intercity_transport.get("status") or "intercity_scope_incomplete")
            reasons.append(status)
        summary = ticket_breakdown.get("summary") or {}
        if summary.get("unpriceable_count"):
            reasons.append("unpriceable_poi_exists")
        return reasons

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
            if not requested_ids or str(poi.get("id")) in requested_ids or str(poi.get("name")) in requested_ids
        ]
        if not requested_ids:
            selected = selected[: max(1, duration * BUDGET_DEFAULT_POIS_PER_DAY)]
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
                "source": "final_itinerary_pois" if requested_ids else "standard_reference_poi_combo",
                "selected_poi_ids": [
                    str(poi.get("id"))
                    for poi in selected
                    if poi.get("id")
                ],
                "selected_poi_count": len(selected),
                "known_ticket_count": known_count,
                "free_ticket_count": free_count,
                "estimated_ticket_count": estimated_count,
                "estimated_ticket_total_per_person": round(estimated_total, 2),
                "pending_confirmation_count": len(pending),
                "pending_confirmation_pois": pending,
                "unpriceable_count": 0,
                "unpriceable_pois": [],
                "ignored_non_ticket_count": 0,
                "fallback_applied": estimated_count > 0,
                "experiment_estimate_rule": (
                    "unknown adult ticket prices are counted with explicit fixed category estimates "
                    "and marked as experiment estimates; they are not treated as verified live prices"
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
            "family_entertainment": 160.0,
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
    """Return canonical SHA-256 hashes for the fixed data files used by experiments."""
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
            digest = canonical_json_file_sha256(path)
            files.append(
                {
                    "kind": directory,
                    "city_id": city_id,
                    "path": manifest_path,
                    "sha256": digest,
                    "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
                }
            )
    files.sort(key=lambda item: (item["kind"], item["city_id"], item["path"]))
    missing_files.sort()
    combined_source = canonical_json_bytes(files)
    return {
        "schema_version": "fixed_data_manifest_v2",
        "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
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
