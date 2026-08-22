"""Build the pre-formal Task D/E/F validation registry."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.pre_formal_validation_registry import (  # noqa: E402
    DEFAULT_PRE_FORMAL_VALIDATION_REGISTRY_PATH,
    validate_pre_formal_validation_registry,
    write_pre_formal_validation_registry,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_PRE_FORMAL_VALIDATION_REGISTRY_PATH,
        help="Registry JSON output path.",
    )
    args = parser.parse_args()

    path = write_pre_formal_validation_registry(output_path=args.output)
    report = validate_pre_formal_validation_registry(path)
    print(
        json.dumps(
            {
                "status": report["status"],
                "registry": path.as_posix(),
                "registry_sha256": report.get("registry_sha256"),
                "errors": report.get("errors") or [],
                "warnings": report.get("warnings") or [],
                "summary": report.get("summary") or {},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
