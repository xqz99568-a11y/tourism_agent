"""Subprocess worker for one isolated benchmark case/method result.

The parent process owns checkpointing and the hard timeout.  This worker only
loads a serialized request, runs one ExperimentRunner result with hard-timeout
recursion disabled, and writes a JSON response.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict

from app.core.experiment_runner import (
    EXPERIMENT_RESULT_HARD_TIMEOUT_CHILD_ENV,
    EXPERIMENT_RESULT_WORKER_STARTUP_DELAY_ENV,
    ExperimentRunner,
)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print(
            "usage: python -m app.core.experiment_result_worker "
            "<request.json> <response.json>",
            file=sys.stderr,
        )
        return 2
    request_path = Path(args[0])
    response_path = Path(args[1])
    try:
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("worker request must be a JSON object")
        startup_delay = _positive_float(
            os.getenv(EXPERIMENT_RESULT_WORKER_STARTUP_DELAY_ENV),
            0.0,
        )
        if startup_delay > 0:
            time.sleep(startup_delay)
        result = asyncio.run(_run(payload))
        _write_response(
            response_path,
            {
                "status": "completed",
                "result": result,
            },
        )
        return 0
    except BaseException as exc:
        _write_response(
            response_path,
            {
                "status": "failed",
                "error_type": exc.__class__.__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(limit=20),
            },
        )
        return 1


async def _run(payload: Dict[str, Any]) -> Dict[str, Any]:
    os.environ[EXPERIMENT_RESULT_HARD_TIMEOUT_CHILD_ENV] = "true"
    runner = ExperimentRunner(
        trace_dir=Path(str(payload["trace_dir"])),
        output_dir=Path(str(payload["output_dir"])),
        repeats=int(payload.get("repeats") or 1),
        run_id=str(payload.get("run_id") or ""),
        repeat_index=int(payload.get("repeat_index") or 0),
        system_variant=str(payload.get("system_variant") or ""),
        model_config_name=str(payload.get("model_config_name") or ""),
        method_order_seed=int(payload.get("method_order_seed") or 20260718),
        enable_research_agent_decision_normalizer=bool(
            payload.get("enable_research_agent_decision_normalizer", True)
        ),
    )
    return await runner.arun(
        payload.get("case") if isinstance(payload.get("case"), dict) else {},
        method=str(payload.get("method") or "adaptive_multi_agent"),
        run_id=str(payload.get("run_id") or ""),
        repeat_index=int(payload.get("repeat_index") or 0),
        system_variant=str(payload.get("system_variant") or ""),
        model_config_name=str(payload.get("model_config_name") or ""),
        request_id=str(payload.get("request_id") or ""),
    )


def _write_response(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if parsed > 0 else float(default)


if __name__ == "__main__":
    raise SystemExit(main())
