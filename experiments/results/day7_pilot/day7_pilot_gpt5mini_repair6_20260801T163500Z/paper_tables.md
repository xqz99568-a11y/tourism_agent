# Paper Result Tables

## Method-level results

| Method | Cases | STSR | HCSR | Agent F1 | Tool F1 | Latency ms | Agent calls | Tool calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 8 | 0.125 | 0.3148 | 0.25 | 0.25 | 12168.3063 | 0.0 | 0.0 |
| M1 Single Agent | 8 | 0.125 | 0.5926 | 0.0 | 0.5 | 17676.0775 | 1.0 | 0.5 |
| M2 Fixed Multi-Agent | 8 | 0.375 | 0.9583 | 0.7155 | 0.725 | 35130.5412 | 3.0 | 2.25 |
| M3 Proposed | 8 | 1.0 | 1.0 | 1.0 | 1.0 | 23548.2225 | 1.5 | 1.125 |

## Agent/tool diagnostics

| Method | Agent exact | Agent coverage | Extra agents | Dup agents | Plan=Actual agents | Agent success | Tool exact | Tool coverage | Extra tools | Dup tools | Forbidden tools | Tool success |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 0.25 | 0.25 | 0.0 | 0.0 | 1.0 |  | 0.25 | 0.25 | 0.0 | 0.0 | 0.0 |  |
| M1 Single Agent | 0.0 | 0.0 | 1.0 | 0.0 | 1.0 | 0.75 | 0.5 | 0.5 | 0.0 | 0.0 | 0.0 | 1.0 |
| M2 Fixed Multi-Agent | 0.375 | 1.0 | 1.5 | 0.0 | 1.0 | 1.0 | 0.375 | 1.0 | 1.125 | 0.0 | 0.0 | 1.0 |
| M3 Proposed | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 0.0 | 1.0 |

## Token and cost

| Method | LLM calls | Prompt tokens | Completion tokens | Tokens/case | Cost/case | Standardized cost/case | Actual cost/case | Cost/success | Successful cases |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 1.0 | 1591.625 | 1329.875 | 2921.5 | 0.0 | 0.0 |  | 0.0 | 1.0 |
| M1 Single Agent | 1.5 | 3666.75 | 1943.25 | 5610.0 | 0.0 | 0.0 |  | 0.0 | 1.0 |
| M2 Fixed Multi-Agent | 3.875 | 15321.4286 | 4361.1429 | 17222.25 | 0.0 | 0.0 |  | 0.0 | 3.0 |
| M3 Proposed | 2.375 | 8648.8571 | 2908.0 | 10112.25 | 0.0 | 0.0 |  | 0.0 | 8.0 |

## Multi-turn scenario costs

| Method | Scenarios | Target turn incremental LLM calls | Target turn incremental tokens | Target turn incremental tools | Scenario total LLM calls | Scenario total tokens | Scenario total tools | Scenario total latency ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 2 | 1.0 | 7200.0 | 0.0 | 2.0 | 9795.5 | 0.0 | 38525.405 |
| M1 Single Agent | 2 | 1.0 | 8043.0 | 0.0 | 4.0 | 18734.0 | 2.0 | 57858.49 |
| M2 Fixed Multi-Agent | 2 | 5.0 | 24506.5 | 3.0 | 10.0 | 52550.5 | 6.0 | 120396.65 |
| M3 Proposed | 2 | 3.5 | 17675.0 | 1.5 | 8.5 | 42631.5 | 4.5 | 100886.985 |

## Paired M3 vs M2 statistics

| Metric | Pairs | M3 mean | M2 mean | Delta mean | Delta median | Delta IQR | 95% CI | Test | p-value |
|---|---:|---:|---:|---:|---:|---|---|---|---:|
| stsr | 8 | 1.0 | 0.375 | 0.625 | 1.0 | [0.0, 1.0] | [0.25, 0.875] | McNemar | 0.0625 |
| evaluation_hcsr | 6 | 1.0 | 0.9583 | 0.0417 | 0.0 | [0.0, 0.0] | [0.0, 0.125] | Wilcoxon | 1.0 |
| agent_selection_f1 | 8 | 1.0 | 0.7155 | 0.2845 | 0.2381 | [0.0, 0.6] | [0.1107, 0.4583] | Wilcoxon | 0.0625 |
| tool_selection_f1 | 8 | 1.0 | 0.725 | 0.275 | 0.35 | [0.0, 0.5] | [0.125, 0.4375] | Wilcoxon | 0.0625 |
| agent_set_exact_match | 8 | 1.0 | 0.375 | 0.625 | 1.0 | [0.0, 1.0] | [0.25, 0.875] | McNemar | 0.0625 |
| necessary_agent_coverage | 8 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| planned_actual_agent_consistency | 8 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| agent_execution_success_rate | 6 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| tool_set_exact_match | 8 | 1.0 | 0.375 | 0.625 | 1.0 | [0.0, 1.0] | [0.25, 1.0] | McNemar | 0.0625 |
| necessary_tool_coverage | 8 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| planned_actual_tool_consistency | 8 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| tool_call_success_rate | 6 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| total_tokens | 8 | 10112.25 | 17222.25 | -7110.0 | -6831.5 | [-13885.0, 0.0] | [-12489.5906, -1907.4063] | Wilcoxon | 0.0625 |
| estimated_cost | 7 | 0.0 | 0.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| standardized_estimated_cost | 7 | 0.0 | 0.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| actual_cost | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| llm_call_count | 8 | 2.375 | 3.875 | -1.5 | -1.5 | [-3.0, 0.0] | [-2.375, -0.625] | Wilcoxon | 0.0625 |
| agent_llm_call_count | 6 | 2.0 | 4.0 | -2.0 | -2.5 | [-3.0, -1.25] | [-2.8333, -1.0] | Wilcoxon | 0.0625 |
| api_call_count | 8 | 0.0 | 0.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| prompt_tokens | 7 | 8648.8571 | 15321.4286 | -6672.5714 | -5655.0 | [-12532.5, -2750.5] | [-11315.0, -1692.1893] | Wilcoxon | 0.0625 |
| completion_tokens | 7 | 2908.0 | 4361.1429 | -1453.1429 | -1750.0 | [-1963.5, -378.5] | [-2562.8571, -466.7036] | Wilcoxon | 0.0625 |
| agent_prompt_tokens | 6 | 4650.3333 | 9327.8333 | -4677.5 | -5016.5 | [-7403.0, -3638.75] | [-7424.2625, -1670.9042] | Wilcoxon | 0.0625 |
| agent_completion_tokens | 6 | 2531.5 | 4249.1667 | -1717.6667 | -1819.0 | [-2036.5, -1210.0] | [-2772.0, -675.3167] | Wilcoxon | 0.0625 |
| agent_total_tokens | 6 | 7181.8333 | 13577.0 | -6395.1667 | -6835.5 | [-9439.5, -4848.75] | [-10106.0, -2333.0] | Wilcoxon | 0.0625 |
| llm_total_duration_ms | 7 | 26761.0143 | 39984.8171 | -13223.8029 | -12102.28 | [-21524.695, -1437.13] | [-23646.2135, -3520.0714] | Wilcoxon | 0.0781 |
| agent_total_duration_ms | 6 | 21876.2817 | 37162.1167 | -15285.835 | -15499.69 | [-21415.185, -7518.755] | [-26259.91, -5014.357] | Wilcoxon | 0.0625 |
| tool_total_duration_ms | 6 | 0.8967 | 1.9783 | -1.0817 | -1.045 | [-1.6525, -0.445] | [-1.7974, -0.3599] | Wilcoxon | 0.0625 |
| api_total_duration_ms | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| latency_ms | 8 | 23548.2225 | 35130.5413 | -11582.3188 | -7373.66 | [-20468.29, -184.14] | [-21064.0696, -2670.2898] | Wilcoxon | 0.0547 |
| agent_call_count | 8 | 1.5 | 3.0 | -1.5 | -1.5 | [-3.0, 0.0] | [-2.375, -0.625] | Wilcoxon | 0.0625 |
| tool_call_count | 8 | 1.125 | 2.25 | -1.125 | -1.5 | [-2.0, 0.0] | [-1.75, -0.5] | Wilcoxon | 0.0625 |
