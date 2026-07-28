# Paper Result Tables

## Method-level results

| Method | Cases | STSR | HCSR | Agent F1 | Tool F1 | Latency ms | Agent calls | Tool calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 8 | 0.25 | 0.5278 | 0.25 | 0.25 | 64.0725 | 0.0 | 0.0 |
| M1 Single Agent | 8 | 0.875 | 0.9815 | 0.25 | 1.0 | 64.075 | 0.75 | 1.125 |
| M2 Fixed Multi-Agent | 8 | 0.875 | 0.9815 | 1.0 | 1.0 | 64.3037 | 1.5 | 1.125 |
| M3 Proposed | 8 | 0.875 | 0.9815 | 1.0 | 1.0 | 65.7725 | 1.5 | 1.125 |

## Agent/tool diagnostics

| Method | Agent exact | Agent coverage | Extra agents | Dup agents | Plan=Actual agents | Agent success | Tool exact | Tool coverage | Extra tools | Dup tools | Forbidden tools | Tool success |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 0.25 | 0.25 | 0.0 | 0.0 | 1.0 |  | 0.25 | 0.25 | 0.0 | 0.0 | 0.0 |  |
| M1 Single Agent | 0.25 | 0.25 | 0.75 | 0.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 0.0 | 1.0 |
| M2 Fixed Multi-Agent | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 0.0 | 1.0 |
| M3 Proposed | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 0.0 | 1.0 |

## Token and cost

| Method | Tokens/case | Cost/case | Cost/success | Successful cases |
|---|---:|---:|---:|---:|
| M0 Direct LLM | 0.0 |  |  | 2.0 |
| M1 Single Agent | 0.0 |  |  | 7.0 |
| M2 Fixed Multi-Agent | 0.0 |  |  | 7.0 |
| M3 Proposed | 0.0 |  |  | 7.0 |

## Paired M3 vs M2 statistics

| Metric | Pairs | M3 mean | M2 mean | Delta mean | Delta median | Delta IQR | 95% CI | Test | p-value |
|---|---:|---:|---:|---:|---:|---|---|---|---:|
| stsr | 8 | 0.875 | 0.875 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| evaluation_hcsr | 6 | 0.9815 | 0.9815 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| agent_selection_f1 | 8 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| tool_selection_f1 | 8 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| agent_set_exact_match | 8 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| necessary_agent_coverage | 8 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| planned_actual_agent_consistency | 8 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| agent_execution_success_rate | 6 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| tool_set_exact_match | 8 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| necessary_tool_coverage | 8 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| planned_actual_tool_consistency | 8 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| tool_call_success_rate | 6 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| total_tokens | 8 | 0.0 | 0.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| estimated_cost | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| latency_ms | 8 | 65.7725 | 64.3037 | 1.4688 | 1.05 | [0.22, 3.3075] | [-1.195, 4.0262] | Wilcoxon | 0.1484 |
| agent_call_count | 8 | 1.5 | 1.5 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| tool_call_count | 8 | 1.125 | 1.125 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
