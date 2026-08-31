import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.formal_experiment_gate import (
    FORMAL_EXPERIMENT_GATE_SCHEMA_VERSION,
    _failure_classification_summary,
    write_formal_experiment_gate,
)
from app.core.formal_artifact_integrity import build_formal_artifact_integrity_report


def test_formal_experiment_gate_passes_complete_formal_evidence(tmp_path: Path) -> None:
    run_dir = _write_formal_run_dir(tmp_path / "formal-run", independent_cases=1)

    payload = write_formal_experiment_gate(run_dir, min_cases=1)

    assert Path(payload["json"]).exists()
    assert Path(payload["markdown"]).exists()
    gate = payload["gate"]
    assert gate["schema_version"] == FORMAL_EXPERIMENT_GATE_SCHEMA_VERSION
    assert gate["status"] == "passed"
    assert gate["experiment_integrity_passed"] is True
    assert gate["hypothesis_supported"] is True
    assert gate["paper_claims_allowed"] is True
    assert gate["checks"]["formal_preflight_passed"] is True
    assert gate["checks"]["paper_analysis_ready"] is True
    assert gate["checks"]["bpcr_field_present"] is True
    assert gate["checks"]["commit_matches_preflight"] is True
    assert gate["checks"]["artifact_integrity_matches_preflight"] is True
    assert gate["checks"]["preflight_expected_result_count_matches_structure"] is True
    assert gate["checks"]["method_result_grid_complete"] is True
    assert gate["checks"]["metric_values_calculable"] is True
    assert gate["checks"]["artifact_hashes_recorded"] is True
    assert gate["raw_count_summary"]["structure_expected_result_count"] == 4
    assert gate["method_result_grid_summary"]["observed_group_count"] == 1
    assert gate["metric_calculability_summary"]["result_issue_count"] == 0
    assert gate["artifact_index"]["trace_file_count"] == 4
    assert gate["artifact_index"]["referenced_trace_file_count"] == 4
    assert gate["artifact_index"]["unreferenced_trace_file_count"] == 0
    assert len(gate["artifact_index"]["trace_combined_sha256"]) == 64
    manifest_artifact = next(
        item for item in gate["artifact_index"]["files"] if item["key"] == "manifest"
    )
    assert manifest_artifact["sha256"] == hashlib.sha256(
        (run_dir / "experiment_manifest.json").read_bytes()
    ).hexdigest()

    report = Path(payload["markdown"]).read_text(encoding="utf-8")
    assert "Formal experiment final gate" in report
    assert "Raw result completeness" in report
    assert "Metric calculability" in report
    assert "Artifact hashes" in report

    manifest = json.loads((run_dir / "experiment_manifest.json").read_text(encoding="utf-8"))
    assert manifest["formal_experiment_gate"]["status"] == "passed"
    assert manifest["formal_experiment_gate"]["experiment_integrity_passed"] is True
    assert manifest["formal_experiment_gate"]["hypothesis_supported"] is True
    assert manifest["formal_experiment_gate"]["method_result_grid_summary"]["passed"] is True
    assert manifest["formal_experiment_gate"]["artifact_index"] == "see formal_experiment_gate.json"
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


def test_formal_experiment_gate_marks_unreferenced_trace_files(tmp_path: Path) -> None:
    run_dir = _write_formal_run_dir(tmp_path / "formal-run", independent_cases=1)
    orphan = run_dir / "traces" / "interrupted_attempt.jsonl"
    orphan.write_text(json.dumps({"status": "cancelled"}, ensure_ascii=False) + "\n", encoding="utf-8")

    payload = write_formal_experiment_gate(run_dir, min_cases=1)
    artifact_index = payload["gate"]["artifact_index"]

    assert payload["gate_status"] == "passed"
    assert artifact_index["trace_file_count"] == 5
    assert artifact_index["referenced_trace_file_count"] == 4
    assert artifact_index["unreferenced_trace_file_count"] == 1
    assert orphan.as_posix() in artifact_index["unreferenced_trace_files"]


def test_formal_experiment_gate_retains_method_failure_without_blocking_integrity(
    tmp_path: Path,
) -> None:
    run_dir = _write_formal_run_dir(tmp_path / "method-failure-run", independent_cases=1)
    results_path = run_dir / "benchmark_results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    result = results[0]
    result["status"] = "failed"
    result["output"]["execution_status"] = "failed"
    result["output"]["final_answer"] = "The model returned content but violated the schema."
    result["metrics"]["stsr"] = False
    result["metrics"]["evaluation_failed_rule_ids"] = ["G_SCHEMA_VALID"]
    result["run_audit"]["metrics"]["stsr"] = False
    result["run_audit"]["metrics"]["evaluation_failed_rule_ids"] = ["G_SCHEMA_VALID"]
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = write_formal_experiment_gate(run_dir, min_cases=1)
    gate = payload["gate"]

    assert payload["gate_status"] == "passed"
    assert "no_failed_results" not in gate["checks"]
    assert gate["checks"]["all_failures_classified"] is True
    assert gate["checks"]["no_integrity_failures"] is True
    assert gate["failure_classification_summary"]["method_failure_count"] == 1
    assert gate["failure_classification_summary"]["integrity_failure_count"] == 0


def test_failure_classification_marks_worker_bootstrap_failure_as_integrity(
    tmp_path: Path,
) -> None:
    result = {
        "case_id": "worker-error-case",
        "scenario_id": "worker-error-case",
        "turn_id": "t1",
        "method": "adaptive_multi_agent_no_reuse",
        "repeat_index": 0,
        "status": "failed",
        "error": (
            "experiment result worker failed before producing a valid result: "
            "worker exited with code 1: ValueError: method must be one of ..."
        ),
        "trace": {
            "request_id": "worker-error-trace",
            "llm_calls": [],
        },
        "output": {
            "execution_status": "failed",
            "metadata": {
                "result_hard_timeout": {
                    "worker_status": "failed",
                    "triggered": False,
                }
            },
        },
        "metrics": {
            "stsr": False,
            "evaluation_failed_rule_ids": ["G_EXECUTION_STATUS_VALID"],
        },
    }

    summary = _failure_classification_summary(tmp_path, [result])

    assert summary["integrity_failure_count"] == 1
    assert summary["method_failure_count"] == 0
    assert summary["items"][0]["category"] == "integrity_failure"
    assert summary["items"][0]["reason"] == "result_worker_failed_before_valid_result"


def test_formal_experiment_gate_retains_api_failure_with_retry_evidence(
    tmp_path: Path,
) -> None:
    run_dir = _write_formal_run_dir(tmp_path / "api-failure-run", independent_cases=1)
    results_path = run_dir / "benchmark_results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    result = results[1]
    result["status"] = "failed"
    result["output"]["execution_status"] = "failed"
    result["output"]["final_answer"] = ""
    result["metrics"]["stsr"] = False
    result["run_audit"]["metrics"]["stsr"] = False
    trace_path = Path(result["trace_file"])
    trace = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
    trace["llm_calls"][0].update(_terminal_api_failure_retry())
    trace_path.write_text(json.dumps(trace, ensure_ascii=False) + "\n", encoding="utf-8")
    result["trace"] = trace
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = write_formal_experiment_gate(run_dir, min_cases=1)
    gate = payload["gate"]

    assert payload["gate_status"] == "passed"
    assert gate["checks"]["all_api_failures_have_retry_evidence"] is True
    assert gate["api_failure_summary"]["terminal_failure_count"] == 1
    assert gate["api_failure_summary"]["terminal_without_retry_evidence_count"] == 0
    assert gate["failure_classification_summary"]["api_infrastructure_failure_count"] == 1


def test_formal_experiment_gate_blocks_api_failure_without_retry_evidence(
    tmp_path: Path,
) -> None:
    run_dir = _write_formal_run_dir(tmp_path / "api-no-retry-run", independent_cases=1)
    results_path = run_dir / "benchmark_results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    result = results[1]
    result["status"] = "failed"
    result["output"]["execution_status"] = "failed"
    result["metrics"]["stsr"] = False
    result["run_audit"]["metrics"]["stsr"] = False
    trace_path = Path(result["trace_file"])
    trace = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
    trace["llm_calls"][0].update({"success": False, "status": "failed", "error": "HTTP 500"})
    trace_path.write_text(json.dumps(trace, ensure_ascii=False) + "\n", encoding="utf-8")
    result["trace"] = trace
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = write_formal_experiment_gate(run_dir, min_cases=1)
    gate = payload["gate"]

    assert payload["gate_status"] == "failed"
    assert "all_api_failures_have_retry_evidence" in gate["failed_checks"]
    assert gate["api_failure_summary"]["terminal_without_retry_evidence_count"] == 1


def test_formal_experiment_gate_blocks_method_grid_duplicates_even_when_count_matches(
    tmp_path: Path,
) -> None:
    run_dir = _write_formal_run_dir(tmp_path / "duplicate-grid-run", independent_cases=1)
    results_path = run_dir / "benchmark_results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results[1]["method"] = "llm_direct"
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = write_formal_experiment_gate(run_dir, min_cases=1)

    assert payload["gate_status"] == "failed"
    failed = set(payload["gate"]["failed_checks"])
    assert "method_result_grid_complete" in failed
    grid = payload["gate"]["method_result_grid_summary"]
    assert grid["missing_method_group_count"] == 1
    assert grid["duplicate_method_result_count"] == 1
    assert grid["observed_group_count"] == 1


def test_formal_experiment_gate_blocks_uncalculable_core_metrics(
    tmp_path: Path,
) -> None:
    run_dir = _write_formal_run_dir(tmp_path / "bad-metrics-run", independent_cases=1)
    results_path = run_dir / "benchmark_results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results[0]["metrics"]["evaluation_hcsr"] = None
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = write_formal_experiment_gate(run_dir, min_cases=1)

    assert payload["gate_status"] == "failed"
    failed = set(payload["gate"]["failed_checks"])
    assert "metric_values_calculable" in failed
    metrics = payload["gate"]["metric_calculability_summary"]
    assert metrics["result_issue_count"] >= 1
    assert metrics["sample_result_issues"][0]["metric"] == "evaluation_hcsr"


def test_formal_experiment_gate_allows_hcsr_na_when_no_hcsr_rule_applies(
    tmp_path: Path,
) -> None:
    run_dir = _write_formal_run_dir(tmp_path / "hcsr-na-run", independent_cases=1)
    results_path = run_dir / "benchmark_results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results[0]["metrics"]["evaluation_hcsr"] = None
    results[0]["metrics"]["evaluation_hcsr_applicable_count"] = 0
    results[0]["run_audit"]["metrics"]["evaluation_hcsr"] = None
    results[0]["run_audit"]["metrics"]["evaluation_hcsr_applicable_count"] = 0
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = write_formal_experiment_gate(run_dir, min_cases=1)

    assert payload["gate_status"] == "passed"
    assert payload["gate"]["checks"]["metric_values_calculable"] is True
    assert payload["gate"]["metric_calculability_summary"]["result_issue_count"] == 0


def test_formal_experiment_gate_allows_missing_standardized_cost_for_zero_call_row(
    tmp_path: Path,
) -> None:
    run_dir = _write_formal_run_dir(tmp_path / "zero-call-cost-run", independent_cases=1)
    results_path = run_dir / "benchmark_results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    metrics = results[0]["metrics"]
    metrics["llm_call_count"] = 0
    metrics["api_call_count"] = 0
    metrics["total_tokens"] = 0
    metrics["standardized_estimated_cost"] = None
    audit_metrics = results[0]["run_audit"]["metrics"]
    audit_metrics["standardized_estimated_cost"] = None
    results[0]["trace"] = {
        "llm_call_count": 0,
        "api_call_count": 0,
        "total_tokens": 0,
        "llm_calls": [],
        "api_calls": [],
    }
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = write_formal_experiment_gate(run_dir, min_cases=1)

    assert payload["gate_status"] == "passed"
    assert payload["gate"]["checks"]["metric_values_calculable"] is True
    assert payload["gate"]["metric_calculability_summary"]["result_issue_count"] == 0


def test_formal_experiment_gate_blocks_missing_decision_normalization_diagnostics(
    tmp_path: Path,
) -> None:
    run_dir = _write_formal_run_dir(tmp_path / "missing-decision-diagnostics", independent_cases=1)
    summary_path = run_dir / "evaluation_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.pop("decision_normalization")
    for row in summary["methods"].values():
        row.pop("decision_normalization", None)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = write_formal_experiment_gate(run_dir, min_cases=1)

    assert payload["gate_status"] == "failed"
    failed = set(payload["gate"]["failed_checks"])
    assert "decision_normalization_diagnostics_calculable" in failed
    metrics = payload["gate"]["metric_calculability_summary"]
    assert metrics["decision_normalization_issue_count"] >= 1
    assert metrics["sample_decision_normalization_issues"][0]["section"] == "decision_normalization"


def test_formal_experiment_gate_requires_520_raw_results_for_ctp100_protocol(
    tmp_path: Path,
) -> None:
    run_dir = _write_formal_run_dir(
        tmp_path / "ctp100-count-run",
        independent_cases=100,
        preflight_case_count=100,
        preflight_turn_count=130,
        preflight_expected_raw_run_count=4,
    )

    payload = write_formal_experiment_gate(run_dir, min_cases=100)

    assert payload["gate_status"] == "failed"
    failed = set(payload["gate"]["failed_checks"])
    assert "formal_ctp100_raw_result_count_is_520" in failed
    assert "preflight_expected_result_count_matches_structure" in failed
    raw_count = payload["gate"]["raw_count_summary"]
    assert raw_count["requires_ctp100_520_result_count"] is True
    assert raw_count["formal_ctp100_expected_raw_result_count"] == 520
    assert raw_count["structure_expected_result_count"] == 520
    assert raw_count["actual_result_count"] == 4


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
    preflight_case_count: int | None = None,
    preflight_turn_count: int | None = None,
    preflight_expected_raw_run_count: int | None = None,
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
    artifact_integrity = build_formal_artifact_integrity_report()
    benchmark_case_count = preflight_case_count or independent_cases
    benchmark_turn_count = preflight_turn_count or 1
    expected_raw_run_count = (
        preflight_expected_raw_run_count
        if preflight_expected_raw_run_count is not None
        else benchmark_turn_count * len(methods)
    )
    (run_dir / "formal_preflight_report.json").write_text(
        json.dumps(
            {
                "schema_version": "ctp-formal-preflight-v1",
                "status": "passed",
                "benchmark": {
                    "case_count": benchmark_case_count,
                    "total_turn_count": benchmark_turn_count,
                },
                "artifact_integrity": artifact_integrity,
                "run": {
                    "run_id": "unit-formal-run",
                    "methods": methods,
                    "method_count": len(methods),
                    "repeats": 1,
                    "expected_raw_run_count": expected_raw_run_count,
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
                "git_commit": artifact_integrity["git"]["commit"],
                "git": artifact_integrity["git"],
                "formal_artifact_integrity": artifact_integrity,
                "benchmark_structure": {
                    "case_count": benchmark_case_count,
                    "total_turn_count": benchmark_turn_count,
                },
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
        "bpcr": 1.0,
        "bpcr_applicable_count": 1,
        "agent_selection_f1": 1.0,
        "tool_selection_f1": 1.0,
        "agent_set_exact_match": True,
        "tool_set_exact_match": True,
        "llm_call_count": 1,
        "agent_call_count": 1,
        "called_tool_count": 1,
        "total_tokens": tokens,
        "standardized_estimated_cost": round(tokens / 5000, 4),
        "evaluation_failed_rule_ids": [],
    }
    return {
        "case_id": "case_001",
        "method": method,
        "target_turn": True,
        "latency_ms": 100,
        "metrics": metrics,
        "evaluation": {"task_type": "weather_query"},
        "output": {"task_type": "weather_query", "execution_status": "completed"},
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


def _terminal_api_failure_retry() -> dict:
    attempts = [
        {
            "success": False,
            "retryable": True,
            "retry_reason": "http_5xx",
            "error_type": "APIStatusError",
        }
        for _ in range(3)
    ]
    return {
        "success": False,
        "status": "failed",
        "error": "HTTP 500 after retries",
        "retry": {
            "schema_version": "ctp-llm-retry-audit-v1",
            "max_attempts": 3,
            "attempt_count": 3,
            "retry_count": 2,
            "error_count": 3,
            "succeeded": False,
            "attempts": attempts,
        },
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
            "llm_direct": _method_summary(tokens=100, llm_calls=1, decisions=0),
            "single_agent": _method_summary(tokens=100, llm_calls=1, decisions=0),
            "fixed_multi_agent": _method_summary(tokens=100, llm_calls=1, decisions=2),
            "adaptive_multi_agent": _method_summary(tokens=50, llm_calls=1, decisions=1),
        },
        "decision_normalization": _decision_normalization_summary(),
        "paired_statistics": {
            "comparison": "adaptive_multi_agent_vs_fixed_multi_agent",
            "pair_count": 1,
            "metrics": {
                "stsr": _paired_metric(1.0, 1.0, binary=True),
                "evaluation_hcsr": _paired_metric(1.0, 1.0),
                "bpcr": _paired_metric(1.0, 1.0),
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


def _method_summary(*, tokens: int, llm_calls: int, decisions: int) -> dict:
    decision_summary = _decision_normalization_method_summary(decisions=decisions)
    return {
        "case_count": 1,
        "raw_run_count": 1,
        "stsr_rate": 1.0,
        "evaluation_hcsr_mean": 1.0,
        "bpcr_mean": 1.0,
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
        "decision_normalization": decision_summary,
        "agent_decision_total": decision_summary["agent_decision_total"],
        "raw_decision_success_count": decision_summary["raw_decision_success_count"],
        "raw_decision_success_rate": decision_summary["raw_decision_success_rate"],
        "normalizer_recovery_count": decision_summary["normalizer_recovery_count"],
        "normalizer_recovery_rate": decision_summary["normalizer_recovery_rate"],
        "pipeline_completion_rate": decision_summary["pipeline_completion_rate"],
    }


def _decision_normalization_summary() -> dict:
    by_method = {
        "llm_direct": _decision_normalization_method_summary(decisions=0),
        "single_agent": _decision_normalization_method_summary(decisions=0),
        "fixed_multi_agent": _decision_normalization_method_summary(decisions=2),
        "adaptive_multi_agent": _decision_normalization_method_summary(decisions=1),
    }
    return {
        "schema_version": "ctp-decision-normalization-diagnostics-v1",
        "result_count": 4,
        "pipeline_completion_count": 4,
        "pipeline_completion_rate": 1.0,
        "agent_decision_total": 3,
        "raw_decision_success_count": 3,
        "raw_decision_success_rate": 1.0,
        "normalizer_recovery_count": 0,
        "normalizer_recovery_rate": 0.0,
        "missing_agent_decision_audit_result_count": 0,
        "by_method": by_method,
    }


def _decision_normalization_method_summary(*, decisions: int) -> dict:
    return {
        "result_count": 1,
        "pipeline_completion_count": 1,
        "pipeline_completion_rate": 1.0,
        "agent_decision_total": decisions,
        "raw_decision_success_count": decisions,
        "raw_decision_success_rate": 1.0 if decisions else None,
        "normalizer_recovery_count": 0,
        "normalizer_recovery_rate": 0.0 if decisions else None,
        "missing_agent_decision_audit_result_count": 0,
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
