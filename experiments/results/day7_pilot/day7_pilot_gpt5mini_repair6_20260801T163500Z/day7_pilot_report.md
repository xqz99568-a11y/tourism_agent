# Day 7 pilot report

## Conclusion

- status: `passed`
- run_id: `day7_pilot_gpt5mini_repair6_20260801T163500Z`
- top_level_case_count: `8`
- total_turn_count: `10`
- method_count: `4`
- expected_trace_count: `40`
- actual_trace_file_count: `40`
- expected_result_count: `40`
- actual_result_count: `40`
- llm_call_count: `98`
- total_tokens: `419502.0`
- estimated_cost: `0.0`
- result_status_counts: `{'completed': 35, 'failed': 3, 'clarification': 2}`
- result_error_count: `0`
- failed_checks: `[]`

## Gate checks

| check | passed |
|---|---:|
| preflight_passed | `True` |
| result_count_matches | `True` |
| csv_row_count_matches | `True` |
| pilot_case_count_matches_preflight | `True` |
| pilot_turn_count_matches_preflight | `True` |
| request_level_trace_count_matches | `True` |
| loaded_trace_count_matches | `True` |
| required_result_files_saved | `True` |
| preflight_report_saved | `True` |
| pilot_benchmark_saved | `True` |
| trace_files_saved | `True` |
| run_audit_attached | `True` |
| metric_fields_present | `True` |
| llm_call_recorded | `True` |
| runtime_audit_recorded | `True` |
| no_llm_fallback_recorded | `True` |
| mock_policy_satisfied | `True` |
| strict_runtime_recorded | `True` |
| cache_disabled_recorded | `True` |
| user_message_not_persisted | `True` |

## Method metric summary

| method | runs | STSR | Agent F1 | Tool F1 | LLM calls | Tokens | Cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| adaptive_multi_agent | 10 | 1.0 | 1.0 | 1.0 | 29.0 | 130811.0 | 0.0 |
| fixed_multi_agent | 10 | 0.4 | 0.7724 | 0.78 | 41.0 | 193866.0 | 0.0 |
| llm_direct | 10 | 0.1 | 0.2 | 0.2 | 10.0 | 28563.0 | 0.0 |
| single_agent | 10 | 0.1 | 0.0 | 0.55 | 18.0 | 66262.0 | 0.0 |

## Artifact paths

| artifact | path |
|---|---|
| pilot_benchmark | `experiments/results/day7_pilot/_day7_pilot_inputs/day7_pilot_gpt5mini_repair6_20260801T163500Z_day7_pilot_benchmark.json` |
| preflight | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/day7_pilot_preflight_report.json` |
| benchmark_results.csv | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/benchmark_results.csv` |
| benchmark_results.json | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/benchmark_results.json` |
| evaluation_summary.json | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/evaluation_summary.json` |
| paper_tables.md | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/paper_tables.md` |
| experiment_manifest.json | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/experiment_manifest.json` |
| trace_dir | `experiments/results/day7_pilot/day7_pilot_gpt5mini_repair6_20260801T163500Z/traces` |
