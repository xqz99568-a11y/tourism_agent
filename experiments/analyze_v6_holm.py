"""Generate offline Holm-Bonferroni statistics for frozen CTP100 v6 results."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.holm_secondary_statistics import write_holm_secondary_statistics


DEFAULT_SOURCE_RUN_DIR = Path(r"D:\Tourism_Agent_Formal_Runs\formal_ctp100_20260825_v6")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run-dir", type=Path, default=DEFAULT_SOURCE_RUN_DIR)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing files in the separate Holm analysis output directory.",
    )
    args = parser.parse_args()
    payload = write_holm_secondary_statistics(
        args.source_run_dir,
        output_dir=args.output_dir,
        alpha=args.alpha,
        overwrite=args.overwrite,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["analysis_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
