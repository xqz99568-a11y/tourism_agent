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
        "--dev",
        action="store_true",
        help="Use warning-only development checks for incomplete gold labels.",
    )
    args = parser.parse_args()

    document, cases = load_benchmark_document(args.benchmark)
    report = build_benchmark_dataset_quality_report(
        document=document,
        cases=cases,
        expected_case_count=args.expected_cases,
        strict_formal=not args.dev,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
