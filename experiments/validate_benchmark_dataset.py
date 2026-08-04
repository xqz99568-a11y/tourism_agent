"""Validate a benchmark JSON file before spending LLM/API budget."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.benchmark_dataset_validator import build_benchmark_dataset_quality_report
from app.core.formal_experiment_preflight import load_benchmark_document


DEFAULT_BENCHMARK_PATH = ROOT / "experiments" / "benchmark_test.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK_PATH)
    parser.add_argument("--expected-cases", type=int, default=None)
    parser.add_argument(
        "--compare-with",
        action="append",
        type=Path,
        default=[],
        help=(
            "Optional benchmark/case file to compare against for cross-split "
            "duplicate and near-duplicate checks. Can be used multiple times."
        ),
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Use warning-only development checks for incomplete gold labels.",
    )
    args = parser.parse_args()

    document, cases = load_benchmark_document(args.benchmark)
    comparison_splits = _load_comparison_splits(
        benchmark_path=args.benchmark,
        document=document,
        explicit_paths=args.compare_with,
    )
    report = build_benchmark_dataset_quality_report(
        document=document,
        cases=cases,
        expected_case_count=args.expected_cases,
        strict_formal=not args.dev,
        comparison_splits=comparison_splits,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 2


def _load_comparison_splits(
    *,
    benchmark_path: Path,
    document: object,
    explicit_paths: list[Path],
) -> dict[str, list[dict[str, object]]]:
    paths: list[Path] = []
    if isinstance(document, dict) and isinstance(document.get("comparison_files"), list):
        paths.extend(Path(str(path)) for path in document["comparison_files"])
    paths.extend(explicit_paths)

    comparison_splits: dict[str, list[dict[str, object]]] = {}
    for path in paths:
        resolved = path if path.is_absolute() else benchmark_path.parent / path
        comparison_document, comparison_cases = load_benchmark_document(resolved)
        split_name = _comparison_split_name(resolved, comparison_document)
        comparison_splits[split_name] = comparison_cases
    return comparison_splits


def _comparison_split_name(path: Path, document: object) -> str:
    if isinstance(document, dict):
        for key in ("split", "dataset_id"):
            value = str(document.get(key) or "").strip()
            if value:
                return value
    return path.stem


if __name__ == "__main__":
    raise SystemExit(main())
