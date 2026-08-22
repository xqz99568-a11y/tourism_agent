# Task E Four-Method Real API Validation Report

- status: `passed`
- run_id: `task_e_four_method_real_api_final3_20260821T123500Z`
- expected_result_count: `80`
- actual_result_count: `80`
- result_status_counts: `{'clarification': 9, 'completed': 71}`
- method_counts: `{'adaptive_multi_agent': 20, 'fixed_multi_agent': 20, 'llm_direct': 20, 'single_agent': 20}`
- provider: `vectorengine_openai_compatible`
- model: `gpt-5-mini`
- max_tokens: `4096`
- timeout_seconds: `120`
- hard_timeout_seconds: `600`
- llm_call_count: `90`
- llm_calls_by_method: `{'adaptive_multi_agent': 25, 'fixed_multi_agent': 25, 'llm_direct': 20, 'single_agent': 20}`
- tool_calls_by_method: `{'adaptive_multi_agent': 21, 'fixed_multi_agent': 21, 'llm_direct': 0, 'single_agent': 24}`
- agent_runs_by_method: `{'adaptive_multi_agent': 25, 'fixed_multi_agent': 25, 'llm_direct': 0, 'single_agent': 14}`
- mock_call_count: `0`
- fallback_call_count: `0`
- failed_llm_call_count: `1`
- retry_error_count: `13`
- hard_timeout_triggered_count: `0`

## Gate checks

| check | passed |
|---|---:|
| not_skipped | `True` |
| expected_result_count | `True` |
| all_four_methods_present | `True` |
| method_grid_complete | `True` |
| all_results_completed | `True` |
| trace_count_matches_results | `True` |
| llm_calls_recorded | `True` |
| llm_calls_cover_all_methods | `True` |
| m0_zero_tool_calls | `True` |
| m1_m2_m3_have_agent_or_tool_evidence | `True` |
| no_mock_calls | `True` |
| no_fallback_calls | `True` |
| no_hard_timeout | `True` |
| provider_recorded | `True` |
| token_usage_recorded | `True` |
| latency_recorded | `True` |
| cost_accounting_recorded | `True` |
| no_length_finish_reason | `True` |

## Warnings

- `failed_llm_calls_recorded` count=`1`: At least one internal LLM call failed after retries, but Task E treats this as a provider-stability warning when the result grid has no failed result and no hard timeout.
- `llm_retry_errors_recorded` count=`13`: Retryable API errors or network timeouts occurred and were recorded in trace evidence.

## Artifacts

| artifact | path |
|---|---|
| benchmark | `experiments/results/task_e_four_method_real_api/task_e_four_method_real_api_final3_20260821T123500Z/task_e_four_method_real_api_20_benchmark.json` |
| benchmark_results_json | `experiments/results/task_e_four_method_real_api/task_e_four_method_real_api_final3_20260821T123500Z/benchmark_results.json` |
| benchmark_results_csv | `experiments/results/task_e_four_method_real_api/task_e_four_method_real_api_final3_20260821T123500Z/benchmark_results.csv` |
| evaluation_summary | `experiments/results/task_e_four_method_real_api/task_e_four_method_real_api_final3_20260821T123500Z/evaluation_summary.json` |
| paper_tables | `experiments/results/task_e_four_method_real_api/task_e_four_method_real_api_final3_20260821T123500Z/paper_tables.md` |
| manifest | `experiments/results/task_e_four_method_real_api/task_e_four_method_real_api_final3_20260821T123500Z/experiment_manifest.json` |
| checkpoint_json | `experiments/results/task_e_four_method_real_api/task_e_four_method_real_api_final3_20260821T123500Z/benchmark_results.checkpoint.json` |
| checkpoint_csv | `experiments/results/task_e_four_method_real_api/task_e_four_method_real_api_final3_20260821T123500Z/benchmark_results.checkpoint.csv` |
| resume_state | `experiments/results/task_e_four_method_real_api/task_e_four_method_real_api_final3_20260821T123500Z/benchmark_resume_state.json` |
| traces | `experiments/results/task_e_four_method_real_api/task_e_four_method_real_api_final3_20260821T123500Z/traces` |
| report_json | `experiments/results/task_e_four_method_real_api/task_e_four_method_real_api_final3_20260821T123500Z/task_e_four_method_real_api_report.json` |
| report_md | `experiments/results/task_e_four_method_real_api/task_e_four_method_real_api_final3_20260821T123500Z/task_e_four_method_real_api_report.md` |
