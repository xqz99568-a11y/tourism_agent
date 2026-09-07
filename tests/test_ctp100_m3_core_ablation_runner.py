import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import experiments.run_ctp100_m3_core_ablation as core_run  # noqa: E402
from app.core.formal_experiment_preflight import load_benchmark_document  # noqa: E402
from experiments.m3_core_ablation_variants import (  # noqa: E402
    M3_NO_PROPAGATION_METHOD,
    M3_NO_STATE_METHOD,
    M3CoreAblationRunner,
)


def _selected_cases() -> list[dict]:
    _, cases = load_benchmark_document(core_run.DEFAULT_BENCHMARK_PATH)
    contract = core_run._load_protocol_contract(core_run.CONTRACT_PATH)
    return core_run.select_frozen_two_turn_cases(cases, contract)


def _fake_result(case: dict, method: str, run_id: str, repeat_index: int) -> dict:
    return {
        "case_id": case["case_id"],
        "scenario_id": case["scenario_id"],
        "method": method,
        "run_id": run_id,
        "repeat_index": repeat_index,
        "status": "completed",
        "metrics": {"stsr": 1.0, "hcsr": 1.0, "itcsr": 1.0},
        "output": {
            "execution_status": "completed",
            "final_answer": "synthetic test result",
            "metadata": {},
        },
        "raw_output": {},
        "trace": {},
    }


def test_frozen_subset_and_model_free_dry_audits() -> None:
    cases = _selected_cases()

    assert len(cases) == 30
    assert core_run._turn_count(cases) == 60
    assert core_run.canonical_json_sha256(cases) == (
        "f6082726bd82f11ca8f8c330bdfc67c040ed2f5ab56a2915ac95b3a8f179274f"
    )

    scheduler = core_run._deterministic_scheduler_dry_run_audit(cases)
    visibility = core_run._preflight_no_state_visibility_audit(cases)

    assert scheduler["model_calls"] == 0
    assert scheduler["default_regression_equivalent"] is True
    assert scheduler["no_propagation_required_fields_complete"] is True
    assert scheduler["propagation_opportunity_count"] == 12
    assert visibility["status"] == "passed"


def test_complete_preflight_passes_without_calling_a_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        core_run,
        "_environment_report",
        lambda: {
            "base_url": "https://example.invalid/v1",
            "model": "gpt-5-mini",
            "temperature": 0.0,
            "max_tokens": 4096,
            "reasoning_effort": "minimal",
            "strict_mode": True,
            "cache_disabled": True,
            "hard_timeout_seconds": 900.0,
            "api_key_configured": True,
            "ollama_configured": False,
        },
    )
    monkeypatch.setattr(
        core_run,
        "_comparator_artifact_audit",
        lambda *_: {"status": "passed", "artifact_count": 6, "failed_count": 0},
    )
    monkeypatch.setattr(core_run, "_git_status_short", lambda: [])
    monkeypatch.setattr(core_run, "_git_tags_at_head", lambda: ["core-ablation-test"])

    report = core_run.build_ctp100_m3_core_ablation_preflight(
        output_dir=tmp_path,
        run_id="preflight-test",
        require_clean_git=True,
        require_tagged_commit=True,
    )

    assert report["status"] == "passed"
    assert report["errors"] == []
    assert report["api_calls"] == {"llm": 0, "weather": 0, "intercity": 0}
    assert report["run"]["expected_raw_result_count"] == 360


def test_no_state_worker_boundary_strips_state_but_keeps_evaluator_labels(
    tmp_path: Path,
) -> None:
    runner = M3CoreAblationRunner(trace_dir=tmp_path / "traces")
    raw = {
        "case_id": "case-1",
        "user_input": "预算改成4000元，其他不变。",
        "expected": {"task_type": "partial_replan"},
        "previous_state": {"slots": {"destination": "hangzhou"}},
        "method_previous_state": {"slots": {"destination": "hangzhou"}},
        "dialogue_history": [
            {"role": "assistant", "content": "上一轮回答", "output": {"secret": 1}}
        ],
    }

    worker_case = runner._case_visible_to_result_worker(raw, M3_NO_STATE_METHOD)
    generation_case = runner._case_visible_to_generation(worker_case, M3_NO_STATE_METHOD)

    assert worker_case["expected"] == raw["expected"]
    assert "previous_state" not in worker_case
    assert "method_previous_state" not in worker_case
    assert worker_case["dialogue_history"] == [
        {"role": "assistant", "content": "上一轮回答"}
    ]
    assert "expected" not in generation_case
    assert "previous_state" not in generation_case


def test_core_runner_checkpoints_then_resumes_without_duplicate_turns(
    tmp_path: Path,
) -> None:
    source_document, _ = load_benchmark_document(core_run.DEFAULT_BENCHMARK_PATH)
    one_case = _selected_cases()[0]
    subset = {
        "schema_version": "test-subset-v1",
        "dataset_id": "test-core-ablation-subset",
        "dataset_version": "test-v1",
        "source_dataset_sha256": core_run.canonical_json_sha256(source_document),
        "cases": [one_case],
    }
    subset_path = tmp_path / "subset.json"
    subset_path.write_text(json.dumps(subset, ensure_ascii=False), encoding="utf-8")
    run_id = "resume-core-ablation"

    first = core_run.CTP100M3CoreAblationRunner(
        output_dir=tmp_path,
        trace_dir=tmp_path / run_id / "traces",
        repeats=1,
        run_id=run_id,
    )
    calls = 0

    async def interrupted_arun(case: dict, *, method: str, run_id: str, repeat_index: int, **_: object) -> dict:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("synthetic interruption")
        return _fake_result(case, method, run_id, repeat_index)

    first.arun = interrupted_arun  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        asyncio.run(
            first.arun_core_ablation_benchmark(
                subset_path,
                repeats=1,
                run_id=run_id,
            )
        )

    checkpoint_path = tmp_path / run_id / core_run.BENCHMARK_CHECKPOINT_JSON_NAME
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert len(checkpoint) == 2

    second = core_run.CTP100M3CoreAblationRunner(
        output_dir=tmp_path,
        trace_dir=tmp_path / run_id / "traces",
        repeats=1,
        run_id=run_id,
    )
    resumed_calls = 0

    async def resumed_arun(case: dict, *, method: str, run_id: str, repeat_index: int, **_: object) -> dict:
        nonlocal resumed_calls
        resumed_calls += 1
        return _fake_result(case, method, run_id, repeat_index)

    second.arun = resumed_arun  # type: ignore[method-assign]
    results = asyncio.run(
        second.arun_core_ablation_benchmark(
            subset_path,
            repeats=1,
            run_id=run_id,
            resume=True,
        )
    )

    assert len(results) == 4
    assert resumed_calls == 2
    keys = {
        (row["case_id"], row["turn_id"], row["method"], row["repeat_index"])
        for row in results
    }
    assert len(keys) == 4
    resume_state = json.loads(
        (tmp_path / run_id / core_run.BENCHMARK_RESUME_STATE_NAME).read_text(
            encoding="utf-8"
        )
    )
    assert resume_state["status"] == "completed"
    assert resume_state["progress"]["remaining_result_count"] == 0


def test_comparator_hash_audit_detects_mismatch(tmp_path: Path) -> None:
    result_path = tmp_path / "benchmark_results.csv"
    result_path.write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / core_run.MANIFEST_NAME).write_text("{}", encoding="utf-8")
    source = {
        "run_id": "bad-reference",
        "results_csv": result_path.as_posix(),
        "results_csv_raw_sha256": "0" * 64,
        "manifest_raw_sha256": "0" * 64,
    }

    items = core_run._reference_source_artifacts(source)

    assert len(items) == 2
    assert all(item["matches"] is False for item in items)


def test_method_grid_requires_exact_360_unique_keys() -> None:
    rows = []
    for scenario_index in range(30):
        for turn_id in ("t1", "t2"):
            for method in (M3_NO_STATE_METHOD, M3_NO_PROPAGATION_METHOD):
                for repeat_index in range(3):
                    rows.append(
                        {
                            "case_id": f"case-{scenario_index:02d}",
                            "turn_id": turn_id,
                            "method": method,
                            "repeat_index": repeat_index,
                        }
                    )

    complete = core_run._method_repeat_grid(rows)
    duplicated = core_run._method_repeat_grid([*rows, dict(rows[0])])

    assert complete["actual_count"] == 360
    assert complete["missing_count"] == 0
    assert complete["duplicate_count"] == 0
    assert duplicated["duplicate_count"] == 1


def test_post_run_report_accepts_complete_360_row_integrity_pack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = []
    for scenario_index in range(30):
        for turn_index, turn_id in enumerate(("t1", "t2")):
            for method in (M3_NO_STATE_METHOD, M3_NO_PROPAGATION_METHOD):
                for repeat_index in range(3):
                    if method == M3_NO_STATE_METHOD:
                        scheduler = {
                            "name": "stateless_current_request_capability_router",
                            "decision": {"reused_agents": []},
                            "ablation": {"structured_goal_state_ticket_used": False},
                        }
                        previous_fields = {
                            "previous_state_provided": False,
                            "previous_state_method": None,
                            "previous_state_is_method_local": True,
                            "previous_state_is_prior_turn": True,
                            "previous_state_has_evaluation": False,
                            "previous_state_has_metrics": False,
                            "method_previous_state_audit": {
                                "dialogue_history_is_method_local": True,
                                "orchestrator_prior_result_is_prior_turn": True,
                            },
                        }
                    else:
                        scheduler = {
                            "name": "goal_state_scheduler_no_propagation_ablation",
                            "decision": {
                                "invalidation_propagation_enabled": False,
                                "initial_invalidated_agents": ["weather"],
                                "propagated_invalidated_agents": [],
                                "final_invalidated_agents": ["weather"],
                                "propagation_candidates": ["itinerary"] if turn_id == "t2" else [],
                                "propagation_reasons": ["slot_change_downstream_invalidation"]
                                if turn_id == "t2"
                                else [],
                            },
                        }
                        previous_fields = {
                            "previous_state_provided": turn_id == "t2",
                            "previous_state_method": method if turn_id == "t2" else None,
                            "previous_state_is_method_local": True,
                            "previous_state_is_prior_turn": True,
                            "previous_state_has_evaluation": False,
                            "previous_state_has_metrics": False,
                            "method_previous_state_audit": {},
                        }
                    rows.append(
                        {
                            "case_id": f"case-{scenario_index:02d}",
                            "scenario_id": f"case-{scenario_index:02d}",
                            "turn_id": turn_id,
                            "turn_index": turn_index,
                            "target_turn": turn_id == "t2",
                            "method": method,
                            "repeat_index": repeat_index,
                            "run_id": "complete-pack",
                            "status": "completed",
                            "metrics": {"stsr": 1.0, "hcsr": 1.0, "itcsr": 1.0},
                            "output": {"metadata": {"adaptive_scheduler": scheduler}},
                            **previous_fields,
                        }
                    )

    monkeypatch.setattr(
        core_run,
        "_load_traces",
        lambda *_: [{"llm_calls": [{"mock": False, "fallback": False}]} for _ in rows],
    )
    monkeypatch.setattr(core_run, "_failure_classification_summary", lambda *_: {})
    monkeypatch.setattr(
        core_run,
        "_api_failure_timeout_summary",
        lambda *_: {"terminal_failure_count": 0},
    )
    monkeypatch.setattr(
        core_run,
        "_worker_io_audit",
        lambda *_: {
            "request_file_count": 360,
            "response_file_count": 360,
            "request_method_counts": {
                M3_NO_STATE_METHOD: 180,
                M3_NO_PROPAGATION_METHOD: 180,
            },
            "invalid_request_file_count": 0,
            "invalid_response_file_count": 0,
            "unpaired_file_count": 0,
            "no_state_structured_state_violation_count": 0,
        },
    )
    monkeypatch.setattr(
        core_run,
        "_run_artifact_audit",
        lambda *_: {"status": "passed"},
    )
    report = core_run.build_ctp100_m3_core_ablation_report(
        run_id="complete-pack",
        run_dir=tmp_path,
        benchmark_path=core_run.DEFAULT_BENCHMARK_PATH,
        subset_path=tmp_path / "subset.json",
        preflight={"status": "passed"},
        results=rows,
        elapsed_seconds=1.0,
    )

    assert report["status"] == "passed"
    assert report["paper_claims_allowed"] is True
    assert report["failed_checks"] == []
    assert report["scheduler_audit"]["no_propagation_opportunity_row_count"] == 90
