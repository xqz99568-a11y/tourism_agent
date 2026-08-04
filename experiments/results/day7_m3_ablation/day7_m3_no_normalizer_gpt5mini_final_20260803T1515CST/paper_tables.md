# Paper Result Tables

## Method-level results

| Method | Cases | STSR | HCSR | Agent F1 | Tool F1 | Latency ms | Agent calls | Tool calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| M3 Proposed | 20 | 0.5 | 0.8984 | 0.9157 | 0.8817 | 25176.0905 | 1.7 | 1.5 |

## Agent/tool diagnostics

| Method | Agent exact | Agent coverage | Extra agents | Dup agents | Plan=Actual agents | Agent success | Tool exact | Tool coverage | Extra tools | Dup tools | Forbidden tools | Tool success |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M3 Proposed | 0.75 | 0.95 | 0.4 | 0.0 | 1.0 | 0.6042 | 0.75 | 0.925 | 0.3 | 0.0 | 0.0 | 1.0 |

## Token and cost

| Method | LLM calls | Prompt tokens | Completion tokens | Tokens/case | Cost/case | Standardized cost/case | Actual cost/case | Cost/success | Successful cases |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M3 Proposed | 1.7 | 4144.75 | 2580.25 | 5380.0 | 0.0062 | 0.0062 |  | 0.0099 | 10.0 |

## Multi-turn scenario costs

| Method | Scenarios | Target turn incremental LLM calls | Target turn incremental tokens | Target turn incremental tools | Scenario total LLM calls | Scenario total tokens | Scenario total tools | Scenario total latency ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| M3 Proposed | 6 | 2.1667 | 5946.6667 | 2.0 | 5.1667 | 16304.1667 | 4.5 | 78927.7667 |

## Paired M3 vs M2 statistics

| Metric | Pairs | M3 mean | M2 mean | Delta mean | Delta median | Delta IQR | 95% CI | Test | p-value |
|---|---:|---:|---:|---:|---:|---|---|---|---:|
| stsr | 0 |  |  |  |  |  |  | McNemar | 1.0 |
| evaluation_hcsr | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| agent_selection_f1 | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| tool_selection_f1 | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| agent_set_exact_match | 0 |  |  |  |  |  |  | McNemar | 1.0 |
| necessary_agent_coverage | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| planned_actual_agent_consistency | 0 |  |  |  |  |  |  | McNemar | 1.0 |
| agent_execution_success_rate | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| tool_set_exact_match | 0 |  |  |  |  |  |  | McNemar | 1.0 |
| necessary_tool_coverage | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| planned_actual_tool_consistency | 0 |  |  |  |  |  |  | McNemar | 1.0 |
| tool_call_success_rate | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| total_tokens | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| estimated_cost | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| standardized_estimated_cost | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| actual_cost | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| llm_call_count | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| agent_llm_call_count | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| api_call_count | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| prompt_tokens | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| completion_tokens | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| agent_prompt_tokens | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| agent_completion_tokens | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| agent_total_tokens | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| llm_total_duration_ms | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| agent_total_duration_ms | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| tool_total_duration_ms | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| api_total_duration_ms | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| latency_ms | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| agent_call_count | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| tool_call_count | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
