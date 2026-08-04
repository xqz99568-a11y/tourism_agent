"""Run the Day 7 M3 no-decision-normalizer ablation.

This command runs the 20-case development split with only M3
(``adaptive_multi_agent``) and disables the deterministic research-agent
decision normalizer.  It is a controlled ablation, not a replacement for the
four-method development run.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.day7_dev_experiment_gate import (  # noqa: E402
    DEFAULT_DEV_CASE_COUNT,
    DEFAULT_DEV_SCENARIO_CASE_COUNT,
    DEFAULT_DEV_TURN_COUNT,
)
from app.core.day7_m3_ablation import (  # noqa: E402
    write_m3_no_decision_normalizer_ablation_report,
)
from experiments.run_day7_dev_experiment import (  # noqa: E402
    DEFAULT_BENCHMARK_PATH,
    DEFAULT_MODEL_CONFIG_NAME,
    run_day7_dev_experiment,
)


DEFAULT_OUTPUT_ROOT = ROOT / "experiments" / "results" / "day7_m3_ablation"
ABLATION_METHOD = "adaptive_multi_agent"
DEFAULT_ABLATION_MODEL_CONFIG_NAME = f"{DEFAULT_MODEL_CONFIG_NAME}-m3-no-normalizer"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--model-config-name", type=str, default=DEFAULT_ABLATION_MODEL_CONFIG_NAME)
    parser.add_argument("--expected-cases", type=int, default=DEFAULT_DEV_CASE_COUNT)
    parser.add_argument("--expected-turns", type=int, default=DEFAULT_DEV_TURN_COUNT)
    parser.add_argument("--expected-scenarios", type=int, default=DEFAULT_DEV_SCENARIO_CASE_COUNT)
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Validate dataset/runtime/output path only; do not call the model.",
    )
    parser.add_argument(
        "--skip-llm-config-check",
        action="store_true",
        help="Allow a dry preflight when LLM credentials are not configured.",
    )
    parser.add_argument(
        "--allow-mock-llm",
        action="store_true",
        help="Permit mock LLM calls in the ablation report. Use only in local tests.",
    )
    parser.add_argument(
        "--strict-ablation-gate",
        action="store_true",
        help="Exit non-zero unless the no-normalizer ablation report passes.",
    )
    args = parser.parse_args()

    payload = run_day7_m3_ablation(
        benchmark_path=args.benchmark,
        output_dir=args.output_dir,
        run_id=args.run_id,
        model_config_name=args.model_config_name,
        expected_case_count=args.expected_cases,
        expected_turn_count=args.expected_turns,
        expected_scenario_case_count=args.expected_scenarios,
        preflight_only=args.preflight_only,
        require_llm_config=not args.skip_llm_config_check,
        allow_mock_llm=args.allow_mock_llm,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload.get("status") == "preflight_failed":
        return 2
    if payload.get("status") == "preflight_passed":
        return 0
    if args.strict_ablation_gate and payload.get("ablation_status") != "passed":
        return 1
    return 0 if payload.get("status") == "completed" else 1


def run_day7_m3_ablation(
    *,
    benchmark_path: str | Path = DEFAULT_BENCHMARK_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_ROOT,
    run_id: Optional[str] = None,
    model_config_name: str = DEFAULT_ABLATION_MODEL_CONFIG_NAME,
    expected_case_count: int = DEFAULT_DEV_CASE_COUNT,
    expected_turn_count: int = DEFAULT_DEV_TURN_COUNT,
    expected_scenario_case_count: int = DEFAULT_DEV_SCENARIO_CASE_COUNT,
    preflight_only: bool = False,
    require_llm_config: bool = True,
    allow_mock_llm: bool = False,
    runner_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run M3 with deterministic Agent decision normalization disabled."""
    run_id = run_id or f"day7_m3_no_normalizer_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    base_payload = run_day7_dev_experiment(
        benchmark_path=benchmark_path,
        output_dir=output_dir,
        run_id=run_id,
        repeats=1,
        methods=[ABLATION_METHOD],
        model_config_name=model_config_name,
        expected_case_count=expected_case_count,
        expected_turn_count=expected_turn_count,
        expected_scenario_case_count=expected_scenario_case_count,
        preflight_only=preflight_only,
        require_llm_config=require_llm_config,
        allow_mock_llm=allow_mock_llm,
        enable_decision_normalizer=False,
        runner_kwargs=runner_kwargs,
    )
    if base_payload.get("status") != "completed":
        return base_payload

    ablation_payload = write_m3_no_decision_normalizer_ablation_report(
        base_payload["output_dir"],
        expected_turn_count=expected_turn_count,
        expected_method=ABLATION_METHOD,
    )
    return {
        **base_payload,
        "ablation_schema": "ctp-day7-m3-no-decision-normalizer-ablation-v1",
        "ablation_status": ablation_payload["ablation_status"],
        "ablation_report_json": ablation_payload["json"],
        "ablation_report_md": ablation_payload["markdown"],
        "ablation_failed_checks": ablation_payload["failed_checks"],
        "decision_normalizer_enabled": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
