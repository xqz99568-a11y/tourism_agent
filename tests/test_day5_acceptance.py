import json
import sys
from pathlib import Path

import pytest


def test_day5_acceptance_script_writes_evaluation_evidence(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    from experiments import run_day5_acceptance as day5_acceptance

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_day5_acceptance.py",
            "--output-dir",
            str(tmp_path / "day5_acceptance"),
            "--run-id",
            "day5-unit",
        ],
    )

    assert day5_acceptance.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "passed"
    assert payload["run_id"] == "day5-unit"
    assert payload["result_count"] == payload["expected_count"] == 32
    for key in ("summary", "paper_tables", "manifest", "report"):
        assert Path(payload[key]).exists()

    cases = json.loads(day5_acceptance.BENCHMARK_PATH.read_text(encoding="utf-8"))["cases"]
    catalog = day5_acceptance.load_rule_catalog()
    assert {case["task_type"] for case in cases} == set(catalog["task_types"])

    summary = json.loads(Path(payload["summary"]).read_text(encoding="utf-8"))
    manifest = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
    paper_tables = Path(payload["paper_tables"]).read_text(encoding="utf-8")
    assert set(summary["methods"]) == set(day5_acceptance.ExperimentRunner.METHODS)
    assert summary["paired_m3_vs_m2"]["pair_count"] == 8
    assert summary["paired_statistics"]["pair_count"] == 8
    assert "bootstrap_ci_95" in summary["paired_statistics"]["metrics"]["stsr"]["delta"]
    assert "agent_set_exact_match_mean" in summary["methods"]["adaptive_multi_agent"]
    assert "total_tokens_mean" in summary["methods"]["adaptive_multi_agent"]
    assert "M3 Proposed" in paper_tables
    assert "Agent/tool diagnostics" in paper_tables
    assert "Token and cost" in paper_tables
    assert manifest["results"]["paper_tables"] == payload["paper_tables"]
    assert manifest["evaluation"]["catalog_id"] == "day8_formal_independent_evaluator_rules"


def test_day5_acceptance_refuses_to_overwrite_output_dir(monkeypatch, tmp_path: Path) -> None:
    from experiments import run_day5_acceptance as day5_acceptance

    output_root = tmp_path / "day5_acceptance"
    occupied = output_root / "day5-unit"
    occupied.mkdir(parents=True)
    marker = occupied / "old.txt"
    marker.write_text("keep", encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_day5_acceptance.py",
            "--output-dir",
            str(output_root),
            "--run-id",
            "day5-unit",
        ],
    )

    with pytest.raises(RuntimeError, match="not empty"):
        day5_acceptance.main()
    assert marker.read_text(encoding="utf-8") == "keep"
