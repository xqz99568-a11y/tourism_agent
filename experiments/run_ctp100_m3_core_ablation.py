"""Run and audit the frozen 360-row CTP100 M3 core-ablation experiment.

This is a supplementary runner, not a fifth/sixth method in the frozen CTP100
main benchmark.  It executes exactly the 30 two-turn CTP100 scenarios with
M3-no-state and M3-no-propagation for three repeats.  The runner performs a
model-free preflight, writes a checkpoint after every new turn, supports strict
contract-checked resume, and emits a post-run integrity report plus immutable
artifact index.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.budget_gold import DEFAULT_CTP100_BUDGET_GOLD_PATH, validate_budget_gold
from app.core.config import settings
from app.core.experiment_method_contract import EVALUATOR_ONLY_FIELDS
from app.core.experiment_method_input import parse_visible_request_slots
from app.core.experiment_runner import (
    BENCHMARK_CHECKPOINT_CSV_NAME,
    BENCHMARK_CHECKPOINT_JSON_NAME,
    BENCHMARK_RESULTS_CSV_NAME,
    BENCHMARK_RESULTS_JSON_NAME,
    BENCHMARK_RESUME_STATE_NAME,
    EXPERIMENT_RESUME_CONTRACT_SCHEMA_VERSION,
    RESEARCH_AGENT_DECISION_NORMALIZER_VERSION,
)
from app.core.final_artifact_index import write_final_artifact_index
from app.core.fixed_data import (
    CANONICAL_JSON_SHA256_STRATEGY,
    canonical_json_sha256,
    validate_fixed_data_snapshot,
)
from app.core.formal_experiment_gate import (
    _api_failure_timeout_summary,
    _failure_classification_summary,
    _load_traces,
)
from app.core.formal_experiment_preflight import (
    DEFAULT_FORMAL_METHOD_ORDER_SEED,
    load_benchmark_document,
)
from app.core.goal_state_scheduler import build_goal_state_result_fingerprints
from app.core.intercity_transport_snapshot import (
    intercity_transport_snapshot_summary,
    validate_intercity_transport_snapshot,
)
from app.core.qweather_snapshot import (
    qweather_snapshot_summary,
    validate_qweather_snapshot,
)
from experiments.m3_core_ablation_variants import (
    M3_CORE_ABLATION_METHODS,
    M3_NO_PROPAGATION_METHOD,
    M3_NO_STATE_METHOD,
    M3CoreAblationRunner,
)
from experiments.run_formal_experiment import (
    _apply_formal_env_defaults,
    _run_pre_formal_real_api_smoke,
)


REPORT_SCHEMA_VERSION = "ctp100-m3-core-ablation-report-v1"
MANIFEST_SCHEMA_VERSION = "ctp100-m3-core-ablation-manifest-v1"
SUBSET_SCHEMA_VERSION = "ctp100-m3-core-ablation-subset-v1"
PREFLIGHT_SCHEMA_VERSION = "ctp100-m3-core-ablation-preflight-v1"
METHOD_GRID_SCHEMA_VERSION = "ctp100-m3-core-ablation-grid-v1"
BASE_CONTRACT_PATH = ROOT / "experiments" / "generated" / "ctp100_m3_core_ablation_contract_v1.json"
BASE_CONTRACT_MD_PATH = ROOT / "experiments" / "generated" / "ctp100_m3_core_ablation_contract_v1.md"
CONTRACT_PATH = ROOT / "experiments" / "generated" / "ctp100_m3_core_ablation_contract_v2.json"
CONTRACT_MD_PATH = ROOT / "experiments" / "generated" / "ctp100_m3_core_ablation_contract_v2.md"
DEFAULT_BENCHMARK_PATH = ROOT / "experiments" / "ctp100_formal_v2.json"
DEFAULT_OUTPUT_ROOT = Path(r"D:\Tourism_Agent_Formal_Runs\ctp100_m3_core_ablation")
DEFAULT_MODEL_CONFIG_NAME = "ctp100-m3-core-ablation-v1"
EXPECTED_SCENARIOS = 30
EXPECTED_TURNS = 60
EXPECTED_REPEATS = 3
EXPECTED_ROWS_PER_METHOD = 180
EXPECTED_ROWS = 360
EXPECTED_TARGET_ROWS_PER_METHOD = 90
EXPECTED_TARGET_ROWS = 180
PREFLIGHT_NAME = "ctp100_m3_core_ablation_preflight.json"
SUBSET_NAME = "ctp100_m3_core_ablation_subset.json"
REPORT_JSON_NAME = "ctp100_m3_core_ablation_report.json"
REPORT_MD_NAME = "ctp100_m3_core_ablation_report.md"
MANIFEST_NAME = "experiment_manifest.json"

# This digest is frozen from the pre-refactor M3 scheduler at contract source
# commit 4c22dff6... over the deterministic 30-case dry-audit projection.  It is
# filled by the task-4 regression fixture and checked before any model call.
PRE_REFACTOR_M3_DECISION_DIGEST = (
    "54d3204ac292afd8569edbc06e6ff364e8bad36882739a96e1965783855f9e81"
)


class CTP100M3CoreAblationRunner(M3CoreAblationRunner):
    """Dedicated runner with a contract independent of the four main methods."""

    def __init__(
        self,
        *,
        protocol_contract_path: str | Path = CONTRACT_PATH,
        **kwargs: Any,
    ) -> None:
        self.protocol_contract_path = Path(protocol_contract_path)
        super().__init__(**kwargs)

    def run_core_ablation_benchmark(
        self,
        benchmark_path: str | Path,
        *,
        repeats: Optional[int] = None,
        run_id: Optional[str] = None,
        system_variant: Optional[str] = None,
        model_config_name: Optional[str] = None,
        csv_path: Optional[str | Path] = None,
        json_path: Optional[str | Path] = None,
        summary_path: Optional[str | Path] = None,
        paper_tables_path: Optional[str | Path] = None,
        manifest_path: Optional[str | Path] = None,
        resume: bool = False,
    ) -> List[Dict[str, Any]]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.arun_core_ablation_benchmark(
                    benchmark_path,
                    repeats=repeats,
                    run_id=run_id,
                    system_variant=system_variant,
                    model_config_name=model_config_name,
                    csv_path=csv_path,
                    json_path=json_path,
                    summary_path=summary_path,
                    paper_tables_path=paper_tables_path,
                    manifest_path=manifest_path,
                    resume=resume,
                )
            )
        raise RuntimeError(
            "run_core_ablation_benchmark() cannot run inside an active event loop; "
            "use arun_core_ablation_benchmark()."
        )

    async def arun_core_ablation_benchmark(
        self,
        benchmark_path: str | Path,
        *,
        repeats: Optional[int] = None,
        run_id: Optional[str] = None,
        system_variant: Optional[str] = None,
        model_config_name: Optional[str] = None,
        csv_path: Optional[str | Path] = None,
        json_path: Optional[str | Path] = None,
        summary_path: Optional[str | Path] = None,
        paper_tables_path: Optional[str | Path] = None,
        manifest_path: Optional[str | Path] = None,
        resume: bool = False,
    ) -> List[Dict[str, Any]]:
        benchmark_file = Path(benchmark_path)
        benchmark_document = json.loads(benchmark_file.read_text(encoding="utf-8"))
        cases = self.load_benchmark(benchmark_file)
        selected_methods = list(M3_CORE_ABLATION_METHODS)
        effective_repeats = self.repeats if repeats is None else _validate_repeats(repeats)
        effective_run_id = str(run_id or self.run_id)

        benchmark_output_dir = self._benchmark_output_dir(effective_run_id)
        csv_path = Path(csv_path or benchmark_output_dir / BENCHMARK_RESULTS_CSV_NAME)
        json_path = Path(json_path or benchmark_output_dir / BENCHMARK_RESULTS_JSON_NAME)
        summary_path = Path(summary_path or benchmark_output_dir / "evaluation_summary.json")
        paper_tables_path = Path(paper_tables_path or benchmark_output_dir / "paper_tables.md")
        manifest_path = Path(manifest_path or benchmark_output_dir / MANIFEST_NAME)
        checkpoint_csv_path = benchmark_output_dir / BENCHMARK_CHECKPOINT_CSV_NAME
        checkpoint_json_path = benchmark_output_dir / BENCHMARK_CHECKPOINT_JSON_NAME
        resume_state_path = benchmark_output_dir / BENCHMARK_RESUME_STATE_NAME
        resume_contract = self._build_core_resume_contract(
            benchmark_path=benchmark_file,
            benchmark_document=benchmark_document,
            run_id=effective_run_id,
            repeats=effective_repeats,
            system_variant=system_variant,
            model_config_name=model_config_name,
        )
        planned_keys = self._planned_benchmark_resume_keys(
            cases,
            methods=selected_methods,
            repeats=effective_repeats,
            repeat_index_start=self.repeat_index,
        )
        planned_key_index = {key: index for index, key in enumerate(planned_keys)}
        results: List[Dict[str, Any]] = []
        completed_by_key: Dict[tuple[str, str, str, int], Dict[str, Any]] = {}
        resume_events: List[Dict[str, Any]] = []
        if resume:
            resume_load = self._load_resume_checkpoint(
                checkpoint_json_path=checkpoint_json_path,
                final_json_path=json_path,
                resume_state_path=resume_state_path,
                current_contract=resume_contract,
                planned_keys=planned_keys,
            )
            results = list(resume_load["results"])
            completed_by_key = {
                self._resume_key_from_result(result): result for result in results
            }
            resume_events.extend(resume_load.get("resume_events") or [])
            resume_events.append(
                {
                    "event": "resume_started",
                    "created_at": _utc_now(),
                    "loaded_result_count": len(results),
                    "source": resume_load.get("source"),
                }
            )
        self._write_benchmark_resume_state(
            resume_state_path,
            contract=resume_contract,
            status="running",
            completed_results=results,
            expected_result_count=len(planned_keys),
            resume_enabled=bool(resume),
            resume_events=resume_events,
        )

        for repeat_offset in range(effective_repeats):
            repeat_index = self.repeat_index + repeat_offset
            for case in cases:
                if not self._is_scenario_case(case):
                    raise ValueError("core-ablation subset must contain scenario cases only")
                case_methods = self._ordered_methods_for_case(
                    selected_methods,
                    case_id=self._benchmark_case_order_id(case),
                    repeat_index=repeat_index,
                )
                for method in case_methods:

                    def checkpoint_result(result: Dict[str, Any]) -> None:
                        self._record_new_resume_result(
                            result,
                            results=results,
                            completed_by_key=completed_by_key,
                        )
                        ordered = self._sort_results_for_resume(results, planned_key_index)
                        self._export_benchmark_checkpoint(
                            ordered,
                            csv_path=checkpoint_csv_path,
                            json_path=checkpoint_json_path,
                        )
                        self._write_benchmark_resume_state(
                            resume_state_path,
                            contract=resume_contract,
                            status="running",
                            completed_results=ordered,
                            expected_result_count=len(planned_keys),
                            resume_enabled=bool(resume),
                            resume_events=resume_events,
                        )

                    scenario_results = await self._arun_scenario_case(
                        case,
                        method=method,
                        run_id=effective_run_id,
                        repeat_index=repeat_index,
                        system_variant=system_variant,
                        model_config_name=model_config_name,
                        completed_results_by_key=completed_by_key,
                        on_new_result=checkpoint_result,
                    )
                    for result in scenario_results:
                        self._record_new_resume_result(
                            result,
                            results=results,
                            completed_by_key=completed_by_key,
                        )

        results = self._sort_results_for_resume(results, planned_key_index)
        self.export_csv(results, csv_path)
        self.export_json(results, json_path)
        summary = self.export_evaluation_summary(results, summary_path)
        self.export_paper_tables(summary, paper_tables_path)
        self._export_benchmark_checkpoint(
            results,
            csv_path=checkpoint_csv_path,
            json_path=checkpoint_json_path,
        )
        self._write_benchmark_resume_state(
            resume_state_path,
            contract=resume_contract,
            status="completed",
            completed_results=results,
            expected_result_count=len(planned_keys),
            resume_enabled=bool(resume),
            resume_events=resume_events,
        )
        self.write_core_manifest(
            benchmark_path=benchmark_file,
            output_path=manifest_path,
            run_id=effective_run_id,
            repeats=effective_repeats,
            system_variant=system_variant,
            model_config_name=model_config_name,
            result_paths={
                "csv": csv_path,
                "json": json_path,
                "summary": summary_path,
                "paper_tables": paper_tables_path,
                "resume_state": resume_state_path,
                "checkpoint_csv": checkpoint_csv_path,
                "checkpoint_json": checkpoint_json_path,
            },
            resume_state_path=resume_state_path,
        )
        return results

    def _build_core_resume_contract(
        self,
        *,
        benchmark_path: Path,
        benchmark_document: Any,
        run_id: str,
        repeats: int,
        system_variant: Optional[str],
        model_config_name: Optional[str],
    ) -> Dict[str, Any]:
        contract_document = _load_protocol_contract(self.protocol_contract_path)
        qweather = qweather_snapshot_summary(compact=True)
        intercity = intercity_transport_snapshot_summary(compact=True)
        model_config = _runtime_model_config()
        return {
            "schema_version": EXPERIMENT_RESUME_CONTRACT_SCHEMA_VERSION,
            "run_id": str(run_id),
            "git_commit": _git_commit(),
            "dataset": {
                "path": benchmark_path.as_posix(),
                "sha256": canonical_json_sha256(benchmark_document),
                "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
            },
            "methods": list(M3_CORE_ABLATION_METHODS),
            "method_contract_sha256": canonical_json_sha256(
                contract_document.get("method_definitions") or {}
            ),
            "protocol_contract_raw_sha256": _file_sha256(self.protocol_contract_path),
            "protocol_contract_canonical_sha256": canonical_json_sha256(
                _read_json_object(self.protocol_contract_path)
            ),
            "effective_protocol_contract_sha256": canonical_json_sha256(contract_document),
            "repeats": _validate_repeats(repeats),
            "repeat_index_start": self.repeat_index,
            "method_order_seed": self.method_order_seed,
            "system_variant": system_variant or "m3_core_ablation",
            "model_config_name": model_config_name or self.model_config_name,
            "model_config": model_config,
            "runtime_config": {
                "strict_mode": _environment_bool("EXPERIMENT_STRICT_MODE", False),
                "cache_disabled": _environment_bool("EXPERIMENT_DISABLE_CACHE", False),
                "trace_save_user_message": _environment_bool("TRACE_SAVE_USER_MESSAGE", False),
                "result_hard_timeout_seconds": _environment_float(
                    "EXPERIMENT_RESULT_HARD_TIMEOUT_SECONDS", 0.0
                ),
            },
            "method_controls": {
                "research_agent_decision_normalizer_enabled": (
                    self.enable_research_agent_decision_normalizer
                ),
                "research_agent_decision_normalizer_version": (
                    RESEARCH_AGENT_DECISION_NORMALIZER_VERSION
                ),
            },
            "offline_data": {
                "fixed_data_combined_sha256": self.fixed_data_manifest.get("combined_sha256"),
                "qweather_snapshot_id": qweather.get("snapshot_id"),
                "qweather_combined_sha256": qweather.get("combined_sha256"),
                "intercity_snapshot_id": intercity.get("snapshot_id"),
                "intercity_combined_sha256": intercity.get("combined_sha256"),
                "budget_gold_file_sha256": _file_sha256(DEFAULT_CTP100_BUDGET_GOLD_PATH),
            },
        }

    def _resume_contract_mismatches(
        self,
        previous_contract: Any,
        current_contract: Mapping[str, Any],
    ) -> List[str]:
        mismatches = super()._resume_contract_mismatches(
            previous_contract,
            current_contract,
        )
        for key in (
            "protocol_contract_raw_sha256",
            "protocol_contract_canonical_sha256",
            "effective_protocol_contract_sha256",
        ):
            previous = _nested_value(previous_contract, key)
            current = current_contract.get(key)
            if previous != current:
                mismatches.append(
                    f"{key} changed: previous={previous!r}, current={current!r}"
                )
        return mismatches

    def write_core_manifest(
        self,
        *,
        benchmark_path: str | Path,
        output_path: str | Path,
        run_id: str,
        repeats: int,
        system_variant: Optional[str],
        model_config_name: Optional[str],
        result_paths: Mapping[str, str | Path],
        resume_state_path: Optional[str | Path],
    ) -> Dict[str, Any]:
        benchmark_file = Path(benchmark_path)
        document = _read_json_object(benchmark_file)
        resume_contract = self._build_core_resume_contract(
            benchmark_path=benchmark_file,
            benchmark_document=document,
            run_id=run_id,
            repeats=repeats,
            system_variant=system_variant,
            model_config_name=model_config_name,
        )
        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "created_at": _utc_now(),
            "run_id": str(run_id),
            "paper_role": "post-review supplemental M3 core-mechanism ablation",
            "dataset_id": document.get("dataset_id"),
            "dataset_version": document.get("dataset_version"),
            "dataset_path": benchmark_file.as_posix(),
            "dataset_sha256": canonical_json_sha256(document),
            "dataset_hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
            "git_commit": _git_commit(),
            "git_tags_at_commit": _git_tags_at_head(),
            "working_tree_clean_at_runner_start": len(self.git_status_short_at_start) == 0,
            "git_status_short_at_runner_start": list(self.git_status_short_at_start),
            "methods": list(M3_CORE_ABLATION_METHODS),
            "method_order_seed": self.method_order_seed,
            "repeats": _validate_repeats(repeats),
            "repeat_index_start": self.repeat_index,
            "expected_result_count": EXPECTED_ROWS,
            "system_variant": system_variant or "m3_core_ablation",
            "model_config_name": model_config_name or self.model_config_name,
            "model_config": resume_contract["model_config"],
            "runtime_config": resume_contract["runtime_config"],
            "offline_data": resume_contract["offline_data"],
            "protocol_contract": {
                "path": self.protocol_contract_path.as_posix(),
                "raw_sha256": resume_contract["protocol_contract_raw_sha256"],
                "canonical_sha256": resume_contract["protocol_contract_canonical_sha256"],
                "effective_contract_sha256": resume_contract[
                    "effective_protocol_contract_sha256"
                ],
            },
            "method_contract_sha256": resume_contract["method_contract_sha256"],
            "results": {key: Path(value).as_posix() for key, value in result_paths.items()},
            "resume": self._manifest_resume_summary(resume_state_path),
        }
        _write_json(Path(output_path), manifest)
        return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK_PATH)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    parser.add_argument("--contract-md", type=Path, default=CONTRACT_MD_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--repeats", type=int, default=EXPECTED_REPEATS)
    parser.add_argument("--repeat-index-start", type=int, default=0)
    parser.add_argument("--method-order-seed", type=int, default=DEFAULT_FORMAL_METHOD_ORDER_SEED)
    parser.add_argument("--model-config-name", type=str, default=DEFAULT_MODEL_CONFIG_NAME)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--strict-ablation-readiness", action="store_true")
    parser.add_argument("--require-clean-git", action="store_true")
    parser.add_argument("--require-tagged-commit", action="store_true")
    parser.add_argument("--skip-real-api-smoke", action="store_true")
    parser.add_argument("--real-api-smoke-max-tokens", type=int, default=512)
    args = parser.parse_args()

    _apply_formal_env_defaults()
    run_id = args.run_id or (
        f"ctp100_m3_core_ablation_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    )
    run_dir = _resolve_run_output_dir(args.output_dir, run_id)
    strict_clean = bool(args.require_clean_git or args.strict_ablation_readiness)
    strict_tag = bool(args.require_tagged_commit or args.strict_ablation_readiness)
    preflight = build_ctp100_m3_core_ablation_preflight(
        benchmark_path=args.benchmark,
        contract_path=args.contract,
        contract_md_path=args.contract_md,
        output_dir=args.output_dir,
        run_id=run_id,
        repeats=args.repeats,
        repeat_index_start=args.repeat_index_start,
        method_order_seed=args.method_order_seed,
        model_config_name=args.model_config_name,
        resume=args.resume,
        require_clean_git=strict_clean,
        require_tagged_commit=strict_tag,
    )
    if args.preflight_only:
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return 0 if preflight["status"] == "passed" else 2
    if preflight["status"] != "passed":
        _raise_preflight_error(preflight)

    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / PREFLIGHT_NAME, preflight)
    subset_document = build_ctp100_m3_core_ablation_subset_document(
        benchmark_path=args.benchmark,
        contract_path=args.contract,
    )
    subset_path = run_dir / SUBSET_NAME
    _write_json(subset_path, subset_document)

    smoke = None
    if not args.skip_real_api_smoke:
        smoke = _run_pre_formal_real_api_smoke(
            run_output_dir=run_dir,
            run_id=run_id,
            max_tokens=args.real_api_smoke_max_tokens,
        )

    runner = CTP100M3CoreAblationRunner(
        protocol_contract_path=args.contract,
        trace_dir=run_dir / "traces",
        output_dir=run_dir,
        repeats=args.repeats,
        repeat_index=args.repeat_index_start,
        run_id=run_id,
        model_config_name=args.model_config_name,
        method_order_seed=args.method_order_seed,
    )
    started = time.perf_counter()
    results = runner.run_core_ablation_benchmark(
        subset_path,
        repeats=args.repeats,
        run_id=run_id,
        system_variant="m3_core_ablation",
        model_config_name=args.model_config_name,
        csv_path=run_dir / BENCHMARK_RESULTS_CSV_NAME,
        json_path=run_dir / BENCHMARK_RESULTS_JSON_NAME,
        summary_path=run_dir / "evaluation_summary.json",
        paper_tables_path=run_dir / "paper_tables.md",
        manifest_path=run_dir / MANIFEST_NAME,
        resume=args.resume,
    )
    elapsed_seconds = time.perf_counter() - started
    report = build_ctp100_m3_core_ablation_report(
        run_id=run_id,
        run_dir=run_dir,
        benchmark_path=args.benchmark,
        subset_path=subset_path,
        preflight=preflight,
        results=results,
        elapsed_seconds=elapsed_seconds,
        pre_formal_smoke=smoke,
    )
    _write_report(run_dir, report)
    _attach_report_to_manifest(run_dir, report=report, preflight=preflight)
    final_index = write_final_artifact_index(
        run_dir,
        artifact_files=_artifact_files(args.benchmark, args.contract, args.contract_md),
        manifest_name=MANIFEST_NAME,
    )
    payload = _completion_payload(
        run_id=run_id,
        run_dir=run_dir,
        report=report,
        final_index=final_index,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.strict_ablation_readiness and (
        report["status"] != "passed" or final_index["index_status"] != "passed"
    ):
        return 1
    return 0


def build_ctp100_m3_core_ablation_preflight(
    *,
    benchmark_path: str | Path = DEFAULT_BENCHMARK_PATH,
    contract_path: str | Path = CONTRACT_PATH,
    contract_md_path: str | Path = CONTRACT_MD_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_ROOT,
    run_id: str = "ctp100_m3_core_ablation_preflight",
    repeats: int = EXPECTED_REPEATS,
    repeat_index_start: int = 0,
    method_order_seed: int = DEFAULT_FORMAL_METHOD_ORDER_SEED,
    model_config_name: str = DEFAULT_MODEL_CONFIG_NAME,
    resume: bool = False,
    require_clean_git: bool = False,
    require_tagged_commit: bool = False,
) -> Dict[str, Any]:
    benchmark_file = Path(benchmark_path)
    contract_file = Path(contract_path)
    contract_md_file = Path(contract_md_path)
    run_dir = _resolve_run_output_dir(output_dir, run_id)
    errors: List[str] = []
    warnings: List[str] = []

    try:
        benchmark_document, source_cases = load_benchmark_document(benchmark_file)
    except Exception as exc:
        benchmark_document, source_cases = {}, []
        errors.append(f"benchmark_load_failed: {exc}")
    try:
        contract = _load_protocol_contract(contract_file)
    except Exception as exc:
        contract = {}
        errors.append(f"contract_load_failed: {exc}")
    try:
        contract_md = contract_md_file.read_text(encoding="utf-8")
    except OSError as exc:
        contract_md = ""
        errors.append(f"contract_markdown_load_failed: {exc}")

    selected_cases = select_frozen_two_turn_cases(source_cases, contract)
    selected_ids = [_case_id(case) for case in selected_cases]
    selected_turn_count = _turn_count(selected_cases)
    expected_ids = [
        str(value)
        for value in _nested_list(contract, "data_scope", "selected_case_ids")
    ]
    selected_hash = canonical_json_sha256(selected_cases) if selected_cases else None
    frozen_selected_hash = _nested_value(
        contract,
        "data_scope",
        "selection_policy",
        "selected_cases_canonical_sha256",
    )
    source_raw_hash = _file_sha256(benchmark_file) if benchmark_file.exists() else None
    source_canonical_hash = (
        canonical_json_sha256(benchmark_document) if benchmark_document else None
    )

    contract_md_audit = _contract_markdown_audit(contract, contract_md)
    comparator_audit = _comparator_artifact_audit(contract)
    dry_run_audit = _deterministic_scheduler_dry_run_audit(selected_cases)
    no_state_audit = _preflight_no_state_visibility_audit(selected_cases)

    fixed_data_report = _validation_report(validate_fixed_data_snapshot)
    qweather_report = _validation_report(validate_qweather_snapshot)
    intercity_report = _validation_report(validate_intercity_transport_snapshot)
    budget_gold_report = _validation_report(validate_budget_gold, DEFAULT_CTP100_BUDGET_GOLD_PATH)
    current_fixed_hash = _nested_value(fixed_data_report, "payload", "combined_sha256")
    current_qweather_hash = qweather_snapshot_summary(compact=True).get("combined_sha256")
    current_intercity_hash = intercity_transport_snapshot_summary(compact=True).get(
        "combined_sha256"
    )
    frozen_controls = _mapping(contract.get("frozen_controls"))
    environment = _environment_report()
    git_status = _git_status_short()
    git_tags = _git_tags_at_head()
    output_has_contents = run_dir.exists() and any(run_dir.iterdir())

    checks = {
        "contract_json_loadable": bool(contract),
        "contract_markdown_agrees": contract_md_audit["agrees"],
        "contract_corrected_before_results": _contract_correction_is_auditable(contract),
        "source_dataset_raw_sha256_matches": source_raw_hash
        == _nested_value(contract, "data_scope", "source_dataset", "raw_file_sha256"),
        "source_dataset_canonical_sha256_matches": source_canonical_hash
        == _nested_value(contract, "data_scope", "source_dataset", "canonical_json_sha256"),
        "selected_case_ids_exact": selected_ids == expected_ids,
        "selected_case_count_30": len(selected_cases) == EXPECTED_SCENARIOS,
        "selected_turn_count_60": selected_turn_count == EXPECTED_TURNS,
        "selected_cases_canonical_sha256_matches": selected_hash == frozen_selected_hash,
        "methods_exact": list(M3_CORE_ABLATION_METHODS)
        == _nested_list(contract, "run_scope", "new_methods"),
        "repeats_3": int(repeats) == EXPECTED_REPEATS,
        "repeat_index_start_0": int(repeat_index_start) == 0,
        "expected_result_count_360": selected_turn_count
        * len(M3_CORE_ABLATION_METHODS)
        * int(repeats)
        == EXPECTED_ROWS,
        "method_order_seed_matches": int(method_order_seed)
        == int(frozen_controls.get("method_order_seed") or -1),
        "model_matches": environment["model"] == frozen_controls.get("model"),
        "temperature_matches": environment["temperature"]
        == float(frozen_controls.get("temperature") or 0),
        "max_tokens_matches": environment["max_tokens"]
        == int(frozen_controls.get("max_tokens") or 0),
        "reasoning_effort_matches": environment["reasoning_effort"]
        == frozen_controls.get("reasoning_effort"),
        "strict_mode_enabled": environment["strict_mode"],
        "cache_disabled": environment["cache_disabled"],
        "hard_timeout_worker_enabled": environment["hard_timeout_seconds"] > 0,
        "llm_runtime_configured": environment["api_key_configured"]
        or environment["ollama_configured"],
        "fixed_data_valid": fixed_data_report["status"] == "passed",
        "qweather_snapshot_valid": qweather_report["status"] == "passed",
        "intercity_transport_snapshot_valid": intercity_report["status"] == "passed",
        "budget_gold_valid": budget_gold_report["status"] == "passed",
        "fixed_data_hash_matches": current_fixed_hash
        == frozen_controls.get("fixed_data_combined_sha256"),
        "qweather_hash_matches": current_qweather_hash
        == frozen_controls.get("qweather_combined_sha256"),
        "intercity_hash_matches": current_intercity_hash
        == frozen_controls.get("intercity_transport_combined_sha256"),
        "all_comparator_hashes_match": comparator_audit["status"] == "passed",
        "m3_default_regression_equivalent": dry_run_audit[
            "default_regression_equivalent"
        ],
        "no_state_input_isolation_passed": no_state_audit["status"] == "passed",
        "no_propagation_fields_present": dry_run_audit[
            "no_propagation_required_fields_complete"
        ],
        "real_propagation_opportunity_present": dry_run_audit[
            "propagation_opportunity_count"
        ]
        > 0,
        "gold_not_visible_to_generation": no_state_audit[
            "generation_gold_leak_count"
        ]
        == 0,
        "output_directory_clean_or_resume": not output_has_contents or bool(resume),
        "git_clean_if_required": not require_clean_git or not git_status,
        "implementation_commit_tagged_if_required": not require_tagged_commit
        or bool(git_tags),
    }
    for key, passed in checks.items():
        if not passed:
            errors.append(key)
    if not require_clean_git and git_status:
        warnings.append("working tree is dirty; strict formal run must use --require-clean-git")
    if not require_tagged_commit and not git_tags:
        warnings.append(
            "current commit is untagged; strict formal run must use --require-tagged-commit"
        )

    return {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "created_at": _utc_now(),
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "run": {
            "run_id": run_id,
            "output_dir": run_dir.as_posix(),
            "methods": list(M3_CORE_ABLATION_METHODS),
            "repeats": int(repeats),
            "repeat_indices": list(range(int(repeat_index_start), int(repeat_index_start) + int(repeats))),
            "method_order_seed": int(method_order_seed),
            "model_config_name": model_config_name,
            "expected_raw_result_count": EXPECTED_ROWS,
            "resume": bool(resume),
        },
        "benchmark": {
            "path": benchmark_file.as_posix(),
            "source_raw_sha256": source_raw_hash,
            "source_canonical_sha256": source_canonical_hash,
            "selected_cases_canonical_sha256": selected_hash,
            "selected_case_count": len(selected_cases),
            "selected_turn_count": selected_turn_count,
            "selected_case_ids": selected_ids,
        },
        "contract": {
            "path": contract_file.as_posix(),
            "markdown_path": contract_md_file.as_posix(),
            "raw_sha256": _file_sha256(contract_file) if contract_file.exists() else None,
            "canonical_sha256": canonical_json_sha256(
                _read_json_object(contract_file)
            )
            if contract
            else None,
            "effective_contract_sha256": canonical_json_sha256(contract)
            if contract
            else None,
            "markdown_audit": contract_md_audit,
        },
        "comparator_artifact_audit": comparator_audit,
        "deterministic_scheduler_dry_run_audit": dry_run_audit,
        "no_state_visibility_audit": no_state_audit,
        "environment": environment,
        "git": {
            "commit": _git_commit(),
            "status_short": git_status,
            "tags_at_head": git_tags,
            "clean_required": bool(require_clean_git),
            "tag_required": bool(require_tagged_commit),
        },
        "fixed_data": fixed_data_report,
        "qweather_snapshot": qweather_report,
        "intercity_transport_snapshot": intercity_report,
        "budget_gold": budget_gold_report,
        "api_calls": {"llm": 0, "weather": 0, "intercity": 0},
    }


def build_ctp100_m3_core_ablation_subset_document(
    *,
    benchmark_path: str | Path = DEFAULT_BENCHMARK_PATH,
    contract_path: str | Path = CONTRACT_PATH,
) -> Dict[str, Any]:
    document, cases = load_benchmark_document(benchmark_path)
    contract = _load_protocol_contract(Path(contract_path))
    selected = select_frozen_two_turn_cases(cases, contract)
    return {
        "schema_version": SUBSET_SCHEMA_VERSION,
        "dataset_id": "ctp100_m3_core_ablation_subset_v1",
        "dataset_version": "2026-09-07-pre-result-hash-correction-v1",
        "dataset_role": "supplemental_core_ablation_subset",
        "source_dataset": {
            "path": Path(benchmark_path).as_posix(),
            "dataset_id": document.get("dataset_id"),
            "canonical_sha256": canonical_json_sha256(document),
            "raw_sha256": _file_sha256(Path(benchmark_path)),
        },
        "protocol_contract": {
            "path": Path(contract_path).as_posix(),
            "canonical_sha256": canonical_json_sha256(contract),
            "amendment_canonical_sha256": canonical_json_sha256(
                _read_json_object(Path(contract_path))
            ),
            "raw_sha256": _file_sha256(Path(contract_path)),
        },
        "selection_policy": {
            "rule": "all and only source cases with exactly two turns",
            "manual_selection": False,
            "post_hoc_success_filtering": False,
            "selected_scenario_count": len(selected),
            "selected_turn_count": _turn_count(selected),
            "selected_cases_canonical_sha256": canonical_json_sha256(selected),
        },
        "cases": selected,
    }


def select_frozen_two_turn_cases(
    cases: Sequence[Mapping[str, Any]],
    contract: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    expected_ids = {
        str(value) for value in _nested_list(contract, "data_scope", "selected_case_ids")
    }
    selected = [
        copy.deepcopy(dict(case))
        for case in cases
        if isinstance(case.get("turns"), list) and len(case.get("turns") or []) == 2
    ]
    if expected_ids:
        selected = [case for case in selected if _case_id(case) in expected_ids]
    return selected


def _deterministic_scheduler_dry_run_audit(
    cases: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    runner = M3CoreAblationRunner()
    default_projection: List[Dict[str, Any]] = []
    explicit_projection: List[Dict[str, Any]] = []
    no_propagation_projection: List[Dict[str, Any]] = []
    propagation_cases: List[Dict[str, Any]] = []
    required_fields = {
        "invalidation_propagation_enabled",
        "initial_invalidated_agents",
        "propagated_invalidated_agents",
        "final_invalidated_agents",
        "propagation_candidates",
        "propagation_reasons",
    }
    missing_fields: List[Dict[str, Any]] = []
    for scenario in cases:
        turns = scenario.get("turns") if isinstance(scenario.get("turns"), list) else []
        if len(turns) != 2:
            continue
        t1, t2 = turns
        previous_state = _synthetic_successful_previous_state(
            parse_visible_request_slots(str(t1.get("user_input") or "")),
            scenario_id=_case_id(scenario),
            method="adaptive_multi_agent",
        )
        case = {
            "case_id": _case_id(scenario),
            "scenario_id": _case_id(scenario),
            "turn_id": str(t2.get("turn_id") or "t2"),
            "turn_index": 1,
            "scenario_turn_count": 2,
            "target_turn": True,
            "user_input": str(t2.get("user_input") or ""),
            "current_turn_slots": parse_visible_request_slots(
                str(t2.get("user_input") or "")
            ),
            "previous_state": previous_state,
            "method_previous_state": previous_state,
            "dialogue_history": [
                {"role": "user", "content": str(t1.get("user_input") or "")},
                {"role": "assistant", "content": "上一轮方法自身生成的普通文本摘要。"},
            ],
        }
        default_plan = runner._select_adaptive_research_plan(case)
        explicit_plan = runner._select_adaptive_research_plan(
            case,
            invalidation_propagation_enabled=True,
        )
        no_propagation_plan = runner._select_adaptive_research_plan(
            case,
            invalidation_propagation_enabled=False,
        )
        default_item = _scheduler_projection(_case_id(scenario), default_plan)
        explicit_item = _scheduler_projection(_case_id(scenario), explicit_plan)
        no_propagation_item = _scheduler_projection(
            _case_id(scenario), no_propagation_plan
        )
        default_projection.append(default_item)
        explicit_projection.append(explicit_item)
        no_propagation_projection.append(no_propagation_item)
        no_prop_decision = _nested_mapping(no_propagation_plan, "scheduler", "decision")
        absent = sorted(required_fields - set(no_prop_decision))
        if absent:
            missing_fields.append({"case_id": _case_id(scenario), "fields": absent})
        default_decision = _nested_mapping(default_plan, "scheduler", "decision")
        propagated = list(default_decision.get("propagated_invalidated_agents") or [])
        if propagated:
            propagation_cases.append(
                {
                    "case_id": _case_id(scenario),
                    "propagated_invalidated_agents": propagated,
                    "propagation_reasons": list(
                        default_decision.get("propagation_reasons") or []
                    ),
                    "full_planned_agents": list(default_plan.get("agents") or []),
                    "no_propagation_planned_agents": list(
                        no_propagation_plan.get("agents") or []
                    ),
                }
            )
    default_digest = canonical_json_sha256(default_projection)
    explicit_digest = canonical_json_sha256(explicit_projection)
    no_prop_digest = canonical_json_sha256(no_propagation_projection)
    baseline_frozen = PRE_REFACTOR_M3_DECISION_DIGEST != "__TO_BE_FROZEN__"
    return {
        "schema_version": "ctp100-m3-core-ablation-scheduler-dry-run-v1",
        "model_calls": 0,
        "case_count": len(default_projection),
        "projection_fields": [
            "planned_agents",
            "planned_tools",
            "reused_agents",
            "invalidated_agents",
        ],
        "default_projection_sha256": default_digest,
        "explicit_true_projection_sha256": explicit_digest,
        "pre_refactor_projection_sha256": PRE_REFACTOR_M3_DECISION_DIGEST,
        "default_equals_explicit_true": default_projection == explicit_projection,
        "default_regression_equivalent": baseline_frozen
        and default_digest == PRE_REFACTOR_M3_DECISION_DIGEST
        and default_projection == explicit_projection,
        "no_propagation_projection_sha256": no_prop_digest,
        "no_propagation_required_fields_complete": not missing_fields,
        "missing_required_fields": missing_fields,
        "propagation_opportunity_count": len(propagation_cases),
        "propagation_opportunity_case_ids": [
            item["case_id"] for item in propagation_cases
        ],
        "propagation_opportunities": propagation_cases,
        "design_candidate_count_note": (
            "The contract's 13 annotated design candidates are not a runtime target. "
            "This independent visible-text/synthetic-state audit is authoritative for "
            "the implementation gate and currently finds 12 actual opportunities."
        ),
    }


def _scheduler_projection(
    case_id: str,
    plan: Mapping[str, Any],
) -> Dict[str, Any]:
    decision = _nested_mapping(plan, "scheduler", "decision")
    return {
        "case_id": case_id,
        "planned_agents": list(decision.get("planned_agents") or []),
        "planned_tools": list(decision.get("planned_tools") or []),
        "reused_agents": list(decision.get("reused_agents") or []),
        "invalidated_agents": list(decision.get("invalidated_agents") or []),
    }


def _synthetic_successful_previous_state(
    slots: Mapping[str, Any],
    *,
    scenario_id: str,
    method: str,
) -> Dict[str, Any]:
    canonical_slots = dict(slots)
    city = str(canonical_slots.get("destination") or "unknown")
    days = int(canonical_slots.get("duration_days") or 1)
    people = int(canonical_slots.get("people_count") or 1)
    start_date = canonical_slots.get("start_date")
    agents = ["attraction", "itinerary", "budget"]
    tool_results: Dict[str, Any] = {
        "poi_search": {
            "tool_name": "poi_search",
            "status": "success",
            "success": True,
            "input": {"city": city, "limit": 4},
            "data": {
                "attractions": [
                    {"poi_id": f"{city}-synthetic-poi", "name": "synthetic POI"}
                ]
            },
        },
        "budget_calculator": {
            "tool_name": "budget_calculator",
            "status": "success",
            "success": True,
            "input": {"city": city, "days": days, "people_count": people},
            "data": {"total": 1000},
        },
    }
    if start_date:
        agents.insert(1, "weather")
        tool_results["weather_query"] = {
            "tool_name": "weather_query",
            "status": "success",
            "success": True,
            "input": {"city": city, "date": start_date, "days": days},
            "data": {"daily_weather": [{"date": start_date, "condition": "sunny"}]},
        }
    daily_itinerary = [
        {"day": index + 1, "attractions": [{"poi_id": f"{city}-synthetic-poi"}]}
        for index in range(max(1, days))
    ]
    available_results = {name: name in agents for name in ("attraction", "weather", "itinerary", "budget")}
    state = {
        "schema_version": "ctp-method-previous-state-v1",
        "case_id": scenario_id,
        "scenario_id": scenario_id,
        "turn_id": "t1",
        "turn_index": 0,
        "method": method,
        "status": "completed",
        "execution_status": "completed",
        "slots": canonical_slots,
        "available_results": available_results,
        "tool_results": tool_results,
        "daily_itinerary": daily_itinerary,
    }
    state["result_fingerprints"] = build_goal_state_result_fingerprints(
        slots=canonical_slots,
        tool_results=tool_results,
        daily_itinerary=daily_itinerary,
        result_agents=agents,
    )
    return state


def _preflight_no_state_visibility_audit(
    cases: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    runner = M3CoreAblationRunner()
    generation_violations: List[Dict[str, Any]] = []
    worker_state_violations: List[Dict[str, Any]] = []
    gold_leaks: List[Dict[str, Any]] = []
    forbidden_generation_keys = {
        "previous_state",
        "method_previous_state",
        "expected",
        "evaluation",
        "metrics",
        "gold",
        "changed_slots",
        "preserved_slots",
    }
    for scenario in cases:
        turns = scenario.get("turns") if isinstance(scenario.get("turns"), list) else []
        if len(turns) != 2:
            continue
        t1, t2 = turns
        previous_state = _synthetic_successful_previous_state(
            parse_visible_request_slots(str(t1.get("user_input") or "")),
            scenario_id=_case_id(scenario),
            method=M3_NO_STATE_METHOD,
        )
        raw_case = {
            **dict(t2),
            "case_id": _case_id(scenario),
            "scenario_id": _case_id(scenario),
            "turn_index": 1,
            "previous_state": previous_state,
            "method_previous_state": previous_state,
            "dialogue_history": [
                {"role": "user", "content": str(t1.get("user_input") or ""), "slots": {"leak": True}},
                {"role": "assistant", "content": "普通文本历史", "output": {"leak": True}},
            ],
        }
        generation_case = runner._case_visible_to_generation(raw_case, M3_NO_STATE_METHOD)
        worker_case = runner._case_visible_to_result_worker(raw_case, M3_NO_STATE_METHOD)
        generation_keys = _recursive_keys(generation_case)
        leaked = sorted(forbidden_generation_keys & generation_keys)
        if leaked:
            generation_violations.append({"case_id": _case_id(scenario), "keys": leaked})
        if any(field in generation_keys for field in EVALUATOR_ONLY_FIELDS):
            gold_leaks.append({"case_id": _case_id(scenario)})
        history = generation_case.get("dialogue_history")
        if not _history_is_role_content_only(history):
            generation_violations.append(
                {"case_id": _case_id(scenario), "keys": ["structured_dialogue_history"]}
            )
        if "previous_state" in worker_case or "method_previous_state" in worker_case:
            worker_state_violations.append({"case_id": _case_id(scenario)})
        if not _history_is_role_content_only(worker_case.get("dialogue_history")):
            worker_state_violations.append(
                {"case_id": _case_id(scenario), "reason": "structured_history"}
            )
    return {
        "schema_version": "ctp100-m3-no-state-preflight-visibility-audit-v1",
        "status": "passed"
        if not generation_violations and not worker_state_violations and not gold_leaks
        else "failed",
        "case_count": len(cases),
        "generation_violation_count": len(generation_violations),
        "worker_state_violation_count": len(worker_state_violations),
        "generation_gold_leak_count": len(gold_leaks),
        "generation_violations": generation_violations[:20],
        "worker_state_violations": worker_state_violations[:20],
        "gold_leaks": gold_leaks[:20],
    }


def _contract_markdown_audit(
    contract: Mapping[str, Any],
    markdown: str,
) -> Dict[str, Any]:
    expected_tokens = [
        str(contract.get("contract_id") or ""),
        M3_NO_STATE_METHOD,
        M3_NO_PROPAGATION_METHOD,
        str(_nested_value(contract, "data_scope", "selection_policy", "selected_cases_canonical_sha256") or ""),
        str(_nested_value(contract, "run_scope", "expected_new_raw_rows_total") or ""),
    ]
    missing = [token for token in expected_tokens if token and token not in markdown]
    return {
        "agrees": not missing,
        "checked_tokens": expected_tokens,
        "missing_tokens": missing,
    }


def _contract_correction_is_auditable(contract: Mapping[str, Any]) -> bool:
    corrections = contract.get("pre_run_corrections")
    if not isinstance(corrections, list):
        return False
    expected = _nested_value(
        contract,
        "data_scope",
        "selection_policy",
        "selected_cases_canonical_sha256",
    )
    return any(
        isinstance(item, Mapping)
        and item.get("timing") == "before any core-ablation LLM call or result inspection"
        and item.get("corrected_value") == expected
        for item in corrections
    )


def _comparator_artifact_audit(contract: Mapping[str, Any]) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    references = _mapping(contract.get("existing_reference_results"))
    full = _mapping(references.get("adaptive_multi_agent"))
    sources = full.get("sources") if isinstance(full.get("sources"), list) else []
    for source in sources:
        if isinstance(source, Mapping):
            items.extend(_reference_source_artifacts(source))
    no_reuse = _mapping(references.get("adaptive_multi_agent_no_reuse"))
    if no_reuse:
        items.extend(_reference_source_artifacts(no_reuse))
    failed = [item for item in items if not item["matches"]]
    return {
        "schema_version": "ctp100-m3-core-ablation-comparator-audit-v1",
        "status": "passed" if items and not failed else "failed",
        "artifact_count": len(items),
        "failed_count": len(failed),
        "artifacts": items,
    }


def _reference_source_artifacts(source: Mapping[str, Any]) -> List[Dict[str, Any]]:
    results_path = Path(str(source.get("results_csv") or ""))
    manifest_path = results_path.with_name(MANIFEST_NAME)
    pairs = (
        ("results_csv", results_path, source.get("results_csv_raw_sha256")),
        ("manifest", manifest_path, source.get("manifest_raw_sha256")),
    )
    items = []
    for artifact_type, path, expected in pairs:
        actual = _file_sha256(path) if path.exists() else None
        items.append(
            {
                "run_id": source.get("run_id"),
                "artifact_type": artifact_type,
                "path": path.as_posix(),
                "exists": path.exists(),
                "expected_raw_sha256": expected,
                "actual_raw_sha256": actual,
                "matches": bool(expected) and actual == expected,
            }
        )
    return items


def _environment_report() -> Dict[str, Any]:
    base_url = os.getenv("LLM_BASE_URL") or settings.llm.base_url
    model = os.getenv("LLM_MODEL") or settings.llm.model
    api_key = os.getenv("LLM_API_KEY") or settings.llm.api_key
    return {
        "base_url": str(base_url),
        "model": str(model),
        "temperature": _environment_float("LLM_TEMPERATURE", settings.llm.temperature),
        "max_tokens": _environment_int("LLM_MAX_TOKENS", settings.llm.max_tokens),
        "reasoning_effort": os.getenv("LLM_REASONING_EFFORT"),
        "strict_mode": _environment_bool("EXPERIMENT_STRICT_MODE", False),
        "cache_disabled": _environment_bool("EXPERIMENT_DISABLE_CACHE", False),
        "hard_timeout_seconds": _environment_float(
            "EXPERIMENT_RESULT_HARD_TIMEOUT_SECONDS", 0.0
        ),
        "api_key_configured": bool(str(api_key or "").strip()),
        "ollama_configured": "ollama" in str(base_url or "").casefold(),
    }


def _runtime_model_config() -> Dict[str, Any]:
    environment = _environment_report()
    return {
        "base_url": environment["base_url"],
        "model": environment["model"],
        "temperature": environment["temperature"],
        "max_tokens": environment["max_tokens"],
        "timeout_seconds": _environment_int("LLM_TIMEOUT", settings.llm.timeout),
        "retry_max_attempts": _environment_int(
            "LLM_RETRY_MAX_ATTEMPTS", settings.llm.retry_max_attempts
        ),
        "reasoning_effort": environment["reasoning_effort"],
        "deterministic_research_final_answer": _environment_bool(
            "EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER", False
        ),
    }


def _validation_report(function: Any, *args: Any) -> Dict[str, Any]:
    try:
        payload = function(*args)
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}
    status = "passed"
    if isinstance(payload, Mapping) and payload.get("status") in {"failed", "error"}:
        status = "failed"
    return {"status": status, "payload": _jsonable(payload)}


def _history_is_role_content_only(history: Any) -> bool:
    return isinstance(history, list) and all(
        isinstance(item, Mapping)
        and set(item).issubset({"role", "content"})
        and bool(str(item.get("content") or "").strip())
        for item in history
    )


def _recursive_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            keys.add(str(key))
            keys.update(_recursive_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(_recursive_keys(item))
    return keys


def _read_json_object(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return value


def _load_protocol_contract(path: Path) -> Dict[str, Any]:
    document = _read_json_object(path)
    base = document.get("base_contract")
    overrides = document.get("effective_overrides")
    if not isinstance(base, Mapping) or not isinstance(overrides, Mapping):
        return document
    base_path = Path(str(base.get("path") or ""))
    if not base_path.is_absolute():
        base_path = ROOT / base_path
    expected_raw = str(base.get("raw_sha256") or "")
    expected_canonical = str(base.get("canonical_sha256") or "")
    actual_raw = _file_sha256(base_path)
    base_document = _read_json_object(base_path)
    actual_canonical = canonical_json_sha256(base_document)
    if actual_raw != expected_raw or actual_canonical != expected_canonical:
        raise ValueError(
            "base protocol contract hash mismatch: "
            f"raw={actual_raw!r}/{expected_raw!r}, "
            f"canonical={actual_canonical!r}/{expected_canonical!r}"
        )
    effective = copy.deepcopy(base_document)
    effective["contract_id"] = document.get("contract_id")
    effective["status"] = document.get("status")
    effective["freeze_date"] = document.get("freeze_date")
    effective["pre_run_corrections"] = copy.deepcopy(
        document.get("pre_run_corrections") or []
    )
    effective["contract_version_chain"] = {
        "base_path": base_path.as_posix(),
        "base_contract_id": base.get("contract_id"),
        "amendment_path": path.as_posix(),
        "amendment_raw_sha256": _file_sha256(path),
        "amendment_canonical_sha256": canonical_json_sha256(document),
    }
    for dotted_path, value in overrides.items():
        _set_nested_value(effective, str(dotted_path).split("."), copy.deepcopy(value))
    return effective


def _set_nested_value(target: Dict[str, Any], path: Sequence[str], value: Any) -> None:
    if not path:
        raise ValueError("override path must not be empty")
    current = target
    for key in path[:-1]:
        existing = current.get(key)
        if not isinstance(existing, dict):
            existing = {}
            current[key] = existing
        current = existing
    current[path[-1]] = value


def _read_json_object_or_none(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return _read_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _read_json_list_or_none(path: Path) -> Optional[List[Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, list) else None


def _csv_row_count(path: Path) -> Optional[int]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    except OSError:
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _file_sha256(path: Path) -> Optional[str]:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nested_mapping(value: Any, *path: str) -> Mapping[str, Any]:
    current: Any = value
    for key in path:
        if not isinstance(current, Mapping):
            return {}
        current = current.get(key)
    return current if isinstance(current, Mapping) else {}


def _nested_value(value: Any, *path: str) -> Any:
    current = value
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _nested_list(value: Any, *path: str) -> List[Any]:
    current = _nested_value(value, *path)
    return list(current) if isinstance(current, list) else []


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _case_id(case: Mapping[str, Any]) -> str:
    return str(case.get("case_id") or case.get("scenario_id") or case.get("id") or "")


def _turn_count(cases: Iterable[Mapping[str, Any]]) -> int:
    return sum(
        len(case.get("turns") or [])
        if isinstance(case.get("turns"), list)
        else 1
        for case in cases
    )


def _resolve_run_output_dir(output_dir: str | Path, run_id: str) -> Path:
    root = Path(output_dir)
    return root if root.name == run_id else root / run_id


def _git_status_short() -> List[str]:
    completed = subprocess.run(
        ["git", "status", "--short"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return ["git_status_unavailable"]
    return [line for line in completed.stdout.splitlines() if line.strip()]


def _git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def _git_tags_at_head() -> List[str]:
    completed = subprocess.run(
        ["git", "tag", "--points-at", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return []
    return sorted(line.strip() for line in completed.stdout.splitlines() if line.strip())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_repeats(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("repeats must be an integer") from exc
    if parsed <= 0:
        raise ValueError("repeats must be positive")
    return parsed


def _environment_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return bool(default)
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _environment_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return int(default)


def _environment_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


def _raise_preflight_error(preflight: Mapping[str, Any]) -> None:
    errors = preflight.get("errors") if isinstance(preflight.get("errors"), list) else []
    details = "\n".join(f"- {item}" for item in errors)
    raise RuntimeError(f"CTP100 M3 core-ablation preflight failed:\n{details}")


def build_ctp100_m3_core_ablation_report(
    *,
    run_id: str,
    run_dir: Path,
    benchmark_path: str | Path,
    subset_path: str | Path,
    preflight: Mapping[str, Any],
    results: List[Dict[str, Any]],
    elapsed_seconds: float,
    pre_formal_smoke: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    traces = _load_traces(run_dir, results)
    method_counts = Counter(str(row.get("method") or "unknown") for row in results)
    status_counts = Counter(str(row.get("status") or "unknown") for row in results)
    repeat_indices = sorted(
        {
            int(row.get("repeat_index"))
            for row in results
            if isinstance(row.get("repeat_index"), int)
        }
    )
    target_rows = [row for row in results if _is_target_turn(row)]
    target_method_counts = Counter(str(row.get("method") or "unknown") for row in target_rows)
    grid = _method_repeat_grid(results)
    method_state_audit = _method_state_audit(results)
    scheduler_audit = _runtime_scheduler_audit(results)
    trace_audit = _trace_audit(traces)
    worker_audit = _worker_io_audit(run_dir, results)
    artifact_audit = _run_artifact_audit(run_dir, results)
    failure_classification = _failure_classification_summary(run_dir, results)
    api_failure_timeout = _api_failure_timeout_summary(traces)
    hard_timeout_result_count = sum(
        1 for row in results if bool(row.get("hard_timeout_triggered"))
    )
    checks = {
        "preflight_passed": preflight.get("status") == "passed",
        "expected_result_count_360": len(results) == EXPECTED_ROWS,
        "methods_exact": set(method_counts) == set(M3_CORE_ABLATION_METHODS),
        "each_method_has_180_rows": all(
            method_counts.get(method, 0) == EXPECTED_ROWS_PER_METHOD
            for method in M3_CORE_ABLATION_METHODS
        ),
        "repeat_indices_0_1_2": repeat_indices == [0, 1, 2],
        "method_repeat_grid_complete_and_unique": grid["missing_count"] == 0
        and grid["duplicate_count"] == 0,
        "target_result_count_180": len(target_rows) == EXPECTED_TARGET_ROWS,
        "each_method_has_90_target_rows": all(
            target_method_counts.get(method, 0) == EXPECTED_TARGET_ROWS_PER_METHOD
            for method in M3_CORE_ABLATION_METHODS
        ),
        "t2_uses_only_own_method_t1": method_state_audit[
            "method_local_or_stateless_violation_count"
        ]
        == 0,
        "no_evaluator_state_in_previous_state": method_state_audit[
            "previous_state_evaluator_leak_count"
        ]
        == 0,
        "no_state_runtime_isolation": scheduler_audit[
            "no_state_violation_count"
        ]
        == 0,
        "no_propagation_runtime_fields_complete": scheduler_audit[
            "no_propagation_field_violation_count"
        ]
        == 0,
        "no_propagation_runtime_opportunity_present": scheduler_audit[
            "no_propagation_opportunity_row_count"
        ]
        > 0,
        "trace_count_matches_results": trace_audit["trace_file_count"] == len(results),
        "llm_calls_recorded": trace_audit["llm_call_count"] > 0,
        "no_mock_calls": trace_audit["mock_call_count"] == 0,
        "no_fallback_calls": trace_audit["fallback_call_count"] == 0,
        "worker_request_count_matches_results": worker_audit[
            "request_file_count"
        ]
        == len(results),
        "worker_response_count_matches_results": worker_audit[
            "response_file_count"
        ]
        == len(results),
        "worker_request_method_grid_complete": all(
            worker_audit["request_method_counts"].get(method, 0)
            == EXPECTED_ROWS_PER_METHOD
            for method in M3_CORE_ABLATION_METHODS
        ),
        "worker_files_valid_and_paired": worker_audit["invalid_request_file_count"]
        == 0
        and worker_audit["invalid_response_file_count"] == 0
        and worker_audit["unpaired_file_count"] == 0,
        "no_state_worker_previous_state_absent": worker_audit[
            "no_state_structured_state_violation_count"
        ]
        == 0,
        "checkpoint_final_and_resume_state_complete": artifact_audit[
            "status"
        ]
        == "passed",
    }
    failed_checks = [key for key, passed in checks.items() if not passed]
    quality = _quality_summary_by_method(results)
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "created_at": _utc_now(),
        "status": "passed" if not failed_checks else "failed",
        "paper_claims_allowed": not failed_checks,
        "run_id": run_id,
        "elapsed_seconds": round(float(elapsed_seconds), 3),
        "benchmark": {
            "source_path": Path(benchmark_path).as_posix(),
            "subset_path": Path(subset_path).as_posix(),
            "source_raw_sha256": _file_sha256(Path(benchmark_path)),
            "subset_raw_sha256": _file_sha256(Path(subset_path)),
        },
        "results": {
            "expected_raw_result_count": EXPECTED_ROWS,
            "actual_raw_result_count": len(results),
            "method_counts": dict(sorted(method_counts.items())),
            "target_method_counts": dict(sorted(target_method_counts.items())),
            "status_counts": dict(sorted(status_counts.items())),
            "repeat_indices": repeat_indices,
            "hard_timeout_result_count": hard_timeout_result_count,
        },
        "checks": checks,
        "failed_checks": failed_checks,
        "method_grid": grid,
        "method_state_audit": method_state_audit,
        "scheduler_audit": scheduler_audit,
        "trace_audit": trace_audit,
        "worker_io_audit": worker_audit,
        "run_artifact_audit": artifact_audit,
        "quality_summary_by_method": quality,
        "failure_classification_summary": failure_classification,
        "api_failure_timeout_summary": api_failure_timeout,
        "pre_formal_real_api_smoke": _jsonable(pre_formal_smoke or {}),
        "interpretation_policy": {
            "primary_scope": "t2 only; 30 scenarios x 3 repeats per method",
            "t1_is_descriptive_setup": True,
            "method_and_api_failures_remain_in_denominator": True,
            "quality_failures_are_not_integrity_gate_failures": True,
            "m3_no_state_primary_comparator": "adaptive_multi_agent_no_reuse",
            "m3_no_propagation_primary_comparator": "adaptive_multi_agent",
            "existing_comparator_rows_are_not_replaced": True,
        },
    }


def _method_repeat_grid(results: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = list(results)
    seen: Counter[tuple[str, str, str, int]] = Counter()
    for row in rows:
        key = (
            str(row.get("case_id") or row.get("scenario_id") or ""),
            str(row.get("turn_id") or ""),
            str(row.get("method") or ""),
            int(row.get("repeat_index") or 0),
        )
        seen[key] += 1
    case_turns = sorted(
        {
            (
                str(row.get("case_id") or row.get("scenario_id") or ""),
                str(row.get("turn_id") or ""),
            )
            for row in rows
            if row.get("case_id") or row.get("scenario_id")
        }
    )
    expected = {
        (case_id, turn_id, method, repeat_index)
        for case_id, turn_id in case_turns
        for method in M3_CORE_ABLATION_METHODS
        for repeat_index in range(EXPECTED_REPEATS)
    }
    missing = sorted(expected - set(seen))
    duplicates = [
        {"case_id": key[0], "turn_id": key[1], "method": key[2], "repeat_index": key[3], "count": count}
        for key, count in sorted(seen.items())
        if count > 1
    ]
    return {
        "schema_version": METHOD_GRID_SCHEMA_VERSION,
        "expected_count": EXPECTED_ROWS,
        "actual_count": len(rows),
        "actual_unique_count": len(seen),
        "missing_count": len(missing),
        "duplicate_count": len(duplicates),
        "sample_missing": [
            {"case_id": key[0], "turn_id": key[1], "method": key[2], "repeat_index": key[3]}
            for key in missing[:20]
        ],
        "sample_duplicates": duplicates[:20],
    }


def _method_state_audit(results: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    method_local_violations: List[Dict[str, Any]] = []
    evaluator_leaks: List[Dict[str, Any]] = []
    for row in results:
        if not _is_target_turn(row):
            continue
        method = str(row.get("method") or "")
        identity = _result_identity(row)
        if method == M3_NO_STATE_METHOD:
            audit = _mapping(row.get("method_previous_state_audit"))
            valid = (
                row.get("previous_state_provided") is False
                and row.get("previous_state_is_method_local") is True
                and row.get("previous_state_is_prior_turn") is True
                and audit.get("dialogue_history_is_method_local") is True
                and audit.get("orchestrator_prior_result_is_prior_turn") is True
            )
        else:
            valid = (
                row.get("previous_state_provided") is True
                and row.get("previous_state_method") == method
                and row.get("previous_state_is_method_local") is True
                and row.get("previous_state_is_prior_turn") is True
            )
        if not valid:
            method_local_violations.append(identity)
        if row.get("previous_state_has_evaluation") or row.get("previous_state_has_metrics"):
            evaluator_leaks.append(identity)
    return {
        "schema_version": "ctp100-m3-core-ablation-method-state-audit-v1",
        "target_turn_count": sum(1 for row in results if _is_target_turn(row)),
        "method_local_or_stateless_violation_count": len(method_local_violations),
        "previous_state_evaluator_leak_count": len(evaluator_leaks),
        "method_local_or_stateless_violations": method_local_violations[:20],
        "previous_state_evaluator_leaks": evaluator_leaks[:20],
    }


def _runtime_scheduler_audit(results: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    no_state_violations: List[Dict[str, Any]] = []
    no_prop_field_violations: List[Dict[str, Any]] = []
    opportunity_rows: List[Dict[str, Any]] = []
    required = {
        "invalidation_propagation_enabled",
        "initial_invalidated_agents",
        "propagated_invalidated_agents",
        "final_invalidated_agents",
        "propagation_candidates",
        "propagation_reasons",
    }
    for row in results:
        output = _mapping(row.get("output"))
        metadata = _nested_mapping(output, "metadata")
        scheduler = _nested_mapping(metadata, "adaptive_scheduler")
        decision = _nested_mapping(scheduler, "decision")
        method = str(row.get("method") or "")
        identity = _result_identity(row)
        if method == M3_NO_STATE_METHOD:
            ablation = _mapping(scheduler.get("ablation"))
            invalid = (
                scheduler.get("name") != "stateless_current_request_capability_router"
                or ablation.get("structured_goal_state_ticket_used") is not False
                or bool(decision.get("reused_agents"))
                or bool(_nested_value(metadata, "reuse_execution", "reused_tool_results"))
                or "goal_state_slots" in metadata
            )
            if invalid:
                no_state_violations.append(identity)
        elif method == M3_NO_PROPAGATION_METHOD:
            missing = sorted(required - set(decision))
            invalid = (
                bool(missing)
                or decision.get("invalidation_propagation_enabled") is not False
                or bool(decision.get("propagated_invalidated_agents"))
            )
            if invalid:
                entry = identity
                entry["missing_fields"] = missing
                no_prop_field_violations.append(entry)
            if decision.get("propagation_candidates"):
                opportunity_rows.append(
                    {
                        **identity,
                        "propagation_candidates": list(decision.get("propagation_candidates") or []),
                        "propagation_reasons": list(decision.get("propagation_reasons") or []),
                    }
                )
    return {
        "schema_version": "ctp100-m3-core-ablation-runtime-scheduler-audit-v1",
        "no_state_violation_count": len(no_state_violations),
        "no_propagation_field_violation_count": len(no_prop_field_violations),
        "no_propagation_opportunity_row_count": len(opportunity_rows),
        "no_state_violations": no_state_violations[:20],
        "no_propagation_field_violations": no_prop_field_violations[:20],
        "no_propagation_opportunity_rows": opportunity_rows[:40],
    }


def _worker_io_audit(
    run_dir: Path,
    results: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    worker_dir = run_dir / "worker_io"
    request_files = sorted(worker_dir.glob("*.request.json")) if worker_dir.exists() else []
    response_files = sorted(worker_dir.glob("*.response.json")) if worker_dir.exists() else []
    no_state_violations: List[Dict[str, Any]] = []
    invalid_files: List[str] = []
    invalid_response_files: List[str] = []
    method_counts: Counter[str] = Counter()
    for path in request_files:
        try:
            request = _read_json_object(path)
        except Exception:
            invalid_files.append(path.as_posix())
            continue
        method = str(request.get("method") or "unknown")
        method_counts[method] += 1
        if method != M3_NO_STATE_METHOD:
            continue
        case = _mapping(request.get("case"))
        reasons: List[str] = []
        if "previous_state" in case or "method_previous_state" in case:
            reasons.append("structured_previous_state_present")
        if not _history_is_role_content_only(case.get("dialogue_history")):
            # Empty t1 history is also valid.
            history = case.get("dialogue_history")
            if history not in (None, []):
                reasons.append("structured_dialogue_history_present")
        if reasons:
            no_state_violations.append(
                {"path": path.as_posix(), "reasons": reasons}
            )
    for path in response_files:
        try:
            _read_json_object(path)
        except Exception:
            invalid_response_files.append(path.as_posix())
    request_stems = {path.name.removesuffix(".request.json") for path in request_files}
    response_stems = {path.name.removesuffix(".response.json") for path in response_files}
    unpaired = sorted(request_stems ^ response_stems)
    expected_no_state_rows = sum(
        1 for row in results if row.get("method") == M3_NO_STATE_METHOD
    )
    return {
        "schema_version": "ctp100-m3-core-ablation-worker-io-audit-v1",
        "directory": worker_dir.as_posix(),
        "request_file_count": len(request_files),
        "response_file_count": len(response_files),
        "request_method_counts": dict(sorted(method_counts.items())),
        "expected_no_state_request_count": expected_no_state_rows,
        "invalid_request_file_count": len(invalid_files),
        "invalid_request_files": invalid_files[:20],
        "invalid_response_file_count": len(invalid_response_files),
        "invalid_response_files": invalid_response_files[:20],
        "unpaired_file_count": len(unpaired),
        "unpaired_file_stems": unpaired[:20],
        "no_state_structured_state_violation_count": len(no_state_violations),
        "no_state_structured_state_violations": no_state_violations[:20],
    }


def _run_artifact_audit(
    run_dir: Path,
    results: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    final_json = _read_json_list_or_none(run_dir / BENCHMARK_RESULTS_JSON_NAME)
    checkpoint_json = _read_json_list_or_none(
        run_dir / BENCHMARK_CHECKPOINT_JSON_NAME
    )
    resume_state = _read_json_object_or_none(run_dir / BENCHMARK_RESUME_STATE_NAME)
    manifest = _read_json_object_or_none(run_dir / MANIFEST_NAME)
    preflight = _read_json_object_or_none(run_dir / PREFLIGHT_NAME)
    final_csv_count = _csv_row_count(run_dir / BENCHMARK_RESULTS_CSV_NAME)
    checkpoint_csv_count = _csv_row_count(
        run_dir / BENCHMARK_CHECKPOINT_CSV_NAME
    )
    results_jsonable = _jsonable(list(results))
    checks = {
        "final_json_matches_memory_results": final_json == results_jsonable,
        "checkpoint_json_matches_final_json": checkpoint_json == final_json,
        "final_csv_row_count_matches": final_csv_count == len(results),
        "checkpoint_csv_row_count_matches": checkpoint_csv_count == len(results),
        "resume_state_completed": _nested_value(resume_state, "status") == "completed",
        "resume_completed_result_count_matches": _nested_value(
            resume_state, "progress", "completed_result_count"
        )
        == len(results),
        "resume_remaining_zero": _nested_value(
            resume_state, "progress", "remaining_result_count"
        )
        == 0,
        "manifest_methods_match": _nested_list(manifest, "methods")
        == list(M3_CORE_ABLATION_METHODS),
        "manifest_repeats_3": _nested_value(manifest, "repeats")
        == EXPECTED_REPEATS,
        "preflight_artifact_passed": _nested_value(preflight, "status") == "passed",
    }
    failed = [key for key, passed in checks.items() if not passed]
    return {
        "schema_version": "ctp100-m3-core-ablation-run-artifact-audit-v1",
        "status": "passed" if not failed else "failed",
        "checks": checks,
        "failed_checks": failed,
        "final_csv_row_count": final_csv_count,
        "checkpoint_csv_row_count": checkpoint_csv_count,
        "final_json_row_count": len(final_json) if isinstance(final_json, list) else None,
        "checkpoint_json_row_count": len(checkpoint_json)
        if isinstance(checkpoint_json, list)
        else None,
    }


def _trace_audit(traces: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = list(traces)
    llm_calls = [
        call
        for trace in rows
        for call in trace.get("llm_calls", [])
        if isinstance(call, Mapping)
    ]
    return {
        "schema_version": "ctp100-m3-core-ablation-trace-audit-v1",
        "trace_file_count": len(rows),
        "llm_call_count": len(llm_calls),
        "mock_call_count": sum(1 for call in llm_calls if call.get("mock") is True),
        "fallback_call_count": sum(
            1 for call in llm_calls if call.get("fallback") is True
        ),
    }


def _quality_summary_by_method(
    results: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    rows = list(results)
    summaries: Dict[str, Any] = {}
    for method in M3_CORE_ABLATION_METHODS:
        method_rows = [row for row in rows if row.get("method") == method]
        target_rows = [row for row in method_rows if _is_target_turn(row)]
        summaries[method] = {
            "all_turns": _metric_summary(method_rows),
            "target_turns": _metric_summary(target_rows),
        }
    return summaries


def _metric_summary(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    def values(name: str) -> List[float]:
        return [
            float(value)
            for value in (_nested_value(row, "metrics", name) for row in rows)
            if isinstance(value, (int, float))
        ]

    stsr = values("stsr")
    hcsr = values("hcsr")
    itcsr = values("itcsr")
    return {
        "row_count": len(rows),
        "stsr_count": len(stsr),
        "mean_stsr": _mean(stsr),
        "mean_hcsr": _mean(hcsr),
        "mean_itcsr": _mean(itcsr),
    }


def _mean(values: Sequence[float]) -> Optional[float]:
    return round(sum(values) / len(values), 6) if values else None


def _is_target_turn(row: Mapping[str, Any]) -> bool:
    return row.get("target_turn") is True or str(row.get("turn_id") or "").casefold() == "t2"


def _result_identity(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "case_id": row.get("case_id") or row.get("scenario_id"),
        "turn_id": row.get("turn_id"),
        "method": row.get("method"),
        "repeat_index": row.get("repeat_index"),
        "status": row.get("status"),
    }


def render_ctp100_m3_core_ablation_report(report: Mapping[str, Any]) -> str:
    checks = _mapping(report.get("checks"))
    results = _mapping(report.get("results"))
    scheduler = _mapping(report.get("scheduler_audit"))
    state = _mapping(report.get("method_state_audit"))
    worker = _mapping(report.get("worker_io_audit"))
    lines = [
        "# CTP100 M3 Core Ablation Integrity Report",
        "",
        f"- status: `{report.get('status')}`",
        f"- paper_claims_allowed: `{report.get('paper_claims_allowed')}`",
        f"- run_id: `{report.get('run_id')}`",
        f"- elapsed_seconds: `{report.get('elapsed_seconds')}`",
        "",
        "## Structural gate",
        "",
        "| check | passed |",
        "| --- | --- |",
    ]
    lines.extend(f"| {key} | `{bool(value)}` |" for key, value in checks.items())
    lines.extend(
        [
            "",
            "## Counts",
            "",
            f"- expected rows: `{results.get('expected_raw_result_count')}`",
            f"- actual rows: `{results.get('actual_raw_result_count')}`",
            f"- methods: `{results.get('method_counts')}`",
            f"- target turns: `{results.get('target_method_counts')}`",
            f"- repeats: `{results.get('repeat_indices')}`",
            "",
            "## State and scheduler audit",
            "",
            f"- method-local/stateless violations: `{state.get('method_local_or_stateless_violation_count')}`",
            f"- previous-state evaluator leaks: `{state.get('previous_state_evaluator_leak_count')}`",
            f"- no-state violations: `{scheduler.get('no_state_violation_count')}`",
            f"- no-propagation field violations: `{scheduler.get('no_propagation_field_violation_count')}`",
            f"- no-propagation opportunity rows: `{scheduler.get('no_propagation_opportunity_row_count')}`",
            "",
            "## Worker I/O",
            "",
            f"- request files: `{worker.get('request_file_count')}`",
            f"- response files: `{worker.get('response_file_count')}`",
            f"- no-state structured-state violations: `{worker.get('no_state_structured_state_violation_count')}`",
            "",
            "Quality scores are outcomes, not integrity-gate conditions; all failures remain in the denominator.",
            "",
        ]
    )
    failed = report.get("failed_checks") if isinstance(report.get("failed_checks"), list) else []
    if failed:
        lines.extend(["## Failed checks", ""])
        lines.extend(f"- `{item}`" for item in failed)
        lines.append("")
    return "\n".join(lines)


def _write_report(run_dir: Path, report: Mapping[str, Any]) -> None:
    _write_json(run_dir / REPORT_JSON_NAME, report)
    (run_dir / REPORT_MD_NAME).write_text(
        render_ctp100_m3_core_ablation_report(report),
        encoding="utf-8",
    )


def _attach_report_to_manifest(
    run_dir: Path,
    *,
    report: Mapping[str, Any],
    preflight: Mapping[str, Any],
) -> None:
    path = run_dir / MANIFEST_NAME
    try:
        manifest = _read_json_object(path)
    except Exception:
        return
    manifest["core_ablation_gate"] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": report.get("status"),
        "paper_claims_allowed": report.get("paper_claims_allowed"),
        "failed_checks": report.get("failed_checks") or [],
        "report_json": (run_dir / REPORT_JSON_NAME).as_posix(),
        "report_markdown": (run_dir / REPORT_MD_NAME).as_posix(),
        "preflight_sha256": canonical_json_sha256(preflight),
    }
    _write_json(path, manifest)


def _artifact_files(
    benchmark_path: str | Path,
    contract_path: str | Path,
    contract_md_path: str | Path,
) -> Dict[str, str | Path]:
    return {
        "ctp100_source_dataset": Path(benchmark_path),
        "core_ablation_base_contract_json": BASE_CONTRACT_PATH,
        "core_ablation_base_contract_markdown": BASE_CONTRACT_MD_PATH,
        "core_ablation_contract_json": Path(contract_path),
        "core_ablation_contract_markdown": Path(contract_md_path),
        "core_ablation_subset": SUBSET_NAME,
        "core_ablation_preflight": PREFLIGHT_NAME,
        "benchmark_results_csv": BENCHMARK_RESULTS_CSV_NAME,
        "benchmark_results_json": BENCHMARK_RESULTS_JSON_NAME,
        "benchmark_results_checkpoint_csv": BENCHMARK_CHECKPOINT_CSV_NAME,
        "benchmark_results_checkpoint_json": BENCHMARK_CHECKPOINT_JSON_NAME,
        "evaluation_summary": "evaluation_summary.json",
        "paper_tables": "paper_tables.md",
        "experiment_manifest": MANIFEST_NAME,
        "benchmark_resume_state": BENCHMARK_RESUME_STATE_NAME,
        "core_ablation_gate": REPORT_JSON_NAME,
        "core_ablation_report": REPORT_MD_NAME,
    }


def _completion_payload(
    *,
    run_id: str,
    run_dir: Path,
    report: Mapping[str, Any],
    final_index: Mapping[str, Any],
) -> Dict[str, Any]:
    results = _mapping(report.get("results"))
    final_index_passed = final_index.get("index_status") == "passed"
    paper_claims_allowed = bool(report.get("paper_claims_allowed")) and final_index_passed
    return {
        "status": "passed" if paper_claims_allowed else "failed",
        "run_id": run_id,
        "output_dir": run_dir.as_posix(),
        "result_count": results.get("actual_raw_result_count"),
        "expected_count": results.get("expected_raw_result_count"),
        "core_ablation_gate": (run_dir / REPORT_JSON_NAME).as_posix(),
        "core_ablation_report": (run_dir / REPORT_MD_NAME).as_posix(),
        "manifest": (run_dir / MANIFEST_NAME).as_posix(),
        "resume_state": (run_dir / BENCHMARK_RESUME_STATE_NAME).as_posix(),
        "checkpoint_csv": (run_dir / BENCHMARK_CHECKPOINT_CSV_NAME).as_posix(),
        "checkpoint_json": (run_dir / BENCHMARK_CHECKPOINT_JSON_NAME).as_posix(),
        "traces": (run_dir / "traces").as_posix(),
        "worker_io": (run_dir / "worker_io").as_posix(),
        "paper_claims_allowed": paper_claims_allowed,
        "core_ablation_gate_status": report.get("status"),
        "failed_checks": report.get("failed_checks") or [],
        "final_artifact_index_json": final_index.get("json"),
        "final_artifact_index_status": final_index.get("index_status"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
