"""Unified offline tools for formal tourism experiments.

These tools are the experimental contract used by M1/M2/M3.  They wrap the
fixed five-city data layer and deliberately avoid real-time tourism APIs.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from app.core.fixed_data import FixedDataError, get_fixed_tourism_data
from app.tools.base import BaseTool, ToolResult


TOOL_CONTRACT_VERSION = "ctp-research-tools-v1.0"
RESEARCH_TOOL_NAMES = (
    "poi_search",
    "weather_query",
    "budget_calculator",
    "constraint_checker",
)
GENERATION_TOOL_NAMES = (
    "poi_search",
    "weather_query",
    "budget_calculator",
)


def build_research_tool_catalog(*, include_constraint_checker: bool = True) -> Dict[str, BaseTool]:
    """Return the shared deterministic tool catalog for experiment methods."""
    tools: List[BaseTool] = [
        ResearchPOISearchTool(),
        ResearchWeatherTool(),
        ResearchBudgetCalculatorTool(),
    ]
    if include_constraint_checker:
        tools.append(ResearchConstraintCheckerTool())
    return {tool.name: tool for tool in tools}


def generation_tools() -> List[BaseTool]:
    """Tools visible to generation methods M1/M2/M3."""
    catalog = build_research_tool_catalog(include_constraint_checker=False)
    return [catalog[name] for name in GENERATION_TOOL_NAMES]


def evaluator_tools() -> List[BaseTool]:
    """Tools reserved for method-blind checking after generation."""
    return [ResearchConstraintCheckerTool()]


class ResearchPOISearchTool(BaseTool):
    """Search fixed experiment attractions with a stable input/output contract."""

    name = "poi_search"
    description = "查询固定离线数据中的旅游景点，输入城市、偏好和人群，返回有证据来源的景点列表。"
    external_service = "fixed_offline_dataset"
    parameters = {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "城市名称，如杭州、北京"},
            "destination": {"type": "string", "description": "city 的兼容别名"},
            "preferences": {
                "type": ["array", "string"],
                "items": {"type": "string"},
                "description": "旅游偏好，如历史文化、自然风光、亲子、室内",
            },
            "people": {"type": "string", "description": "出行人群，如亲子、老人、情侣"},
            "limit": {"type": "integer", "default": 6, "minimum": 1, "maximum": 20},
        },
        "required": ["city"],
    }

    def validate_params(self, params: Dict[str, Any]) -> bool:
        return bool(params.get("city") or params.get("destination")) and _is_valid_optional_int(
            params.get("limit"),
            minimum=1,
            maximum=20,
        )

    async def execute(
        self,
        city: Optional[str] = None,
        destination: Optional[str] = None,
        preferences: Any = None,
        people: Any = None,
        limit: int = 6,
        **_: Any,
    ) -> ToolResult:
        city_value = city or destination
        input_payload = {
            "city": city_value,
            "preferences": _as_text_list(preferences),
            "people": _optional_text(people),
            "limit": limit,
        }
        if not city_value:
            return _failed_tool_result(self.name, input_payload, "invalid_arguments", "city is required")
        bounded_limit, limit_error = _parse_int_argument(
            limit,
            name="limit",
            default=6,
            minimum=1,
            maximum=20,
            required=False,
        )
        if limit_error:
            return _failed_tool_result(self.name, input_payload, "invalid_arguments", limit_error)

        try:
            keywords = _keyword_from_preferences(preferences, people)
            raw_results = get_fixed_tourism_data().search_pois(
                city=city_value,
                keywords=keywords or "景点",
                category="attraction",
                limit=bounded_limit,
            )
            if not raw_results and keywords:
                raw_results = get_fixed_tourism_data().search_pois(
                    city=city_value,
                    keywords="景点",
                    category="attraction",
                    limit=bounded_limit,
                )
            attractions = [_format_attraction(item) for item in raw_results]
            status = "success" if attractions else "no_result"
            payload = _tool_payload(
                self.name,
                status=status,
                input_payload=input_payload,
                data={
                    "city": city_value,
                    "preferences": _as_text_list(preferences),
                    "people": _optional_text(people),
                    "attractions": attractions,
                },
                metadata=_metadata_from_rows(attractions, dataset_key="poi_dataset_versions"),
            )
            return ToolResult(
                success=True,
                data=payload,
                metadata=payload["metadata"],
                api_calls=[],
            )
        except FixedDataError as exc:
            return _failed_tool_result(self.name, input_payload, "fixed_data_not_found", str(exc))
        except Exception as exc:  # keep experiment runs table-shaped
            return _failed_tool_result(self.name, input_payload, "internal_error", str(exc))


class ResearchWeatherTool(BaseTool):
    """Query fixed weather scenarios with optional date labels."""

    name = "weather_query"
    description = "查询固定离线天气，输入城市和日期，返回可复现天气场景与每日天气。"
    external_service = "fixed_offline_dataset"
    parameters = {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "城市名称，如杭州、北京"},
            "destination": {"type": "string", "description": "city 的兼容别名"},
            "date": {"type": "string", "description": "开始日期，YYYY-MM-DD；缺省时只返回 day_index"},
            "start_date": {"type": "string", "description": "date 的兼容别名"},
            "days": {"type": "integer", "default": 3, "minimum": 1, "maximum": 5},
            "duration": {"type": "integer", "description": "days 的兼容别名"},
            "scenario_type": {
                "type": "string",
                "enum": ["sunny", "rain", "high_temperature", "low_temperature", "continuous_change"],
                "default": "sunny",
            },
            "weather_scenario": {"type": "string", "description": "scenario_type 的兼容别名"},
        },
        "required": ["city"],
    }

    def validate_params(self, params: Dict[str, Any]) -> bool:
        days_value = params.get("days") if "days" in params else params.get("duration")
        return bool(params.get("city") or params.get("destination")) and _is_valid_optional_int(
            days_value,
            minimum=1,
            maximum=5,
        )

    async def execute(
        self,
        city: Optional[str] = None,
        destination: Optional[str] = None,
        date: Optional[str] = None,
        start_date: Optional[str] = None,
        days: Optional[int] = None,
        duration: Optional[int] = None,
        scenario_type: str = "sunny",
        weather_scenario: Optional[str] = None,
        **_: Any,
    ) -> ToolResult:
        city_value = city or destination
        start_date_value = start_date or date
        raw_days = days if days is not None else duration
        requested_days, days_error = _parse_int_argument(
            raw_days,
            name="days",
            default=3,
            minimum=1,
            maximum=5,
            required=False,
        )
        requested_scenario = weather_scenario or scenario_type or "sunny"
        scenario = _fixed_weather_scenario_for_date(
            city_value,
            start_date_value,
            fallback=requested_scenario,
        )
        input_payload = {
            "city": city_value,
            "date": start_date_value,
            "days": requested_days,
            "scenario_type": requested_scenario,
        }
        if not city_value:
            return _failed_tool_result(self.name, input_payload, "invalid_arguments", "city is required")
        if days_error:
            return _failed_tool_result(self.name, input_payload, "invalid_arguments", days_error)
        if start_date_value and _parse_date(start_date_value) is None:
            return _failed_tool_result(
                self.name,
                input_payload,
                "invalid_arguments",
                "date must use YYYY-MM-DD format",
            )

        try:
            raw = get_fixed_tourism_data().weather_query(
                city=city_value,
                scenario_type=scenario,
                days=requested_days,
            )
            daily_weather = _format_daily_weather(raw.get("daily_forecasts") or [], start_date_value)
            payload = _tool_payload(
                self.name,
                status="success" if daily_weather else "no_result",
                input_payload=input_payload,
                data={
                    "city": raw.get("city") or city_value,
                    "city_id": raw.get("city_id"),
                    "date": start_date_value,
                    "scenario_type": raw.get("scenario_type"),
                    "requested_scenario_type": requested_scenario,
                    "scenario_selection": (
                        "city_date_hash" if start_date_value else "explicit_scenario_or_default"
                    ),
                    "risk_level": raw.get("risk_level"),
                    "daily_weather": daily_weather,
                    "planning_constraints": raw.get("planning_constraints") or {},
                    "weather_adjustment_required": bool(
                        (raw.get("planning_constraints") or {}).get("dynamic_adjustment_required")
                    ),
                },
                metadata={
                    "offline": True,
                    "source_mode": "frozen_offline",
                    "dataset_version": raw.get("dataset_version"),
                    "source_file_id": raw.get("source_file_id"),
                    "record_count": len(daily_weather),
                    "real_time_api_allowed": False,
                    "canonical_city_id": _canonical_weather_city_key(city_value),
                    "weather_date_mapping_rule": (
                        "sha256(canonical_city_id + date) selects one fixed scenario when date is provided"
                        if start_date_value
                        else "scenario_type is used only when no concrete date is provided"
                    ),
                },
            )
            return ToolResult(success=True, data=payload, metadata=payload["metadata"], api_calls=[])
        except FixedDataError as exc:
            return _failed_tool_result(self.name, input_payload, "fixed_data_not_found", str(exc))
        except Exception as exc:
            return _failed_tool_result(self.name, input_payload, "internal_error", str(exc))


class ResearchBudgetCalculatorTool(BaseTool):
    """Calculate fixed-budget estimates from selected POIs and trip size."""

    name = "budget_calculator"
    description = "基于固定离线规则计算预算，输入人数、天数、景点和消费等级，返回结构化费用。"
    external_service = "fixed_offline_dataset"
    parameters = {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "城市名称"},
            "destination": {"type": "string", "description": "city 的兼容别名"},
            "people_count": {"type": "integer", "default": 1, "minimum": 1},
            "num_travelers": {"type": "integer", "description": "people_count 的兼容别名"},
            "days": {"type": "integer", "default": 1, "minimum": 1, "maximum": 5},
            "duration": {"type": "integer", "description": "days 的兼容别名"},
            "attractions": {"type": "array", "items": {"type": "string"}, "description": "景点 ID 或名称"},
            "poi_ids": {"type": "array", "items": {"type": "string"}, "description": "attractions 的兼容别名"},
            "spending_level": {
                "type": "string",
                "enum": ["economy", "medium", "comfort", "luxury", "premium"],
                "default": "medium",
            },
            "budget_level": {"type": "string", "description": "spending_level 的兼容别名"},
        },
        "required": ["city", "days"],
    }

    def validate_params(self, params: Dict[str, Any]) -> bool:
        has_city = bool(params.get("city") or params.get("destination"))
        days_value = params.get("days") if "days" in params else params.get("duration")
        travelers_value = (
            params.get("people_count")
            if "people_count" in params
            else params.get("num_travelers")
        )
        return (
            has_city
            and _is_valid_required_int(days_value, minimum=1, maximum=5)
            and _is_valid_optional_int(travelers_value, minimum=1, maximum=50)
        )

    async def execute(
        self,
        city: Optional[str] = None,
        destination: Optional[str] = None,
        people_count: Optional[int] = None,
        num_travelers: Optional[int] = None,
        days: Optional[int] = None,
        duration: Optional[int] = None,
        attractions: Any = None,
        poi_ids: Any = None,
        spending_level: Optional[str] = None,
        budget_level: Optional[str] = None,
        **_: Any,
    ) -> ToolResult:
        city_value = city or destination
        raw_days = days if days is not None else duration
        raw_travelers = people_count if people_count is not None else num_travelers
        trip_days, days_error = _parse_int_argument(
            raw_days,
            name="days",
            default=None,
            minimum=1,
            maximum=5,
            required=True,
        )
        travelers, travelers_error = _parse_int_argument(
            raw_travelers,
            name="people_count",
            default=1,
            minimum=1,
            maximum=50,
            required=False,
        )
        selected_pois = _as_text_list(poi_ids if poi_ids is not None else attractions)
        level = spending_level or budget_level or "medium"
        input_payload = {
            "city": city_value,
            "people_count": raw_travelers,
            "days": raw_days,
            "attractions": selected_pois,
            "spending_level": level,
        }
        if not city_value:
            return _failed_tool_result(self.name, input_payload, "invalid_arguments", "city is required")
        if days_error:
            return _failed_tool_result(self.name, input_payload, "invalid_arguments", days_error)
        if travelers_error:
            return _failed_tool_result(self.name, input_payload, "invalid_arguments", travelers_error)
        input_payload["people_count"] = travelers
        input_payload["days"] = trip_days

        try:
            raw = get_fixed_tourism_data().calculate_budget(
                destination=city_value,
                duration=trip_days,
                num_travelers=travelers,
                budget_level=level,
                poi_ids=selected_pois,
            )
            payload = _tool_payload(
                self.name,
                status="success",
                input_payload=input_payload,
                data={
                    "city": city_value,
                    "people_count": travelers,
                    "days": trip_days,
                    "spending_level": level,
                    "currency": "CNY",
                    "total": raw.get("total_recommended"),
                    "per_person": raw.get("per_person"),
                    "daily_average": raw.get("daily"),
                    "breakdown": raw.get("breakdown") or {},
                    "items": raw.get("items") or [],
                    "ticket_breakdown": raw.get("ticket_breakdown") or {},
                },
                metadata={
                    "offline": True,
                    "source_mode": "frozen_offline",
                    "dataset_versions": raw.get("dataset_versions") or {},
                    "source_file_ids": raw.get("source_file_ids") or {},
                    "record_count": len(raw.get("items") or []),
                    "real_time_api_allowed": False,
                    "calculation_source": raw.get("calculation_source"),
                },
            )
            return ToolResult(success=True, data=payload, metadata=payload["metadata"], api_calls=[])
        except FixedDataError as exc:
            return _failed_tool_result(self.name, input_payload, "fixed_data_not_found", str(exc))
        except Exception as exc:
            return _failed_tool_result(self.name, input_payload, "internal_error", str(exc))


class ResearchConstraintCheckerTool(BaseTool):
    """Method-blind deterministic checker for hard travel constraints."""

    name = "constraint_checker"
    description = "检查预算、天气、天数和景点数量等硬约束；正式实验中作为独立评价工具使用。"
    external_service = "fixed_offline_evaluator"
    parameters = {
        "type": "object",
        "properties": {
            "request": {"type": "object", "description": "规范化案例输入或 slots"},
            "plan": {"type": "object", "description": "统一方法输出"},
            "constraints": {"type": "object", "description": "可程序检查的硬约束"},
        },
        "required": ["plan"],
    }

    def validate_params(self, params: Dict[str, Any]) -> bool:
        return isinstance(params.get("plan"), dict)

    async def execute(
        self,
        plan: Dict[str, Any],
        request: Optional[Dict[str, Any]] = None,
        constraints: Optional[Any] = None,
        **_: Any,
    ) -> ToolResult:
        request_payload = request or {}
        constraint_payload = _normalize_constraint_payload(constraints)
        checks = _check_constraints(plan, request_payload, constraint_payload)
        applicable = [item for item in checks if item["status"] != "NA"]
        passed = [item for item in applicable if item["passed"] is True]
        failed = [item for item in applicable if item["passed"] is False]
        payload = _tool_payload(
            self.name,
            status="success",
            input_payload={
                "request": request_payload,
                "constraints": constraint_payload,
            },
            data={
                "all_passed": not failed,
                "applicable_count": len(applicable),
                "passed_count": len(passed),
                "failed_count": len(failed),
                "checks": checks,
            },
            metadata={
                "offline": True,
                "source_mode": "deterministic_evaluator",
                "contract": TOOL_CONTRACT_VERSION,
                "real_time_api_allowed": False,
            },
        )
        return ToolResult(success=True, data=payload, metadata=payload["metadata"], api_calls=[])


def _tool_payload(
    tool_name: str,
    *,
    status: str,
    input_payload: Dict[str, Any],
    data: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
    error: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "schema_version": "research_tool_result_v1",
        "tool_contract_version": TOOL_CONTRACT_VERSION,
        "tool_name": tool_name,
        "status": status,
        "success": status in {"success", "no_result"},
        "input": input_payload,
        "data": data,
        "error": error,
        "metadata": {
            "offline": True,
            "source_mode": "frozen_offline",
            "real_time_api_allowed": False,
            **(metadata or {}),
        },
    }


def _failed_tool_result(
    tool_name: str,
    input_payload: Dict[str, Any],
    code: str,
    message: str,
) -> ToolResult:
    payload = _tool_payload(
        tool_name,
        status="failed",
        input_payload=input_payload,
        data={},
        error={"code": code, "message": message, "retryable": False},
        metadata={"error_code": code},
    )
    return ToolResult(
        success=False,
        data=payload,
        error=message,
        metadata=payload["metadata"],
        api_calls=[],
    )


def _format_attraction(item: Dict[str, Any]) -> Dict[str, Any]:
    ticket_value = item.get("ticket_price_value")
    return {
        "poi_id": item.get("id"),
        "name": item.get("name"),
        "city": item.get("city"),
        "city_id": item.get("city_id"),
        "category": item.get("category") or item.get("type"),
        "tags": item.get("tags") or [],
        "indoor_outdoor": item.get("indoor_outdoor"),
        "recommended_duration_hours": item.get("visit_duration_hours") or item.get("recommended_duration"),
        "ticket_price_cny": ticket_value,
        "ticket_price_known": ticket_value is not None,
        "address": item.get("address"),
        "transport_node_id": item.get("transport_node_id") or item.get("matrix_node_id"),
        "evidence": {
            "dataset_version": item.get("dataset_version"),
            "source_file_id": item.get("source_file_id"),
            "snapshot_date": item.get("snapshot_date"),
            "offline": True,
        },
    }


def _format_daily_weather(rows: Iterable[Dict[str, Any]], start_date: Optional[str]) -> List[Dict[str, Any]]:
    parsed_start = _parse_date(start_date)
    formatted: List[Dict[str, Any]] = []
    for row in rows:
        day_index = int(row.get("day_index") or len(formatted) + 1)
        labeled_date = None
        if parsed_start is not None:
            labeled_date = (parsed_start + timedelta(days=day_index - 1)).strftime("%Y-%m-%d")
        formatted.append(
            {
                "day_index": day_index,
                "date": labeled_date,
                "state": row.get("state"),
                "weather": row.get("weather") or row.get("day_weather"),
                "temperature_min_c": row.get("temperature_min_c") or row.get("min_temp"),
                "temperature_max_c": row.get("temperature_max_c") or row.get("max_temp"),
                "precipitation_mm": row.get("precipitation_mm"),
                "risk_level": row.get("risk_level"),
                "risk_tags": row.get("risk_tags") or [],
                "suitable_periods": row.get("suitable_periods") or [],
                "avoid_periods": row.get("avoid_periods") or [],
            }
        )
    return formatted


def _metadata_from_rows(rows: List[Dict[str, Any]], *, dataset_key: str) -> Dict[str, Any]:
    versions = sorted(
        {
            ((row.get("evidence") or {}).get("dataset_version"))
            for row in rows
            if (row.get("evidence") or {}).get("dataset_version")
        }
    )
    source_files = sorted(
        {
            ((row.get("evidence") or {}).get("source_file_id"))
            for row in rows
            if (row.get("evidence") or {}).get("source_file_id")
        }
    )
    return {
        "offline": True,
        "source_mode": "frozen_offline",
        dataset_key: versions,
        "source_file_ids": source_files,
        "record_count": len(rows),
        "real_time_api_allowed": False,
    }


def _check_constraints(
    plan: Dict[str, Any],
    request: Dict[str, Any],
    constraints: Dict[str, Any],
) -> List[Dict[str, Any]]:
    expected_days = _first_present(
        constraints.get("days"),
        constraints.get("duration"),
        request.get("days"),
        request.get("duration"),
        request.get("trip_days"),
    )
    itinerary = _first_present(plan.get("daily_itinerary"), plan.get("itinerary"), [])
    if isinstance(itinerary, dict):
        itinerary = itinerary.get("days") or []
    actual_days = len(itinerary) if isinstance(itinerary, list) else None

    budget_limit = _first_present(
        constraints.get("budget_limit"),
        constraints.get("max_budget"),
        request.get("budget"),
        request.get("budget_limit"),
    )
    budget_payload = plan.get("budget") or {}
    budget_total = _first_present(
        budget_payload.get("total"),
        budget_payload.get("total_recommended"),
        budget_payload.get("estimated_total"),
    )

    weather_payload = plan.get("weather") or {}
    weather_adjustments = plan.get("weather_adjustments") or []
    requires_weather_adjustment = bool(
        constraints.get("weather_adjustment_required")
        or weather_payload.get("weather_adjustment_required")
        or _contains_rain(weather_payload)
    )

    attractions = _collect_plan_attractions(plan)
    min_attractions = _first_present(constraints.get("min_attractions"), request.get("min_attractions"))
    max_attractions = _first_present(constraints.get("max_attractions"), request.get("max_attractions"))

    return [
        _check_item(
            "trip_days",
            expected_days is None,
            actual_days is not None and actual_days == _safe_int(expected_days),
            {"expected": expected_days, "actual": actual_days},
        ),
        _check_item(
            "budget_limit",
            budget_limit is None,
            budget_total is not None and _safe_float(budget_total) <= _safe_float(budget_limit),
            {"limit": budget_limit, "actual": budget_total},
        ),
        _check_item(
            "weather_adjustment",
            not requires_weather_adjustment,
            bool(weather_adjustments),
            {"required": requires_weather_adjustment, "adjustment_count": len(weather_adjustments)},
        ),
        _check_item(
            "min_attractions",
            min_attractions is None,
            len(attractions) >= _safe_int(min_attractions),
            {"minimum": min_attractions, "actual": len(attractions)},
        ),
        _check_item(
            "max_attractions",
            max_attractions is None,
            len(attractions) <= _safe_int(max_attractions),
            {"maximum": max_attractions, "actual": len(attractions)},
        ),
    ]


def _normalize_constraint_payload(constraints: Optional[Any]) -> Dict[str, Any]:
    if isinstance(constraints, dict):
        return dict(constraints)
    if constraints is None:
        return {}
    items = _as_text_list(constraints)
    text = " ".join(items)
    payload: Dict[str, Any] = {"raw_constraints": items}
    if any(word in text for word in ("雨", "下雨", "天气", "高温", "低温", "室内")):
        payload["weather_adjustment_required"] = True
    return payload


def _check_item(name: str, not_applicable: bool, passed: bool, details: Dict[str, Any]) -> Dict[str, Any]:
    if not_applicable:
        return {"name": name, "status": "NA", "passed": None, "details": details}
    return {"name": name, "status": "passed" if passed else "failed", "passed": bool(passed), "details": details}


def _collect_plan_attractions(plan: Dict[str, Any]) -> List[Any]:
    direct = plan.get("attractions")
    if isinstance(direct, list):
        return direct
    daily = plan.get("daily_itinerary") or []
    if not isinstance(daily, list):
        return []
    results: List[Any] = []
    for day in daily:
        if isinstance(day, dict):
            items = day.get("attractions") or day.get("pois") or []
            if isinstance(items, list):
                results.extend(items)
    return results


def _contains_rain(weather_payload: Any) -> bool:
    text = str(weather_payload).lower()
    return "rain" in text or "雨" in text


def _keyword_from_preferences(preferences: Any, people: Any) -> str:
    terms = [*_as_text_list(preferences), *_as_text_list(people)]
    return " ".join(term for term in terms if term)


def _fixed_weather_scenario_for_date(
    city: Any,
    start_date: Optional[str],
    *,
    fallback: str,
) -> str:
    if not start_date:
        return fallback or "sunny"
    scenarios = ["sunny", "rain", "high_temperature", "low_temperature", "continuous_change"]
    key = f"{_canonical_weather_city_key(city)}|{start_date}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return scenarios[int(digest[:8], 16) % len(scenarios)]


def _canonical_weather_city_key(city: Any) -> str:
    try:
        city_id = get_fixed_tourism_data().resolve_city_id(city)
    except Exception:
        city_id = None
    return city_id or str(city or "").strip().lower()


def _as_text_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        return [str(item).strip() for item in value.values() if str(item).strip()]
    if isinstance(value, Iterable):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _optional_text(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _is_valid_optional_int(value: Any, *, minimum: int, maximum: int) -> bool:
    _, error = _parse_int_argument(
        value,
        name="value",
        default=None,
        minimum=minimum,
        maximum=maximum,
        required=False,
    )
    return error is None


def _is_valid_required_int(value: Any, *, minimum: int, maximum: int) -> bool:
    _, error = _parse_int_argument(
        value,
        name="value",
        default=None,
        minimum=minimum,
        maximum=maximum,
        required=True,
    )
    return error is None


def _parse_int_argument(
    value: Any,
    *,
    name: str,
    default: Optional[int],
    minimum: int,
    maximum: int,
    required: bool,
) -> tuple[Optional[int], Optional[str]]:
    if value is None or value == "":
        if required:
            return None, f"{name} is required"
        return default, None
    if isinstance(value, bool):
        return None, f"{name} must be an integer between {minimum} and {maximum}"
    try:
        if isinstance(value, float):
            if not value.is_integer():
                raise ValueError
            parsed = int(value)
        elif isinstance(value, int):
            parsed = value
        elif isinstance(value, str):
            stripped = value.strip()
            digits = stripped[1:] if stripped[:1] in {"+", "-"} else stripped
            if not digits.isdigit():
                raise ValueError
            parsed = int(stripped)
        else:
            raise ValueError
    except (TypeError, ValueError):
        return None, f"{name} must be an integer between {minimum} and {maximum}"
    if parsed < minimum or parsed > maximum:
        return None, f"{name} must be between {minimum} and {maximum}"
    return parsed, None


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _parse_date(value: Optional[str]):
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None
