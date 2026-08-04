"""Generate the Day 7 issue list and final-fix report for a pilot run."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.day7_fix_report import write_day7_fix_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        type=Path,
        required=True,
        help="Directory containing Day 7 pilot artifacts.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Where to write the report. Defaults to --run-dir.",
    )
    parser.add_argument(
        "--development-run-dir",
        type=Path,
        default=None,
        help="Optional Day 7 development run directory used to keep method issues open when dev evidence is weak.",
    )
    parser.add_argument(
        "--m3-ablation-run-dir",
        type=Path,
        default=None,
        help="Optional M3-no-decision-normalizer ablation run directory used to close the normalizer ablation issue.",
    )
    parser.add_argument(
        "--no-manifest-attach",
        action="store_true",
        help="Do not attach report paths/status to experiment_manifest.json.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if the report itself is incomplete.",
    )
    args = parser.parse_args()

    payload = write_day7_fix_report(
        args.run_dir,
        development_run_dir=args.development_run_dir,
        m3_ablation_run_dir=args.m3_ablation_run_dir,
        output_dir=args.output_dir,
        attach_to_manifest=not args.no_manifest_attach,
    )
    response = {
        "status": payload["status"],
        "json": payload["json"],
        "markdown": payload["markdown"],
        "failed_checks": payload["failed_checks"],
        "issue_counts": payload["issue_counts"],
        "m3_systemic_failure": payload["m3_systemic_failure"],
        "m3_method_formal_run_blocked": payload["m3_method_formal_run_blocked"],
        "m3_programmatic_decision_rate": payload["m3_programmatic_decision_rate"],
        "m3_ablation_closed": payload["report"]["m3_method_readiness"].get("ablation_closed"),
        "m3_ablation_status": payload["report"]["m3_method_readiness"].get("ablation_status"),
    }
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 1 if args.strict and payload["status"] != "completed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
