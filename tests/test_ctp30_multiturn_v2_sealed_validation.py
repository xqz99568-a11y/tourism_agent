import csv
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.fixed_data import canonical_json_sha256
from experiments.run_ctp30_multiturn_v2_sealed_validation import (
    CTP30_MT_V2_EXPECTED_PRIMARY_RESULTS,
    CTP30_MT_V2_EXPECTED_RESULTS,
    CTP30_MT_V2_METHODS,
    GATE_NAME,
    MANIFEST_NAME,
    PREFLIGHT_NAME,
    REPORT_NAME,
    _multiturn_v2_artifact_files,
    build_multiturn_v2_preflight,
    build_multiturn_v2_report,
    render_multiturn_v2_report,
)


FROZEN_DATASET = ROOT / "experiments" / "ctp30_multiturn_validation_v2.json"
FREEZE_MANIFEST = ROOT / "experiments" / "generated" / "ctp30_multiturn_v2_freeze_manifest.json"


def test_ctp30_multiturn_v2_preflight_accepts_frozen_reviewed_dataset(
    tmp_path: Path,
) -> None:
    report = build_multiturn_v2_preflight(
        benchmark_path=FROZEN_DATASET,
        output_dir=tmp_path / "runs",
        run_id="ctp30-mt-v2",
        runtime_config=_runtime_config(api_configured=True),
        freeze_manifest_path=FREEZE_MANIFEST,
        frozen_ctp100_commit=_current_git_commit(),
    )

    assert report["status"] == "passed"
    assert report["run"]["methods"] == list(CTP30_MT_V2_METHODS)
    assert report["run"]["expected_raw_run_count"] == CTP30_MT_V2_EXPECTED_RESULTS
    assert report["run"]["expected_primary_result_count"] == CTP30_MT_V2_EXPECTED_PRIMARY_RESULTS
    assert report["checks"]["freeze_manifest_matches_dataset"] is True
    assert report["checks"]["manual_review_confirmed"] is True
    assert report["checks"]["top_level_user_input_absent"] is True


def test_ctp30_multiturn_v2_preflight_rejects_single_turn_shape(
    tmp_path: Path,
) -> None:
    benchmark = tmp_path / "bad_ctp30_v2.json"
    payload = json.loads(FROZEN_DATASET.read_text(encoding="utf-8"))
    payload["cases"][0]["turns"] = payload["cases"][0]["turns"][:1]
    payload["turn_count"] = 59
    benchmark.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    report = build_multiturn_v2_preflight(
        benchmark_path=benchmark,
        output_dir=tmp_path / "runs",
        run_id="ctp30-mt-v2-bad",
        runtime_config=_runtime_config(api_configured=True),
        freeze_manifest_path=FREEZE_MANIFEST,
        frozen_ctp100_commit=_current_git_commit(),
    )

    assert report["status"] == "failed"
    assert "freeze_manifest_matches_dataset" in report["failed_checks"]
    assert "turn_count_60" in report["failed_checks"]
    assert "every_case_two_turns" in report["failed_checks"]


def test_ctp30_multiturn_v2_report_passes_for_complete_two_turn_grid(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "ctp30_mt_v2_run"
    run_dir.mkdir()
    benchmark = json.loads(FROZEN_DATASET.read_text(encoding="utf-8"))
    results = _complete_results(benchmark)
    _write_run_artifacts(run_dir, results, benchmark)
    preflight = _preflight_dict()

    report = build_multiturn_v2_report(
        run_id="ctp30-mt-v2",
        run_dir=run_dir,
        benchmark_path=FROZEN_DATASET,
        benchmark_document=benchmark,
        runtime_config=_runtime_config(api_configured=True),
        preflight=preflight,
        results=results,
        elapsed_seconds=30.0,
    )

    assert report["status"] == "passed"
    assert report["results"]["actual_raw_result_count"] == CTP30_MT_V2_EXPECTED_RESULTS
    assert report["results"]["actual_primary_result_count"] == CTP30_MT_V2_EXPECTED_PRIMARY_RESULTS
    assert report["paired_m3_vs_m2_primary_turn"]["pair_count"] == 30
    assert report["previous_state_audit"]["missing_previous_slots_count"] == 0
    assert report["worker_previous_state_audit"]["turn2_previous_slots_required_count"] == 58
    assert report["worker_previous_state_audit"]["turn2_previous_slots_not_required_count"] == 2
    assert report["worker_previous_state_audit"]["missing_previous_slots_count"] == 0
    assert report["worker_previous_state_audit"]["raw_previous_state_gold_field_violation_count"] == 0
    assert report["failed_checks"] == []
    markdown = render_multiturn_v2_report(report)
    assert "CTP30-v2 Sealed Multi-Turn Validation Report" in markdown
    assert "| turn2_previous_slots_auditable | `True` |" in markdown


def test_ctp30_multiturn_v2_report_fails_when_turn2_lacks_previous_slots(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "ctp30_mt_v2_missing_slots"
    run_dir.mkdir()
    benchmark = json.loads(FROZEN_DATASET.read_text(encoding="utf-8"))
    results = _complete_results(benchmark)
    victim = next(
        row
        for row in results
        if row["turn_id"] == "t2" and row["method"] == "adaptive_multi_agent"
    )
    victim["method_previous_state_audit"]["previous_slots"] = {}
    victim["method_previous_state_audit"]["previous_slots_sha256"] = None
    victim["method_previous_state_audit"]["previous_slots_key_count"] = 0
    victim["method_previous_state_audit"]["previous_slots_auditable"] = False
    _write_run_artifacts(run_dir, results, benchmark)
    first_t2_request = next(
        path
        for path in sorted((run_dir / "worker_io").glob("*.request.json"))
        if json.loads(path.read_text(encoding="utf-8"))["request_id"]
        == victim["request_id"]
    )
    request_payload = json.loads(first_t2_request.read_text(encoding="utf-8"))
    request_payload["case"]["previous_state"]["slots"] = {}
    first_t2_request.write_text(
        json.dumps(request_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    report = build_multiturn_v2_report(
        run_id="ctp30-mt-v2",
        run_dir=run_dir,
        benchmark_path=FROZEN_DATASET,
        benchmark_document=benchmark,
        runtime_config=_runtime_config(api_configured=True),
        preflight=_preflight_dict(),
        results=results,
        elapsed_seconds=30.0,
    )

    assert report["status"] == "failed"
    assert "turn2_previous_slots_auditable" in report["failed_checks"]


def test_ctp30_multiturn_v2_report_allows_empty_previous_slots_for_non_slot_control(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "ctp30_mt_v2_no_slot_control"
    run_dir.mkdir()
    benchmark = json.loads(FROZEN_DATASET.read_text(encoding="utf-8"))
    results = _complete_results(benchmark)
    _write_run_artifacts(run_dir, results, benchmark)
    for request_path in sorted((run_dir / "worker_io").glob("*.request.json")):
        request_payload = json.loads(request_path.read_text(encoding="utf-8"))
        case = request_payload.get("case") or {}
        if case.get("case_id") != "ctp30_mt_v2_030" or case.get("turn_id") != "t2":
            continue
        request_payload["case"]["previous_state"]["slots"] = {}
        request_path.write_text(
            json.dumps(request_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    report = build_multiturn_v2_report(
        run_id="ctp30-mt-v2",
        run_dir=run_dir,
        benchmark_path=FROZEN_DATASET,
        benchmark_document=benchmark,
        runtime_config=_runtime_config(api_configured=True),
        preflight=_preflight_dict(),
        results=results,
        elapsed_seconds=30.0,
    )

    worker_audit = report["worker_previous_state_audit"]
    assert report["status"] == "passed"
    assert report["checks"]["turn2_previous_slots_auditable"] is True
    assert worker_audit["missing_previous_slots_count"] == 0
    assert worker_audit["optional_empty_previous_slots_count"] == 2
    assert worker_audit["turn2_previous_slots_required_count"] == 58
    assert worker_audit["turn2_previous_slots_not_required_count"] == 2


def _complete_results(benchmark: dict) -> list[dict]:
    rows: list[dict] = []
    for case in benchmark["cases"]:
        case_id = case["case_id"]
        for turn_index, turn in enumerate(case["turns"]):
            turn_id = turn["turn_id"]
            for method in CTP30_MT_V2_METHODS:
                request_id = f"{case_id}_{turn_id}_{method}"
                rows.append(
                    {
                        "case_id": case_id,
                        "scenario_id": case_id,
                        "turn_id": turn_id,
                        "turn_index": turn_index,
                        "scenario_turn_count": 2,
                        "target_turn": turn_id == "t2",
                        "method": method,
                        "request_id": request_id,
                        "run_id": "ctp30-mt-v2",
                        "repeat_index": 0,
                        "status": "completed",
                        "trace_file": f"traces/{request_id}.jsonl",
                        "latency_ms": 1000.0,
                        "hard_timeout_triggered": False,
                        "previous_state_provided": turn_index > 0,
                        "previous_state_method": method if turn_index > 0 else None,
                        "previous_state_turn_id": "t1" if turn_index > 0 else None,
                        "previous_state_turn_index": 0 if turn_index > 0 else None,
                        "previous_state_is_method_local": True,
                        "previous_state_is_prior_turn": True,
                        "previous_state_has_evaluation": False,
                        "previous_state_has_metrics": False,
                        "method_previous_state_audit": _previous_audit(method, turn_index),
                        "metrics": {
                            "stsr": 1.0 if method == "adaptive_multi_agent" else 0.9,
                        },
                        "output": {
                            "execution_status": "completed",
                            "metadata": {
                                "fixed_template_scheduler": {
                                    "state_reuse": False,
                                    "decision": {"reused_agents": []},
                                }
                            }
                            if method == "fixed_multi_agent"
                            else {},
                        },
                    }
                )
    return rows


def _previous_audit(method: str, turn_index: int) -> dict:
    if turn_index == 0:
        return {
            "previous_state_provided": False,
            "previous_slots": {},
            "previous_slots_sha256": None,
            "previous_slots_key_count": 0,
            "previous_slots_auditable": True,
            "visible_previous_state_has_evaluation": False,
            "visible_previous_state_has_metrics": False,
            "visible_previous_state_has_constraint_report": False,
        }
    slots = {
        "destination": "hangzhou",
        "duration_days": 2,
        "people_count": 2,
        "budget_amount": 3000,
    }
    return {
        "previous_state_provided": True,
        "schema_version": "ctp-method-previous-state-v1",
        "method": method,
        "turn_id": "t1",
        "turn_index": 0,
        "is_method_local": True,
        "is_prior_turn": True,
        "has_evaluation": False,
        "has_metrics": False,
        "visible_previous_state_sha256": canonical_json_sha256({"method": method, "slots": slots}),
        "visible_previous_state_has_evaluation": False,
        "visible_previous_state_has_metrics": False,
        "visible_previous_state_has_constraint_report": False,
        "previous_slots": slots,
        "previous_slots_sha256": canonical_json_sha256(slots),
        "previous_slots_key_count": len(slots),
        "previous_slots_auditable": True,
    }


def _write_run_artifacts(run_dir: Path, results: list[dict], benchmark: dict) -> None:
    (run_dir / "benchmark_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (run_dir / "benchmark_results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case_id", "turn_id", "method", "status"])
        writer.writeheader()
        for row in results:
            writer.writerow(
                {
                    "case_id": row["case_id"],
                    "turn_id": row["turn_id"],
                    "method": row["method"],
                    "status": row["status"],
                }
            )
    (run_dir / "benchmark_results.checkpoint.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "benchmark_results.checkpoint.csv").write_text(
        "case_id,turn_id,method,status\n",
        encoding="utf-8",
    )
    (run_dir / "evaluation_summary.json").write_text(
        json.dumps(_summary(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "paper_tables.md").write_text("# tables\n", encoding="utf-8")
    (run_dir / MANIFEST_NAME).write_text(
        json.dumps({"results": {}, "git_commit": "test"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "benchmark_resume_state.json").write_text(
        json.dumps({"status": "completed"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / PREFLIGHT_NAME).write_text(
        json.dumps(_preflight_dict(), ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / GATE_NAME).write_text(
        json.dumps({"status": "passed"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / REPORT_NAME).write_text("# report\n", encoding="utf-8")

    trace_dir = run_dir / "traces"
    trace_dir.mkdir(exist_ok=True)
    worker_dir = run_dir / "worker_io"
    worker_dir.mkdir(exist_ok=True)
    for result in results:
        (run_dir / result["trace_file"]).write_text(
            json.dumps(
                {
                    "request_id": result["request_id"],
                    "case_id": result["case_id"],
                    "scenario_id": result["case_id"],
                    "turn_id": result["turn_id"],
                    "method": result["method"],
                    "status": "completed",
                    "llm_calls": [{"success": True, "status": "completed"}],
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        request_payload = {
            "case": {
                "case_id": result["case_id"],
                "scenario_id": result["case_id"],
                "turn_id": result["turn_id"],
                "turn_index": result["turn_index"],
            },
            "method": result["method"],
            "request_id": result["request_id"],
        }
        if result["turn_index"] > 0:
            request_payload["case"]["previous_state"] = {
                "schema_version": "ctp-method-previous-state-v1",
                "case_id": result["case_id"],
                "scenario_id": result["case_id"],
                "turn_id": "t1",
                "turn_index": 0,
                "method": result["method"],
                "status": "completed",
                "execution_status": "completed",
                "slots": result["method_previous_state_audit"]["previous_slots"],
            }
        (worker_dir / f"{result['request_id']}.request.json").write_text(
            json.dumps(request_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (worker_dir / f"{result['request_id']}.response.json").write_text(
            json.dumps({"status": "completed", "result": result}, ensure_ascii=False, indent=2),
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
                    "m3": {"mean": 1.0},
                    "m2": {"mean": 0.9},
                    "delta": {"mean": 0.1, "bootstrap_ci_95": [0.0, 0.2]},
                    "mcnemar": {
                        "m3_only_success": 3,
                        "m2_only_success": 0,
                        "discordant_pairs": 3,
                        "p_value": 0.25,
                        "method": "exact_binomial_two_sided",
                    },
                    "wilcoxon_signed_rank": None,
                }
            },
        },
    }


def _runtime_config(*, api_configured: bool) -> dict:
    return {
        "schema_version": "ctp30-multiturn-v2-runtime-config-v1",
        "api_configured": api_configured,
        "methods": list(CTP30_MT_V2_METHODS),
        "method_order_seed": 20260718,
    }


def _preflight_dict() -> dict:
    return {
        "schema_version": "ctp30-multiturn-v2-sealed-validation-preflight-v1",
        "status": "passed",
    }


def _current_git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()
