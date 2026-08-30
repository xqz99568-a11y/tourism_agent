"""Run CTP100 M2/M3 repeat-stability experiment.

This supplementary runner adds two more CTP100 repeats for M2 and M3 after
the frozen CTP100 v6 formal run.  It does not run M0/M1, does not change any
agent logic, and writes a separate audit report so the paper can treat these
rows as stability evidence rather than a replacement main experiment.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.experiment_method_contract import method_fairness_contract_hash
from app.core.experiment_runner import ExperimentRunner
from app.core.final_artifact_index import write_final_artifact_index
from app.core.fixed_data import CANONICAL_JSON_SHA256_STRATEGY, canonical_json_sha256
from app.core.formal_experiment_gate import (
    _api_failure_timeout_summary,
    _failure_classification_summary,
    _load_traces,
)
from app.core.formal_experiment_preflight import (
    DEFAULT_FORMAL_METHOD_ORDER_SEED,
    assert_formal_preflight_passed,
    build_formal_preflight_report,
    load_benchmark_document,
)
from experiments.run_ctp30_sealed_validation import CTP100_V6_FROZEN_COMMIT
from experiments.run_formal_experiment import (
    _apply_formal_env_defaults,
    _run_pre_formal_real_api_smoke,
)


CTP100_M2_M3_STABILITY_REPORT_SCHEMA_VERSION = (
    "ctp100-m2-m3-stability-report-v1"
)
CTP100_M2_M3_STABILITY_METHODS = ("fixed_multi_agent", "adaptive_multi_agent")
CTP100_M2_M3_STABILITY_EXPECTED_CASES = 100
CTP100_M2_M3_STABILITY_EXPECTED_TURNS = 130
CTP100_M2_M3_STABILITY_DEFAULT_REPEATS = 2
CTP100_M2_M3_STABILITY_EXPECTED_RESULTS = (
    CTP100_M2_M3_STABILITY_EXPECTED_TURNS
    * len(CTP100_M2_M3_STABILITY_METHODS)
    * CTP100_M2_M3_STABILITY_DEFAULT_REPEATS
)
DEFAULT_BENCHMARK_PATH = ROOT / "experiments" / "benchmark.json"
DEFAULT_OUTPUT_ROOT = Path(r"D:\Tourism_Agent_Formal_Runs\ctp100_m2_m3_stability")
DEFAULT_MODEL_CONFIG_NAME = "ctp100-m2-m3-stability-v6"
PREFLIGHT_NAME = "ctp100_m2_m3_stability_preflight.json"
REPORT_JSON_NAME = "ctp100_m2_m3_stability_report.json"
REPORT_MD_NAME = "ctp100_m2_m3_stability_report.md"
MANIFEST_NAME = "experiment_manifest.json"

PROTECTED_CTP100_V6_PATHS = (
    "app/agents",
    "app/tools",
    "app/core/experiment_runner.py",
    "app/core/experiment_method_contract.py",
    "app/core/experiment_method_input.py",
    "app/core/experiment_metrics.py",
    "app/core/fixed_data.py",
    "app/core/goal_state_scheduler.py",
    "app/core/independent_evaluator.py",
    "app/core/intercity_transport_snapshot.py",
    "app/core/no_date_weather_policy.py",
    "app/core/qweather_snapshot.py",
    "experiments/ctp100_formal_v2.json",
    "experiments/evaluation_rule_catalog.json",
    "data/accommodation",
    "data/attractions",
    "data/intercity_transport",
    "data/restaurants",
    "data/weather_snapshot",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--repeats", type=int, default=CTP100_M2_M3_STABILITY_DEFAULT_REPEATS)
    parser.add_argument("--repeat-index-start", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--strict-stability-readiness", action="store_true")
    parser.add_argument("--skip-real-api-smoke", action="store_true")
    parser.add_argument("--real-api-smoke-max-tokens", type=int, default=512)
    parser.add_argument("--method-order-seed", type=int, default=DEFAULT_FORMAL_METHOD_ORDER_SEED)
    parser.add_argument("--model-config-name", type=str, default=DEFAULT_MODEL_CONFIG_NAME)
    parser.add_argument("--frozen-ctp100-commit", type=str, default=CTP100_V6_FROZEN_COMMIT)
    parser.add_argument(
        "--require-clean-git",
        action="store_true",
        help="Require a clean working tree before the stability run starts.",
    )
    args = parser.parse_args()

    run_id = args.run_id or (
        f"ctp100_m2_m3_stability_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    )
    run_dir = _resolve_run_output_dir(args.output_dir, run_id)
    _apply_formal_env_defaults()
    preflight = build_ctp100_m2_m3_stability_preflight(
        benchmark_path=args.benchmark,
        output_dir=args.output_dir,
        run_id=run_id,
        repeats=args.repeats,
        repeat_index_start=args.repeat_index_start,
        method_order_seed=args.method_order_seed,
        model_config_name=args.model_config_name,
        resume=args.resume,
        require_clean_git=args.require_clean_git,
        frozen_ctp100_commit=args.frozen_ctp100_commit,
    )
    if args.preflight_only:
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return 0 if preflight["status"] == "passed" else 2
    assert_formal_preflight_passed(preflight["formal_preflight"])
    if preflight["status"] != "passed":
        _raise_stability_preflight_error(preflight)

    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / PREFLIGHT_NAME, preflight)
    smoke = None
    if not args.skip_real_api_smoke:
        smoke = _run_pre_formal_real_api_smoke(
            run_output_dir=run_dir,
            run_id=run_id,
            max_tokens=args.real_api_smoke_max_tokens,
        )

    runner = ExperimentRunner(
        trace_dir=run_dir / "traces",
        output_dir=run_dir,
        repeats=args.repeats,
        repeat_index=args.repeat_index_start,
        run_id=run_id,
        model_config_name=args.model_config_name,
        method_order_seed=args.method_order_seed,
    )
    started = time.perf_counter()
    results = runner.run_benchmark(
        args.benchmark,
        methods=CTP100_M2_M3_STABILITY_METHODS,
        repeats=args.repeats,
        run_id=run_id,
        model_config_name=args.model_config_name,
        csv_path=run_dir / "benchmark_results.csv",
        json_path=run_dir / "benchmark_results.json",
        summary_path=run_dir / "evaluation_summary.json",
        paper_tables_path=run_dir / "paper_tables.md",
        manifest_path=run_dir / MANIFEST_NAME,
        resume=args.resume,
    )
    elapsed = time.perf_counter() - started
    benchmark_document, cases = load_benchmark_document(args.benchmark)
    report = build_ctp100_m2_m3_stability_report(
        run_id=run_id,
        run_dir=run_dir,
        benchmark_path=args.benchmark,
        benchmark_document=benchmark_document,
        cases=cases,
        preflight=preflight,
        results=results,
        elapsed_seconds=elapsed,
        pre_formal_smoke=smoke,
    )
    _attach_stability_metadata_to_manifest(run_dir, report=report, preflight=preflight)
    _write_stability_report(run_dir, report)
    final_index = write_final_artifact_index(
        run_dir,
        artifact_files=_stability_artifact_files(args.benchmark),
        manifest_name=MANIFEST_NAME,
    )
    payload = _payload(run_id, run_dir, report, final_index=final_index)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.strict_stability_readiness and (
        report["status"] != "passed" or final_index["index_status"] != "passed"
    ):
        return 1
    return 0


def build_ctp100_m2_m3_stability_preflight(
    *,
    benchmark_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    repeats: int = CTP100_M2_M3_STABILITY_DEFAULT_REPEATS,
    repeat_index_start: int = 1,
    method_order_seed: int = DEFAULT_FORMAL_METHOD_ORDER_SEED,
    model_config_name: str = DEFAULT_MODEL_CONFIG_NAME,
    resume: bool = False,
    require_clean_git: bool = False,
    frozen_ctp100_commit: str = CTP100_V6_FROZEN_COMMIT,
) -> Dict[str, Any]:
    benchmark_file = Path(benchmark_path)
    errors: List[str] = []
    warnings: List[str] = []
    formal_preflight = build_formal_preflight_report(
        benchmark_path=benchmark_file,
        output_dir=output_dir,
        run_id=run_id,
        methods=CTP100_M2_M3_STABILITY_METHODS,
        repeats=repeats,
        method_order_seed=method_order_seed,
        model_config_name=model_config_name,
        expected_case_count=CTP100_M2_M3_STABILITY_EXPECTED_CASES,
        require_llm_config=True,
        strict_formal=True,
        require_day8_delivery_pack=False,
        require_clean_git=require_clean_git,
        resume=resume,
    )
    errors.extend(formal_preflight.get("errors") or [])
    warnings.extend(formal_preflight.get("warnings") or [])

    document: Any = None
    cases: List[Dict[str, Any]] = []
    try:
        document, cases = load_benchmark_document(benchmark_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"benchmark file is invalid: {exc}")

    protected_audit = _protected_core_hash_audit(
        frozen_ctp100_commit,
        PROTECTED_CTP100_V6_PATHS,
    )
    if protected_audit["status"] != "passed":
        errors.append("protected CTP100 v6 method/data files changed")

    turn_count = _turn_count(cases)
    expected_raw = turn_count * len(CTP100_M2_M3_STABILITY_METHODS) * int(repeats)
    if int(repeats) != CTP100_M2_M3_STABILITY_DEFAULT_REPEATS:
        errors.append(
            "CTP100 M2/M3 stability run requires repeats=2 to supplement v6"
        )
    if int(repeat_index_start) != 1:
        errors.append(
            "CTP100 M2/M3 stability run requires repeat_index_start=1 so "
            "new repeats become R2/R3 after v6 repeat_index=0"
        )
    if expected_raw != CTP100_M2_M3_STABILITY_EXPECTED_RESULTS:
        errors.append(
            "expected raw result count mismatch: "
            f"expected {CTP100_M2_M3_STABILITY_EXPECTED_RESULTS}, got {expected_raw}"
        )

    benchmark_meta = _mapping(document)
    points_to_ctp100 = benchmark_meta.get("case_files") == ["ctp100_formal_v2.json"]
    direct_ctp100 = benchmark_meta.get("dataset_id") == "ctp100_formal_v2"
    checks = {
        "formal_preflight_passed": formal_preflight.get("status") == "passed",
        "benchmark_points_to_ctp100_formal_v2": bool(points_to_ctp100 or direct_ctp100),
        "case_count_100": len(cases) == CTP100_M2_M3_STABILITY_EXPECTED_CASES,
        "turn_count_130": turn_count == CTP100_M2_M3_STABILITY_EXPECTED_TURNS,
        "methods_are_m2_m3_only": tuple(CTP100_M2_M3_STABILITY_METHODS)
        == ("fixed_multi_agent", "adaptive_multi_agent"),
        "repeats_2": int(repeats) == CTP100_M2_M3_STABILITY_DEFAULT_REPEATS,
        "repeat_index_start_1": int(repeat_index_start) == 1,
        "expected_result_count_520": expected_raw
        == CTP100_M2_M3_STABILITY_EXPECTED_RESULTS,
        "protected_core_unchanged_from_ctp100_v6": protected_audit["status"]
        == "passed",
    }
    errors.extend(
        key
        for key, passed in checks.items()
        if not passed
        and key
        not in {
            "formal_preflight_passed",
            "protected_core_unchanged_from_ctp100_v6",
        }
    )
    return {
        "schema_version": "ctp100-m2-m3-stability-preflight-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "benchmark": {
            "path": benchmark_file.as_posix(),
            "dataset_id": benchmark_meta.get("dataset_id"),
            "dataset_version": benchmark_meta.get("dataset_version"),
            "case_files": list(benchmark_meta.get("case_files") or []),
            "dataset_sha256": canonical_json_sha256(document)
            if document is not None
            else None,
            "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY
            if document is not None
            else None,
            "case_count": len(cases),
            "turn_count": turn_count,
        },
        "run": {
            "run_id": run_id,
            "output_dir": _resolve_run_output_dir(output_dir, run_id).as_posix(),
            "methods": list(CTP100_M2_M3_STABILITY_METHODS),
            "method_count": len(CTP100_M2_M3_STABILITY_METHODS),
            "repeats": int(repeats),
            "repeat_index_start": int(repeat_index_start),
            "method_order_seed": int(method_order_seed),
            "model_config_name": model_config_name,
            "expected_raw_run_count": expected_raw,
        },
        "supplement_policy": {
            "source_main_run": "formal_ctp100_20260825_v6",
            "source_main_repeat_index": 0,
            "new_repeat_indices": [1, 2],
            "paper_role": "M2/M3 repeat-stability evidence for CTP100",
            "not_a_replacement_for_main_four_method_run": True,
            "m0_m1_not_rerun": True,
        },
        "method_contract_sha256": method_fairness_contract_hash(
            CTP100_M2_M3_STABILITY_METHODS
        ),
        "protected_core_audit": protected_audit,
        "formal_preflight": formal_preflight,
    }


def build_ctp100_m2_m3_stability_report(
    *,
    run_id: str,
    run_dir: Path,
    benchmark_path: str | Path,
    benchmark_document: Mapping[str, Any],
    cases: List[Dict[str, Any]],
    preflight: Mapping[str, Any],
    results: List[Dict[str, Any]],
    elapsed_seconds: float,
    pre_formal_smoke: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    traces = _load_traces(run_dir, results)
    expected_result_count = int(_mapping(preflight.get("run")).get("expected_raw_run_count") or 0)
    method_counts = Counter(str(result.get("method") or "unknown") for result in results)
    status_counts = Counter(str(result.get("status") or "unknown") for result in results)
    repeat_indices = sorted(
        {
            int(result.get("repeat_index"))
            for result in results
            if isinstance(result.get("repeat_index"), int)
        }
    )
    failed_results = [
        _result_identity(result)
        for result in results
        if str(result.get("status") or "").lower() not in {"completed", "clarification"}
    ]
    grid = _method_repeat_grid(
        results,
        expected_methods=CTP100_M2_M3_STABILITY_METHODS,
        expected_repeat_indices=[1, 2],
    )
    trace_audit = _trace_audit(traces)
    failure_classification = _failure_classification_summary(run_dir, results)
    api_failure_timeout = _api_failure_timeout_summary(traces)
    hard_timeout_result_count = sum(
        1 for result in results if bool(result.get("hard_timeout_triggered"))
    )
    checks = {
        "preflight_passed": preflight.get("status") == "passed",
        "expected_result_count": len(results) == expected_result_count,
        "methods_are_m2_m3_only": set(method_counts)
        == set(CTP100_M2_M3_STABILITY_METHODS),
        "method_counts_260_each": all(
            method_counts.get(method, 0)
            == CTP100_M2_M3_STABILITY_EXPECTED_TURNS
            * CTP100_M2_M3_STABILITY_DEFAULT_REPEATS
            for method in CTP100_M2_M3_STABILITY_METHODS
        ),
        "repeat_indices_1_2": repeat_indices == [1, 2],
        "method_repeat_grid_complete": grid["missing_count"] == 0
        and grid["duplicate_count"] == 0,
        "no_m0_m1_results": not ({"llm_direct", "single_agent"} & set(method_counts)),
        "all_results_completed_or_clarification": not failed_results,
        "trace_count_matches_results": trace_audit["trace_file_count"] == len(results),
        "llm_calls_recorded": trace_audit["llm_call_count"] > 0 if results else False,
        "no_mock_calls": trace_audit["mock_call_count"] == 0,
        "no_fallback_calls": trace_audit["fallback_call_count"] == 0,
        "no_hard_timeout": hard_timeout_result_count == 0
        and api_failure_timeout.get("terminal_failure_count") == 0,
        "protected_core_unchanged_from_ctp100_v6": _mapping(
            preflight.get("protected_core_audit")
        ).get("status")
        == "passed",
    }
    failed_checks = [key for key, passed in checks.items() if not passed]
    return {
        "schema_version": CTP100_M2_M3_STABILITY_REPORT_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if not failed_checks else "failed",
        "run_id": run_id,
        "elapsed_seconds": round(float(elapsed_seconds), 3),
        "benchmark": {
            "path": Path(benchmark_path).as_posix(),
            "dataset_id": benchmark_document.get("dataset_id"),
            "dataset_version": benchmark_document.get("dataset_version"),
            "dataset_sha256": canonical_json_sha256(benchmark_document),
            "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
            "case_count": len(cases),
            "turn_count": _turn_count(cases),
        },
        "results": {
            "expected_raw_result_count": expected_result_count,
            "actual_raw_result_count": len(results),
            "method_counts": dict(sorted(method_counts.items())),
            "status_counts": dict(sorted(status_counts.items())),
            "repeat_indices": repeat_indices,
            "failed_result_count": len(failed_results),
            "failed_results": failed_results[:20],
        },
        "method_grid": grid,
        "trace_audit": trace_audit,
        "failure_classification_summary": failure_classification,
        "api_failure_timeout_summary": api_failure_timeout,
        "hard_timeout_result_count": hard_timeout_result_count,
        "checks": checks,
        "failed_checks": failed_checks,
        "preflight": {
            "path": (run_dir / PREFLIGHT_NAME).as_posix(),
            "status": preflight.get("status"),
            "formal_preflight_status": _mapping(preflight.get("formal_preflight")).get(
                "status"
            ),
        },
        "pre_formal_real_api_smoke": dict(pre_formal_smoke or {}),
        "supplement_policy": dict(_mapping(preflight.get("supplement_policy"))),
    }


def render_ctp100_m2_m3_stability_report(report: Mapping[str, Any]) -> str:
    results = _mapping(report.get("results"))
    trace = _mapping(report.get("trace_audit"))
    checks = _mapping(report.get("checks"))
    grid = _mapping(report.get("method_grid"))
    lines = [
        "# CTP100 M2/M3 Repeat-Stability Report",
        "",
        f"- status: `{report.get('status')}`",
        f"- run_id: `{report.get('run_id')}`",
        f"- expected_raw_result_count: `{results.get('expected_raw_result_count')}`",
        f"- actual_raw_result_count: `{results.get('actual_raw_result_count')}`",
        f"- method_counts: `{results.get('method_counts')}`",
        f"- repeat_indices: `{results.get('repeat_indices')}`",
        f"- trace_file_count: `{trace.get('trace_file_count')}`",
        f"- llm_call_count: `{trace.get('llm_call_count')}`",
        f"- missing_grid_count: `{grid.get('missing_count')}`",
        f"- duplicate_grid_count: `{grid.get('duplicate_count')}`",
        "",
        "## Gate checks",
        "",
        "| check | passed |",
        "| --- | --- |",
    ]
    for key, value in checks.items():
        lines.append(f"| {key} | `{value}` |")
    lines.extend(
        [
            "",
            "## Paper-use boundary",
            "",
            (
                "This run supplements the frozen CTP100 v6 main experiment with "
                "two additional M2/M3 repeats. It must be analyzed together with "
                "the original v6 M2/M3 rows and must not replace the four-method "
                "main result."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def _method_repeat_grid(
    results: Iterable[Mapping[str, Any]],
    *,
    expected_methods: Sequence[str],
    expected_repeat_indices: Sequence[int],
) -> Dict[str, Any]:
    seen: Counter[tuple[str, str, int]] = Counter()
    for result in results:
        case_id = str(result.get("scenario_id") or result.get("case_id") or "")
        turn_id = str(result.get("turn_id") or "")
        method = str(result.get("method") or "")
        repeat_index = result.get("repeat_index")
        if not isinstance(repeat_index, int):
            continue
        seen[(case_id, turn_id, repeat_index, method)] += 1
    expected: List[tuple[str, str, int, str]] = []
    case_turns = sorted({(key[0], key[1]) for key in seen})
    for case_id, turn_id in case_turns:
        for repeat_index in expected_repeat_indices:
            for method in expected_methods:
                expected.append((case_id, turn_id, repeat_index, method))
    missing = [key for key in expected if seen.get(key, 0) == 0]
    duplicates = [
        {"case_id": key[0], "turn_id": key[1], "repeat_index": key[2], "method": key[3], "count": count}
        for key, count in seen.items()
        if count > 1
    ]
    return {
        "expected_key_count": len(expected),
        "actual_unique_key_count": len(seen),
        "missing_count": len(missing),
        "duplicate_count": len(duplicates),
        "sample_missing": [
            {
                "case_id": key[0],
                "turn_id": key[1],
                "repeat_index": key[2],
                "method": key[3],
            }
            for key in missing[:20]
        ],
        "sample_duplicates": duplicates[:20],
    }


def _trace_audit(traces: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    traces = list(traces)
    llm_calls = [
        call
        for trace in traces
        for call in trace.get("llm_calls") or []
        if isinstance(call, Mapping)
    ]
    return {
        "trace_file_count": len(traces),
        "llm_call_count": len(llm_calls),
        "mock_call_count": sum(1 for call in llm_calls if call.get("mock") or call.get("mock_used")),
        "fallback_call_count": sum(
            1 for call in llm_calls if call.get("fallback") or call.get("fallback_used")
        ),
        "failed_llm_call_count": sum(1 for call in llm_calls if call.get("success") is False),
        "methods_in_traces": sorted(
            {str(trace.get("method") or "") for trace in traces if trace.get("method")}
        ),
    }


def _turn_count(cases: Iterable[Mapping[str, Any]]) -> int:
    total = 0
    for case in cases:
        turns = case.get("turns")
        total += len(turns) if isinstance(turns, list) and turns else 1
    return total


def _result_identity(result: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "case_id": result.get("case_id"),
        "scenario_id": result.get("scenario_id"),
        "turn_id": result.get("turn_id"),
        "method": result.get("method"),
        "repeat_index": result.get("repeat_index"),
        "status": result.get("status"),
        "error": result.get("error"),
    }


def _attach_stability_metadata_to_manifest(
    run_dir: Path,
    *,
    report: Mapping[str, Any],
    preflight: Mapping[str, Any],
) -> None:
    manifest_path = run_dir / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    manifest["stability_experiment"] = {
        "schema_version": CTP100_M2_M3_STABILITY_REPORT_SCHEMA_VERSION,
        "status": report.get("status"),
        "failed_checks": report.get("failed_checks") or [],
        "paper_role": "M2/M3 repeat-stability evidence for CTP100",
        "source_main_run": "formal_ctp100_20260825_v6",
        "source_main_commit": CTP100_V6_FROZEN_COMMIT,
        "new_repeat_indices": [1, 2],
        "preflight_sha256": canonical_json_sha256(preflight),
    }
    _write_json(manifest_path, manifest)


def _write_stability_report(run_dir: Path, report: Mapping[str, Any]) -> None:
    _write_json(run_dir / REPORT_JSON_NAME, report)
    (run_dir / REPORT_MD_NAME).write_text(
        render_ctp100_m2_m3_stability_report(report),
        encoding="utf-8",
    )


def _stability_artifact_files(benchmark_path: str | Path) -> Dict[str, str | Path]:
    return {
        "ctp100_benchmark_source": Path(benchmark_path),
        "stability_preflight": PREFLIGHT_NAME,
        "benchmark_results_csv": "benchmark_results.csv",
        "benchmark_results_json": "benchmark_results.json",
        "benchmark_results_checkpoint_csv": "benchmark_results.checkpoint.csv",
        "benchmark_results_checkpoint_json": "benchmark_results.checkpoint.json",
        "evaluation_summary": "evaluation_summary.json",
        "paper_tables": "paper_tables.md",
        "experiment_manifest": MANIFEST_NAME,
        "benchmark_resume_state": "benchmark_resume_state.json",
        "stability_gate": REPORT_JSON_NAME,
        "stability_report": REPORT_MD_NAME,
    }


def _payload(
    run_id: str,
    run_dir: Path,
    report: Mapping[str, Any],
    *,
    final_index: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    results = _mapping(report.get("results"))
    payload = {
        "status": report.get("status"),
        "run_id": run_id,
        "output_dir": run_dir.as_posix(),
        "result_count": results.get("actual_raw_result_count"),
        "expected_count": results.get("expected_raw_result_count"),
        "stability_gate": (run_dir / REPORT_JSON_NAME).as_posix(),
        "stability_report": (run_dir / REPORT_MD_NAME).as_posix(),
        "manifest": (run_dir / MANIFEST_NAME).as_posix(),
        "checkpoint_json": (run_dir / "benchmark_results.checkpoint.json").as_posix(),
        "checkpoint_csv": (run_dir / "benchmark_results.checkpoint.csv").as_posix(),
        "traces": (run_dir / "traces").as_posix(),
        "failed_checks": report.get("failed_checks") or [],
    }
    if final_index:
        payload["final_artifact_index_json"] = final_index.get("json")
        payload["final_artifact_index_status"] = final_index.get("index_status")
    return payload


def _resolve_run_output_dir(output_dir: str | Path, run_id: str) -> Path:
    root = Path(output_dir)
    return root if root.name == run_id else root / run_id


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _raise_stability_preflight_error(preflight: Mapping[str, Any]) -> None:
    errors = preflight.get("errors") or []
    message = "CTP100 M2/M3 stability preflight failed"
    if errors:
        message += ":\n" + "\n".join(f"- {error}" for error in errors)
    raise RuntimeError(message)


def _protected_core_hash_audit(
    frozen_commit: str,
    paths: Sequence[str],
) -> Dict[str, Any]:
    if not frozen_commit:
        return {"status": "skipped", "reason": "no frozen commit supplied"}
    frozen_paths = _git_ls_tree(frozen_commit, paths)
    if frozen_paths is None:
        return {"status": "failed", "error": f"cannot inspect frozen commit: {frozen_commit}"}
    changed_paths = _git_diff_name_only(frozen_commit, paths)
    if changed_paths is None:
        return {"status": "failed", "error": f"cannot diff frozen commit: {frozen_commit}"}
    mismatches = []
    missing_current = []
    missing_frozen = []
    compared = 0
    for relative_path in frozen_paths:
        current_path = ROOT / relative_path
        frozen_bytes = _git_show_bytes(frozen_commit, relative_path)
        if frozen_bytes is None:
            missing_frozen.append(relative_path)
            continue
        if not current_path.exists():
            missing_current.append(relative_path)
            continue
        current_sha = _bytes_sha256(_canonical_bytes_for_hash(current_path.read_bytes()))
        frozen_sha = _bytes_sha256(_canonical_bytes_for_hash(frozen_bytes))
        compared += 1
        if current_sha != frozen_sha:
            mismatches.append(
                {
                    "path": relative_path,
                    "current_sha256": current_sha,
                    "frozen_sha256": frozen_sha,
                }
            )
    errors = []
    if missing_current:
        errors.append("missing_current_files")
    if missing_frozen:
        errors.append("missing_frozen_files")
    if changed_paths:
        errors.append("git_diff_detected_protected_changes")
    if mismatches:
        errors.append("hash_mismatch")
    return {
        "schema_version": "ctp100-m2-m3-stability-protected-core-audit-v1",
        "status": "passed" if not errors else "failed",
        "frozen_commit": frozen_commit,
        "protected_paths": list(paths),
        "compared_file_count": compared,
        "git_diff_changed_path_count": len(changed_paths),
        "mismatch_count": len(mismatches),
        "missing_current_count": len(missing_current),
        "missing_frozen_count": len(missing_frozen),
        "errors": errors,
        "sample_git_diff_changed_paths": changed_paths[:20],
        "sample_mismatches": mismatches[:20],
        "sample_missing_current": missing_current[:20],
        "sample_missing_frozen": missing_frozen[:20],
    }


def _git_ls_tree(commit: str, paths: Sequence[str]) -> Optional[List[str]]:
    try:
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", commit, "--", *paths],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _git_diff_name_only(commit: str, paths: Sequence[str]) -> Optional[List[str]]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", commit, "HEAD", "--", *paths],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _git_show_bytes(commit: str, relative_path: str) -> Optional[bytes]:
    try:
        result = subprocess.run(
            ["git", "show", f"{commit}:{relative_path}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout


def _bytes_sha256(value: bytes) -> str:
    return __import__("hashlib").sha256(value).hexdigest()


def _canonical_bytes_for_hash(value: bytes) -> bytes:
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        return value
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
