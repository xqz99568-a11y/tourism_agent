"""LLM token-cost accounting for formal experiment traces.

The project cannot reliably query provider billing APIs during a benchmark run,
so every trace records two separate concepts:

* ``actual_cost``: provider-reported billed cost when it is available.  Mock
  LLM calls use an actual cost of zero.  Most OpenAI-compatible chat responses
  do not include billed cost, so this field can be ``None`` with an explicit
  status.
* ``standardized_estimated_cost`` / ``estimated_cost``: reproducible estimate
  from actual token counts and a run-level price snapshot.  The snapshot is
  provided through environment variables so paper runs can freeze the exact
  prices used for comparison without changing code.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any, Dict, Optional


COSTING_SCHEMA_VERSION = "ctp-llm-costing-v1"
DEFAULT_PRICE_UNIT = "per_1k_tokens"
DEFAULT_PRICE_CURRENCY = "CNY"
DEFAULT_PRICE_SOURCE = "env_or_zero_default"
DEFAULT_PRICING_MODE = "standardized_token_estimate"


def build_llm_cost_record(
    *,
    usage: Optional[Dict[str, Any]],
    provider: Any,
    model: Any,
    mock: bool,
) -> Dict[str, Any]:
    """Build the cost fields persisted on one LLM trace call."""
    normalized_usage = usage if isinstance(usage, dict) else {}
    prompt_tokens = _first_float(
        normalized_usage.get("prompt_tokens"),
        normalized_usage.get("input_tokens"),
    ) or 0.0
    completion_tokens = _first_float(
        normalized_usage.get("completion_tokens"),
        normalized_usage.get("output_tokens"),
    ) or 0.0
    snapshot = build_price_snapshot(provider=provider, model=model, mock=mock)
    input_price = _first_float(snapshot.get("input_token_unit_price")) or 0.0
    output_price = _first_float(snapshot.get("output_token_unit_price")) or 0.0
    estimated = round(
        (prompt_tokens / 1000.0) * input_price
        + (completion_tokens / 1000.0) * output_price,
        8,
    )

    reported_actual = _first_float(
        normalized_usage.get("actual_cost"),
        normalized_usage.get("actual_cost_cny"),
        normalized_usage.get("cost"),
        normalized_usage.get("cost_cny"),
    )
    if mock:
        actual_cost = 0.0
        actual_cost_status = "mock_zero_cost"
    elif reported_actual is not None:
        actual_cost = reported_actual
        actual_cost_status = "provider_reported"
    else:
        actual_cost = None
        actual_cost_status = "not_reported_by_provider"

    currency = str(snapshot["currency"])
    return {
        "cost_schema_version": COSTING_SCHEMA_VERSION,
        "cost_currency": currency,
        "estimated_cost": estimated,
        "standardized_estimated_cost": estimated,
        "estimated_cost_cny": estimated if currency.upper() == "CNY" else None,
        "standardized_estimated_cost_cny": estimated if currency.upper() == "CNY" else None,
        "actual_cost": actual_cost,
        "actual_cost_status": actual_cost_status,
        "input_token_unit_price": input_price,
        "output_token_unit_price": output_price,
        "price_unit": str(snapshot["price_unit"]),
        "price_snapshot_date": str(snapshot["price_snapshot_date"]),
        "price_source_url": str(snapshot["price_source_url"]),
        "pricing_mode": str(snapshot["pricing_mode"]),
        "price_snapshot": snapshot,
    }


def build_price_snapshot(
    *,
    provider: Any,
    model: Any,
    mock: bool = False,
) -> Dict[str, Any]:
    """Return the run-level price snapshot used for standardized estimates."""
    if mock:
        input_price = 0.0
        output_price = 0.0
        pricing_mode = "mock_zero_cost"
        source = "mock_llm"
    else:
        input_price = _env_float("LLM_PRICE_INPUT_PER_1K", "LLM_INPUT_PRICE_PER_1K") or 0.0
        output_price = _env_float("LLM_PRICE_OUTPUT_PER_1K", "LLM_OUTPUT_PRICE_PER_1K") or 0.0
        pricing_mode = _env_text("LLM_PRICE_MODE") or DEFAULT_PRICING_MODE
        source = _env_text("LLM_PRICE_SOURCE_URL") or DEFAULT_PRICE_SOURCE

    return {
        "schema_version": COSTING_SCHEMA_VERSION,
        "provider": str(provider or "unknown"),
        "model": str(model or "unknown"),
        "price_snapshot_date": _env_text("LLM_PRICE_SNAPSHOT_DATE") or date.today().isoformat(),
        "price_source_url": source,
        "currency": _env_text("LLM_PRICE_CURRENCY") or DEFAULT_PRICE_CURRENCY,
        "price_unit": _env_text("LLM_PRICE_UNIT") or DEFAULT_PRICE_UNIT,
        "input_token_unit_price": input_price,
        "output_token_unit_price": output_price,
        "pricing_mode": pricing_mode,
    }


def _env_text(name: str) -> Optional[str]:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _env_float(*names: str) -> Optional[float]:
    for name in names:
        value = _env_text(name)
        if value is None:
            continue
        try:
            return float(value)
        except ValueError:
            continue
    return None


def _first_float(*values: Any) -> Optional[float]:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
