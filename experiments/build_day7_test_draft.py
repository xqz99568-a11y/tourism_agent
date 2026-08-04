"""Build the Day 7 100-case formal test-draft dataset and reports.

This command is offline-only: it writes the draft benchmark JSON, quota gate,
offline feasibility report, and a human-readable Markdown report.  It does not
call any LLM or external API.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.benchmark_dataset_validator import build_benchmark_dataset_quality_report
from app.core.day7_test_draft import (
    DEFAULT_EXPECTED_CASE_COUNT,
    build_ctp120_test_draft_document,
    build_day7_test_draft_gate,
    render_day7_test_draft_report,
    write_json,
    write_text,
)
from app.core.formal_experiment_preflight import load_benchmark_document


DEFAULT_DATASET_PATH = ROOT / "experiments" / "ctp120_test_draft.json"
DEFAULT_QUOTA_REPORT_PATH = ROOT / "experiments" / "ctp120_test_draft_quota_report.json"
DEFAULT_FEASIBILITY_REPORT_PATH = (
    ROOT / "experiments" / "ctp120_test_draft_feasibility_report.json"
)
DEFAULT_MARKDOWN_REPORT_PATH = ROOT / "docs" / "Day7_test_draft_dataset.md"
DEFAULT_BENCHMARK_MANIFEST_PATH = ROOT / "experiments" / "benchmark.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-path", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--quota-report", type=Path, default=DEFAULT_QUOTA_REPORT_PATH)
    parser.add_argument(
        "--feasibility-report",
        type=Path,
        default=DEFAULT_FEASIBILITY_REPORT_PATH,
    )
    parser.add_argument("--markdown-report", type=Path, default=DEFAULT_MARKDOWN_REPORT_PATH)
    parser.add_argument(
        "--benchmark-manifest",
        type=Path,
        default=DEFAULT_BENCHMARK_MANIFEST_PATH,
        help="benchmark.json entry point to update after the draft gate passes.",
    )
    parser.add_argument(
        "--no-update-benchmark",
        action="store_true",
        help="Write the draft and reports but leave experiments/benchmark.json unchanged.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero unless the quota/quality gate passes.",
    )
    args = parser.parse_args()

    payload = build_day7_test_draft_artifacts(
        dataset_path=args.dataset_path,
        quota_report_path=args.quota_report,
        feasibility_report_path=args.feasibility_report,
        markdown_report_path=args.markdown_report,
        benchmark_manifest_path=None
        if args.no_update_benchmark
        else args.benchmark_manifest,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.strict and payload.get("gate_status") != "passed":
        return 1
    return 0


def build_day7_test_draft_artifacts(
    *,
    dataset_path: str | Path = DEFAULT_DATASET_PATH,
    quota_report_path: str | Path = DEFAULT_QUOTA_REPORT_PATH,
    feasibility_report_path: str | Path = DEFAULT_FEASIBILITY_REPORT_PATH,
    markdown_report_path: str | Path = DEFAULT_MARKDOWN_REPORT_PATH,
    benchmark_manifest_path: str | Path | None = DEFAULT_BENCHMARK_MANIFEST_PATH,
) -> Dict[str, Any]:
    """Write the 100-case test draft and its offline evidence artifacts."""
    dataset_file = Path(dataset_path)
    document = build_ctp120_test_draft_document()
    write_json(dataset_file, document)
    comparison_splits = _load_comparison_splits(dataset_file, document)
    quality_report = build_benchmark_dataset_quality_report(
        document=document,
        cases=document["cases"],
        expected_case_count=DEFAULT_EXPECTED_CASE_COUNT,
        strict_formal=True,
        comparison_splits=comparison_splits,
    )
    gate = build_day7_test_draft_gate(
        document=document,
        cases=document["cases"],
        comparison_splits=comparison_splits,
        quality_report=quality_report,
    )
    quota_path = write_json(quota_report_path, gate)
    feasibility_path = write_json(feasibility_report_path, gate["offline_feasibility"])
    markdown_path = write_text(markdown_report_path, render_day7_test_draft_report(gate))

    benchmark_path: Path | None = None
    if benchmark_manifest_path is not None and gate["status"] == "passed":
        benchmark_path = _write_benchmark_manifest(
            Path(benchmark_manifest_path),
            dataset_path=dataset_file,
            dataset_document=document,
        )

    return {
        "schema_version": "ctp-day7-test-draft-build-v1",
        "status": "completed",
        "gate_status": gate["status"],
        "dataset": dataset_file.as_posix(),
        "quota_report": quota_path.as_posix(),
        "feasibility_report": feasibility_path.as_posix(),
        "markdown_report": markdown_path.as_posix(),
        "benchmark_manifest": benchmark_path.as_posix() if benchmark_path else None,
        "case_count": gate["actual"]["case_count"],
        "turn_count": gate["actual"]["total_turn_count"],
        "scenario_case_count": gate["actual"]["scenario_case_count"],
        "failed_checks": gate["failed_checks"],
        "quality_errors": gate["quality_gate"]["errors"],
        "quality_warnings": gate["quality_gate"]["warnings"],
    }


def _write_benchmark_manifest(
    benchmark_path: Path,
    *,
    dataset_path: Path,
    dataset_document: Mapping[str, Any],
) -> Path:
    manifest = {
        "schema_version": "ctp-benchmark-manifest-v1",
        "dataset_id": "tourism_benchmark_v1",
        "dataset_version": dataset_document.get("dataset_version"),
        "split": "test_draft",
        "language": "zh-CN",
        "description": (
            "正式测试集草稿入口。当前指向 ctp120_test_draft.json；该入口用于 "
            "100案例/130轮正式实验 preflight，开发集仍保留在 ctp120_dev.json。"
        ),
        "case_files": [_relative_path(benchmark_path.parent, dataset_path)],
        "comparison_files": [
            _relative_path(benchmark_path.parent, benchmark_path.parent / "ctp120_dev.json"),
            _relative_path(benchmark_path.parent, benchmark_path.parent / "benchmark_test.json"),
        ],
        "expected": {
            "case_count": 100,
            "turn_count": 130,
            "scenario_case_count": 30,
            "statistical_unit": "case_id",
        },
    }
    return write_json(benchmark_path, manifest)


def _load_comparison_splits(
    benchmark_path: Path,
    document: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    comparison_splits: dict[str, list[dict[str, Any]]] = {}
    for raw_path in _as_list(document.get("comparison_files")):
        comparison_path = benchmark_path.parent / str(raw_path)
        comparison_document, comparison_cases = load_benchmark_document(comparison_path)
        split_name = _comparison_split_name(comparison_path, comparison_document)
        comparison_splits[split_name] = comparison_cases
    return comparison_splits


def _comparison_split_name(path: Path, document: Any) -> str:
    if isinstance(document, Mapping):
        for key in ("split", "dataset_id"):
            value = str(document.get(key) or "").strip()
            if value:
                return value
    return path.stem


def _relative_path(base: Path, target: Path) -> str:
    try:
        return target.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return target.as_posix()


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


if __name__ == "__main__":
    raise SystemExit(main())
