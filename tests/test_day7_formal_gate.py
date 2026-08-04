import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.formal_experiment_gate import (
    FORMAL_EXPERIMENT_GATE_SCHEMA_VERSION,
    write_formal_experiment_gate,
)


def test_formal_experiment_gate_passes_complete_formal_evidence(tmp_path: Path) -> None:
    run_dir = _write_formal_run_dir(tmp_path / "formal-run", independent_cases=1)

    payload = write_formal_experiment_gate(run_dir, min_cases=1)

    assert Path(payload["json"]).exists()
    assert Path(payload["markdown"]).exists()
    gate = payload["gate"]
    assert gate["schema_version"] == FORMAL_EXPERIMENT_GATE_SCHEMA_VERSION
    assert gate["status"] == "passed"
    assert gate["paper_claims_allowed"] is True
    assert gate["checks"]["formal_preflight_passed"] is True
    assert gate["checks"]["paper_analysis_ready"] is True
    assert gate["checks"]["artifact_hashes_recorded"] is True
    assert gate["artifact_index"]["trace_file_count"] == 4
    assert len(gate["artifact_index"]["trace_combined_sha256"]) == 64

    report = Path(payload["markdown"]).read_text(encoding="utf-8")
    assert "Formal experiment final gate" in report
    assert "Artifact hashes" in report

    manifest = json.loads((run_dir / "experiment_manifest.json").read_text(encoding="utf-8"))
    assert manifest["formal_experiment_gate"]["status"] == "passed"
    assert manifest["results"]["formal_experiment_gate"] == payload["json"]
    assert manifest["results"]["formal_experiment_report"] == payload["markdown"]


def test_formal_experiment_gate_blocks_small_mock_run(tmp_path: Path) -> None:
    run_dir = _write_formal_run_dir(tmp_path / "bad-run", independent_cases=1, mock=True)

    payload = write_formal_experiment_gate(run_dir, min_cases=100)

    assert payload["gate_status"] == "failed"
    failed = set(payload["gate"]["failed_checks"])
    assert "minimum_case_count_met" in failed
    assert "paper_analysis_ready" in failed
    assert "paper_claims_allowed_by_analysis" in failed
    assert "no_mock_llm" in failed
    assert payload["paper_claims_allowed"] is False


def test_finalize_formal_experiment_cli_writes_gate(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    from experiments import finalize_formal_experiment

    run_dir = _write_formal_run_dir(tmp_path / "cli-run", independent_cases=1)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "finalize_formal_experiment.py",
            "--run-dir",
            str(run_dir),
            "--min-cases",
            "1",
            "--strict",
        ],
    )

    assert finalize_formal_experiment.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["gate_status"] == "passed"
    assert payload["paper_claims_allowed"] is True
    assert Path(payload["gate"]).exists()
    assert Path(payload["report"]).exists()


def _write_formal_run_dir(
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
    trace_dir = run_dir / "traces"
    trace_dir.mkdir()
    results = []
    for method in methods:
        tokens = 50 if method == "adaptive_multi_agent" else 100
        trace_path = trace_dir / f"case_001_{method}.jsonl"
        trace = _trace(method, tokens=tokens, mock=mock)
        trace_path.write_text(json.dumps(trace, ensure_ascii=False) + "\n", encoding="utf-8")
        results.append(_result(method, tokens=tokens, trace=trace, trace_path=trace_path, mock=mock))

    (run_dir / "benchmark_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_csv(run_dir / "benchmark_results.csv", results)
    (run_dir / "evaluation_summary.json").write_text(
        json.dumps(_summary(independent_cases=independent_cases), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "paper_tables.md").write_text("# Paper Result Tables\n", encoding="utf-8")
    (run_dir / "formal_preflight_report.json").write_text(
        json.dumps(
            {
                "schema_version": "ctp-formal-preflight-v1",
                "status": "passed",
                "run": {
                    "run_id": "unit-formal-run",
                    "expected_raw_run_count": 4,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_dir / "experiment_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "unit-formal-run",
                "dataset_id": "unit-formal-dataset",
                "dataset_version": "v1",
                "methods": methods,
                "repeats": 1,
                "runtime_config": {
                    "strict_mode": True,
                    "cache_disabled": True,
                    "deterministic_research_final_answer": True,
                },
                "method_fairness_contract": {
                    "schema_version": "ctp-method-fairness-contract-v1",
                    "contract_sha256": "a" * 64,
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
    return run_dir


def _result(
    method: str,
    *,
    tokens: int,
    trace: dict,
    trace_path: Path,
    mock: bool,
) -> dict:
    metrics = {
        "stsr": True,
        "evaluation_hcsr": 1.0,
        "agent_selection_f1": 1.0,
        "tool_selection_f1": 1.0,
        "agent_set_exact_match": True,
        "tool_set_exact_match": True,
        "llm_call_count": 1,
        "agent_call_count": 1,
        "called_tool_count": 1,
        "total_tokens": tokens,
        "evaluation_failed_rule_ids": [],
    }
    return {
        "case_id": "case_001",
        "method": method,
        "target_turn": True,
        "latency_ms": 100,
        "metrics": metrics,
        "evaluation": {"task_type": "weather_query"},
        "output": {"task_type": "weather_query"},
        "run_audit": {
            "schema_version": "ctp-run-audit-v1",
            "metrics": metrics,
        },
        "trace": trace,
        "trace_file": trace_path.as_posix(),
        "mock": mock,
    }


def _trace(method: str, *, tokens: int, mock: bool) -> dict:
    return {
        "method": method,
        "user_message": None,
        "agent_call_count": 1,
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
                "standardized_estimated_cost": round(tokens / 5000, 4),
            }
        ],
    }


def _write_csv(path: Path, results: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case_id", "method"])
        writer.writeheader()
        for result in results:
            writer.writerow({"case_id": result["case_id"], "method": result["method"]})


def _summary(*, independent_cases: int) -> dict:
    return {
        "schema_version": "ctp-evaluation-summary-v1",
        "result_count": 4,
        "raw_run_count": 4,
        "quality_result_count": 4,
        "unique_case_count": independent_cases,
        "independent_case_count": independent_cases,
        "methods": {
            "llm_direct": _method_summary(tokens=100, llm_calls=1),
            "single_agent": _method_summary(tokens=100, llm_calls=1),
            "fixed_multi_agent": _method_summary(tokens=100, llm_calls=1),
            "adaptive_multi_agent": _method_summary(tokens=50, llm_calls=1),
        },
        "paired_statistics": {
            "comparison": "adaptive_multi_agent_vs_fixed_multi_agent",
            "pair_count": 1,
            "metrics": {
                "stsr": _paired_metric(1.0, 1.0, binary=True),
                "evaluation_hcsr": _paired_metric(1.0, 1.0),
                "agent_selection_f1": _paired_metric(1.0, 1.0),
                "tool_selection_f1": _paired_metric(1.0, 1.0),
                "llm_call_count": _paired_metric(1.0, 1.0),
                "agent_call_count": _paired_metric(1.0, 2.0),
                "tool_call_count": _paired_metric(1.0, 2.0),
                "total_tokens": _paired_metric(50.0, 100.0),
                "standardized_estimated_cost": _paired_metric(0.01, 0.02),
                "latency_ms": _paired_metric(80.0, 100.0),
            },
        },
    }


def _method_summary(*, tokens: int, llm_calls: int) -> dict:
    return {
        "case_count": 1,
        "raw_run_count": 1,
        "stsr_rate": 1.0,
        "evaluation_hcsr_mean": 1.0,
        "agent_selection_f1_mean": 1.0,
        "tool_selection_f1_mean": 1.0,
        "llm_call_count_mean": llm_calls,
        "agent_call_count_mean": 1,
        "called_tool_count_mean": 1,
        "tool_call_count_mean": 1,
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
