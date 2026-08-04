# Paper Result Tables

## Method-level results

| Method | Cases | STSR | HCSR | Agent F1 | Tool F1 | Latency ms | Agent calls | Tool calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 8 | 0.0 | 0.0 | 0.25 | 0.25 | 14088.1588 | 0.0 | 0.0 |
| M1 Single Agent | 8 | 0.0 | 0.5873 | 0.0 | 0.8708 | 21847.5163 | 1.0 | 1.625 |
| M2 Fixed Multi-Agent | 8 | 0.0 | 0.5179 | 0.6655 | 0.5792 | 27592.2075 | 1.25 | 1.25 |
| M3 Proposed | 8 | 0.0 | 0.4123 | 0.6125 | 0.5583 | 20111.995 | 0.875 | 0.875 |

## Agent/tool diagnostics

| Method | Agent exact | Agent coverage | Extra agents | Dup agents | Plan=Actual agents | Agent success | Tool exact | Tool coverage | Extra tools | Dup tools | Forbidden tools | Tool success |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 0.25 | 0.25 | 0.0 | 0.0 | 1.0 |  | 0.25 | 0.25 | 0.0 | 0.0 | 0.0 |  |
| M1 Single Agent | 0.0 | 0.0 | 1.0 | 0.0 | 1.0 | 0.125 | 0.625 | 1.0 | 0.5 | 0.0 | 0.0 | 1.0 |
| M2 Fixed Multi-Agent | 0.375 | 0.875 | 1.125 | 0.0 | 1.0 | 0.0 | 0.25 | 0.6458 | 0.625 | 0.0 | 0.0 | 1.0 |
| M3 Proposed | 0.5 | 0.6667 | 0.5 | 0.0 | 1.0 | 0.0 | 0.375 | 0.5208 | 0.375 | 0.0 | 0.0 | 1.0 |

## Token and cost

| Method | LLM calls | Prompt tokens | Completion tokens | Tokens/case | Cost/case | Standardized cost/case | Actual cost/case | Cost/success | Successful cases |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 1.0 | 889.875 | 963.75 | 1853.625 | 0.0 | 0.0 |  |  | 0.0 |
| M1 Single Agent | 2.0 | 5380.625 | 1266.5 | 6647.125 | 0.0 | 0.0 |  |  | 0.0 |
| M2 Fixed Multi-Agent | 1.875 | 4162.6 | 2986.2 | 4468.0 | 0.0 | 0.0 |  |  | 0.0 |
| M3 Proposed | 1.5 | 3541.2 | 2426.2 | 3729.625 | 0.0 | 0.0 |  |  | 0.0 |

## Multi-turn scenario costs

| Method | Scenarios | Target turn incremental LLM calls | Target turn incremental tokens | Target turn incremental tools | Scenario total LLM calls | Scenario total tokens | Scenario total tools | Scenario total latency ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 2 | 1.0 | 2914.5 | 0.0 | 2.0 | 4527.5 | 0.0 | 27857.66 |
| M1 Single Agent | 2 | 2.0 | 10191.5 | 3.0 | 4.0 | 17257.5 | 6.0 | 51236.16 |
| M2 Fixed Multi-Agent | 2 | 3.0 | 7247.0 | 2.0 | 6.0 | 14037.5 | 4.0 | 110635.905 |
| M3 Proposed | 2 | 2.0 | 5773.5 | 1.0 | 5.0 | 12564.0 | 3.0 | 79007.515 |

## Paired M3 vs M2 statistics

| Metric | Pairs | M3 mean | M2 mean | Delta mean | Delta median | Delta IQR | 95% CI | Test | p-value |
|---|---:|---:|---:|---:|---:|---|---|---|---:|
| stsr | 8 | 0.0 | 0.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| evaluation_hcsr | 6 | 0.4123 | 0.5179 | -0.1055 | 0.0 | [-0.0194, 0.0] | [-0.3079, 0.0] | Wilcoxon | 0.5 |
| agent_selection_f1 | 8 | 0.6125 | 0.6655 | -0.053 | 0.0 | [-0.0893, 0.0] | [-0.2946, 0.1804] | Wilcoxon | 0.75 |
| tool_selection_f1 | 8 | 0.5583 | 0.5792 | -0.0208 | 0.0 | [0.0, 0.0417] | [-0.2292, 0.1458] | Wilcoxon | 1.0 |
| agent_set_exact_match | 8 | 0.5 | 0.375 | 0.125 | 0.0 | [0.0, 0.0] | [0.0, 0.375] | McNemar | 1.0 |
| necessary_agent_coverage | 8 | 0.6667 | 0.875 | -0.2083 | 0.0 | [-0.1667, 0.0] | [-0.5, 0.0] | Wilcoxon | 0.5 |
| planned_actual_agent_consistency | 8 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| agent_execution_success_rate | 5 | 0.0 | 0.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| tool_set_exact_match | 8 | 0.375 | 0.25 | 0.125 | 0.0 | [0.0, 0.0] | [0.0, 0.375] | McNemar | 1.0 |
| necessary_tool_coverage | 8 | 0.5208 | 0.6458 | -0.125 | 0.0 | [0.0, 0.0] | [-0.375, 0.0] | Wilcoxon | 1.0 |
| planned_actual_tool_consistency | 8 | 0.75 | 0.375 | 0.375 | 0.0 | [0.0, 1.0] | [0.0, 0.75] | McNemar | 0.25 |
| tool_call_success_rate | 5 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| total_tokens | 8 | 3729.625 | 4468.0 | -738.375 | 0.0 | [-1399.25, 0.0] | [-1549.625, 0.0] | Wilcoxon | 0.25 |
| estimated_cost | 5 | 0.0 | 0.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| standardized_estimated_cost | 5 | 0.0 | 0.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| actual_cost | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| llm_call_count | 8 | 1.5 | 1.875 | -0.375 | 0.0 | [-1.0, 0.0] | [-0.75, -0.125] | Wilcoxon | 0.25 |
| agent_llm_call_count | 5 | 1.4 | 2.0 | -0.6 | -1.0 | [-1.0, 0.0] | [-1.0, -0.2] | Wilcoxon | 0.25 |
| api_call_count | 8 | 0.0 | 0.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| prompt_tokens | 5 | 3541.2 | 4162.6 | -621.4 | -301.0 | [-598.0, 0.0] | [-1444.4, -60.2] | Wilcoxon | 0.25 |
| completion_tokens | 5 | 2426.2 | 2986.2 | -560.0 | -942.0 | [-1024.0, 0.0] | [-1007.6, -90.8] | Wilcoxon | 0.25 |
| agent_prompt_tokens | 5 | 1578.4 | 2137.6 | -559.2 | -598.0 | [-1028.0, 0.0] | [-970.4, -119.6] | Wilcoxon | 0.25 |
| agent_completion_tokens | 5 | 1433.6 | 2048.0 | -614.4 | -1024.0 | [-1024.0, 0.0] | [-1024.0, -204.8] | Wilcoxon | 0.25 |
| agent_total_tokens | 5 | 3012.0 | 4185.6 | -1173.6 | -1622.0 | [-2052.0, 0.0] | [-2022.8, -324.4] | Wilcoxon | 0.25 |
| llm_total_duration_ms | 5 | 31997.79 | 43956.96 | -11959.17 | -14703.27 | [-20016.72, -298.59] | [-23360.478, -557.862] | Wilcoxon | 0.1875 |
| agent_total_duration_ms | 5 | 18191.388 | 30324.676 | -12133.288 | -14849.77 | [-19228.33, -2558.61] | [-22829.5755, -531.266] | Wilcoxon | 0.1875 |
| tool_total_duration_ms | 5 | 1.998 | 1.654 | 0.344 | -1.0 | [-1.71, 0.0] | [-1.688, 3.462] | Wilcoxon | 0.875 |
| api_total_duration_ms | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| latency_ms | 8 | 20111.995 | 27592.2075 | -7480.2125 | -159.96 | [-16033.3175, 5.625] | [-15978.6856, 500.3238] | Wilcoxon | 0.3828 |
| agent_call_count | 8 | 0.875 | 1.25 | -0.375 | 0.0 | [-1.0, 0.0] | [-0.75, -0.125] | Wilcoxon | 0.25 |
| tool_call_count | 8 | 0.875 | 1.25 | -0.375 | 0.0 | [-1.0, 0.0] | [-0.75, -0.125] | Wilcoxon | 0.25 |
