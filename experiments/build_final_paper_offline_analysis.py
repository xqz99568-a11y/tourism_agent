"""Build final offline paper-analysis artifacts for Tourism Agent experiments."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.final_paper_offline_analysis import write_final_paper_offline_analysis


DEFAULT_OUTPUT_DIR = Path(
    r"D:\Tourism_Agent_Formal_Runs\paper_final_offline_analysis\paper_final_offline_analysis_20260831_v1"
)
DEFAULT_CTP100_V6_RUN_DIR = Path(
    r"D:\Tourism_Agent_Formal_Runs\formal_ctp100_20260825_v6"
)
DEFAULT_CTP100_STABILITY_RUN_DIR = Path(
    r"D:\Tourism_Agent_Formal_Runs\ctp100_m2_m3_stability\ctp100_m2m3_stability_20260830_v1"
)
DEFAULT_CTP100_STABILITY_ANALYSIS_DIR = Path(
    r"D:\Tourism_Agent_Formal_Runs\ctp100_m2_m3_stability\ctp100_m2m3_stability_20260830_v1_offline_analysis"
)
DEFAULT_M3_NO_REUSE_RUN_DIR = Path(
    r"D:\Tourism_Agent_Formal_Runs\ctp100_m3_no_reuse_ablation\ctp100_m3_no_reuse_ablation_20260831_v2"
)
DEFAULT_CTP30_V1_RUN_DIR = Path(
    r"D:\Tourism_Agent_Formal_Runs\ctp30_sealed_validation\ctp30_sealed_validation_20260826_v1"
)
DEFAULT_CTP30_V2_RUN_DIR = Path(
    r"D:\Tourism_Agent_Formal_Runs\ctp30_sealed_validation\ctp30_multiturn_v2_20260830_v2"
)
DEFAULT_HOLM_SECONDARY_DIR = Path(
    r"D:\Tourism_Agent_Formal_Runs\formal_ctp100_20260825_v6_secondary_statistics"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--ctp100-v6-run-dir", type=Path, default=DEFAULT_CTP100_V6_RUN_DIR)
    parser.add_argument("--ctp100-stability-run-dir", type=Path, default=DEFAULT_CTP100_STABILITY_RUN_DIR)
    parser.add_argument("--ctp100-stability-analysis-dir", type=Path, default=DEFAULT_CTP100_STABILITY_ANALYSIS_DIR)
    parser.add_argument("--m3-no-reuse-run-dir", type=Path, default=DEFAULT_M3_NO_REUSE_RUN_DIR)
    parser.add_argument("--ctp30-v1-run-dir", type=Path, default=DEFAULT_CTP30_V1_RUN_DIR)
    parser.add_argument("--ctp30-v2-run-dir", type=Path, default=DEFAULT_CTP30_V2_RUN_DIR)
    parser.add_argument("--holm-secondary-dir", type=Path, default=DEFAULT_HOLM_SECONDARY_DIR)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing final offline-analysis artifacts in --output-dir.",
    )
    args = parser.parse_args()

    result = write_final_paper_offline_analysis(
        output_dir=args.output_dir,
        ctp100_v6_run_dir=args.ctp100_v6_run_dir,
        ctp100_stability_run_dir=args.ctp100_stability_run_dir,
        ctp100_stability_analysis_dir=args.ctp100_stability_analysis_dir,
        m3_no_reuse_run_dir=args.m3_no_reuse_run_dir,
        ctp30_v1_run_dir=args.ctp30_v1_run_dir,
        ctp30_v2_run_dir=args.ctp30_v2_run_dir,
        holm_secondary_dir=args.holm_secondary_dir,
        overwrite=args.overwrite,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
