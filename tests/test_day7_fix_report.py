import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.day7_fix_report import (
    DAY7_FIX_REPORT_MD_NAME,
    DAY7_FIX_REPORT_SCHEMA_VERSION,
    DAY7_ISSUE_REPORT_JSON_NAME,
    ISSUE_CATEGORIES,
    build_day7_fix_report,
    write_day7_fix_report,
)


def test_day7_fix_report_classifies_m3_systemic_failures(tmp_path: Path) -> None:
    run_dir = _write_day7_run_dir(tmp_path / "day7-pilot", m3_systemic=True)

    payload = write_day7_fix_report(run_dir)

    assert payload["status"] == "completed"
    assert payload["m3_systemic_failure"] is True
    assert Path(payload["json"]).name == DAY7_ISSUE_REPORT_JSON_NAME
    assert Path(payload["markdown"]).name == DAY7_FIX_REPORT_MD_NAME

    report = json.loads(Path(payload["json"]).read_text(encoding="utf-8"))
    assert report["schema_version"] == DAY7_FIX_REPORT_SCHEMA_VERSION
    assert report["checks"]["three_issue_categories_present"] is True
    assert report["checks"]["each_issue_has_modification"] is True
    assert report["checks"]["each_issue_has_before_after"] is True
    assert report["checks"]["each_issue_has_regression_or_diagnostic_test"] is True
    assert set(report["issues"]) == set(ISSUE_CATEGORIES)
    assert report["runtime_audit"]["consistent_with_manifest"] is True
    assert report["runtime_audit"]["mismatch_count"] == 0

    m3 = report["m3_systemic_failure_analysis"]
    assert m3["systemic_failure"] is True
    assert m3["failed_quality_unit_count"] == 2
    assert m3["quality_unit_count"] == 2
    assert sorted(m3["systemic_task_types"]) == ["trip_planning", "weather_query"]

    method_issues = report["issues"]["method_real_failures"]
    assert method_issues[0]["issue_id"] == "METHOD-001"
    assert method_issues[0]["status"] == "open"
    assert method_issues[0]["regression_tests"]

    manifest = json.loads((run_dir / "experiment_manifest.json").read_text(encoding="utf-8"))
    assert manifest["day7_fix_report"]["status"] == "completed"
    assert manifest["day7_fix_report"]["m3_systemic_failure"] is True
    assert manifest["results"]["day7_issue_report_json"] == payload["json"]
    assert manifest["results"]["day7_fix_report_md"] == payload["markdown"]

    markdown = Path(payload["markdown"]).read_text(encoding="utf-8")
    assert "Day 7 开发期问题清单与最后修正报告" in markdown
    assert "基础设施" not in markdown or "infrastructure_errors" in markdown
    assert "M3 是否存在整类任务系统性失败" in markdown


def test_day7_fix_report_marks_m3_non_systemic_when_quality_passes(tmp_path: Path) -> None:
    run_dir = _write_day7_run_dir(tmp_path / "day7-pilot-pass", m3_systemic=False)

    report = build_day7_fix_report(run_dir)

    assert report["status"] == "completed"
    assert report["m3_systemic_failure_analysis"]["systemic_failure"] is False
    assert report["issues"]["method_real_failures"][0]["status"] == "fixed"
    assert _issue_status(report["issues"]["method_real_failures"], "METHOD-002") == "fixed"
    assert report["issue_counts"]["infrastructure_errors"]["fixed"] >= 3
    assert report["issue_counts"]["experiment_implementation_errors"]["fixed"] >= 4


def test_day7_fix_report_keeps_method_open_when_dev_quality_is_low(tmp_path: Path) -> None:
    pilot_dir = _write_day7_run_dir(tmp_path / "day7-pilot-pass", m3_systemic=False)
    dev_dir = _write_development_run_dir(
        tmp_path / "day7-dev-low-quality",
        m3_stsr=0.3,
        m3_hcsr=0.8088,
        m2_hcsr=0.8781,
    )

    report = build_day7_fix_report(pilot_dir, development_run_dir=dev_dir)

    assert report["m3_systemic_failure_analysis"]["systemic_failure"] is False
    readiness = report["m3_method_readiness"]
    assert readiness["quality_formal_run_blocked"] is True
    assert readiness["formal_run_blocked"] is True
    assert {row["id"] for row in readiness["blocking_reasons"]} >= {
        "development_m3_stsr_below_threshold",
        "development_m3_hcsr_below_m2",
    }
    method_issues = report["issues"]["method_real_failures"]
    assert _issue_status(method_issues, "METHOD-001") == "open"
    assert _issue_status(method_issues, "METHOD-002") == "open"
    assert report["issue_counts"]["method_real_failures"]["open"] >= 2


def test_day7_fix_report_discloses_programmatic_agent_decisions(tmp_path: Path) -> None:
    pilot_dir = _write_day7_run_dir(tmp_path / "day7-pilot-pass", m3_systemic=False)
    dev_dir = _write_development_run_dir(
        tmp_path / "day7-dev-programmatic",
        m3_stsr=0.8,
        m3_hcsr=0.91,
        m2_hcsr=0.88,
        include_programmatic_m3=True,
    )

    report = build_day7_fix_report(pilot_dir, development_run_dir=dev_dir)

    assistance = report["agent_decision_assistance_analysis"]["development"]["methods"][
        "adaptive_multi_agent"
    ]
    assert assistance["agent_decision_output_count"] == 3
    assert assistance["deterministic_normalizer_count"] == 1
    assert assistance["reused_or_synthetic_decision_count"] == 1
    assert assistance["programmatic_decision_count"] == 2
    assert assistance["programmatic_decision_rate"] == 0.6667
    assert report["m3_method_readiness"]["ablation_required"] is True
    assert report["m3_method_readiness"]["formal_run_blocked"] is True
    assert _issue_status(report["issues"]["method_real_failures"], "METHOD-003") == "open"


def test_day7_fix_report_closes_normalizer_issue_when_ablation_is_available(
    tmp_path: Path,
) -> None:
    pilot_dir = _write_day7_run_dir(tmp_path / "day7-pilot-pass", m3_systemic=False)
    dev_dir = _write_development_run_dir(
        tmp_path / "day7-dev-programmatic",
        m3_stsr=0.8,
        m3_hcsr=0.91,
        m2_hcsr=0.88,
        include_programmatic_m3=True,
    )
    ablation_dir = _write_m3_ablation_report(tmp_path / "day7-m3-ablation")

    report = build_day7_fix_report(
        pilot_dir,
        development_run_dir=dev_dir,
        m3_ablation_run_dir=ablation_dir,
    )

    readiness = report["m3_method_readiness"]
    assert readiness["ablation_closed"] is True
    assert readiness["ablation_required"] is False
    assert readiness["formal_run_blocked"] is False
    assert report["m3_no_decision_normalizer_ablation"]["status"] == "passed"
    assert _issue_status(report["issues"]["method_real_failures"], "METHOD-003") == "fixed"


def test_report_day7_fixes_cli_writes_payload(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    from experiments import report_day7_fixes

    run_dir = _write_day7_run_dir(tmp_path / "cli-run", m3_systemic=True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "report_day7_fixes.py",
            "--run-dir",
            str(run_dir),
            "--strict",
        ],
    )

    assert report_day7_fixes.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert payload["m3_systemic_failure"] is True
    assert Path(payload["json"]).exists()
    assert Path(payload["markdown"]).exists()


def _write_day7_run_dir(run_dir: Path, *, m3_systemic: bool) -> Path:
    run_dir.mkdir(parents=True)
    methods = [
        "llm_direct",
        "single_agent",
        "fixed_multi_agent",
        "adaptive_multi_agent",
    ]
    tasks = ["trip_planning", "weather_query"]
    results = []
    for method in methods:
        for task in tasks:
            failed = method == "adaptive_multi_agent" and m3_systemic
            results.append(_result(method, task, failed=failed))
    (run_dir / "benchmark_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "benchmark_results.csv").write_text(
        "case_id,method\n" + "\n".join(f"{row['case_id']},{row['method']}" for row in results),
        encoding="utf-8-sig",
    )
    (run_dir / "evaluation_summary.json").write_text(
        json.dumps(
            {
                "schema_version": "ctp-evaluation-summary-v1",
                "raw_run_count": len(results),
                "quality_result_count": len(results),
                "independent_case_count": len(tasks),
                "methods": {
                    method: {
                        "case_count": len(tasks),
                        "raw_run_count": len(tasks),
                        "stsr_rate": 0.0
                        if method == "adaptive_multi_agent" and m3_systemic
                        else 1.0,
                        "top_failed_rules": [
                            {"rule_id": "G_TASK_TYPE_MATCH", "count": 1},
                            {"rule_id": "H_TOOL_EVIDENCE", "count": 1},
                        ]
                        if method == "adaptive_multi_agent" and m3_systemic
                        else [],
                        "top_tool_failure_types": [],
                    }
                    for method in methods
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_dir / "day7_pilot_gate.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "expected_result_count": len(results),
                "actual_result_count": len(results),
                "pilot_structure": {
                    "case_count": 2,
                    "total_turn_count": 2,
                    "selected_case_ids": tasks,
                },
                "trace_summary": {
                    "llm_call_count": len(results),
                    "retry_count": 0,
                    "mock_llm_call_count": 0,
                    "fallback_llm_call_count": 0,
                },
                "result_status_summary": {
                    "status_counts": {"failed": 2, "completed": len(results) - 2}
                    if m3_systemic
                    else {"completed": len(results)},
                    "quality_gated": False,
                    "error_count": 0,
                },
                "quality_policy": {"quality_threshold_enforced": False},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_dir / "experiment_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "day7-unit",
                "dataset_id": "unit-smoke",
                "dataset_version": "2026-07-31-zh",
                "model": "gpt-5-mini",
                "runtime_config": {
                    "model": "gpt-5-mini",
                    "temperature": 0.0,
                    "max_tokens": 1024,
                    "timeout_seconds": 60,
                    "retry_max_attempts": 3,
                    "strict_mode": True,
                    "cache_disabled": True,
                },
                "results": {},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_dir / "paper_tables.md").write_text("# table\n", encoding="utf-8")
    (run_dir / "traces").mkdir()
    return run_dir


def _write_development_run_dir(
    run_dir: Path,
    *,
    m3_stsr: float,
    m3_hcsr: float,
    m2_hcsr: float,
    include_programmatic_m3: bool = False,
) -> Path:
    run_dir.mkdir(parents=True)
    m3_outputs = (
        {
            "attraction": _agent_output("attraction", source="deterministic_evidence_normalizer"),
            "weather": _agent_output("weather", source="llm"),
            "itinerary": _agent_output("itinerary", reused=True),
        }
        if include_programmatic_m3
        else {}
    )
    results = [
        _result(
            "adaptive_multi_agent",
            "trip_planning",
            failed=m3_stsr < 1.0,
            agent_outputs=m3_outputs,
        ),
        _result("fixed_multi_agent", "trip_planning", failed=False),
    ]
    (run_dir / "benchmark_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "evaluation_summary.json").write_text(
        json.dumps(
            {
                "schema_version": "ctp-evaluation-summary-v1",
                "raw_run_count": len(results),
                "quality_result_count": len(results),
                "methods": {
                    "adaptive_multi_agent": {
                        "case_count": 20,
                        "stsr_rate": m3_stsr,
                        "evaluation_hcsr_mean": m3_hcsr,
                        "agent_set_exact_match_mean": 0.7,
                        "tool_set_exact_match_mean": 0.7,
                        "successful_case_count": int(round(m3_stsr * 20)),
                        "top_failed_rules": [
                            {"rule_id": "G_TASK_TYPE_MATCH", "count": 7},
                            {"rule_id": "S_AGENT_SET_MATCH", "count": 6},
                            {"rule_id": "S_TOOL_SET_MATCH", "count": 6},
                        ],
                    },
                    "fixed_multi_agent": {
                        "case_count": 20,
                        "stsr_rate": 0.6,
                        "evaluation_hcsr_mean": m2_hcsr,
                        "agent_set_exact_match_mean": 0.8,
                        "tool_set_exact_match_mean": 0.8,
                        "successful_case_count": 12,
                        "top_failed_rules": [],
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_dir / "experiment_manifest.json").write_text(
        json.dumps({"run_id": "day7-dev-unit"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return run_dir


def _write_m3_ablation_report(run_dir: Path) -> Path:
    run_dir.mkdir(parents=True)
    (run_dir / "day7_m3_no_decision_normalizer_ablation.json").write_text(
        json.dumps(
            {
                "schema_version": "ctp-day7-m3-no-decision-normalizer-ablation-v1",
                "status": "passed",
                "run_dir": run_dir.as_posix(),
                "controlled_change": {
                    "name": "M3-no-decision-normalizer",
                    "method": "adaptive_multi_agent",
                    "decision_normalizer_enabled": False,
                },
                "summary": {
                    "ablation_closed": True,
                    "agent_decision_output_count": 3,
                    "deterministic_normalizer_count": 0,
                    "normalizer_skipped_count": 2,
                    "invalid_llm_decision_count": 2,
                    "normalizer_enabled_true_count": 0,
                },
                "checks": {
                    "manifest_decision_normalizer_disabled": True,
                    "deterministic_normalizer_not_used": True,
                    "agent_outputs_do_not_enable_normalizer": True,
                },
                "failed_checks": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return run_dir


def _result(
    method: str,
    task: str,
    *,
    failed: bool,
    agent_outputs: dict | None = None,
) -> dict:
    return _result_with_agent_outputs(
        method,
        task,
        failed=failed,
        agent_outputs=agent_outputs or {},
    )


def _result_with_agent_outputs(
    method: str,
    task: str,
    *,
    failed: bool,
    agent_outputs: dict,
) -> dict:
    return {
        "case_id": f"{task}_{method}",
        "method": method,
        "target_turn": True,
        "status": "failed" if failed else "completed",
        "evaluation": {"task_type": task},
        "output": {
            "task_type": task,
            "agent_outputs": agent_outputs,
            "metadata": {
                "agent_outputs": agent_outputs,
                "structured_llm_output": {
                    "failure_reason": "structured LLM output is empty or not text"
                    if failed
                    else None
                }
            },
        },
        "metrics": {
            "stsr": not failed,
            "evaluation_failed_rule_ids": [
                "G_TASK_TYPE_MATCH",
                "H_TOOL_EVIDENCE",
            ]
            if failed
            else [],
        },
        "trace": {
            "llm_calls": [
                {
                    "model": "gpt-5-mini",
                    "request_options": {
                        "model": "gpt-5-mini",
                        "temperature": 0.0,
                        "max_tokens": 1024,
                        "timeout_seconds": 60,
                        "retry_max_attempts": 3,
                    },
                    "retry": {
                        "max_attempts": 3,
                        "attempt_count": 1,
                        "retry_count": 0,
                        "error_count": 0,
                    },
                    "mock": False,
                    "mock_used": False,
                    "fallback": False,
                    "fallback_used": False,
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                }
            ]
        },
    }


def _agent_output(agent_name: str, *, source: str = "llm", reused: bool = False) -> dict:
    if reused:
        return {
            "agent_name": agent_name,
            "status": "reused",
            "reused": True,
            "decision_source": "",
            "decision_fallback_used": False,
            "decision_parse_status": "not_available",
            "decision_validation_status": "not_available",
            "llm_decision_parse_status": "not_available",
            "llm_decision_validation_status": "not_available",
        }
    deterministic = source == "deterministic_evidence_normalizer"
    return {
        "agent_name": agent_name,
        "status": "completed",
        "reused": False,
        "decision_source": source,
        "decision_fallback_used": deterministic,
        "decision_normalizer_version": "ctp-research-agent-decision-normalizer-v1"
        if deterministic
        else None,
        "decision_parse_status": "passed",
        "decision_validation_status": "passed",
        "llm_decision_parse_status": "failed" if deterministic else "passed",
        "llm_decision_validation_status": "failed" if deterministic else "passed",
    }


def _issue_status(issues: list[dict], issue_id: str) -> str:
    for issue in issues:
        if issue.get("issue_id") == issue_id:
            return str(issue.get("status"))
    raise AssertionError(f"missing issue {issue_id}")
