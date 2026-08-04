"""Final evidence gate for paper-level formal experiment runs.

The preflight gate checks whether a run is allowed to start.  This module
checks the opposite end of the pipeline: after a formal run has finished, are
the saved artifacts complete enough to support paper claims?
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.core.experiment_paper_analysis import (
    DEFAULT_REQUIRED_METHODS,
    PAPER_ANALYSIS_JSON_NAME,
    PAPER_ANALYSIS_MD_NAME,
    PAPER_ANALYSIS_SCHEMA_VERSION,
    write_experiment_paper_analysis,
)
from app.core.experiment_run_audit import RUN_AUDIT_SCHEMA_VERSION
from app.core.formal_experiment_preflight import FORMAL_PREFLIGHT_SCHEMA_VERSION


FORMAL_EXPERIMENT_GATE_SCHEMA_VERSION = "ctp-formal-experiment-gate-v1"
FORMAL_EXPERIMENT_GATE_NAME = "formal_experiment_gate.json"
FORMAL_EXPERIMENT_REPORT_NAME = "formal_experiment_report.md"

_CORE_ARTIFACTS = {
    "csv": "benchmark_results.csv",
    "json": "benchmark_results.json",
    "summary": "evaluation_summary.json",
    "paper_tables": "paper_tables.md",
    "manifest": "experiment_manifest.json",
    "preflight": "formal_preflight_report.json",
    "paper_analysis_json": PAPER_ANALYSIS_JSON_NAME,
    "paper_analysis_md": PAPER_ANALYSIS_MD_NAME,
}
_REQUIRED_METRIC_FIELDS = (
    "stsr",
    "evaluation_hcsr",
    "agent_selection_f1",
    "tool_selection_f1",
    "agent_set_exact_match",
    "tool_set_exact_match",
    "llm_call_count",
    "agent_call_count",
    "called_tool_count",
    "total_tokens",
)


def write_formal_experiment_gate(
    run_dir: str | Path,
    *,
    min_cases: Optional[int] = None,
    required_methods: Optional[Iterable[str]] = None,
    allow_mock_llm: bool = False,
) -> Dict[str, Any]:
    """Write final formal gate artifacts and attach them to the manifest."""
    root = Path(run_dir)
    paper_payload = write_experiment_paper_analysis(
        root,
        profile="formal",
        min_cases=min_cases,
        required_methods=required_methods,
        allow_mock_llm=allow_mock_llm,
    )
    gate = build_formal_experiment_gate(
        root,
        paper_analysis=paper_payload["analysis"],
        min_cases=min_cases,
        required_methods=required_methods,
        allow_mock_llm=allow_mock_llm,
    )
    gate_path = root / FORMAL_EXPERIMENT_GATE_NAME
    report_path = root / FORMAL_EXPERIMENT_REPORT_NAME
    gate["artifact_paths"]["formal_gate"] = gate_path.as_posix()
    gate["artifact_paths"]["formal_report"] = report_path.as_posix()
    gate_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(render_formal_experiment_report(gate), encoding="utf-8")
    _attach_gate_to_manifest(
        root,
        gate=gate,
        gate_path=gate_path,
        report_path=report_path,
    )
    return {
        "status": "completed",
        "gate": gate,
        "json": gate_path.as_posix(),
        "markdown": report_path.as_posix(),
        "gate_status": gate["status"],
        "paper_claims_allowed": gate["paper_claims_allowed"],
        "paper_analysis_json": paper_payload["json"],
        "paper_analysis_md": paper_payload["markdown"],
        "paper_readiness_status": paper_payload["readiness_status"],
    }


def build_formal_experiment_gate(
    run_dir: str | Path,
    *,
    paper_analysis: Optional[Dict[str, Any]] = None,
    min_cases: Optional[int] = None,
    required_methods: Optional[Iterable[str]] = None,
    allow_mock_llm: bool = False,
) -> Dict[str, Any]:
    """Build the machine-readable final gate for a saved formal run."""
    root = Path(run_dir)
    artifacts = _load_artifacts(root)
    results = artifacts["results"]
    summary = artifacts["summary"]
    manifest = artifacts["manifest"]
    preflight = artifacts["preflight"]
    analysis = paper_analysis or artifacts["paper_analysis"]
    csv_rows = _read_csv_rows(root / _CORE_ARTIFACTS["csv"])
    traces = _load_traces(root, results)
    llm_calls = [
        call
        for trace in traces
        for call in _as_dict_list(trace.get("llm_calls"))
    ]
    methods = _dict(summary.get("methods"))
    expected_result_count = _expected_result_count(preflight, summary)
    required = _normalize_methods(required_methods or DEFAULT_REQUIRED_METHODS)
    effective_min_cases = _effective_min_cases(min_cases)
    independent_case_count = _int(
        summary.get("independent_case_count"),
        summary.get("unique_case_count"),
        default=0,
    )
    artifact_index = _artifact_index(root)
    checks = {
        "run_dir_exists": root.exists(),
        "required_artifacts_saved": all(
            (root / filename).exists() for filename in _CORE_ARTIFACTS.values()
        ),
        "formal_preflight_saved": bool(preflight),
        "formal_preflight_schema_valid": (
            preflight.get("schema_version") == FORMAL_PREFLIGHT_SCHEMA_VERSION
        ),
        "formal_preflight_passed": preflight.get("status") == "passed",
        "paper_analysis_saved": bool(artifacts["paper_analysis"]),
        "paper_analysis_schema_valid": (
            analysis.get("schema_version") == PAPER_ANALYSIS_SCHEMA_VERSION
        ),
        "paper_analysis_ready": _nested(analysis, "readiness", "status") == "ready",
        "paper_claims_allowed_by_analysis": (
            _nested(analysis, "readiness", "paper_claims_allowed") is True
        ),
        "minimum_case_count_met": independent_case_count >= effective_min_cases,
        "required_methods_present": all(method in methods for method in required),
        "paired_m3_m2_present": _int(_nested(summary, "paired_statistics", "pair_count"), default=0) > 0,
        "result_count_matches_expected": (
            expected_result_count is not None and len(results) == expected_result_count
        ),
        "csv_row_count_matches_results": len(csv_rows) == len(results),
        "run_audit_attached": _all_results_have_run_audit(results),
        "metric_fields_present": _all_results_have_metrics(results),
        "trace_evidence_saved": bool(results)
        and all(_result_trace_evidence_exists(root, result) for result in results),
        "llm_call_recorded": bool(llm_calls),
        "no_mock_llm": bool(allow_mock_llm) or not _has_mock_llm(llm_calls),
        "no_llm_fallback": not _has_fallback_llm(llm_calls),
        "strict_runtime_recorded": _nested(manifest, "runtime_config", "strict_mode") is True,
        "cache_disabled_recorded": _nested(manifest, "runtime_config", "cache_disabled") is True,
        "deterministic_research_final_answer_recorded": _nested(
            manifest,
            "runtime_config",
            "deterministic_research_final_answer",
        )
        is True,
        "user_message_not_persisted": all(not trace.get("user_message") for trace in traces),
        "method_contract_recorded": _method_contract_recorded(manifest),
        "artifact_hashes_recorded": all(item.get("sha256") for item in artifact_index["files"]),
    }
    failed_checks = [key for key, value in checks.items() if not value]
    status = "passed" if not failed_checks else "failed"
    return {
        "schema_version": FORMAL_EXPERIMENT_GATE_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "paper_claims_allowed": status == "passed",
        "run_id": manifest.get("run_id") or _nested(preflight, "run", "run_id"),
        "run_dir": root.as_posix(),
        "expected_result_count": expected_result_count,
        "actual_result_count": len(results),
        "independent_case_count": independent_case_count,
        "min_cases": effective_min_cases,
        "required_methods": required,
        "observed_methods": list(methods.keys()),
        "checks": checks,
        "failed_checks": failed_checks,
        "artifact_index": artifact_index,
        "artifact_paths": {
            key: (root / filename).as_posix()
            for key, filename in _CORE_ARTIFACTS.items()
            if (root / filename).exists()
        },
        "paper_analysis": {
            "status": _nested(analysis, "readiness", "status"),
            "paper_claims_allowed": _nested(analysis, "readiness", "paper_claims_allowed"),
            "failed_checks": _nested(analysis, "readiness", "failed_checks") or [],
        },
        "trace_summary": _trace_summary(traces, llm_calls),
        "method_summary": _method_summary(analysis, summary),
        "m3_vs_m2": _dict(analysis.get("m3_vs_m2")),
        "interpretation": _interpretation(status),
    }


def render_formal_experiment_report(gate: Dict[str, Any]) -> str:
    """Render a concise human-readable formal gate report."""
    trace = _dict(gate.get("trace_summary"))
    methods = _dict(gate.get("method_summary"))
    m3_vs_m2 = _dict(gate.get("m3_vs_m2"))
    lines = [
        "# Formal experiment final gate",
        "",
        "## Conclusion",
        "",
        f"- status: `{gate.get('status')}`",
        f"- paper_claims_allowed: `{gate.get('paper_claims_allowed')}`",
        f"- run_id: `{gate.get('run_id')}`",
        f"- independent_case_count: `{gate.get('independent_case_count')}`",
        f"- expected_result_count: `{gate.get('expected_result_count')}`",
        f"- actual_result_count: `{gate.get('actual_result_count')}`",
        f"- failed_checks: `{gate.get('failed_checks') or []}`",
        f"- interpretation: {gate.get('interpretation')}",
        "",
        "## Gate checks",
        "",
        "| Check | Passed |",
        "|---|---:|",
    ]
    for key, value in _dict(gate.get("checks")).items():
        lines.append(f"| {key} | `{value}` |")

    lines.extend(
        [
            "",
            "## Method summary",
            "",
            "| Method | Cases | STSR | Agent F1 | Tool F1 | LLM calls | Tokens | Std. cost | Latency ms |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in methods.get("rows") or []:
        lines.append(
            f"| {row.get('label')} | {_fmt(row.get('case_count'))} "
            f"| {_fmt(row.get('stsr'))} | {_fmt(row.get('agent_selection_f1'))} "
            f"| {_fmt(row.get('tool_selection_f1'))} | {_fmt(row.get('llm_call_count'))} "
            f"| {_fmt(row.get('total_tokens'))} | {_fmt(row.get('standardized_estimated_cost'))} "
            f"| {_fmt(row.get('latency_ms'))} |"
        )

    lines.extend(
        [
            "",
            "## M3 vs M2 resource savings",
            "",
            "| Metric | M3 mean | M2 mean | Delta | Relative saving |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for metric, row in _dict(m3_vs_m2.get("metrics")).items():
        if row.get("relative_saving_rate") is None:
            continue
        lines.append(
            f"| {metric} | {_fmt(row.get('m3_mean'))} | {_fmt(row.get('m2_mean'))} "
            f"| {_fmt(row.get('delta_mean'))} | {_fmt(row.get('relative_saving_rate'))} |"
        )

    lines.extend(
        [
            "",
            "## Trace summary",
            "",
            f"- trace_count: `{trace.get('trace_count')}`",
            f"- llm_call_count: `{trace.get('llm_call_count')}`",
            f"- mock_llm_call_count: `{trace.get('mock_llm_call_count')}`",
            f"- fallback_llm_call_count: `{trace.get('fallback_llm_call_count')}`",
            f"- total_tokens: `{trace.get('total_tokens')}`",
            f"- standardized_estimated_cost: `{trace.get('standardized_estimated_cost')}`",
            "",
            "## Artifact hashes",
            "",
            "| Artifact | SHA-256 | Path |",
            "|---|---|---|",
        ]
    )
    for item in _dict(gate.get("artifact_index")).get("files") or []:
        lines.append(f"| {item.get('key')} | `{item.get('sha256')}` | `{item.get('path')}` |")
    return "\n".join(lines) + "\n"


def _load_artifacts(root: Path) -> Dict[str, Any]:
    return {
        "summary": _read_json_object(root / _CORE_ARTIFACTS["summary"]),
        "results": _read_json_list(root / _CORE_ARTIFACTS["json"]),
        "manifest": _read_json_object(root / _CORE_ARTIFACTS["manifest"]),
        "preflight": _read_json_object(root / _CORE_ARTIFACTS["preflight"]),
        "paper_analysis": _read_json_object(root / PAPER_ANALYSIS_JSON_NAME),
    }


def _artifact_index(root: Path) -> Dict[str, Any]:
    files = []
    for key, filename in _CORE_ARTIFACTS.items():
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
        "schema_version": "ctp-formal-artifact-index-v1",
        "hash_strategy": "sha256_file_bytes_v1",
        "files": files,
        "trace_dir": trace_dir.as_posix(),
        "trace_file_count": len(trace_files),
        "trace_combined_sha256": _combined_hash(trace_hashes),
    }


def _attach_gate_to_manifest(
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
            "formal_experiment_gate": gate_path.as_posix(),
            "formal_experiment_report": report_path.as_posix(),
        }
    )
    manifest["results"] = results
    manifest["formal_experiment_gate"] = {
        "schema_version": FORMAL_EXPERIMENT_GATE_SCHEMA_VERSION,
        "status": gate.get("status"),
        "paper_claims_allowed": gate.get("paper_claims_allowed"),
        "failed_checks": gate.get("failed_checks") or [],
        "json": gate_path.as_posix(),
        "markdown": report_path.as_posix(),
        "artifact_index": gate.get("artifact_index"),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _method_summary(analysis: Dict[str, Any], summary: Dict[str, Any]) -> Dict[str, Any]:
    rows = analysis.get("method_comparison")
    if isinstance(rows, list):
        return {"rows": [row for row in rows if isinstance(row, dict)]}
    methods = _dict(summary.get("methods"))
    fallback_rows = []
    for method, row in methods.items():
        data = _dict(row)
        fallback_rows.append(
            {
                "method": method,
                "label": method,
                "case_count": data.get("case_count"),
                "stsr": data.get("stsr_rate"),
                "agent_selection_f1": data.get("agent_selection_f1_mean"),
                "tool_selection_f1": data.get("tool_selection_f1_mean"),
                "llm_call_count": data.get("llm_call_count_mean"),
                "total_tokens": data.get("total_tokens_mean"),
                "standardized_estimated_cost": data.get("standardized_estimated_cost_mean"),
                "latency_ms": data.get("latency_ms_mean"),
            }
        )
    return {"rows": fallback_rows}


def _trace_summary(traces: List[Dict[str, Any]], llm_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "trace_count": len(traces),
        "llm_call_count": len(llm_calls),
        "mock_llm_call_count": sum(_bool(call.get("mock")) or _bool(call.get("mock_used")) for call in llm_calls),
        "fallback_llm_call_count": sum(
            _bool(call.get("fallback")) or _bool(call.get("fallback_used"))
            for call in llm_calls
        ),
        "retry_attempt_count": _sum_number(call.get("retry_attempt_count") for call in llm_calls),
        "retry_count": _sum_number(call.get("retry_count") for call in llm_calls),
        "prompt_tokens": _sum_usage(llm_calls, "prompt_tokens", "input_tokens"),
        "completion_tokens": _sum_usage(llm_calls, "completion_tokens", "output_tokens"),
        "total_tokens": _sum_usage(llm_calls, "total_tokens", "tokens_used"),
        "estimated_cost": _sum_number(call.get("estimated_cost") for call in llm_calls),
        "standardized_estimated_cost": _sum_number(
            call.get("standardized_estimated_cost") for call in llm_calls
        ),
        "actual_cost": _sum_number(call.get("actual_cost") for call in llm_calls),
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


def _all_results_have_metrics(results: List[Dict[str, Any]]) -> bool:
    if not results:
        return False
    for result in results:
        metrics = result.get("metrics")
        if not isinstance(metrics, dict):
            return False
        if any(key not in metrics for key in _REQUIRED_METRIC_FIELDS):
            return False
    return True


def _result_trace_evidence_exists(root: Path, result: Dict[str, Any]) -> bool:
    if isinstance(result.get("trace"), dict) and result["trace"]:
        return True
    path = _resolve_trace_path(root, result.get("trace_file"))
    return bool(path and path.exists())


def _load_traces(root: Path, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    traces = []
    for result in results:
        trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
        if trace:
            traces.append(trace)
            continue
        path = _resolve_trace_path(root, result.get("trace_file"))
        if path and path.exists():
            loaded = _read_jsonl_first(path)
            if loaded:
                traces.append(loaded)
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


def _method_contract_recorded(manifest: Dict[str, Any]) -> bool:
    contract = manifest.get("method_fairness_contract")
    return (
        isinstance(contract, dict)
        and bool(contract.get("schema_version"))
        and isinstance(contract.get("contract_sha256"), str)
        and len(contract.get("contract_sha256")) == 64
    )


def _expected_result_count(preflight: Dict[str, Any], summary: Dict[str, Any]) -> Optional[int]:
    for value in (
        _nested(preflight, "run", "expected_raw_run_count"),
        summary.get("raw_run_count"),
        summary.get("result_count"),
    ):
        number = _int(value)
        if number is not None:
            return number
    return None


def _effective_min_cases(min_cases: Optional[int]) -> int:
    if min_cases is None:
        return 100
    if isinstance(min_cases, bool) or int(min_cases) < 0:
        raise ValueError("min_cases must be a non-negative integer")
    return int(min_cases)


def _normalize_methods(methods: Iterable[str]) -> List[str]:
    normalized = [str(method).strip() for method in methods if str(method).strip()]
    if not normalized:
        raise ValueError("required_methods must not be empty")
    return normalized


def _has_mock_llm(llm_calls: List[Dict[str, Any]]) -> bool:
    return any(_bool(call.get("mock")) or _bool(call.get("mock_used")) for call in llm_calls)


def _has_fallback_llm(llm_calls: List[Dict[str, Any]]) -> bool:
    return any(_bool(call.get("fallback")) or _bool(call.get("fallback_used")) for call in llm_calls)


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


def _sum_usage(calls: List[Dict[str, Any]], *keys: str) -> Optional[float]:
    values = []
    for call in calls:
        usage = call.get("usage") if isinstance(call.get("usage"), dict) else call.get("tokens")
        usage = usage if isinstance(usage, dict) else {}
        values.append(_first_number(*(usage.get(key) for key in keys)))
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


def _interpretation(status: str) -> str:
    if status == "passed":
        return "Formal evidence package is complete enough for measured paper claims."
    return "Formal evidence package is not ready for paper claims; inspect failed_checks."


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return str(round(value, 4))
    return str(value)
