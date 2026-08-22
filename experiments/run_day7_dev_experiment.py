"""Run the Day 7 20-case development-set real experiment.

The default scope is the frozen development split:

- 20 top-level cases
- 26 actual dialogue turns
- 4 methods
- 104 raw result rows

The generated gate is a development evidence gate, not a final paper gate.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.day7_dev_experiment_gate import (
    DAY7_DEV_EXPERIMENT_GATE_SCHEMA_VERSION,
    DAY7_DEV_PREFLIGHT_REPORT_NAME,
    DEFAULT_DEV_CASE_COUNT,
    DEFAULT_DEV_SCENARIO_CASE_COUNT,
    DEFAULT_DEV_TURN_COUNT,
    write_day7_dev_experiment_gate,
)
from app.core.experiment_runner import ExperimentRunner
from app.core.formal_experiment_preflight import (
    DEFAULT_FORMAL_METHOD_ORDER_SEED,
    assert_formal_preflight_passed,
    build_formal_preflight_report,
    resolve_run_output_dir,
    write_preflight_report,
)


DAY7_DEV_EXPERIMENT_SCHEMA_VERSION = "ctp-day7-dev-experiment-run-v1"
DEFAULT_BENCHMARK_PATH = ROOT / "experiments" / "ctp120_dev.json"
DEFAULT_OUTPUT_ROOT = ROOT / "experiments" / "results" / "day7_dev"
DEFAULT_MODEL_CONFIG_NAME = "day7-dev-real"
DEFAULT_ISOLATED_ROW_TIMEOUT_SECONDS = 720
RUNTIME_DEFAULTS = {
    "EXPERIMENT_STRICT_MODE": "true",
    "EXPERIMENT_DISABLE_CACHE": "true",
    "TRACE_SAVE_USER_MESSAGE": "false",
    "LLM_TEMPERATURE": "0",
    "LLM_MAX_TOKENS": "4096",
    "LLM_TIMEOUT": "60",
    "LLM_RETRY_MAX_ATTEMPTS": "3",
    "EXPERIMENT_RESULT_HARD_TIMEOUT_SECONDS": "720",
    "LLM_REASONING_EFFORT": "minimal",
    "EXPERIMENT_RESULT_TIMEOUT_SECONDS": "600",
    "EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER": "true",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--methods", type=str, default=",".join(ExperimentRunner.METHODS))
    parser.add_argument("--method-order-seed", type=int, default=DEFAULT_FORMAL_METHOD_ORDER_SEED)
    parser.add_argument("--model-config-name", type=str, default=DEFAULT_MODEL_CONFIG_NAME)
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
        help="Permit mock LLM calls in the dev gate. Use only in local tests.",
    )
    parser.add_argument(
        "--disable-decision-normalizer",
        action="store_true",
        help=(
            "Run M3 with the deterministic Agent decision normalizer disabled. "
            "Use only for the M3-no-decision-normalizer ablation."
        ),
    )
    parser.add_argument(
        "--strict-dev-gate",
        action="store_true",
        help="Exit non-zero unless the final Day7 dev gate passes.",
    )
    parser.add_argument(
        "--no-isolate-rows",
        action="store_true",
        help=(
            "Run in the original in-process mode. The default real run isolates "
            "each case-method row in a child process to avoid SDK/network hangs."
        ),
    )
    parser.add_argument(
        "--isolated-row-timeout-seconds",
        type=int,
        default=DEFAULT_ISOLATED_ROW_TIMEOUT_SECONDS,
        help="Outer subprocess timeout for one case-method row in isolated mode.",
    )
    parser.add_argument("--row-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--row-case-json", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--row-result-json", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--row-method", type=str, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--row-trace-dir", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--row-output-dir", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--row-repeat-index", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.row_worker:
        return _run_isolated_row_worker(
            case_path=args.row_case_json,
            result_path=args.row_result_json,
            method=args.row_method,
            trace_dir=args.row_trace_dir,
            output_dir=args.row_output_dir,
            run_id=args.run_id,
            repeat_index=args.row_repeat_index,
            system_variant=None,
            model_config_name=args.model_config_name,
            method_order_seed=args.method_order_seed,
            enable_decision_normalizer=not args.disable_decision_normalizer,
        )

    payload = run_day7_dev_experiment(
        benchmark_path=args.benchmark,
        output_dir=args.output_dir,
        run_id=args.run_id,
        repeats=args.repeats,
        methods=_parse_methods(args.methods),
        method_order_seed=args.method_order_seed,
        model_config_name=args.model_config_name,
        expected_case_count=args.expected_cases,
        expected_turn_count=args.expected_turns,
        expected_scenario_case_count=args.expected_scenarios,
        preflight_only=args.preflight_only,
        require_llm_config=not args.skip_llm_config_check,
        allow_mock_llm=args.allow_mock_llm,
        enable_decision_normalizer=not args.disable_decision_normalizer,
        isolate_rows=not args.no_isolate_rows,
        isolated_row_timeout_seconds=args.isolated_row_timeout_seconds,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload.get("status") == "preflight_failed":
        return 2
    if payload.get("status") == "preflight_passed":
        return 0
    if args.strict_dev_gate and payload.get("dev_gate_status") != "passed":
        return 1
    return 0 if payload.get("status") == "completed" else 1


def run_day7_dev_experiment(
    *,
    benchmark_path: str | Path = DEFAULT_BENCHMARK_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_ROOT,
    run_id: Optional[str] = None,
    repeats: int = 1,
    methods: Optional[Iterable[str]] = None,
    method_order_seed: int = DEFAULT_FORMAL_METHOD_ORDER_SEED,
    model_config_name: str = DEFAULT_MODEL_CONFIG_NAME,
    expected_case_count: int = DEFAULT_DEV_CASE_COUNT,
    expected_turn_count: int = DEFAULT_DEV_TURN_COUNT,
    expected_scenario_case_count: int = DEFAULT_DEV_SCENARIO_CASE_COUNT,
    preflight_only: bool = False,
    require_llm_config: bool = True,
    allow_mock_llm: bool = False,
    enable_decision_normalizer: bool = True,
    isolate_rows: Optional[bool] = None,
    isolated_row_timeout_seconds: int = DEFAULT_ISOLATED_ROW_TIMEOUT_SECONDS,
    runner_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run the Day7 development experiment and return a payload."""
    selected_methods = _normalize_methods(methods or ExperimentRunner.METHODS)
    if int(repeats) != 1:
        raise ValueError("Day7 development experiment requires repeats=1 for the fixed 104-row audit.")
    run_id = run_id or f"day7_dev_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    benchmark = Path(benchmark_path)
    output_root = Path(output_dir)
    run_output_dir = resolve_run_output_dir(output_root, run_id)
    expected_raw_count = int(expected_turn_count) * len(selected_methods)

    with _temporary_env(RUNTIME_DEFAULTS):
        preflight_report = build_formal_preflight_report(
            benchmark_path=benchmark,
            output_dir=output_root,
            run_id=run_id,
            methods=selected_methods,
            repeats=repeats,
            method_order_seed=method_order_seed,
            expected_case_count=expected_case_count,
            require_llm_config=require_llm_config,
            strict_formal=True,
        )
        preflight_payload = {
            "schema_version": DAY7_DEV_EXPERIMENT_SCHEMA_VERSION,
            "status": (
                "preflight_passed"
                if preflight_report.get("status") == "passed"
                else "preflight_failed"
            ),
            "run_id": run_id,
            "output_dir": run_output_dir.as_posix(),
            "benchmark": benchmark.as_posix(),
            "expected_count": expected_raw_count,
            "preflight": preflight_report,
        }
        if preflight_only or preflight_report.get("status") != "passed":
            return preflight_payload

        assert_formal_preflight_passed(preflight_report)
        run_output_dir.mkdir(parents=True, exist_ok=True)
        preflight_path = write_preflight_report(
            preflight_report,
            run_output_dir / DAY7_DEV_PREFLIGHT_REPORT_NAME,
        )
        runner = ExperimentRunner(
            trace_dir=run_output_dir / "traces",
            output_dir=run_output_dir,
            repeats=repeats,
            run_id=run_id,
            model_config_name=model_config_name,
            method_order_seed=method_order_seed,
            enable_research_agent_decision_normalizer=enable_decision_normalizer,
            **(runner_kwargs or {}),
        )
        use_isolated_rows = bool(isolate_rows) if isolate_rows is not None else runner_kwargs is None
        if use_isolated_rows:
            if runner_kwargs:
                raise ValueError("isolated Day7 row execution does not support runner_kwargs")
            results = _run_isolated_benchmark_rows(
                runner=runner,
                benchmark=benchmark,
                selected_methods=selected_methods,
                repeats=repeats,
                run_id=run_id,
                model_config_name=model_config_name,
                method_order_seed=method_order_seed,
                enable_decision_normalizer=enable_decision_normalizer,
                row_timeout_seconds=isolated_row_timeout_seconds,
                run_output_dir=run_output_dir,
            )
        else:
            results = runner.run_benchmark(
                benchmark,
                methods=selected_methods,
                repeats=repeats,
                run_id=run_id,
                model_config_name=model_config_name,
            )

    gate_payload = write_day7_dev_experiment_gate(
        run_output_dir,
        expected_case_count=expected_case_count,
        expected_turn_count=expected_turn_count,
        expected_scenario_case_count=expected_scenario_case_count,
        required_methods=selected_methods,
        allow_mock_llm=allow_mock_llm,
    )
    payload = _build_payload(
        run_id=run_id,
        run_output_dir=run_output_dir,
        benchmark=benchmark,
        preflight_path=preflight_path,
        result_count=len(results),
        expected_count=expected_raw_count,
        gate_payload=gate_payload,
    )
    _validate_payload_files(payload)
    return payload


def _run_isolated_benchmark_rows(
    *,
    runner: ExperimentRunner,
    benchmark: Path,
    selected_methods: Sequence[str],
    repeats: int,
    run_id: str,
    model_config_name: str,
    method_order_seed: int,
    enable_decision_normalizer: bool,
    row_timeout_seconds: int,
    run_output_dir: Path,
) -> List[Dict[str, Any]]:
    """Run each benchmark row in a child process while preserving parent order.

    The Day 7 real API run must not be held hostage by a single SDK/network hang.
    Parent-side orchestration keeps the same method ordering, checkpoint files,
    and method-local multi-turn state policy as ``ExperimentRunner.run_benchmark``;
    only the actual row execution is isolated.
    """
    cases = runner.load_benchmark(benchmark)
    benchmark_output_dir = run_output_dir
    csv_path = benchmark_output_dir / "benchmark_results.csv"
    json_path = benchmark_output_dir / "benchmark_results.json"
    summary_path = benchmark_output_dir / "evaluation_summary.json"
    paper_tables_path = benchmark_output_dir / "paper_tables.md"
    manifest_path = benchmark_output_dir / "experiment_manifest.json"
    checkpoint_csv_path = benchmark_output_dir / "benchmark_results.checkpoint.csv"
    checkpoint_json_path = benchmark_output_dir / "benchmark_results.checkpoint.json"
    row_root = benchmark_output_dir / "_isolated_rows"
    row_root.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []
    row_index = 0
    for repeat_offset in range(int(repeats)):
        repeat_index = runner.repeat_index + repeat_offset
        for case in cases:
            case_methods = runner._ordered_methods_for_case(
                selected_methods,
                case_id=runner._benchmark_case_order_id(case),
                repeat_index=repeat_index,
            )
            if runner._is_scenario_case(case):
                for method in case_methods:
                    scenario_results = _run_isolated_scenario_rows(
                        runner=runner,
                        scenario=case,
                        method=method,
                        run_id=run_id,
                        repeat_index=repeat_index,
                        model_config_name=model_config_name,
                        method_order_seed=method_order_seed,
                        enable_decision_normalizer=enable_decision_normalizer,
                        row_timeout_seconds=row_timeout_seconds,
                        run_output_dir=run_output_dir,
                        row_root=row_root,
                        row_index_start=row_index,
                    )
                    row_index += len(scenario_results)
                    results.extend(scenario_results)
                    runner._export_benchmark_checkpoint(
                        results,
                        csv_path=checkpoint_csv_path,
                        json_path=checkpoint_json_path,
                    )
                continue

            for method in case_methods:
                row_index += 1
                results.append(
                    _run_isolated_row(
                        runner=runner,
                        case=case,
                        method=method,
                        run_id=run_id,
                        repeat_index=repeat_index,
                        model_config_name=model_config_name,
                        method_order_seed=method_order_seed,
                        enable_decision_normalizer=enable_decision_normalizer,
                        row_timeout_seconds=row_timeout_seconds,
                        run_output_dir=run_output_dir,
                        row_root=row_root,
                        row_index=row_index,
                    )
                )
                runner._export_benchmark_checkpoint(
                    results,
                    csv_path=checkpoint_csv_path,
                    json_path=checkpoint_json_path,
                )

    runner.export_csv(results, csv_path)
    runner.export_json(results, json_path)
    summary = runner.export_evaluation_summary(results, summary_path)
    runner.export_paper_tables(summary, paper_tables_path)
    runner.write_experiment_manifest(
        benchmark_path=benchmark,
        output_path=manifest_path,
        run_id=run_id,
        repeats=repeats,
        methods=selected_methods,
        method_order_seed=method_order_seed,
        system_variant=None,
        model_config_name=model_config_name,
        result_paths={
            "csv": csv_path,
            "json": json_path,
            "summary": summary_path,
            "paper_tables": paper_tables_path,
        },
    )
    return results


def _run_isolated_scenario_rows(
    *,
    runner: ExperimentRunner,
    scenario: Dict[str, Any],
    method: str,
    run_id: str,
    repeat_index: int,
    model_config_name: str,
    method_order_seed: int,
    enable_decision_normalizer: bool,
    row_timeout_seconds: int,
    run_output_dir: Path,
    row_root: Path,
    row_index_start: int,
) -> List[Dict[str, Any]]:
    scenario_id = runner._scenario_id(scenario)
    turns = runner._scenario_turns(scenario)
    previous_state: Optional[Dict[str, Any]] = None
    dialogue_history = runner._scenario_initial_history(scenario)
    results: List[Dict[str, Any]] = []
    for offset, turn in enumerate(turns):
        turn_case = runner._scenario_turn_case(
            scenario,
            turn,
            scenario_id=scenario_id,
            turn_index=offset,
            turn_count=len(turns),
            dialogue_history=dialogue_history,
            previous_state=previous_state,
        )
        result = _run_isolated_row(
            runner=runner,
            case=turn_case,
            method=method,
            run_id=run_id,
            repeat_index=repeat_index,
            model_config_name=model_config_name,
            method_order_seed=method_order_seed,
            enable_decision_normalizer=enable_decision_normalizer,
            row_timeout_seconds=row_timeout_seconds,
            run_output_dir=run_output_dir,
            row_root=row_root,
            row_index=row_index_start + offset + 1,
        )
        runner._attach_scenario_result_metadata(
            result,
            scenario_id=scenario_id,
            turn_id=str(turn_case["turn_id"]),
            turn_index=offset,
            turn_count=len(turns),
            target_turn=bool(turn_case.get("target_turn")),
            previous_state=previous_state,
            method=method,
        )
        results.append(result)
        previous_state = runner._method_previous_state_from_result(result)
        dialogue_history = runner._append_scenario_dialogue_history(
            dialogue_history,
            turn_case,
            result,
        )
    return results


def _run_isolated_row(
    *,
    runner: ExperimentRunner,
    case: Dict[str, Any],
    method: str,
    run_id: str,
    repeat_index: int,
    model_config_name: str,
    method_order_seed: int,
    enable_decision_normalizer: bool,
    row_timeout_seconds: int,
    run_output_dir: Path,
    row_root: Path,
    row_index: int,
) -> Dict[str, Any]:
    safe_case_id = _safe_filename(str(case.get("case_id") or "case"))
    safe_method = _safe_filename(str(method or "method"))
    prefix = f"{row_index:04d}_{safe_case_id}_{safe_method}"
    case_path = row_root / f"{prefix}.case.json"
    result_path = row_root / f"{prefix}.result.json"
    stdout_path = row_root / f"{prefix}.stdout.log"
    stderr_path = row_root / f"{prefix}.stderr.log"
    case_path.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")

    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--row-worker",
        "--row-case-json",
        str(case_path),
        "--row-result-json",
        str(result_path),
        "--row-method",
        method,
        "--row-trace-dir",
        str(run_output_dir / "traces"),
        "--row-output-dir",
        str(run_output_dir),
        "--run-id",
        run_id,
        "--row-repeat-index",
        str(repeat_index),
        "--model-config-name",
        model_config_name,
        "--method-order-seed",
        str(method_order_seed),
    ]
    if not enable_decision_normalizer:
        command.append("--disable-decision-normalizer")

    started = datetime.utcnow()
    try:
        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open(
            "w",
            encoding="utf-8",
        ) as stderr:
            completed = subprocess.run(
                command,
                cwd=ROOT,
                stdout=stdout,
                stderr=stderr,
                timeout=max(1, int(row_timeout_seconds)),
                check=False,
            )
    except subprocess.TimeoutExpired as exc:
        return _isolated_row_failure_result(
            runner=runner,
            case=case,
            method=method,
            run_id=run_id,
            repeat_index=repeat_index,
            model_config_name=model_config_name,
            started=started,
            error=f"isolated row subprocess timeout after {row_timeout_seconds}s: {exc}",
        )

    if result_path.exists():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
    stderr_tail = _tail_text(stderr_path)
    stdout_tail = _tail_text(stdout_path)
    detail = stderr_tail or stdout_tail or f"exit_code={completed.returncode}"
    return _isolated_row_failure_result(
        runner=runner,
        case=case,
        method=method,
        run_id=run_id,
        repeat_index=repeat_index,
        model_config_name=model_config_name,
        started=started,
        error=f"isolated row subprocess failed: {detail}",
    )


def _run_isolated_row_worker(
    *,
    case_path: Optional[Path],
    result_path: Optional[Path],
    method: Optional[str],
    trace_dir: Optional[Path],
    output_dir: Optional[Path],
    run_id: Optional[str],
    repeat_index: int,
    system_variant: Optional[str],
    model_config_name: str,
    method_order_seed: int,
    enable_decision_normalizer: bool,
) -> int:
    if not case_path or not result_path or not method or not trace_dir or not output_dir:
        raise SystemExit("row worker requires case/result/method/trace/output arguments")
    case = json.loads(case_path.read_text(encoding="utf-8"))
    runner = ExperimentRunner(
        trace_dir=trace_dir,
        output_dir=output_dir,
        repeats=1,
        run_id=str(run_id or "day7-row-worker"),
        model_config_name=model_config_name,
        method_order_seed=method_order_seed,
        enable_research_agent_decision_normalizer=enable_decision_normalizer,
    )
    result = runner.run(
        case,
        method=method,
        run_id=run_id,
        repeat_index=repeat_index,
        system_variant=system_variant,
        model_config_name=model_config_name,
    )
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def _isolated_row_failure_result(
    *,
    runner: ExperimentRunner,
    case: Dict[str, Any],
    method: str,
    run_id: str,
    repeat_index: int,
    model_config_name: str,
    started: datetime,
    error: str,
) -> Dict[str, Any]:
    normalized_case = runner._normalize_case(case)
    latency_ms = max(0.0, (datetime.utcnow() - started).total_seconds() * 1000.0)
    output = {
        "error": error,
        "execution_status": "failed",
        "metadata": {"isolated_row_failure": True},
    }
    result = asyncio.run(
        runner._build_unified_result(
            case=normalized_case,
            method=method,
            output=output,
            latency_ms=latency_ms,
            trace=None,
            error=error,
        )
    )
    result["status"] = "failed"
    result["error"] = error
    result["raw_output"] = output
    result["output"]["execution_status"] = "failed"
    result["output"]["final_answer"] = error
    result["output"]["metadata"]["isolated_row_failure"] = True
    result["latency"] = latency_ms
    result["latency_ms"] = latency_ms
    result["repeat_index"] = repeat_index
    result["run_id"] = run_id
    result["model_config_name"] = model_config_name
    return result


def _tail_text(path: Path, *, limit: int = 2000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-limit:]


def _safe_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)
    return cleaned[:120] or "row"


def _build_payload(
    *,
    run_id: str,
    run_output_dir: Path,
    benchmark: Path,
    preflight_path: Path,
    result_count: int,
    expected_count: int,
    gate_payload: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "schema_version": DAY7_DEV_EXPERIMENT_SCHEMA_VERSION,
        "status": "completed",
        "run_id": run_id,
        "benchmark": benchmark.as_posix(),
        "output_dir": run_output_dir.as_posix(),
        "result_count": result_count,
        "expected_count": expected_count,
        "preflight": preflight_path.as_posix(),
        "csv": (run_output_dir / "benchmark_results.csv").as_posix(),
        "json": (run_output_dir / "benchmark_results.json").as_posix(),
        "summary": (run_output_dir / "evaluation_summary.json").as_posix(),
        "paper_tables": (run_output_dir / "paper_tables.md").as_posix(),
        "manifest": (run_output_dir / "experiment_manifest.json").as_posix(),
        "trace_dir": (run_output_dir / "traces").as_posix(),
        "day7_dev_gate": gate_payload["json"],
        "day7_dev_report": gate_payload["markdown"],
        "day7_dev_gate_schema_version": DAY7_DEV_EXPERIMENT_GATE_SCHEMA_VERSION,
        "dev_gate_status": gate_payload["gate_status"],
        "paper_claims_allowed": gate_payload["paper_claims_allowed"],
        "failed_checks": gate_payload["failed_checks"],
    }


def _validate_payload_files(payload: Dict[str, Any]) -> None:
    for key in (
        "preflight",
        "csv",
        "json",
        "summary",
        "paper_tables",
        "manifest",
        "day7_dev_gate",
        "day7_dev_report",
    ):
        path = Path(str(payload[key]))
        if not path.exists():
            raise RuntimeError(f"Day7 dev experiment missing output file: {key}")
    if payload["result_count"] != payload["expected_count"]:
        raise RuntimeError(
            f"Day7 dev experiment result count mismatch: "
            f"{payload['result_count']} != {payload['expected_count']}"
        )


def _parse_methods(value: str) -> List[str]:
    return [item.strip() for item in str(value or "").replace(";", ",").split(",") if item.strip()]


def _normalize_methods(methods: Iterable[str]) -> List[str]:
    normalized = [str(method).strip().lower() for method in methods if str(method).strip()]
    if not normalized:
        raise ValueError("methods must not be empty")
    return normalized


@contextmanager
def _temporary_env(defaults: Dict[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in defaults}
    try:
        for key, value in defaults.items():
            os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
