"""Artifact and Git integrity checks for formal academic experiments.

The formal experiment has two kinds of gates:

* preflight: can this run start?
* final gate: can the saved results support paper claims?

Both gates need to speak about the same frozen inputs, evaluator code, rule
catalog, and Git state.  This module keeps that evidence in one small,
read-only place.  It never calls an LLM and never refreshes online data.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping


FORMAL_ARTIFACT_INTEGRITY_SCHEMA_VERSION = "ctp-formal-artifact-integrity-v1"
FORMAL_EVALUATION_RULE_CATALOG_ID = "day8_formal_independent_evaluator_rules"
FORMAL_EVALUATION_RULE_CATALOG_FROZEN_ON = "2026-08-19"
FILE_HASH_STRATEGY = "sha256_file_bytes_v1"

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_FORMAL_INTEGRITY_PATHS: dict[str, Path] = {
    "benchmark_manifest": ROOT / "experiments" / "benchmark.json",
    "formal_dataset": ROOT / "experiments" / "ctp100_formal_v2.json",
    "sealed_validation_dataset": ROOT / "experiments" / "ctp30_sealed_validation_v1.json",
    "academic_experiment_design": ROOT / "experiments" / "academic_experiment_design_v1.json",
    "experiment_protocol": ROOT / "Phase0_实验协议.md",
    "budget_policy_doc": ROOT / "docs" / "Budget_Policy_v2.md",
    "budget_gold": ROOT / "experiments" / "generated" / "ctp100_budget_gold_v2.json",
    "qweather_manifest": ROOT / "data" / "weather_snapshot" / "qweather_v1" / "snapshot_manifest.json",
    "qweather_validation": ROOT / "data" / "weather_snapshot" / "qweather_v1" / "validation_report.json",
    "intercity_manifest": ROOT / "data" / "intercity_transport" / "snapshot_manifest.json",
    "intercity_fare_table": ROOT / "data" / "intercity_transport" / "rail_second_class_v1.json",
    "evaluation_rule_catalog": ROOT / "experiments" / "evaluation_rule_catalog.json",
    "independent_evaluator_code": ROOT / "app" / "core" / "independent_evaluator.py",
    "experiment_runner_code": ROOT / "app" / "core" / "experiment_runner.py",
    "method_contract_code": ROOT / "app" / "core" / "experiment_method_contract.py",
    "formal_preflight_code": ROOT / "app" / "core" / "formal_experiment_preflight.py",
    "formal_gate_code": ROOT / "app" / "core" / "formal_experiment_gate.py",
}


def build_formal_artifact_integrity_report(
    *,
    paths: Mapping[str, str | Path] | None = None,
    include_git: bool = True,
) -> dict[str, Any]:
    """Return hashes for the frozen formal-input and evaluator artifacts."""
    selected_paths = {
        key: Path(value)
        for key, value in (paths or DEFAULT_FORMAL_INTEGRITY_PATHS).items()
    }
    artifacts = {
        key: _artifact_item(path)
        for key, path in selected_paths.items()
    }
    missing = [key for key, item in artifacts.items() if item["exists"] is not True]
    artifact_hashes = [
        str(item["sha256"])
        for item in artifacts.values()
        if item.get("sha256")
    ]
    report = {
        "schema_version": FORMAL_ARTIFACT_INTEGRITY_SCHEMA_VERSION,
        "hash_strategy": FILE_HASH_STRATEGY,
        "artifacts": artifacts,
        "combined_sha256": _combined_hash(artifact_hashes),
        "all_required_artifacts_exist": not missing,
        "missing_artifacts": missing,
        "git": git_state_report() if include_git else {
            "checked": False,
            "commit": None,
            "worktree_clean": None,
            "status_short": [],
        },
    }
    return report


def git_state_report() -> dict[str, Any]:
    """Return current Git commit and working tree state."""
    commit = _git_command(["rev-parse", "HEAD"])
    status_text = _git_command(["status", "--short"])
    status_lines = status_text.splitlines() if status_text else []
    return {
        "checked": True,
        "commit": commit or "unknown",
        "worktree_clean": len(status_lines) == 0,
        "status_short": status_lines,
    }


def artifact_hash(report: Mapping[str, Any], key: str) -> str | None:
    artifact = report.get("artifacts")
    if not isinstance(artifact, Mapping):
        return None
    item = artifact.get(key)
    if not isinstance(item, Mapping):
        return None
    value = item.get("sha256")
    return str(value) if value else None


def artifact_hashes_match(
    *,
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    keys: list[str] | tuple[str, ...],
) -> bool:
    return all(
        artifact_hash(expected, key) == artifact_hash(actual, key)
        for key in keys
    )


def _artifact_item(path: Path) -> dict[str, Any]:
    exists = path.exists()
    return {
        "path": _display_path(path),
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else None,
        "sha256": _file_sha256(path) if exists else None,
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _combined_hash(hashes: list[str]) -> str | None:
    if not hashes:
        return None
    payload = json.dumps(sorted(hashes), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _git_command(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return completed.stdout.strip()


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()
