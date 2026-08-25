import hashlib
import json
from pathlib import Path

from app.core.final_artifact_index import (
    FINAL_ARTIFACT_INDEX_NAME,
    validate_final_artifact_index,
    write_final_artifact_index,
)
from app.core.formal_experiment_gate import write_formal_experiment_gate
from app.core.paper_draft_pack import write_paper_draft_pack
from app.core.paper_result_pack import write_paper_result_pack
from app.core.paper_submission_pack import write_paper_submission_pack
from tests.test_day7_formal_gate import _write_formal_run_dir


def test_final_artifact_index_is_last_readable_hash_anchor(tmp_path: Path) -> None:
    run_dir = _write_formal_run_dir(tmp_path / "final-index-run", independent_cases=1)
    results = json.loads((run_dir / "benchmark_results.json").read_text(encoding="utf-8"))
    _write_resume_and_checkpoint_artifacts(run_dir, results)
    _write_worker_io(run_dir, result_count=len(results))
    write_formal_experiment_gate(run_dir, min_cases=1)
    write_paper_result_pack(run_dir, profile="formal", min_cases=1)
    write_paper_draft_pack(run_dir, profile="formal", min_cases=1)
    write_paper_submission_pack(run_dir, min_cases=1)

    payload = write_final_artifact_index(run_dir)
    index_path = run_dir / FINAL_ARTIFACT_INDEX_NAME
    index = payload["index"]
    manifest_path = run_dir / "experiment_manifest.json"

    assert payload["index_status"] == "passed"
    assert index_path.exists()
    assert index["checks"]["self_hash_excluded"] is True
    assert all(item["key"] != FINAL_ARTIFACT_INDEX_NAME for item in index["files"])
    assert index["traces"]["file_count"] == len(results)
    assert index["worker_io"]["requests"]["file_count"] == len(results)
    assert index["worker_io"]["responses"]["file_count"] == len(results)
    manifest_item = next(item for item in index["files"] if item["key"] == "experiment_manifest")
    assert manifest_item["sha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    manifest_hash_before = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    index_hash_before = hashlib.sha256(index_path.read_bytes()).hexdigest()
    validation = validate_final_artifact_index(run_dir)
    manifest_hash_after = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    index_hash_after = hashlib.sha256(index_path.read_bytes()).hexdigest()

    assert validation["status"] == "passed"
    assert manifest_hash_after == manifest_hash_before
    assert index_hash_after == index_hash_before


def _write_resume_and_checkpoint_artifacts(run_dir: Path, results: list[dict]) -> None:
    (run_dir / "benchmark_results.checkpoint.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "benchmark_results.checkpoint.csv").write_text(
        "case_id,method\n"
        + "\n".join(f"{item['case_id']},{item['method']}" for item in results)
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "benchmark_resume_state.json").write_text(
        json.dumps(
            {
                "schema_version": "ctp-benchmark-resume-state-v1",
                "status": "completed",
                "completed_result_count": len(results),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_worker_io(run_dir: Path, *, result_count: int) -> None:
    worker_dir = run_dir / "worker_io"
    worker_dir.mkdir()
    for index in range(result_count):
        stem = f"case_{index:03d}"
        (worker_dir / f"{stem}.request.json").write_text(
            json.dumps({"index": index}, ensure_ascii=False),
            encoding="utf-8",
        )
        (worker_dir / f"{stem}.response.json").write_text(
            json.dumps({"index": index, "status": "completed"}, ensure_ascii=False),
            encoding="utf-8",
        )
