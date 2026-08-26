"""Offline Holm-Bonferroni analysis for frozen CTP100 secondary metrics.

This module intentionally reads a completed run directory and writes a
separate analysis directory.  It never calls an LLM and must not mutate the
source formal run artifacts.
"""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[2]
HOLM_SECONDARY_SCHEMA_VERSION = "ctp-holm-secondary-statistics-v1"
HOLM_SECONDARY_METRICS: tuple[tuple[str, str], ...] = (
    ("evaluation_hcsr", "HCSR"),
    ("agent_selection_f1", "Agent Selection F1"),
    ("tool_selection_f1", "Tool Selection F1"),
    ("llm_call_count", "LLM call count"),
    ("agent_call_count", "Agent call count"),
    ("tool_call_count", "Tool call count"),
    ("total_tokens", "Total tokens"),
    ("latency_ms", "Latency"),
    ("standardized_estimated_cost", "Standardized estimated cost"),
)
HOLM_RESULT_JSON_NAME = "holm_secondary_results.json"
HOLM_RESULT_CSV_NAME = "holm_secondary_results.csv"
HOLM_RESULT_MD_NAME = "holm_secondary_results.md"
HOLM_ANALYSIS_MANIFEST_NAME = "analysis_manifest.json"


def write_holm_secondary_statistics(
    source_run_dir: str | Path,
    *,
    output_dir: Optional[str | Path] = None,
    alpha: float = 0.05,
    metric_family: Sequence[tuple[str, str]] = HOLM_SECONDARY_METRICS,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Write Holm-corrected secondary statistics for a frozen formal run."""
    source = Path(source_run_dir)
    destination = (
        Path(output_dir)
        if output_dir is not None
        else source.parent / f"{source.name}_secondary_statistics"
    )
    _validate_analysis_paths(source, destination, overwrite=overwrite)
    destination.mkdir(parents=True, exist_ok=True)

    summary_path = source / "evaluation_summary.json"
    summary = _read_json_object(summary_path)
    analysis = build_holm_secondary_statistics(
        summary,
        source_run_dir=source,
        evaluation_summary_path=summary_path,
        alpha=alpha,
        metric_family=metric_family,
    )
    json_path = destination / HOLM_RESULT_JSON_NAME
    csv_path = destination / HOLM_RESULT_CSV_NAME
    md_path = destination / HOLM_RESULT_MD_NAME
    manifest_path = destination / HOLM_ANALYSIS_MANIFEST_NAME

    _write_json(json_path, analysis)
    _write_holm_csv(csv_path, analysis["metrics"])
    md_path.write_text(render_holm_secondary_statistics(analysis), encoding="utf-8")

    manifest = build_holm_analysis_manifest(
        source_run_dir=source,
        output_dir=destination,
        evaluation_summary_path=summary_path,
        analysis_json_path=json_path,
        analysis_csv_path=csv_path,
        analysis_md_path=md_path,
        alpha=alpha,
        metric_family=metric_family,
    )
    _write_json(manifest_path, manifest)
    return {
        "status": "completed",
        "analysis_status": analysis["status"],
        "output_dir": destination.as_posix(),
        "json": json_path.as_posix(),
        "csv": csv_path.as_posix(),
        "markdown": md_path.as_posix(),
        "manifest": manifest_path.as_posix(),
        "failed_checks": analysis.get("failed_checks") or [],
    }


def build_holm_secondary_statistics(
    evaluation_summary: Mapping[str, Any],
    *,
    source_run_dir: str | Path,
    evaluation_summary_path: str | Path,
    alpha: float = 0.05,
    metric_family: Sequence[tuple[str, str]] = HOLM_SECONDARY_METRICS,
) -> Dict[str, Any]:
    """Build Holm-corrected results from an evaluation summary payload."""
    _validate_metric_family(metric_family)
    if not (0 < float(alpha) < 1):
        raise ValueError("alpha must be between 0 and 1")

    paired = evaluation_summary.get("paired_statistics")
    paired = paired if isinstance(paired, Mapping) else {}
    metric_stats = paired.get("metrics")
    metric_stats = metric_stats if isinstance(metric_stats, Mapping) else {}
    rows = []
    errors: List[str] = []
    for metric, label in metric_family:
        stat = metric_stats.get(metric)
        if not isinstance(stat, Mapping):
            errors.append(f"missing secondary metric: {metric}")
            continue
        p_value = _extract_secondary_p_value(stat)
        if p_value is None:
            errors.append(f"missing secondary p-value: {metric}")
            continue
        rows.append(
            {
                "metric": metric,
                "label": label,
                "test_name": _secondary_test_name(stat),
                "raw_p_value": p_value,
                "m3_mean": _nested_number(stat, "m3", "mean"),
                "m2_mean": _nested_number(stat, "m2", "mean"),
                "delta_mean": _nested_number(stat, "delta", "mean"),
                "delta_ci_95": _nested_value(stat, "delta", "bootstrap_ci_95"),
                "pair_count": _optional_int(stat.get("pair_count")),
                "alpha": float(alpha),
                "family_size": len(metric_family),
            }
        )
    stsr_in_family = any(metric == "stsr" for metric, _ in metric_family)
    if stsr_in_family:
        errors.append("primary metric stsr must not be included in Holm secondary family")

    corrected = apply_holm_bonferroni(rows, alpha=alpha)
    failed_checks = []
    if errors:
        failed_checks.append("secondary_metrics_complete")
    if stsr_in_family:
        failed_checks.append("stsr_excluded_from_secondary_family")
    return {
        "schema_version": HOLM_SECONDARY_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if not failed_checks else "failed",
        "failed_checks": failed_checks,
        "errors": errors,
        "source": {
            "run_dir": Path(source_run_dir).as_posix(),
            "evaluation_summary": Path(evaluation_summary_path).as_posix(),
            "evaluation_summary_sha256": _file_sha256(Path(evaluation_summary_path))
            if Path(evaluation_summary_path).exists()
            else None,
        },
        "policy": {
            "primary_metric": "stsr",
            "primary_metric_correction_policy": "not_in_holm_family_pre_specified_primary_endpoint",
            "secondary_correction": "Holm-Bonferroni",
            "alpha": float(alpha),
            "family_size": len(metric_family),
            "metric_family": [
                {"metric": metric, "label": label} for metric, label in metric_family
            ],
            "exploratory_metrics_not_in_family": ["bpcr", "itcsr"],
        },
        "primary_stsr_reference": _primary_stsr_reference(metric_stats),
        "metrics": corrected,
    }


def apply_holm_bonferroni(
    rows: Sequence[Mapping[str, Any]],
    *,
    alpha: float = 0.05,
) -> List[Dict[str, Any]]:
    """Return rows with Holm adjusted p-values.

    The returned order follows the input order, so table output remains stable
    even though the Holm calculation itself ranks p-values internally.
    """
    normalized: List[Dict[str, Any]] = []
    for index, row in enumerate(rows):
        p_value = _coerce_p_value(row.get("raw_p_value"), label=str(row.get("metric") or index))
        normalized.append({**dict(row), "_input_index": index, "raw_p_value": p_value})

    family_size = len(normalized)
    ranked = sorted(
        normalized,
        key=lambda item: (float(item["raw_p_value"]), str(item.get("metric") or "")),
    )
    cumulative = 0.0
    for rank_index, row in enumerate(ranked):
        multiplier = family_size - rank_index
        adjusted = min(1.0, float(row["raw_p_value"]) * multiplier)
        cumulative = max(cumulative, adjusted)
        row["holm_rank"] = rank_index + 1
        row["holm_multiplier"] = multiplier
        row["holm_adjusted_p_value"] = round(cumulative, 6)
        row["significant_after_correction"] = row["holm_adjusted_p_value"] <= alpha

    by_index = {row["_input_index"]: row for row in ranked}
    ordered: List[Dict[str, Any]] = []
    for index in range(family_size):
        row = dict(by_index[index])
        row.pop("_input_index", None)
        ordered.append(row)
    return ordered


def build_holm_analysis_manifest(
    *,
    source_run_dir: str | Path,
    output_dir: str | Path,
    evaluation_summary_path: str | Path,
    analysis_json_path: str | Path,
    analysis_csv_path: str | Path,
    analysis_md_path: str | Path,
    alpha: float,
    metric_family: Sequence[tuple[str, str]],
) -> Dict[str, Any]:
    """Build the hash manifest for the offline Holm analysis directory."""
    files = {
        "holm_secondary_results_json": Path(analysis_json_path),
        "holm_secondary_results_csv": Path(analysis_csv_path),
        "holm_secondary_results_md": Path(analysis_md_path),
    }
    return {
        "schema_version": "ctp-holm-analysis-manifest-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if all(path.exists() for path in files.values()) else "failed",
        "analysis_type": "offline_holm_bonferroni_secondary_statistics",
        "source_run_dir": Path(source_run_dir).as_posix(),
        "output_dir": Path(output_dir).as_posix(),
        "source": {
            "evaluation_summary": Path(evaluation_summary_path).as_posix(),
            "evaluation_summary_sha256": _file_sha256(Path(evaluation_summary_path)),
        },
        "git": {
            "commit": _git_commit(),
            "working_tree_clean": _git_working_tree_clean(),
        },
        "analysis_code": _analysis_code_hashes(),
        "policy": {
            "alpha": float(alpha),
            "secondary_metric_family": [
                {"metric": metric, "label": label} for metric, label in metric_family
            ],
            "primary_metric_excluded_from_holm": "stsr",
        },
        "files": [
            {
                "key": key,
                "path": path.as_posix(),
                "exists": path.exists(),
                "sha256": _file_sha256(path) if path.exists() else None,
            }
            for key, path in files.items()
        ],
    }


def render_holm_secondary_statistics(analysis: Mapping[str, Any]) -> str:
    """Render a compact Markdown report."""
    policy = analysis.get("policy") if isinstance(analysis.get("policy"), Mapping) else {}
    source = analysis.get("source") if isinstance(analysis.get("source"), Mapping) else {}
    lines = [
        "# Holm-Bonferroni Secondary Statistics",
        "",
        f"- status: `{analysis.get('status')}`",
        f"- source_run_dir: `{source.get('run_dir')}`",
        f"- evaluation_summary_sha256: `{source.get('evaluation_summary_sha256')}`",
        f"- alpha: `{policy.get('alpha')}`",
        f"- family_size: `{policy.get('family_size')}`",
        f"- primary_metric_policy: `{policy.get('primary_metric_correction_policy')}`",
        "",
        "| metric | test | pair_count | M3 mean | M2 mean | delta mean | raw p | Holm adjusted p | significant |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in analysis.get("metrics") or []:
        if not isinstance(row, Mapping):
            continue
        lines.append(
            "| {metric} | {test} | {pair_count} | {m3} | {m2} | {delta} | {raw_p} | {adj_p} | `{sig}` |".format(
                metric=row.get("label") or row.get("metric"),
                test=row.get("test_name"),
                pair_count=_fmt(row.get("pair_count")),
                m3=_fmt(row.get("m3_mean")),
                m2=_fmt(row.get("m2_mean")),
                delta=_fmt(row.get("delta_mean")),
                raw_p=_fmt(row.get("raw_p_value")),
                adj_p=_fmt(row.get("holm_adjusted_p_value")),
                sig=row.get("significant_after_correction"),
            )
        )
    if analysis.get("errors"):
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {error}" for error in analysis.get("errors") or [])
    return "\n".join(lines) + "\n"


def _validate_metric_family(metric_family: Sequence[tuple[str, str]]) -> None:
    if not metric_family:
        raise ValueError("metric_family must not be empty")
    seen = set()
    for metric, label in metric_family:
        if not str(metric).strip() or not str(label).strip():
            raise ValueError("metric_family entries require non-empty metric and label")
        if metric in seen:
            raise ValueError(f"duplicate secondary metric: {metric}")
        seen.add(metric)


def _extract_secondary_p_value(stat: Mapping[str, Any]) -> Optional[float]:
    wilcoxon = stat.get("wilcoxon_signed_rank")
    if isinstance(wilcoxon, Mapping) and wilcoxon.get("p_value") is not None:
        return _coerce_p_value(wilcoxon.get("p_value"), label="wilcoxon_signed_rank")
    mcnemar = stat.get("mcnemar")
    if isinstance(mcnemar, Mapping) and mcnemar.get("p_value") is not None:
        return _coerce_p_value(mcnemar.get("p_value"), label="mcnemar")
    return None


def _secondary_test_name(stat: Mapping[str, Any]) -> str:
    wilcoxon = stat.get("wilcoxon_signed_rank")
    if isinstance(wilcoxon, Mapping):
        return str(wilcoxon.get("method") or "Wilcoxon")
    mcnemar = stat.get("mcnemar")
    if isinstance(mcnemar, Mapping):
        return str(mcnemar.get("method") or "McNemar")
    return "unknown"


def _primary_stsr_reference(metric_stats: Mapping[str, Any]) -> Dict[str, Any]:
    stsr = metric_stats.get("stsr")
    if not isinstance(stsr, Mapping):
        return {"available": False}
    mcnemar = stsr.get("mcnemar") if isinstance(stsr.get("mcnemar"), Mapping) else {}
    return {
        "available": True,
        "pair_count": stsr.get("pair_count"),
        "m3_rate": _nested_number(stsr, "m3", "mean"),
        "m2_rate": _nested_number(stsr, "m2", "mean"),
        "delta_mean": _nested_number(stsr, "delta", "mean"),
        "delta_ci_95": _nested_value(stsr, "delta", "bootstrap_ci_95"),
        "raw_mcnemar_p_value": mcnemar.get("p_value"),
        "correction_policy": "pre_specified_primary_endpoint_not_holm_corrected",
    }


def _validate_analysis_paths(source: Path, destination: Path, *, overwrite: bool) -> None:
    if not source.exists():
        raise FileNotFoundError(f"source run directory does not exist: {source}")
    summary_path = source / "evaluation_summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"evaluation_summary.json does not exist: {summary_path}")
    try:
        source_resolved = source.resolve()
        destination_resolved = destination.resolve()
    except OSError:
        source_resolved = source
        destination_resolved = destination
    if destination_resolved == source_resolved or source_resolved in destination_resolved.parents:
        raise ValueError("Holm output_dir must not be inside the frozen source run directory")
    if destination.exists() and any(destination.iterdir()) and not overwrite:
        raise RuntimeError(f"Holm output directory is not empty: {destination}")


def _write_holm_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    fieldnames = [
        "metric",
        "label",
        "test_name",
        "pair_count",
        "m3_mean",
        "m2_mean",
        "delta_mean",
        "raw_p_value",
        "holm_rank",
        "holm_multiplier",
        "holm_adjusted_p_value",
        "significant_after_correction",
        "alpha",
        "family_size",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json_object(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _coerce_p_value(value: Any, *, label: str) -> float:
    try:
        p_value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid p-value for {label}: {value!r}") from exc
    if not 0 <= p_value <= 1:
        raise ValueError(f"p-value out of range for {label}: {p_value}")
    return p_value


def _optional_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _nested_value(value: Mapping[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _nested_number(value: Mapping[str, Any], *keys: str) -> Optional[float]:
    target = _nested_value(value, *keys)
    if isinstance(target, bool):
        return None
    if isinstance(target, (int, float)):
        return float(target)
    return None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit() -> Optional[str]:
    return _git_output(["git", "rev-parse", "HEAD"])


def _git_working_tree_clean() -> Optional[bool]:
    status = _git_output(["git", "status", "--short"])
    return None if status is None else status == ""


def _git_output(args: List[str]) -> Optional[str]:
    try:
        result = subprocess.run(
            args,
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _analysis_code_hashes() -> Dict[str, Any]:
    module_path = Path(__file__)
    script_path = ROOT / "experiments" / "analyze_v6_holm.py"
    files = {
        "holm_secondary_statistics_module": module_path,
        "analyze_v6_holm_script": script_path,
    }
    return {
        key: {
            "path": path.as_posix(),
            "exists": path.exists(),
            "sha256": _file_sha256(path) if path.exists() else None,
        }
        for key, path in files.items()
    }


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


__all__ = [
    "HOLM_SECONDARY_METRICS",
    "HOLM_SECONDARY_SCHEMA_VERSION",
    "apply_holm_bonferroni",
    "build_holm_secondary_statistics",
    "render_holm_secondary_statistics",
    "write_holm_secondary_statistics",
]
