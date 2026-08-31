import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.final_paper_offline_analysis import (
    build_final_paper_offline_analysis,
    write_final_paper_offline_analysis,
)


def _result_row(
    scenario_id: str,
    *,
    method: str,
    repeat_index: int,
    turn_id: str = "t2",
    target_turn: bool = True,
    stsr: bool = True,
    tokens: float = 1000.0,
    cost: float = 0.01,
    latency: float = 100.0,
) -> dict:
    return {
        "case_id": scenario_id,
        "scenario_id": scenario_id,
        "turn_id": turn_id,
        "turn_index": 1 if turn_id == "t2" else 0,
        "scenario_turn_count": 2,
        "target_turn": target_turn,
        "method": method,
        "repeat_index": repeat_index,
        "status": "completed",
        "latency_ms": latency,
        "metrics": {
            "stsr": stsr,
            "evaluation_hcsr": 1.0 if stsr else 0.9,
            "bpcr": 1.0,
            "agent_selection_f1": 1.0,
            "tool_selection_f1": 1.0,
            "total_tokens": tokens,
            "standardized_estimated_cost": cost,
            "llm_call_count": 2,
        },
        "trace": {
            "agent_call_count": 2,
            "tool_call_count": 1,
        },
    }


def _summary(result_count: int, quality_result_count: int) -> dict:
    methods = {}
    for method in (
        "llm_direct",
        "single_agent",
        "fixed_multi_agent",
        "adaptive_multi_agent",
        "adaptive_multi_agent_no_reuse",
    ):
        methods[method] = {
            "case_count": 30 if method == "adaptive_multi_agent_no_reuse" else 100,
            "raw_run_count": 90 if method == "adaptive_multi_agent_no_reuse" else 100,
            "stsr_rate": 0.9,
            "evaluation_hcsr_mean": 0.95,
            "bpcr_mean": 1.0,
            "agent_selection_f1_mean": 0.8,
            "tool_selection_f1_mean": 0.8,
            "total_tokens_mean": 1000,
            "standardized_estimated_cost_mean": 0.01,
            "latency_ms_mean": 100,
            "llm_call_count_mean": 2,
            "agent_call_count_mean": 2,
            "tool_call_count_mean": 1,
            "successful_case_count": 90,
        }
    return {
        "result_count": result_count,
        "quality_result_count": quality_result_count,
        "methods": methods,
        "paired_statistics": {
            "metrics": {
                "stsr": {
                    "pair_count": 30,
                    "m2": {"mean": 0.8},
                    "m3": {"mean": 0.9},
                    "delta": {"mean": 0.1, "bootstrap_ci_95": [0.0, 0.2]},
                    "mcnemar": {"p_value": 0.05, "m3_only_success": 3, "m2_only_success": 0},
                }
            }
        },
    }


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _make_run_dirs(tmp_path: Path) -> dict:
    dirs = {
        "ctp100_v6": tmp_path / "ctp100_v6",
        "ctp100_stability": tmp_path / "ctp100_stability",
        "ctp100_stability_analysis": tmp_path / "ctp100_stability_analysis",
        "m3_no_reuse": tmp_path / "m3_no_reuse",
        "ctp30_v1": tmp_path / "ctp30_v1",
        "ctp30_v2": tmp_path / "ctp30_v2",
        "holm": tmp_path / "holm",
    }
    for path in dirs.values():
        path.mkdir(parents=True)

    scenario_ids = [f"ctp100_v2_{index:03d}" for index in range(51, 81)]
    v6_rows = [
        _result_row(sid, method="adaptive_multi_agent", repeat_index=0, tokens=1000, cost=0.01, latency=100)
        for sid in scenario_ids
    ]
    v6_rows.extend(
        _result_row(f"filler_v6_{index:03d}", method="llm_direct", repeat_index=0)
        for index in range(520 - len(v6_rows))
    )
    stability_rows = []
    for repeat in (1, 2):
        stability_rows.extend(
            _result_row(sid, method="adaptive_multi_agent", repeat_index=repeat, tokens=1000, cost=0.01, latency=100)
            for sid in scenario_ids
        )
    stability_rows.extend(
        _result_row(f"filler_stability_{index:03d}", method="fixed_multi_agent", repeat_index=1)
        for index in range(520 - len(stability_rows))
    )
    no_reuse_rows = []
    for repeat in (0, 1, 2):
        for sid in scenario_ids:
            no_reuse_rows.append(
                _result_row(
                    sid,
                    method="adaptive_multi_agent_no_reuse",
                    repeat_index=repeat,
                    turn_id="t1",
                    target_turn=False,
                    tokens=1800,
                    cost=0.02,
                    latency=200,
                )
            )
            no_reuse_rows.append(
                _result_row(
                    sid,
                    method="adaptive_multi_agent_no_reuse",
                    repeat_index=repeat,
                    turn_id="t2",
                    target_turn=True,
                    tokens=1800,
                    cost=0.02,
                    latency=200,
                )
            )

    _write_json(dirs["ctp100_v6"] / "benchmark_results.json", v6_rows)
    _write_json(dirs["ctp100_v6"] / "evaluation_summary.json", _summary(520, 400))
    _write_json(dirs["ctp100_v6"] / "experiment_manifest.json", {"git_commit": "v6", "working_tree_clean": True})
    _write_json(dirs["ctp100_v6"] / "formal_experiment_gate.json", {"status": "passed", "failed_checks": []})

    _write_json(dirs["ctp100_stability"] / "benchmark_results.json", stability_rows)
    _write_json(dirs["ctp100_stability"] / "experiment_manifest.json", {"git_commit": "stability", "working_tree_clean": True})
    _write_json(dirs["ctp100_stability"] / "ctp100_m2_m3_stability_report.json", {"status": "passed", "failed_checks": []})

    _write_json(
        dirs["ctp100_stability_analysis"] / "ctp100_m2_m3_stability_combined_analysis.json",
        {
            "status": "passed",
            "combined_key_results": {
                "stsr": {
                    "m2_mean": 0.8567,
                    "m3_mean": 0.9567,
                    "delta_mean": 0.1,
                    "delta_ci_95": [0.04, 0.1667],
                    "mcnemar_p_value": 0.002,
                }
            },
            "repeat_method_metrics": [],
            "repeat_pair_deltas": [
                {"repeat_index": 0, "m2_stsr": 0.86, "m3_stsr": 0.96, "stsr_delta": 0.1, "stsr_mcnemar_p_value": 0.0063}
            ],
            "aggregate_repeat_stats": {},
            "paper_claim_guidance": {},
        },
    )

    _write_json(dirs["m3_no_reuse"] / "benchmark_results.json", no_reuse_rows)
    _write_json(dirs["m3_no_reuse"] / "evaluation_summary.json", _summary(180, 90))
    _write_json(dirs["m3_no_reuse"] / "experiment_manifest.json", {"git_commit": "noreuse", "working_tree_clean": True})
    _write_json(
        dirs["m3_no_reuse"] / "ctp100_m3_no_reuse_ablation_report.json",
        {
            "status": "passed",
            "failed_checks": [],
            "no_reuse_audit": {
                "reused_agent_violation_count": 0,
                "reused_tool_result_violation_count": 0,
            },
        },
    )

    for key, raw, quality, gate_name, manifest_name in (
        ("ctp30_v1", 60, 60, "sealed_validation_gate.json", "sealed_validation_manifest.json"),
        ("ctp30_v2", 120, 60, "multiturn_sealed_validation_gate.json", "multiturn_sealed_validation_manifest.json"),
    ):
        _write_json(dirs[key] / "evaluation_summary.json", _summary(raw, quality))
        _write_json(dirs[key] / gate_name, {"status": "passed", "failed_checks": []})
        _write_json(dirs[key] / manifest_name, {"git_commit": key, "working_tree_clean": True})

    _write_json(
        dirs["holm"] / "holm_secondary_results.json",
        {
            "status": "passed",
            "metrics": [
                {
                    "metric": "total_tokens",
                    "label": "Total tokens",
                    "raw_p_value": 0.001,
                    "holm_adjusted_p_value": 0.009,
                    "significant_after_correction": True,
                }
            ],
            "primary_stsr_reference": {},
        },
    )
    return dirs


def test_build_final_paper_offline_analysis_passes_and_pairs_ablation(tmp_path: Path) -> None:
    dirs = _make_run_dirs(tmp_path)

    analysis = build_final_paper_offline_analysis(
        ctp100_v6_run_dir=dirs["ctp100_v6"],
        ctp100_stability_run_dir=dirs["ctp100_stability"],
        ctp100_stability_analysis_dir=dirs["ctp100_stability_analysis"],
        m3_no_reuse_run_dir=dirs["m3_no_reuse"],
        ctp30_v1_run_dir=dirs["ctp30_v1"],
        ctp30_v2_run_dir=dirs["ctp30_v2"],
        holm_secondary_dir=dirs["holm"],
    )

    assert analysis["status"] == "passed"
    assert analysis["failed_checks"] == []
    assert analysis["m3_reuse_ablation"]["pair_count"] == 90
    by_metric = {
        row["metric"]: row
        for row in analysis["m3_reuse_ablation"]["metric_rows"]
    }
    assert by_metric["total_tokens"]["delta_full_minus_no_reuse_mean"] == -800.0
    assert by_metric["standardized_estimated_cost"]["delta_full_minus_no_reuse_mean"] == -0.01


def test_write_final_paper_offline_analysis_outputs_artifacts(tmp_path: Path) -> None:
    dirs = _make_run_dirs(tmp_path)
    output = tmp_path / "final_analysis"

    result = write_final_paper_offline_analysis(
        output_dir=output,
        ctp100_v6_run_dir=dirs["ctp100_v6"],
        ctp100_stability_run_dir=dirs["ctp100_stability"],
        ctp100_stability_analysis_dir=dirs["ctp100_stability_analysis"],
        m3_no_reuse_run_dir=dirs["m3_no_reuse"],
        ctp30_v1_run_dir=dirs["ctp30_v1"],
        ctp30_v2_run_dir=dirs["ctp30_v2"],
        holm_secondary_dir=dirs["holm"],
    )

    assert result["status"] == "passed"
    assert (output / "final_paper_offline_analysis.json").exists()
    assert (output / "final_paper_tables.md").exists()
    assert (output / "ctp100_m3_reuse_ablation_pair_metrics.csv").exists()
    manifest = json.loads((output / "final_paper_analysis_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "passed"
    assert manifest["artifact_hashes"]["final_paper_tables.md"]
