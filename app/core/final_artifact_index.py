"""Immutable final artifact index for formal experiment runs.

The final index is intentionally written after all formal run artifacts and
after the manifest receives the final index path.  The index excludes its own
hash to avoid a self-referential hash cycle.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


FINAL_ARTIFACT_INDEX_SCHEMA_VERSION = "ctp-final-artifact-index-v1"
FINAL_ARTIFACT_INDEX_NAME = "final_artifact_index.json"

_RUN_ARTIFACTS = {
    "formal_preflight": "formal_preflight_report.json",
    "benchmark_results_csv": "benchmark_results.csv",
    "benchmark_results_json": "benchmark_results.json",
    "benchmark_results_checkpoint_csv": "benchmark_results.checkpoint.csv",
    "benchmark_results_checkpoint_json": "benchmark_results.checkpoint.json",
    "evaluation_summary": "evaluation_summary.json",
    "paper_tables": "paper_tables.md",
    "experiment_manifest": "experiment_manifest.json",
    "benchmark_resume_state": "benchmark_resume_state.json",
    "paper_analysis_json": "paper_analysis.json",
    "paper_analysis_md": "paper_analysis.md",
    "formal_experiment_gate": "formal_experiment_gate.json",
    "formal_experiment_report": "formal_experiment_report.md",
    "paper_result_pack_json": "paper_result_pack.json",
    "paper_result_pack_md": "paper_result_pack.md",
    "paper_draft_pack_json": "paper_draft_pack.json",
    "paper_draft_md": "paper_draft.md",
    "paper_submission_pack_json": "paper_submission_pack.json",
    "paper_submission_checklist_md": "paper_submission_checklist.md",
}


def write_final_artifact_index(
    run_dir: str | Path,
    *,
    artifact_files: Optional[Mapping[str, str | Path]] = None,
    manifest_name: str = "experiment_manifest.json",
    attach_to_manifest: bool = True,
) -> Dict[str, Any]:
    """Write the final immutable artifact index for a completed formal run."""
    root = Path(run_dir)
    index_path = root / FINAL_ARTIFACT_INDEX_NAME
    if attach_to_manifest:
        _attach_final_index_path_to_manifest(root, index_path, manifest_name=manifest_name)
    index = build_final_artifact_index(root, artifact_files=artifact_files)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "completed",
        "index_status": index["status"],
        "json": index_path.as_posix(),
        "index": index,
    }


def build_final_artifact_index(
    run_dir: str | Path,
    *,
    artifact_files: Optional[Mapping[str, str | Path]] = None,
) -> Dict[str, Any]:
    """Build the final index payload without writing it."""
    root = Path(run_dir)
    results = _read_json(root / "benchmark_results.json")
    result_count = len(results) if isinstance(results, list) else 0
    artifacts = artifact_files or _RUN_ARTIFACTS
    files = [
        _artifact_item(key, _resolve_artifact_path(root, filename))
        for key, filename in artifacts.items()
    ]
    traces = _directory_inventory(root / "traces", "*.jsonl")
    worker_requests = _directory_inventory(root / "worker_io", "*.request.json")
    worker_responses = _directory_inventory(root / "worker_io", "*.response.json")
    worker_all = _directory_inventory(root / "worker_io", "*.json")
    checks = {
        "run_dir_exists": root.exists(),
        "core_artifacts_exist": all(item["exists"] for item in files),
        "self_hash_excluded": True,
        "result_count_recorded": result_count > 0,
        "trace_count_matches_results": traces["file_count"] == result_count,
        "worker_request_count_matches_results": worker_requests["file_count"] == result_count,
        "worker_response_count_matches_results": worker_responses["file_count"] == result_count,
        "worker_json_count_matches_expected": worker_all["file_count"] == result_count * 2,
        "file_hashes_recorded": all(
            item.get("sha256") for item in files if item.get("exists") is True
        ),
        "trace_hash_recorded": _is_sha256(traces.get("combined_sha256")),
        "worker_io_hash_recorded": _is_sha256(worker_all.get("combined_sha256")),
    }
    failed_checks = [key for key, value in checks.items() if not value]
    return {
        "schema_version": FINAL_ARTIFACT_INDEX_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if not failed_checks else "failed",
        "run_dir": root.as_posix(),
        "hash_strategy": "sha256_file_bytes_v1",
        "self_hash_excluded": True,
        "self_path": (root / FINAL_ARTIFACT_INDEX_NAME).as_posix(),
        "result_count": result_count,
        "checks": checks,
        "failed_checks": failed_checks,
        "files": files,
        "files_combined_sha256": _combined_hash(
            item["sha256"] for item in files if item.get("sha256")
        ),
        "traces": traces,
        "worker_io": {
            "all": worker_all,
            "requests": worker_requests,
            "responses": worker_responses,
        },
    }


def validate_final_artifact_index(run_dir: str | Path) -> Dict[str, Any]:
    """Read the saved final index and verify that indexed file hashes still match."""
    root = Path(run_dir)
    index_path = root / FINAL_ARTIFACT_INDEX_NAME
    saved = _read_json(index_path)
    if not isinstance(saved, dict):
        return {
            "status": "failed",
            "index": index_path.as_posix(),
            "errors": ["final_artifact_index_missing_or_invalid"],
        }
    errors: List[str] = []
    for item in _as_dict_list(saved.get("files")):
        path = Path(str(item.get("path") or ""))
        if not path.exists():
            errors.append(f"missing_file:{item.get('key')}")
            continue
        if item.get("sha256") != _file_sha256(path):
            errors.append(f"hash_mismatch:{item.get('key')}")
    for section_name in ("traces",):
        section = saved.get(section_name) if isinstance(saved.get(section_name), dict) else {}
        errors.extend(_validate_directory_inventory(section_name, section))
    worker = saved.get("worker_io") if isinstance(saved.get("worker_io"), dict) else {}
    for section_name in ("all", "requests", "responses"):
        section = worker.get(section_name) if isinstance(worker.get(section_name), dict) else {}
        errors.extend(_validate_directory_inventory(f"worker_io.{section_name}", section))
    return {
        "status": "passed" if not errors else "failed",
        "index": index_path.as_posix(),
        "errors": errors,
    }


def _attach_final_index_path_to_manifest(
    root: Path,
    index_path: Path,
    *,
    manifest_name: str,
) -> None:
    manifest_path = root / manifest_name
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        return
    results = manifest.get("results") if isinstance(manifest.get("results"), dict) else {}
    results = dict(results)
    results["final_artifact_index"] = index_path.as_posix()
    manifest["results"] = results
    manifest["final_artifact_index"] = {
        "schema_version": FINAL_ARTIFACT_INDEX_SCHEMA_VERSION,
        "path": index_path.as_posix(),
        "self_hash_excluded": True,
        "manifest_records_path_only": True,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_artifact_path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _artifact_item(key: str, path: Path) -> Dict[str, Any]:
    exists = path.exists()
    return {
        "key": key,
        "path": path.as_posix(),
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else None,
        "sha256": _file_sha256(path) if exists else None,
    }


def _directory_inventory(directory: Path, pattern: str) -> Dict[str, Any]:
    files = sorted(directory.glob(pattern)) if directory.exists() else []
    items = [_artifact_item(path.name, path) for path in files]
    hashes = [item["sha256"] for item in items if item.get("sha256")]
    return {
        "directory": directory.as_posix(),
        "glob": pattern,
        "file_count": len(items),
        "combined_sha256": _combined_hash(hashes),
        "files": items,
    }


def _validate_directory_inventory(section_name: str, inventory: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    files = _as_dict_list(inventory.get("files"))
    hashes = []
    for item in files:
        path = Path(str(item.get("path") or ""))
        if not path.exists():
            errors.append(f"missing_file:{section_name}:{item.get('key')}")
            continue
        sha = _file_sha256(path)
        hashes.append(sha)
        if item.get("sha256") != sha:
            errors.append(f"hash_mismatch:{section_name}:{item.get('key')}")
    if inventory.get("combined_sha256") != _combined_hash(hashes):
        errors.append(f"combined_hash_mismatch:{section_name}")
    if inventory.get("file_count") != len(files):
        errors.append(f"file_count_mismatch:{section_name}")
    return errors


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _combined_hash(hashes: Iterable[Any]) -> str:
    return hashlib.sha256(
        "\n".join(sorted(str(item) for item in hashes if item)).encode("utf-8")
    ).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _as_dict_list(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        ch in "0123456789abcdef" for ch in value.lower()
    )
