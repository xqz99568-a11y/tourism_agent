import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.day7_delivery_pack import (
    DAY7_DELIVERY_PACK_SCHEMA_VERSION,
    build_day7_delivery_pack,
    write_day7_delivery_pack,
)
from app.core.paper_submission_pack import write_paper_submission_pack
from tests.test_day7_paper_submission_pack import _write_ready_formal_materials


def test_day7_delivery_pack_writes_final_handoff_and_manifest(tmp_path: Path) -> None:
    run_dir = _write_ready_formal_materials(tmp_path / "delivery-ready-run")
    write_paper_submission_pack(run_dir, min_cases=1)

    payload = write_day7_delivery_pack(run_dir, min_cases=1)

    assert Path(payload["json"]).exists()
    assert Path(payload["markdown"]).exists()
    pack = payload["pack"]
    assert pack["schema_version"] == DAY7_DELIVERY_PACK_SCHEMA_VERSION
    assert pack["readiness"]["status"] == "delivery_ready"
    assert pack["readiness"]["paper_claims_allowed"] is True
    assert pack["readiness"]["failed_checks"] == []
    assert pack["source_submission"]["status"] == "submission_ready"
    assert any(phase["phase"] == "Day7 最终交付验收" for phase in pack["day7_phases"])
    assert any(
        item["key"] == "paper_submission_pack_json" and item["exists"] and len(item["sha256"]) == 64
        for item in pack["artifact_inventory"]
    )

    markdown = Path(payload["markdown"]).read_text(encoding="utf-8")
    assert "最终交付验收报告" in markdown
    assert "Day7 链路阶段" in markdown
    assert "可复制命令" in markdown

    manifest = json.loads((run_dir / "experiment_manifest.json").read_text(encoding="utf-8"))
    assert manifest["day7_delivery_pack"]["status"] == "delivery_ready"
    assert manifest["results"]["day7_delivery_pack_json"] == payload["json"]
    assert manifest["results"]["day7_delivery_report_md"] == payload["markdown"]


def test_day7_delivery_pack_blocks_missing_submission_outputs(tmp_path: Path) -> None:
    run_dir = _write_ready_formal_materials(tmp_path / "missing-submission-run")

    pack = build_day7_delivery_pack(run_dir, min_cases=1)

    assert pack["readiness"]["status"] == "delivery_blocked"
    assert pack["readiness"]["paper_claims_allowed"] is False
    failed = set(pack["readiness"]["failed_checks"])
    assert "submission_pack_json_present" in failed
    assert "submission_checklist_md_present" in failed
    assert pack["source_submission"]["status"] == "submission_ready"


def test_export_day7_delivery_pack_cli_writes_payload(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    from experiments import export_day7_delivery_pack

    run_dir = _write_ready_formal_materials(tmp_path / "cli-run")
    write_paper_submission_pack(run_dir, min_cases=1)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "export_day7_delivery_pack.py",
            "--run-dir",
            str(run_dir),
            "--min-cases",
            "1",
            "--strict",
        ],
    )

    assert export_day7_delivery_pack.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["delivery_status"] == "delivery_ready"
    assert payload["paper_claims_allowed"] is True
    assert Path(payload["json"]).exists()
    assert Path(payload["markdown"]).exists()
