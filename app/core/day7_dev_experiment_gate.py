"""Day 7 development-set real experiment evidence gate.

This gate is intentionally narrower than the formal paper gate.  It validates
that the 20-case development run produced complete real-run evidence
(104 raw rows, CSV, request-level traces, summary, paper tables, manifest, and
runtime audit fields), while keeping paper claims disabled because the
development set is not the final 100-150 case test set.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from app.core.experiment_paper_analysis import DEFAULT_REQUIRED_METHODS
from app.core.experiment_run_audit import RUN_AUDIT_SCHEMA_VERSION
from app.core.formal_experiment_preflight import FORMAL_PREFLIGHT_SCHEMA_VERSION


DAY7_DEV_EXPERIMENT_GATE_SCHEMA_VERSION = "ctp-day7-dev-experiment-gate-v1"
DAY7_DEV_EXPERIMENT_GATE_NAME = "day7_dev_gate.json"
DAY7_DEV_EXPERIMENT_REPORT_NAME = "day7_dev_report.md"
DAY7_DEV_PREFLIGHT_REPORT_NAME = "day7_dev_preflight_report.json"

DEFAULT_DEV_CASE_COUNT = 20
DEFAULT_DEV_TURN_COUNT = 26
DEFAULT_DEV_SCENARIO_CASE_COUNT = 6
DEFAULT_INFRASTRUCTURE_FAILURE_RATE_LIMIT = 0.05
DEFAULT_DAY7_DEV_MAX_TOKENS = 4096
DEFAULT_TOKEN_CAP_HIT_RATE_LIMIT = 0.05

_CORE_ARTIFACTS = {
    "csv": "benchmark_results.csv",
    "json": "benchmark_results.json",
    "summary": "evaluation_summary.json",
    "paper_tables": "paper_tables.md",
    "manifest": "experiment_manifest.json",
}
_RUNTIME_FIELDS = (
    "model",
    "temperature",
    "max_tokens",
    "timeout_seconds",
    "retry_max_attempts",
    "reasoning_effort",
)


def write_day7_dev_experiment_gate(
    run_dir: str | Path,
    *,
    expected_case_count: int = DEFAULT_DEV_CASE_COUNT,
    expected_turn_count: int = DEFAULT_DEV_TURN_COUNT,
    expected_scenario_case_count: int = DEFAULT_DEV_SCENARIO_CASE_COUNT,
    required_methods: Optional[Iterable[str]] = None,
    allow_mock_llm: bool = False,
    infrastructure_failure_rate_limit: float = DEFAULT_INFRASTRUCTURE_FAILURE_RATE_LIMIT,
    expected_max_tokens: int = DEFAULT_DAY7_DEV_MAX_TOKENS,
    token_cap_hit_rate_limit: float = DEFAULT_TOKEN_CAP_HIT_RATE_LIMIT,
    attach_to_manifest: bool = True,
) -> Dict[str, Any]:
    """Write the Day 7 development-set gate JSON/Markdown artifacts."""
    root = Path(run_dir)
    gate = build_day7_dev_experiment_gate(
        root,
        expected_case_count=expected_case_count,
        expected_turn_count=expected_turn_count,
        expected_scenario_case_count=expected_scenario_case_count,
        required_methods=required_methods,
        allow_mock_llm=allow_mock_llm,
        infrastructure_failure_rate_limit=infrastructure_failure_rate_limit,
        expected_max_tokens=expected_max_tokens,
        token_cap_hit_rate_limit=token_cap_hit_rate_limit,
    )
    gate_path = root / DAY7_DEV_EXPERIMENT_GATE_NAME
    report_path = root / DAY7_DEV_EXPERIMENT_REPORT_NAME
    gate["artifact_paths"]["day7_dev_gate"] = gate_path.as_posix()
    gate["artifact_paths"]["day7_dev_report"] = report_path.as_posix()
    gate_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(render_day7_dev_experiment_report(gate), encoding="utf-8")
    if attach_to_manifest:
        _attach_to_manifest(
            root,
            gate=gate,
            gate_path=gate_path,
            report_path=report_path,
        )
        gate = refresh_day7_dev_artifact_index(root)
    return {
        "status": "completed",
        "gate": gate,
        "json": gate_path.as_posix(),
        "markdown": report_path.as_posix(),
        "gate_status": gate["status"],
        "paper_claims_allowed": gate["paper_claims_allowed"],
        "failed_checks": gate["failed_checks"],
    }


def build_day7_dev_experiment_gate(
    run_dir: str | Path,
    *,
    expected_case_count: int = DEFAULT_DEV_CASE_COUNT,
    expected_turn_count: int = DEFAULT_DEV_TURN_COUNT,
    expected_scenario_case_count: int = DEFAULT_DEV_SCENARIO_CASE_COUNT,
    required_methods: Optional[Iterable[str]] = None,
    allow_mock_llm: bool = False,
    infrastructure_failure_rate_limit: float = DEFAULT_INFRASTRUCTURE_FAILURE_RATE_LIMIT,
    expected_max_tokens: int = DEFAULT_DAY7_DEV_MAX_TOKENS,
    token_cap_hit_rate_limit: float = DEFAULT_TOKEN_CAP_HIT_RATE_LIMIT,
) -> Dict[str, Any]:
    """Build a machine-readable evidence gate for a saved dev-set run."""
    root = Path(run_dir)
    required = _normalize_methods(required_methods or DEFAULT_REQUIRED_METHODS)
    artifacts = _load_artifacts(root)
    results = artifacts["results"]
    csv_rows = _read_csv_rows(root / _CORE_ARTIFACTS["csv"])
    traces = _load_traces(root, results)
    llm_calls = [
        call
        for trace in traces
        for call in _as_dict_list(trace.get("llm_calls"))
    ]
    expected_raw_result_count = expected_turn_count * len(required)
    method_counts = _method_result_counts(results, required)
    raw_pairing = _raw_turn_pairing(results, required)
    state_isolation = _multi_turn_state_isolation(results, required)
    runtime_audit = _runtime_audit(
        artifacts["manifest"],
        llm_calls,
        expected_max_tokens=expected_max_tokens,
    )
    output_length_risk = _output_length_risk_summary(
        llm_calls,
        token_cap_hit_rate_limit=token_cap_hit_rate_limit,
    )
    trace_summary = _trace_summary(root, results, traces, llm_calls)
    field_completeness = _field_completeness(results)
    infrastructure = _infrastructure_failure_summary(
        results,
        llm_calls,
        expected_raw_result_count=expected_raw_result_count,
    )
    summary = _dict(artifacts["summary"])
    manifest = _dict(artifacts["manifest"])
    preflight = _dict(artifacts["preflight"])
    benchmark_structure = _dict(manifest.get("benchmark_structure"))
    quality_pairing_required = {
        "fixed_multi_agent",
        "adaptive_multi_agent",
    }.issubset(set(required))
    checks = {
        "run_dir_exists": root.exists(),
        "core_artifacts_saved": all((root / name).exists() for name in _CORE_ARTIFACTS.values()),
        "day7_dev_preflight_saved": bool(preflight),
        "day7_dev_preflight_schema_valid": preflight.get("schema_version")
        == FORMAL_PREFLIGHT_SCHEMA_VERSION,
        "day7_dev_preflight_passed": preflight.get("status") == "passed",
        "case_count_matches": _int(benchmark_structure.get("case_count")) == expected_case_count,
        "turn_count_matches": _int(benchmark_structure.get("total_turn_count")) == expected_turn_count,
        "scenario_case_count_matches": _int(benchmark_structure.get("scenario_case_count"))
        == expected_scenario_case_count,
        "result_count_matches": len(results) == expected_raw_result_count,
        "csv_row_count_matches": len(csv_rows) == expected_raw_result_count,
        "summary_raw_run_count_matches": _int(summary.get("raw_run_count")) == expected_raw_result_count,
        "summary_result_count_matches": _int(summary.get("result_count")) == expected_raw_result_count,
        "method_counts_match": all(
            method_counts["counts"].get(method) == expected_turn_count
            for method in required
        ),
        "required_methods_present": all(method in method_counts["counts"] for method in required),
        "raw_turn_pairing_complete": raw_pairing["complete"] is True,
        "quality_pairing_present": (
            _int(_nested(summary, "paired_statistics", "pair_count"), default=0)
            >= expected_case_count
            if quality_pairing_required
            else True
        ),
        "request_level_trace_count_matches": trace_summary["trace_file_count"]
        == expected_raw_result_count,
        "loaded_trace_count_matches": trace_summary["loaded_trace_count"]
        == expected_raw_result_count,
        "run_audit_attached": _all_results_have_run_audit(results),
        "runtime_audit_consistent": runtime_audit["consistent_with_manifest"] is True,
        "runtime_matches_day7_max_tokens_protocol": runtime_audit[
            "matches_day7_max_tokens_protocol"
        ]
        is True,
        "strict_runtime_recorded": _nested(manifest, "runtime_config", "strict_mode") is True,
        "cache_disabled_recorded": _nested(manifest, "runtime_config", "cache_disabled") is True,
        "deterministic_research_final_answer_recorded": _nested(
            manifest,
            "runtime_config",
            "deterministic_research_final_answer",
        )
        is True,
        "no_mock_llm": bool(allow_mock_llm) or trace_summary["mock_llm_call_count"] == 0,
        "no_llm_fallback": trace_summary["fallback_llm_call_count"] == 0,
        "no_cache_hit": trace_summary["cache_hit_count"] == 0,
        "token_latency_fields_complete": field_completeness["token_latency_complete"] is True,
        "cost_fields_complete_for_llm_rows": field_completeness[
            "cost_complete_for_llm_rows"
        ]
        is True,
        "multi_turn_state_isolation_passed": state_isolation["passed"] is True,
        "infrastructure_failure_rate_below_5pct": infrastructure["failure_rate"]
        < infrastructure_failure_rate_limit,
        "completion_token_cap_hit_rate_below_limit": output_length_risk[
            "completion_token_cap_hit_rate_below_limit"
        ]
        is True,
        "no_empty_outputs_at_token_cap": output_length_risk[
            "empty_and_token_capped_call_count"
        ]
        == 0,
        "artifact_hashes_recorded": bool(_artifact_index(root)["files"]),
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    status = "passed" if not failed_checks else "failed"
    artifact_index = _artifact_index(root)
    return {
        "schema_version": DAY7_DEV_EXPERIMENT_GATE_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "paper_claims_allowed": False,
        "run_id": manifest.get("run_id") or _nested(preflight, "run", "run_id"),
        "run_dir": root.as_posix(),
        "dataset_id": manifest.get("dataset_id") or _nested(manifest, "dataset", "id"),
        "dataset_version": manifest.get("dataset_version") or _nested(manifest, "dataset", "version"),
        "expected": {
            "case_count": expected_case_count,
            "turn_count": expected_turn_count,
            "scenario_case_count": expected_scenario_case_count,
            "method_count": len(required),
            "raw_result_count": expected_raw_result_count,
            "per_method_result_count": expected_turn_count,
            "infrastructure_failure_rate_limit": infrastructure_failure_rate_limit,
            "max_tokens": expected_max_tokens,
            "completion_token_cap_hit_rate_limit": token_cap_hit_rate_limit,
            "quality_pairing_required": quality_pairing_required,
        },
        "actual": {
            "case_count": benchmark_structure.get("case_count"),
            "turn_count": benchmark_structure.get("total_turn_count"),
            "scenario_case_count": benchmark_structure.get("scenario_case_count"),
            "raw_result_count": len(results),
            "csv_row_count": len(csv_rows),
            "summary_raw_run_count": summary.get("raw_run_count"),
            "summary_result_count": summary.get("result_count"),
            "quality_result_count": summary.get("quality_result_count"),
            "quality_pair_count": _nested(summary, "paired_statistics", "pair_count"),
        },
        "required_methods": required,
        "method_result_counts": method_counts,
        "raw_turn_pairing": raw_pairing,
        "multi_turn_state_isolation": state_isolation,
        "trace_summary": trace_summary,
        "runtime_audit": runtime_audit,
        "output_length_risk": output_length_risk,
        "field_completeness": field_completeness,
        "infrastructure_failures": infrastructure,
        "checks": checks,
        "failed_checks": failed_checks,
        "artifact_index": artifact_index,
        "artifact_paths": {
            key: (root / filename).as_posix()
            for key, filename in _CORE_ARTIFACTS.items()
            if (root / filename).exists()
        }
        | {
            "day7_dev_preflight": (root / DAY7_DEV_PREFLIGHT_REPORT_NAME).as_posix()
            if (root / DAY7_DEV_PREFLIGHT_REPORT_NAME).exists()
            else (root / "formal_preflight_report.json").as_posix()
        },
        "paper_use_policy": {
            "summary": (
                "This is a Day 7 development-set real run. It may support debugging, "
                "ablation planning, and preliminary tables, but it must not replace "
                "the final 100-150 case formal experiment."
            ),
            "allowed_uses": [
                "development-set real-run completeness evidence",
                "method failure diagnosis before expanding the dataset",
                "preliminary cost/token/latency estimates",
            ],
            "forbidden_uses": [
                "final paper conclusion",
                "claiming M3 superiority over M2 from the development split alone",
                "mixing development results with the final held-out test set",
            ],
        },
        "interpretation": _interpretation(status),
    }


def render_day7_dev_experiment_report(gate: Dict[str, Any]) -> str:
    """Render the dev-set evidence gate as Markdown."""
    expected = _dict(gate.get("expected"))
    actual = _dict(gate.get("actual"))
    traces = _dict(gate.get("trace_summary"))
    runtime = _dict(gate.get("runtime_audit"))
    fields = _dict(gate.get("field_completeness"))
    infra = _dict(gate.get("infrastructure_failures"))
    state = _dict(gate.get("multi_turn_state_isolation"))
    output_risk = _dict(gate.get("output_length_risk"))
    lines = [
        "# Day 7 开发集真实实验验收报告",
        "",
        "## 结论",
        "",
        f"- gate_status: `{gate.get('status')}`",
        f"- paper_claims_allowed: `{gate.get('paper_claims_allowed')}`",
        f"- run_id: `{gate.get('run_id')}`",
        f"- dataset: `{gate.get('dataset_id')}` / `{gate.get('dataset_version')}`",
        f"- expected_raw_results: `{expected.get('raw_result_count')}`",
        f"- actual_raw_results: `{actual.get('raw_result_count')}`",
        f"- csv_rows: `{actual.get('csv_row_count')}`",
        f"- trace_files: `{traces.get('trace_file_count')}`",
        f"- loaded_traces: `{traces.get('loaded_trace_count')}`",
        f"- runtime_consistent_with_manifest: `{runtime.get('consistent_with_manifest')}`",
        f"- runtime_matches_day7_max_tokens_protocol: `{runtime.get('matches_day7_max_tokens_protocol')}`",
        f"- completion_token_cap_hit_rate: `{_fmt(output_risk.get('completion_token_cap_hit_rate'))}`",
        f"- empty_and_token_capped_call_count: `{output_risk.get('empty_and_token_capped_call_count')}`",
        f"- infrastructure_failure_rate: `{_fmt(infra.get('failure_rate'))}`",
        f"- multi_turn_state_isolation: `{state.get('passed')}`",
        f"- failed_checks: `{gate.get('failed_checks') or []}`",
        "",
        "## 核心验收项",
        "",
        "| Check | Passed |",
        "|---|---:|",
    ]
    for key, value in _dict(gate.get("checks")).items():
        lines.append(f"| {key} | `{value}` |")

    lines.extend(
        [
            "",
            "## 四方法逐轮配对",
            "",
            "| Method | Result count |",
            "|---|---:|",
        ]
    )
    counts = _dict(_dict(gate.get("method_result_counts")).get("counts"))
    for method in gate.get("required_methods") or []:
        lines.append(f"| {method} | {counts.get(method, 0)} |")
    pairing = _dict(gate.get("raw_turn_pairing"))
    lines.extend(
        [
            "",
            f"- raw_turn_unit_count: `{pairing.get('unit_count')}`",
            f"- incomplete_unit_count: `{pairing.get('incomplete_unit_count')}`",
            f"- duplicate_unit_method_count: `{pairing.get('duplicate_unit_method_count')}`",
            "",
            "## 字段完整率",
            "",
            "| Field group | Complete | Complete rows | Total rows | Rate |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for group in ("token_latency", "cost_for_llm_rows"):
        row = _dict(fields.get(group))
        lines.append(
            f"| {group} | `{row.get('complete')}` | {row.get('complete_count')} "
            f"| {row.get('total_count')} | {_fmt(row.get('rate'))} |"
        )

    lines.extend(
        [
            "",
            "## Trace / Mock / Fallback / Cache",
            "",
            f"- llm_call_count: `{traces.get('llm_call_count')}`",
            f"- mock_llm_call_count: `{traces.get('mock_llm_call_count')}`",
            f"- fallback_llm_call_count: `{traces.get('fallback_llm_call_count')}`",
            f"- cache_hit_count: `{traces.get('cache_hit_count')}`",
            f"- total_tokens: `{traces.get('total_tokens')}`",
            f"- standardized_estimated_cost: `{traces.get('standardized_estimated_cost')}`",
            "",
            "## Output length risk",
            "",
            f"- completion_token_cap_hit_count: `{output_risk.get('completion_token_cap_hit_count')}`",
            f"- completion_token_cap_hit_rate: `{_fmt(output_risk.get('completion_token_cap_hit_rate'))}`",
            f"- completion_token_cap_hit_rate_limit: `{_fmt(output_risk.get('completion_token_cap_hit_rate_limit'))}`",
            f"- empty_output_call_count: `{output_risk.get('empty_output_call_count')}`",
            f"- empty_and_token_capped_call_count: `{output_risk.get('empty_and_token_capped_call_count')}`",
            f"- request_max_token_values: `{output_risk.get('request_max_token_values')}`",
            "",
            "## 多轮状态隔离",
            "",
            f"- expected_scenario_case_count: `{expected.get('scenario_case_count')}`",
            f"- observed_scenario_case_count: `{state.get('scenario_case_count')}`",
            f"- checked_method_scenario_count: `{state.get('checked_method_scenario_count')}`",
            f"- violation_count: `{state.get('violation_count')}`",
            "",
            "## 基础设施失败",
            "",
            f"- failed_result_count: `{infra.get('failed_result_count')}`",
            f"- failed_llm_call_count: `{infra.get('failed_llm_call_count')}`",
            f"- failure_rate: `{_fmt(infra.get('failure_rate'))}`",
            "",
            "## 产物哈希",
            "",
            "| Artifact | SHA-256 | Path |",
            "|---|---|---|",
        ]
    )
    for item in _dict(gate.get("artifact_index")).get("files") or []:
        lines.append(f"| {item.get('key')} | `{item.get('sha256')}` | `{item.get('path')}` |")
    return "\n".join(lines) + "\n"


def _load_artifacts(root: Path) -> Dict[str, Any]:
    preflight_path = root / DAY7_DEV_PREFLIGHT_REPORT_NAME
    if not preflight_path.exists():
        preflight_path = root / "formal_preflight_report.json"
    return {
        "results": _read_json_list(root / _CORE_ARTIFACTS["json"]),
        "summary": _read_json_object(root / _CORE_ARTIFACTS["summary"]),
        "manifest": _read_json_object(root / _CORE_ARTIFACTS["manifest"]),
        "preflight": _read_json_object(preflight_path),
    }


def _attach_to_manifest(
    root: Path,
    *,
    gate: Dict[str, Any],
    gate_path: Path,
    report_path: Path,
) -> None:
    manifest_path = root / _CORE_ARTIFACTS["manifest"]
    manifest = _read_json_object(manifest_path)
    if not manifest:
        return
    results = _dict(manifest.get("results"))
    results.update(
        {
            "day7_dev_gate": gate_path.as_posix(),
            "day7_dev_report": report_path.as_posix(),
        }
    )
    manifest["results"] = results
    manifest["day7_dev_experiment"] = {
        "schema_version": DAY7_DEV_EXPERIMENT_GATE_SCHEMA_VERSION,
        "status": gate.get("status"),
        "paper_claims_allowed": False,
        "expected": gate.get("expected"),
        "actual": gate.get("actual"),
        "failed_checks": gate.get("failed_checks") or [],
        "json": gate_path.as_posix(),
        "markdown": report_path.as_posix(),
        "interpretation": gate.get("interpretation"),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def refresh_day7_dev_artifact_index(run_dir: str | Path) -> Dict[str, Any]:
    """Refresh hashes after later scripts attach metadata to the manifest.

    Day 7 tools intentionally append their own artifact paths to
    ``experiment_manifest.json``.  Without this refresh step, the manifest hash
    stored in ``day7_dev_gate.json`` can describe a pre-attachment manifest and
    become stale before the run is frozen.
    """
    root = Path(run_dir)
    gate_path = root / DAY7_DEV_EXPERIMENT_GATE_NAME
    gate = _read_json_object(gate_path)
    if not gate:
        return {}
    gate["artifact_index"] = _artifact_index(root)
    gate["artifact_index"]["refreshed_at"] = datetime.now(timezone.utc).isoformat()
    artifact_paths = _dict(gate.get("artifact_paths"))
    artifact_paths["day7_dev_gate"] = gate_path.as_posix()
    artifact_paths["day7_dev_report"] = (root / DAY7_DEV_EXPERIMENT_REPORT_NAME).as_posix()
    gate["artifact_paths"] = artifact_paths
    gate_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / DAY7_DEV_EXPERIMENT_REPORT_NAME).write_text(
        render_day7_dev_experiment_report(gate),
        encoding="utf-8",
    )
    return gate


def _method_result_counts(
    results: List[Dict[str, Any]],
    required_methods: Sequence[str],
) -> Dict[str, Any]:
    counts = Counter(str(result.get("method") or "unknown") for result in results)
    missing = [method for method in required_methods if method not in counts]
    unexpected = sorted(method for method in counts if method not in set(required_methods))
    return {
        "counts": dict(sorted(counts.items())),
        "missing_methods": missing,
        "unexpected_methods": unexpected,
    }


def _raw_turn_pairing(
    results: List[Dict[str, Any]],
    required_methods: Sequence[str],
) -> Dict[str, Any]:
    required = set(required_methods)
    by_unit: Dict[str, List[str]] = defaultdict(list)
    duplicate_pairs: List[Dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for result in results:
        unit_id = _raw_turn_unit_id(result)
        method = str(result.get("method") or "unknown")
        pair = (unit_id, method)
        if pair in seen_pairs:
            duplicate_pairs.append({"unit_id": unit_id, "method": method})
        seen_pairs.add(pair)
        by_unit[unit_id].append(method)
    incomplete = []
    for unit_id, methods in sorted(by_unit.items()):
        observed = set(methods)
        if observed != required or len(methods) != len(required):
            incomplete.append(
                {
                    "unit_id": unit_id,
                    "observed_methods": sorted(observed),
                    "missing_methods": sorted(required - observed),
                    "extra_methods": sorted(observed - required),
                    "raw_count": len(methods),
                }
            )
    return {
        "complete": not incomplete and not duplicate_pairs and bool(by_unit),
        "unit_count": len(by_unit),
        "incomplete_unit_count": len(incomplete),
        "duplicate_unit_method_count": len(duplicate_pairs),
        "sample_incomplete_units": incomplete[:10],
        "sample_duplicate_unit_methods": duplicate_pairs[:10],
    }


def _multi_turn_state_isolation(
    results: List[Dict[str, Any]],
    required_methods: Sequence[str],
) -> Dict[str, Any]:
    scenario_rows = [
        result
        for result in results
        if result.get("scenario_id") and _int(result.get("scenario_turn_count"), default=1) > 1
    ]
    scenario_ids = sorted({str(result.get("scenario_id")) for result in scenario_rows})
    by_scenario_method: Dict[tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for result in scenario_rows:
        key = (str(result.get("scenario_id")), str(result.get("method") or "unknown"))
        by_scenario_method[key].append(result)

    violations: List[Dict[str, Any]] = []
    required_set = set(required_methods)
    for (scenario_id, method), rows in sorted(by_scenario_method.items()):
        if method not in required_set:
            continue
        ordered = sorted(rows, key=lambda row: _int(row.get("turn_index"), default=-1) or -1)
        for position, row in enumerate(ordered):
            turn_index = _int(row.get("turn_index"), default=position)
            expected_previous = turn_index > 0
            provided = _bool(row.get("previous_state_provided"))
            local = _bool(row.get("previous_state_is_method_local"))
            prior = _bool(row.get("previous_state_is_prior_turn"))
            has_eval = _bool(row.get("previous_state_has_evaluation"))
            has_metrics = _bool(row.get("previous_state_has_metrics"))
            if provided != expected_previous:
                violations.append(
                    _state_violation(row, "previous_state_presence_mismatch")
                )
            if expected_previous and not local:
                violations.append(_state_violation(row, "previous_state_cross_method"))
            if expected_previous and not prior:
                violations.append(_state_violation(row, "previous_state_not_prior_turn"))
            if has_eval or has_metrics:
                violations.append(_state_violation(row, "previous_state_contains_evaluator_data"))
    expected_group_count = len(scenario_ids) * len(required_methods)
    missing_groups = [
        {"scenario_id": scenario_id, "method": method}
        for scenario_id in scenario_ids
        for method in required_methods
        if (scenario_id, method) not in by_scenario_method
    ]
    return {
        "passed": not violations and not missing_groups and bool(scenario_ids),
        "scenario_case_count": len(scenario_ids),
        "checked_method_scenario_count": sum(
            1 for key in by_scenario_method if key[1] in required_set
        ),
        "expected_method_scenario_count": expected_group_count,
        "violation_count": len(violations),
        "missing_group_count": len(missing_groups),
        "sample_violations": violations[:10],
        "sample_missing_groups": missing_groups[:10],
        "policy": "method_local_previous_state_from_prior_turn_output",
    }


def _state_violation(result: Dict[str, Any], reason: str) -> Dict[str, Any]:
    return {
        "reason": reason,
        "case_id": result.get("case_id"),
        "scenario_id": result.get("scenario_id"),
        "turn_id": result.get("turn_id"),
        "turn_index": result.get("turn_index"),
        "method": result.get("method"),
        "previous_state_method": result.get("previous_state_method"),
        "previous_state_turn_index": result.get("previous_state_turn_index"),
    }


def _runtime_audit(
    manifest: Dict[str, Any],
    llm_calls: List[Dict[str, Any]],
    *,
    expected_max_tokens: int,
) -> Dict[str, Any]:
    runtime = _dict(manifest.get("runtime_config"))
    expected = {
        "model": runtime.get("model") or manifest.get("model"),
        "temperature": runtime.get("temperature") if "temperature" in runtime else manifest.get("temperature"),
        "max_tokens": runtime.get("max_tokens") if "max_tokens" in runtime else manifest.get("max_tokens"),
        "timeout_seconds": runtime.get("timeout_seconds")
        if "timeout_seconds" in runtime
        else manifest.get("timeout_seconds"),
        "retry_max_attempts": runtime.get("retry_max_attempts")
        if "retry_max_attempts" in runtime
        else manifest.get("retry_max_attempts"),
        "reasoning_effort": runtime.get("reasoning_effort")
        if "reasoning_effort" in runtime
        else manifest.get("reasoning_effort"),
    }
    mismatches = []
    protocol_mismatches = []
    values: Dict[str, set[str]] = defaultdict(set)
    for index, call in enumerate(llm_calls):
        options = _dict(call.get("request_options"))
        retry = _dict(call.get("retry"))
        observed = {
            "model": options.get("model") or call.get("model"),
            "temperature": options.get("temperature") if "temperature" in options else call.get("temperature"),
            "max_tokens": options.get("max_tokens") if "max_tokens" in options else call.get("max_tokens"),
            "timeout_seconds": options.get("timeout_seconds")
            if "timeout_seconds" in options
            else call.get("timeout_seconds"),
            "retry_max_attempts": retry.get("max_attempts")
            or options.get("retry_max_attempts")
            or call.get("retry_max_attempts"),
            "reasoning_effort": options.get("reasoning_effort")
            if "reasoning_effort" in options
            else call.get("reasoning_effort"),
        }
        for field in _RUNTIME_FIELDS:
            if observed.get(field) is not None:
                values[field].add(str(observed[field]))
            if expected.get(field) is not None and not _same_value(expected[field], observed.get(field)):
                mismatches.append(
                    {
                        "call_index": index,
                        "field": field,
                        "manifest_value": expected.get(field),
                        "call_value": observed.get(field),
                    }
                )
        if not _same_value(expected_max_tokens, observed.get("max_tokens")):
            protocol_mismatches.append(
                {
                    "call_index": index,
                    "field": "max_tokens",
                    "expected_protocol_value": expected_max_tokens,
                    "call_value": observed.get("max_tokens"),
                }
            )
    manifest_matches_protocol = _same_value(expected_max_tokens, expected.get("max_tokens"))
    if not manifest_matches_protocol:
        protocol_mismatches.insert(
            0,
            {
                "call_index": None,
                "field": "max_tokens",
                "expected_protocol_value": expected_max_tokens,
                "manifest_value": expected.get("max_tokens"),
            },
        )
    return {
        "manifest_runtime": expected,
        "llm_call_count": len(llm_calls),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:20],
        "consistent_with_manifest": bool(llm_calls) and not mismatches,
        "request_option_values": {
            field: sorted(field_values)
            for field, field_values in sorted(values.items())
        },
        "day7_max_tokens_protocol": {
            "expected_max_tokens": expected_max_tokens,
            "manifest_matches_protocol": manifest_matches_protocol,
            "protocol_mismatch_count": len(protocol_mismatches),
            "sample_protocol_mismatches": protocol_mismatches[:20],
        },
        "matches_day7_max_tokens_protocol": bool(llm_calls)
        and manifest_matches_protocol
        and not protocol_mismatches,
    }


def _output_length_risk_summary(
    llm_calls: List[Dict[str, Any]],
    *,
    token_cap_hit_rate_limit: float,
) -> Dict[str, Any]:
    capped_calls = []
    empty_calls = []
    empty_and_capped_calls = []
    max_token_values: Counter[str] = Counter()
    for index, call in enumerate(llm_calls):
        max_tokens = _call_max_tokens(call)
        completion_tokens = _call_completion_tokens(call)
        output_chars = _first_number(call.get("output_chars"))
        if max_tokens is not None:
            max_token_values[str(int(max_tokens) if max_tokens.is_integer() else max_tokens)] += 1
        capped = (
            max_tokens is not None
            and completion_tokens is not None
            and completion_tokens >= max_tokens
        )
        empty = output_chars == 0
        ref = {
            "call_index": index,
            "call_id": call.get("call_id") or call.get("id"),
            "agent_name": call.get("agent_name"),
            "component": call.get("component"),
            "completion_tokens": completion_tokens,
            "max_tokens": max_tokens,
            "output_chars": output_chars,
        }
        if capped:
            capped_calls.append(ref)
        if empty:
            empty_calls.append(ref)
        if capped and empty:
            empty_and_capped_calls.append(ref)
    cap_rate = _rate(len(capped_calls), len(llm_calls)) or 0.0
    return {
        "llm_call_count": len(llm_calls),
        "completion_token_cap_hit_count": len(capped_calls),
        "completion_token_cap_hit_rate": cap_rate,
        "completion_token_cap_hit_rate_limit": float(token_cap_hit_rate_limit),
        "completion_token_cap_hit_rate_below_limit": cap_rate
        <= float(token_cap_hit_rate_limit),
        "empty_output_call_count": len(empty_calls),
        "empty_and_token_capped_call_count": len(empty_and_capped_calls),
        "request_max_token_values": dict(sorted(max_token_values.items())),
        "sample_token_capped_calls": capped_calls[:10],
        "sample_empty_and_token_capped_calls": empty_and_capped_calls[:10],
        "interpretation": (
            "High cap-hit or empty-and-capped counts indicate that output-length "
            "limits, not method capability, may be depressing baseline quality."
        ),
    }


def _call_completion_tokens(call: Dict[str, Any]) -> Optional[float]:
    usage = call.get("usage") if isinstance(call.get("usage"), dict) else call.get("tokens")
    usage = usage if isinstance(usage, dict) else {}
    return _first_number(usage.get("completion_tokens"), usage.get("output_tokens"))


def _call_max_tokens(call: Dict[str, Any]) -> Optional[float]:
    options = _dict(call.get("request_options"))
    return _first_number(
        options.get("max_tokens"),
        call.get("max_tokens"),
    )


def _trace_summary(
    root: Path,
    results: List[Dict[str, Any]],
    traces: List[Dict[str, Any]],
    llm_calls: List[Dict[str, Any]],
) -> Dict[str, Any]:
    trace_files = {
        path.as_posix()
        for path in (
            _resolve_trace_path(root, result.get("trace_file"))
            for result in results
        )
        if path and path.exists()
    }
    return {
        "trace_file_count": len(trace_files),
        "loaded_trace_count": len(traces),
        "trace_without_llm_call_count": sum(
            1 for trace in traces if not _as_dict_list(trace.get("llm_calls"))
        ),
        "llm_call_count": len(llm_calls),
        "mock_llm_call_count": sum(
            _bool(call.get("mock")) or _bool(call.get("mock_used"))
            for call in llm_calls
        ),
        "fallback_llm_call_count": sum(
            _bool(call.get("fallback")) or _bool(call.get("fallback_used"))
            for call in llm_calls
        ),
        "cache_hit_count": _cache_hit_count(traces, llm_calls),
        "prompt_tokens": _sum_usage(llm_calls, "prompt_tokens", "input_tokens"),
        "completion_tokens": _sum_usage(llm_calls, "completion_tokens", "output_tokens"),
        "reasoning_tokens": _sum_nested_usage(
            llm_calls,
            "completion_tokens_details",
            "reasoning_tokens",
        ),
        "total_tokens": _sum_usage(llm_calls, "total_tokens", "tokens_used"),
        "estimated_cost": _sum_number(call.get("estimated_cost") for call in llm_calls),
        "standardized_estimated_cost": _sum_number(
            call.get("standardized_estimated_cost") for call in llm_calls
        ),
        "retry_count": _sum_number(call.get("retry_count") for call in llm_calls),
    }


def _field_completeness(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    token_latency_complete = [
        result
        for result in results
        if _metric_present(result, "total_tokens") and _number(result.get("latency_ms")) is not None
    ]
    llm_rows = [
        result
        for result in results
        if _number(_nested(result, "metrics", "llm_call_count")) not in (None, 0)
    ]
    cost_complete = [
        result
        for result in llm_rows
        if _metric_present(result, "estimated_cost")
        and _metric_present(result, "standardized_estimated_cost")
    ]
    token_latency_rate = _rate(len(token_latency_complete), len(results))
    cost_rate = _rate(len(cost_complete), len(llm_rows))
    return {
        "token_latency_complete": len(token_latency_complete) == len(results) and bool(results),
        "cost_complete_for_llm_rows": len(cost_complete) == len(llm_rows),
        "token_latency": {
            "complete": len(token_latency_complete) == len(results) and bool(results),
            "complete_count": len(token_latency_complete),
            "total_count": len(results),
            "rate": token_latency_rate,
            "sample_missing": [
                _result_ref(result)
                for result in results
                if result not in token_latency_complete
            ][:10],
        },
        "cost_for_llm_rows": {
            "complete": len(cost_complete) == len(llm_rows),
            "complete_count": len(cost_complete),
            "total_count": len(llm_rows),
            "rate": cost_rate,
            "sample_missing": [
                _result_ref(result)
                for result in llm_rows
                if result not in cost_complete
            ][:10],
            "non_llm_row_count": len(results) - len(llm_rows),
        },
    }


def _infrastructure_failure_summary(
    results: List[Dict[str, Any]],
    llm_calls: List[Dict[str, Any]],
    *,
    expected_raw_result_count: int,
) -> Dict[str, Any]:
    failed_results = [
        result
        for result in results
        if result.get("error") or _looks_infrastructure_error(result)
    ]
    failed_llm_calls = [
        call
        for call in llm_calls
        if call.get("success") is False or call.get("error")
    ]
    denominator = expected_raw_result_count or len(results)
    return {
        "failed_result_count": len(failed_results),
        "failed_llm_call_count": len(failed_llm_calls),
        "failure_rate": _rate(len(failed_results), denominator) or 0.0,
        "sample_failed_results": [_result_ref(result) for result in failed_results[:10]],
        "sample_failed_llm_calls": [
            {
                "call_id": call.get("call_id") or call.get("id"),
                "model": call.get("model"),
                "error": call.get("error"),
            }
            for call in failed_llm_calls[:10]
        ],
    }


def _artifact_index(root: Path) -> Dict[str, Any]:
    files = []
    artifact_paths = {
        **_CORE_ARTIFACTS,
        "day7_dev_preflight": DAY7_DEV_PREFLIGHT_REPORT_NAME,
    }
    if not (root / DAY7_DEV_PREFLIGHT_REPORT_NAME).exists():
        artifact_paths["formal_preflight"] = "formal_preflight_report.json"
    for key, filename in artifact_paths.items():
        path = root / filename
        if not path.exists():
            continue
        files.append(
            {
                "key": key,
                "path": path.as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _file_sha256(path),
            }
        )
    trace_dir = root / "traces"
    trace_files = sorted(trace_dir.glob("*.jsonl")) if trace_dir.exists() else []
    trace_hashes = [_file_sha256(path) for path in trace_files]
    return {
        "schema_version": "ctp-day7-dev-artifact-index-v1",
        "hash_strategy": "sha256_file_bytes_v1",
        "files": files,
        "trace_dir": trace_dir.as_posix(),
        "trace_file_count": len(trace_files),
        "trace_combined_sha256": _combined_hash(trace_hashes),
    }


def _all_results_have_run_audit(results: List[Dict[str, Any]]) -> bool:
    if not results:
        return False
    for result in results:
        audit = result.get("run_audit")
        if not isinstance(audit, dict) or audit.get("schema_version") != RUN_AUDIT_SCHEMA_VERSION:
            return False
        if not isinstance(audit.get("metrics"), dict):
            return False
    return True


def _metric_present(result: Dict[str, Any], key: str) -> bool:
    return _nested(result, "metrics", key) is not None


def _looks_infrastructure_error(result: Dict[str, Any]) -> bool:
    output = result.get("raw_output") if isinstance(result.get("raw_output"), dict) else result.get("output")
    if not isinstance(output, dict):
        return False
    text = " ".join(
        str(value)
        for value in (
            output.get("error"),
            _nested(output, "metadata", "structured_llm_output", "failure_reason"),
        )
        if value
    ).lower()
    infrastructure_markers = (
        "api",
        "timeout",
        "connection",
        "rate limit",
        "429",
        "500",
        "502",
        "503",
        "504",
        "sdk",
        "network",
    )
    return any(marker in text for marker in infrastructure_markers)


def _raw_turn_unit_id(result: Dict[str, Any]) -> str:
    scenario_id = str(result.get("scenario_id") or "").strip()
    turn_id = str(result.get("turn_id") or "").strip()
    if scenario_id and turn_id:
        return f"{scenario_id}::{turn_id}"
    return str(result.get("case_id") or result.get("request_id") or "").strip()


def _result_ref(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "case_id": result.get("case_id"),
        "scenario_id": result.get("scenario_id"),
        "turn_id": result.get("turn_id"),
        "method": result.get("method"),
        "request_id": result.get("request_id"),
        "status": result.get("status"),
        "error": result.get("error"),
    }


def _load_traces(root: Path, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    traces: List[Dict[str, Any]] = []
    for result in results:
        path = _resolve_trace_path(root, result.get("trace_file"))
        if path and path.exists():
            loaded = _read_jsonl_first(path)
            if loaded:
                loaded["trace_file"] = path.as_posix()
                traces.append(loaded)
                continue
        trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
        if trace:
            traces.append(trace)
    return traces


def _resolve_trace_path(root: Path, value: Any) -> Optional[Path]:
    if not value:
        return None
    path = Path(str(value))
    if path.is_absolute():
        return path
    for candidate in (root / path, root.parent / path, Path.cwd() / path):
        if candidate.exists():
            return candidate
    return path


def _read_json_object(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_json_list(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _read_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_jsonl_first(path: Path) -> Dict[str, Any]:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _combined_hash(hashes: List[str]) -> Optional[str]:
    if not hashes:
        return None
    return hashlib.sha256("\n".join(sorted(hashes)).encode("utf-8")).hexdigest()


def _cache_hit_count(traces: List[Dict[str, Any]], llm_calls: List[Dict[str, Any]]) -> int:
    trace_hits = sum(_int(trace.get("cache_hit_count"), default=0) or 0 for trace in traces)
    llm_hits = sum(1 for call in llm_calls if _bool(call.get("cache_hit")))
    return trace_hits + llm_hits


def _sum_usage(calls: List[Dict[str, Any]], *keys: str) -> Optional[float]:
    values = []
    for call in calls:
        usage = call.get("usage") if isinstance(call.get("usage"), dict) else call.get("tokens")
        usage = usage if isinstance(usage, dict) else {}
        values.append(_first_number(*(usage.get(key) for key in keys)))
    return _sum_number(values)


def _sum_nested_usage(calls: List[Dict[str, Any]], *keys: str) -> Optional[float]:
    values = []
    for call in calls:
        usage = call.get("usage") if isinstance(call.get("usage"), dict) else call.get("tokens")
        current: Any = usage if isinstance(usage, dict) else {}
        for key in keys:
            current = current.get(key) if isinstance(current, dict) else None
        values.append(_first_number(current))
    return _sum_number(values)


def _sum_number(values: Iterable[Any]) -> Optional[float]:
    numbers = [_first_number(value) for value in values]
    numbers = [value for value in numbers if value is not None]
    return None if not numbers else round(sum(numbers), 4)


def _first_number(*values: Any) -> Optional[float]:
    for value in values:
        number = _number(value)
        if number is not None:
            return number
    return None


def _rate(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _same_value(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    left_number = _number(left)
    right_number = _number(right)
    if left_number is not None and right_number is not None:
        return abs(left_number - right_number) < 1e-9
    return str(left) == str(right)


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _int(*values: Any, default: Optional[int] = None) -> Optional[int]:
    for value in values:
        number = _number(value)
        if number is not None:
            return int(number)
    return default


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_dict_list(value: Any) -> List[Dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _normalize_methods(methods: Iterable[str]) -> List[str]:
    normalized = [str(method).strip().lower() for method in methods if str(method).strip()]
    if not normalized:
        raise ValueError("required_methods must not be empty")
    return normalized


def _interpretation(status: str) -> str:
    if status == "passed":
        return (
            "Development-set real-run evidence is complete enough for Day 7 "
            "diagnosis and for deciding whether to expand to the formal set."
        )
    return "Development-set evidence is incomplete; inspect failed_checks before using it."


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return str(round(value, 4))
    return str(value)
