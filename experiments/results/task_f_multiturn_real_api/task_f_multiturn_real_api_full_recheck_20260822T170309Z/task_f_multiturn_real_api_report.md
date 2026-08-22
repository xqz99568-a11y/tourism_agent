# Task F Multi-Turn Real API Validation Report

- status: `passed`
- run_id: `task_f_multiturn_real_api_full_recheck_20260822T170309Z`
- expected_result_count: `24`
- actual_result_count: `24`
- status_counts: `{'completed': 24}`
- trace_file_count: `24`
- llm_call_count: `76`
- provider_counts: `{'vectorengine_openai_compatible': 76}`
- mock_call_count: `0`
- fallback_call_count: `0`
- hard_timeout_triggered_count: `0`
- m3_expectation_violation_count: `0`
- decision_normalizer_recovery_rate: `0.513158`

## Gate checks

| check | passed |
| --- | --- |
| not_skipped | `True` |
| expected_result_count | `True` |
| m2_m3_methods_only | `True` |
| turn_method_grid_complete | `True` |
| all_results_completed | `True` |
| trace_count_matches_results | `True` |
| llm_calls_recorded | `True` |
| agent_or_tool_evidence_recorded | `True` |
| second_turn_previous_state_present | `True` |
| m2_second_turn_no_reuse | `True` |
| m3_second_turn_reuse_expectations_met | `True` |
| m3_destination_change_invalidates_all | `True` |
| no_mock_calls | `True` |
| no_mock_or_model_fallback | `True` |
| no_hard_timeout | `True` |
| provider_is_vectorengine_openai_compatible | `True` |
| token_usage_recorded | `True` |
| latency_recorded | `True` |
| cost_accounting_recorded | `True` |
| no_length_finish_reason | `True` |

## M3 second-turn reuse audit

- destination_change_invalidation_passed: `True`
- missing_previous_state_count: `0`
- m2_reuse_violation_count: `0`
- m3_expectation_violation_count: `0`
- violations: `[]`

## Decision normalizer diagnostics

- agent_decision_total: `76`
- raw_llm_decision_success_rate: `0.486842`
- decision_normalizer_recovery_count: `39`
- decision_normalizer_recovery_rate: `0.513158`
- recovery_by_method: `{'adaptive_multi_agent': {'total': 38, 'raw_success': 17, 'recovered': 21}, 'fixed_multi_agent': {'total': 38, 'raw_success': 20, 'recovered': 18}}`
- recovery_by_agent: `{'attraction': {'total': 16, 'raw_success': 2, 'recovered': 14}, 'budget': {'total': 24, 'raw_success': 22, 'recovered': 2}, 'itinerary': {'total': 22, 'raw_success': 0, 'recovered': 22}, 'weather': {'total': 14, 'raw_success': 13, 'recovered': 1}}`
