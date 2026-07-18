"""Run and freeze Day 4 scheduler acceptance evidence.

This script is intentionally offline and deterministic. It checks the Day 4
goal-state scheduler contract, M3 reuse execution, metrics, and trace evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_OUTPUT_ROOT = ROOT / "experiments" / "results" / "day4_acceptance"

HASHED_INPUTS = {
    "source": [
        "app/core/goal_state_scheduler.py",
        "app/core/experiment_runner.py",
        "app/core/tracing.py",
        "app/schemas/experiment.py",
        "experiments/run_day4_acceptance.py",
        "docs/Day4_acceptance_report.md",
        "docs/Day4_goal_state_scheduler_rules.md",
        "docs/TRACE_FIELDS.md",
    ],
    "tests": [
        "tests/test_goal_state_scheduler.py",
        "tests/test_research_tools.py",
        "tests/test_tracing.py",
    ],
    "cases": [
        "experiments/day4_scheduler_acceptance_cases.json",
    ],
}


class _AcceptanceLLM:
    async def chat(self, messages: Any, tools: Any = None) -> Any:
        return SimpleNamespace(
            content="offline acceptance answer",
            tool_calls=[],
            usage={"total_tokens": 1},
        )


COMMANDS = [
    {
        "name": "compile_day4_modules",
        "args": [
            sys.executable,
            "-m",
            "compileall",
            "-q",
            "app/core/goal_state_scheduler.py",
            "app/core/experiment_runner.py",
            "app/core/tracing.py",
            "app/schemas/experiment.py",
            "experiments/run_day4_acceptance.py",
            "tests/test_goal_state_scheduler.py",
            "tests/test_research_tools.py",
        ],
    },
    {
        "name": "pytest_day4_scheduler_and_runner",
        "args": [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_goal_state_scheduler.py",
            "tests/test_research_tools.py",
        ],
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Day 4 acceptance checks.")
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Directory where a unique Day 4 acceptance run folder is created.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional explicit run id. The script refuses to overwrite it.",
    )
    args = parser.parse_args()

    run_id = args.run_id or f"day4_acceptance_{_timestamp()}"
    git_info = _git_info()
    output_dir = Path(args.output_root) / run_id
    if output_dir.exists():
        raise SystemExit(f"Refusing to overwrite existing Day 4 evidence: {output_dir}")
    output_dir.mkdir(parents=True)

    command_results = [_run_command(spec, output_dir) for spec in COMMANDS]
    passed = all(item["returncode"] == 0 for item in command_results)
    representative = _write_representative_trace(output_dir, run_id) if passed else {}
    manifest = _build_manifest(
        run_id=run_id,
        output_dir=output_dir,
        command_results=command_results,
        passed=passed,
        representative=representative,
        git_info=git_info,
    )

    manifest_path = output_dir / "day4_acceptance_manifest.json"
    report_path = output_dir / "day4_acceptance_report.md"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(_render_report(manifest), encoding="utf-8")

    print(
        json.dumps(
            {
                "run_id": run_id,
                "passed": passed,
                "output_dir": str(output_dir),
                "manifest": str(manifest_path),
                "report": str(report_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if passed else 1


def _run_command(spec: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    completed = subprocess.run(
        spec["args"],
        cwd=ROOT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        text=True,
        capture_output=True,
        check=False,
    )
    stdout_path = output_dir / f"{spec['name']}.stdout.txt"
    stderr_path = output_dir / f"{spec['name']}.stderr.txt"
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    return {
        "name": spec["name"],
        "args": spec["args"],
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "returncode": completed.returncode,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }


def _write_representative_trace(output_dir: Path, run_id: str) -> dict[str, Any]:
    from app.core.experiment_runner import ExperimentRunner

    trace_dir = output_dir / "traces"
    runner = ExperimentRunner(
        trace_dir=trace_dir,
        output_dir=output_dir,
        llm_factory=_AcceptanceLLM,
        run_id=run_id,
        model_config_name="day4-acceptance-offline",
    )
    first = runner.run(
        {
            "case_id": "day4_trace_turn1",
            "user_input": "plan a two day Hangzhou trip",
            "slots": {
                "destination": "hangzhou",
                "duration": 2,
                "people_count": 2,
                "start_date": "2026-08-01",
            },
        },
        method="adaptive_multi_agent",
        repeat_index=0,
    )
    second = runner.run(
        {
            "case_id": "day4_trace_turn2",
            "user_input": "same plan again",
            "slots": {},
            "previous_state": first,
        },
        method="adaptive_multi_agent",
        repeat_index=0,
    )
    result_path = output_dir / "representative_results.json"
    result_path.write_text(
        json.dumps([first, second], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    trace_files = sorted(trace_dir.glob("*.jsonl"))
    return {
        "result_path": str(result_path),
        "result_sha256": _sha256_file(result_path),
        "trace_dir": str(trace_dir),
        "trace_files": [
            {
                "path": str(path),
                "sha256": _sha256_file(path),
            }
            for path in trace_files
        ],
    }


def _build_manifest(
    *,
    run_id: str,
    output_dir: Path,
    command_results: list[dict[str, Any]],
    passed: bool,
    representative: dict[str, Any],
    git_info: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "day4-acceptance-manifest-v1",
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "output_dir": str(output_dir),
        "git": git_info,
        "scope": {
            "scheduler": "app/core/goal_state_scheduler.py",
            "runner": "app/core/experiment_runner.py",
            "trace": "app/core/tracing.py",
            "acceptance_cases": "experiments/day4_scheduler_acceptance_cases.json",
            "tests": [
                "tests/test_goal_state_scheduler.py",
                "tests/test_research_tools.py",
            ],
        },
        "checked_requirements": [
            "wrong previous-result city fingerprint must not be reused",
            "failed previous tool result must not be counted as reused",
            "multiple changed slots must be combined before scheduling",
            "goal shift without slot change must not become identical reuse",
            "M2 and M3 follow-up runs must receive comparable previous slots",
            "M3 savings metrics must use task-aware M2 reference counts",
            "scheduler ticket, decision, reuse validation, and hit rate must persist in trace",
            "single-capability tasks must not create fake itinerary fingerprints",
            "reused, invalidated, and replanned agent sets must be mutually consistent",
            "budget estimation must schedule missing attraction evidence before budget",
            "reused itinerary must copy the previous itinerary artifact instead of rebuilding it",
            "clarification tasks must stop with clarification status and explicit missing fields",
            "fixed M2 must recover slots from its own previous turn output",
            "available result markers without concrete artifacts must not count as reuse",
            "upstream tool failure must stop downstream dependent agents",
            "expired previous results must not be reusable",
            "empty preferences and null budget must be preserved as cancellation deltas",
            "regenerate requests must override identical-request reuse",
            "same-plan attraction expansion must override identical-request reuse",
            "previous-state expired flags and tool-result expired flags must block reuse",
            "previous fingerprints with extra conditions must not match missing current slots",
            "different repeat_index values must use isolated experiment session ids",
            "different run_id values must use isolated experiment session ids",
            "M3 scheduler metrics must be recoverable from trace after output exceptions",
            "acceptance manifest must freeze git state, SHA-256 inputs, outputs, and representative trace",
        ],
        "input_sha256": {
            group: _hash_files(paths)
            for group, paths in HASHED_INPUTS.items()
        },
        "commands": command_results,
        "representative_run": representative,
        "output_sha256": _hash_output_files(output_dir),
    }


def _git_info() -> dict[str, Any]:
    commit = _git_command(["rev-parse", "HEAD"], strip=True)
    status = _git_command(["status", "--short"], strip=False)
    return {
        "commit": commit,
        "working_tree_clean": status == "",
        "status_short": status.splitlines() if status else [],
    }


def _git_command(args: list[str], *, strip: bool) -> str | None:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() if strip else completed.stdout.rstrip("\r\n")


def _hash_files(paths: list[str]) -> dict[str, str | None]:
    hashes: dict[str, str | None] = {}
    for relative in paths:
        path = ROOT / relative
        hashes[relative] = _sha256_file(path) if path.exists() else None
    return hashes


def _hash_output_files(output_dir: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "day4_acceptance_manifest.json":
            continue
        hashes[str(path.relative_to(output_dir))] = _sha256_file(path)
    return hashes


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _render_report(manifest: dict[str, Any]) -> str:
    lines = [
        "# Day 4 Acceptance Report",
        "",
        f"- run_id: `{manifest['run_id']}`",
        f"- passed: `{manifest['passed']}`",
        f"- created_at: `{manifest['created_at']}`",
        f"- git_commit: `{(manifest.get('git') or {}).get('commit')}`",
        f"- working_tree_clean: `{(manifest.get('git') or {}).get('working_tree_clean')}`",
        "",
        "## Checked requirements",
        "",
    ]
    lines.extend(f"- {item}" for item in manifest["checked_requirements"])
    lines.extend(["", "## Commands", ""])
    for command in manifest["commands"]:
        args = " ".join(command["args"])
        lines.append(f"- `{command['name']}`: returncode `{command['returncode']}`")
        lines.append(f"  - command: `{args}`")
        lines.append(f"  - stdout: `{command['stdout_path']}`")
        lines.append(f"  - stderr: `{command['stderr_path']}`")
    representative = manifest.get("representative_run") or {}
    lines.extend(["", "## Representative trace", ""])
    lines.append(f"- result: `{representative.get('result_path')}`")
    for trace_file in representative.get("trace_files") or []:
        lines.append(f"- trace: `{trace_file.get('path')}`")
        lines.append(f"  - sha256: `{trace_file.get('sha256')}`")
    lines.append("")
    return "\n".join(lines)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


if __name__ == "__main__":
    raise SystemExit(main())
