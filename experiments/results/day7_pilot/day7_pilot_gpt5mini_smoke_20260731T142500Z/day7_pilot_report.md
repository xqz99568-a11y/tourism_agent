# Day 7 pilot report

## Conclusion

- status: `passed`
- run_id: `day7_pilot_gpt5mini_smoke_20260731T142500Z`
- top_level_case_count: `8`
- total_turn_count: `10`
- method_count: `4`
- expected_trace_count: `40`
- actual_trace_file_count: `40`
- expected_result_count: `40`
- actual_result_count: `40`
- llm_call_count: `69`
- total_tokens: `178107.0`
- estimated_cost: `0.0`
- result_status_counts: `{'failed': 32, 'clarification': 6, 'completed': 2}`
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
| adaptive_multi_agent | 10 | 0.0 | 0.69 | 0.6067 | 18.0 | 43418.0 | 0.0 |
| fixed_multi_agent | 10 | 0.0 | 0.7324 | 0.6233 | 21.0 | 49325.0 | 0.0 |
| llm_direct | 10 | 0.0 | 0.2 | 0.2 | 10.0 | 18055.0 | 0.0 |
| single_agent | 10 | 0.0 | 0.0 | 0.8967 | 20.0 | 67309.0 | 0.0 |

## Artifact paths

| artifact | path |
|---|---|
| pilot_benchmark | `D:/Code/Tourism_Agent/experiments/results/day7_pilot/_day7_pilot_inputs/day7_pilot_gpt5mini_smoke_20260731T142500Z_day7_pilot_benchmark.json` |
| preflight | `D:/Code/Tourism_Agent/experiments/results/day7_pilot/day7_pilot_gpt5mini_smoke_20260731T142500Z/day7_pilot_preflight_report.json` |
| benchmark_results.csv | `D:/Code/Tourism_Agent/experiments/results/day7_pilot/day7_pilot_gpt5mini_smoke_20260731T142500Z/benchmark_results.csv` |
| benchmark_results.json | `D:/Code/Tourism_Agent/experiments/results/day7_pilot/day7_pilot_gpt5mini_smoke_20260731T142500Z/benchmark_results.json` |
| evaluation_summary.json | `D:/Code/Tourism_Agent/experiments/results/day7_pilot/day7_pilot_gpt5mini_smoke_20260731T142500Z/evaluation_summary.json` |
| paper_tables.md | `D:/Code/Tourism_Agent/experiments/results/day7_pilot/day7_pilot_gpt5mini_smoke_20260731T142500Z/paper_tables.md` |
| experiment_manifest.json | `D:/Code/Tourism_Agent/experiments/results/day7_pilot/day7_pilot_gpt5mini_smoke_20260731T142500Z/experiment_manifest.json` |
| trace_dir | `D:/Code/Tourism_Agent/experiments/results/day7_pilot/day7_pilot_gpt5mini_smoke_20260731T142500Z/traces` |
