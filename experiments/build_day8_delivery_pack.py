"""Build the Day8 delivery package for frozen formal experiment inputs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.day8_delivery_pack import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    write_day8_delivery_pack,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--docs-report", type=Path, default=None)
    args = parser.parse_args()
    payload = write_day8_delivery_pack(
        output_dir=args.output_dir,
        docs_report_path=args.docs_report,
        run_id=args.run_id,
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "delivery_status": payload["delivery_status"],
                "ready_for_formal_experiment": payload["ready_for_formal_experiment"],
                "failed_checks": payload["failed_checks"],
                "json": payload["json"],
                "markdown": payload["markdown"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload["ready_for_formal_experiment"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
