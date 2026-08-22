import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.formal_experiment_gate import write_formal_experiment_gate
from app.core.paper_result_pack import (
    PAPER_RESULT_PACK_SCHEMA_VERSION,
    build_paper_result_pack,
    write_paper_result_pack,
)
from app.core.formal_artifact_integrity import build_formal_artifact_integrity_report


def test_paper_result_pack_writes_rq_tables_and_manifest(tmp_path: Path) -> None:
    run_dir = _write_formal_run_dir(tmp_path / "formal-run", independent_cases=1)
    write_formal_experiment_gate(run_dir, min_cases=1)

    payload = write_paper_result_pack(run_dir, profile="formal", min_cases=1)

    assert Path(payload["json"]).exists()
    assert Path(payload["markdown"]).exists()
    pack = payload["pack"]
    assert pack["schema_version"] == PAPER_RESULT_PACK_SCHEMA_VERSION
    assert pack["readiness"]["paper_claims_allowed"] is True
    assert [item["rq_id"] for item in pack["research_questions"]] == ["RQ1", "RQ2", "RQ3"]
    assert pack["tables"]["rq3_efficiency"]["rows"][3]["method"] == "M3 Proposed"
    assert pack["tables"]["m3_m2_paired"]["rows"][8]["metric"] == "total_tokens"
    assert pack["artifact_evidence"]["trace_file_count"] == 4

    markdown = Path(payload["markdown"]).read_text(encoding="utf-8")
    assert "Paper result pack" in markdown
    assert "RQ3 efficiency" in markdown
    assert "Copy-ready paper text" in markdown

    manifest = json.loads((run_dir / "experiment_manifest.json").read_text(encoding="utf-8"))
    assert manifest["paper_result_pack"]["paper_claims_allowed"] is True
    assert manifest["results"]["paper_result_pack_json"] == payload["json"]
    assert manifest["results"]["paper_result_pack_md"] == payload["markdown"]


def test_paper_result_pack_blocks_formal_claims_without_final_gate(tmp_path: Path) -> None:
    run_dir = _write_formal_run_dir(tmp_path / "no-gate-run", independent_cases=1)

    pack = build_paper_result_pack(run_dir, profile="formal", min_cases=1)

    assert pack["readiness"]["paper_claims_allowed"] is False
    assert "formal_experiment_gate_missing" in pack["readiness"]["failed_checks"]
    assert pack["copy_ready_text"]["result_paragraph"].startswith("当前实验结果尚未通过")


def test_export_paper_result_pack_cli_writes_payload(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    from experiments import export_paper_result_pack

    run_dir = _write_formal_run_dir(tmp_path / "cli-run", independent_cases=1)
    write_formal_experiment_gate(run_dir, min_cases=1)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "export_paper_result_pack.py",
            "--run-dir",
            str(run_dir),
            "--profile",
            "formal",
            "--min-cases",
            "1",
            "--strict",
        ],
    )

    assert export_paper_result_pack.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["paper_claims_allowed"] is True
    assert Path(payload["json"]).exists()
    assert Path(payload["markdown"]).exists()


def _write_formal_run_dir(run_dir: Path, *, independent_cases: int) -> Path:
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
        trace = _trace(method, tokens=tokens)
        trace_path.write_text(json.dumps(trace, ensure_ascii=False) + "\n", encoding="utf-8")
        results.append(_result(method, tokens=tokens, trace=trace, trace_path=trace_path))

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
    git_commit = artifact_integrity["git"]["commit"]
    benchmark_case_count = independent_cases
    benchmark_turn_count = 1
    (run_dir / "formal_preflight_report.json").write_text(
        json.dumps(
            {
                "schema_version": "ctp-formal-preflight-v1",
                "status": "passed",
                "benchmark": {
                    "case_count": benchmark_case_count,
                    "total_turn_count": benchmark_turn_count,
                },
                "run": {
                    "run_id": "unit-formal-run",
                    "methods": methods,
                    "method_count": len(methods),
                    "repeats": 1,
                    "expected_raw_run_count": 4,
                },
                "artifact_integrity": artifact_integrity,
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
                "git_commit": git_commit,
                "git": {"commit": git_commit},
                "dataset_id": "unit-formal-dataset",
                "dataset_version": "v1",
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
                "formal_artifact_integrity": artifact_integrity,
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


def _result(method: str, *, tokens: int, trace: dict, trace_path: Path) -> dict:
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
        "execution_status": "completed",
        "run_audit": {"schema_version": "ctp-run-audit-v1", "metrics": metrics},
        "trace": trace,
        "trace_file": trace_path.as_posix(),
    }


def _trace(method: str, *, tokens: int) -> dict:
    return {
        "method": method,
        "user_message": None,
        "agent_call_count": 1,
        "tool_call_count": 1,
        "llm_calls": [
            {
                "mock": False,
                "mock_used": False,
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
            "llm_direct": _method_summary(tokens=100, agent_calls=0, tool_calls=0, decisions=0),
            "single_agent": _method_summary(tokens=100, agent_calls=1, tool_calls=1, decisions=0),
            "fixed_multi_agent": _method_summary(tokens=100, agent_calls=2, tool_calls=2, decisions=2),
            "adaptive_multi_agent": _method_summary(tokens=50, agent_calls=1, tool_calls=1, decisions=1),
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


def _method_summary(*, tokens: int, agent_calls: int, tool_calls: int, decisions: int) -> dict:
    decision_summary = _decision_normalization_method_summary(decisions=decisions)
    return {
        "case_count": 1,
        "raw_run_count": 1,
        "stsr_rate": 1.0,
        "evaluation_hcsr_mean": 1.0,
        "bpcr_mean": 1.0,
        "agent_selection_f1_mean": 1.0,
        "tool_selection_f1_mean": 1.0,
        "llm_call_count_mean": 1,
        "agent_call_count_mean": agent_calls,
        "called_tool_count_mean": tool_calls,
        "tool_call_count_mean": tool_calls,
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
