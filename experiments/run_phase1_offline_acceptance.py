"""Run the Phase 1 acceptance matrix without LLM or external API calls."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.experiment_runner import ExperimentRunner
from app.core.tracing import get_current_trace


async def _offline_handler(case: Dict[str, Any]) -> Dict[str, str]:
    trace = get_current_trace()
    if trace is None:
        raise RuntimeError("offline acceptance requires tracing")
    trace.mark_first_body_token()
    return {"case_id": case["case_id"], "source": "offline-static"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("experiments/results/phase1_acceptance_runs"),
        help="Root directory. The script creates a run_id subdirectory under this root.",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Optional stable run id. Defaults to phase1_acceptance_<UTC timestamp>.",
    )
    args = parser.parse_args()
    run_id = args.run_id or f"phase1_acceptance_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    run_output_dir = args.output_dir if args.output_dir.name == run_id else args.output_dir / run_id
    if run_output_dir.exists() and any(run_output_dir.iterdir()):
        raise RuntimeError(f"acceptance output directory already exists and is not empty: {run_output_dir}")

    os.environ["EXPERIMENT_STRICT_MODE"] = "true"
    os.environ["EXPERIMENT_DISABLE_CACHE"] = "true"
    os.environ["LLM_MODEL"] = "offline-static-model"
    os.environ["LLM_TEMPERATURE"] = "0"

    handlers = {method: _offline_handler for method in ExperimentRunner.METHODS}
    runner = ExperimentRunner(
        trace_dir=run_output_dir / "traces",
        output_dir=run_output_dir,
        method_handlers=handlers,
        repeats=2,
        run_id=run_id,
        model_config_name="offline-static",
    )
    benchmark_path = Path("experiments/phase1_offline_cases.json")
    benchmark_doc = json.loads(benchmark_path.read_text(encoding="utf-8"))
    expected_count = (
        len(benchmark_doc.get("cases") or [])
        * len(ExperimentRunner.METHODS)
        * runner.repeats
    )
    results = runner.run_benchmark(benchmark_path)

    if len(results) != expected_count or any(result["status"] != "completed" for result in results):
        raise RuntimeError(
            f"offline acceptance matrix did not produce {expected_count} completed runs"
        )

    print(
        json.dumps(
            {
                "status": "passed",
                "run_id": runner.run_id,
                "output_dir": str(run_output_dir),
                "result_count": len(results),
                "expected_count": expected_count,
                "trace_count": len(list((run_output_dir / "traces").glob("*.jsonl"))),
                "manifest": str(run_output_dir / "experiment_manifest.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
