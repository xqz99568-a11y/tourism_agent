import json
from pathlib import Path

from app.core.final_artifact_index import (
    FINAL_ARTIFACT_INDEX_NAME,
    validate_final_artifact_index,
    write_final_artifact_index,
)
from experiments.run_ctp30_sealed_validation import (
    CTP30_EXPECTED_RESULTS,
    CTP30_SEALED_METHODS,
    SEALED_MANIFEST_NAME,
    _sealed_artifact_files,
    build_sealed_validation_preflight,
    build_sealed_validation_report,
)


def test_ctp30_preflight_accepts_30_cases_and_m2_m3_only(tmp_path: Path) -> None:
    benchmark = tmp_path / "ctp30.json"
    benchmark.write_text(
        json.dumps(_ctp30_benchmark(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    report = build_sealed_validation_preflight(
        benchmark_path=benchmark,
        output_dir=tmp_path / "runs",
        run_id="ctp30_test",
        runtime_config=_runtime_config(api_configured=True),
        frozen_ctp100_commit=_current_git_commit(),
    )

    assert report["status"] == "passed"
    assert report["run"]["methods"] == list(CTP30_SEALED_METHODS)
    assert report["run"]["expected_raw_run_count"] == CTP30_EXPECTED_RESULTS
    assert report["checks"]["methods_are_m2_m3_only"] is True


def test_ctp30_preflight_rejects_non_sealed_shape(tmp_path: Path) -> None:
    benchmark = tmp_path / "ctp30_bad.json"
    payload = _ctp30_benchmark()
    payload["cases"] = payload["cases"][:29]
    payload["case_count"] = 29
    payload["turn_count"] = 29
    benchmark.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    report = build_sealed_validation_preflight(
        benchmark_path=benchmark,
        output_dir=tmp_path / "runs",
        run_id="ctp30_test",
        runtime_config=_runtime_config(api_configured=True),
        frozen_ctp100_commit=_current_git_commit(),
    )

    assert report["status"] == "failed"
    assert "case_count_30" in report["failed_checks"]
    assert "turn_count_30" in report["failed_checks"]


def test_ctp30_report_passes_integrity_and_separates_direction(tmp_path: Path) -> None:
    run_dir = tmp_path / "ctp30_run"
    run_dir.mkdir()
    benchmark = _ctp30_benchmark()
    results = _ctp30_results()
    _write_run_artifacts(run_dir, results)

    report = build_sealed_validation_report(
        run_id="ctp30_test",
        run_dir=run_dir,
        benchmark_path=tmp_path / "ctp30.json",
        benchmark_document=benchmark,
        runtime_config=_runtime_config(api_configured=True),
        results=results,
        elapsed_seconds=1.25,
    )

    assert report["status"] == "passed"
    assert report["direction_supported"] is True
    assert report["paired_m3_vs_m2"]["pair_count"] == 30
    assert report["failure_classification_summary"]["method_failure_count"] == 0
    assert report["trace_audit"]["worker_request_count"] == CTP30_EXPECTED_RESULTS
    assert report["trace_audit"]["worker_response_count"] == CTP30_EXPECTED_RESULTS


def test_ctp30_final_artifact_index_supports_sealed_manifest_and_custom_files(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "ctp30_run"
    run_dir.mkdir()
    benchmark_path = tmp_path / "ctp30_sealed_validation_v1.json"
    benchmark_path.write_text(
        json.dumps(_ctp30_benchmark(), ensure_ascii=False),
        encoding="utf-8",
    )
    results = _ctp30_results()
    _write_run_artifacts(run_dir, results)
    (run_dir / "sealed_validation_preflight.json").write_text(
        json.dumps({"status": "passed"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "sealed_validation_gate.json").write_text(
        json.dumps({"status": "passed"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "sealed_validation_report.md").write_text("# report\n", encoding="utf-8")

    payload = write_final_artifact_index(
        run_dir,
        artifact_files=_sealed_artifact_files(run_dir, benchmark_path),
        manifest_name=SEALED_MANIFEST_NAME,
    )

    assert payload["index_status"] == "passed"
    assert (run_dir / FINAL_ARTIFACT_INDEX_NAME).exists()
    manifest = json.loads((run_dir / SEALED_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["results"]["final_artifact_index"].endswith(FINAL_ARTIFACT_INDEX_NAME)
    assert validate_final_artifact_index(run_dir)["status"] == "passed"


def _ctp30_benchmark() -> dict:
    cases = [
        {
            "case_id": f"ctp30_sealed_{index:03d}",
            "title": f"case {index}",
            "task_type": "general_chat",
            "user_input": "你好，简单聊一下。",
            "expected": {
                "task_type": "general_chat",
                "required_tools": [],
                "accepted_agent_sets": [[]],
                "accepted_tool_sets": [[]],
            },
        }
        for index in range(1, 31)
    ]
    return {
        "schema_version": "ctp-benchmark-v2",
        "dataset_id": "ctp30_sealed_validation_v1",
        "dataset_role": "sealed_validation_after_main_design_freeze",
        "dataset_version": "test",
        "case_count": 30,
        "turn_count": 30,
        "cases": cases,
    }


def _ctp30_results() -> list[dict]:
    rows = []
    for index in range(1, 31):
        case_id = f"ctp30_sealed_{index:03d}"
        for method in CTP30_SEALED_METHODS:
            trace_file = f"traces/{case_id}_{method}.jsonl"
            rows.append(
                {
                    "case_id": case_id,
                    "method": method,
                    "status": "completed",
                    "trace_file": trace_file,
                    "metrics": {"stsr": 1.0 if method == "adaptive_multi_agent" else 0.8},
                    "output": {"execution_status": "completed"},
                }
            )
    return rows


def _write_run_artifacts(run_dir: Path, results: list[dict]) -> None:
    (run_dir / "benchmark_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "benchmark_results.csv").write_text("case_id,method,status\n", encoding="utf-8")
    (run_dir / "benchmark_results.checkpoint.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "benchmark_results.checkpoint.csv").write_text(
        "case_id,method,status\n",
        encoding="utf-8",
    )
    (run_dir / "evaluation_summary.json").write_text(
        json.dumps(_summary(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "paper_tables.md").write_text("# tables\n", encoding="utf-8")
    (run_dir / SEALED_MANIFEST_NAME).write_text(
        json.dumps({"results": {}, "git_commit": "test"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "benchmark_resume_state.json").write_text(
        json.dumps({"status": "completed"}, ensure_ascii=False),
        encoding="utf-8",
    )
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(exist_ok=True)
    worker_dir = run_dir / "worker_io"
    worker_dir.mkdir(exist_ok=True)
    for idx, result in enumerate(results):
        (run_dir / result["trace_file"]).write_text(
            json.dumps({"llm_calls": [{"success": True, "status": "completed"}]}, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        (worker_dir / f"{idx:03d}.request.json").write_text(
            json.dumps({"idx": idx}, ensure_ascii=False),
            encoding="utf-8",
        )
        (worker_dir / f"{idx:03d}.response.json").write_text(
            json.dumps({"idx": idx}, ensure_ascii=False),
            encoding="utf-8",
        )


def _summary() -> dict:
    return {
        "schema_version": "ctp-evaluation-summary-v1",
        "paired_statistics": {
            "comparison": "adaptive_multi_agent_vs_fixed_multi_agent",
            "pair_count": 30,
            "metrics": {
                "stsr": {
                    "pair_count": 30,
                    "m3": {"mean": 0.9},
                    "m2": {"mean": 0.8},
                    "delta": {"mean": 0.1, "bootstrap_ci_95": [0.02, 0.18]},
                    "mcnemar": {
                        "m3_only_success": 4,
                        "m2_only_success": 1,
                        "discordant_pairs": 5,
                        "p_value": 0.375,
                        "method": "exact_binomial_two_sided",
                    },
                    "wilcoxon_signed_rank": None,
                }
            },
        },
    }


def _runtime_config(*, api_configured: bool) -> dict:
    return {
        "schema_version": "ctp30-sealed-runtime-config-v1",
        "api_configured": api_configured,
        "methods": list(CTP30_SEALED_METHODS),
        "method_order_seed": 20260718,
    }


def _current_git_commit() -> str:
    import subprocess

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()
