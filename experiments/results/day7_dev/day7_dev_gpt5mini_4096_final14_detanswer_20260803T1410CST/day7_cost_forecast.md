# Day 7 成本预测与模型冻结报告

## 结论

- status: `passed`
- freeze_status: `frozen_for_cost_and_runtime`
- run_id: `day7_dev_gpt5mini_4096_final14_detanswer_20260803T1410CST`
- 冻结模型: `gpt-5-mini`
- 冻结参数: temperature=`0.0`, max_tokens=`4096`, timeout=`60`, retry_max_attempts=`3`, reasoning_effort=`minimal`
- 开发集真实估算费用: `4.468857 CNY` / `0.612172 USD`
- 正式主实验外推费用: `22.344285 CNY` / `3.060861 USD`
- 两周保守总费用: `34.410199 CNY`
- failed_checks: `[]`
- quality_advisory_failed_checks: `[]`
- quality_rerun_recommended: `False`

说明：这是成本与运行参数冻结证据，不代表方法质量已经达到投稿水平；开发集质量问题会保留在 quality_advisory 中。

## 质量边界

- development_gate_status: `passed`
- cost_freeze_independent_from_quality_gate: `True`
- quality_rerun_recommended: `False`
- advisory_failed_checks: `[]`

## Trace 成本证据

- trace_standardized_cost_sum: `0.612172`
- trace_standardized_cost_positive_call_count: `215`
- trace_token_positive_call_count: `215`
- trace_env_or_zero_default_call_count: `0`
- completion_token_cap_hit_count: `0`
- completion_token_cap_hit_rate: `0.0`
- empty_and_token_capped_call_count: `0`
- actual_cost_statuses: `['not_reported_by_provider']`

## 价格快照

| 字段 | 值 |
|---|---:|
| source | `https://api.vectorengine.ai/pricing` |
| snapshot_date | `2026-08-01` |
| input USD / 1M tokens | 0.25 |
| output USD / 1M tokens | 2 |
| USD→CNY 汇率 | 7.3 |

## 四种方法平均成本

| Method | Rows | LLM calls | Avg input tok | Avg output tok | Avg total tok | Avg cost CNY | Avg latency ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| llm_direct | 26 | 26 | 1606.7692 | 1781.5 | 3388.2692 | 0.028942 | 16194.0381 |
| single_agent | 26 | 46 | 5870.9615 | 854.4615 | 6725.4231 | 0.02319 | 34557.4154 |
| fixed_multi_agent | 26 | 88 | 7800.4615 | 3949.5385 | 11750.0 | 0.071899 | 43223.395 |
| adaptive_multi_agent | 26 | 56 | 4595.0769 | 2702.8846 | 7297.9615 | 0.047848 | 31441.5408 |

## 八类任务平均成本

| Task type | Rows | Avg input tok | Avg output tok | Avg total tok | Avg cost CNY | Avg latency ms |
|---|---:|---:|---:|---:|---:|---:|
| attraction_recommendation | 8 | 2664.625 | 1268.0 | 3932.625 | 0.023376 | 15000.675 |
| budget_query | 12 | 4120.4167 | 1885.0833 | 6005.5 | 0.035042 | 21748.7283 |
| clarification | 8 | 446.125 | 495.125 | 941.25 | 0.008043 | 4488.67 |
| general_chat | 8 | 431.375 | 254.0 | 685.375 | 0.004496 | 3957.4762 |
| partial_replan | 12 | 8986.6667 | 2749.6667 | 11736.3333 | 0.056546 | 29835.9758 |
| trip_planning | 40 | 6187.275 | 3496.375 | 9683.65 | 0.062339 | 53405.6565 |
| weather_adjustment | 8 | 7773.25 | 2628.875 | 10402.125 | 0.052568 | 26763.3438 |
| weather_query | 8 | 2675.75 | 1107.25 | 3783.0 | 0.021049 | 12987.7613 |

## 预算门禁

| 项目 | 估算 CNY | 阈值 CNY | Passed |
|---|---:|---:|---:|
| 开发试跑（含重试储备） | 4.915743 | 15 | `True` |
| 正式主实验（含重试储备） | 24.578714 | 75 | `True` |
| 两周总成本 | 34.410199 | 150 | `True` |

## 重试与网络储备

- llm_call_count: `216`
- retry_count: `1.0`
- retry_error_count: `2.0`
- observed_retry_overhead_rate: `0.0046`
- reserve_rate_used: `0.1`

## 冻结检查

| Check | Passed |
|---|---:|
| dev_gate_passed | `True` |
| expected_dev_scope_matches | `True` |
| raw_result_count_matches | `True` |
| method_count_complete | `True` |
| task_type_count_complete | `True` |
| token_fields_complete | `True` |
| nonzero_price_snapshot | `True` |
| trace_standardized_cost_nonzero | `True` |
| trace_price_source_not_zero_default | `True` |
| runtime_consistent | `True` |
| runtime_max_tokens_matches_day7_protocol | `True` |
| deterministic_research_final_answer_recorded | `True` |
| completion_token_cap_hit_rate_below_limit | `True` |
| no_empty_outputs_at_token_cap | `True` |
| no_mock_fallback_cache | `True` |
| dev_budget_within_15_cny | `True` |
| formal_budget_within_75_cny | `True` |
| two_week_budget_within_150_cny | `True` |

## 运行时冻结值

| Field | Manifest value | Observed request values | Consistent |
|---|---:|---:|---:|
| model | `gpt-5-mini` | `['gpt-5-mini']` | `True` |
| temperature | `0.0` | `[0.0]` | `True` |
| max_tokens | `4096` | `[4096]` | `True` |
| timeout_seconds | `60` | `[60]` | `True` |
| retry_max_attempts | `3` | `[3]` | `True` |
| reasoning_effort | `minimal` | `['minimal']` | `True` |

## 实验控制冻结值

- deterministic_research_final_answer: `True`
- final_answer_generation_mode: `deterministic_research_evidence_renderer`
