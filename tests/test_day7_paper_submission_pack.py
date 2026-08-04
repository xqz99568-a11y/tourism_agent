import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.formal_experiment_gate import write_formal_experiment_gate
from app.core.paper_draft_pack import write_paper_draft_pack
from app.core.paper_result_pack import write_paper_result_pack
from app.core.paper_submission_pack import (
    PAPER_SUBMISSION_PACK_SCHEMA_VERSION,
    build_paper_submission_pack,
    write_paper_submission_pack,
)
from tests.test_day7_paper_draft_pack import _write_formal_run_dir


def test_paper_submission_pack_writes_archive_and_manifest(tmp_path: Path) -> None:
    run_dir = _write_ready_formal_materials(tmp_path / "submission-ready-run")

    payload = write_paper_submission_pack(run_dir, min_cases=1)

    assert Path(payload["json"]).exists()
    assert Path(payload["markdown"]).exists()
    pack = payload["pack"]
    assert pack["schema_version"] == PAPER_SUBMISSION_PACK_SCHEMA_VERSION
    assert pack["readiness"]["status"] == "submission_ready"
    assert pack["readiness"]["paper_claims_allowed"] is True
    assert pack["readiness"]["failed_checks"] == []
    assert pack["artifact_inventory"]["traces"]["trace_file_count"] == 4
    assert len(pack["artifact_inventory"]["traces"]["trace_combined_sha256"]) == 64
    assert any(
        item["key"] == "paper_draft_md" and item["exists"] and len(item["sha256"]) == 64
        for item in pack["artifact_inventory"]["files"]
    )
    assert any(item["status"] == "manual_required" for item in pack["submission_checklist"])

    markdown = Path(payload["markdown"]).read_text(encoding="utf-8")
    assert "论文投稿归档包" in markdown
    assert "复现实验命令" in markdown
    assert "Artifact inventory" in markdown

    manifest = json.loads((run_dir / "experiment_manifest.json").read_text(encoding="utf-8"))
    assert manifest["paper_submission_pack"]["status"] == "submission_ready"
    assert manifest["results"]["paper_submission_pack_json"] == payload["json"]
    assert manifest["results"]["paper_submission_checklist_md"] == payload["markdown"]


def test_paper_submission_pack_blocks_missing_draft_pack(tmp_path: Path) -> None:
    run_dir = _write_formal_run_dir(tmp_path / "missing-draft-run", independent_cases=1)
    write_formal_experiment_gate(run_dir, min_cases=1)
    write_paper_result_pack(run_dir, profile="formal", min_cases=1)

    pack = build_paper_submission_pack(run_dir, min_cases=1)

    assert pack["readiness"]["status"] == "revision_needed"
    assert pack["readiness"]["paper_claims_allowed"] is False
    failed = set(pack["readiness"]["failed_checks"])
    assert "required_artifacts_present" in failed
    assert "paper_draft_pack_present" in failed
    assert "paper_draft_markdown_present" in failed
    assert "paper_draft_claims_allowed" in failed


def test_export_paper_submission_pack_cli_writes_payload(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    from experiments import export_paper_submission_pack

    run_dir = _write_ready_formal_materials(tmp_path / "cli-run")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "export_paper_submission_pack.py",
            "--run-dir",
            str(run_dir),
            "--min-cases",
            "1",
            "--strict",
        ],
    )

    assert export_paper_submission_pack.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["submission_status"] == "submission_ready"
    assert payload["paper_claims_allowed"] is True
    assert Path(payload["json"]).exists()
    assert Path(payload["markdown"]).exists()


def _write_ready_formal_materials(run_dir: Path) -> Path:
    run_dir = _write_formal_run_dir(run_dir, independent_cases=1)
    write_formal_experiment_gate(run_dir, min_cases=1)
    write_paper_result_pack(run_dir, profile="formal", min_cases=1)
    write_paper_draft_pack(run_dir, profile="formal", min_cases=1)
    return run_dir
