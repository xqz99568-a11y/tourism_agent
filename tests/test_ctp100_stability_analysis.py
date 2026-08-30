import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.ctp100_stability_analysis import (
    M2_METHOD,
    M3_METHOD,
    build_ctp100_m2_m3_stability_analysis,
    write_ctp100_m2_m3_stability_analysis,
)


def _row(case_id: str, method: str, repeat_index: int, stsr: bool) -> dict:
    return {
        "case_id": case_id,
        "method": method,
        "repeat_index": repeat_index,
        "status": "completed",
        "latency_ms": 1000 + repeat_index,
        "metrics": {
            "stsr": stsr,
            "evaluation_hcsr": 1.0 if stsr else 0.5,
            "bpcr": 1.0,
            "agent_selection_f1": 1.0,
            "tool_selection_f1": 1.0,
            "total_tokens": 100 + repeat_index,
            "standardized_estimated_cost": 0.01 + repeat_index * 0.001,
            "llm_call_count": 2,
            "agent_call_count": 3,
            "tool_call_count": 4,
        },
        "trace": {
            "agent_call_count": 3,
            "tool_call_count": 4,
        },
    }


def _write_source_runs(tmp_path: Path, *, omit_m3_repeat_2: bool = False) -> tuple[Path, Path]:
    v6 = tmp_path / "formal_ctp100_v6"
    stability = tmp_path / "stability"
    v6.mkdir()
    stability.mkdir()
    cases = ("c1", "c2")
    v6_rows = []
    stability_rows = []
    for case_id in cases:
        v6_rows.append(_row(case_id, M2_METHOD, 0, stsr=case_id == "c1"))
        v6_rows.append(_row(case_id, M3_METHOD, 0, stsr=True))
        v6_rows.append(_row(case_id, "single_agent", 0, stsr=False))
        for repeat in (1, 2):
            stability_rows.append(_row(case_id, M2_METHOD, repeat, stsr=case_id == "c1"))
            if not (omit_m3_repeat_2 and repeat == 2):
                stability_rows.append(_row(case_id, M3_METHOD, repeat, stsr=True))
    (v6 / "benchmark_results.json").write_text(
        json.dumps(v6_rows, ensure_ascii=False),
        encoding="utf-8",
    )
    (stability / "benchmark_results.json").write_text(
        json.dumps(stability_rows, ensure_ascii=False),
        encoding="utf-8",
    )
    return v6, stability


def test_build_ctp100_m2_m3_stability_analysis_combines_three_repeats(
    tmp_path: Path,
) -> None:
    v6, stability = _write_source_runs(tmp_path)

    analysis = build_ctp100_m2_m3_stability_analysis(
        v6_run_dir=v6,
        stability_run_dir=stability,
        expected_quality_units_per_method_repeat=2,
        expected_raw_rows_per_method_repeat=2,
    )

    assert analysis["status"] == "passed"
    assert analysis["failed_checks"] == []
    assert analysis["row_counts"]["raw_total"] == 12
    assert analysis["row_counts"]["quality_total"] == 12
    assert len(analysis["repeat_pair_deltas"]) == 3
    assert [row["stsr_delta"] for row in analysis["repeat_pair_deltas"]] == [0.5, 0.5, 0.5]
    assert analysis["combined_key_results"]["stsr"]["m2_mean"] == 0.5
    assert analysis["combined_key_results"]["stsr"]["m3_mean"] == 1.0
    assert analysis["paper_claim_guidance"]["claim_level"] != "not_allowed"


def test_build_ctp100_m2_m3_stability_analysis_fails_on_missing_repeat(
    tmp_path: Path,
) -> None:
    v6, stability = _write_source_runs(tmp_path, omit_m3_repeat_2=True)

    analysis = build_ctp100_m2_m3_stability_analysis(
        v6_run_dir=v6,
        stability_run_dir=stability,
        expected_quality_units_per_method_repeat=2,
        expected_raw_rows_per_method_repeat=2,
    )

    assert analysis["status"] == "failed"
    assert "raw_row_count" in analysis["failed_checks"]
    assert "quality_count_per_method_repeat" in analysis["failed_checks"]
    assert "m2_m3_quality_unit_pairs_match_each_repeat" in analysis["failed_checks"]


def test_write_ctp100_m2_m3_stability_analysis_outputs_artifacts(
    tmp_path: Path,
) -> None:
    v6, stability = _write_source_runs(tmp_path)
    output = tmp_path / "offline_analysis"

    payload = write_ctp100_m2_m3_stability_analysis(
        v6_run_dir=v6,
        stability_run_dir=stability,
        output_dir=output,
        expected_quality_units_per_method_repeat=2,
        expected_raw_rows_per_method_repeat=2,
    )

    assert payload["analysis_status"] == "passed"
    assert (output / "ctp100_m2_m3_stability_combined_analysis.json").exists()
    assert (output / "ctp100_m2_m3_stability_combined_analysis.md").exists()
    assert (output / "combined_evaluation_summary.json").exists()
    assert (output / "repeat_method_metrics.csv").exists()
    assert (output / "repeat_pair_deltas.csv").exists()
    manifest = json.loads((output / "analysis_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "passed"
    assert manifest["artifact_hashes"]["combined_evaluation_summary.json"]


def test_write_ctp100_m2_m3_stability_analysis_refuses_to_overwrite(
    tmp_path: Path,
) -> None:
    v6, stability = _write_source_runs(tmp_path)
    output = tmp_path / "offline_analysis"
    output.mkdir()
    (output / "combined_evaluation_summary.json").write_text("{}", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_ctp100_m2_m3_stability_analysis(
            v6_run_dir=v6,
            stability_run_dir=stability,
            output_dir=output,
            expected_quality_units_per_method_repeat=2,
            expected_raw_rows_per_method_repeat=2,
        )
