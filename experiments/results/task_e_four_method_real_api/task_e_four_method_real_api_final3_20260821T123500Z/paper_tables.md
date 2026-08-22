# Paper Result Tables

## Method-level results

| Method | Cases | STSR | HCSR | BPCR | Agent F1 | Tool F1 | Latency ms | Agent calls | Tool calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 20 | 0.05 | 0.1844 | 0.0139 | 0.3 | 0.3 | 13978.8115 | 0.0 | 0.0 |
| M1 Single Agent | 20 | 0.5 | 0.8812 | 0.8362 | 0.3 | 0.965 | 16059.6035 | 0.7 | 1.2 |
| M2 Fixed Template Multi-Agent | 20 | 0.8 | 0.9726 | 0.9406 | 1.0 | 1.0 | 23004.481 | 1.25 | 1.05 |
| M3 Proposed | 20 | 0.8 | 0.9726 | 0.9406 | 1.0 | 1.0 | 35821.923 | 1.25 | 1.05 |

## Agent/tool diagnostics

| Method | Agent exact | Agent coverage | Extra agents | Dup agents | Plan=Actual agents | Agent success | Tool exact | Tool coverage | Extra tools | Dup tools | Forbidden tools | Tool success |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 0.3 | 0.3 | 0.0 | 0.0 | 1.0 |  | 0.3 | 0.3 | 0.0 | 0.0 | 0.0 |  |
| M1 Single Agent | 0.3 | 0.3 | 0.7 | 0.0 | 1.0 | 1.0 | 0.9 | 1.0 | 0.15 | 0.0 | 0.15 | 1.0 |
| M2 Fixed Template Multi-Agent | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 0.0 | 1.0 |
| M3 Proposed | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 0.0 | 1.0 |

## Token and cost

| Method | LLM calls | Prompt tokens | Completion tokens | Tokens/case | Cost/case | Standardized cost/case | Actual cost/case | Cost/success | Successful cases |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 1.0 | 881.15 | 1034.45 | 1915.6 | 0.0023 | 0.0023 |  | 0.0458 | 1.0 |
| M1 Single Agent | 1.0 | 3963.8571 | 107.2143 | 2849.75 | 0.0012 | 0.0012 |  | 0.0017 | 10.0 |
| M2 Fixed Template Multi-Agent | 1.25 | 4882.8571 | 2040.2143 | 4846.15 | 0.0053 | 0.0053 |  | 0.0046 | 16.0 |
| M3 Proposed | 1.25 | 4402.2143 | 1971.6429 | 4461.7 | 0.005 | 0.005 |  | 0.0044 | 16.0 |

## Multi-turn scenario costs

| Method | Scenarios | Target turn incremental LLM calls | Target turn incremental tokens | Target turn incremental tools | Scenario total LLM calls | Scenario total tokens | Scenario total tools | Scenario total latency ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 Direct LLM | 0 |  |  |  |  |  |  |  |
| M1 Single Agent | 0 |  |  |  |  |  |  |  |
| M2 Fixed Template Multi-Agent | 0 |  |  |  |  |  |  |  |
| M3 Proposed | 0 |  |  |  |  |  |  |  |

## Paired M3 vs M2 statistics

| Metric | Pairs | M3 mean | M2 mean | Delta mean | Delta median | Delta IQR | 95% CI | Test | p-value |
|---|---:|---:|---:|---:|---:|---|---|---|---:|
| stsr | 20 | 0.8 | 0.8 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| evaluation_hcsr | 14 | 0.9726 | 0.9726 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| itcsr | 8 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| bpcr | 8 | 0.9406 | 0.9406 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| agent_selection_f1 | 20 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| tool_selection_f1 | 20 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| agent_set_exact_match | 20 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| necessary_agent_coverage | 20 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| planned_actual_agent_consistency | 20 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| agent_execution_success_rate | 14 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| tool_set_exact_match | 20 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| necessary_tool_coverage | 20 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| planned_actual_tool_consistency | 20 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | McNemar | 1.0 |
| tool_call_success_rate | 14 | 1.0 | 1.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| total_tokens | 20 | 4461.7 | 4846.15 | -384.45 | 0.0 | [-43.25, 113.0] | [-1449.8463, 338.815] | Wilcoxon | 0.7034 |
| estimated_cost | 14 | 0.005 | 0.0053 | -0.0003 | 0.0002 | [-0.0002, 0.0003] | [-0.0014, 0.0005] | Wilcoxon | 0.364 |
| standardized_estimated_cost | 14 | 0.005 | 0.0053 | -0.0003 | 0.0002 | [-0.0002, 0.0003] | [-0.0014, 0.0005] | Wilcoxon | 0.364 |
| actual_cost | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| llm_call_count | 20 | 1.25 | 1.25 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| agent_llm_call_count | 14 | 1.7857 | 1.7857 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| api_call_count | 20 | 0.0 | 0.0 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| prompt_tokens | 14 | 4402.2143 | 4882.8571 | -480.6429 | 0.0 | [-2.0, 0.0] | [-1550.8625, 319.4304] | Wilcoxon | 0.1484 |
| completion_tokens | 14 | 1971.6429 | 2040.2143 | -68.5714 | 113.0 | [-63.25, 161.75] | [-527.9125, 249.7393] | Wilcoxon | 0.3258 |
| agent_prompt_tokens | 14 | 4402.2143 | 4882.8571 | -480.6429 | 0.0 | [-2.0, 0.0] | [-1550.7196, 316.5714] | Wilcoxon | 0.1484 |
| agent_completion_tokens | 14 | 1971.6429 | 2040.2143 | -68.5714 | 113.0 | [-63.25, 161.75] | [-517.4393, 250.6679] | Wilcoxon | 0.3258 |
| agent_total_tokens | 14 | 6373.8571 | 6923.0714 | -549.2143 | 110.0 | [-237.5, 141.5] | [-2066.1286, 497.9518] | Wilcoxon | 0.7034 |
| llm_total_duration_ms | 14 | 50881.6593 | 32572.1157 | 18309.5436 | 627.62 | [-1845.4225, 8563.35] | [-2383.6523, 45595.7148] | Wilcoxon | 0.4631 |
| agent_total_duration_ms | 14 | 51026.5721 | 32723.2971 | 18303.275 | 619.59 | [-1843.865, 8565.8975] | [-2199.8421, 43677.3802] | Wilcoxon | 0.4631 |
| tool_total_duration_ms | 14 | 10.2621 | 10.855 | -0.5929 | -0.325 | [-1.0, 0.31] | [-1.3057, 0.0486] | Wilcoxon | 0.1768 |
| api_total_duration_ms | 0 |  |  |  |  |  |  | Wilcoxon | 1.0 |
| latency_ms | 20 | 35821.923 | 23004.481 | 12817.442 | 2.145 | [-1548.015, 2718.9125] | [-1509.7939, 32201.3737] | Wilcoxon | 0.4304 |
| agent_call_count | 20 | 1.25 | 1.25 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
| tool_call_count | 20 | 1.05 | 1.05 | 0.0 | 0.0 | [0.0, 0.0] | [0.0, 0.0] | Wilcoxon | 1.0 |
