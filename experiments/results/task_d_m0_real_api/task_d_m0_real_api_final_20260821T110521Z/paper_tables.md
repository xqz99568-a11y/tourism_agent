# Paper Result Tables

## Method-level results

| Method | Cases | STSR | HCSR | BPCR | Agent F1 | Tool F1 | Latency ms | Agent calls | Tool calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 20 | 0.05 | 0.1886 | 0.0139 | 0.3 | 0.3 | 14924.4835 | 0.0 | 0.0 |

## Agent/tool diagnostics

| Method | Agent exact | Agent coverage | Extra agents | Dup agents | Plan=Actual agents | Agent success | Tool exact | Tool coverage | Extra tools | Dup tools | Forbidden tools | Tool success |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 0.3 | 0.3 | 0.0 | 0.0 | 1.0 |  | 0.3 | 0.3 | 0.0 | 0.0 | 0.0 |  |

## Token and cost

| Method | LLM calls | Prompt tokens | Completion tokens | Tokens/case | Cost/case | Standardized cost/case | Actual cost/case | Cost/success | Successful cases |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 1.0 | 881.15 | 913.5 | 1794.65 | 0.002 | 0.002 |  | 0.0409 | 1.0 |

## Multi-turn scenario costs

| Method | Scenarios | Target turn incremental LLM calls | Target turn incremental tokens | Target turn incremental tools | Scenario total LLM calls | Scenario total tokens | Scenario total tools | Scenario total latency ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 0 |  |  |  |  |  |  |  |

## Paired M3 vs M2 statistics

| Metric | Pairs | M3 mean | M2 mean | Delta mean | Delta median | Delta IQR | 95% CI | Test | p-value |
|---|---:|---:|---:|---:|---:|---|---|---|---:|
| stsr | 0 |  |  |  |  |  |  | McNemar | 1.0 |
| evaluation_hcsr | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| itcsr | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| bpcr | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
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
