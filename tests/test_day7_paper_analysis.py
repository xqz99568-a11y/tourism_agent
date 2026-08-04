import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.experiment_paper_analysis import (
    PAPER_ANALYSIS_SCHEMA_VERSION,
    build_experiment_paper_analysis,
    write_experiment_paper_analysis,
)


def test_paper_analysis_marks_small_formal_run_ready_when_threshold_is_met(tmp_path: Path) -> None:
    run_dir = _write_run_dir(tmp_path / "formal-run", independent_cases=1)

    payload = write_experiment_paper_analysis(
        run_dir,
        profile="formal",
        min_cases=1,
    )

    assert Path(payload["json"]).exists()
    assert Path(payload["markdown"]).exists()
    analysis = payload["analysis"]
    assert analysis["schema_version"] == PAPER_ANALYSIS_SCHEMA_VERSION
    assert analysis["profile"] == "formal"
    assert analysis["readiness"]["status"] == "ready"
    assert analysis["readiness"]["paper_claims_allowed"] is True
    assert analysis["m3_vs_m2"]["metrics"]["total_tokens"]["relative_saving_rate"] == 0.5
    assert analysis["m3_vs_m2"]["metrics"]["llm_call_count"]["delta_mean"] == -1.0

    markdown = Path(payload["markdown"]).read_text(encoding="utf-8")
    assert "M3 vs M2 paired comparison" in markdown
    assert "Method comparison" in markdown

    manifest = json.loads((run_dir / "experiment_manifest.json").read_text(encoding="utf-8"))
    assert manifest["paper_analysis"]["status"] == "ready"
    assert manifest["results"]["paper_analysis_json"] == payload["json"]
    assert manifest["results"]["paper_analysis_md"] == payload["markdown"]


def test_paper_analysis_auto_detects_day7_pilot_as_analysis_only(tmp_path: Path) -> None:
    run_dir = _write_run_dir(tmp_path / "pilot-run", independent_cases=1)
    (run_dir / "day7_pilot_gate.json").write_text(
        json.dumps({"status": "passed", "expected_result_count": 4}, ensure_ascii=False),
        encoding="utf-8",
    )
    manifest = json.loads((run_dir / "experiment_manifest.json").read_text(encoding="utf-8"))
    manifest["day7_pilot"] = {"status": "passed"}
    (run_dir / "experiment_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )

    analysis = build_experiment_paper_analysis(run_dir, profile="auto")

    assert analysis["profile"] == "pilot"
    assert analysis["readiness"]["status"] == "analysis_only"
    assert analysis["readiness"]["paper_claims_allowed"] is False
    assert analysis["paper_use_policy"]["forbidden_uses"] == [
        "formal paper conclusion",
        "claiming model superiority",
        "reporting pilot scores as final experiment results",
    ]


def test_paper_analysis_blocks_formal_claims_on_mock_or_small_sample(tmp_path: Path) -> None:
    run_dir = _write_run_dir(tmp_path / "not-ready", independent_cases=1, mock=True)

    analysis = build_experiment_paper_analysis(
        run_dir,
        profile="formal",
        min_cases=100,
    )

    assert analysis["readiness"]["status"] == "not_ready"
    assert analysis["readiness"]["paper_claims_allowed"] is False
    assert "minimum_case_count_met" in analysis["readiness"]["failed_checks"]
    assert "no_mock_llm" in analysis["readiness"]["failed_checks"]


def test_analyze_experiment_run_cli_writes_payload(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    from experiments import analyze_experiment_run

    run_dir = _write_run_dir(tmp_path / "cli-run", independent_cases=1)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "analyze_experiment_run.py",
            "--run-dir",
            str(run_dir),
            "--profile",
            "formal",
            "--min-cases",
            "1",
        ],
    )

    assert analyze_experiment_run.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["readiness_status"] == "ready"
    assert payload["paper_claims_allowed"] is True
    assert Path(payload["json"]).exists()
    assert Path(payload["markdown"]).exists()


def _write_run_dir(
    run_dir: Path,
    *,
    independent_cases: int,
    mock: bool = False,
) -> Path:
    run_dir.mkdir(parents=True)
    methods = [
        "llm_direct",
        "single_agent",
        "fixed_multi_agent",
        "adaptive_multi_agent",
    ]
    results = [
        _result(method, tokens=50 if method == "adaptive_multi_agent" else 100, mock=mock)
        for method in methods
    ]
    (run_dir / "benchmark_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_csv(run_dir / "benchmark_results.csv", results)
    (run_dir / "evaluation_summary.json").write_text(
        json.dumps(
            _summary(independent_cases=independent_cases),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_dir / "paper_tables.md").write_text("# Paper Result Tables\n", encoding="utf-8")
    (run_dir / "experiment_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "unit-run",
                "dataset_id": "unit-dataset",
                "dataset_version": "v1",
                "methods": methods,
                "repeats": 1,
                "runtime_config": {
                    "strict_mode": True,
                    "cache_disabled": True,
                },
                "model_config_name": "unit-model-config",
                "model": "unit-model",
                "results": {
                    "csv": (run_dir / "benchmark_results.csv").as_posix(),
                    "json": (run_dir / "benchmark_results.json").as_posix(),
                    "summary": (run_dir / "evaluation_summary.json").as_posix(),
                    "paper_tables": (run_dir / "paper_tables.md").as_posix(),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_dir / "traces").mkdir()
    return run_dir


def _result(method: str, *, tokens: int, mock: bool) -> dict:
    return {
        "case_id": "case_001",
        "method": method,
        "target_turn": True,
        "latency_ms": 100,
        "metrics": {
            "stsr": True,
            "evaluation_hcsr": 1.0,
            "agent_selection_f1": 1.0,
            "tool_selection_f1": 1.0,
            "evaluation_failed_rule_ids": [],
        },
        "evaluation": {"task_type": "weather_query"},
        "output": {"task_type": "weather_query"},
        "trace": {
            "user_message": None,
            "agent_call_count": 1 if method == "adaptive_multi_agent" else 2,
            "tool_call_count": 1,
            "llm_calls": [
                {
                    "mock": mock,
                    "mock_used": mock,
                    "fallback": False,
                    "fallback_used": False,
                    "retry_attempt_count": 1,
                    "retry_count": 0,
                    "usage": {
                        "prompt_tokens": tokens - 10,
                        "completion_tokens": 10,
                        "total_tokens": tokens,
                    },
                    "standardized_estimated_cost": 0.01,
                }
            ],
        },
    }


def _write_csv(path: Path, results: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case_id", "method"])
        writer.writeheader()
        for result in results:
            writer.writerow({"case_id": result["case_id"], "method": result["method"]})


def _summary(*, independent_cases: int) -> dict:
    method_rows = {
        "llm_direct": _method_summary(tokens=100, llm_calls=2, agent_calls=0, tool_calls=0),
        "single_agent": _method_summary(tokens=100, llm_calls=2, agent_calls=1, tool_calls=1),
        "fixed_multi_agent": _method_summary(tokens=100, llm_calls=2, agent_calls=2, tool_calls=2),
        "adaptive_multi_agent": _method_summary(tokens=50, llm_calls=1, agent_calls=1, tool_calls=1),
    }
    return {
        "schema_version": "ctp-evaluation-summary-v1",
        "result_count": 4,
        "raw_run_count": 4,
        "quality_result_count": 4,
        "unique_case_count": independent_cases,
        "independent_case_count": independent_cases,
        "methods": method_rows,
        "paired_statistics": {
            "comparison": "adaptive_multi_agent_vs_fixed_multi_agent",
            "pair_count": 1,
            "metrics": {
                "stsr": _paired_metric(1.0, 1.0, binary=True),
                "evaluation_hcsr": _paired_metric(1.0, 1.0),
                "agent_selection_f1": _paired_metric(1.0, 1.0),
                "tool_selection_f1": _paired_metric(1.0, 1.0),
                "llm_call_count": _paired_metric(1.0, 2.0),
                "agent_call_count": _paired_metric(1.0, 2.0),
                "tool_call_count": _paired_metric(1.0, 2.0),
                "total_tokens": _paired_metric(50.0, 100.0),
                "standardized_estimated_cost": _paired_metric(0.01, 0.02),
                "latency_ms": _paired_metric(80.0, 100.0),
            },
        },
    }


def _method_summary(
    *,
    tokens: int,
    llm_calls: int,
    agent_calls: int,
    tool_calls: int,
) -> dict:
    return {
        "case_count": 1,
        "raw_run_count": 1,
        "stsr_rate": 1.0,
        "evaluation_hcsr_mean": 1.0,
        "agent_selection_f1_mean": 1.0,
        "tool_selection_f1_mean": 1.0,
        "llm_call_count_mean": llm_calls,
        "agent_call_count_mean": agent_calls,
        "called_tool_count_mean": tool_calls,
        "tool_call_count_mean": tool_calls,
        "total_tokens_mean": tokens,
        "standardized_estimated_cost_mean": round(tokens / 5000, 4),
        "latency_ms_mean": 100,
        "top_failed_rules": [],
        "top_tool_failure_types": [],
    }


def _paired_metric(m3: float, m2: float, *, binary: bool = False) -> dict:
    delta = round(m3 - m2, 4)
    payload = {
        "pair_count": 1,
        "m3": {"mean": m3},
        "m2": {"mean": m2},
        "delta": {
            "mean": delta,
            "median": delta,
            "iqr": [delta, delta],
            "bootstrap_ci_95": [delta, delta],
        },
    }
    if binary:
        payload["mcnemar"] = {"p_value": 1.0}
    else:
        payload["wilcoxon_signed_rank"] = {"p_value": 1.0}
    return payload
