"""Day 7 M3 no-decision-normalizer ablation evidence.

The ablation is a controlled development-set run of ``adaptive_multi_agent``
with the deterministic research-agent decision normalizer disabled.  This
module is offline-only: it reads a completed run directory and writes a compact
evidence report that can be referenced by the Day 7 issue report.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from app.core.day7_dev_experiment_gate import refresh_day7_dev_artifact_index


DAY7_M3_ABLATION_SCHEMA_VERSION = "ctp-day7-m3-no-decision-normalizer-ablation-v1"
DAY7_M3_ABLATION_REPORT_JSON_NAME = "day7_m3_no_decision_normalizer_ablation.json"
DAY7_M3_ABLATION_REPORT_MD_NAME = "day7_m3_no_decision_normalizer_ablation.md"
DEFAULT_ABLATION_METHOD = "adaptive_multi_agent"
DEFAULT_EXPECTED_TURN_COUNT = 26
DEFAULT_EXPECTED_MAX_TOKENS = 4096


def write_m3_no_decision_normalizer_ablation_report(
    run_dir: str | Path,
    *,
    expected_turn_count: int = DEFAULT_EXPECTED_TURN_COUNT,
    expected_method: str = DEFAULT_ABLATION_METHOD,
    expected_max_tokens: int = DEFAULT_EXPECTED_MAX_TOKENS,
    attach_to_manifest: bool = True,
) -> Dict[str, Any]:
    """Write the M3 no-decision-normalizer ablation report."""
    root = Path(run_dir)
    report = build_m3_no_decision_normalizer_ablation_report(
        root,
        expected_turn_count=expected_turn_count,
        expected_method=expected_method,
        expected_max_tokens=expected_max_tokens,
    )
    json_path = root / DAY7_M3_ABLATION_REPORT_JSON_NAME
    md_path = root / DAY7_M3_ABLATION_REPORT_MD_NAME
    report["artifact_paths"]["ablation_report_json"] = json_path.as_posix()
    report["artifact_paths"]["ablation_report_md"] = md_path.as_posix()
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_m3_no_decision_normalizer_ablation_report(report), encoding="utf-8")
    refreshed_gate: Dict[str, Any] = {}
    if attach_to_manifest:
        _attach_to_manifest(root, report=report, json_path=json_path, md_path=md_path)
        refreshed_gate = refresh_day7_dev_artifact_index(root)
    return {
        "status": "completed",
        "ablation_status": report["status"],
        "json": json_path.as_posix(),
        "markdown": md_path.as_posix(),
        "failed_checks": report["failed_checks"],
        "checks": report["checks"],
        "summary": report["summary"],
        "artifact_index_refreshed": bool(refreshed_gate),
    }


def build_m3_no_decision_normalizer_ablation_report(
    run_dir: str | Path,
    *,
    expected_turn_count: int = DEFAULT_EXPECTED_TURN_COUNT,
    expected_method: str = DEFAULT_ABLATION_METHOD,
    expected_max_tokens: int = DEFAULT_EXPECTED_MAX_TOKENS,
) -> Dict[str, Any]:
    """Build a report for a saved no-normalizer ablation run."""
    root = Path(run_dir)
    results_path = root / "benchmark_results.json"
    manifest_path = root / "experiment_manifest.json"
    summary_path = root / "evaluation_summary.json"
    gate_path = root / "day7_dev_gate.json"
    results = _read_json_list(results_path)
    manifest = _read_json_object(manifest_path)
    summary = _read_json_object(summary_path)
    gate = _read_json_object(gate_path)
    traces = _load_traces(root, results)
    llm_calls = [
        call
        for trace in traces
        for call in _as_dict_list(trace.get("llm_calls"))
    ]
    method_counts = Counter(str(row.get("method") or "") for row in results)
    agent_audit = _agent_decision_audit(results)
    trace_audit = _trace_audit(llm_calls, expected_max_tokens=expected_max_tokens)
    manifest_normalizer_enabled = _nested(
        manifest,
        "method_controls",
        "research_agent_decision_normalizer_enabled",
    )
    methods = [str(method) for method in manifest.get("methods") or []]
    checks = {
        "run_dir_exists": root.exists(),
        "core_artifacts_saved": all(
            path.exists()
            for path in (results_path, manifest_path, summary_path, root / "benchmark_results.csv")
        ),
        "single_expected_method_recorded": methods == [expected_method],
        "result_count_matches_expected_turns": len(results) == expected_turn_count,
        "method_count_matches_expected_turns": method_counts.get(expected_method, 0)
        == expected_turn_count,
        "no_unexpected_methods": set(method_counts) <= {expected_method},
        "trace_count_matches_expected_turns": len(traces) == expected_turn_count,
        "manifest_decision_normalizer_disabled": manifest_normalizer_enabled is False,
        "agent_outputs_do_not_enable_normalizer": agent_audit[
            "normalizer_enabled_true_count"
        ]
        == 0,
        "deterministic_normalizer_not_used": agent_audit[
            "deterministic_normalizer_count"
        ]
        == 0,
        "normalizer_skip_audit_present": agent_audit["normalizer_skipped_count"] > 0
        or agent_audit["invalid_llm_decision_count"] == 0,
        "runtime_max_tokens_matches_protocol": trace_audit[
            "runtime_max_tokens_matches_protocol"
        ],
        "no_mock_llm": trace_audit["mock_llm_call_count"] == 0,
        "no_llm_fallback": trace_audit["fallback_llm_call_count"] == 0,
        "no_cache_hit": trace_audit["cache_hit_count"] == 0,
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": DAY7_M3_ABLATION_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if not failed_checks else "failed",
        "run_dir": root.as_posix(),
        "run_id": manifest.get("run_id"),
        "controlled_change": {
            "name": "M3-no-decision-normalizer",
            "method": expected_method,
            "decision_normalizer_enabled": False,
            "description": (
                "Disable deterministic research-agent decision normalization and "
                "preserve invalid/empty LLM Agent decisions as failures."
            ),
        },
        "expected": {
            "method": expected_method,
            "turn_count": expected_turn_count,
            "max_tokens": expected_max_tokens,
        },
        "actual": {
            "result_count": len(results),
            "method_counts": dict(method_counts),
            "trace_count": len(traces),
            "summary_raw_run_count": summary.get("raw_run_count"),
            "gate_status": gate.get("status"),
        },
        "summary": {
            "ablation_closed": not failed_checks,
            "agent_decision_output_count": agent_audit["agent_decision_output_count"],
            "deterministic_normalizer_count": agent_audit[
                "deterministic_normalizer_count"
            ],
            "normalizer_skipped_count": agent_audit["normalizer_skipped_count"],
            "invalid_llm_decision_count": agent_audit["invalid_llm_decision_count"],
            "llm_valid_decision_count": agent_audit["llm_valid_decision_count"],
            "normalizer_enabled_true_count": agent_audit[
                "normalizer_enabled_true_count"
            ],
            "llm_call_count": trace_audit["llm_call_count"],
            "runtime_max_tokens_values": trace_audit["max_tokens_values"],
        },
        "agent_decision_audit": agent_audit,
        "trace_audit": trace_audit,
        "checks": checks,
        "failed_checks": failed_checks,
        "artifact_paths": {
            "benchmark_results_json": results_path.as_posix(),
            "benchmark_results_csv": (root / "benchmark_results.csv").as_posix(),
            "evaluation_summary": summary_path.as_posix(),
            "manifest": manifest_path.as_posix(),
            "day7_dev_gate": gate_path.as_posix(),
        },
        "paper_use_policy": {
            "allowed_uses": [
                "ablation evidence for deterministic Agent decision normalization",
                "diagnosing how much M3 depends on programmatic decision repair",
            ],
            "forbidden_uses": [
                "replacing the four-method development run",
                "claiming final paper performance from the development split",
            ],
        },
    }


def render_m3_no_decision_normalizer_ablation_report(report: Mapping[str, Any]) -> str:
    """Render the ablation report as Markdown."""
    summary = _dict(report.get("summary"))
    actual = _dict(report.get("actual"))
    lines = [
        "# Day 7 M3-no-decision-normalizer 消融报告",
        "",
        "## 结论",
        "",
        f"- status: `{report.get('status')}`",
        f"- run_id: `{report.get('run_id')}`",
        f"- run_dir: `{report.get('run_dir')}`",
        f"- result_count: `{actual.get('result_count')}`",
        f"- trace_count: `{actual.get('trace_count')}`",
        f"- deterministic_normalizer_count: `{summary.get('deterministic_normalizer_count')}`",
        f"- normalizer_skipped_count: `{summary.get('normalizer_skipped_count')}`",
        f"- invalid_llm_decision_count: `{summary.get('invalid_llm_decision_count')}`",
        f"- runtime_max_tokens_values: `{summary.get('runtime_max_tokens_values')}`",
        f"- failed_checks: `{report.get('failed_checks') or []}`",
        "",
        "## 检查项",
        "",
        "| Check | Passed |",
        "|---|---:|",
    ]
    for key, value in _dict(report.get("checks")).items():
        lines.append(f"| {key} | `{value}` |")
    lines.extend(
        [
            "",
            "## 论文口径",
            "",
            (
                "该消融只改变一个因素：关闭 deterministic Agent decision normalizer。"
                "如果 Agent 的 LLM 决策为空、非严格 JSON 或不满足 schema，系统不再补全，"
                "而是把错误保留到实验结果中。"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _agent_decision_audit(results: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    agent_count = 0
    llm_valid = 0
    deterministic = 0
    skipped = 0
    invalid_llm = 0
    normalizer_enabled_true = 0
    by_agent: Dict[str, Counter[str]] = {}
    for result in results:
        for agent_name, output in _agent_outputs(result).items():
            if not isinstance(output, Mapping):
                continue
            name = str(output.get("agent_name") or agent_name)
            by_agent.setdefault(name, Counter())["total"] += 1
            agent_count += 1
            source = str(output.get("decision_source") or "")
            if output.get("decision_normalizer_enabled") is True:
                normalizer_enabled_true += 1
                by_agent[name]["normalizer_enabled_true"] += 1
            if (
                output.get("decision_fallback_used")
                or source == "deterministic_evidence_normalizer"
                or output.get("decision_normalizer_version")
            ):
                deterministic += 1
                by_agent[name]["deterministic_normalizer"] += 1
            if output.get("decision_normalizer_skipped"):
                skipped += 1
                by_agent[name]["normalizer_skipped"] += 1
            llm_status_ok = (
                source == "llm"
                and output.get("llm_decision_parse_status") == "passed"
                and output.get("llm_decision_validation_status") == "passed"
                and output.get("decision_validation_status") == "passed"
            )
            if llm_status_ok:
                llm_valid += 1
                by_agent[name]["llm_valid"] += 1
            elif source == "llm":
                invalid_llm += 1
                by_agent[name]["invalid_llm"] += 1
    return {
        "agent_decision_output_count": agent_count,
        "llm_valid_decision_count": llm_valid,
        "deterministic_normalizer_count": deterministic,
        "normalizer_skipped_count": skipped,
        "invalid_llm_decision_count": invalid_llm,
        "normalizer_enabled_true_count": normalizer_enabled_true,
        "by_agent": {key: dict(counter) for key, counter in sorted(by_agent.items())},
    }


def _trace_audit(
    llm_calls: Iterable[Mapping[str, Any]],
    *,
    expected_max_tokens: int,
) -> Dict[str, Any]:
    calls = [call for call in llm_calls if isinstance(call, Mapping)]
    max_tokens_values = sorted(
        {
            _int(
                call.get("max_tokens")
                or _nested(call, "request_options", "max_tokens"),
                default=0,
            )
            for call in calls
        }
        - {0}
    )
    return {
        "llm_call_count": len(calls),
        "max_tokens_values": max_tokens_values,
        "runtime_max_tokens_matches_protocol": bool(calls)
        and max_tokens_values == [int(expected_max_tokens)],
        "mock_llm_call_count": sum(
            1 for call in calls if call.get("mock") or call.get("mock_used")
        ),
        "fallback_llm_call_count": sum(
            1 for call in calls if call.get("fallback") or call.get("fallback_used")
        ),
        "cache_hit_count": sum(1 for call in calls if call.get("cache_hit")),
    }


def _load_traces(root: Path, results: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    traces: List[Dict[str, Any]] = []
    seen: set[Path] = set()
    for result in results:
        trace_path = _result_trace_path(root, result)
        if trace_path is None or trace_path in seen or not trace_path.exists():
            continue
        seen.add(trace_path)
        line = trace_path.read_text(encoding="utf-8").splitlines()[0]
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            traces.append(payload)
    return traces


def _result_trace_path(root: Path, result: Mapping[str, Any]) -> Optional[Path]:
    raw = result.get("trace_file") or result.get("trace_path")
    if not raw:
        return None
    path = Path(str(raw))
    return path if path.is_absolute() else root / path


def _agent_outputs(result: Mapping[str, Any]) -> Dict[str, Any]:
    candidates = (
        _nested(result, "output", "metadata", "agent_outputs"),
        _nested(result, "output", "agent_outputs"),
        _nested(result, "raw_output", "metadata", "agent_outputs"),
        _nested(result, "raw_output", "agent_outputs"),
        _nested(result, "output", "raw_output", "metadata", "agent_outputs"),
        _nested(result, "output", "raw_output", "agent_outputs"),
    )
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return {}


def _attach_to_manifest(
    run_dir: Path,
    *,
    report: Mapping[str, Any],
    json_path: Path,
    md_path: Path,
) -> None:
    manifest_path = run_dir / "experiment_manifest.json"
    if not manifest_path.exists():
        return
    manifest = _read_json_object(manifest_path)
    manifest["m3_no_decision_normalizer_ablation"] = {
        "schema_version": DAY7_M3_ABLATION_SCHEMA_VERSION,
        "status": report.get("status"),
        "ablation_closed": _nested(report, "summary", "ablation_closed"),
        "deterministic_normalizer_count": _nested(
            report,
            "summary",
            "deterministic_normalizer_count",
        ),
        "normalizer_skipped_count": _nested(
            report,
            "summary",
            "normalizer_skipped_count",
        ),
        "json": json_path.as_posix(),
        "markdown": md_path.as_posix(),
    }
    manifest.setdefault("results", {})["m3_ablation_json"] = json_path.as_posix()
    manifest.setdefault("results", {})["m3_ablation_report"] = md_path.as_posix()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json_object(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_json_list(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return [row for row in payload["results"] if isinstance(row, dict)]
    return []


def _as_dict_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
