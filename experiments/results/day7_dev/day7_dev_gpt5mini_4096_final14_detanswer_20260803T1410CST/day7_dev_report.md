# Day 7 开发集真实实验验收报告

## 结论

- gate_status: `passed`
- paper_claims_allowed: `False`
- run_id: `day7_dev_gpt5mini_4096_final14_detanswer_20260803T1410CST`
- dataset: `ctp120_dev` / `2026-07-31-zh`
- expected_raw_results: `104`
- actual_raw_results: `104`
- csv_rows: `104`
- trace_files: `104`
- loaded_traces: `104`
- runtime_consistent_with_manifest: `True`
- runtime_matches_day7_max_tokens_protocol: `True`
- completion_token_cap_hit_rate: `0.0`
- empty_and_token_capped_call_count: `0`
- infrastructure_failure_rate: `0.0096`
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
| llm_direct | 26 |
| single_agent | 26 |
| fixed_multi_agent | 26 |
| adaptive_multi_agent | 26 |

- raw_turn_unit_count: `26`
- incomplete_unit_count: `0`
- duplicate_unit_method_count: `0`

## 字段完整率

| Field group | Complete | Complete rows | Total rows | Rate |
|---|---:|---:|---:|---:|
| token_latency | `True` | 104 | 104 | 1.0 |
| cost_for_llm_rows | `True` | 94 | 94 | 1.0 |

## Trace / Mock / Fallback / Cache

- llm_call_count: `216`
- mock_llm_call_count: `0`
- fallback_llm_call_count: `0`
- cache_hit_count: `0`
- total_tokens: `758203.0`
- standardized_estimated_cost: `0.6122`

## Output length risk

- completion_token_cap_hit_count: `0`
- completion_token_cap_hit_rate: `0.0`
- completion_token_cap_hit_rate_limit: `0.05`
- empty_output_call_count: `34`
- empty_and_token_capped_call_count: `0`
- request_max_token_values: `{'4096': 216}`

## 多轮状态隔离

- expected_scenario_case_count: `6`
- observed_scenario_case_count: `6`
- checked_method_scenario_count: `24`
- violation_count: `0`

## 基础设施失败

- failed_result_count: `1`
- failed_llm_call_count: `1`
- failure_rate: `0.0096`

## 产物哈希

| Artifact | SHA-256 | Path |
|---|---|---|
| csv | `079bf265fae666c88f497fbd38f78facae651d10113a300bf29d9f8bd7eab0a8` | `experiments/results/day7_dev/day7_dev_gpt5mini_4096_final14_detanswer_20260803T1410CST/benchmark_results.csv` |
| json | `30d789c39777500c8df9ee8ec153e3a5465d0bba8efdb132e9a81cc166972094` | `experiments/results/day7_dev/day7_dev_gpt5mini_4096_final14_detanswer_20260803T1410CST/benchmark_results.json` |
| summary | `17f4fe62e7419acb284b3729165b19132f013072737e6ee49386f29b08d9fc99` | `experiments/results/day7_dev/day7_dev_gpt5mini_4096_final14_detanswer_20260803T1410CST/evaluation_summary.json` |
| paper_tables | `940d14c5a43b728cce3f884ab430d8f84844845dfebb474359848598958451fd` | `experiments/results/day7_dev/day7_dev_gpt5mini_4096_final14_detanswer_20260803T1410CST/paper_tables.md` |
| manifest | `c6d9f7010636d51b20e524294123bc72d6d9c110fabc5f04eb5b01528f46f554` | `experiments/results/day7_dev/day7_dev_gpt5mini_4096_final14_detanswer_20260803T1410CST/experiment_manifest.json` |
| day7_dev_preflight | `5113d3bfe5f708cc22e8e9f6d23bedf56c4bbb2a942c1f945c74554481994bd0` | `experiments/results/day7_dev/day7_dev_gpt5mini_4096_final14_detanswer_20260803T1410CST/day7_dev_preflight_report.json` |
