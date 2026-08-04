# Day 7 开发集真实实验验收报告

## 结论

- gate_status: `passed`
- paper_claims_allowed: `False`
- run_id: `day7_m3_no_normalizer_gpt5mini_final_20260803T1515CST`
- dataset: `ctp120_dev` / `2026-07-31-zh`
- expected_raw_results: `26`
- actual_raw_results: `26`
- csv_rows: `26`
- trace_files: `26`
- loaded_traces: `26`
- runtime_consistent_with_manifest: `True`
- runtime_matches_day7_max_tokens_protocol: `True`
- completion_token_cap_hit_rate: `0.0`
- empty_and_token_capped_call_count: `0`
- infrastructure_failure_rate: `0.0`
- multi_turn_state_isolation: `True`
- failed_checks: `[]`

## 核心验收项

| Check | Passed |
|---|---:|
| run_dir_exists | `True` |
| core_artifacts_saved | `True` |
| day7_dev_preflight_saved | `True` |
| day7_dev_preflight_schema_valid | `True` |
| day7_dev_preflight_passed | `True` |
| case_count_matches | `True` |
| turn_count_matches | `True` |
| scenario_case_count_matches | `True` |
| result_count_matches | `True` |
| csv_row_count_matches | `True` |
| summary_raw_run_count_matches | `True` |
| summary_result_count_matches | `True` |
| method_counts_match | `True` |
| required_methods_present | `True` |
| raw_turn_pairing_complete | `True` |
| quality_pairing_present | `True` |
| request_level_trace_count_matches | `True` |
| loaded_trace_count_matches | `True` |
| run_audit_attached | `True` |
| runtime_audit_consistent | `True` |
| runtime_matches_day7_max_tokens_protocol | `True` |
| strict_runtime_recorded | `True` |
| cache_disabled_recorded | `True` |
| deterministic_research_final_answer_recorded | `True` |
| no_mock_llm | `True` |
| no_llm_fallback | `True` |
| no_cache_hit | `True` |
| token_latency_fields_complete | `True` |
| cost_fields_complete_for_llm_rows | `True` |
| multi_turn_state_isolation_passed | `True` |
| infrastructure_failure_rate_below_5pct | `True` |
| completion_token_cap_hit_rate_below_limit | `True` |
| no_empty_outputs_at_token_cap | `True` |
| artifact_hashes_recorded | `True` |

## 四方法逐轮配对

| Method | Result count |
|---|---:|
| adaptive_multi_agent | 26 |

- raw_turn_unit_count: `26`
- incomplete_unit_count: `0`
- duplicate_unit_method_count: `0`

## 字段完整率

| Field group | Complete | Complete rows | Total rows | Rate |
|---|---:|---:|---:|---:|
| token_latency | `True` | 26 | 26 | 1.0 |
| cost_for_llm_rows | `True` | 22 | 22 | 1.0 |

## Trace / Mock / Fallback / Cache

- llm_call_count: `52`
- mock_llm_call_count: `0`
- fallback_llm_call_count: `0`
- cache_hit_count: `0`
- total_tokens: `169745.0`
- standardized_estimated_cost: `0.1576`

## Output length risk

- completion_token_cap_hit_count: `0`
- completion_token_cap_hit_rate: `0.0`
- completion_token_cap_hit_rate_limit: `0.05`
- empty_output_call_count: `0`
- empty_and_token_capped_call_count: `0`
- request_max_token_values: `{'4096': 52}`

## 多轮状态隔离

- expected_scenario_case_count: `6`
- observed_scenario_case_count: `6`
- checked_method_scenario_count: `6`
- violation_count: `0`

## 基础设施失败

- failed_result_count: `0`
- failed_llm_call_count: `0`
- failure_rate: `0.0`

## 产物哈希

| Artifact | SHA-256 | Path |
|---|---|---|
| csv | `123072bd2a13113c4ab43642bdee4f6f549a0a5b99e67fbd2b33a100716a0094` | `experiments/results/day7_m3_ablation/day7_m3_no_normalizer_gpt5mini_final_20260803T1515CST/benchmark_results.csv` |
| json | `e2df93019a476d46a01f29d4e3a381b723536ef0244ae5853955bd20ecac09d8` | `experiments/results/day7_m3_ablation/day7_m3_no_normalizer_gpt5mini_final_20260803T1515CST/benchmark_results.json` |
| summary | `4138e0a2a0f45c241e57f3e78a3ba5b758220d7a2754b92155df6b333ded54a9` | `experiments/results/day7_m3_ablation/day7_m3_no_normalizer_gpt5mini_final_20260803T1515CST/evaluation_summary.json` |
| paper_tables | `0681952e20a1d25dc75769e86f1430dd8d67a8ae4d35ff2aefe5767f68230baf` | `experiments/results/day7_m3_ablation/day7_m3_no_normalizer_gpt5mini_final_20260803T1515CST/paper_tables.md` |
| manifest | `bb57edc877a3a464f4a74ea2b9e2f3a6c58783993da8d2e2148b8b33f79627fb` | `experiments/results/day7_m3_ablation/day7_m3_no_normalizer_gpt5mini_final_20260803T1515CST/experiment_manifest.json` |
| day7_dev_preflight | `7cb0523c4154f817c72472607aa8f109781c2ac49865a3e87170835515bb652b` | `experiments/results/day7_m3_ablation/day7_m3_no_normalizer_gpt5mini_final_20260803T1515CST/day7_dev_preflight_report.json` |
