"""Build Day 7 cost forecast and model-freeze artifacts from a saved dev run."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.day7_cost_forecast import (
    DEFAULT_DEV_BUDGET_CNY,
    DEFAULT_DEV_CASE_COUNT,
    DEFAULT_DEV_RAW_RESULT_COUNT,
    DEFAULT_DEV_TURN_COUNT,
    DEFAULT_EXTRA_DEV_RERUNS,
    DEFAULT_DAY7_DEV_MAX_TOKENS,
    DEFAULT_FORMAL_BUDGET_CNY,
    DEFAULT_FORMAL_CASE_COUNT,
    DEFAULT_FORMAL_RAW_RESULT_COUNT,
    DEFAULT_FORMAL_TURN_COUNT,
    DEFAULT_NETWORK_RETRY_RESERVE_RATE,
    DEFAULT_TOKEN_CAP_HIT_RATE_LIMIT,
    DEFAULT_TWO_WEEK_BUDGET_CNY,
    DEFAULT_USD_TO_CNY_RATE,
    GPT5_MINI_PRICE_INPUT_USD_PER_1M,
    GPT5_MINI_PRICE_OUTPUT_USD_PER_1M,
    GPT5_MINI_PRICE_SNAPSHOT_DATE,
    GPT5_MINI_PRICE_SOURCE_URL,
    write_day7_cost_forecast,
)


DEFAULT_DAY7_DEV_ROOT = ROOT / "experiments" / "results" / "day7_dev"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="Completed Day7 dev run directory. Defaults to the newest run under experiments/results/day7_dev.",
    )
    parser.add_argument("--expected-dev-cases", type=int, default=DEFAULT_DEV_CASE_COUNT)
    parser.add_argument("--expected-dev-turns", type=int, default=DEFAULT_DEV_TURN_COUNT)
    parser.add_argument("--expected-dev-raw-results", type=int, default=DEFAULT_DEV_RAW_RESULT_COUNT)
    parser.add_argument("--expected-task-types", type=int, default=8)
    parser.add_argument("--formal-cases", type=int, default=DEFAULT_FORMAL_CASE_COUNT)
    parser.add_argument("--formal-turns", type=int, default=DEFAULT_FORMAL_TURN_COUNT)
    parser.add_argument("--formal-raw-results", type=int, default=DEFAULT_FORMAL_RAW_RESULT_COUNT)
    parser.add_argument("--dev-budget-cny", type=float, default=DEFAULT_DEV_BUDGET_CNY)
    parser.add_argument("--formal-budget-cny", type=float, default=DEFAULT_FORMAL_BUDGET_CNY)
    parser.add_argument("--two-week-budget-cny", type=float, default=DEFAULT_TWO_WEEK_BUDGET_CNY)
    parser.add_argument("--network-retry-reserve-rate", type=float, default=DEFAULT_NETWORK_RETRY_RESERVE_RATE)
    parser.add_argument("--extra-dev-reruns", type=int, default=DEFAULT_EXTRA_DEV_RERUNS)
    parser.add_argument("--usd-to-cny-rate", type=float, default=DEFAULT_USD_TO_CNY_RATE)
    parser.add_argument("--input-usd-per-1m", type=float, default=GPT5_MINI_PRICE_INPUT_USD_PER_1M)
    parser.add_argument("--output-usd-per-1m", type=float, default=GPT5_MINI_PRICE_OUTPUT_USD_PER_1M)
    parser.add_argument("--price-source-url", type=str, default=GPT5_MINI_PRICE_SOURCE_URL)
    parser.add_argument("--price-snapshot-date", type=str, default=GPT5_MINI_PRICE_SNAPSHOT_DATE)
    parser.add_argument(
        "--expected-max-tokens",
        type=int,
        default=DEFAULT_DAY7_DEV_MAX_TOKENS,
        help="Required max_tokens value for the Day7 development/freeze protocol.",
    )
    parser.add_argument(
        "--token-cap-hit-rate-limit",
        type=float,
        default=DEFAULT_TOKEN_CAP_HIT_RATE_LIMIT,
        help="Maximum acceptable fraction of LLM calls that hit the output-token cap.",
    )
    parser.add_argument(
        "--strict-freeze",
        action="store_true",
        help="Exit non-zero unless budget/runtime freeze status passes.",
    )
    args = parser.parse_args()

    run_dir = args.run_dir or _latest_run_dir(DEFAULT_DAY7_DEV_ROOT)
    if run_dir is None:
        print(json.dumps({"status": "failed", "error": "no Day7 dev run directory found"}, ensure_ascii=False))
        return 2

    payload = write_day7_cost_forecast(
        run_dir,
        expected_dev_case_count=args.expected_dev_cases,
        expected_dev_turn_count=args.expected_dev_turns,
        expected_dev_raw_result_count=args.expected_dev_raw_results,
        expected_task_type_count=args.expected_task_types,
        formal_case_count=args.formal_cases,
        formal_turn_count=args.formal_turns,
        formal_raw_result_count=args.formal_raw_results,
        dev_budget_cny=args.dev_budget_cny,
        formal_budget_cny=args.formal_budget_cny,
        two_week_budget_cny=args.two_week_budget_cny,
        network_retry_reserve_rate=args.network_retry_reserve_rate,
        extra_dev_reruns=args.extra_dev_reruns,
        usd_to_cny_rate=args.usd_to_cny_rate,
        input_usd_per_1m=args.input_usd_per_1m,
        output_usd_per_1m=args.output_usd_per_1m,
        price_source_url=args.price_source_url,
        price_snapshot_date=args.price_snapshot_date,
        expected_max_tokens=args.expected_max_tokens,
        token_cap_hit_rate_limit=args.token_cap_hit_rate_limit,
    )
    print(json.dumps(_public_payload(payload), ensure_ascii=False, indent=2))
    if args.strict_freeze and payload.get("freeze_status") != "frozen_for_cost_and_runtime":
        return 1
    return 0 if payload.get("status") == "completed" else 1


def _latest_run_dir(root: Path) -> Optional[Path]:
    if not root.exists():
        return None
    candidates = [
        path
        for path in root.iterdir()
        if path.is_dir() and (path / "benchmark_results.json").exists()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _public_payload(payload: dict) -> dict:
    forecast = payload.get("forecast") if isinstance(payload.get("forecast"), dict) else {}
    return {
        "status": payload.get("status"),
        "freeze_status": payload.get("freeze_status"),
        "budget_status": payload.get("budget_status"),
        "failed_checks": payload.get("failed_checks"),
        "rerun_required": _nested(forecast, "freeze_decision", "rerun_required"),
        "rerun_required_checks": _nested(
            forecast,
            "freeze_decision",
            "rerun_required_checks",
        ),
        "json": payload.get("json"),
        "markdown": payload.get("markdown"),
        "run_id": forecast.get("run_id"),
        "development_cost_cny": _nested(forecast, "development_totals", "cost_cny"),
        "formal_projected_cost_cny": _nested(forecast, "formal_projection", "cost_cny"),
        "two_week_total_cny": _nested(forecast, "budget_gate", "two_week_total_cny"),
        "model": _nested(forecast, "freeze_decision", "model"),
        "runtime": {
            "temperature": _nested(forecast, "freeze_decision", "temperature"),
            "max_tokens": _nested(forecast, "freeze_decision", "max_tokens"),
            "timeout_seconds": _nested(forecast, "freeze_decision", "timeout_seconds"),
            "retry_max_attempts": _nested(forecast, "freeze_decision", "retry_max_attempts"),
        },
    }


def _nested(value: dict, *keys: str):
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


if __name__ == "__main__":
    raise SystemExit(main())
