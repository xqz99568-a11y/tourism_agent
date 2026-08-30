"""Run the CTP100 M3-no-reuse ablation experiment.

This supplementary experiment keeps M3's goal-state understanding and adaptive
agent scheduling, but strips method-local previous intermediate artifacts before
execution.  It is intentionally run separately from the frozen four-method main
benchmark so the paper can use it as ablation evidence rather than as another
main method.
"""
from __future__ import annotations

import argparse
import asyncio
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
from app.core.experiment_runner import (
    BENCHMARK_CHECKPOINT_CSV_NAME,
    BENCHMARK_CHECKPOINT_JSON_NAME,
    BENCHMARK_RESULTS_CSV_NAME,
    BENCHMARK_RESULTS_JSON_NAME,
    BENCHMARK_RESUME_STATE_NAME,
    EXPERIMENT_RESUME_CONTRACT_SCHEMA_VERSION,
    METHOD_PREVIOUS_STATE_SCHEMA_VERSION,
    RESEARCH_AGENT_DECISION_NORMALIZER_VERSION,
    ExperimentRunner,
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
from app.core.intercity_transport_snapshot import (
    intercity_transport_snapshot_summary,
    validate_intercity_transport_snapshot,
)
from app.core.qweather_snapshot import (
    qweather_snapshot_summary,
    validate_qweather_snapshot,
)
from experiments.run_ctp30_sealed_validation import CTP100_V6_FROZEN_COMMIT
from experiments.run_formal_experiment import (
    _apply_formal_env_defaults,
    _run_pre_formal_real_api_smoke,
)


CTP100_M3_NO_REUSE_ABLATION_REPORT_SCHEMA_VERSION = (
    "ctp100-m3-no-reuse-ablation-report-v1"
)
CTP100_M3_NO_REUSE_ABLATION_METHOD = "adaptive_multi_agent_no_reuse"
CTP100_M3_NO_REUSE_EXPECTED_SCENARIO_COUNT = 30
CTP100_M3_NO_REUSE_EXPECTED_TURN_COUNT = 60
CTP100_M3_NO_REUSE_DEFAULT_REPEATS = 3
CTP100_M3_NO_REUSE_EXPECTED_RESULTS = (
    CTP100_M3_NO_REUSE_EXPECTED_TURN_COUNT * CTP100_M3_NO_REUSE_DEFAULT_REPEATS
)
DEFAULT_BENCHMARK_PATH = ROOT / "experiments" / "benchmark.json"
DEFAULT_OUTPUT_ROOT = Path(r"D:\Tourism_Agent_Formal_Runs\ctp100_m3_no_reuse_ablation")
DEFAULT_MODEL_CONFIG_NAME = "ctp100-m3-no-reuse-ablation-v1"
PREFLIGHT_NAME = "ctp100_m3_no_reuse_ablation_preflight.json"
REPORT_JSON_NAME = "ctp100_m3_no_reuse_ablation_report.json"
REPORT_MD_NAME = "ctp100_m3_no_reuse_ablation_report.md"
SUBSET_NAME = "ctp100_m3_no_reuse_ablation_subset.json"
MANIFEST_NAME = "experiment_manifest.json"


class M3NoReuseAblationRunner(ExperimentRunner):
    """ExperimentRunner wrapper for the M3-no-reuse supplementary method."""

    METHOD_ALIASES = {
        **ExperimentRunner.METHOD_ALIASES,
        "m3_no_reuse": CTP100_M3_NO_REUSE_ABLATION_METHOD,
        "m3-no-reuse": CTP100_M3_NO_REUSE_ABLATION_METHOD,
    }

    def run_ablation_benchmark(
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
                self.arun_ablation_benchmark(
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
            "M3NoReuseAblationRunner.run_ablation_benchmark() cannot be used "
            "inside a running event loop; use arun_ablation_benchmark()."
        )

    async def arun_ablation_benchmark(
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
        selected_methods = [CTP100_M3_NO_REUSE_ABLATION_METHOD]
        effective_repeats = self.repeats if repeats is None else _validate_repeats_local(repeats)
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
        resume_contract = self._build_ablation_resume_contract(
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
                    "created_at": datetime.utcnow().isoformat() + "Z",
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
                case_methods = self._ordered_methods_for_case(
                    selected_methods,
                    case_id=self._benchmark_case_order_id(case),
                    repeat_index=repeat_index,
                )
                if self._is_scenario_case(case):
                    for method in case_methods:

                        def _checkpoint_scenario_result(result: Dict[str, Any]) -> None:
                            self._record_new_resume_result(
                                result,
                                results=results,
                                completed_by_key=completed_by_key,
                            )
                            self._export_benchmark_checkpoint(
                                self._sort_results_for_resume(results, planned_key_index),
                                csv_path=checkpoint_csv_path,
                                json_path=checkpoint_json_path,
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

                        scenario_results = await self._arun_scenario_case(
                            case,
                            method=method,
                            run_id=effective_run_id,
                            repeat_index=repeat_index,
                            system_variant=system_variant,
                            model_config_name=model_config_name,
                            completed_results_by_key=completed_by_key,
                            on_new_result=_checkpoint_scenario_result,
                        )
                        for result in scenario_results:
                            self._record_new_resume_result(
                                result,
                                results=results,
                                completed_by_key=completed_by_key,
                            )
                        self._export_benchmark_checkpoint(
                            self._sort_results_for_resume(results, planned_key_index),
                            csv_path=checkpoint_csv_path,
                            json_path=checkpoint_json_path,
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
                    continue
                raise ValueError("M3-no-reuse ablation subset must contain scenario cases only")

        results = self._sort_results_for_resume(results, planned_key_index)
        self.export_csv(results, csv_path)
        self.export_json(results, json_path)
        summary = self.export_evaluation_summary(results, summary_path)
        self.export_paper_tables(summary, paper_tables_path)
        self._write_benchmark_resume_state(
            resume_state_path,
            contract=resume_contract,
            status="completed",
            completed_results=results,
            expected_result_count=len(planned_keys),
            resume_enabled=bool(resume),
            resume_events=resume_events,
        )
        self.write_ablation_manifest(
            benchmark_path=benchmark_file,
            output_path=manifest_path,
            run_id=effective_run_id,
            repeats=effective_repeats,
            method_order_seed=self.method_order_seed,
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

    def _normalize_method(self, method: str) -> str:
        normalized = str(method or "").strip().lower()
        normalized = self.METHOD_ALIASES.get(normalized, normalized)
        if normalized == CTP100_M3_NO_REUSE_ABLATION_METHOD:
            return normalized
        return super()._normalize_method(normalized)

    async def _dispatch_method(
        self,
        case: Dict[str, Any],
        method: str,
        request_id: str,
    ) -> Any:
        if method == CTP100_M3_NO_REUSE_ABLATION_METHOD:
            return await self._run_adaptive_multi_agent_no_reuse(case, request_id)
        return await super()._dispatch_method(case, method, request_id)

    async def _run_adaptive_multi_agent_no_reuse(
        self,
        case: Dict[str, Any],
        request_id: str,
    ) -> Dict[str, Any]:
        original_previous_state = self._goal_state_previous_state(case)
        no_reuse_case = self._case_with_previous_slots_only(case)
        no_reuse_previous_state = self._goal_state_previous_state(no_reuse_case)
        plan = self._select_adaptive_research_plan(no_reuse_case)
        scheduler_metadata = self._scheduler_metadata_for_no_reuse_ablation(
            scheduler_metadata=plan.get("scheduler"),
            original_previous_state=original_previous_state,
            no_reuse_previous_state=no_reuse_previous_state,
        )
        execution_case = self._case_with_goal_state_slots(
            no_reuse_case,
            scheduler_metadata=scheduler_metadata,
        )
        return await self._run_research_multi_agent(
            case=execution_case,
            request_id=request_id,
            method=CTP100_M3_NO_REUSE_ABLATION_METHOD,
            planned_agents=plan["agents"],
            planned_tools=plan["tools"],
            scheduler_metadata=scheduler_metadata,
            initial_tool_results={},
        )

    def _research_method_metadata(
        self,
        *,
        method: str,
        scheduler_metadata: Optional[Dict[str, Any]],
        case: Optional[Dict[str, Any]] = None,
        result_agents: Optional[List[str]] = None,
        agent_outputs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        metadata = super()._research_method_metadata(
            method=method,
            scheduler_metadata=scheduler_metadata,
            case=case,
            result_agents=result_agents,
            agent_outputs=agent_outputs,
        )
        if (
            method == CTP100_M3_NO_REUSE_ABLATION_METHOD
            and scheduler_metadata is not None
        ):
            metadata["adaptive_scheduler"] = scheduler_metadata
            metadata["scheduler"] = scheduler_metadata
            reuse_execution = scheduler_metadata.get("reuse_execution")
            if isinstance(reuse_execution, dict):
                metadata["reuse_execution"] = reuse_execution
        return metadata

    def _scheduler_metadata_for_no_reuse_ablation(
        self,
        *,
        scheduler_metadata: Optional[Dict[str, Any]],
        original_previous_state: Optional[Dict[str, Any]],
        no_reuse_previous_state: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if scheduler_metadata is None:
            return None
        scheduler_with_empty_reuse = self._scheduler_metadata_with_reuse_execution(
            scheduler_metadata=scheduler_metadata,
            previous_state=no_reuse_previous_state,
            reused_tool_results={},
        )
        if scheduler_with_empty_reuse is None:
            return None
        return {
            **scheduler_with_empty_reuse,
            "name": "goal_state_scheduler_no_reuse_ablation",
            "ablation": {
                "schema_version": "ctp-m3-no-reuse-ablation-execution-v1",
                "source_method": "adaptive_multi_agent",
                "ablation_method": CTP100_M3_NO_REUSE_ABLATION_METHOD,
                "previous_state_policy": "method_local_previous_slots_only",
                "uses_previous_slots": bool(
                    _nested_mapping(no_reuse_previous_state, "slots")
                ),
                "agent_result_reuse_enabled": False,
                "tool_result_reuse_enabled": False,
                "previous_tool_results_available_before_strip": bool(
                    self._previous_tool_results_from_state(original_previous_state)
                ),
                "previous_agent_outputs_available_before_strip": bool(
                    self._previous_agent_outputs_from_state(original_previous_state)
                ),
                "previous_artifacts_available_after_strip": bool(
                    self._previous_tool_results_from_state(no_reuse_previous_state)
                    or self._previous_agent_outputs_from_state(no_reuse_previous_state)
                    or self._previous_attractions_from_state(no_reuse_previous_state)
                    or self._previous_daily_itinerary_from_state(no_reuse_previous_state)
                    or self._previous_budget_from_state(no_reuse_previous_state)
                ),
            },
        }

    def _case_with_previous_slots_only(self, case: Dict[str, Any]) -> Dict[str, Any]:
        previous_state = self._goal_state_previous_state(case)
        if previous_state is None:
            return dict(case)
        slots = _nested_mapping(previous_state, "slots")
        slots_only_state = {
            "schema_version": METHOD_PREVIOUS_STATE_SCHEMA_VERSION,
            "case_id": previous_state.get("case_id"),
            "scenario_id": previous_state.get("scenario_id"),
            "turn_id": previous_state.get("turn_id"),
            "turn_index": previous_state.get("turn_index"),
            "method": previous_state.get("method"),
            "status": previous_state.get("status"),
            "execution_status": previous_state.get("execution_status"),
            "slots": dict(slots) if isinstance(slots, Mapping) else {},
            "ablation_previous_state_policy": "slots_only_no_intermediate_results",
        }
        stripped_case = dict(case)
        stripped_case["previous_state"] = slots_only_state
        stripped_case["method_previous_state"] = slots_only_state
        return stripped_case

    def _build_ablation_resume_contract(
        self,
        *,
        benchmark_path: Path,
        benchmark_document: Any,
        run_id: str,
        repeats: int,
        system_variant: Optional[str],
        model_config_name: Optional[str],
    ) -> Dict[str, Any]:
        base_url = os.getenv("LLM_BASE_URL") or settings.llm.base_url
        model = os.getenv("LLM_MODEL") or settings.llm.model
        method_contract = self._ablation_method_contract()
        return {
            "schema_version": EXPERIMENT_RESUME_CONTRACT_SCHEMA_VERSION,
            "run_id": str(run_id),
            "git_commit": _git_commit(),
            "dataset": {
                "path": benchmark_path.as_posix(),
                "sha256": canonical_json_sha256(benchmark_document),
                "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
            },
            "methods": [CTP100_M3_NO_REUSE_ABLATION_METHOD],
            "method_contract_sha256": canonical_json_sha256(method_contract),
            "repeats": _validate_repeats_local(repeats),
            "repeat_index_start": self.repeat_index,
            "method_order_seed": self.method_order_seed,
            "system_variant": system_variant or CTP100_M3_NO_REUSE_ABLATION_METHOD,
            "model_config_name": model_config_name or self.model_config_name,
            "model_config": {
                "base_url": str(base_url),
                "model": str(model),
                "temperature": _environment_float("LLM_TEMPERATURE", settings.llm.temperature),
                "max_tokens": _environment_int("LLM_MAX_TOKENS", settings.llm.max_tokens),
                "timeout_seconds": _environment_int("LLM_TIMEOUT", settings.llm.timeout),
                "retry_max_attempts": _environment_int(
                    "LLM_RETRY_MAX_ATTEMPTS",
                    settings.llm.retry_max_attempts,
                ),
                "reasoning_effort": os.getenv("LLM_REASONING_EFFORT"),
                "deterministic_research_final_answer": _environment_bool(
                    "EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER",
                    False,
                ),
            },
            "runtime_config": {
                "strict_mode": _environment_bool("EXPERIMENT_STRICT_MODE", False),
                "cache_disabled": _environment_bool("EXPERIMENT_DISABLE_CACHE", False),
                "trace_save_user_message": _environment_bool(
                    "TRACE_SAVE_USER_MESSAGE",
                    False,
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
                "qweather_snapshot_id": qweather_snapshot_summary(compact=True).get("snapshot_id"),
                "qweather_combined_sha256": qweather_snapshot_summary(compact=True).get("combined_sha256"),
                "intercity_snapshot_id": intercity_transport_snapshot_summary(compact=True).get("snapshot_id"),
                "intercity_combined_sha256": intercity_transport_snapshot_summary(compact=True).get("combined_sha256"),
                "budget_gold_file_sha256": _budget_gold_file_sha256(),
                "budget_gold_review_status": _budget_gold_review_status(),
                "budget_gold_artifact_hashes": _budget_gold_artifact_hashes(),
            },
            "ablation_method_contract": method_contract,
        }

    def write_ablation_manifest(
        self,
        *,
        benchmark_path: str | Path,
        output_path: str | Path,
        run_id: str,
        repeats: int,
        method_order_seed: int,
        system_variant: Optional[str],
        model_config_name: Optional[str],
        result_paths: Mapping[str, str | Path],
        resume_state_path: Optional[str | Path],
    ) -> Dict[str, Any]:
        benchmark_file = Path(benchmark_path)
        document = json.loads(benchmark_file.read_text(encoding="utf-8"))
        method_contract = self._ablation_method_contract()
        manifest = {
            "schema_version": "ctp100-m3-no-reuse-ablation-manifest-v1",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "run_id": str(run_id),
            "dataset_id": str(_mapping(document).get("dataset_id") or benchmark_file.stem),
            "dataset_version": str(_mapping(document).get("dataset_version") or "unknown"),
            "dataset_path": benchmark_file.as_posix(),
            "dataset_sha256": canonical_json_sha256(document),
            "dataset_hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
            "git_commit": _git_commit(),
            "working_tree_clean": not _git_status_short(),
            "git_status_short": _git_status_short(),
            "methods": [CTP100_M3_NO_REUSE_ABLATION_METHOD],
            "method_fairness_contract": {
                **method_contract,
                "contract_sha256": canonical_json_sha256(method_contract),
            },
            "method_order_seed": method_order_seed,
            "repeats": _validate_repeats_local(repeats),
            "repeat_index_start": self.repeat_index,
            "system_variant": system_variant or CTP100_M3_NO_REUSE_ABLATION_METHOD,
            "model_config_name": model_config_name or self.model_config_name,
            "model_config": self._build_ablation_resume_contract(
                benchmark_path=benchmark_file,
                benchmark_document=document,
                run_id=run_id,
                repeats=repeats,
                system_variant=system_variant,
                model_config_name=model_config_name,
            )["model_config"],
            "offline_data": {
                "enabled": True,
                "snapshot": self._offline_data_summary(),
                "qweather_snapshot": qweather_snapshot_summary(),
                "intercity_transport_snapshot": intercity_transport_snapshot_summary(),
            },
            "results": {
                key: Path(value).as_posix() for key, value in result_paths.items()
            },
            "resume": self._manifest_resume_summary(resume_state_path),
        }
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    @staticmethod
    def _ablation_method_contract() -> Dict[str, Any]:
        return {
            "schema_version": "ctp-supplemental-ablation-method-contract-v1",
            "contract_id": "ctp100_m3_no_reuse_ablation_20260831",
            "active_methods": [CTP100_M3_NO_REUSE_ABLATION_METHOD],
            "paper_role": "supplemental ablation, not part of the four-method main benchmark",
            "source_formal_method": "adaptive_multi_agent",
            "methods": {
                CTP100_M3_NO_REUSE_ABLATION_METHOD: {
                    "method": CTP100_M3_NO_REUSE_ABLATION_METHOD,
                    "paper_label": "M3-no-reuse",
                    "experimental_role": (
                        "ablation of M3 that keeps goal-state scheduling and "
                        "method-local previous slots but disables previous "
                        "agent/tool result reuse"
                    ),
                    "agent_topology": "four shared business agents",
                    "scheduler_policy": "goal-state scheduler with slots-only previous state",
                    "state_reuse_policy": (
                        "previous slots only; previous tool results, agent outputs, "
                        "daily itinerary, weather, budget, and attraction artifacts are stripped"
                    ),
                    "can_call_generation_tools": True,
                    "can_reuse_previous_results": False,
                    "source_method": "adaptive_multi_agent",
                    "business_agents": ["attraction", "weather", "itinerary", "budget"],
                    "available_generation_tools": [
                        "poi_search",
                        "weather_query",
                        "budget_calculator",
                    ],
                }
            },
            "isolation_policy": {
                "run_separately_from_main_methods": True,
                "gold_visible_to_generation": False,
                "same_model_prompt_tools_and_frozen_data_as_m3": True,
            },
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--repeats", type=int, default=CTP100_M3_NO_REUSE_DEFAULT_REPEATS)
    parser.add_argument("--repeat-index-start", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--strict-ablation-readiness", action="store_true")
    parser.add_argument("--skip-real-api-smoke", action="store_true")
    parser.add_argument("--real-api-smoke-max-tokens", type=int, default=512)
    parser.add_argument("--method-order-seed", type=int, default=DEFAULT_FORMAL_METHOD_ORDER_SEED)
    parser.add_argument("--model-config-name", type=str, default=DEFAULT_MODEL_CONFIG_NAME)
    parser.add_argument("--frozen-ctp100-commit", type=str, default=CTP100_V6_FROZEN_COMMIT)
    parser.add_argument(
        "--require-clean-git",
        action="store_true",
        help="Require a clean working tree before the ablation run starts.",
    )
    args = parser.parse_args()

    run_id = args.run_id or (
        f"ctp100_m3_no_reuse_ablation_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    )
    run_dir = _resolve_run_output_dir(args.output_dir, run_id)
    _apply_formal_env_defaults()
    preflight = build_ctp100_m3_no_reuse_ablation_preflight(
        benchmark_path=args.benchmark,
        output_dir=args.output_dir,
        run_id=run_id,
        repeats=args.repeats,
        repeat_index_start=args.repeat_index_start,
        method_order_seed=args.method_order_seed,
        model_config_name=args.model_config_name,
        resume=args.resume,
        require_clean_git=args.require_clean_git,
        frozen_ctp100_commit=args.frozen_ctp100_commit,
    )
    if args.preflight_only:
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return 0 if preflight["status"] == "passed" else 2
    if preflight["status"] != "passed":
        _raise_ablation_preflight_error(preflight)

    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / PREFLIGHT_NAME, preflight)
    subset_path = run_dir / SUBSET_NAME
    subset_document = build_ctp100_m3_no_reuse_ablation_subset_document(
        benchmark_path=args.benchmark,
    )
    _write_json(subset_path, subset_document)

    smoke = None
    if not args.skip_real_api_smoke:
        smoke = _run_pre_formal_real_api_smoke(
            run_output_dir=run_dir,
            run_id=run_id,
            max_tokens=args.real_api_smoke_max_tokens,
        )

    runner = M3NoReuseAblationRunner(
        trace_dir=run_dir / "traces",
        output_dir=run_dir,
        repeats=args.repeats,
        repeat_index=args.repeat_index_start,
        run_id=run_id,
        model_config_name=args.model_config_name,
        method_order_seed=args.method_order_seed,
    )
    started = time.perf_counter()
    results = runner.run_ablation_benchmark(
        subset_path,
        repeats=args.repeats,
        run_id=run_id,
        system_variant=CTP100_M3_NO_REUSE_ABLATION_METHOD,
        model_config_name=args.model_config_name,
        csv_path=run_dir / BENCHMARK_RESULTS_CSV_NAME,
        json_path=run_dir / BENCHMARK_RESULTS_JSON_NAME,
        summary_path=run_dir / "evaluation_summary.json",
        paper_tables_path=run_dir / "paper_tables.md",
        manifest_path=run_dir / MANIFEST_NAME,
        resume=args.resume,
    )
    elapsed = time.perf_counter() - started
    source_document, source_cases = load_benchmark_document(args.benchmark)
    subset_cases = select_ctp100_two_turn_scenarios(source_cases)
    report = build_ctp100_m3_no_reuse_ablation_report(
        run_id=run_id,
        run_dir=run_dir,
        benchmark_path=args.benchmark,
        subset_path=subset_path,
        benchmark_document=source_document,
        subset_document=subset_document,
        cases=subset_cases,
        preflight=preflight,
        results=results,
        elapsed_seconds=elapsed,
        pre_formal_smoke=smoke,
    )
    _attach_ablation_metadata_to_manifest(run_dir, report=report, preflight=preflight)
    _write_ablation_report(run_dir, report)
    final_index = write_final_artifact_index(
        run_dir,
        artifact_files=_ablation_artifact_files(args.benchmark),
        manifest_name=MANIFEST_NAME,
    )
    payload = _payload(run_id, run_dir, report, final_index=final_index)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.strict_ablation_readiness and (
        report["status"] != "passed" or final_index["index_status"] != "passed"
    ):
        return 1
    return 0


def build_ctp100_m3_no_reuse_ablation_preflight(
    *,
    benchmark_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    repeats: int = CTP100_M3_NO_REUSE_DEFAULT_REPEATS,
    repeat_index_start: int = 0,
    method_order_seed: int = DEFAULT_FORMAL_METHOD_ORDER_SEED,
    model_config_name: str = DEFAULT_MODEL_CONFIG_NAME,
    resume: bool = False,
    require_clean_git: bool = False,
    frozen_ctp100_commit: str = CTP100_V6_FROZEN_COMMIT,
) -> Dict[str, Any]:
    benchmark_file = Path(benchmark_path)
    run_dir = _resolve_run_output_dir(output_dir, run_id)
    errors: List[str] = []
    warnings: List[str] = []
    document: Any = None
    source_cases: List[Dict[str, Any]] = []
    subset_cases: List[Dict[str, Any]] = []
    if not benchmark_file.exists():
        errors.append(f"benchmark file does not exist: {benchmark_file}")
    else:
        try:
            document, source_cases = load_benchmark_document(benchmark_file)
            subset_cases = select_ctp100_two_turn_scenarios(source_cases)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"benchmark file is invalid: {exc}")

    output_dir_has_contents = run_dir.exists() and any(run_dir.iterdir())
    if output_dir_has_contents and not resume:
        errors.append(f"output directory is not empty: {run_dir}")
    if int(repeats) != CTP100_M3_NO_REUSE_DEFAULT_REPEATS:
        errors.append("M3-no-reuse ablation requires repeats=3")
    if int(repeat_index_start) != 0:
        errors.append("M3-no-reuse ablation requires repeat_index_start=0")
    if len(subset_cases) != CTP100_M3_NO_REUSE_EXPECTED_SCENARIO_COUNT:
        errors.append(
            "two-turn scenario count mismatch: "
            f"expected {CTP100_M3_NO_REUSE_EXPECTED_SCENARIO_COUNT}, got {len(subset_cases)}"
        )
    turn_count = _turn_count(subset_cases)
    if turn_count != CTP100_M3_NO_REUSE_EXPECTED_TURN_COUNT:
        errors.append(
            "two-turn scenario turn count mismatch: "
            f"expected {CTP100_M3_NO_REUSE_EXPECTED_TURN_COUNT}, got {turn_count}"
        )

    git_status = _git_status_short()
    if require_clean_git and git_status:
        errors.append("git working tree must be clean before ablation run")
    if not _git_commit_exists(frozen_ctp100_commit):
        errors.append(f"cannot inspect frozen CTP100 commit: {frozen_ctp100_commit}")

    fixed_data_report = _validation_report(validate_fixed_data_snapshot)
    qweather_report = _validation_report(validate_qweather_snapshot)
    intercity_report = _validation_report(validate_intercity_transport_snapshot)
    budget_gold_report = _validation_report(validate_budget_gold, DEFAULT_CTP100_BUDGET_GOLD_PATH)
    for label, report in (
        ("fixed_data", fixed_data_report),
        ("qweather_snapshot", qweather_report),
        ("intercity_transport_snapshot", intercity_report),
        ("budget_gold", budget_gold_report),
    ):
        if report["status"] != "passed":
            errors.append(f"{label}: {report.get('error') or 'validation failed'}")

    environment_report = _environment_report(warnings=warnings)
    if not environment_report["api_key_configured"] and not environment_report["ollama_configured"]:
        errors.append("no LLM runtime configured; set LLM_API_KEY/LLM_BASE_URL/LLM_MODEL")

    expected_raw = turn_count * CTP100_M3_NO_REUSE_DEFAULT_REPEATS
    checks = {
        "benchmark_loadable": document is not None,
        "source_case_count_100": len(source_cases) == 100,
        "two_turn_scenario_count_30": len(subset_cases)
        == CTP100_M3_NO_REUSE_EXPECTED_SCENARIO_COUNT,
        "two_turn_total_turn_count_60": turn_count
        == CTP100_M3_NO_REUSE_EXPECTED_TURN_COUNT,
        "method_is_m3_no_reuse_only": True,
        "repeats_3": int(repeats) == CTP100_M3_NO_REUSE_DEFAULT_REPEATS,
        "repeat_index_start_0": int(repeat_index_start) == 0,
        "expected_result_count_180": expected_raw
        == CTP100_M3_NO_REUSE_EXPECTED_RESULTS,
        "output_directory_clean_or_resume": not output_dir_has_contents or bool(resume),
        "git_clean_if_required": not require_clean_git or not git_status,
        "frozen_ctp100_commit_available": _git_commit_exists(frozen_ctp100_commit),
        "fixed_data_valid": fixed_data_report["status"] == "passed",
        "qweather_snapshot_valid": qweather_report["status"] == "passed",
        "intercity_transport_snapshot_valid": intercity_report["status"] == "passed",
        "budget_gold_valid": budget_gold_report["status"] == "passed",
        "llm_runtime_configured": environment_report["api_key_configured"]
        or environment_report["ollama_configured"],
    }
    return {
        "schema_version": "ctp100-m3-no-reuse-ablation-preflight-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "benchmark": {
            "path": benchmark_file.as_posix(),
            "dataset_sha256": canonical_json_sha256(document)
            if document is not None
            else None,
            "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY
            if document is not None
            else None,
            "source_case_count": len(source_cases),
            "selected_two_turn_scenario_count": len(subset_cases),
            "selected_turn_count": turn_count,
            "selected_case_ids": [_case_id(case) for case in subset_cases],
        },
        "run": {
            "run_id": run_id,
            "output_dir": run_dir.as_posix(),
            "methods": [CTP100_M3_NO_REUSE_ABLATION_METHOD],
            "method_count": 1,
            "repeats": int(repeats),
            "repeat_index_start": int(repeat_index_start),
            "method_order_seed": int(method_order_seed),
            "model_config_name": model_config_name,
            "expected_raw_run_count": expected_raw,
        },
        "ablation_policy": {
            "paper_role": "M3 result-reuse ablation on all CTP100 two-turn scenarios",
            "source_main_run": "formal_ctp100_20260825_v6",
            "source_main_commit": frozen_ctp100_commit,
            "source_method": "adaptive_multi_agent",
            "ablation_method": CTP100_M3_NO_REUSE_ABLATION_METHOD,
            "keeps_goal_state_ticket": True,
            "keeps_method_local_previous_slots": True,
            "disables_previous_agent_outputs": True,
            "disables_previous_tool_results": True,
            "not_a_replacement_for_main_four_method_run": True,
        },
        "environment": environment_report,
        "fixed_data": fixed_data_report,
        "qweather_snapshot": qweather_report,
        "intercity_transport_snapshot": intercity_report,
        "budget_gold": budget_gold_report,
    }


def build_ctp100_m3_no_reuse_ablation_subset_document(
    *,
    benchmark_path: str | Path,
) -> Dict[str, Any]:
    benchmark_document, cases = load_benchmark_document(benchmark_path)
    subset_cases = select_ctp100_two_turn_scenarios(cases)
    return {
        "schema_version": "ctp100-m3-no-reuse-ablation-subset-v1",
        "dataset_id": "ctp100_m3_no_reuse_ablation_subset",
        "dataset_version": "2026-08-31-v1",
        "dataset_role": "supplemental_ablation_subset_from_ctp100_two_turn_scenarios",
        "source_dataset": {
            "path": Path(benchmark_path).as_posix(),
            "sha256": canonical_json_sha256(benchmark_document),
            "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
            "case_count": len(cases),
            "turn_count": _turn_count(cases),
        },
        "selection_policy": {
            "selected_unit": "all CTP100 scenarios with exactly two turns",
            "post_hoc_success_filtering": False,
            "selected_scenario_count": len(subset_cases),
            "selected_turn_count": _turn_count(subset_cases),
        },
        "cases": subset_cases,
    }


def select_ctp100_two_turn_scenarios(cases: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    for case in cases:
        turns = case.get("turns")
        if isinstance(turns, list) and len(turns) == 2:
            selected.append(dict(case))
    return selected


def build_ctp100_m3_no_reuse_ablation_report(
    *,
    run_id: str,
    run_dir: Path,
    benchmark_path: str | Path,
    subset_path: str | Path,
    benchmark_document: Mapping[str, Any],
    subset_document: Mapping[str, Any],
    cases: List[Dict[str, Any]],
    preflight: Mapping[str, Any],
    results: List[Dict[str, Any]],
    elapsed_seconds: float,
    pre_formal_smoke: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    traces = _load_traces(run_dir, results)
    expected_result_count = int(_mapping(preflight.get("run")).get("expected_raw_run_count") or 0)
    method_counts = Counter(str(result.get("method") or "unknown") for result in results)
    status_counts = Counter(str(result.get("status") or "unknown") for result in results)
    repeat_indices = sorted(
        {
            int(result.get("repeat_index"))
            for result in results
            if isinstance(result.get("repeat_index"), int)
        }
    )
    grid = _method_repeat_grid(
        results,
        expected_repeat_indices=[0, 1, 2],
    )
    trace_audit = _trace_audit(traces)
    no_reuse_audit = _no_reuse_audit(results)
    previous_state_audit = _previous_state_audit(results)
    quality_summary = _quality_summary(results)
    failure_classification = _failure_classification_summary(run_dir, results)
    api_failure_timeout = _api_failure_timeout_summary(traces)
    hard_timeout_result_count = sum(
        1 for result in results if bool(result.get("hard_timeout_triggered"))
    )
    failed_results = [
        _result_identity(result)
        for result in results
        if str(result.get("status") or "").lower() not in {"completed", "clarification"}
    ]
    checks = {
        "preflight_passed": preflight.get("status") == "passed",
        "expected_result_count": len(results) == expected_result_count,
        "method_is_m3_no_reuse_only": set(method_counts)
        == {CTP100_M3_NO_REUSE_ABLATION_METHOD},
        "method_count_180": method_counts.get(CTP100_M3_NO_REUSE_ABLATION_METHOD, 0)
        == CTP100_M3_NO_REUSE_EXPECTED_RESULTS,
        "repeat_indices_0_1_2": repeat_indices == [0, 1, 2],
        "method_repeat_grid_complete": grid["missing_count"] == 0
        and grid["duplicate_count"] == 0,
        "trace_count_matches_results": trace_audit["trace_file_count"] == len(results),
        "llm_calls_recorded": trace_audit["llm_call_count"] > 0 if results else False,
        "no_mock_calls": trace_audit["mock_call_count"] == 0,
        "no_fallback_calls": trace_audit["fallback_call_count"] == 0,
        "no_hard_timeout": hard_timeout_result_count == 0
        and api_failure_timeout.get("terminal_failure_count") == 0,
        "previous_slots_available_on_second_turns": previous_state_audit[
            "second_turn_slots_missing_count"
        ]
        == 0,
        "no_reused_agents_recorded": no_reuse_audit["reused_agent_violation_count"] == 0,
        "no_reused_tool_results_recorded": no_reuse_audit[
            "reused_tool_result_violation_count"
        ]
        == 0,
        "previous_artifacts_stripped": no_reuse_audit[
            "previous_artifacts_after_strip_violation_count"
        ]
        == 0,
        "no_agent_outputs_marked_reused": no_reuse_audit[
            "agent_output_reuse_violation_count"
        ]
        == 0,
    }
    failed_checks = [key for key, passed in checks.items() if not passed]
    return {
        "schema_version": CTP100_M3_NO_REUSE_ABLATION_REPORT_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if not failed_checks else "failed",
        "run_id": run_id,
        "elapsed_seconds": round(float(elapsed_seconds), 3),
        "benchmark": {
            "source_path": Path(benchmark_path).as_posix(),
            "source_dataset_id": benchmark_document.get("dataset_id"),
            "source_dataset_version": benchmark_document.get("dataset_version"),
            "source_dataset_sha256": canonical_json_sha256(benchmark_document),
            "subset_path": Path(subset_path).as_posix(),
            "subset_dataset_id": subset_document.get("dataset_id"),
            "subset_dataset_sha256": canonical_json_sha256(subset_document),
            "hash_strategy": CANONICAL_JSON_SHA256_STRATEGY,
            "selected_scenario_count": len(cases),
            "selected_turn_count": _turn_count(cases),
            "selection_policy": _mapping(subset_document.get("selection_policy")),
        },
        "results": {
            "expected_raw_result_count": expected_result_count,
            "actual_raw_result_count": len(results),
            "method_counts": dict(sorted(method_counts.items())),
            "status_counts": dict(sorted(status_counts.items())),
            "repeat_indices": repeat_indices,
            "failed_result_count": len(failed_results),
            "failed_results": failed_results[:20],
        },
        "quality_summary": quality_summary,
        "method_grid": grid,
        "previous_state_audit": previous_state_audit,
        "no_reuse_audit": no_reuse_audit,
        "trace_audit": trace_audit,
        "failure_classification_summary": failure_classification,
        "api_failure_timeout_summary": api_failure_timeout,
        "hard_timeout_result_count": hard_timeout_result_count,
        "checks": checks,
        "failed_checks": failed_checks,
        "preflight": {
            "path": (run_dir / PREFLIGHT_NAME).as_posix(),
            "status": preflight.get("status"),
        },
        "pre_formal_real_api_smoke": _jsonable_mapping(pre_formal_smoke),
        "paper_interpretation": {
            "claim_scope": (
                "This run estimates the contribution of M3 result reuse on the "
                "frozen CTP100 two-turn subset. It must be compared with the "
                "three-repeat full M3 rows and must not replace the CTP100 main run."
            ),
            "quality_failures_are_results_not_gate_failures": True,
        },
    }


def render_ctp100_m3_no_reuse_ablation_report(report: Mapping[str, Any]) -> str:
    checks = _mapping(report.get("checks"))
    lines = [
        "# CTP100 M3-no-reuse Ablation Report",
        "",
        f"- status: `{report.get('status')}`",
        f"- run_id: `{report.get('run_id')}`",
        f"- elapsed_seconds: `{report.get('elapsed_seconds')}`",
        "",
        "## Structural gate",
        "",
        "| check | passed |",
        "| --- | --- |",
    ]
    for key, value in checks.items():
        lines.append(f"| {key} | `{bool(value)}` |")
    results = _mapping(report.get("results"))
    quality = _mapping(report.get("quality_summary"))
    no_reuse = _mapping(report.get("no_reuse_audit"))
    previous = _mapping(report.get("previous_state_audit"))
    lines.extend(
        [
            "",
            "## Result counts",
            "",
            f"- expected_raw_result_count: `{results.get('expected_raw_result_count')}`",
            f"- actual_raw_result_count: `{results.get('actual_raw_result_count')}`",
            f"- method_counts: `{results.get('method_counts')}`",
            f"- repeat_indices: `{results.get('repeat_indices')}`",
            "",
            "## Quality summary",
            "",
            f"- mean_stsr: `{quality.get('mean_stsr')}`",
            f"- mean_hcsr: `{quality.get('mean_hcsr')}`",
            f"- quality_unit_count: `{quality.get('quality_unit_count')}`",
            "",
            "## No-reuse audit",
            "",
            f"- reused_agent_violation_count: `{no_reuse.get('reused_agent_violation_count')}`",
            f"- reused_tool_result_violation_count: `{no_reuse.get('reused_tool_result_violation_count')}`",
            f"- previous_artifacts_after_strip_violation_count: `{no_reuse.get('previous_artifacts_after_strip_violation_count')}`",
            f"- agent_output_reuse_violation_count: `{no_reuse.get('agent_output_reuse_violation_count')}`",
            "",
            "## Previous-state audit",
            "",
            f"- second_turn_count: `{previous.get('second_turn_count')}`",
            f"- second_turn_slots_missing_count: `{previous.get('second_turn_slots_missing_count')}`",
            f"- previous_state_not_method_local_count: `{previous.get('not_method_local_count')}`",
            "",
        ]
    )
    failed = report.get("failed_checks") or []
    if failed:
        lines.extend(["## Failed checks", ""])
        lines.extend(f"- `{item}`" for item in failed)
        lines.append("")
    return "\n".join(lines)


def _attach_ablation_metadata_to_manifest(
    run_dir: Path,
    *,
    report: Mapping[str, Any],
    preflight: Mapping[str, Any],
) -> None:
    manifest_path = run_dir / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    manifest["m3_no_reuse_ablation"] = {
        "schema_version": CTP100_M3_NO_REUSE_ABLATION_REPORT_SCHEMA_VERSION,
        "status": report.get("status"),
        "failed_checks": report.get("failed_checks") or [],
        "paper_role": "M3 result-reuse ablation on CTP100 two-turn scenarios",
        "source_main_run": "formal_ctp100_20260825_v6",
        "source_main_commit": CTP100_V6_FROZEN_COMMIT,
        "method": CTP100_M3_NO_REUSE_ABLATION_METHOD,
        "preflight_sha256": canonical_json_sha256(preflight),
    }
    _write_json(manifest_path, manifest)


def _write_ablation_report(run_dir: Path, report: Mapping[str, Any]) -> None:
    _write_json(run_dir / REPORT_JSON_NAME, report)
    (run_dir / REPORT_MD_NAME).write_text(
        render_ctp100_m3_no_reuse_ablation_report(report),
        encoding="utf-8",
    )


def _ablation_artifact_files(benchmark_path: str | Path) -> Dict[str, str | Path]:
    return {
        "ctp100_benchmark_source": Path(benchmark_path),
        "ablation_subset": SUBSET_NAME,
        "ablation_preflight": PREFLIGHT_NAME,
        "benchmark_results_csv": BENCHMARK_RESULTS_CSV_NAME,
        "benchmark_results_json": BENCHMARK_RESULTS_JSON_NAME,
        "benchmark_results_checkpoint_csv": BENCHMARK_CHECKPOINT_CSV_NAME,
        "benchmark_results_checkpoint_json": BENCHMARK_CHECKPOINT_JSON_NAME,
        "evaluation_summary": "evaluation_summary.json",
        "paper_tables": "paper_tables.md",
        "experiment_manifest": MANIFEST_NAME,
        "benchmark_resume_state": BENCHMARK_RESUME_STATE_NAME,
        "ablation_gate": REPORT_JSON_NAME,
        "ablation_report": REPORT_MD_NAME,
    }


def _payload(
    run_id: str,
    run_dir: Path,
    report: Mapping[str, Any],
    *,
    final_index: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    results = _mapping(report.get("results"))
    payload = {
        "status": report.get("status"),
        "run_id": run_id,
        "output_dir": run_dir.as_posix(),
        "result_count": results.get("actual_raw_result_count"),
        "expected_count": results.get("expected_raw_result_count"),
        "ablation_gate": (run_dir / REPORT_JSON_NAME).as_posix(),
        "ablation_report": (run_dir / REPORT_MD_NAME).as_posix(),
        "manifest": (run_dir / MANIFEST_NAME).as_posix(),
        "checkpoint_json": (run_dir / BENCHMARK_CHECKPOINT_JSON_NAME).as_posix(),
        "checkpoint_csv": (run_dir / BENCHMARK_CHECKPOINT_CSV_NAME).as_posix(),
        "traces": (run_dir / "traces").as_posix(),
        "failed_checks": report.get("failed_checks") or [],
    }
    if final_index:
        payload["final_artifact_index_json"] = final_index.get("json")
        payload["final_artifact_index_status"] = final_index.get("index_status")
    return payload


def _no_reuse_audit(results: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    reused_agent_violations: List[Dict[str, Any]] = []
    reused_tool_violations: List[Dict[str, Any]] = []
    stripped_artifact_violations: List[Dict[str, Any]] = []
    agent_output_reuse_violations: List[Dict[str, Any]] = []
    for result in results:
        metrics = _mapping(result.get("metrics"))
        output = _mapping(result.get("output"))
        scheduler = _mapping(_nested_mapping(output, "metadata", "adaptive_scheduler"))
        reuse_execution = _mapping(scheduler.get("reuse_execution"))
        ablation = _mapping(scheduler.get("ablation"))
        reused_agents = _as_list(metrics.get("m3_reused_agents")) or _as_list(
            reuse_execution.get("reused_agent_results")
        )
        reused_tools = _as_list(metrics.get("m3_reused_tool_results")) or _as_list(
            reuse_execution.get("reused_tool_results")
        )
        if reused_agents or int(metrics.get("m3_reused_agent_count") or 0) != 0:
            reused_agent_violations.append(_result_identity(result))
        if reused_tools or int(metrics.get("m3_reused_tool_result_count") or 0) != 0:
            reused_tool_violations.append(_result_identity(result))
        if ablation.get("previous_artifacts_available_after_strip") is True:
            stripped_artifact_violations.append(_result_identity(result))
        agent_outputs = _mapping(output.get("agent_outputs"))
        reused_output_names = [
            name
            for name, item in agent_outputs.items()
            if isinstance(item, Mapping) and item.get("reused") is True
        ]
        if reused_output_names:
            identity = _result_identity(result)
            identity["reused_agent_outputs"] = reused_output_names
            agent_output_reuse_violations.append(identity)
    return {
        "schema_version": "ctp100-m3-no-reuse-audit-v1",
        "reused_agent_violation_count": len(reused_agent_violations),
        "reused_tool_result_violation_count": len(reused_tool_violations),
        "previous_artifacts_after_strip_violation_count": len(stripped_artifact_violations),
        "agent_output_reuse_violation_count": len(agent_output_reuse_violations),
        "sample_reused_agent_violations": reused_agent_violations[:20],
        "sample_reused_tool_result_violations": reused_tool_violations[:20],
        "sample_previous_artifact_violations": stripped_artifact_violations[:20],
        "sample_agent_output_reuse_violations": agent_output_reuse_violations[:20],
    }


def _previous_state_audit(results: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    second_turns = [
        result
        for result in results
        if str(result.get("turn_id") or "").strip().lower() in {"t2", "turn_02", "2"}
        or int(result.get("turn_index") or 0) == 1
    ]
    slots_missing: List[Dict[str, Any]] = []
    not_method_local: List[Dict[str, Any]] = []
    not_prior_turn: List[Dict[str, Any]] = []
    for result in second_turns:
        output = _mapping(result.get("output"))
        scheduler = _mapping(_nested_mapping(output, "metadata", "adaptive_scheduler"))
        ablation = _mapping(scheduler.get("ablation"))
        if not ablation.get("uses_previous_slots"):
            slots_missing.append(_result_identity(result))
        if result.get("previous_state_is_method_local") is not True:
            not_method_local.append(_result_identity(result))
        if result.get("previous_state_is_prior_turn") is not True:
            not_prior_turn.append(_result_identity(result))
    return {
        "schema_version": "ctp100-m3-no-reuse-previous-state-audit-v1",
        "second_turn_count": len(second_turns),
        "second_turn_slots_missing_count": len(slots_missing),
        "not_method_local_count": len(not_method_local),
        "not_prior_turn_count": len(not_prior_turn),
        "sample_slots_missing": slots_missing[:20],
        "sample_not_method_local": not_method_local[:20],
        "sample_not_prior_turn": not_prior_turn[:20],
    }


def _quality_summary(results: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = list(results)
    stsr_values = [
        float(value)
        for value in (_nested_value(row, "metrics", "stsr") for row in rows)
        if isinstance(value, (int, float))
    ]
    hcsr_values = [
        float(value)
        for value in (_nested_value(row, "metrics", "hcsr") for row in rows)
        if isinstance(value, (int, float))
    ]
    return {
        "schema_version": "ctp100-m3-no-reuse-quality-summary-v1",
        "quality_unit_count": len(stsr_values),
        "mean_stsr": round(sum(stsr_values) / len(stsr_values), 6)
        if stsr_values
        else None,
        "mean_hcsr": round(sum(hcsr_values) / len(hcsr_values), 6)
        if hcsr_values
        else None,
        "stsr_success_count": int(sum(1 for value in stsr_values if value >= 1.0)),
        "hcsr_success_count": int(sum(1 for value in hcsr_values if value >= 1.0)),
    }


def _method_repeat_grid(
    results: Iterable[Mapping[str, Any]],
    *,
    expected_repeat_indices: Sequence[int],
) -> Dict[str, Any]:
    seen = Counter()
    for result in results:
        key = (
            str(result.get("case_id") or result.get("scenario_id") or ""),
            str(result.get("turn_id") or ""),
            str(result.get("method") or ""),
            int(result.get("repeat_index") or 0),
        )
        seen[key] += 1
    expected_keys = []
    for repeat_index in expected_repeat_indices:
        for case_id, turn_id in _expected_case_turn_keys_from_results(results):
            expected_keys.append(
                (
                    case_id,
                    turn_id,
                    CTP100_M3_NO_REUSE_ABLATION_METHOD,
                    int(repeat_index),
                )
            )
    missing = [key for key in expected_keys if key not in seen]
    duplicates = [
        {"case_id": key[0], "turn_id": key[1], "method": key[2], "repeat_index": key[3], "count": count}
        for key, count in seen.items()
        if count > 1
    ]
    return {
        "schema_version": "ctp100-m3-no-reuse-method-grid-v1",
        "expected_count": len(expected_keys),
        "actual_unique_count": len(seen),
        "missing_count": len(missing),
        "duplicate_count": len(duplicates),
        "sample_missing": [
            {"case_id": key[0], "turn_id": key[1], "method": key[2], "repeat_index": key[3]}
            for key in missing[:20]
        ],
        "sample_duplicates": duplicates[:20],
    }


def _expected_case_turn_keys_from_results(
    results: Iterable[Mapping[str, Any]],
) -> List[tuple[str, str]]:
    pairs = {
        (
            str(result.get("case_id") or result.get("scenario_id") or ""),
            str(result.get("turn_id") or ""),
        )
        for result in results
    }
    return sorted(pair for pair in pairs if pair[0])


def _trace_audit(traces: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = list(traces)
    llm_calls = [
        call
        for trace in rows
        for call in trace.get("llm_calls", [])
        if isinstance(call, Mapping)
    ]
    return {
        "schema_version": "ctp100-m3-no-reuse-trace-audit-v1",
        "trace_file_count": len(rows),
        "llm_call_count": len(llm_calls),
        "mock_call_count": sum(1 for call in llm_calls if call.get("mock") is True),
        "fallback_call_count": sum(1 for call in llm_calls if call.get("fallback") is True),
    }


def _result_identity(result: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "case_id": result.get("case_id") or result.get("scenario_id"),
        "turn_id": result.get("turn_id"),
        "method": result.get("method"),
        "repeat_index": result.get("repeat_index"),
        "status": result.get("status"),
    }


def _validation_report(func: Any, *args: Any) -> Dict[str, Any]:
    try:
        payload = func(*args)
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}
    status = "passed"
    if isinstance(payload, Mapping) and payload.get("status") in {"failed", "error"}:
        status = "failed"
    return {"status": status, "payload": _jsonable_value(payload)}


def _budget_gold_file_sha256() -> Optional[str]:
    try:
        document = json.loads(DEFAULT_CTP100_BUDGET_GOLD_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return canonical_json_sha256(document)


def _budget_gold_review_status() -> Optional[str]:
    try:
        document = json.loads(DEFAULT_CTP100_BUDGET_GOLD_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = document.get("review_status") if isinstance(document, Mapping) else None
    return str(value) if value is not None else None


def _budget_gold_artifact_hashes() -> Dict[str, Any]:
    try:
        document = json.loads(DEFAULT_CTP100_BUDGET_GOLD_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    hashes = document.get("artifact_hashes") if isinstance(document, Mapping) else None
    return dict(hashes) if isinstance(hashes, Mapping) else {}


def _environment_report(*, warnings: List[str]) -> Dict[str, Any]:
    base_url = os.getenv("LLM_BASE_URL") or settings.llm.base_url
    model = os.getenv("LLM_MODEL") or settings.llm.model
    api_key_configured = bool(os.getenv("LLM_API_KEY") or settings.llm.is_configured)
    ollama_configured = bool(os.getenv("OLLAMA_MODEL"))
    if "vectorengine.ai" not in str(base_url):
        warnings.append("LLM_BASE_URL is not VectorEngine; verify this is intentional")
    return {
        "schema_version": "ctp100-m3-no-reuse-runtime-env-v1",
        "base_url": str(base_url),
        "model": str(model),
        "api_key_configured": api_key_configured,
        "ollama_configured": ollama_configured,
        "temperature": os.getenv("LLM_TEMPERATURE") or str(settings.llm.temperature),
        "max_tokens": os.getenv("LLM_MAX_TOKENS") or str(settings.llm.max_tokens),
        "timeout": os.getenv("LLM_TIMEOUT") or str(settings.llm.timeout),
        "strict_mode": os.getenv("EXPERIMENT_STRICT_MODE"),
        "cache_disabled": os.getenv("EXPERIMENT_DISABLE_CACHE"),
    }


def _turn_count(cases: Iterable[Mapping[str, Any]]) -> int:
    total = 0
    for case in cases:
        turns = case.get("turns")
        total += len(turns) if isinstance(turns, list) and turns else 1
    return total


def _case_id(case: Mapping[str, Any]) -> str:
    return str(case.get("case_id") or case.get("scenario_id") or case.get("id") or "")


def _resolve_run_output_dir(output_dir: str | Path, run_id: str) -> Path:
    root = Path(output_dir)
    return root if root.name == run_id else root / run_id


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _raise_ablation_preflight_error(preflight: Mapping[str, Any]) -> None:
    errors = preflight.get("errors") or []
    message = "CTP100 M3-no-reuse ablation preflight failed"
    if errors:
        message += ":\n" + "\n".join(f"- {error}" for error in errors)
    raise RuntimeError(message)


def _git_status_short() -> List[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        return ["<git status unavailable>"]
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip()


def _git_commit_exists(commit: str) -> bool:
    if not str(commit or "").strip():
        return False
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def _jsonable_mapping(value: Any) -> Dict[str, Any]:
    return _jsonable_value(value) if isinstance(value, Mapping) else {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nested_mapping(value: Any, *path: str) -> Any:
    current = value
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


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    if isinstance(value, str):
        return [item.strip() for item in value.split("|") if item.strip()]
    return [value]


def _jsonable_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable_value(item) for item in value]
    return value


def _validate_repeats_local(value: Any) -> int:
    try:
        repeats = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("repeats must be a positive integer") from exc
    if repeats < 1:
        raise ValueError("repeats must be a positive integer")
    return repeats


def _environment_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return int(default)
    try:
        return int(value)
    except ValueError:
        return int(default)


def _environment_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return float(default)
    try:
        return float(value)
    except ValueError:
        return float(default)


def _environment_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return bool(default)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
