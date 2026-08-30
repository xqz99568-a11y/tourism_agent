"""Generate offline CTP100 M2/M3 repeat-stability analysis artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.ctp100_stability_analysis import (
    write_ctp100_m2_m3_stability_analysis,
)


DEFAULT_V6_RUN_DIR = Path(r"D:\Tourism_Agent_Formal_Runs\formal_ctp100_20260825_v6")
DEFAULT_STABILITY_RUN_DIR = Path(
    r"D:\Tourism_Agent_Formal_Runs\ctp100_m2_m3_stability\ctp100_m2m3_stability_20260830_v1"
)
DEFAULT_OUTPUT_DIR = Path(
    r"D:\Tourism_Agent_Formal_Runs\ctp100_m2_m3_stability\ctp100_m2m3_stability_20260830_v1_offline_analysis"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v6-run-dir", type=Path, default=DEFAULT_V6_RUN_DIR)
    parser.add_argument("--stability-run-dir", type=Path, default=DEFAULT_STABILITY_RUN_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--expected-quality-units", type=int, default=100)
    parser.add_argument("--expected-raw-rows-per-method-repeat", type=int, default=130)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing existing offline-analysis artifacts in --output-dir.",
    )
    args = parser.parse_args()

    payload = write_ctp100_m2_m3_stability_analysis(
        v6_run_dir=args.v6_run_dir,
        stability_run_dir=args.stability_run_dir,
        output_dir=args.output_dir,
        expected_quality_units_per_method_repeat=args.expected_quality_units,
        expected_raw_rows_per_method_repeat=args.expected_raw_rows_per_method_repeat,
        overwrite=args.overwrite,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["analysis_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

