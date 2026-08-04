# Day 7 M3-no-decision-normalizer 消融报告

## 结论

- status: `passed`
- run_id: `day7_m3_no_normalizer_gpt5mini_final_20260803T1515CST`
- run_dir: `experiments/results/day7_m3_ablation/day7_m3_no_normalizer_gpt5mini_final_20260803T1515CST`
- result_count: `26`
- trace_count: `26`
- deterministic_normalizer_count: `0`
- normalizer_skipped_count: `21`
- invalid_llm_decision_count: `21`
- runtime_max_tokens_values: `[4096]`
- failed_checks: `[]`

## 检查项

| Check | Passed |
|---|---:|
| run_dir_exists | `True` |
| core_artifacts_saved | `True` |
| single_expected_method_recorded | `True` |
| result_count_matches_expected_turns | `True` |
| method_count_matches_expected_turns | `True` |
| no_unexpected_methods | `True` |
| trace_count_matches_expected_turns | `True` |
| manifest_decision_normalizer_disabled | `True` |
| agent_outputs_do_not_enable_normalizer | `True` |
| deterministic_normalizer_not_used | `True` |
| normalizer_skip_audit_present | `True` |
| runtime_max_tokens_matches_protocol | `True` |
| no_mock_llm | `True` |
| no_llm_fallback | `True` |
| no_cache_hit | `True` |

## 论文口径

该消融只改变一个因素：关闭 deterministic Agent decision normalizer。如果 Agent 的 LLM 决策为空、非严格 JSON 或不满足 schema，系统不再补全，而是把错误保留到实验结果中。
