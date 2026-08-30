import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.formal_experiment_preflight import load_benchmark_document
from experiments.run_ctp100_m2_m3_stability import (
    CTP100_M2_M3_STABILITY_EXPECTED_RESULTS,
    CTP100_M2_M3_STABILITY_METHODS,
    build_ctp100_m2_m3_stability_preflight,
    build_ctp100_m2_m3_stability_report,
    render_ctp100_m2_m3_stability_report,
)


DATASET = ROOT / "experiments" / "benchmark.json"


def test_ctp100_m2_m3_stability_preflight_passes_for_frozen_ctp100(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _formal_env(monkeypatch)

    report = build_ctp100_m2_m3_stability_preflight(
        benchmark_path=DATASET,
        output_dir=tmp_path / "runs",
        run_id="ctp100-m2-m3-stability",
        require_clean_git=False,
    )

    assert report["status"] == "passed"
    assert report["run"]["methods"] == list(CTP100_M2_M3_STABILITY_METHODS)
    assert report["run"]["repeats"] == 2
    assert report["run"]["repeat_index_start"] == 1
    assert report["run"]["expected_raw_run_count"] == 520
    assert report["benchmark"]["case_count"] == 100
    assert report["benchmark"]["turn_count"] == 130
    assert report["checks"]["benchmark_points_to_ctp100_formal_v2"] is True
    assert report["checks"]["protected_core_unchanged_from_ctp100_v6"] is True
    assert report["formal_preflight"]["run"]["expected_raw_run_count"] == 520


def test_ctp100_m2_m3_stability_preflight_rejects_wrong_repeat_shape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _formal_env(monkeypatch)

    report = build_ctp100_m2_m3_stability_preflight(
        benchmark_path=DATASET,
        output_dir=tmp_path / "runs",
        run_id="bad-repeat-shape",
        repeats=1,
        repeat_index_start=0,
    )

    assert report["status"] == "failed"
    errors = "\n".join(report["errors"])
    assert "requires repeats=2" in errors
    assert "requires repeat_index_start=1" in errors
    assert "expected raw result count mismatch" in errors


def test_ctp100_m2_m3_stability_report_passes_for_complete_grid(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "stability-run"
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True)
    document, cases = load_benchmark_document(DATASET)
    results = _complete_results(cases, trace_dir)
    preflight = {
        "status": "passed",
        "run": {"expected_raw_run_count": CTP100_M2_M3_STABILITY_EXPECTED_RESULTS},
        "protected_core_audit": {"status": "passed"},
        "formal_preflight": {"status": "passed"},
        "supplement_policy": {"source_main_run": "formal_ctp100_20260825_v6"},
    }

    report = build_ctp100_m2_m3_stability_report(
        run_id="stability-unit",
        run_dir=run_dir,
        benchmark_path=DATASET,
        benchmark_document=document,
        cases=cases,
        preflight=preflight,
        results=results,
        elapsed_seconds=1.5,
    )

    assert report["status"] == "passed"
    assert report["failed_checks"] == []
    assert report["results"]["actual_raw_result_count"] == 520
    assert report["results"]["method_counts"] == {
        "adaptive_multi_agent": 260,
        "fixed_multi_agent": 260,
    }
    assert report["results"]["repeat_indices"] == [1, 2]
    assert report["method_grid"]["missing_count"] == 0
    assert report["method_grid"]["duplicate_count"] == 0
    markdown = render_ctp100_m2_m3_stability_report(report)
    assert "CTP100 M2/M3 Repeat-Stability Report" in markdown
    assert "| expected_result_count | `True` |" in markdown


def test_ctp100_m2_m3_stability_report_fails_on_m0_contamination(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "stability-run"
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True)
    document, cases = load_benchmark_document(DATASET)
    results = _complete_results(cases, trace_dir)
    results[0]["method"] = "llm_direct"
    preflight = {
        "status": "passed",
        "run": {"expected_raw_run_count": CTP100_M2_M3_STABILITY_EXPECTED_RESULTS},
        "protected_core_audit": {"status": "passed"},
        "formal_preflight": {"status": "passed"},
    }

    report = build_ctp100_m2_m3_stability_report(
        run_id="stability-unit",
        run_dir=run_dir,
        benchmark_path=DATASET,
        benchmark_document=document,
        cases=cases,
        preflight=preflight,
        results=results,
        elapsed_seconds=1.5,
    )

    assert report["status"] == "failed"
    assert "methods_are_m2_m3_only" in report["failed_checks"]
    assert "no_m0_m1_results" in report["failed_checks"]


def _complete_results(cases: list[dict], trace_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for repeat_index in (1, 2):
        for case in cases:
            case_id = str(case.get("case_id") or case.get("scenario_id") or case.get("id"))
            turns = case.get("turns")
            if isinstance(turns, list) and turns:
                turn_items = [
                    (str(turn.get("turn_id") or turn.get("id") or f"t{index + 1}"), index)
                    for index, turn in enumerate(turns)
                ]
            else:
                turn_items = [("", 0)]
            for turn_id, turn_index in turn_items:
                for method in CTP100_M2_M3_STABILITY_METHODS:
                    trace_file = trace_dir / f"{case_id}_{turn_id}_{method}_{repeat_index}.jsonl"
                    _write_trace(trace_file, method=method)
                    rows.append(
                        {
                            "case_id": case_id,
                            "scenario_id": case_id,
                            "turn_id": turn_id,
                            "turn_index": turn_index,
                            "method": method,
                            "repeat_index": repeat_index,
                            "status": "completed",
                            "latency_ms": 1000.0,
                            "hard_timeout_triggered": False,
                            "trace_file": f"traces/{trace_file.name}",
                            "metrics": {"stsr": 1.0},
                        }
                    )
    assert len(rows) == CTP100_M2_M3_STABILITY_EXPECTED_RESULTS
    return rows


def _write_trace(path: Path, *, method: str) -> None:
    payload = {
        "method": method,
        "llm_calls": [
            {
                "model": "gpt-5-mini",
                "provider": "vectorengine_openai_compatible",
                "success": True,
                "mock": False,
                "fallback": False,
                "duration_ms": 10,
            }
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def _formal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPERIMENT_STRICT_MODE", "true")
    monkeypatch.setenv("EXPERIMENT_DISABLE_CACHE", "true")
    monkeypatch.setenv("TRACE_SAVE_USER_MESSAGE", "false")
    monkeypatch.setenv("LLM_API_KEY", "test-key-not-persisted")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.vectorengine.ai/v1")
    monkeypatch.setenv("LLM_MODEL", "gpt-5-mini")
    monkeypatch.setenv("LLM_TEMPERATURE", "0")
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
    monkeypatch.setenv("LLM_TIMEOUT", "120")
    monkeypatch.setenv("LLM_RETRY_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "minimal")
    monkeypatch.setenv("EXPERIMENT_RESULT_HARD_TIMEOUT_SECONDS", "900")
    monkeypatch.setenv("EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER", "true")
