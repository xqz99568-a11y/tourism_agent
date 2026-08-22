"""Unified offline tools for formal tourism experiments.

These tools are the experimental contract used by M1/M2/M3.  They wrap the
fixed five-city data layer and deliberately avoid real-time tourism APIs.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from app.core.fixed_data import FixedDataError, get_fixed_tourism_data
from app.core.qweather_snapshot import (
    QWEATHER_DEFAULT_WEATHER_QUERY_DAYS,
    QWEATHER_MAX_QUERY_DAYS,
    QWeatherSnapshotError,
    load_qweather_snapshot_manifest,
    normalize_qweather_city_id,
    query_qweather_snapshot,
)
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
    """Query the frozen QWeather snapshot with optional date labels."""

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
            "days": {"type": "integer", "default": 3, "minimum": 1, "maximum": QWEATHER_MAX_QUERY_DAYS},
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
            maximum=QWEATHER_MAX_QUERY_DAYS,
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
        default_days = 3 if start_date_value else QWEATHER_DEFAULT_WEATHER_QUERY_DAYS
        requested_days, days_error = _parse_int_argument(
            raw_days,
            name="days",
            default=default_days,
            minimum=1,
            maximum=QWEATHER_MAX_QUERY_DAYS,
            required=False,
        )
        date_defaulted = False
        if not start_date_value:
            start_date_value = str(load_qweather_snapshot_manifest().get("forecast_start_date") or "")
            date_defaulted = True
        requested_scenario = weather_scenario or scenario_type or "sunny"
        input_payload = {
            "city": city_value,
            "date": start_date_value,
            "days": requested_days,
            "scenario_type": requested_scenario,
            "date_defaulted_to_snapshot_start": date_defaulted,
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
            raw = query_qweather_snapshot(
                city=city_value,
                start_date=start_date_value,
                days=requested_days,
            )
            daily_weather = list(raw.get("daily_weather") or [])
            coverage_status = str(raw.get("coverage_status") or "out_of_range")
            payload = _tool_payload(
                self.name,
                status="success",
                input_payload=input_payload,
                data={
                    "city": raw.get("city") or city_value,
                    "city_id": raw.get("city_id"),
                    "date": raw.get("date") or start_date_value,
                    "start_date": raw.get("start_date") or start_date_value,
                    "end_date": raw.get("end_date"),
                    "provider": raw.get("provider"),
                    "location_id": raw.get("location_id"),
                    "scenario_type": raw.get("scenario_type"),
                    "requested_scenario_type": requested_scenario,
                    "scenario_selection": raw.get("scenario_selection"),
                    "weather_type": raw.get("weather_type"),
                    "risk_level": raw.get("risk_level"),
                    "risk_tags": raw.get("risk_tags") or [],
                    "requested_days": raw.get("requested_days"),
                    "coverage_days": raw.get("coverage_days"),
                    "coverage_status": coverage_status,
                    "covered_dates": raw.get("covered_dates") or [],
                    "missing_dates": raw.get("missing_dates") or [],
                    "forecast_start_date": raw.get("forecast_start_date"),
                    "forecast_end_date": raw.get("forecast_end_date"),
                    "snapshot_forecast_start_date": raw.get("snapshot_forecast_start_date"),
                    "snapshot_forecast_end_date": raw.get("snapshot_forecast_end_date"),
                    "daily_weather": daily_weather,
                    "daily_forecasts": daily_weather,
                    "forecast": daily_weather,
                    "planning_constraints": raw.get("planning_constraints") or {},
                    "weather_adjustment_required": bool(raw.get("weather_adjustment_required")),
                    "warnings": raw.get("warnings") or [],
                    "applied_rules": raw.get("applied_rules") or [],
                    "snapshot_id": raw.get("snapshot_id"),
                    "snapshot_combined_sha256": raw.get("snapshot_combined_sha256"),
                    "metadata": raw.get("metadata") or {},
                    "date_defaulted_to_snapshot_start": date_defaulted or bool(raw.get("date_defaulted_to_snapshot_start")),
                },
                metadata={
                    "offline": True,
                    "source_mode": "qweather_frozen_snapshot",
                    "dataset_version": raw.get("dataset_version"),
                    "source_file_id": raw.get("source_file_id"),
                    "record_count": len(daily_weather),
                    "real_time_api_allowed": False,
                    "canonical_city_id": normalize_qweather_city_id(city_value),
                    "coverage_status": coverage_status,
                    "snapshot_id": raw.get("snapshot_id"),
                    "snapshot_combined_sha256": raw.get("snapshot_combined_sha256"),
                    "weather_date_mapping_rule": "city_id + requested date range selects rows from frozen QWeather snapshot",
                    "date_defaulted_to_snapshot_start": date_defaulted,
                },
            )
            return ToolResult(success=True, data=payload, metadata=payload["metadata"], api_calls=[])
        except QWeatherSnapshotError as exc:
            return _failed_tool_result(self.name, input_payload, "qweather_snapshot_unavailable", str(exc))
        except FixedDataError as exc:
            return _failed_tool_result(self.name, input_payload, "fixed_data_not_found", str(exc))
        except Exception as exc:
            return _failed_tool_result(self.name, input_payload, "internal_error", str(exc))

    external_service = "qweather_frozen_snapshot"


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
            "origin": {
                "type": "string",
                "description": "Optional departure city for frozen round-trip rail fare.",
            },
            "from_city": {
                "type": "string",
                "description": "Alias of origin.",
            },
            "people_count": {"type": "integer", "default": 1, "minimum": 1},
            "num_travelers": {"type": "integer", "description": "people_count 的兼容别名"},
            "days": {"type": "integer", "default": 1, "minimum": 1, "maximum": 5},
            "duration": {"type": "integer", "description": "days 的兼容别名"},
            "attractions": {"type": "array", "items": {"type": "string"}, "description": "景点 ID 或名称"},
            "poi_ids": {"type": "array", "items": {"type": "string"}, "description": "attractions 的兼容别名"},
            "daily_itinerary": {
                "type": "array",
                "items": {"type": "object"},
                "description": "最终逐日行程，用于预算工具按实际景点和路线计价。",
            },
            "budget_limit": {
                "type": "number",
                "description": "用户总预算上限；默认按总预算理解。",
            },
            "budget_basis": {
                "type": "string",
                "enum": ["total", "per_person"],
                "description": "用户原始预算口径；budget_limit 始终是换算后的总预算上限。",
            },
            "spending_level": {
                "type": "string",
                "enum": ["economy", "medium", "comfort", "luxury", "premium"],
                "default": "medium",
            },
            "budget_level": {"type": "string", "description": "spending_level 的兼容别名"},
            "hotel_level": {"type": "string", "description": "住宿偏好"},
            "food_level": {"type": "string", "description": "餐饮偏好"},
            "transport_mode": {"type": "string", "description": "市内交通偏好"},
            "requested_budget_scope": {
                "type": "string",
                "description": "预算范围：destination_local_only 或 local_plus_round_trip_intercity",
            },
            "intercity_transport_included": {
                "type": "boolean",
                "description": "用户需求层面是否期望纳入冻结城际往返交通费用。",
            },
            "mandatory_budget_disclaimer": {
                "type": "boolean",
                "description": "是否必须提醒用户当前预算未覆盖城际大交通。",
            },
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
        origin: Optional[str] = None,
        from_city: Optional[str] = None,
        people_count: Optional[int] = None,
        num_travelers: Optional[int] = None,
        days: Optional[int] = None,
        duration: Optional[int] = None,
        attractions: Any = None,
        poi_ids: Any = None,
        daily_itinerary: Optional[List[Dict[str, Any]]] = None,
        budget_limit: Any = None,
        budget_basis: Optional[str] = None,
        spending_level: Optional[str] = None,
        budget_level: Optional[str] = None,
        hotel_level: Optional[str] = None,
        food_level: Optional[str] = None,
        transport_mode: Optional[str] = None,
        requested_budget_scope: Optional[str] = None,
        intercity_transport_included: Optional[bool] = None,
        mandatory_budget_disclaimer: Optional[bool] = None,
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
            "origin": origin or from_city,
            "people_count": raw_travelers,
            "days": raw_days,
            "attractions": selected_pois,
            "daily_itinerary": daily_itinerary or [],
            "budget_limit": budget_limit,
            "budget_basis": budget_basis,
            "spending_level": level,
            "hotel_level": hotel_level,
            "food_level": food_level,
            "transport_mode": transport_mode,
            "requested_budget_scope": requested_budget_scope,
            "intercity_transport_included": intercity_transport_included,
            "mandatory_budget_disclaimer": mandatory_budget_disclaimer,
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
                origin=origin or from_city,
                destination=city_value,
                duration=trip_days,
                num_travelers=travelers,
                budget_level=level,
                budget_limit=budget_limit,
                poi_ids=selected_pois,
                daily_itinerary=daily_itinerary,
                hotel_level=hotel_level,
                food_level=food_level,
                transport_mode=transport_mode,
                requested_budget_scope=requested_budget_scope,
            )
            effective_mandatory_disclaimer = bool(
                raw.get("mandatory_budget_disclaimer")
                or mandatory_budget_disclaimer
            )
            effective_budget_disclaimer = raw.get("budget_disclaimer")
            if effective_mandatory_disclaimer and not effective_budget_disclaimer:
                effective_budget_disclaimer = "当前预算不包含出发地与目的地之间的往返城际大交通。"
            payload = _tool_payload(
                self.name,
                status="success",
                input_payload=input_payload,
                data={
                    "city": city_value,
                    "origin": origin or from_city,
                    "people_count": travelers,
                    "days": trip_days,
                    "spending_level": level,
                    "currency": "CNY",
                    "total": raw.get("total_recommended"),
                    "final_recommended_total": raw.get("final_recommended_total"),
                    "recommended_preparation_amount": raw.get("recommended_preparation_amount"),
                    "estimated_actual_spending": raw.get("estimated_actual_spending"),
                    "economic_baseline_total": raw.get("economic_baseline_total"),
                    "economic_baseline_local_total": raw.get("economic_baseline_local_total"),
                    "budget_limit": raw.get("budget_limit"),
                    "budget_basis": budget_basis,
                    "remaining_budget": raw.get("remaining_budget"),
                    "covered_scope_remaining_budget": raw.get("covered_scope_remaining_budget"),
                    "budget_gap": raw.get("budget_gap"),
                    "is_over_budget": raw.get("is_over_budget"),
                    "requested_budget_scope": raw.get("requested_budget_scope"),
                    "computed_budget_scope": raw.get("computed_budget_scope"),
                    "scope_complete": raw.get("scope_complete"),
                    "sufficiency_status": raw.get("sufficiency_status"),
                    "local_total": raw.get("local_total_recommended"),
                    "local_total_recommended": raw.get("local_total_recommended"),
                    "per_person": raw.get("per_person"),
                    "daily_average": raw.get("daily"),
                    "budget_scope": raw.get("budget_scope"),
                    "budget_policy_version": raw.get("budget_policy_version"),
                    "budget_policy": raw.get("budget_policy") or {},
                    "budget_complete": raw.get("budget_complete"),
                    "can_judge_budget_sufficiency": raw.get("can_judge_budget_sufficiency"),
                    "contingency_amount": raw.get("contingency_amount"),
                    "intercity_transport_cost": raw.get("intercity_transport_cost"),
                    "intercity_transport_included": raw.get("intercity_transport_included"),
                    "real_time_api_allowed": False,
                    "runtime_online_refresh_allowed": False,
                    "real_time_price_claim_allowed": False,
                    "mandatory_budget_disclaimer": effective_mandatory_disclaimer,
                    "budget_disclaimer": effective_budget_disclaimer,
                    "intercity_transport": raw.get("intercity_transport") or {},
                    "breakdown": raw.get("breakdown") or {},
                    "transport_breakdown": raw.get("transport_breakdown") or {},
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
                    "runtime_online_refresh_allowed": False,
                    "real_time_price_claim_allowed": False,
                    "calculation_source": raw.get("calculation_source"),
                    "budget_policy_version": raw.get("budget_policy_version"),
                    "budget_scope": raw.get("budget_scope"),
                    "requested_budget_scope": raw.get("requested_budget_scope"),
                    "computed_budget_scope": raw.get("computed_budget_scope"),
                    "scope_complete": raw.get("scope_complete"),
                    "sufficiency_status": raw.get("sufficiency_status"),
                    "intercity_snapshot_id": (raw.get("intercity_transport") or {}).get("snapshot_id"),
                    "intercity_snapshot_combined_sha256": (raw.get("intercity_transport") or {}).get("snapshot_combined_sha256"),
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
        "outdoor_ratio": item.get("outdoor_ratio"),
        "weather_suitability": item.get("weather_suitability") or {},
        "rain_suitability": item.get("rain_suitability"),
        "high_temperature_suitability": item.get("high_temperature_suitability"),
        "low_temperature_suitability": item.get("low_temperature_suitability"),
        "visit_intensity": item.get("visit_intensity"),
        "walking_level": item.get("walking_level"),
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

    attraction_refs = _collect_plan_attraction_refs(plan)
    rain_attraction_refs = _rain_scoped_attraction_refs(
        attraction_refs,
        weather_payload,
    )
    attractions = [ref["raw"] for ref in attraction_refs]
    city_id = _constraint_city_id(plan, request, constraints)
    resolved_attractions = _resolve_attraction_refs(attraction_refs, city_id)
    rain_resolved_attractions = _resolve_attraction_refs(rain_attraction_refs, city_id)
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
        _poi_existence_check(attraction_refs, resolved_attractions, city_id),
        _duplicate_attractions_check(attraction_refs, resolved_attractions),
        _must_include_pois_check(attraction_refs, resolved_attractions, request, constraints, city_id),
        _forbidden_pois_check(attraction_refs, resolved_attractions, request, constraints, city_id),
        _rain_attraction_suitability_check(
            weather_payload,
            rain_attraction_refs,
            rain_resolved_attractions,
        ),
        _senior_accessibility_check(request, constraints, attraction_refs, resolved_attractions),
        _tool_evidence_check(plan, constraints),
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
            for key in ("attraction_poi_ids", "poi_ids", "attraction_ids", "selected_poi_ids"):
                values = day.get(key)
                if isinstance(values, list):
                    results.extend(values)
            items = day.get("attractions") or day.get("pois") or []
            if isinstance(items, list):
                results.extend(items)
    return results


def _collect_plan_attraction_refs(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    direct_refs: List[Dict[str, Any]] = []
    daily_refs: List[Dict[str, Any]] = []
    direct = plan.get("attractions")
    if isinstance(direct, list):
        direct_refs.extend(_coerce_attraction_refs(direct, day_index=None))

    daily = plan.get("daily_itinerary") or plan.get("itinerary") or []
    if isinstance(daily, dict):
        daily = daily.get("days") or []
    if isinstance(daily, list):
        for index, day in enumerate(daily, start=1):
            if not isinstance(day, dict):
                continue
            day_index = _safe_int(day.get("day") or day.get("day_index") or index)
            for key in ("attraction_poi_ids", "poi_ids", "attraction_ids", "selected_poi_ids"):
                items = day.get(key)
                if isinstance(items, list):
                    daily_refs.extend(_coerce_attraction_refs(items, day_index=day_index))
            for key in ("attractions", "pois", "poi_list"):
                items = day.get(key)
                if isinstance(items, list):
                    daily_refs.extend(_coerce_attraction_refs(items, day_index=day_index))
            activities = day.get("activities") or day.get("schedule") or []
            if isinstance(activities, list):
                daily_refs.extend(_coerce_attraction_refs(activities, day_index=day_index))
    task_type = str(plan.get("task_type") or "").strip().lower()
    if daily_refs and task_type not in {"attraction_recommendation", "budget_query"}:
        return daily_refs
    return [*direct_refs, *daily_refs]


def _rain_scoped_attraction_refs(
    refs: List[Dict[str, Any]],
    weather_payload: Any,
) -> List[Dict[str, Any]]:
    rainy_days = _rainy_day_indexes(weather_payload)
    if not rainy_days:
        return refs
    scoped = [
        ref
        for ref in refs
        if _safe_int(ref.get("day_index")) in rainy_days
    ]
    return scoped or refs


def _coerce_attraction_refs(items: List[Any], *, day_index: Optional[int]) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for item in items:
        ref = _coerce_attraction_ref(item, day_index=day_index)
        if ref is not None:
            refs.append(ref)
    return refs


def _coerce_attraction_ref(item: Any, *, day_index: Optional[int]) -> Optional[Dict[str, Any]]:
    if isinstance(item, str):
        text = item.strip()
        if not text:
            return None
        return {"id": None, "name": text, "identifier": text, "day_index": day_index, "raw": item}
    if not isinstance(item, dict):
        return None
    nested = item.get("poi") if isinstance(item.get("poi"), dict) else {}
    poi_id = _first_present(
        item.get("poi_id"),
        item.get("id"),
        item.get("attraction_id"),
        nested.get("poi_id"),
        nested.get("id"),
    )
    name = _first_present(
        item.get("name"),
        item.get("poi_name"),
        item.get("attraction_name"),
        item.get("title"),
        nested.get("name"),
        nested.get("poi_name"),
    )
    identifier = _first_present(poi_id, name)
    if not identifier:
        return None
    return {
        "id": str(poi_id).strip() if poi_id else None,
        "name": str(name).strip() if name else None,
        "identifier": str(identifier).strip(),
        "day_index": day_index,
        "raw": item,
    }


def _constraint_city_id(plan: Dict[str, Any], request: Dict[str, Any], constraints: Dict[str, Any]) -> Optional[str]:
    candidates = [
        constraints.get("city"),
        constraints.get("destination"),
        request.get("city"),
        request.get("destination"),
        request.get("destination_city"),
    ]
    weather = plan.get("weather") if isinstance(plan.get("weather"), dict) else {}
    budget = plan.get("budget") if isinstance(plan.get("budget"), dict) else {}
    candidates.extend([weather.get("city_id"), weather.get("city"), budget.get("city_id"), budget.get("city")])
    for ref in _collect_plan_attraction_refs(plan):
        raw = ref.get("raw")
        if isinstance(raw, dict):
            candidates.extend([raw.get("city_id"), raw.get("city")])
    dataset = get_fixed_tourism_data()
    for candidate in candidates:
        city_id = dataset.resolve_city_id(candidate)
        if city_id:
            return city_id
    return None


def _resolve_attraction_refs(refs: List[Dict[str, Any]], city_id: Optional[str]) -> List[Dict[str, Any]]:
    dataset = get_fixed_tourism_data()
    resolved: List[Dict[str, Any]] = []
    for ref in refs:
        entity = None
        matched_by = None
        for key in ("id", "name", "identifier"):
            value = ref.get(key)
            if not value:
                continue
            candidate = dataset.find_entity(value, city_id)
            if candidate and candidate.get("kind") == "poi":
                entity = candidate
                matched_by = key
                break
        resolved.append({**ref, "entity": entity, "matched_by": matched_by})
    return resolved


def _poi_existence_check(
    refs: List[Dict[str, Any]],
    resolved_refs: List[Dict[str, Any]],
    city_id: Optional[str],
) -> Dict[str, Any]:
    if not refs:
        return _check_item("poi_existence", True, False, {"attraction_count": 0})
    unresolved = [_attraction_display(ref) for ref in resolved_refs if ref.get("entity") is None]
    return _check_item(
        "poi_existence",
        False,
        not unresolved,
        {"city_id": city_id, "attraction_count": len(refs), "unresolved": unresolved},
    )


def _duplicate_attractions_check(
    refs: List[Dict[str, Any]],
    resolved_refs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if len(refs) < 2:
        return _check_item("duplicate_attractions", True, False, {"attraction_count": len(refs)})
    counts: Dict[str, int] = {}
    labels: Dict[str, str] = {}
    for ref in resolved_refs:
        key = _resolved_attraction_key(ref)
        counts[key] = counts.get(key, 0) + 1
        labels.setdefault(key, _attraction_display(ref))
    duplicates = [
        {"key": key, "label": labels.get(key), "count": count}
        for key, count in counts.items()
        if count > 1
    ]
    return _check_item(
        "duplicate_attractions",
        False,
        not duplicates,
        {"duplicates": duplicates, "unique_count": len(counts), "attraction_count": len(refs)},
    )


def _must_include_pois_check(
    refs: List[Dict[str, Any]],
    resolved_refs: List[Dict[str, Any]],
    request: Dict[str, Any],
    constraints: Dict[str, Any],
    city_id: Optional[str],
) -> Dict[str, Any]:
    required = _constraint_text_list(
        constraints,
        request,
        "must_include_pois",
        "must_include_attractions",
        "required_pois",
        "required_attractions",
        "must_visit",
    )
    if not required:
        return _check_item("must_include_pois", True, False, {"required": []})
    missing = [item for item in required if not _required_ref_present(item, resolved_refs, city_id)]
    return _check_item("must_include_pois", False, not missing, {"required": required, "missing": missing})


def _forbidden_pois_check(
    refs: List[Dict[str, Any]],
    resolved_refs: List[Dict[str, Any]],
    request: Dict[str, Any],
    constraints: Dict[str, Any],
    city_id: Optional[str],
) -> Dict[str, Any]:
    forbidden = _constraint_text_list(
        constraints,
        request,
        "forbidden_pois",
        "forbidden_attractions",
        "avoid_pois",
        "avoid_attractions",
        "excluded_pois",
        "excluded_attractions",
    )
    if not forbidden:
        return _check_item("forbidden_pois", True, False, {"forbidden": []})
    violations = [item for item in forbidden if _required_ref_present(item, resolved_refs, city_id)]
    return _check_item("forbidden_pois", False, not violations, {"forbidden": forbidden, "violations": violations})


def _rain_attraction_suitability_check(
    weather_payload: Any,
    refs: List[Dict[str, Any]],
    resolved_refs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not _contains_rain(weather_payload):
        return _check_item("rain_attraction_suitability", True, False, {"rain_detected": False})
    if not refs:
        return _check_item(
            "rain_attraction_suitability",
            True,
            False,
            {"rain_detected": True, "attraction_count": 0},
        )
    conflicts: List[Dict[str, Any]] = []
    for ref in resolved_refs:
        entity = ref.get("entity")
        if not entity:
            continue
        raw = entity.get("raw") or {}
        formatted = entity.get("formatted") or {}
        environment = raw.get("environment") or {}
        suitability = str(((environment.get("weather_suitability") or {}).get("rain") or "")).lower()
        outdoor_ratio = _safe_float(environment.get("outdoor_ratio"))
        environment_type = str(formatted.get("indoor_outdoor") or environment.get("type") or "").lower()
        acceptable = (
            suitability == "suitable"
            or environment_type == "indoor"
            or outdoor_ratio < 0.5
        )
        if not acceptable:
            conflicts.append(
                {
                    "poi": _attraction_display(ref),
                    "rain_suitability": suitability or None,
                    "environment_type": environment_type or None,
                    "outdoor_ratio": outdoor_ratio,
                }
            )
    return _check_item(
        "rain_attraction_suitability",
        False,
        not conflicts,
        {"rain_detected": True, "conflicts": conflicts},
    )


def _senior_accessibility_check(
    request: Dict[str, Any],
    constraints: Dict[str, Any],
    refs: List[Dict[str, Any]],
    resolved_refs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not _is_senior_request(request, constraints):
        return _check_item("senior_accessibility", True, False, {"senior_request": False})
    if not refs:
        return _check_item(
            "senior_accessibility",
            True,
            False,
            {"senior_request": True, "attraction_count": 0},
        )
    high_intensity: List[Dict[str, Any]] = []
    for ref in resolved_refs:
        entity = ref.get("entity")
        if not entity:
            continue
        profile = ((entity.get("raw") or {}).get("visit_profile") or {})
        intensity = str(profile.get("intensity") or "").lower()
        walking_level = str(profile.get("walking_level") or "").lower()
        if intensity == "high" or walking_level == "high":
            high_intensity.append(
                {"poi": _attraction_display(ref), "intensity": intensity or None, "walking_level": walking_level or None}
            )
    return _check_item(
        "senior_accessibility",
        False,
        not high_intensity,
        {"senior_request": True, "high_intensity": high_intensity},
    )


def _tool_evidence_check(plan: Dict[str, Any], constraints: Dict[str, Any]) -> Dict[str, Any]:
    tool_results = plan.get("tool_results")
    context_tool_results = plan.get("context_tool_results")
    requires_evidence = bool(constraints.get("require_tool_evidence"))
    if (
        not requires_evidence
        and not isinstance(tool_results, dict)
        and not isinstance(context_tool_results, dict)
    ):
        return _check_item("tool_evidence", True, False, {"required": False})
    tool_results = tool_results if isinstance(tool_results, dict) else {}
    context_tool_results = context_tool_results if isinstance(context_tool_results, dict) else {}
    required_tools: List[str] = []
    if _collect_plan_attraction_refs(plan):
        required_tools.append("poi_search")
    if isinstance(plan.get("weather"), dict) and plan.get("weather"):
        required_tools.append("weather_query")
    if isinstance(plan.get("budget"), dict) and plan.get("budget"):
        required_tools.append("budget_calculator")
    required_tools = _ordered_unique_text(required_tools)
    evidence_sources: Dict[str, str] = {}
    missing_or_failed: List[str] = []
    for tool_name in required_tools:
        if _tool_result_success(tool_results.get(tool_name)):
            evidence_sources[tool_name] = "current"
        elif _tool_result_success(context_tool_results.get(tool_name)):
            evidence_sources[tool_name] = "context"
        else:
            evidence_sources[tool_name] = "missing_or_failed"
            missing_or_failed.append(tool_name)
    return _check_item(
        "tool_evidence",
        not required_tools,
        not missing_or_failed,
        {
            "required": requires_evidence,
            "required_tools": required_tools,
            "missing_or_failed": missing_or_failed,
            "evidence_sources": evidence_sources,
        },
    )


def _constraint_text_list(constraints: Dict[str, Any], request: Dict[str, Any], *keys: str) -> List[str]:
    values: List[str] = []
    for container in (constraints, request):
        for key in keys:
            values.extend(_as_text_list(container.get(key)))
    return _ordered_unique_text(values)


def _required_ref_present(value: str, resolved_refs: List[Dict[str, Any]], city_id: Optional[str]) -> bool:
    target_entity = get_fixed_tourism_data().find_entity(value, city_id)
    target_keys = {_normalize_key(value)}
    if target_entity and target_entity.get("kind") == "poi":
        formatted = target_entity.get("formatted") or {}
        target_keys.update(_normalize_key(item) for item in (formatted.get("id"), formatted.get("name")) if item)
    for ref in resolved_refs:
        if target_keys & _attraction_match_keys(ref):
            return True
    return False


def _attraction_match_keys(ref: Dict[str, Any]) -> set[str]:
    keys = {_normalize_key(item) for item in (ref.get("id"), ref.get("name"), ref.get("identifier")) if item}
    entity = ref.get("entity")
    if entity:
        formatted = entity.get("formatted") or {}
        keys.update(_normalize_key(item) for item in (formatted.get("id"), formatted.get("name")) if item)
    return {key for key in keys if key}


def _resolved_attraction_key(ref: Dict[str, Any]) -> str:
    entity = ref.get("entity")
    if entity:
        formatted = entity.get("formatted") or {}
        return _normalize_key(_first_present(formatted.get("id"), formatted.get("name")))
    return _normalize_key(ref.get("identifier"))


def _attraction_display(ref: Dict[str, Any]) -> str:
    entity = ref.get("entity")
    if entity:
        formatted = entity.get("formatted") or {}
        return str(_first_present(formatted.get("id"), formatted.get("name"), ref.get("identifier")) or "")
    return str(_first_present(ref.get("id"), ref.get("name"), ref.get("identifier")) or "")


def _is_senior_request(request: Dict[str, Any], constraints: Dict[str, Any]) -> bool:
    text = f"{request} {constraints}".lower()
    return any(
        marker in text
        for marker in ("senior", "elder", "elderly", "older", "old people", "老年", "老人", "长辈", "父母", "爸妈")
    )


def _tool_result_success(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("success") is False:
        return False
    status = str(result.get("status") or "").lower()
    return status in {"success", "no_result", "completed"}


def _normalize_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _ordered_unique_text(values: Iterable[Any]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _contains_rain(weather_payload: Any) -> bool:
    return bool(_rainy_day_indexes(weather_payload))


def _rainy_day_indexes(weather_payload: Any) -> List[int]:
    if not isinstance(weather_payload, dict):
        return []
    rainy_days: List[int] = []
    for index, day in enumerate(weather_payload.get("daily_weather") or [], start=1):
        if not isinstance(day, dict):
            continue
        if _weather_day_has_rain(day):
            rainy_days.append(_safe_int(day.get("day_index") or day.get("day") or index))
    if rainy_days:
        return _unique_ints(day for day in rainy_days if day)
    scenario = str(
        weather_payload.get("scenario_type")
        or weather_payload.get("requested_scenario_type")
        or ""
    ).lower()
    if scenario == "rain" or "雨" in scenario:
        days = len(weather_payload.get("daily_weather") or []) or 1
        return list(range(1, days + 1))
    return []


def _weather_day_has_rain(day: Dict[str, Any]) -> bool:
    labels = [
        str(day.get(key) or "").lower()
        for key in ("state", "condition", "weather", "scenario_type", "weather_type")
    ]
    labels.extend(str(item or "").lower() for item in day.get("risk_tags") or [])
    if any(label == "rain" or "雨" in label or "rainy" in label for label in labels):
        return True
    return _safe_float(day.get("precipitation_mm")) > 0


def _unique_ints(values: Iterable[int]) -> List[int]:
    seen: set[int] = set()
    result: List[int] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


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
