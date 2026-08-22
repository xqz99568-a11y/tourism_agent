import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.formal_artifact_integrity import (  # noqa: E402
    DEFAULT_FORMAL_INTEGRITY_PATHS,
    FORMAL_OUTPUT_PACK_CODE_PATHS,
    FORMAL_RUN_SCRIPT_PATHS,
    FORMAL_RUNTIME_CODE_PATHS,
    PRE_FORMAL_VALIDATION_SCRIPT_PATHS,
    build_formal_artifact_integrity_report,
)
from app.core.formal_experiment_preflight import _DAY8_ARTIFACT_HASH_KEYS  # noqa: E402
from app.core.pre_formal_validation_registry import CRITICAL_CODE_PATHS  # noqa: E402


REQUIRED_RUNTIME_HASH_KEYS = {
    "experiment_runner_code",
    "experiment_result_worker_code",
    "experiment_method_input_code",
    "goal_state_scheduler_code",
    "research_tools_code",
    "fixed_data_code",
    "qweather_snapshot_code",
    "intercity_transport_snapshot_code",
    "tool_executor_code",
    "tracing_code",
    "llm_client_code",
    "llm_manager_code",
    "independent_evaluator_code",
}


def test_formal_artifact_integrity_covers_runtime_and_validation_code() -> None:
    required_groups = (
        FORMAL_RUNTIME_CODE_PATHS,
        FORMAL_OUTPUT_PACK_CODE_PATHS,
        FORMAL_RUN_SCRIPT_PATHS,
        PRE_FORMAL_VALIDATION_SCRIPT_PATHS,
    )
    grouped_keys = set().union(*(set(group) for group in required_groups))

    assert REQUIRED_RUNTIME_HASH_KEYS <= set(FORMAL_RUNTIME_CODE_PATHS)
    assert grouped_keys <= set(DEFAULT_FORMAL_INTEGRITY_PATHS)
    assert grouped_keys <= set(CRITICAL_CODE_PATHS)
    assert set(DEFAULT_FORMAL_INTEGRITY_PATHS) <= set(_DAY8_ARTIFACT_HASH_KEYS)


def test_formal_artifact_integrity_hashes_all_default_paths() -> None:
    report = build_formal_artifact_integrity_report(include_git=False)

    assert report["all_required_artifacts_exist"] is True, report["missing_artifacts"]
    assert set(report["artifacts"]) == set(DEFAULT_FORMAL_INTEGRITY_PATHS)
    assert report["combined_sha256"]
    for key in REQUIRED_RUNTIME_HASH_KEYS:
        item = report["artifacts"][key]
        assert item["exists"] is True
        assert isinstance(item["sha256"], str)
        assert len(item["sha256"]) == 64
