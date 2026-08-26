import json
from pathlib import Path

import pytest

from app.core.holm_secondary_statistics import (
    HOLM_SECONDARY_METRICS,
    apply_holm_bonferroni,
    build_holm_secondary_statistics,
    write_holm_secondary_statistics,
)


def test_holm_bonferroni_is_order_independent_and_returns_input_order() -> None:
    rows = [
        {"metric": "b", "raw_p_value": 0.04},
        {"metric": "a", "raw_p_value": 0.001},
        {"metric": "c", "raw_p_value": 0.01},
    ]

    adjusted = apply_holm_bonferroni(rows)
    by_metric = {row["metric"]: row for row in adjusted}

    assert [row["metric"] for row in adjusted] == ["b", "a", "c"]
    assert by_metric["a"]["holm_adjusted_p_value"] == 0.003
    assert by_metric["c"]["holm_adjusted_p_value"] == 0.02
    assert by_metric["b"]["holm_adjusted_p_value"] == 0.04

    shuffled = apply_holm_bonferroni(list(reversed(rows)))
    shuffled_by_metric = {row["metric"]: row for row in shuffled}
    assert {
        metric: row["holm_adjusted_p_value"]
        for metric, row in by_metric.items()
    } == {
        metric: row["holm_adjusted_p_value"]
        for metric, row in shuffled_by_metric.items()
    }


def test_holm_bonferroni_handles_zero_and_one() -> None:
    adjusted = apply_holm_bonferroni(
        [
            {"metric": "zero", "raw_p_value": 0},
            {"metric": "one", "raw_p_value": 1},
        ]
    )

    assert adjusted[0]["holm_adjusted_p_value"] == 0
    assert adjusted[0]["significant_after_correction"] is True
    assert adjusted[1]["holm_adjusted_p_value"] == 1
    assert adjusted[1]["significant_after_correction"] is False


def test_holm_secondary_statistics_excludes_primary_stsr() -> None:
    summary = _summary_with_secondary_metrics()

    analysis = build_holm_secondary_statistics(
        summary,
        source_run_dir=Path("source-run"),
        evaluation_summary_path=Path("missing-summary.json"),
    )

    assert analysis["status"] == "passed"
    assert len(analysis["metrics"]) == 9
    assert all(row["metric"] != "stsr" for row in analysis["metrics"])
    assert analysis["primary_stsr_reference"]["raw_mcnemar_p_value"] == 0.0063


def test_holm_secondary_statistics_refuses_missing_metric() -> None:
    summary = _summary_with_secondary_metrics()
    del summary["paired_statistics"]["metrics"]["tool_call_count"]

    analysis = build_holm_secondary_statistics(
        summary,
        source_run_dir=Path("source-run"),
        evaluation_summary_path=Path("missing-summary.json"),
    )

    assert analysis["status"] == "failed"
    assert "secondary_metrics_complete" in analysis["failed_checks"]
    assert any("tool_call_count" in error for error in analysis["errors"])


def test_holm_secondary_statistics_refuses_primary_metric_in_family() -> None:
    summary = _summary_with_secondary_metrics()

    analysis = build_holm_secondary_statistics(
        summary,
        source_run_dir=Path("source-run"),
        evaluation_summary_path=Path("missing-summary.json"),
        metric_family=(("stsr", "STSR"),),
    )

    assert analysis["status"] == "failed"
    assert "stsr_excluded_from_secondary_family" in analysis["failed_checks"]


def test_write_holm_secondary_statistics_uses_separate_output_and_records_hash(
    tmp_path: Path,
) -> None:
    source = tmp_path / "formal_ctp100_20260825_v6"
    source.mkdir()
    summary_path = source / "evaluation_summary.json"
    summary_path.write_text(
        json.dumps(_summary_with_secondary_metrics(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    before = summary_path.read_bytes()
    output = tmp_path / "formal_ctp100_20260825_v6_secondary_statistics"

    payload = write_holm_secondary_statistics(source, output_dir=output)

    assert payload["analysis_status"] == "passed"
    assert summary_path.read_bytes() == before
    manifest = json.loads((output / "analysis_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"]["evaluation_summary_sha256"]
    assert (output / "holm_secondary_results.json").exists()
    assert (output / "holm_secondary_results.csv").exists()
    assert (output / "holm_secondary_results.md").exists()


def test_write_holm_secondary_statistics_blocks_output_inside_source(tmp_path: Path) -> None:
    source = tmp_path / "formal_ctp100_20260825_v6"
    source.mkdir()
    (source / "evaluation_summary.json").write_text(
        json.dumps(_summary_with_secondary_metrics(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must not be inside"):
        write_holm_secondary_statistics(source, output_dir=source / "holm")


def _summary_with_secondary_metrics() -> dict:
    metrics = {
        "stsr": _paired_metric(0.96, 0.86, p=0.0063, binary=True),
    }
    for index, (metric, _) in enumerate(HOLM_SECONDARY_METRICS):
        metrics[metric] = _paired_metric(
            1.0 + index,
            0.5 + index,
            p=[0, 0.001, 0.01, 0.04, 0.2, 0.5, 0.8, 1, 0.03][index],
        )
    return {
        "schema_version": "ctp-evaluation-summary-v1",
        "paired_statistics": {
            "comparison": "adaptive_multi_agent_vs_fixed_multi_agent",
            "pair_count": 100,
            "metrics": metrics,
        },
    }


def _paired_metric(m3: float, m2: float, *, p: float, binary: bool = False) -> dict:
    payload = {
        "pair_count": 100,
        "m3": {"mean": m3},
        "m2": {"mean": m2},
        "delta": {
            "mean": round(m3 - m2, 4),
            "bootstrap_ci_95": [0.1, 0.9],
        },
    }
    if binary:
        payload["mcnemar"] = {
            "p_value": p,
            "method": "exact_binomial_two_sided",
        }
        payload["wilcoxon_signed_rank"] = None
    else:
        payload["mcnemar"] = None
        payload["wilcoxon_signed_rank"] = {
            "p_value": p,
            "method": "exact_signed_rank",
        }
    return payload
