"""Build 13 human-friendly review files from the current Day7 review CSV."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.plain_language_review import write_plain_review_batches


DEFAULT_REVIEW_CSV = (
    ROOT
    / "experiments"
    / "results"
    / "day7_acceptance"
    / "day7_acceptance_label_fix_20260804"
    / "day7_annotation_review_round1.csv"
)
DEFAULT_OUTPUT_DIR = DEFAULT_REVIEW_CSV.parent / "plain_language_review_batches"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-csv", type=Path, default=DEFAULT_REVIEW_CSV)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--expected-rows", type=int, default=130)
    args = parser.parse_args()

    result = write_plain_review_batches(
        review_csv_path=args.review_csv,
        output_dir=args.output_dir,
        batch_size=args.batch_size,
        expected_rows=args.expected_rows,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
